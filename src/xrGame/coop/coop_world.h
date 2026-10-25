#pragma once

// World state replication between co-op clients.
// Every client runs a full local A-Life; changes are mirrored by object id,
// so all clients must start from the same world (same save).

class CSE_ALifeCreatureAbstract;
class CSE_ALifeInventoryItem;
class CSE_ALifeDynamicObject;
class CSE_Abstract;
class NET_Packet;

namespace coop
{
	// called from CSE_ALifeCreatureAbstract::on_death, online and offline deaths alike
	void on_creature_death(CSE_ALifeCreatureAbstract* victim, CSE_Abstract* killer);
	// another game's death of a creature offline here is being applied: its body stays (coop_sync.script)
	bool is_dying_remotely(u16 id);
	// per frame: a body of a death we sent lies still, the others are told where (eBodyRest)
	void update_bodies();
	void update_releases(); // per frame: releases waiting for their object to be made on our side
	void apply_body_rest(NET_Packet& P); // M_ACTOR_ACTION eBodyRest
	// called from CALifeGraphRegistry::attach / detach, which every A-Life parent change goes through
	void on_item_attached(CSE_Abstract& parent, CSE_ALifeInventoryItem* item);
	void on_item_detached(CSE_Abstract& parent, CSE_ALifeInventoryItem* item, u16 game_vertex_id);
	// called from CALifeSimulatorBase::release for the released object itself, not for its children
	void on_object_released(CSE_Abstract* object);
	// called from CALifeSimulatorBase::register_object, which every new A-Life object goes through
	void on_object_registered(CSE_ALifeDynamicObject* object);

	// a level is running: world changes can be applied and sent (not while loading or tearing down)
	bool world_ready();

	// sends an object to the others as a whole, as when our actor takes something new
	void share_object(CSE_ALifeDynamicObject* object);
	// an item our actor carries goes to another player (trading): false when it can't
	bool give_item(u16 id, u32 peer);

	// for Lua wrappers around Anomaly's world logic
	void begin_shared_spawns();
	void end_shared_spawns();

	// from other clients
	void apply_entity_death(NET_Packet& P);
	void apply_item_parent(NET_Packet& P);
	void apply_object_release(NET_Packet& P);
	void apply_object_spawn(NET_Packet& P);
}
