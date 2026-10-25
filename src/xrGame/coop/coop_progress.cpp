#include "stdafx.h"
#include "coop_progress.h"
#include "coop_net.h"
#include "coop_save.h"
#include "coop_world.h"
#include "Level.h"
#include "Actor.h"
#include "ai_space.h"
#include "alife_simulator.h"
#include "alife_object_registry.h"
#include "alife_graph_registry.h"
#include "alife_registry_container.h"
#include "script_engine.h"
#include "xrServer_Objects_ALife_Monsters.h"
#include "map_location.h"
#include "map_manager.h"
#include "../xrCore/LocatorAPI_defs.h"

namespace coop
{
	// the progress file: MAGIC, VERSION, then sections, each u32 size + data (write_section), in this order
	static const u32 MAGIC = 0x47525043; // "CPRG"
	static const u16 VERSION = 1;
	static const u32 CHUNK = 15000;      // data per M_PROGRESS, fits a NET_Packet with its header
	static const u16 ACTOR_ID = 0;
	static const u16 MAP_ID = 1;         // the map manager keeps all its spots under 1 (map_manager.cpp)
	static LPCSTR LUA_OUT = "coop_progress_out.dat"; // in $game_saves$: Lua writes its part there, and reads ours
	static LPCSTR LUA_IN = "coop_progress_in.dat";
	static LPCSTR WORLD_INFOS = "coop_world_infos"; // gamedata/configs/mod_system_coop.ltx

	static xr_vector<u8> g_received; // ours, as the server sent it with the world
	static u32 g_received_got = 0;
	static bool g_take = false;      // the save being loaded gets our progress
	static bool g_fresh = false;     // ... or none at all: a new character
	static string_path g_lua_in = "";

	static CALifeSimulator& alife_rw()
	{
		return const_cast<CALifeSimulator&>(ai().alife());
	}

	template <typename R>
	static R& registry()
	{
		return ai().alife().registry((R*)nullptr);
	}

	// Facts about the world Anomaly keeps as the actor's info portions (a squad is dead, a mechanic has his
	// tools): the same for every player, never part of the progress; the save's stay.
	static bool is_world_info(const shared_str& info)
	{
		static xr_vector<shared_str> masks;
		static bool read = false;
		if (!read)
		{
			read = true;
			if (pSettings->section_exist(WORLD_INFOS))
				for (const auto& item : pSettings->r_section(WORLD_INFOS).Data)
					masks.push_back(item.first);
		}
		for (const shared_str& mask : masks)
			if (PatternMatch(info.c_str(), mask.c_str()))
				return true;
		return false;
	}

	static void path_in_saves(LPCSTR name, string_path& path)
	{
		FS.update_path(path, "$game_saves$", name);
	}

	static bool read_file(LPCSTR path, xr_vector<u8>& data)
	{
		FILE* f = fopen(path, "rb");
		if (!f)
			return false;
		fseek(f, 0, SEEK_END);
		data.resize(ftell(f));
		fseek(f, 0, SEEK_SET);
		const bool ok = data.empty() || fread(data.data(), 1, data.size(), f) == data.size();
		fclose(f);
		return ok;
	}

	template <typename F>
	static void write_section(IWriter& out, F&& write)
	{
		CMemoryWriter part;
		write(part);
		out.w_u32(part.size());
		if (part.size())
			out.w(part.pointer(), part.size());
	}

	// the next section as a reader over its data
	static IReader read_section(IReader& in)
	{
		const u32 size = in.r_u32();
		IReader part(in.pointer(), size);
		in.advance(size);
		return part;
	}

	template <typename R>
	static void save_entry(IWriter& out, u16 id)
	{
		typename R::_data* data = registry<R>().object(id, true);
		typename R::_data empty;
		save_data(data ? *data : empty, out);
	}

	// replaces the registry's entry, freeing what the old one held (tasks and map spots are pointers)
	template <typename R>
	static void put_entry(u16 id, typename R::_data& data)
	{
		if (typename R::_data* old = registry<R>().object(id, true))
		{
			delete_data(*old);
			*old = data;
		}
		else
			registry<R>().add(id, data, true);
	}

	template <typename R>
	static void load_entry(IReader& in, u16 id)
	{
		typename R::_data data;
		load_data(data, in);
		put_entry<R>(id, data);
	}

	template <typename R>
	static void clear_entry(u16 id)
	{
		typename R::_data empty;
		put_entry<R>(id, empty);
	}

	//------------------------------------------------------------------------------------------------
	// Ours, to the server

