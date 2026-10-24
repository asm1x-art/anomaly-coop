#include "stdafx.h"
#include "coop_world.h"
#include "coop_net.h"
#include "coop_shadow.h"
#include "Level.h"
#include "Actor.h"
#include "Entity.h"
#include "ai_space.h"
#include "alife_simulator.h"
#include "alife_object_registry.h"
#include "alife_graph_registry.h"
#include "xrServer_Objects_ALife_Monsters.h"

namespace coop
{
	enum EPlace : u8
	{
		ePlaceGround,      // vec3 position, u16 game vertex, u32 level vertex
		ePlaceObject,      // u16 parent id, stringZ parent section
		ePlaceSenderActor, // the sending player's actor, which is its shadow on the receiving side
	};

	static const u16 NO_ID = u16(-1);
	static const u32 MAX_SKIP_LOGS = 10; // per reason: background A-Life traffic must not hide player actions

	// Deaths we applied on behalf of another client. Their on_death must not be sent back:
	// online kills reach on_death later, through GE_DIE, so a plain "applying" flag won't do.
	static xr_set<u16> g_remote_deaths;
	// same for online objects we asked to be destroyed
	static xr_set<u16> g_remote_releases;
	// set while we change A-Life on behalf of another client, so hooks don't echo it back
	static bool g_applying = false;
	static xr_map<xr_string, u32> g_skip_logs; // reason -> times logged

	// Objects created in this world during the session, which the others don't have. Changes to
	// them aren't sent; an object becomes shared - sent as a whole - once our actor takes it.
	// Scripts that run in every world (corpse loot, respawns) can't produce duplicates that way.
	static xr_set<u16> g_local_objects;
	static const void* g_world = nullptr;
	// > 0 while Lua runs world logic this client is the authority for: what it spawns is shared at once
	static u32 g_shared_scope = 0;

	static void check_world()
	{
		// another save loaded: the ids mean other objects now
		if (g_world != ai().get_alife())
		{
			g_local_objects.clear();
			g_world = ai().get_alife();
		}
	}

	static xr_set<u16>& local_objects()
	{
		check_world();
		return g_local_objects;
	}

	void begin_shared_spawns() { ++g_shared_scope; }
	void end_shared_spawns() { if (g_shared_scope) --g_shared_scope; }

	// ai().alife() is const; the Lua alife() binding does the same (alife_simulator_script.cpp)
	static CALifeSimulator& alife_rw()
	{
		return const_cast<CALifeSimulator&>(ai().alife());
	}

	// A running level: loading a save attaches thousands of items, and while a level is torn down
	// (quitting, changing levels) the actor's whole inventory gets detached. bReady is false in both.
	static bool level_running()
	{
		return g_pGameLevel && g_pGameLevel->bReady && g_actor && ai().get_alife();
	}

	static bool should_send()
	{
		return !g_applying && level_running() && is_connected();
	}

	static void skip(LPCSTR what, u16 id, LPCSTR reason)
	{
		u32& count = g_skip_logs[reason];
		if (++count <= MAX_SKIP_LOGS)
			Msg("! [coop] remote %s of id=%u skipped: %s%s", what, id, reason,
			    count == MAX_SKIP_LOGS ? " (no more of these)" : "");
	}

	static bool is_actor(CSE_Abstract* object)
	{
		return object && smart_cast<CSE_ALifeCreatureActor*>(object) != nullptr;
	}

	static LPCSTR peer_name(u32 id)
	{
		auto peer = peers().find(id);
		return peer != peers().end() ? peer->second.name.c_str() : "?";
	}

	// the local object that matches a remote one, or null when the worlds differ
	static CSE_ALifeDynamicObject* local_object(u16 id, const shared_str& section)
	{
		CSE_ALifeDynamicObject* object = ai().alife().objects().object(id, true);
		return object && object->s_name == section ? object : nullptr;
	}

