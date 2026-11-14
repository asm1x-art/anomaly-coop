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
#include "coop_puppet.h"
#include "coop_combat.h"
#include "Helicopter.h"
#include "PhysicsShellHolder.h"
#include "../xrPhysics/PhysicsShell.h"
#include "level_graph.h"
#include "game_level_cross_table.h"
#include "ai_object_location.h"
#include "Inventory.h"
#include "inventory_item.h"
#include "script_engine.h"

namespace coop
{
	enum EPlace : u8
	{
		ePlaceGround,      // vec3 position, u16 game vertex, u32 level vertex
		ePlaceObject,      // u16 parent id, stringZ parent section
		ePlaceSenderActor, // the sending player's actor, which is its shadow on the receiving side
		ePlacePlayer,      // u32 peer id: that player's actor, our own one or the player's shadow (trading)
	};

	static const u16 NO_ID = u16(-1);
	static const u32 MAX_SKIP_LOGS = 10; // per reason: background A-Life traffic must not hide player actions

	// Deaths we applied on behalf of another client. Their on_death must not be sent back:
	// online kills reach on_death later, through GE_DIE, so a plain "applying" flag won't do.
	static xr_set<u16> g_remote_deaths;
	static u16 g_dying_remotely = u16(-1);
	static xr_set<u16> g_remote_vehicles; // their destruction another game sent, being applied here
	// bodies of our deaths still falling here: when they lie still, the others put theirs there too
	static xr_map<u16, u32> g_falling; // id -> Device.dwTimeContinual of the death
	static const u32 BODY_CHECK_MS = 500;
	static const u32 BODY_FALL_MIN_MS = 2000;  // the ragdoll is made a frame or two after the death
	static const u32 BODY_FALL_MAX_MS = 15000; // a body sliding down a slope is told where it is by then
	// same for online objects we asked to be destroyed
	static xr_set<u16> g_remote_releases;
	// and for items we asked to be dropped out of an online holder
	static xr_set<u16> g_remote_drops;
	// set while we change A-Life on behalf of another client, so hooks don't echo it back
	static bool g_applying = false;
	static xr_map<xr_string, u32> g_skip_logs; // reason -> times logged
	// Eating or using an item takes it out of the inventory first (reported as dropped) and destroys
	// it right after, ownerless by then: remember such items to log what really happened.
	static xr_set<u16> g_left_actor;  // left our actor's inventory
	static xr_map<u16, u32> g_left_shadow; // item -> peer: left a shadow here

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

	bool world_ready()
	{
		return level_running();
	}

	static bool g_replaying = false; // the journal goes into a world still loading: everything is offline

	// world changes from the others are applied now
	static bool can_apply()
	{
		return g_replaying || level_running();
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
		LPCSTR name = player_name(id);
		return *name ? name : "?";
	}

	// where a player's things are here: ours on our actor, another's in their shadow (also a player gone: the
	// journal's changes are by ids of players who may have left, us among them in an earlier session)
	static CSE_ALifeDynamicObject* things_of(u32 player)
	{
		LPCSTR name = player_name(player);
		if (player == my_id() || my_name() == name)
			return ai().alife().graph().actor();
		return *name ? ai().alife().objects().object(shadow_of(name), true) : nullptr;
	}

	// the local object that matches a remote one, or null when the worlds differ
	static CSE_ALifeDynamicObject* local_object(u16 id, const shared_str& section)
	{
		CSE_ALifeDynamicObject* object = ai().alife().objects().object(id, true);
		return object && object->s_name == section ? object : nullptr;
	}

	struct SBodyPlace
	{
		Fvector position;
		u16 game_vertex;
		u32 level_vertex;
	};

	// where a body lies in our game: its object while it is online here, else its A-Life place
	static SBodyPlace body_place(CSE_ALifeDynamicObject* body)
	{
		SBodyPlace place{body->o_Position, body->m_tGraphID, body->m_tNodeID};
		CGameObject* object = body->m_bOnline && g_pGameLevel ?
			smart_cast<CGameObject*>(Level().Objects.net_Find(body->ID)) : nullptr;
		if (!object || !ai().get_level_graph())
			return place;
		place.position = object->Position();
		u32 vertex = ai().level_graph().vertex_id(place.position);
		if (!ai().level_graph().valid_vertex_id(vertex)) // off the AI grid: the nearest, from where it stood
			vertex = ai().level_graph().vertex(object->ai_location().level_vertex_id(), place.position);
		place.level_vertex = vertex;
		place.game_vertex = ai().cross_table().vertex(vertex).game_vertex_id();
		return place;
	}

