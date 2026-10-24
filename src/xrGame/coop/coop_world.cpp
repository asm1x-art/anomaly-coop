#include "stdafx.h"
#include "coop_world.h"
#include "coop_net.h"
#include "Level.h"
#include "Entity.h"
#include "ai_space.h"
#include "alife_simulator.h"
#include "alife_object_registry.h"
#include "xrServer_Objects_ALife_Monsters.h"

namespace coop
{
	// Deaths we applied on behalf of another client. Their on_death must not be sent back:
	// online kills reach on_death later, through GE_DIE, so a plain "applying" flag won't do.
	static xr_set<u16> g_remote_deaths;

	void on_creature_death(CSE_ALifeCreatureAbstract* victim, CSE_Abstract* killer)
	{
		if (g_remote_deaths.erase(victim->ID))
			return;

		// each client has its own actor under the same id
		if (smart_cast<CSE_ALifeCreatureActor*>(victim))
			return;

		if (!is_connected())
			return;

		NET_Packet P;
		P.w_begin(M_ENTITY_DEATH);
		P.w_u16(victim->ID);
		P.w_stringZ(victim->s_name);
		P.w_u16(killer ? killer->ID : u16(-1));
		send(P);

		Msg("[coop] death of %s (id=%u) sent", victim->name_replace(), victim->ID);
	}

	void apply_entity_death(NET_Packet& P)
	{
		const u16 id = P.r_u16();
		shared_str section;
		P.r_stringZ(section);
		P.r_u16(); // killer: not credited locally, rewards stay with whoever made the kill

		if (!g_pGameLevel || !ai().get_alife())
			return;

		CSE_ALifeCreatureAbstract* creature =
			smart_cast<CSE_ALifeCreatureAbstract*>(ai().alife().objects().object(id, true));
		if (!creature || creature->s_name != section)
		{
			Msg("! [coop] remote death of %s (id=%u) ignored: no such creature here, worlds differ?", section.c_str(), id);
			return;
		}
		if (!creature->g_Alive())
			return;

		Msg("[coop] remote death of %s (id=%u)", creature->name_replace(), id);
		g_remote_deaths.insert(id);

		if (CEntity* entity = smart_cast<CEntity*>(Level().Objects.net_Find(id)))
		{
			// online: the regular GE_DIE path, killed "by itself" like obj:kill(nil) does
			if (!entity->AlreadyDie())
				entity->KillEntity(id);
		}
		else
		{
			// offline: what sim_offline_combat does; scripts then drop it from its squad
			creature->on_death(creature);
		}
	}
}
