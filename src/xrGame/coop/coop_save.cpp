#include "stdafx.h"
#include "coop_save.h"
#include "coop_net.h"
#include "coop_shadow.h"
#include "coop_world.h"
#include "Level.h"
#include "Actor.h"
#include "ai_object_location.h"
#include "ai_space.h"
#include "script_engine.h"
#include "game_graph.h"
#include "alife_simulator.h"
#include "alife_object_registry.h"
#include "alife_graph_registry.h"
#include "xrServer_Objects_ALife_Monsters.h"
#include "../xrEngine/XR_IOConsole.h"
#include <sys/stat.h>

void set_character_name_script(CSE_ALifeTraderAbstract* ta, LPCSTR str); // xrServer_Objects_ALife_Monsters_script.cpp

namespace coop
{
	static LPCSTR WORLD_SAVE = "coop_world";                 // the downloaded world, in the local saves
	static LPCSTR WORLD_EXT[] = {".scop", ".scoc"};          // the A-Life save and its Lua state
	static const u32 WORLD_FILE_COUNT = 2;
	static const u32 CHUNK = 15000;                          // file data per M_WORLD_CHUNK
	static const u32 RECORD_INTERVAL_MS = 10000;
	// a new game on an empty server becomes the world once it has run this long: the new game's
	// scripts move the actor to the chosen start level on the first update
	static const u32 CREATE_AFTER_MS = 10000;
	static const u32 STARTING_MONEY = 5000;
	// a player's first visit: their shadow has nothing for them yet
	static LPCSTR STARTER_KIT[] = {"wpn_knife", "wpn_pm", "ammo_9x18_fmj", "ammo_9x18_fmj", "bandage", "bandage",
	                               "medkit", "bread"};

	struct SCharacter
	{
		shared_str level;
		u16 game_vertex;
		u32 level_vertex;
		Fvector position;
		float yaw;
		u32 money;
		float health;
		shared_str community; // "actor_<faction>", "" in records from before it was kept
	};

	int autosave_interval = 5;

	static xr_string g_seed;
	static xr_string g_settings;
	static bool g_world_info_received = false;
	static bool g_creating = false;       // this game is being saved and uploaded as the new world
	static bool g_join_requested = false; // our new character is made: load the world (join_world)
	static SCharacter g_join_start;       // where the new character starts; its level is found on load
	static u32 g_running_since = 0;       // Device.dwTimeContinual when the level last started running, 0: not running
	static bool g_server_has_world = false;
	static xr_string g_server_owner;
	static u32 g_server_revision = 0;

	static u32 g_in_world = 0;            // revision of the coop world this game runs, 0: none
	static bool g_downloading = false;
	static xr_vector<u8> g_download[WORLD_FILE_COUNT];
	static bool g_load_pending = false;
	static bool g_loading = false;        // the coop world save is being loaded
	static xr_string g_loading_owner;
	static u32 g_loading_revision = 0;

	static bool g_has_record = false;
	static SCharacter g_record;
	static u32 g_last_record = 0;
	static xr_vector<u16> g_starter_kit;  // spawned while loading, shared once the level runs

	// Anomaly writes a save's .scoc after the engine is done with the .scop: the upload waits for it
	static const u32 UPLOAD_WAIT_MS = 10000;
	static xr_string g_pending_upload;    // save name without extension
	static u32 g_pending_since = 0;

	// ai().alife() is const; the Lua alife() binding does the same (alife_simulator_script.cpp)
	static CALifeSimulator& alife_rw()
	{
		return const_cast<CALifeSimulator&>(ai().alife());
	}

	static bool read_file(LPCSTR name, xr_vector<u8>& data)
	{
		IReader* r = FS.r_open("$game_saves$", name);
		if (!r)
			return false;
		data.assign((const u8*)r->pointer(), (const u8*)r->pointer() + r->length());
		FS.r_close(r);
		return true;
	}

	static void upload(LPCSTR save_name_no_ext)
	{
		xr_vector<u8> files[WORLD_FILE_COUNT];
		for (u32 i = 0; i < WORLD_FILE_COUNT; ++i)
		{
			string_path name;
			strconcat(sizeof(name), name, save_name_no_ext, WORLD_EXT[i]);
			if (!read_file(name, files[i]))
			{
				Msg("! [coop] can't upload the world: %s is missing", name);
				return;
			}
		}

		NET_Packet P;
		P.w_begin(M_WORLD_UPLOAD);
		for (const auto& file : files)
			P.w_u32((u32)file.size());
		send(P);
		for (u32 i = 0; i < WORLD_FILE_COUNT; ++i)
			for (u32 offset = 0; offset < files[i].size(); offset += CHUNK)
			{
				P.w_begin(M_WORLD_CHUNK);
				P.w_u8(u8(i));
				P.w_u32(offset);
				P.w(&files[i][offset], _min(CHUNK, (u32)files[i].size() - offset));
				send(P);
			}
		P.w_begin(M_WORLD_DONE);
		send(P);
		Msg("[coop] world uploaded from %s (%u + %u bytes)", save_name_no_ext, files[0].size(), files[1].size());
	}