	static void write_body_place(NET_Packet& P, const SBodyPlace& place)
	{
		P.w_vec3(place.position);
		P.w_u16(place.game_vertex);
		P.w_u32(place.level_vertex);
	}

	static SBodyPlace read_body_place(NET_Packet& P)
	{
		SBodyPlace place;
		P.r_vec3(place.position);
		place.game_vertex = P.r_u16();
		place.level_vertex = P.r_u32();
		return place;
	}

	// A body offline here goes where the game that had it online shows it: offline, squads wander apart
	// in each game, and it would lie wherever ours had got to. Online here, it fell here.
	static void place_body(CSE_ALifeDynamicObject* body, const SBodyPlace& place)
	{
		if (body->m_bOnline || !ai().game_graph().valid_vertex_id(place.game_vertex))
			return;
		const float distance = body->o_Position.distance_to(place.position);
		alife_rw().teleport_object(body->ID, place.game_vertex, place.level_vertex, place.position);
		if (debug_mode)
			Msg("[coop dbg] body of %s (id=%u) moved %.0f m, to where it lies for the others", body->name_replace(),
			    body->ID, distance);
	}

	// the player who killed, for the tasks: "" for anyone else (an NPC, a mutant, an anomaly, offline combat).
	// A stand-in's kill is the kill of the player it stands for (coop_combat.h).
	static LPCSTR killer_name(CSE_Abstract* killer)
	{
		if (!killer)
			return "";
		if (smart_cast<CSE_ALifeCreatureActor*>(killer))
			return my_name().c_str();
		const u32 peer = peer_of_stand_in(killer->ID);
		return peer ? peer_name(peer) : "";
	}

	void on_creature_death(CSE_ALifeCreatureAbstract* victim, CSE_Abstract* killer)
	{
		if (g_remote_deaths.erase(victim->ID))
			return;

		// each client has its own actor under the same id
		if (smart_cast<CSE_ALifeCreatureActor*>(victim))
			return;

		if (!is_connected() || !level_running())
			return;

		if (!local_objects().count(victim->ID)) // not the others' yet: nothing to tell them
		{
			NET_Packet P;
			P.w_begin(M_ENTITY_DEATH);
			P.w_u16(victim->ID);
			P.w_stringZ(victim->s_name);
			P.w_u16(killer ? killer->ID : u16(-1));
			write_body_place(P, body_place(victim));
			send(P);
			if (victim->m_bOnline)
				g_falling[victim->ID] = Device.dwTimeContinual;

			Msg("[coop] death of %s (id=%u) sent", victim->name_replace(), victim->ID);
		}

		// only the game it died in knows the killer: the tasks pass it on to the others (coop_tasks.script)
		::luabind::functor<void> on_kill;
		if (ai().script_engine().functor("_G.coop_on_kill", on_kill))
			on_kill(victim->ID, killer_name(killer), killer ? killer->ID : u16(-1)); // the id: a companion's (Lua)
	}

	void update_bodies()
	{
		static u32 last = 0;
		if (g_falling.empty() || Device.dwTimeContinual - last < BODY_CHECK_MS)
			return;
		last = Device.dwTimeContinual;
		if (!world_ready() || !is_connected())
			return g_falling.clear();
		for (auto it = g_falling.begin(); it != g_falling.end();)
		{
			const u32 age = Device.dwTimeContinual - it->second;
			CPhysicsShellHolder* object = smart_cast<CPhysicsShellHolder*>(Level().Objects.net_Find(it->first));
			CSE_ALifeDynamicObject* body = ai().alife().objects().object(it->first, true);
			if (!object || !body || object->getDestroy())
			{
				it = g_falling.erase(it);
				continue;
			}
			const bool still = !object->PPhysicsShell() || !object->PPhysicsShell()->isEnabled();
			if (age < BODY_FALL_MIN_MS || (!still && age < BODY_FALL_MAX_MS))
			{
				++it;
				continue;
			}
			NET_Packet P;
			P.w_begin(M_ACTOR_ACTION);
			P.w_u8(eBodyRest);
			P.w_u16(it->first);
			write_body_place(P, body_place(body));
			send(P);
			it = g_falling.erase(it);
		}
	}

	void apply_body_rest(NET_Packet& P)
	{
		const u16 id = P.r_u16();
		const SBodyPlace place = read_body_place(P);
		if (!level_running())
		{
			if (debug_mode)
				Msg("[coop dbg] body %u came to rest before our world is up: dropped", id);
			return;
		}
		CSE_ALifeCreatureAbstract* body = smart_cast<CSE_ALifeCreatureAbstract*>(ai().alife().objects().object(id, true));
		if (body && !body->g_Alive())
			place_body(body, place);
	}

