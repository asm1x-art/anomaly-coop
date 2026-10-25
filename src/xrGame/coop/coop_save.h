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
	void on_save_now(NET_Packet& P);        // the server asks us, the sim master, to save the world
	void on_saves(NET_Packet& P);           // the list of saves: _G.coop_on_saves(text)
	void on_rollback_vote(NET_Packet& P);   // _G.coop_on_rollback_vote(proposer id, proposer, revision, time, name, reason)
	void on_rollback_result(NET_Packet& P); // _G.coop_on_rollback_result(result, who, revision)
	void on_world_reload();                 // the world went back to a save: load it again

	// Pausing is the whole world's: a game connected and in it never pauses on its own (the main menu, the
	// window losing focus, the level change box: as in multiplayer); the Pause key asks everyone in the world
	// (coop_pause.script), and once all agree every game pauses, or goes on, together
	bool keeps_running();
	bool world_paused();
	void propose_pause(bool pause);
	// the Pause key: says yes to another player's vote to pause or go on (a mouse has no say on a paused
	// level), or else asks for one
	void pause_key();
	void on_pause_vote(NET_Packet& P);   // _G.coop_on_pause_vote(proposer id, proposer, pause)
	void on_pause_result(NET_Packet& P); // _G.coop_on_pause_result(result, who, pause)
	void on_paused(NET_Packet& P);       // _G.coop_on_paused(paused, who asked)

	// Lua (coop_saves.script, coop_sync.script): what the next save is (name, reason, who; it goes up with it),
	// asking the master to save, the list of saves and the vote to go back to one
	void set_save_meta(LPCSTR name, LPCSTR reason, LPCSTR who);
	void request_save(LPCSTR name);
	void request_saves();
	void propose_rollback(u32 revision);
	void answer_rollback(bool yes);

	const xr_string& world_settings(); // as the server sent them, "" before that
	float world_rule(LPCSTR key, float fallback); // a number from them (coop-server/src/settings.js rules)
	// "unknown" until the server said, then "none" or "exists"; "creating" while this game becomes the world,
	// "no_character" while the world waits for us to make a character, "being_created" while another player
	// makes it (world_creator)
	LPCSTR world_status();
	LPCSTR world_creator();
	// we are about to start the world on an empty server: the server lets only the first player to ask do it;
	// false: we won't after all
	void claim_world(bool claim);
	void on_level_unloaded();
	// CLevel::net_Stop: leaving the world to the menu or the desktop (not a level change or a reload): the
	// master saves it and waits until the server has it; the server learns we are out of the world
	void on_leaving_level();
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
	void on_level_change();                     // CALifeUpdateManager::change_level: its save loads next
	void on_world_objects_loaded();             // objects read from the save, not registered yet
	void on_world_loaded();                     // save fully loaded, nothing online yet
}
