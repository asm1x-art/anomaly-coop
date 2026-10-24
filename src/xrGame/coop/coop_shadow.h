#pragma once

// A peer's "shadow": a hidden inventory box in the local A-Life that holds this world's copy of the
// peer's inventory, standing in for the peer's actor (whose id, 0, is our own actor here).
// It is created locally, never goes online and is never replicated; it is found again after a
// save is loaded by its section and name.

namespace coop
{
	// id of the peer's shadow, created on first use; u16(-1) while no world is loaded
	u16 shadow_of(const xr_string& peer_name);

	void update_shadows(); // per frame: every known peer gets a shadow
	void print_shadow_status();
}