	static void apply_vehicle_death(CSE_ALifeDynamicObject* object);

	void apply_entity_death(NET_Packet& P)
	{
		const u16 id = P.r_u16();
		shared_str section;
		P.r_stringZ(section);
		P.r_u16(); // killer: not credited locally, rewards stay with whoever made the kill
		const bool placed = P.r_elapsed() > 0;
		const SBodyPlace place = placed ? read_body_place(P) : SBodyPlace{};

		if (!can_apply())
			return;

		CSE_ALifeDynamicObject* object = ai().alife().objects().object(id, true);
		if (object && object->s_name == section &&
		    (smart_cast<CSE_ALifeCar*>(object) || smart_cast<CSE_ALifeHelicopter*>(object)))
		{
			apply_vehicle_death(object);
			return;
		}
		CSE_ALifeCreatureAbstract* creature = smart_cast<CSE_ALifeCreatureAbstract*>(object);
		if (!creature || creature->s_name != section)
		{
			Msg("! [coop] remote death of %s (id=%u) ignored: no such creature here, worlds differ?", section.c_str(), id);
			return;
		}
		if (!creature->g_Alive())
			return;

		Msg("[coop] remote death of %s (id=%u)", creature->name_replace(), id);
		g_remote_deaths.insert(id);

		if (CEntity* entity = g_pGameLevel ? smart_cast<CEntity*>(Level().Objects.net_Find(id)) : nullptr)
		{
			// online: the regular GE_DIE path, killed "by itself" like obj:kill(nil) does
			if (!entity->AlreadyDie())
				entity->KillEntity(id);
		}
		else
		{
			// offline: what sim_offline_combat does; scripts then drop it from its squad. A squad releases
			// a member that died offline, and the release would reach the game the body lies in: it stays,
			// as after an online death
			g_dying_remotely = id;
			creature->on_death(creature);
			g_dying_remotely = u16(-1);
			// what its game object kept was a live one's (its plans, its memory): a body coming online with it
			// read past it and crashed (a death replayed from the journal onto the save)
			creature->client_data.clear();
			if (placed)
				place_body(creature, place);
		}
	}

	bool is_dying_remotely(u16 id)
	{
		return id == g_dying_remotely || g_remote_vehicles.count(id);
	}

	void on_vehicle_death(CEntity* vehicle)
	{
		if (g_remote_vehicles.erase(vehicle->ID()) || !is_connected() || !level_running() ||
		    local_objects().count(vehicle->ID()))
			return;
		NET_Packet P;
		P.w_begin(M_ENTITY_DEATH);
		P.w_u16(vehicle->ID());
		P.w_stringZ(vehicle->cNameSect());
		P.w_u16(u16(-1));
		send(P);
		Msg("[coop] destruction of %s (id=%u) sent", vehicle->cName().c_str(), vehicle->ID());
	}