	static bool write_progress(CMemoryWriter& out)
	{
		CActor* actor = g_actor;
		if (!actor || !ai().get_alife())
			return false;

		// Lua first: its save_state handlers run as in a save, before the engine's state is taken
		string_path lua_path;
		path_in_saves(LUA_OUT, lua_path);
		::luabind::functor<bool> export_lua;
		xr_vector<u8> lua;
		if (!ai().script_engine().functor("coop_progress.export", export_lua) || !export_lua(lua_path) ||
		    !read_file(lua_path, lua))
		{
			Msg("! [coop] our Lua progress couldn't be written: not sent");
			return false;
		}

		out.w_u32(MAGIC);
		out.w_u16(VERSION);
		write_section(out, [&](IWriter& w)
		{
			w.w_s32(actor->Rank());
			w.w_s32(actor->Reputation());
		});
		// the actor's own data as a save keeps it (CSE_Abstract::client_data): body, boosters, quick slots...
		write_section(out, [&](IWriter& w)
		{
			NET_Packet P;
			P.write_start();
			actor->net_Save(P); // u16 size, then the data
			if (P.B.count > sizeof(u16))
				w.w(P.B.data + sizeof(u16), P.B.count - sizeof(u16));
		});
		write_section(out, [&](IWriter& w)
		{
			KNOWN_INFO_VECTOR infos;
			if (const auto* all = registry<CInfoPortionRegistry>().object(ACTOR_ID, true))
				for (const shared_str& info : *all)
					if (!is_world_info(info))
						infos.push_back(info);
			save_data(infos, w);
		});
		// how the factions and others see us: the actor's entry, and what every NPC's entry says of us
		write_section(out, [&](IWriter& w) { save_entry<CRelationRegistry>(w, ACTOR_ID); });
		write_section(out, [&](IWriter& w)
		{
			xr_vector<std::pair<u16, CHARACTER_GOODWILL>> toward;
			for (const auto& [id, data] : registry<CRelationRegistry>().objects())
			{
				auto it = data.personal.find(ACTOR_ID);
				if (id != ACTOR_ID && it != data.personal.end())
					toward.emplace_back(id, it->second.Goodwill());
			}
			w.w_u32(u32(toward.size()));
			for (const auto& [id, goodwill] : toward)
			{
				w.w_u16(id);
				w.w_s32(goodwill);
			}
		});
		write_section(out, [&](IWriter& w) { save_entry<CGameNewsRegistry>(w, ACTOR_ID); });
		write_section(out, [&](IWriter& w) { save_entry<CGameTaskRegistry>(w, ACTOR_ID); });
		write_section(out, [&](IWriter& w) { save_entry<CActorStatisticRegistry>(w, ACTOR_ID); });
		// the spots a save keeps (CMapLocationRegistry::save): not the passing ones, nor the other players'
		write_section(out, [&](IWriter& w)
		{
			Locations kept;
			if (Locations* all = registry<CMapLocationRegistry>().object(MAP_ID, true))
				for (const SLocationKey& key : *all)
					if (key.location && key.location->Serializable())
						kept.push_back(key);
			save_data(kept, w); // the keys only: the locations stay the registry's
		});
		write_section(out, [&](IWriter& w)
		{
			if (!lua.empty())
				w.w(lua.data(), u32(lua.size()));
		});
		return true;
	}

	void send_progress()
	{
		if (!is_connected() || !runs_shared_world() || !world_ready())
			return;
		CMemoryWriter out;
		if (!write_progress(out))
			return;
		const u32 total = out.size();
		for (u32 offset = 0; offset < total; offset += CHUNK)
		{
			NET_Packet P;
			P.w_begin(M_PROGRESS);
			P.w_u32(total);
			P.w_u32(offset);
			P.w(out.pointer() + offset, _min(CHUNK, total - offset));
			send(P);
		}
		Msg("[coop] our progress sent (%u bytes)", total);
	}

	//------------------------------------------------------------------------------------------------
	// Ours, from the server, onto the save's actor

	void forget_progress()
	{
		g_received.clear();
		g_received_got = 0;
	}

	void on_progress_chunk(NET_Packet& P)
	{
		const u32 total = P.r_u32();
		const u32 offset = P.r_u32();
		if (offset == 0)
		{
			g_received.assign(total, 0);
			g_received_got = 0;
		}
		const u32 size = P.r_elapsed();
		if (g_received.size() != total || offset + size > total)
			return;
		P.r(g_received.data() + offset, size);
		g_received_got += size;
	}

	static bool have_progress()
	{
		return !g_received.empty() && g_received_got >= g_received.size();
	}

	// the sections after the header, or false when it isn't a progress file of ours
	static bool open_progress(IReader& in)
	{
		if (in.length() < sizeof(u32) + sizeof(u16) || in.r_u32() != MAGIC)
			return false;
		const u16 version = in.r_u16();
		if (version != VERSION)
		{
			Msg("! [coop] our progress is of version %u, this game reads %u: not taken", version, VERSION);
			return false;
		}
		return true;
	}

