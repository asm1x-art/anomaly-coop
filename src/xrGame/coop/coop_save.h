#pragma once

// The shared world lives on the server as a save of the sim master's game. A client downloads it
// when it connects and loads it; its own character - position, money, health, and the inventory
// its shadow holds in the world - is put in place of the save's actor while the save loads.

class NET_Packet;

namespace coop
{
	// seed: a local save to start the world from if the server has none yet (coop_connect's 3rd argument)
	void set_world_seed(LPCSTR save_name);

	void on_world_info(NET_Packet& P);
	void on_world_chunk(NET_Packet& P);
	void on_world_done(NET_Packet& P);
	void on_character(NET_Packet& P);

	void update_world_sync(); // per frame
	void reset_world_sync();  // on disconnect
	void print_world_status();

	// engine hooks, CALifeStorageManager
	void on_game_saved(LPCSTR save_file_name); // after the save and its .scoc are written
	void on_world_objects_loaded();             // objects read from the save, not registered yet
	void on_world_loaded();                     // save fully loaded, nothing online yet
}