	void on_creature_death(CSE_ALifeCreatureAbstract* victim, CSE_Abstract* killer)
	{
		if (g_remote_deaths.erase(victim->ID))
			return;

		// each client has its own actor under the same id
		if (smart_cast<CSE_ALifeCreatureActor*>(victim))
			return;

		if (!is_connected() || !level_running() || local_objects().count(victim->ID))
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

		if (!level_running())
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

	static void send_spawn(CSE_ALifeDynamicObject* object)
	{
		NET_Packet spawn;
		object->Spawn_Write(spawn, FALSE);

		NET_Packet P;
		P.w_begin(M_OBJECT_SPAWN);
		P.w_u16(u16(spawn.B.count));
		P.w(spawn.B.data, spawn.B.count);
		send(P);

		Msg("[coop] got %s (id=%u), sent", object->name_replace(), object->ID);
	}

	void on_item_attached(CSE_Abstract& parent, CSE_ALifeInventoryItem* item)
	{
		if (!should_send() || is_shadow(&parent))
			return;

		if (local_objects().count(item->base()->ID))
		{
			if (is_actor(&parent))
			{
				local_objects().erase(item->base()->ID);
				send_spawn(smart_cast<CSE_ALifeDynamicObject*>(item->base()));
			}
			return;
		}

		NET_Packet P;
		P.w_begin(M_ITEM_PARENT);
		P.w_u16(item->base()->ID);
		P.w_stringZ(item->base()->s_name);
		if (smart_cast<CSE_ALifeCreatureActor*>(&parent))
			P.w_u8(ePlaceSenderActor);
		else
		{
			P.w_u8(ePlaceObject);
			P.w_u16(parent.ID);
			P.w_stringZ(parent.s_name);
		}
		send(P);

		if (is_actor(&parent))
			Msg("[coop] took %s (id=%u), sent", item->base()->name_replace(), item->base()->ID);
	}

	void on_item_detached(CSE_Abstract& parent, CSE_ALifeInventoryItem* item, u16 game_vertex_id)
	{
		if (!should_send() || is_shadow(&parent) || local_objects().count(item->base()->ID))
			return;

		// the item is left where its holder stands
		const CSE_ALifeDynamicObject* holder = smart_cast<CSE_ALifeDynamicObject*>(&parent);
		NET_Packet P;
		P.w_begin(M_ITEM_PARENT);
		P.w_u16(item->base()->ID);
		P.w_stringZ(item->base()->s_name);
		P.w_u8(ePlaceGround);
		P.w_vec3(parent.o_Position);
		P.w_u16(game_vertex_id);
		P.w_u32(holder ? holder->m_tNodeID : u32(-1));
		send(P);

		if (is_actor(&parent))
			Msg("[coop] dropped %s (id=%u), sent", item->base()->name_replace(), item->base()->ID);
	}

	void on_object_released(CSE_Abstract* object)
	{
		if (g_remote_releases.erase(object->ID))
			return;
		if (!should_send() || is_shadow(object) || local_objects().erase(object->ID))
			return;

		NET_Packet P;
		P.w_begin(M_OBJECT_RELEASE);
		P.w_u16(object->ID);
		P.w_stringZ(object->s_name);
		send(P);

		CSE_Abstract* holder = object->ID_Parent != NO_ID ? ai().alife().objects().object(object->ID_Parent, true) : nullptr;
		if (is_actor(holder))
			Msg("[coop] used up %s (id=%u), sent", object->name_replace(), object->ID);
	}

	static void spawn_online(NET_Packet& spawn_packet)
	{
		u16 type;
		spawn_packet.r_begin(type);
		ClientID client;
		client.set(0xffff);
		alife_rw().server().Process_spawn(spawn_packet, client);
	}

	// Puts an offline object into an online holder: Process_spawn creates it on the client as well,
	// as the Lua alife():create() does for an online parent. Done by dropping the local copy first.
	static void respawn_into(CSE_ALifeDynamicObject* object, CSE_ALifeDynamicObject* holder)
	{
		NET_Packet packet;
		object->ID_Parent = holder->ID;
		object->Spawn_Write(packet, FALSE);
		object->ID_Parent = NO_ID;

		g_applying = true;
		alife_rw().release(object, true); // frees the id, Process_spawn takes it again
		spawn_online(packet);
		g_applying = false;
	}

	void apply_item_parent(NET_Packet& P)
	{
		const u32 sender = P.r_u32();
		const u16 id = P.r_u16();
		shared_str section;
		P.r_stringZ(section);
		const EPlace place = EPlace(P.r_u8());

		if (!level_running())
			return;

		CSE_ALifeDynamicObject* object = local_object(id, section);
		CSE_ALifeInventoryItem* item = smart_cast<CSE_ALifeInventoryItem*>(object);
		if (!item)
			return skip("move", id, "no such item here");

		// where it goes
		CSE_ALifeDynamicObject* target = nullptr;
		Fvector position;
		u16 game_vertex = NO_ID;
		u32 level_vertex = u32(-1);
		switch (place)
		{
		case ePlaceGround:
			P.r_vec3(position);
			game_vertex = P.r_u16();
			level_vertex = P.r_u32();
			break;
		case ePlaceObject:
		{
			const u16 parent_id = P.r_u16();
			shared_str parent_section;
			P.r_stringZ(parent_section);
			target = local_object(parent_id, parent_section);
			if (!target)
				return skip("move", id, "no such holder here");
			break;
		}
		case ePlaceSenderActor:
		{
			auto peer = peers().find(sender);
			if (peer == peers().end())
				return skip("move", id, "unknown sender");
			target = ai().alife().objects().object(shadow_of(peer->second.name), true);
			if (!target)
				return skip("move", id, "sender has no shadow");
			break;
		}
		default:
			return skip("move", id, "bad place");
		}

		if (!target && game_vertex == NO_ID)
		{
			// the sender's holder had no graph vertex: leave it where its holder is here
			CSE_ALifeDynamicObject* here = object->ID_Parent != NO_ID ? ai().alife().objects().object(object->ID_Parent, true) : object;
			if (!here)
				return skip("move", id, "nowhere to put it");
			position = here->o_Position;
			game_vertex = here->m_tGraphID;
			level_vertex = here->m_tNodeID;
		}

		if (target && object->ID_Parent == target->ID)
			return;
		if (!target && object->ID_Parent == NO_ID)
		{
			// moved on the ground: nothing to do unless it is lying here offline
			if (!object->m_bOnline)
				alife_rw().teleport_object(id, game_vertex, level_vertex, position);
			return;
		}

		// Everything below is done offline. An online item on the ground can be taken offline,
		// but moving items between online inventories needs client-side transfers: not yet.
		CSE_ALifeDynamicObject* holder = object->ID_Parent != NO_ID ? ai().alife().objects().object(object->ID_Parent, true) : nullptr;
		if (object->m_bOnline && holder)
			return skip("move", id, "it is in an online inventory here");
		if (target && target->m_bOnline)
		{
			// An offline item going into an online inventory here (e.g. a trader's restock, which spawns
			// items on the ground and hands them over): recreate it, same id, right inside the holder.
			if (object->m_bOnline || holder)
				return skip("move", id, "its new holder is online here");
			respawn_into(object, target);
			return;
		}

		if (is_shadow(target) || is_shadow(holder))
			Msg("[coop] '%s' %s %s (id=%u)", peer_name(sender), is_shadow(target) ? "took" : "dropped",
			    object->name_replace(), id);

		g_applying = true;
		if (object->m_bOnline)
			alife_rw().switch_offline(object);
		if (holder)
			alife_rw().graph().detach(*holder, item, holder->m_tGraphID, true);
		if (target)
			alife_rw().graph().attach(*target, item, target->m_tGraphID, true);
		else
			alife_rw().teleport_object(id, game_vertex, level_vertex, position);
		g_applying = false;
	}

	void on_object_registered(CSE_ALifeDynamicObject* object)
	{
		if (!should_send())
			return;

		// Shared at once when created right in our actor's inventory, or by world logic we are the
		// authority for - unless it goes into something only we have. Otherwise local until taken.
		CSE_ALifeDynamicObject* parent = ai().alife().objects().object(object->ID_Parent, true);
		const bool parent_shared = !parent || !local_objects().count(parent->ID);
		if (is_actor(parent) || (g_shared_scope && parent_shared))
			send_spawn(object);
		else
			local_objects().insert(object->ID);
	}

	void apply_object_spawn(NET_Packet& P)
	{
		const u32 sender = P.r_u32();
		const u16 size = P.r_u16();
		NET_Packet spawn;
		spawn.construct(&P.B.data[P.r_tell()], size);

		if (!level_running())
			return;

		u16 type;
		string256 section;
		spawn.r_begin(type);
		spawn.r_stringZ(section);
		if (!pSettings->section_exist(section))
			return skip("spawn", NO_ID, "unknown section");

		CSE_Abstract* abstract = F_entity_Create(section);
		CSE_ALifeDynamicObject* object = smart_cast<CSE_ALifeDynamicObject*>(abstract);
		if (!object)
		{
			F_entity_Destroy(abstract);
			return skip("spawn", NO_ID, "not an A-Life object");
		}
		abstract->Spawn_Read(spawn); // reads from the start again, header included

		const u16 id = object->ID;
		if (!alife_rw().server().is_id_free(id))
		{
			F_entity_Destroy(abstract);
			return skip("spawn", id, "id already taken here, worlds differ?");
		}

		// whose inventory: the sender's actor is its shadow here
		if (object->ID_Parent != NO_ID)
		{
			CSE_ALifeDynamicObject* parent = ai().alife().objects().object(object->ID_Parent, true);
			if (is_actor(parent))
				parent = ai().alife().objects().object(shadow_of(peer_name(sender)), true);
			if (!parent)
			{
				F_entity_Destroy(abstract);
				return skip("spawn", id, "no such holder here");
			}
			object->ID_Parent = parent->ID;
			object->m_tGraphID = parent->m_tGraphID;
			object->m_tNodeID = parent->m_tNodeID;
			object->o_Position = parent->o_Position;
		}

		CSE_ALifeDynamicObject* holder = object->ID_Parent != NO_ID ? ai().alife().objects().object(object->ID_Parent, true) : nullptr;
		g_applying = true;
		if (holder && holder->m_bOnline)
		{
			// Into an online inventory here (a trader we both stand next to): the item has to exist
			// on the client too. Process_spawn does both, as the Lua alife():create() does for that case.
			NET_Packet packet;
			object->Spawn_Write(packet, FALSE);
			F_entity_Destroy(abstract);
			spawn_online(packet);
		}
		else
		{
			// the same id as on the sender: it is from the sender's block, which we never hand out
			object->ID = alife_rw().server().PerformIDgen(id);
			object->m_bOnline = false;
			alife_rw().register_object(object, true);
		}
		g_applying = false;

		Msg("[coop] '%s' got %s (id=%u)", peer_name(sender), section, id);
	}

	static void mark_remote_release(const CSE_ALifeDynamicObject* object)
	{
		g_remote_releases.insert(object->ID);
		for (u16 child : object->children)
			if (const CSE_ALifeDynamicObject* c = ai().alife().objects().object(child, true))
				mark_remote_release(c);
	}

	void apply_object_release(NET_Packet& P)
	{
		const u32 sender = P.r_u32();
		const u16 id = P.r_u16();
		shared_str section;
		P.r_stringZ(section);

		if (!level_running())
			return;

		CSE_ALifeDynamicObject* object = local_object(id, section);
		if (!object)
			return skip("release", id, "no such object here");

		if (is_shadow(ai().alife().objects().object(object->ID_Parent, true)))
			Msg("[coop] '%s' used up %s (id=%u)", peer_name(sender), object->name_replace(), id);

		if (object->m_bOnline)
		{
			// online objects go through GE_DESTROY, like the Lua alife():release() does; the server
			// destroys the contents first, one by one, so none of it must be sent back either
			mark_remote_release(object);
			NET_Packet E;
			E.w_begin(M_EVENT);
			E.w_u32(Level().timeServer());
			E.w_u16(GE_DESTROY);
			E.w_u16(id);
			Level().Send(E, net_flags(TRUE, TRUE));
			return;
		}

		g_applying = true;
		alife_rw().release(object, true);
		g_applying = false;
	}
}