	static bool is_mine(const xr_string& owner);
	static void request_world();

	// the server has a world we have never been in: a character is made first (Lua, the new game screen)
	static bool needs_character()
	{
		return g_server_has_world && !g_has_record && !is_mine(g_server_owner) && !g_join_requested;
	}

	void set_world_seed(LPCSTR save_name)
	{
		g_seed = save_name ? save_name : "";
	}

	void on_world_info(NET_Packet& P)
	{
		g_server_has_world = !!P.r_u8();
		P.r_stringZ(g_server_owner);
		g_server_revision = P.r_u32();
		g_world_info_received = true;

		if (g_creating && g_server_has_world)
		{
			g_creating = false;
			if (is_mine(g_server_owner))
			{
				g_in_world = g_server_revision;
				Msg("[coop] this game is the shared world now (revision %u)", g_in_world);
				return;
			}
			Msg("[coop] '%s' started the world first, switching to it", g_server_owner.c_str());
		}

		if (!g_server_has_world)
		{
			if (!g_seed.empty())
			{
				Msg("[coop] the server has no world yet, starting it from the save '%s'", g_seed.c_str());
				upload(g_seed.c_str());
				g_seed.clear();
			}
			else
				Msg("[coop] the server has no world yet; connect with a save to start it from");
			return;
		}

		// a newer revision from the master's saves doesn't concern a game already running the world
		if (g_in_world || g_downloading || g_load_pending || g_loading)
			return;

		if (needs_character())
		{
			// the new game screen makes it: _G.coop_on_character_needed() opens it, join_world comes back
			Msg("[coop] no character of ours in this world yet: waiting for one");
			::luabind::functor<void> handler;
			if (ai().script_engine().functor("_G.coop_on_character_needed", handler))
				handler();
			return;
		}
		request_world();
	}

	static void request_world()
	{
		Msg("[coop] downloading the world (revision %u, by '%s')", g_server_revision, g_server_owner.c_str());
		for (auto& file : g_download)
			file.clear();
		g_downloading = true;
		NET_Packet R;
		R.w_begin(M_WORLD_REQUEST);
		send(R);
	}

	void on_world_chunk(NET_Packet& P)
	{
		if (!g_downloading)
			return;
		const u8 file = P.r_u8();
		const u32 offset = P.r_u32();
		const u32 size = P.r_elapsed();
		if (file >= WORLD_FILE_COUNT)
			return;
		if (g_download[file].size() < offset + size)
			g_download[file].resize(offset + size);
		P.r(&g_download[file][offset], size);
	}

	void on_world_done(NET_Packet& P)
	{
		if (!g_downloading)
			return;
		g_downloading = false;
		P.r_stringZ(g_loading_owner);
		g_loading_revision = P.r_u32();

		for (u32 i = 0; i < WORLD_FILE_COUNT; ++i)
		{
			string_path name, path;
			strconcat(sizeof(name), name, WORLD_SAVE, WORLD_EXT[i]);
			FS.update_path(path, "$game_saves$", name);
			IWriter* w = FS.w_open(path);
			if (!w)
			{
				Msg("! [coop] can't write %s", path);
				return;
			}
			w->w(g_download[i].data(), (u32)g_download[i].size());
			FS.w_close(w);
			g_download[i].clear();
		}
		Msg("[coop] world downloaded (revision %u), loading it", g_loading_revision);
		g_load_pending = true;
	}

	void on_settings(NET_Packet& P)
	{
		P.r_stringZ(g_settings);
	}

	const xr_string& world_settings()
	{
		return g_settings;
	}

	LPCSTR world_status()
	{
		if (!g_world_info_received)
			return "unknown";
		if (g_creating)
			return "creating";
		if (needs_character() && !g_in_world)
			return "no_character";
		return g_server_has_world ? "exists" : "none";
	}

	void join_world(u16 game_vertex, u32 level_vertex, const Fvector& position)
	{
		if (!needs_character() || g_in_world || g_downloading || g_load_pending || g_loading)
			return;
		g_join_start.game_vertex = game_vertex;
		g_join_start.level_vertex = level_vertex;
		g_join_start.position = position;
		g_join_start.yaw = 0.f;
		g_join_requested = true;
		request_world();
	}

	LPCSTR character_community()
	{
		return g_has_record ? g_record.community.c_str() : "";
	}

