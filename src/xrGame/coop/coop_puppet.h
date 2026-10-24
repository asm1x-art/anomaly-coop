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

	// names of the actor motions a puppet can play (as SActorMotions makes them); the same list on every
	// client, so a motion travels as its index
	const xr_vector<shared_str>& puppet_motion_names();

	void write_look(NET_Packet& P); // our actor, after the rest of M_ACTOR_STATE
	void read_look(NET_Packet& P, SLook& look);

	// what our actor does, for the others' puppets of it (M_ACTOR_ACTION); weapon hooks
	void on_actor_shot(const CWeapon& weapon, bool launcher);
	void on_actor_weapon_state(const CWeapon& weapon, u32 state);
	void on_peer_action(u32 sender, NET_Packet& P);

	void update_puppets(); // per frame
	void clear_puppets();  // disconnect, level unload
}
