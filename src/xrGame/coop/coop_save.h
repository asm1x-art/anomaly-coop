#pragma once

// The shared world lives on the server as a save of the sim master's game. A client downloads it
// when it connects and loads it; its own character - position, money, health, and the inventory
// its shadow holds in the world - is put in place of the save's actor while the save loads.

class NET_Packet;

namespace coop
{
	// seed: a local save to start the world from if the server has none yet (coop_connect's 3rd argument)
	void set_world_seed(LPCSTR save_name);

	// minutes between the sim master's autosaves, 0: off (coop_autosave_interval; the saving is coop_sync.script's)
	extern int autosave_interval;

	void on_world_info(NET_Packet& P);
	void on_world_chunk(NET_Packet& P);
	void on_world_done(NET_Packet& P);
	void on_character(NET_Packet& P);
	void on_settings(NET_Packet& P);

	const xr_string& world_settings(); // as the server sent them, "" before that
	// "unknown" until the server said, then "none" or "exists"; "creating" while this game becomes the world,
	// "no_character" while the world waits for us to make a character
	LPCSTR world_status();
	// our new character is made (Lua) and starts there: load the world; with the "no_character" status only
	void join_world(u16 game_vertex, u32 level_vertex, const Fvector& position);
	LPCSTR character_community(); // "actor_<faction>" of our character as the server keeps it, "" if none
	// this game runs the shared world or is loading it: only then do new objects take ids from leased blocks
	bool runs_shared_world();

	// per frame. A game played while connected to a server without a world becomes the world: after it
	// has run a while it is saved and uploaded, and keeps running as the shared world.
	void update_world_sync();
	void reset_world_sync();  // on disconnect
	void print_world_status();

	// engine hooks, CALifeStorageManager
	void on_game_saved(LPCSTR save_file_name); // after the save and its .scoc are written
	void on_save_loading(LPCSTR file_name);     // any save starts loading
	void on_world_objects_loaded();             // objects read from the save, not registered yet
	void on_world_loaded();                     // save fully loaded, nothing online yet
}
