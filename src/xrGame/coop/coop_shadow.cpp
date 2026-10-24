#include "stdafx.h"
#include "coop_shadow.h"
#include "coop_net.h"
#include "Level.h"
#include "Actor.h"
#include "ai_space.h"
#include "alife_simulator.h"
#include "alife_object_registry.h"
#include "alife_graph_registry.h"
#include "xrServer_Objects_ALife_Monsters.h"

namespace coop
{
	static LPCSTR SHADOW_SECTION = "coop_shadow_box"; // gamedata/configs/mod_system_coop.ltx
	static const u16 NO_ID = u16(-1);

	static xr_map<xr_string, u16> g_shadows; // peer name -> id, a cache: ids are checked on every use

	static xr_string shadow_name(const xr_string& peer_name)
	{
		return xr_string("coop_shadow_") + peer_name;
	}

	static bool is_shadow_of(CSE_ALifeDynamicObject* object, const xr_string& name)
	{
		return object && object->s_name == SHADOW_SECTION && name == object->name_replace();
	}

	static u16 find_shadow(const xr_string& name)
	{
		for (const auto& [id, object] : ai().alife().objects().objects())
			if (is_shadow_of(object, name))
				return id;
		return NO_ID;
	}

	// ai().alife() is const; the Lua alife() binding does the same (alife_simulator_script.cpp)
	static CALifeSimulator& alife_rw()
	{
		return const_cast<CALifeSimulator&>(ai().alife());
	}

	static u16 create_shadow(const xr_string& name)
	{
		// anywhere will do, it never goes online: next to our own actor
		const CSE_ALifeCreatureActor* actor = ai().alife().graph().actor();
		CSE_Abstract* abstract = alife_rw().spawn_item(SHADOW_SECTION, actor->o_Position, actor->m_tNodeID,
		                                                 actor->m_tGraphID, NO_ID, false);
		CSE_ALifeDynamicObject* shadow = smart_cast<CSE_ALifeDynamicObject*>(abstract);
		R_ASSERT(shadow);

		shadow->set_name_replace(name.c_str());
		shadow->can_switch_online(false);
		shadow->can_switch_offline(true);
		shadow->m_flags.set(CSE_ALifeObject::flInteractive, FALSE);
		shadow->m_flags.set(CSE_ALifeObject::flVisibleForAI, FALSE);
		shadow->m_flags.set(CSE_ALifeObject::flUsefulForAI, FALSE);

		// registered only now, so it can't be switched online in between
		alife_rw().register_object(shadow, true);
		return shadow->ID;
	}

	u16 shadow_of(const xr_string& peer_name)
	{
		if (!g_pGameLevel || !ai().get_alife() || !ai().alife().graph().actor())
			return NO_ID;

		const xr_string name = shadow_name(peer_name);

		auto it = g_shadows.find(peer_name);
		if (it != g_shadows.end() && is_shadow_of(ai().alife().objects().object(it->second, true), name))
			return it->second;

		// first use, or another save was loaded since
		u16 id = find_shadow(name);
		if (id == NO_ID)
		{
			id = create_shadow(name);
			Msg("[coop] shadow of '%s' created, id=%u", peer_name.c_str(), id);
		}
		g_shadows[peer_name] = id;
		return id;
	}

	void update_shadows()
	{
		if (!g_actor)
			return;
		for (const auto& [id, peer] : peers())
			shadow_of(peer.name);
	}

	void print_shadow_status()
	{
		for (const auto& [id, peer] : peers())
		{
			const u16 shadow = shadow_of(peer.name);
			CSE_ALifeDynamicObject* object = shadow != NO_ID ? ai().alife().objects().object(shadow, true) : nullptr;
			if (object)
				Msg("[coop]   shadow of '%s': id=%u, %u items", peer.name.c_str(), shadow, object->children.size());
		}
	}
}
