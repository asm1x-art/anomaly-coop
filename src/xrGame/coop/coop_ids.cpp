#include "stdafx.h"
#include "coop_ids.h"
#include "coop_net.h"
#include "coop_save.h"
#include "Level.h"
#include "xrServer.h"
#include "ai_space.h"

namespace coop
{
	static const u16 NO_BLOCK = u16(-1);
	static const u32 WAIT_MS = 2000; // for the first block, see acquire_first_block
	// A block hands out the id freed longest ago, so one nearly used up hands out ids freed moments ago, while their
	// objects may still be on their way out of the client: an update of the old object is then read as the new one's
	// (FATAL "Beer from the creator of ..." in xrServer::Process_update, seen after a raid's garrison died). Such a
	// block is used only when no other has this many free ids.
	static const u32 REUSE_MIN_FREE = 32;

	static xr_vector<u16> g_blocks; // leased to us, in grant order
	static bool g_request_pending = false;
	static bool g_server_exhausted = false;
	static u32 g_fallbacks = 0;     // new ids that had to come from the local generator
	static bool g_first_logged = false;
	static bool g_gave_up_waiting = false; // don't stall every spawn if the server didn't answer
	static u32 g_entry_goal = 0;          // a new character's first entry: free ids to hold, then low_reserve again
	static u32 g_next_usage_log = 0;      // Device.dwTimeGlobal of the next "ids taken in the world" line, 0: at once

	// [coop_ids] in gamedata/configs/mod_system_coop.ltx
	struct SIdSettings
	{
		u32 low_reserve = 128;        // ask for another block when fewer free ids than this are left
		u32 new_character_ids = 768;  // a new character's first entry asks for blocks until it has this many free
		u32 usage_log_ms = 300000;    // how often the ids taken in the world go to the log
		u32 usage_warn_percent = 90;  // from this share taken the line is a warning
	};

	static const SIdSettings& settings()
	{
		static SIdSettings s;
		static bool read = false;
		if (!read && pSettings)
		{
			read = true;
			LPCSTR SECTION = "coop_ids";
			if (pSettings->section_exist(SECTION))
			{
				s.low_reserve = READ_IF_EXISTS(pSettings, r_u32, SECTION, "low_reserve", s.low_reserve);
				s.new_character_ids = READ_IF_EXISTS(pSettings, r_u32, SECTION, "new_character_ids", s.new_character_ids);
				s.usage_log_ms = READ_IF_EXISTS(pSettings, r_u32, SECTION, "usage_log_s", s.usage_log_ms / 1000) * 1000;
				s.usage_warn_percent = READ_IF_EXISTS(pSettings, r_u32, SECTION, "usage_warn_percent", s.usage_warn_percent);
			}
		}
		return s;
	}

	// free ids to keep in our blocks: more on a new character's first entry
	static u32 reserve()
	{
		return _max(settings().low_reserve, g_entry_goal);
	}

	static xrServer* local_server()
	{
		return g_pGameLevel ? Level().Server : nullptr;
	}

	static u32 free_in_owned_blocks(const xrServer& server)
	{
		u32 count = 0;
		for (u16 block : g_blocks)
			count += server.free_ids_in_block(block);
		return count;
	}

	static u32 free_in_world(const xrServer& server)
	{
		u32 count = 0;
		for (u32 block = 0; block < xrServer::id_block_count(); ++block)
			count += server.free_ids_in_block(block);
		return count;
	}

	// ids 0..65534: a world whose objects take them all can't make another one
	static void log_id_usage(const xrServer& server, LPCSTR when)
	{
		const u32 all = xrServer::id_block_count() * 256 - 1;
		const u32 taken = all - _min(all, free_in_world(server));
		const bool warn = taken * 100 >= all * settings().usage_warn_percent;
		Msg("%s[coop] ids: %u of %u taken in the world (%.1f%%), %u block(s) leased to us with %u free (%s)",
		    warn ? "! " : "", taken, all, taken * 100.f / all, g_blocks.size(), free_in_owned_blocks(server), when);
	}

	static void send_request(const xrServer& server)
	{
		// our view of free ids per block lets the server pick a block that is actually usable
		NET_Packet P;
		P.w_begin(M_ID_BLOCK_REQUEST);
		for (u32 block = 0; block < xrServer::id_block_count(); ++block)
			P.w_u16(server.free_ids_in_block(block));
		send(P);
		g_request_pending = true;
	}

	// The first new ids are needed while the save is still loading (scripts spawn squads on the actor's
	// first update), when frames - and so the regular message exchange - aren't running yet. Without
	// a block those objects would get the same ids on every client, so get one right here.
	static void acquire_first_block(const xrServer& server)
	{
		const bool welcomed = wait_for_messages([] { return is_connected(); }, WAIT_MS,
		                                        {M_WELCOME, M_ID_BLOCK_GRANT});
		if (welcomed && g_blocks.empty() && !g_server_exhausted)
		{
			if (!g_request_pending)
				send_request(server);
			wait_for_messages([] { return !g_blocks.empty() || g_server_exhausted; }, WAIT_MS, {M_ID_BLOCK_GRANT});
		}

		if (g_blocks.empty())
		{
			Msg("! [coop] no id block from the server in time");
			g_gave_up_waiting = true;
		}
	}

