#pragma once

class NET_Packet;

// Facts about the world the server keeps itself (coop-server/src/storage.js facts.json), so every game has them
// whoever saved the world: world infos ("info:<name>": facts Anomaly keeps as the actor's info portions, the masks
// of coop_world_infos in gamedata/configs/mod_system_coop.ltx), faction relations ("rel:<faction>:<faction>",
// gamedata/scripts/coop_facts.script). A change in our game goes to the server, which passes it on; a game loading
// the world gets them all with it, and puts them over the save's.
namespace coop
{
	bool is_world_info(const shared_str& info);

	void on_fact(NET_Packet& P);  // M_FACT: from the server, with the world or as another game changed it
	void forget_facts();          // a new download of the world begins: it brings them all again
	LPCSTR fact(LPCSTR key);      // as we know it, "" for none

	// a change in our game (value "" for gone); ignored until the facts are put on the world after a load
	void report_fact(LPCSTR key, LPCSTR value);
	void on_actor_info(const shared_str& info, bool given); // CActor: an info portion given or taken

	void put_infos_on_load(); // the world infos onto the save's actor, before it is in the game (coop_save.cpp)
	void facts_ready();       // Lua, the actor's first update: every fact put on the world, changes reported from now
}