	bool runs_shared_world()
	{
		return g_in_world || g_loading;
	}

	// the character is called by our co-op name, whoever's actor the save holds
	static void name_actor()
	{
		if (CSE_ALifeCreatureActor* actor = ai().alife().graph().actor())
			set_character_name_script(actor, my_name().c_str());
	}

	static void create_world()
	{
		Msg("[coop] the server has no world: this game becomes it");
		name_actor();
		g_creating = true;
		string256 command;
		xr_sprintf(command, "save %s", WORLD_SAVE);
		Console->Execute(command); // on_game_saved uploads it
	}

	void on_character(NET_Packet& P)
	{
		P.r_stringZ(g_record.level);
		g_record.game_vertex = P.r_u16();
		g_record.level_vertex = P.r_u32();
		P.r_vec3(g_record.position);
		g_record.yaw = P.r_float();
		g_record.money = P.r_u32();
		g_record.health = P.r_float();
		if (P.r_elapsed())
			P.r_stringZ(g_record.community);
		else
			g_record.community = "";
		g_has_record = true;
		Msg("[coop] our character is on %s", g_record.level.c_str());
	}

	static void send_record()
	{
		NET_Packet P;
		P.w_begin(M_CHARACTER);
		P.w_stringZ(Level().name());
		P.w_u16(g_actor->ai_location().game_vertex_id());
		P.w_u32(g_actor->ai_location().level_vertex_id());
		P.w_vec3(g_actor->Position());
		P.w_float(Device.vCameraDirection.getH());
		P.w_u32(g_actor->get_money());
		P.w_float(g_actor->GetfHealth());
		P.w_stringZ(g_actor->CharacterInfo().Community().id());
		send(P);
	}

	// seconds since the epoch the save file was written, 0 if it isn't there
	static __time64_t written(LPCSTR save_name_no_ext, LPCSTR ext)
	{
		string_path name, path;
		strconcat(sizeof(name), name, save_name_no_ext, ext);
		FS.update_path(path, "$game_saves$", name);
		struct _stat64 st;
		return _stat64(path, &st) == 0 ? st.st_mtime : 0;
	}

	static void try_pending_upload()
	{
		const LPCSTR name = g_pending_upload.c_str();
		const __time64_t scop = written(name, WORLD_EXT[0]);
		if (scop && written(name, WORLD_EXT[1]) >= scop)
		{
			upload(name);
			g_pending_upload.clear();
		}
		else if (Device.dwTimeContinual - g_pending_since > UPLOAD_WAIT_MS)
		{
			Msg("! [coop] %s%s wasn't written, the world is not uploaded", name, WORLD_EXT[1]);
			g_pending_upload.clear();
		}
	}

	void update_world_sync()
	{
		if (g_load_pending)
		{
			// Engine.Event defers the actual start, so this is safe from a frame callback
			g_load_pending = false;
			g_loading = true;
			Console->Execute("main_menu off"); // as Anomaly's own load from the menu does
			string256 command;
			xr_sprintf(command, "start server(%s/single/alife/load) client(localhost)", WORLD_SAVE);
			Console->Execute(command);
			return;
		}

		if (!g_pending_upload.empty())
			try_pending_upload();

		if (!world_ready())
		{
			g_running_since = 0;
			return;
		}
		if (!g_running_since)
			g_running_since = Device.dwTimeContinual;

		if (!g_in_world)
		{
			if (is_connected() && g_world_info_received && !g_server_has_world && !g_creating && !g_loading &&
			    g_actor && g_actor->g_Alive() && Device.dwTimeContinual - g_running_since >= CREATE_AFTER_MS)
				create_world();
			return;
		}

		for (u16 id : g_starter_kit)
			if (CSE_ALifeDynamicObject* item = ai().alife().objects().object(id, true))
				share_object(item);
		g_starter_kit.clear();

		if (Device.dwTimeContinual - g_last_record >= RECORD_INTERVAL_MS)
		{
			g_last_record = Device.dwTimeContinual;
			send_record();
		}
	}

	void reset_world_sync()
	{
		g_server_has_world = false;
		g_world_info_received = false;
		g_creating = false;
		g_join_requested = false;
		g_has_record = false; // the next connection may be under another name
		g_settings.clear();
		g_downloading = false;
		g_load_pending = false;
		g_in_world = 0;
	}

	void print_world_status()
	{
		if (!g_server_has_world)
			Msg("[coop]   world: none on the server");
		else
			Msg("[coop]   world: revision %u by '%s' on the server; this game %s", g_server_revision,
			    g_server_owner.c_str(), g_in_world ? "runs it" : "doesn't run it");
	}

