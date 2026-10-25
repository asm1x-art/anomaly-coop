#pragma once

class NET_Packet;

// A player's own progress: the world's save is the sim master's game, so everything it keeps on the actor
// (rank, info portions, tasks, PDA news and map, statistics, the body's state; in Lua: tasks, needs,
// statistics...: gamedata/scripts/coop_progress.script) is the master's. Each game sends its own to the server,
// which keeps it per character with every save (coop-server/src/storage.js), and puts it on its actor in
// place of the save's when it loads someone else's save. What it is made of: docs/coop/progress.md.
namespace coop
{
	void send_progress();                 // M_PROGRESS_REQUEST, and on the way out of the world
	void on_progress_chunk(NET_Packet& P); // M_PROGRESS: ours, coming with the world
	void forget_progress();               // a new download of the world begins

	// while a save is being loaded (coop_save.cpp): take = the save's actor is someone else's, put ours on
	// it; a new character without progress starts with none of the save's (fresh)
	void begin_progress_load(bool take, bool new_character);
	LPCSTR progress_lua_file(); // the Lua part to take, written to a file for Lua; "" for none
	bool progress_fresh();      // a new character: the save's personal Lua state goes, nothing comes
	void apply_progress();      // the engine part, once the save's objects and registries are loaded
}
