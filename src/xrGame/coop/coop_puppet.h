#pragma once

// Puppets: the other players on our level, drawn as their characters. A puppet is not a game object:
// no server entity, no physics, nothing the AI sees or bullets hit, only a model on the level with the
// outfit's look, the motions the player's own actor plays, and the item in hands.
// What each player looks like and does travels with its M_ACTOR_STATE (SLook, coop_net.h).

class NET_Packet;
class CWeapon;

namespace coop
{
	struct SLook;

	// M_ACTOR_ACTION: what a player's character, or an NPC its game runs, does
	enum EActorAction : u8
	{
		eShot,        // u8 shot flags (coop_puppet.cpp)
		eWeaponState, // u8 the weapon's new state (CWeapon/CHUDState), for its sounds
		eNpcShot,     // u16 NPC id: the authority's NPC fired (coop_npc.cpp)
		eBullets,     // a shot's bullets, from the player or the authority's NPC (coop_combat.cpp)
		eNpcHit,      // the authority's NPC flinched from a hit (coop_npc.cpp)
		eNpcSound,    // the authority's NPC said something or growled (coop_npc.cpp)
		eNpcWeaponState, // the authority's NPC reloads (coop_npc.cpp)
		eProjectile,  // a thrown grenade or a rocket in flight (coop_projectiles.cpp)
		eExplosion,   // something blew up (coop_projectiles.cpp)
		eBodyRest,    // u16 id, vec3, u16 game vertex, u32 level vertex: a body of a death we sent lies still (coop_world.cpp)
	};

	// names of the actor motions a puppet can play (as SActorMotions makes them); the same list on every
	// client, so a motion travels as its index
	const xr_vector<shared_str>& puppet_motion_names();

	void write_look(NET_Packet& P); // our actor, after the rest of M_ACTOR_STATE
	// our player lies wounded (coop_death.script): the others see it lying, NPCs leave it be
	void set_downed(bool downed);
	bool is_downed(u32 peer); // a player lying wounded; peer may be my_id()
	void read_look(NET_Packet& P, SLook& look);

	// what our actor does, for the others' puppets of it (M_ACTOR_ACTION); weapon hooks
	void on_actor_shot(const CWeapon& weapon, bool launcher);
	void on_actor_weapon_state(const CWeapon& weapon, u32 state);
	void on_peer_action(u32 sender, NET_Packet& P);

	void update_puppets(); // per frame
	void clear_puppets();  // disconnect, level unload
}