	// another game's vehicle destroyed: online here, it goes as there (a car is killed, a helicopter's script
	// brings it down at no health); offline, a car comes online wrecked
	static void apply_vehicle_death(CSE_ALifeDynamicObject* object)
	{
		Msg("[coop] remote destruction of %s (id=%u)", object->name_replace(), object->ID);
		CEntity* vehicle = g_pGameLevel ? smart_cast<CEntity*>(Level().Objects.net_Find(object->ID)) : nullptr;
		if (vehicle)
		{
			if (vehicle->getDestroy() || !vehicle->g_Alive())
				return;
			g_remote_vehicles.insert(object->ID);
			if (CHelicopter* heli = smart_cast<CHelicopter*>(vehicle))
				heli->SetfHealth(0.f);
			else
				vehicle->KillEntity(object->ID);
		}
		else if (CSE_ALifeCar* car = smart_cast<CSE_ALifeCar*>(object))
			car->health = 0.f;
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

	void share_object(CSE_ALifeDynamicObject* object)
	{
		local_objects().erase(object->ID);
		send_spawn(object);
	}

	// The last holder each thing left (not our actor, not a shadow), to tell the server where our actor took it from
	struct STakenFrom
	{
		u16 holder;
		shared_str section;
		Fvector position;
		u16 game_vertex;
		u32 level_vertex;
		u32 time;
	};
	static xr_map<u16, STakenFrom> g_taken_from;
	static const u32 TAKEN_FROM_MS = 2000; // a thing leaving a holder and coming to us this soon after: from it

	// M_TAKEN: going back to a save, a thing taken since goes back there (restore_things)
	static void send_taken(CSE_ALifeDynamicObject* thing)
	{
		auto from = g_taken_from.find(thing->ID);
		const bool held = from != g_taken_from.end() && Device.dwTimeGlobal - from->second.time < TAKEN_FROM_MS;
		NET_Packet P;
		P.w_begin(M_TAKEN);
		P.w_u16(thing->ID);
		P.w_stringZ(thing->s_name);
		P.w_u8(held ? 1 : 0);
		if (held)
		{
			P.w_u16(from->second.holder);
			P.w_stringZ(from->second.section);
			P.w_vec3(from->second.position);
			P.w_u16(from->second.game_vertex);
			P.w_u32(from->second.level_vertex);
		}
		else
		{
			P.w_vec3(thing->o_Position);
			P.w_u16(thing->m_tGraphID);
			P.w_u32(thing->m_tNodeID);
		}
		P.w_stringZ(Level().name());
		send(P);
		if (from != g_taken_from.end())
			g_taken_from.erase(from);
	}

	void on_item_attached(CSE_Abstract& parent, CSE_ALifeInventoryItem* item)
	{
		if (!should_send() || is_shadow(&parent))
			return;
		// where our actor took it from; not a thing a player gave us (it left their shadow)
		if (is_actor(&parent))
		{
			auto from = g_taken_from.find(item->base()->ID);
			const bool given = from != g_taken_from.end() && from->second.holder == u16(-1);
			if (!given)
				if (CSE_ALifeDynamicObject* thing = smart_cast<CSE_ALifeDynamicObject*>(item->base()))
					send_taken(thing);
		}

		if (local_objects().count(item->base()->ID))
		{
			if (is_actor(&parent))
			{
				// Picked up off the ground, the item gets its parent only after this (xrServer::Process_event_ownership):
				// sent without one, it lay on the ground in the other games, another player took it there, and it left
				// our inventory for theirs (an item gone from under the inventory's Drop button).
				CSE_ALifeDynamicObject* object = smart_cast<CSE_ALifeDynamicObject*>(item->base());
				const u16 parent_was = object->ID_Parent;
				object->ID_Parent = parent.ID;
				local_objects().erase(object->ID);
				send_spawn(object);
				object->ID_Parent = parent_was;
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

	void write_item_state(NET_Packet& P, CSE_ALifeDynamicObject* object)
	{
		NET_Packet spawn;
		object->Spawn_Write(spawn, FALSE);
		NET_Packet client;
		client.write_start();
		if (CGameObject* game_object = smart_cast<CGameObject*>(Level().Objects.net_Find(object->ID)))
			game_object->net_Save(client); // u16 size, then the data, as a save keeps it
		const u32 client_size = client.B.count > sizeof(u16) ? client.B.count - sizeof(u16) : 0;
		// what scripts keep by its id (coop_sync.script)
		::luabind::functor<LPCSTR> item_lua;
		LPCSTR lua = nullptr;
		if (ai().script_engine().functor("coop_sync.item_lua", item_lua))
			lua = item_lua(object->ID);

		P.w_u16(u16(spawn.B.count));
		P.w(spawn.B.data, spawn.B.count);
		P.w_u16(u16(client_size));
		if (client_size)
			P.w(client.B.data + sizeof(u16), client_size);
		P.w_stringZ(lua ? lua : "");
	}

	static void send_item_state(CSE_ALifeDynamicObject* object)
	{
		NET_Packet P;
		P.w_begin(M_OBJECT_STATE);
		write_item_state(P, object);
		send(P);
	}

	void send_inventory_states()
	{
		if (!should_send() || !g_actor)
			return;
		u32 sent = 0;
		for (PIItem item : g_actor->inventory().m_all)
		{
			const u16 id = item->object().ID();
			CSE_ALifeDynamicObject* object = ai().alife().objects().object(id, true);
			if (!object || local_objects().count(id))
				continue; // not the others' yet: sent whole when it is
			send_item_state(object);
			++sent;
		}
		if (debug_mode)
			Msg("[coop dbg] the state of our %u thing(s) sent", sent);
	}

	// state's condition, upgrades, ammo...: onto object, which stays where it is
	static void take_state(CSE_ALifeDynamicObject* object, CSE_Abstract* state, const xr_vector<u8>& client, const xr_string& lua)
	{
		const GameGraph::_GRAPH_ID game_vertex = object->m_tGraphID;
		const u32 level_vertex = object->m_tNodeID;
		const float distance = object->m_fDistance;
		NET_Packet packet;
		packet.write_start(); // NET_Packet() leaves its size as the stack had it
		state->STATE_Write(packet);
		packet.r_pos = 0;
		object->STATE_Read(packet, u16(packet.B.count));
		packet.write_start();
		state->UPDATE_Write(packet);
		packet.r_pos = 0;
		object->UPDATE_Read(packet);
		object->m_tGraphID = game_vertex; // where it is stays ours
		object->m_tNodeID = level_vertex;
		object->m_fDistance = distance;
		// Written where the thing was offline (the host, for an exit save: out of our shadow there), its client data
		// is in the spawn packet only. Without it a weapon forgot which modular scope was on it (CWeapon::save,
		// m_cur_scope) and CWeapon::net_Spawn picked a random one on every load.
		const xr_vector<u8>& data = client.empty() ? state->client_data : client;
		if (!data.empty())
			object->client_data = data;
		::luabind::functor<void> take_lua;
		if (!lua.empty() && ai().script_engine().functor("coop_sync.take_item_lua", take_lua))
			take_lua(object->ID, lua.c_str());
	}

	void apply_object_state(NET_Packet& P)
	{
		P.r_u32(); // sender
		const u16 size = P.r_u16();
		NET_Packet spawn;
		spawn.construct(&P.B.data[P.r_tell()], size);
		P.r_advance(size);
		const u16 client_size = P.r_u16();
		xr_vector<u8> client(client_size);
		if (client_size)
			P.r(client.data(), client_size);
		xr_string lua;
		P.r_stringZ(lua);

		if (!can_apply())
			return;
		u16 type;
		string256 section;
		spawn.r_begin(type);
		spawn.r_stringZ(section);
		if (!pSettings->section_exist(section))
			return;
		CSE_Abstract* state = F_entity_Create(section);
		if (!state)
			return;
		state->Spawn_Read(spawn);
		CSE_ALifeDynamicObject* object = local_object(state->ID, section);
		// online here, its game object has the state; an offline copy (a shadow's) takes it
		if (object && !object->m_bOnline)
			take_state(object, state, client, lua);
		F_entity_Destroy(state);
	}

	void on_item_detached(CSE_Abstract& parent, CSE_ALifeInventoryItem* item, u16 game_vertex_id)
	{
		if (level_running() && !is_actor(&parent))
		{
			const CSE_ALifeDynamicObject* holder = smart_cast<CSE_ALifeDynamicObject*>(&parent);
			STakenFrom& from = g_taken_from[item->base()->ID];
			from.holder = is_shadow(&parent) ? u16(-1) : parent.ID; // u16(-1): a player's, given to us
			from.section = parent.s_name;
			from.position = parent.o_Position;
			from.game_vertex = game_vertex_id;
			from.level_vertex = holder ? holder->m_tNodeID : u32(-1);
			from.time = Device.dwTimeGlobal;
			if (g_taken_from.size() > 256) // the ones nobody took
				for (auto it = g_taken_from.begin(); it != g_taken_from.end();)
					it = Device.dwTimeGlobal - it->second.time > TAKEN_FROM_MS ? g_taken_from.erase(it) : std::next(it);
		}
		if (g_remote_drops.erase(item->base()->ID))
			return;
		if (!should_send() || is_shadow(&parent) || local_objects().count(item->base()->ID))
			return;
		if (is_actor(&parent)) // the server entities are as the objects were last frame (CLevel::net_Update)
			send_item_state(smart_cast<CSE_ALifeDynamicObject*>(item->base())); // as it leaves us, first

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
		{
			g_left_actor.insert(item->base()->ID);
			Msg("[coop] dropped %s (id=%u), sent", item->base()->name_replace(), item->base()->ID);
		}
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
		if (is_actor(holder) || g_left_actor.erase(object->ID))
			Msg("[coop] used up %s (id=%u), sent", object->name_replace(), object->ID);
		else if (debug_mode)
			Msg("[coop dbg] release of %s (id=%u) sent", object->name_replace(), object->ID);
	}

	void send_release(u16 id, LPCSTR section)
	{
		NET_Packet P;
		P.w_begin(M_OBJECT_RELEASE);
		P.w_u16(id);
		P.w_stringZ(section);
		send(P);
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
		const u16 parent_was = object->ID_Parent;
		object->ID_Parent = holder->ID;
		object->Spawn_Write(packet, FALSE);
		// Released with its own parent, so that it leaves that holder's children (a player's shadow):
		// left there, giving it back attached it to the shadow twice ("Item is already inside the inventory").
		object->ID_Parent = parent_was;

		g_applying = true;
		alife_rw().release(object, true); // frees the id, Process_spawn takes it again
		g_taken_from.erase(object->ID); // not taken by our actor: it was moved here
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

		if (!can_apply())
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
			target = things_of(sender);
			if (!target)
				return skip("move", id, "unknown sender");
			break;
		case ePlacePlayer:
		{
			const u32 receiver = P.r_u32();
			if (receiver == my_id())
			{
				target = ai().alife().graph().actor();
				Msg("[coop] '%s' gave us %s (id=%u)", peer_name(sender), object->name_replace(), id);
				break;
			}
			target = things_of(receiver);
			if (!target)
				return skip("move", id, "unknown receiver");
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

		CSE_ALifeDynamicObject* holder = object->ID_Parent != NO_ID ? ai().alife().objects().object(object->ID_Parent, true) : nullptr;
		if (!target && object->m_bOnline && holder)
		{
			// Dropped out of an inventory that is online here (a dead NPC's weapon falling from its
			// hands): it falls here too, as a dropped item. Taken out on the server side it would be
			// marked as about to be destroyed, and a dead NPC's weapon is part of its ragdoll until
			// it really falls.
			g_remote_drops.insert(id);
			NET_Packet E;
			CGameObject::u_EventGen(E, GE_OWNERSHIP_REJECT, holder->ID);
			E.w_u16(id);
			CGameObject::u_EventSend(E);
			return;
		}

		// Everything below is done offline. An online item on the ground can be taken offline,
		// but moving items between online inventories needs client-side transfers: not yet.
		if (target && target->m_bOnline)
		{
			// An offline item going into an online inventory here (a trader's restock spawns items on
			// the ground and hands them over; something put out of a shadow into a box next to us):
			// recreate it, same id, right inside the holder.
			if (object->m_bOnline)
				return skip("move", id, "both it and its new holder are online here");
			respawn_into(object, target);
			return;
		}

		if (is_shadow(target) || is_shadow(holder))
			Msg("[coop] '%s' %s %s (id=%u)", peer_name(sender), is_shadow(target) ? "took" : "dropped",
			    object->name_replace(), id);
		if (is_shadow(holder))
			g_left_shadow[id] = sender;

		g_applying = true;
		if (object->m_bOnline && holder)
		{
			// Taken out of an inventory that is online here (a corpse next to both of us): the server
			// drops it like a rejected item, then it goes offline like anything else on the ground.
			alife_rw().server().Perform_reject(object, holder, 0);
			holder = nullptr;
		}
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

	bool give_item(u16 id, u32 peer)
	{
		auto receiver = peers().find(peer);
		CSE_ALifeDynamicObject* object = level_running() ? ai().alife().objects().object(id, true) : nullptr;
		CSE_ALifeInventoryItem* item = smart_cast<CSE_ALifeInventoryItem*>(object);
		CSE_ALifeDynamicObject* actor = level_running() ? ai().alife().graph().actor() : nullptr;
		if (receiver == peers().end() || !item || !actor || object->ID_Parent != actor->ID || !is_connected())
			return false;
		CSE_ALifeDynamicObject* shadow = ai().alife().objects().object(shadow_of(receiver->second.name), true);
		if (!shadow)
			return false;

		send_item_state(object); // as it leaves us, first

		// into the receiver's shadow here, as apply_item_parent moves things
		g_applying = true;
		CSE_ALifeDynamicObject* holder = actor;
		if (object->m_bOnline)
		{
			alife_rw().server().Perform_reject(object, holder, 0);
			holder = nullptr;
			alife_rw().switch_offline(object);
		}
		if (holder)
			alife_rw().graph().detach(*holder, item, holder->m_tGraphID, true);
		alife_rw().graph().attach(*shadow, item, shadow->m_tGraphID, true);
		g_applying = false;

		NET_Packet P;
		P.w_begin(M_ITEM_PARENT);
		P.w_u16(id);
		P.w_stringZ(object->s_name);
		P.w_u8(ePlacePlayer);
		P.w_u32(peer);
		send(P);
		Msg("[coop] gave %s (id=%u) to '%s'", object->name_replace(), id, receiver->second.name.c_str());
		return true;
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

		if (!can_apply())
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
				parent = things_of(sender);
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

	// online objects go through GE_DESTROY, like the Lua alife():release() does; the server destroys the
	// contents first, one by one, so none of it must be sent back either
	static void release_online(CSE_ALifeDynamicObject* object)
	{
		mark_remote_release(object);
		NET_Packet E;
		E.w_begin(M_EVENT);
		E.w_u32(Level().timeServer());
		E.w_u16(GE_DESTROY);
		E.w_u16(object->ID);
		Level().Send(E, net_flags(TRUE, TRUE));
	}

	// Online here, but not made on our side yet: a spawn and its release came one right after the other (a
	// player drops a bandage and uses it). Destroyed before it exists, it is made after all and stays, with
	// no server entity, till the level is destroyed - where the engine stops on it. The release waits.
	static xr_map<u16, u32> g_unborn_releases; // id -> Device.dwTimeContinual asked
	static const u32 UNBORN_WAIT_MS = 5000;

	void update_releases()
	{
		if (g_unborn_releases.empty())
			return;
		if (!level_running())
			return g_unborn_releases.clear();
		for (auto it = g_unborn_releases.begin(); it != g_unborn_releases.end();)
		{
			CSE_ALifeDynamicObject* object = ai().alife().objects().object(it->first, true);
			if (object && object->m_bOnline && !Level().Objects.net_Find(it->first) &&
			    Device.dwTimeContinual - it->second < UNBORN_WAIT_MS)
			{
				++it;
				continue;
			}
			if (object && object->m_bOnline)
				release_online(object);
			else if (object) // gone offline meanwhile
			{
				g_applying = true;
				alife_rw().release(object, true);
				g_applying = false;
			}
			it = g_unborn_releases.erase(it);
		}
	}

	void apply_object_release(NET_Packet& P)
	{
		const u32 sender = P.r_u32();
		const u16 id = P.r_u16();
		shared_str section;
		P.r_stringZ(section);

		if (!can_apply())
			return;

		CSE_ALifeDynamicObject* object = local_object(id, section);
		if (!object)
			return skip("release", id, "no such object here");

		auto left = g_left_shadow.find(id);
		if (is_shadow(ai().alife().objects().object(object->ID_Parent, true)) || left != g_left_shadow.end())
			Msg("[coop] '%s' used up %s (id=%u)", peer_name(sender), object->name_replace(), id);
		if (left != g_left_shadow.end())
			g_left_shadow.erase(left);

		if (object->m_bOnline)
		{
			if (Level().Objects.net_Find(id))
				release_online(object);
			else
				g_unborn_releases.emplace(id, Device.dwTimeContinual);
			return;
		}

		g_applying = true;
		alife_rw().release(object, true);
		g_applying = false;
	}
	void replay_journal()
	{
		xr_vector<xr_vector<u8>> journal, events;
		take_journal(journal);
		if (journal.empty())
			return;
		Msg("[coop] replaying %u change(s) made since the world's save", journal.size());
		g_replaying = true;
		for (xr_vector<u8>& msg : journal)
		{
			NET_Packet P;
			P.construct(msg.data(), (u32)msg.size());
			u16 type;
			P.r_begin(type);
			switch (type)
			{
			case M_ITEM_PARENT: apply_item_parent(P); break;
			case M_OBJECT_RELEASE: apply_object_release(P); break;
			case M_OBJECT_SPAWN: apply_object_spawn(P); break;
			case M_OBJECT_STATE: apply_object_state(P); break;
			case M_ENTITY_DEATH: apply_entity_death(P); break;
			case M_SCRIPT_EVENT: events.push_back(std::move(msg)); break; // Lua's, once the level runs
			default: Msg("! [coop] the journal has a message of type %u, skipped", type);
			}
		}
		g_replaying = false;
		defer_messages(events);
	}
	// After a save's things: where we took things from since it (M_TAKEN). The last place of each wins.
	static void return_taken(IReader& in, CSE_ALifeCreatureActor* actor, const xr_set<u16>& in_save, xr_vector<u16>& returned)
	{
		if (in.elapsed() < 2)
			return;
		struct SPlace
		{
			shared_str section;
			bool held;
			u16 holder;
			shared_str holder_section;
			Fvector position;
			u16 game_vertex;
			u32 level_vertex;
		};
		xr_map<u16, SPlace> places;
		for (u16 count = in.r_u16(); count && in.elapsed() >= 2; --count)
		{
			const u16 size = in.r_u16();
			if (in.elapsed() < size)
				break;
			NET_Packet P;
			P.construct(in.pointer(), size);
			P.r_pos = 0;
			in.advance(size);
			SPlace place;
			const u16 id = P.r_u16();
			P.r_stringZ(place.section);
			place.held = P.r_u8() == 1;
			place.holder = place.held ? P.r_u16() : u16(-1);
			if (place.held)
				P.r_stringZ(place.holder_section);
			P.r_vec3(place.position);
			place.game_vertex = P.r_u16();
			place.level_vertex = P.r_u32();
			places[id] = place;
		}
		u32 to_holders = 0, to_ground = 0;
		for (const auto& [id, place] : places)
		{
			if (in_save.count(id))
				continue; // the save had it: as it says
			CSE_ALifeDynamicObject* object = ai().alife().objects().object(id, true);
			CSE_ALifeInventoryItem* item = smart_cast<CSE_ALifeInventoryItem*>(object);
			if (!item || object->ID_Parent != actor->ID || object->s_name != place.section)
				continue; // not on us any more
			CSE_ALifeDynamicObject* holder = place.held ? ai().alife().objects().object(place.holder, true) : nullptr;
			if (holder && (holder->s_name != place.holder_section || holder == actor))
				holder = nullptr;
			if (!holder && (place.game_vertex == GameGraph::_GRAPH_ID(-1) || place.level_vertex == u32(-1)))
				continue; // nowhere known to put it
			alife_rw().graph().detach(*actor, item, holder ? holder->m_tGraphID : place.game_vertex, true);
			if (holder)
			{
				alife_rw().graph().attach(*holder, item, holder->m_tGraphID, true);
				++to_holders;
			}
			else
			{
				object->o_Position = place.position;
				object->m_tGraphID = place.game_vertex;
				object->m_tNodeID = place.level_vertex;
				++to_ground;
			}
			returned.push_back(id);
		}
		if (to_holders || to_ground)
			Msg("[coop] taken since that save: %u thing(s) back to where they were, %u onto the ground there", to_holders, to_ground);
	}

	void send_item_place(u16 id)
	{
		CSE_ALifeDynamicObject* object = ai().alife().objects().object(id, true);
		if (!object || !is_connected())
			return;
		CSE_ALifeDynamicObject* holder = object->ID_Parent != NO_ID ? ai().alife().objects().object(object->ID_Parent, true) : nullptr;
		NET_Packet P;
		P.w_begin(M_ITEM_PARENT);
		P.w_u16(id);
		P.w_stringZ(object->s_name);
		if (holder)
		{
			P.w_u8(ePlaceObject);
			P.w_u16(holder->ID);
			P.w_stringZ(holder->s_name);
		}
		else
		{
			P.w_u8(ePlaceGround);
			P.w_vec3(object->o_Position);
			P.w_u16(object->m_tGraphID);
			P.w_u32(object->m_tNodeID);
		}
		send(P);
	}

	void restore_things(IReader& things, xr_vector<u16>& made, xr_vector<u16>& returned)
	{
		CSE_ALifeCreatureActor* actor = ai().alife().graph().actor();
		if (!actor)
			return;
		u32 restored = 0, elsewhere = 0;
		xr_set<u16> in_save;
		for (u16 count = things.r_u16(); count; --count)
		{
			const u16 size = things.r_u16();
			const int next = things.tell() + size;
			const u16 spawn_size = things.r_u16();
			NET_Packet spawn;
			spawn.construct(things.pointer(), spawn_size);
			spawn.r_pos = 0;
			things.advance(spawn_size);
			xr_vector<u8> client(things.r_u16());
			if (!client.empty())
				things.r(client.data(), int(client.size()));
			xr_string lua;
			things.r_stringZ(lua);
			things.seek(next);

			u16 type;
			string256 section;
			spawn.r_begin(type);
			spawn.r_stringZ(section);
			if (!pSettings->section_exist(section))
				continue;
			CSE_Abstract* state = F_entity_Create(section);
			CSE_ALifeDynamicObject* thing = smart_cast<CSE_ALifeDynamicObject*>(state);
			if (!thing || !smart_cast<CSE_ALifeInventoryItem*>(state))
			{
				F_entity_Destroy(state);
				continue;
			}
			state->Spawn_Read(spawn);
			in_save.insert(thing->ID);
			CSE_ALifeDynamicObject* object = ai().alife().objects().object(thing->ID, true);
			if (object && object->s_name == thing->s_name)
			{
				if (object->ID_Parent == actor->ID)
				{
					take_state(object, state, client, lua);
					++restored;
				}
				else
					++elsewhere;
				F_entity_Destroy(state);
				continue;
			}
			// gone from the world: made again on us, with its id unless something else has it now
			thing->ID = alife_rw().server().PerformIDgen(object ? u16(-1) : thing->ID);
			thing->ID_Parent = actor->ID;
			thing->o_Position = actor->o_Position;
			thing->m_tGraphID = actor->m_tGraphID;
			thing->m_tNodeID = actor->m_tNodeID;
			thing->m_bOnline = false;
			if (!client.empty())
				thing->client_data = client;
			g_applying = true;
			alife_rw().register_object(thing, true);
			g_applying = false;
			::luabind::functor<void> take_lua;
			if (!lua.empty() && ai().script_engine().functor("coop_sync.take_item_lua", take_lua))
				take_lua(thing->ID, lua.c_str());
			made.push_back(thing->ID);
		}
		Msg("[coop] our things as the save has them: %u back to its state, %u made again, %u elsewhere in the world now",
		    restored, u32(made.size()), elsewhere);
		return_taken(things, actor, in_save, returned);
	}
}
