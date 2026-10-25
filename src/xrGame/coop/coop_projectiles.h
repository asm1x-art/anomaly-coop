#pragma once

// Grenades, rockets and explosions across games. A thrown grenade (a bolt, a launched rocket) is a real
// object only in the game that threw it: our player's, or the level authority's for its NPCs. That game
// streams where it flies (M_ACTOR_ACTION eProjectile) and the others draw its model there. Every
// explosion that happens for real in a game (grenades, rockets, barrels) is sent (eExplosion) with the
// seed of its fragments: the others explode their own copy of the object as a blank (effects and the same
// fragments, no hits, no blast), or play its effects where they have none. Damage comes the usual way,
// through stand-ins and NPCs (coop_combat.h).

class CObject;
class CGameObject;
class NET_Packet;

namespace coop
{
	void on_projectile_launched(CGameObject& projectile, const CObject* thrower); // CMissile, CCustomRocket
	void on_explode(CGameObject& explosive, const Fvector& position, const Fvector& direction, s32 seed); // CExplosive::Explode
	void play_projectile(u32 sender, NET_Packet& P); // eProjectile
	void play_explosion(u32 sender, NET_Packet& P);  // eExplosion

	void update_projectiles(); // per frame
	void clear_projectiles();  // disconnect, level unload
}
