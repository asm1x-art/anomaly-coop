#pragma once

// Physics props and glass, the same in every co-op game (Notion audit item 6). Settings: [coop_physics] in
// gamedata/configs/mod_system_coop_physics.ltx.
//
// Where a thing lies. Every game runs its own physics: a barrel a player kicked, a door that swung (a ph_door with
// no_force), an item an explosion threw lay elsewhere in every game. Now when a thing (a physic object, a door, an item
// on the ground) comes to rest more than rest_min_move m or rest_min_turn degrees from where the world last agreed it
// lies, the game tells the others where its every physics element is (ePropRest). The level's authority has the last
// word: its own rest goes to everyone as the world's; another game's is a proposal, which the authority takes (while
// its copy lies still) and sends on as the world's. The others put their copy there, online (each element's
// position and rotation) or offline (a physic object's saved bones, an item's place), the host's too, so the world's
// save keeps it. A thing's first rest after it came online is never sent (every game loads the same world), unless
// our actor just dropped it or it is loot we just shared.
//
// Glass. A pane broken in one game went for the others only when that game released it, seconds later, with no
// breaking. Now the breaking goes to the others at once (eGlassBreak), who break theirs the same way: the shards fly
// as a seed of its id says, the same in every game. Its release is the breaker's (release_theirs).

class CBreakableObject;
class NET_Packet;

namespace coop
{
	void update_props(); // per frame: things that came to rest here
	void apply_prop_rest(u32 sender, NET_Packet& P); // M_ACTOR_ACTION ePropRest
	void note_moved(u16 id); // its next rest goes to the others, even its first (our actor dropped it, loot we shared)
	// a door whose place its logic decides (a ph_door with a motor: open or closed is a fact, coop_physics.script):
	// its rests aren't sent
	void set_by_logic(u16 id, bool on);

	void on_glass_broken(CBreakableObject& glass); // CBreakableObject::Break, broken here
	void apply_glass_break(NET_Packet& P);          // M_ACTOR_ACTION eGlassBreak

	// An object another game destroyed and we destroy too (a box or a pane it broke): its release is that game's, ours
	// isn't sent (coop_world.cpp on_object_released)
	void release_theirs(u16 id);
	bool is_release_theirs(u16 id); // and forgets it
}
