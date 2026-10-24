#pragma once

namespace coop
{
	// tint of the peers' spots (coop_peer_color)
	extern u32 peer_color;

	// Keeps one PDA map spot per connected peer in sync with the peer list.
	void update_map_markers();
	void clear_map_markers();
}
