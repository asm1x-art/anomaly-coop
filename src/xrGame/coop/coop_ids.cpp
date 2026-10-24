#include "stdafx.h"
#include "coop_ids.h"
#include "coop_net.h"
#include "Level.h"
#include "xrServer.h"
#include "ai_space.h"

namespace coop
{
	static const u32 LOW_RESERVE = 128; // ask for another block when fewer free ids than this are left
	static const u16 NO_BLOCK = u16(-1);
	static const u32 WAIT_MS = 2000; // for the first block, see acquire_first_block

	static xr_vector<u16> g_blocks; // leased to us, in grant order
	static bool g_request_pending = false;
	static bool g_server_exhausted = false;
	static u32 g_fallbacks = 0;     // new ids that had to come from the local generator
	static bool g_first_logged = false;
	static bool g_gave_up_waiting = false; // don't stall every spawn if the server didn't answer

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

	u16 allocate_id(xrServer& server)
	{
		if (!is_link_up())
			return NO_BLOCK;

		if (g_blocks.empty() && !g_gave_up_waiting && !g_server_exhausted)
			acquire_first_block(server);

		for (u16 block : g_blocks)
		{
			u16 id = server.PerformIDgenFromBlock(block);
			if (id != u16(-1))
			{
				if (!g_first_logged)
				{
					Msg("[coop] first new id from a leased block: %u", id);
					g_first_logged = true;
				}
				return id;
			}
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

	void update_id_blocks()
	{
		if (g_request_pending || g_server_exhausted || !is_connected())
			return;

		// before A-Life has loaded the save every block looks free, and the server would pick blindly
		xrServer* server = local_server();
		if (!server || !ai().get_alife() || free_in_owned_blocks(*server) >= LOW_RESERVE)
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
	}

	void print_id_status()
	{
		const xrServer* server = local_server();
		if (!server)
		{
			Msg("[coop]   id blocks: %u leased (no level loaded)", g_blocks.size());
			return;
		}

		u32 world_free = 0;
		for (u32 block = 0; block < xrServer::id_block_count(); ++block)
			world_free += server->free_ids_in_block(block);

		Msg("[coop]   id blocks: %u leased, %u free ids in them; world: %u of %u ids free; %u ids from local generator",
		    g_blocks.size(), free_in_owned_blocks(*server), world_free, xrServer::id_block_count() * 256 - 1, g_fallbacks);
	}
}