	void begin_progress_load(bool take, bool new_character)
	{
		g_take = false;
		g_fresh = false;
		g_lua_in[0] = 0;
		if (!take)
			return;
		if (!have_progress())
		{
			// a new character starts with nothing; one from before progress was kept keeps the save's
			g_fresh = new_character;
			return;
		}
		IReader in(g_received.data(), u32(g_received.size()));
		if (!open_progress(in))
			return;
		for (int skip = 0; skip < 9; ++skip) // to the Lua part, the last one
			read_section(in);
		IReader lua = read_section(in);
		path_in_saves(LUA_IN, g_lua_in);
		FILE* f = fopen(g_lua_in, "wb");
		if (!f)
		{
			Msg("! [coop] can't write %s: our progress is not taken", g_lua_in);
			g_lua_in[0] = 0;
			return;
		}
		fwrite(lua.pointer(), 1, lua.length(), f);
		fclose(f);
		g_take = true;
	}

	LPCSTR progress_lua_file()
	{
		return g_take ? g_lua_in : "";
	}

	bool progress_fresh()
	{
		return g_fresh;
	}

	static void keep_world_infos(KNOWN_INFO_VECTOR& infos)
	{
		if (const auto* save = registry<CInfoPortionRegistry>().object(ACTOR_ID, true))
			for (const shared_str& info : *save)
				if (is_world_info(info) && std::find(infos.begin(), infos.end(), info) == infos.end())
					infos.push_back(info);
	}

	static void forget_toward_actor()
	{
		xr_vector<u16> ids;
		for (const auto& [id, data] : registry<CRelationRegistry>().objects())
			if (id != ACTOR_ID && data.personal.count(ACTOR_ID))
				ids.push_back(id);
		for (u16 id : ids)
			registry<CRelationRegistry>().object(id, true)->personal.erase(ACTOR_ID);
	}

	static void apply_fresh(CSE_ALifeTraderAbstract* actor, CSE_Abstract* actor_entity)
	{
		actor->m_rank = 0;
		actor->m_reputation = 0;
		actor_entity->client_data.clear(); // the body as a new one: nothing to load
		KNOWN_INFO_VECTOR infos;
		keep_world_infos(infos);
		put_entry<CInfoPortionRegistry>(ACTOR_ID, infos);
		clear_entry<CRelationRegistry>(ACTOR_ID);
		forget_toward_actor();
		clear_entry<CGameNewsRegistry>(ACTOR_ID);
		clear_entry<CGameTaskRegistry>(ACTOR_ID);
		clear_entry<CActorStatisticRegistry>(ACTOR_ID);
		clear_entry<CMapLocationRegistry>(MAP_ID);
		Msg("[coop] a new character: nothing of the save's actor's progress kept");
	}

	static void apply_ours(CSE_ALifeTraderAbstract* actor, CSE_Abstract* actor_entity)
	{
		IReader in(g_received.data(), u32(g_received.size()));
		if (!open_progress(in))
			return;
		{
			IReader s = read_section(in);
			actor->m_rank = s.r_s32();
			actor->m_reputation = s.r_s32();
		}
		{
			IReader s = read_section(in);
			actor_entity->client_data.assign((const u8*)s.pointer(), (const u8*)s.pointer() + s.length());
		}
		{
			IReader s = read_section(in);
			KNOWN_INFO_VECTOR infos;
			load_data(infos, s);
			keep_world_infos(infos);
			put_entry<CInfoPortionRegistry>(ACTOR_ID, infos);
		}
		{
			IReader s = read_section(in);
			load_entry<CRelationRegistry>(s, ACTOR_ID);
		}
		{
			IReader s = read_section(in);
			forget_toward_actor();
			for (u32 i = 0, n = s.r_u32(); i < n; ++i)
			{
				const u16 id = s.r_u16();
				const CHARACTER_GOODWILL goodwill = s.r_s32();
				RELATION_DATA* data = registry<CRelationRegistry>().object(id, true);
				if (!data)
				{
					RELATION_DATA empty;
					registry<CRelationRegistry>().add(id, empty, true);
					data = registry<CRelationRegistry>().object(id, true);
				}
				data->personal[ACTOR_ID].SetGoodwill(goodwill);
			}
		}
		{
			IReader s = read_section(in);
			load_entry<CGameNewsRegistry>(s, ACTOR_ID);
		}
		IReader tasks = read_section(in);
		{
			IReader s = read_section(in);
			load_entry<CActorStatisticRegistry>(s, ACTOR_ID);
		}
		// the map before the tasks: a task being loaded looks for its spot on it (CGameTask::CreateMapLocation)
		{
			IReader s = read_section(in);
			load_entry<CMapLocationRegistry>(s, MAP_ID);
		}
		load_entry<CGameTaskRegistry>(tasks, ACTOR_ID);
		Msg("[coop] our own progress in place of the save's actor's (rank %d)", actor->m_rank);
	}

	void apply_progress()
	{
		const bool take = g_take, fresh = g_fresh;
		g_take = g_fresh = false;
		if (!take && !fresh)
			return;
		CSE_ALifeCreatureActor* actor = ai().alife().graph().actor();
		if (!actor)
			return;
		if (fresh)
			apply_fresh(actor, actor);
		else
			apply_ours(actor, actor);
	}
}
