#pragma once

// Helicopters across games, a part of the NPC stream (coop_npc.h). On a level with several players its authority
// runs every helicopter there: its scripts choose the way and the targets (heli_alife, heli_combat, heli_move,
// heli_fire), its engine flies, aims, fires and takes the damage. In the other games a helicopter is a puppet:
// nothing of its own runs (gamedata/scripts/coop_heli.script stops its logic), it flies where the authority's is
// (the tail of M_NPC_STATES), turns its gun as that one does and fires blanks where it fires (eHeliShot), with the
// same tracers and ricochets. Its rockets fly and explode as any (coop_projectiles.h). A player's hit on a puppet goes
// to the authority, where the helicopter takes it from the player's stand-in (coop_combat.h); the authority's bullets,
// rockets and crash hit the other players through their stand-ins. The death goes as a vehicle's (coop_world.h
// on_vehicle_death), then the puppet falls as the authority's falls and blows up when it does. Its pieces are made once,
// by the authority (eHeliBreak tells the others' copies to wait for them), and lie where the authority's lie
// (coop_props.h).
//
// Any shared CHelicopter on the level goes this way: the story's, the smarts' and those a script spawns. A scripted
// event spawns its helicopter once for the world (coop.begin_shared at the level's authority) and drives it only
// where coop.heli_puppet(id) is false; what a script tells a puppet elsewhere changes nothing. One only this game
// has (made outside the shared area) flies here on its own, as before.

class CHelicopter;
class NET_Packet;

namespace coop
{
	bool is_heli_puppet(const CHelicopter* heli);
	// CHelicopter::UpdateCL: true when heli is a puppet, then moved, posed and heard here as the authority has it
	bool drive_heli_puppet(CHelicopter& heli);

	// the authority's side
	u32 write_heli_states(NET_Packet& P); // the level's helicopters, the tail of the first M_NPC_STATES packet; how many
	void on_heli_shot(CHelicopter& heli, const Fvector& position, const Fvector& direction, int shot_num, s32 seed);
	void on_heli_rocket(CHelicopter& heli, const Fvector& position);
	// CHelicopter::ExplodeHelicopter around CPHDestroyable::Destroy: the pieces are made once for the world (shared), and
	// where they come to rest goes to the others (coop_props.h); the others' copies are told to wait for them (eHeliBreak)
	void begin_heli_break(CHelicopter& heli);
	void end_heli_break();
	bool heli_breaking(); // coop_world.cpp on_object_registered: a piece of ours

	// the others'
	void read_heli_states(NET_Packet& P);           // the tail of M_NPC_STATES
	void play_heli_shot(u32 sender, NET_Packet& P);  // M_ACTOR_ACTION eHeliShot
	void play_heli_break(u32 sender, NET_Packet& P); // eHeliBreak: u16 id, vec3 where it broke
	// the authority's blew up there (eExplosion): the puppet's breaks the same, from that place
	void on_heli_exploded(CHelicopter& heli, const Fvector& position);

	void clear_heli_sync(); // disconnect, level unload
}
