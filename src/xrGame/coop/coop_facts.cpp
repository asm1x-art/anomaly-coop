#include "stdafx.h"
#include "coop_facts.h"
#include "coop_net.h"
#include "coop_world.h"
#include "Actor.h"
#include "ai_space.h"
#include "alife_simulator.h"
#include "alife_registry_container.h"
#include "script_engine.h"
#include "../xrCore/LocatorAPI_defs.h"

namespace coop
{
	static LPCSTR WORLD_INFOS = "coop_world_infos"; // gamedata/configs/mod_system_coop.ltx
	static LPCSTR INFO = "info:";
	static const u16 ACTOR_ID = 0;

	static xr_map<xr_string, xr_string> g_facts; // as the server has them, as far as we know
	static bool g_live = false;     // put on the world after the last load: our changes count from now
	static bool g_applying = false; // putting one on: not a change of ours

	bool is_world_info(const shared_str& info)
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

	LPCSTR fact(LPCSTR key)
	{
		auto it = g_facts.find(key);
		return it != g_facts.end() ? it->second.c_str() : "";
	}

	static void store(LPCSTR key, LPCSTR value)
	{
		if (*value)
			g_facts[key] = value;
		else
			g_facts.erase(key);
	}

	// one fact onto the running world: infos here, the rest in Lua (_G.coop_on_fact)
	static void put_on(const xr_string& key, const xr_string& value)
	{
		if (!strncmp(key.c_str(), INFO, xr_strlen(INFO)))
		{
			const shared_str info = key.c_str() + xr_strlen(INFO);
			const bool given = !value.empty();
			if (given == !!g_actor->HasInfo(info))
				return;
			g_applying = true;
			if (given)
				g_actor->OnReceiveInfo(info);
			else
				g_actor->OnDisableInfo(info);
			g_applying = false;
			return;
		}
		::luabind::functor<void> handler;
		if (ai().script_engine().functor("_G.coop_on_fact", handler))
		{
			g_applying = true;
			handler(key.c_str(), value.c_str());
			g_applying = false;
		}
	}

	void on_fact(NET_Packet& P)
	{
		shared_str key, value;
		P.r_stringZ(key);
		P.r_stringZ(value);
		store(key.c_str(), value.c_str());
		if (g_live && g_actor && world_ready())
			put_on(key.c_str(), value.c_str());
	}

	void forget_facts()
	{
		g_facts.clear();
		g_live = false;
	}

	void report_fact(LPCSTR key, LPCSTR value)
	{
		if (g_applying || !g_live || !is_connected() || !world_ready() || !xr_strcmp(fact(key), value))
			return;
		store(key, value);
		NET_Packet P;
		P.w_begin(M_FACT);
		P.w_stringZ(key);
		P.w_stringZ(value);
		send(P);
		if (debug_mode)
			Msg("[coop dbg] fact %s = '%s' sent", key, value);
	}

	void on_actor_info(const shared_str& info, bool given)
	{
		if (g_applying || !g_live || !is_world_info(info))
			return;
		string256 key;
		xr_sprintf(key, "%s%s", INFO, info.c_str());
		report_fact(key, given ? "1" : "");

		// a mechanic's tier given here (a toolkit task's on_complete): we brought him those tools, and the world
		// remembers who, for the discount (coop_mechanics.script); the first one only
		static const char TIER[] = "_upgrade_tier_";
		const char* tier = strstr(info.c_str(), TIER);
		const char* digit = tier ? tier + sizeof(TIER) - 1 : nullptr;
		if (given && digit && *digit && !digit[1])
		{
			string256 tool;
			xr_sprintf(tool, "tool:%.*s:%c", int(tier - info.c_str()), info.c_str(), *digit);
			if (!*fact(tool))
				report_fact(tool, my_name().c_str());
		}
	}

	void put_infos_on_load()
	{
		g_live = false; // until the actor's first update puts the rest on
		KNOWN_INFO_VECTOR* infos = ai().alife().registry((CInfoPortionRegistry*)nullptr).object(ACTOR_ID, true);
		if (!infos)
			return;
		u32 added = 0;
		for (const auto& [key, value] : g_facts)
		{
			if (strncmp(key.c_str(), INFO, xr_strlen(INFO)))
				continue;
			const shared_str info = key.c_str() + xr_strlen(INFO);
			if (std::find(infos->begin(), infos->end(), info) == infos->end())
			{
				infos->push_back(info);
				++added;
			}
		}
		if (added)
			Msg("[coop] %u world fact(s) the save didn't have put on our actor", added);
	}

	void facts_ready()
	{
		if (!g_actor)
			return;
		g_live = true;
		for (const auto& [key, value] : g_facts)
			put_on(key, value);
	}
}