	// An id whose object the client hasn't destroyed yet (a bolt of an NPC gone offline this frame): a new object
	// with it fails to spawn ("Object with ID already exists"), and a stand-in failing so corrupted the heap. Such
	// ids go back to the end of the block's line.
	static u16 take_from_block(xrServer& server, u16 block)
	{
		for (u32 tries = server.free_ids_in_block(block); tries; --tries)
		{
			const u16 id = server.PerformIDgenFromBlock(block);
			if (id == NO_BLOCK || !g_pGameLevel || !Level().Objects.net_Find(id))
				return id;
			server.FreeID(id, Device.TimerAsync());
		}
		return NO_BLOCK;
	}

	static u16 take_from_blocks(xrServer& server)
	{
		for (u32 min_free : {REUSE_MIN_FREE, 1u})
			for (u16 block : g_blocks)
			{
				if (server.free_ids_in_block(block) < min_free)
					continue;
				const u16 id = take_from_block(server, block);
				if (id != NO_BLOCK)
					return id;
			}
		return NO_BLOCK;
	}

	// A burst (a new character's game re-making ~2000 world items in one frame) uses our blocks up before the
	// next grant comes with the frame's messages. The local generator would then hand out ids of other players'
	// blocks, and their own objects with those ids clash with ours: wait for the grant right here instead.
	static void wait_for_block(const xrServer& server)
	{
		if (!g_request_pending)
			send_request(server);
		if (!wait_for_messages([] { return !g_request_pending; }, WAIT_MS, {M_ID_BLOCK_GRANT}))
		{
			Msg("! [coop] no new id block from the server in time");
			g_gave_up_waiting = true;
			g_request_pending = false; // update_id_blocks asks again
		}
	}

	u16 allocate_id(xrServer& server)
	{
		// a new game that is yet to become the world on an empty server makes its objects as usual
		if (!is_link_up() || !runs_shared_world())
			return NO_BLOCK;

		if (g_blocks.empty() && !g_gave_up_waiting && !g_server_exhausted)
			acquire_first_block(server);

		u16 id = take_from_blocks(server);
		if (id == NO_BLOCK && !g_blocks.empty() && !g_gave_up_waiting && !g_server_exhausted && is_connected())
		{
			wait_for_block(server);
			id = take_from_blocks(server);
		}

		if (id != NO_BLOCK)
		{
			if (!g_first_logged)
			{
				Msg("[coop] first new id from a leased block: %u", id);
				g_first_logged = true;
			}
			// ask for the next block now, not on the next frame: a burst may need it before then
			if (!g_request_pending && !g_server_exhausted && is_connected() && ai().get_alife() &&
			    free_in_owned_blocks(server) < reserve())
				send_request(server);
			return id;
		}

		// the object still gets created, but another client may reuse this id for something else
		if (++g_fallbacks <= 10)
			Msg("! [coop] no free ids in leased blocks, new id #%u comes from the local generator", g_fallbacks);
		return NO_BLOCK;
	}

	void on_id_block_granted(NET_Packet& P)
	{
		const u16 block = P.r_u16();
		g_request_pending = false;

		if (block == NO_BLOCK)
		{
			if (!g_server_exhausted)
				Msg("! [coop] server has no free id blocks left");
			g_server_exhausted = true;
			return;
		}

		if (std::find(g_blocks.begin(), g_blocks.end(), block) == g_blocks.end())
			g_blocks.push_back(block);
		g_gave_up_waiting = false;

		const xrServer* server = local_server();
		Msg("[coop] id block %u leased (ids %u..%u, %u free here)", block, block * 256, block * 256 + 255,
		    server ? server->free_ids_in_block(block) : 0);
	}

	void want_new_character_ids()
	{
		g_entry_goal = settings().new_character_ids;
	}

	void update_id_blocks()
	{
		// before A-Life has loaded the save every block looks free, and the server would pick blindly
		xrServer* server = local_server();
		if (!server || !ai().get_alife() || !is_connected())
			return;

		if (Device.dwTimeGlobal >= g_next_usage_log)
		{
			log_id_usage(*server, g_next_usage_log ? "every few minutes" : "coming into the world");
			g_next_usage_log = Device.dwTimeGlobal + settings().usage_log_ms;
		}

		const u32 free = free_in_owned_blocks(*server);
		if (g_entry_goal && free >= g_entry_goal)
		{
			Msg("[coop] new character: %u free ids in %u block(s) for the first entry", free, g_blocks.size());
			g_entry_goal = 0;
		}

		if (g_request_pending || g_server_exhausted || free >= reserve())
			return;

		send_request(*server);
	}

	void reset_id_blocks()
	{
		g_blocks.clear();
		g_request_pending = false;
		g_server_exhausted = false;
		g_fallbacks = 0;
		g_first_logged = false;
		g_gave_up_waiting = false;
		g_entry_goal = 0;
		g_next_usage_log = 0;
	}

	void print_id_status()
	{
		const xrServer* server = local_server();
		if (!server)
		{
			Msg("[coop]   id blocks: %u leased (no level loaded)", g_blocks.size());
			return;
		}

		Msg("[coop]   id blocks: %u leased, %u free ids in them; world: %u of %u ids free; %u ids from local generator",
		    g_blocks.size(), free_in_owned_blocks(*server), free_in_world(*server), xrServer::id_block_count() * 256 - 1,
		    g_fallbacks);
	}
}