	void on_game_saved(LPCSTR save_file_name)
	{
		if (!is_connected() || !(g_in_world || g_creating) || !world_ready())
			return;

		send_record();
		g_last_record = Device.dwTimeContinual;

		// the sim master's game is the world; uploaded once its .scoc is written too
		if (is_sim_master() || g_creating)
		{
			string_path name;
			xr_strcpy(name, save_file_name);
			if (char* ext = strext(name))
				*ext = 0;
			g_pending_upload = name;
			g_pending_since = Device.dwTimeContinual;
		}
	}

	static CSE_ALifeCreatureActor* find_actor()
	{
		for (const auto& [id, object] : ai().alife().objects().objects())
			if (CSE_ALifeCreatureActor* actor = smart_cast<CSE_ALifeCreatureActor*>(object))
				return actor;
		return nullptr;
	}

	static bool is_mine(const xr_string& owner)
	{
		return owner == my_name();
	}

	void on_save_loading(LPCSTR file_name)
	{
		// another save while the server has a world would be a second world drifting apart: play it alone
		if (is_link_up() && !g_loading && g_server_has_world)
		{
			Msg("[coop] '%s' is not the shared world: disconnecting from the co-op server", file_name);
			disconnect();
		}
	}

	void on_world_objects_loaded()
	{
		if (!g_loading || is_mine(g_loading_owner) || !(g_has_record || g_join_requested))
			return;

		// The save's actor is someone else's: put ours where we were, or a new character at its start.
		// Done before the objects are registered, so the level that gets loaded is ours.
		CSE_ALifeCreatureActor* actor = find_actor();
		const CGameGraph& graph = ai().game_graph();
		SCharacter& where = g_has_record ? g_record : g_join_start;
		if (!actor || where.game_vertex >= graph.header().vertex_count())
		{
			Msg("! [coop] our position doesn't fit this world, starting where the save is");
			return;
		}
		const shared_str level = graph.header().level(graph.vertex(where.game_vertex)->level_id()).name();
		if (g_has_record && level != where.level)
		{
			Msg("! [coop] our saved position doesn't fit this world, starting where the save is");
			return;
		}
		actor->o_Position = where.position;
		actor->o_Angle.set(0.f, where.yaw, 0.f);
		actor->m_tGraphID = where.game_vertex;
		actor->m_tNodeID = where.level_vertex;
		if (!g_has_record)
			Msg("[coop] our new character starts on %s", level.c_str());
	}

	// all of from's inventory goes to to, offline
	static void move_inventory(CSE_ALifeDynamicObject* from, CSE_ALifeDynamicObject* to)
	{
		const xr_vector<u16> children = from->children;
		for (u16 id : children)
		{
			CSE_ALifeInventoryItem* item = smart_cast<CSE_ALifeInventoryItem*>(ai().alife().objects().object(id, true));
			if (!item)
				continue;
			alife_rw().graph().detach(*from, item, from->m_tGraphID, true);
			alife_rw().graph().attach(*to, item, to->m_tGraphID, true);
		}
	}

	void on_world_loaded()
	{
		if (!g_loading)
			return;
		g_loading = false;
		g_in_world = g_loading_revision;

		name_actor();

		if (is_mine(g_loading_owner))
		{
			Msg("[coop] world loaded, our own character");
			return;
		}

		// The save's actor is the owner's: their things go to their shadow, ours come out of ours.
		CSE_ALifeCreatureActor* actor = ai().alife().graph().actor();
		CSE_ALifeDynamicObject* owner_shadow = ai().alife().objects().object(shadow_of(g_loading_owner), true);
		if (!actor || !owner_shadow)
		{
			Msg("! [coop] can't swap characters: no actor or no shadow for '%s'", g_loading_owner.c_str());
			return;
		}
		move_inventory(actor, owner_shadow);

		CSE_ALifeDynamicObject* my_shadow = ai().alife().objects().object(find_shadow_of(my_name()), true);
		if (my_shadow)
			move_inventory(my_shadow, actor);
		else if (!g_join_requested) // a character made on the new game screen gets its loadout from there
		{
			// first time in this world: a starter kit, shared with the others once the level runs
			for (LPCSTR section : STARTER_KIT)
			{
				if (!pSettings->section_exist(section))
					continue;
				CSE_Abstract* item = alife_rw().spawn_item(section, actor->o_Position, actor->m_tNodeID,
				                                           actor->m_tGraphID, actor->ID);
				g_starter_kit.push_back(item->ID);
			}
		}

		actor->m_dwMoney = g_has_record ? g_record.money : STARTING_MONEY;
		if (g_has_record && g_record.health > 0.f)
			actor->set_health(g_record.health);

		Msg("[coop] world loaded with our character in place of '%s'%s", g_loading_owner.c_str(),
		    my_shadow ? "" : g_join_requested ? " (new character)" : " (first visit: starter kit)");
	}
}
