#pragma once

// Fighting across games. A puppet (coop_puppet.h) is only a picture: NPCs can't see it and bullets pass.
// So every game also has a stand-in for each other player on its level: an invisible stalker of that
// player's faction (section coop_proxy, level-only: not in A-Life, never saved), kept where the player
// is, in the player's model and motions (it crouches when the player does). NPCs see it, aim at its
// bones and hit it; what hits it is sent to its player, who takes it from the same NPC there. A hit our
// player lands on an NPC puppet (another game runs that NPC) goes to that game, where the NPC takes it
// from our stand-in: so the NPC turns on us, not on the player whose game it is.
// Hits without an attacker (anomalies, radiation) aren't sent: each game has them for its own player.
//
// Grudges: a stalker's squad that a player shot (not by accident in a shared fight) holds it against
// that player, in every game: the game running the level makes them and sends them around, so whoever
// runs the level next has them too. They stand in for vanilla's goodwill of the NPC to the actor, which
// co-op leaves out (RELATION_REGISTRY::Action): every player is the actor of the world's save.

class CObject;
class CGameObject;
class CCustomMonster;
class CEntityAlive;
class CWeapon;
class CCartridge;
class CInventoryOwner;
class NET_Packet;
struct SHit;
struct SRotation;

namespace coop
{
	bool is_proxy(const CObject* object);
	u32 peer_of_stand_in(u16 object); // 0 for none (peer ids start at 1)
	u16 stand_in_of(u32 peer);        // the player's stand-in on our level, 0 for none
	// a stand-in is lit as its player is in their game (SLook::luminocity); false: not a stand-in
	bool stand_in_luminocity(const CObject* object, float& luminocity);
	// per frame for a stand-in, from drive_npc_puppet: where its player is
	bool drive_proxy(CCustomMonster* proxy, Fvector& position, float& model_yaw, SRotation& torso);

	// CGameObject::OnEvent(GE_HIT): true when the hit is another game's to take
	bool intercept_hit(CGameObject* target, SHit& hit);
	void on_coop_hit(u32 sender, NET_Packet& P); // M_COOP_HIT

	// CAI_Stalker::tfGetRelationType: npc's squad holds a grudge against the player other is (our actor
	// or a stand-in); also coop.grudge(npc id, other id) for Lua
	bool has_grudge(const CEntityAlive* npc, const CEntityAlive* other);
	bool has_grudge_id(u16 npc, u16 other);
	// our player fell (coop_death.script: lying wounded, back at the save point): the squads that turned on
	// them calm down, in every game
	void on_player_fell();

	// a bullet as it was fired: where it flew and the seed of its ricochets (CBulletManager::AddBullet)
	struct SBlank
	{
		Fvector direction;
		s32 seed;
	};
	// CWeapon::FireTrace: the bullets of our player's or our NPC's shot, as blanks in the other games
	void on_fire_trace(const CWeapon& weapon, const Fvector& position, float speed, const CCartridge& cartridge,
	                   const xr_vector<SBlank>& bullets);
	void play_bullets(u32 sender, NET_Packet& P); // M_ACTOR_ACTION eBullets

	// CActor::ActorUse: F on a player's stand-in opens the interaction with that player (Lua), never a talk
	bool use_player(CInventoryOwner* person);

	void update_combat();  // per frame
	void clear_proxies();  // disconnect, level unload
	void clear_grudges();  // disconnect
}
