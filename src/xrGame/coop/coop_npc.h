#pragma once

// NPC puppets. On a level with several players one of them is its authority (coop_net.h, is_authority):
// its NPCs think and fight, and its A-Life keeps online what is near any of the players. It streams what
// its online stalkers and mutants do (M_NPC_STATES), their health, shots and flinches from hits. In the
// other players' games the level's NPCs are its mirror from the moment the level loads: puppets with no
// thinking of their own, standing until the stream moves, turns and animates them, their weapons showing
// the authority's shots; ours it doesn't have online are hidden, and ones it has that we don't are
// brought online where it has them.

class CObject;
class CCustomMonster;
class CEntityAlive;
class CWeapon;
class NET_Packet;
struct SRotation;

namespace coop
{
	bool is_npc_puppet(const CCustomMonster* npc);
	// A-Life brings things online near the actor; with co-op near any player on the level, so the
	// level's authority has online what every player there sees
	float distance_to_players(const Fvector& actor_position, const Fvector& position);
	// The level's authority runs its NPCs for the other players' screens too, but the engine runs them for
	// our camera: every frame only near it or seen from it (crows, CObject::UpdateCL), thinking the less
	// often the farther from it (shedule_Scale). CCustomMonster takes the other players for cameras as well:
	// how far the nearest of them is, flt_max when there is none or we aren't the authority
	float distance_to_others(const CCustomMonster* npc);
	// per frame from CCustomMonster::UpdateCL: true when npc is a puppet, with where it is and faces
	// (in place of its own movement and animation)
	bool drive_npc_puppet(CCustomMonster* npc, Fvector& position, float& model_yaw, SRotation& torso);

	void on_npc_shot(const CWeapon& weapon);       // weapon hook, the authority's side
	void play_npc_shot(u16 npc_id);                // a puppet's weapon shows it
	// CCharacterPhysicsSupport::in_Hit played a hit motion (the authority's side); a puppet plays it too
	void on_hit_motion(CEntityAlive& npc, const Fvector& dir, const Fvector& bone_position, u16 bone);
	void play_npc_hit(NET_Packet& P);              // M_ACTOR_ACTION eNpcHit
	// CSoundPlayer::play: the authority's NPC says something (index: which of its sounds, delay: ms);
	// a puppet's own voice is muted, the authority's is played on it
	bool mute_npc_sound(const CObject* object);
	void on_npc_sound(CObject* object, u32 type, u32 index, u32 delay);
	void play_npc_sound(NET_Packet& P);            // eNpcSound
	void on_npc_weapon_state(const CWeapon& weapon, u32 state); // CWeapon::OnStateSwitch
	void play_npc_weapon_state(NET_Packet& P);     // eNpcWeaponState
	void on_npc_states(u32 sender, NET_Packet& P); // M_NPC_STATES

	void update_npc_sync(); // per frame
	void clear_npc_sync();  // disconnect, level unload
}
