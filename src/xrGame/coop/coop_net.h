#pragma once

// Co-op network channel: TCP connection to the coop world server.
// Wire format: u32 size | NET_Packet bytes (u16 type | payload), little-endian.

#include <functional>

struct lua_State;

namespace coop
{
	enum EMessage : u16
	{
		M_HELLO = 1,       // c->s: u16 protocol version, stringZ name, stringZ build id (launcher's, "dev" without one),
		                   // u8 1 for the host (else 0), stringZ the host's secret
		M_WELCOME = 2,     // s->c: u32 client id
		M_PING = 3,        // c->s: u32 client time (ms), u32 our last round trip (ms), for the server's admin page
		M_PONG = 4,        // s->c: u32 echoed client time (ms)
		M_ACTOR_STATE = 5, // c->s: stringZ level, vec3 position, float yaw, then SLook (coop_puppet.cpp)
		M_PEER_STATE = 6,  // s->c: u32 id, stringZ name, then M_ACTOR_STATE payload
		M_PEER_LEFT = 7,   // s->c: u32 id
		M_ENTITY_DEATH = 8, // c->s->others: u16 object id, stringZ section, u16 killer id, where the body lies
		                    // (vec3, u16 game vertex, u32 level vertex)
		M_ID_BLOCK_REQUEST = 9, // c->s: u16 free ids per id block (all blocks, as the client sees them)
		M_ID_BLOCK_GRANT = 10,  // s->c: u16 block leased to this player, u16(-1) when none are left
		// relayed to the others with the sender's client id in front (s->c: u32 sender, then the payload)
		M_ITEM_PARENT = 11,     // c->s: u16 item, stringZ section, u8 place, place data (coop_world.cpp)
		M_OBJECT_RELEASE = 12,  // c->s: u16 object, stringZ section
		M_OBJECT_SPAWN = 13,    // c->s: u16 size, the engine's M_SPAWN packet (CSE_Abstract::Spawn_Write)
		M_SCRIPT_EVENT = 14,    // c->s: stringZ name, stringZ payload; Lua-level state, see coop.send_event
		M_ROLES = 15,           // s->c: u32 sim master id, on every join/leave
		// the shared world, a save kept by the server (coop_save.cpp); files go in chunks
		M_WORLD_INFO = 16,      // s->c: u8 has world, stringZ owner, u32 revision, stringZ who is creating it ("" if nobody)
		M_WORLD_REQUEST = 17,   // c->s: send me the world
		M_WORLD_UPLOAD = 18,    // c->s: u32 size per file (.scop, .scoc), u32 revision we run, stringZ name, reason, who
		M_WORLD_CHUNK = 19,     // both: u8 file, u32 offset, data
		M_WORLD_DONE = 20,      // c->s: upload complete; s->c: stringZ owner, u32 revision
		M_CHARACTER = 21,       // both: stringZ level, u16 game vertex, u32 level vertex, vec3 position, float yaw, u32 money, float health
		M_SETTINGS = 22,        // s->c: stringZ "key=value" lines, world settings and allowed factions (coop-server/src/settings.js)
		M_ACTOR_ACTION = 23,    // c->s: u8 EActorAction, its data; relayed with the sender's id like M_ITEM_PARENT (coop_puppet.cpp)
		M_NPC_STATES = 24,      // c->s: stringZ level, u16 count, NPC states; the level's authority, relayed the same way (coop_npc.cpp)
		M_COOP_HIT = 25,        // c->s: u8 kind, u32 target, SHit, a grudge or a fall; for the other games, relayed the same way (coop_combat.cpp)
		// groups of players, kept by the server by character name (coop-server/src/server.js)
		M_GROUP = 26,           // c->s: u8 EGroupAction, u32 peer id (invite, accept, decline) or stringZ name (kick)
		M_GROUP_INVITE = 27,    // s->c: u32 inviter id, stringZ inviter name
		M_GROUPS = 28,          // s->c: u8 count, per group u8 size and the names, leader first; on every change
		M_GROUP_NOTE = 29,      // s->c: u8 why an invite came to nothing (declined, full, already, expired), stringZ name
		// The world's saves are the sim master's uploads (coop-server/src/storage.js, coop_save.cpp). The players save
		// their characters: a snapshot of ours, made when the server asks; a group's leader saves the whole group
		M_LEFT_WORLD = 32,      // c->s: our game went back to the main menu, still connected
		M_SAVE_REQUEST = 33,    // c->s: stringZ name ("" quick): save our character (a group's leader: the group)
		M_SAVE_NOW = 34,        // s->c, to the sim master: stringZ name, reason, who: save the world, the upload carries them
		M_SAVES_REQUEST = 35,   // c->s: the list of our character's saves
		M_SAVES = 36,           // s->c: u16 count, newest first: u32 id, u32 time, stringZ name, reason, who, u32 0
		M_LOAD_REQUEST = 37,    // c->s: u32 id: our character (a group's save: the group, its leader asks) as that save has it
		M_ROLLBACK_ANSWER = 39, // c->s: u8 yes, to whatever vote is on (a pause)
		M_LOAD_RESULT = 40,     // s->c: u8 result (0 done, 1 no such save, 2 a group's save: its leader loads it), u32 id
		M_WORLD_RELOAD = 41,    // s->c: the world, or our character in it, went back to a save: a game running it loads it
		                        // again
		// pausing the world: everyone in it agrees (as M_ROLLBACK_*; M_ROLLBACK_ANSWER answers any vote)
		M_PAUSE_PROPOSE = 42,   // c->s: u8 1 pause, 0 go on
		M_PAUSE_VOTE = 43,      // s->c: u32 proposer id, stringZ proposer, u8 1 pause, 0 go on
		M_PAUSE_RESULT = 44,    // s->c: u8 result (as M_ROLLBACK_RESULT), stringZ who, u8 1 pause, 0 go on
		M_PAUSED = 45,          // s->c: u8 paused, stringZ the one who asked; to all on every change, after WELCOME
		M_PROGRESS_REQUEST = 46, // s->c, to all in the world when it is to be saved: send our progress (coop_progress.h)
		M_PROGRESS = 47,        // both: u32 total size, u32 offset, data; c->s our progress, s->c ours with the world,
		                        // before M_WORLD_DONE (total 0: none kept)
		M_OBJECT_STATE = 50,    // c->s: u16 size, the object's M_SPAWN packet (Spawn_Write), u16 size, its client data,
		                        // stringZ its Lua data: an item of ours as it is now (condition, upgrades, ammo, uses...);
		                        // relayed like the above
		M_FACT = 49,            // both: stringZ key, stringZ value ("" gone): a fact about the world (coop_facts.h); s->c
		                        // also each one the server keeps, before M_WORLD_DONE
		M_LOG = 48,             // c->s: stringZ file name, u32 size, u32 packed size (zlib), u32 offset, data: a log
		                        // or crash dump of ours, for the server's data/logs (coop_logs.h)
		M_REFUSED = 31,         // s->c: u8 why (0 full, 1 protocol, 2 build not let in, 3 host turned away), u16 the player limit or the
		                        // server's protocol (0 for a build); it closes
		M_WORLD_CLAIM = 30,     // c->s: u8 1: we start the world on an empty server, the first to ask gets it (M_WORLD_INFO
		                        // says who); 0: we gave it up
		M_LEVELS = 51,          // s->c: u8 count, per level with players on it stringZ level, u32 its authority (the one
		                        // there longest); to all on every change
		M_HOST = 52,            // s->c: u32 the world's host (0: none), stringZ its name; after M_WELCOME and to all on every
		                        // change. Not a player: no M_PEER_STATE, but the world changes it sends are applied
		// Joining: the world's last save comes with the changes made since (the journal), replayed while it loads
		// (coop_world.h replay_journal); no game saves for a player to come in
		M_JOURNAL = 53,         // s->c: a world change made since the save (u16 type, then as relayed), before M_WORLD_DONE
		M_NAMES = 54,           // s->c: u16 count, u32 id, stringZ name: every player and host of this server run, before
		                        // the journal (its changes are by ids, some of players gone)
		M_SNAPSHOT_REQUEST = 55, // s->c: u32 save id: a snapshot of our character for it (coop_save.cpp)
		M_SNAPSHOT = 56,        // c->s: u32 save id, u32 total, u32 offset, data: u32 size, our record (as M_CHARACTER);
		                        // u32 size, our progress (as M_PROGRESS); u16 count, per thing we carry u16 size and its
		                        // state (as M_OBJECT_STATE)
		M_SNAPSHOT_THINGS = 57, // s->c: u32 total, u32 offset, data: the things of the save our character went back to,
		                        // with the world (before M_WORLD_DONE), once
		// the in-game admin window (ui_coop_admin.script), behind the server's admin password
		M_ADMIN_LOGIN = 58,     // c->s: stringZ password
		M_ADMIN_STATE = 59,     // s->c: stringZ lines of tab-split fields (coop-server/src/protocol.js): _G.coop_on_admin_state
		M_ADMIN_COMMAND = 60,   // c->s: stringZ tab-split command
		M_ADMIN_RESULT = 61,    // s->c: stringZ what happened: _G.coop_on_admin_result
		// the world's clock (coop_time.h)
		M_TIME = 62,            // s->c: u64 game time (ms), float factor, u8 flags (1 running, 2 set), u32 epoch (grows
		                        // with every jump); after WELCOME, on every change and every 5 s
		M_TIME_SET = 63,        // c->s: u8 kind, then 0 (no clock yet): u64 game time, float factor; 1 jump: u32 ms;
		                        // 2 factor (the sim master's): float
	};

	enum EGroupAction : u8
	{
		eGroupInvite,
		eGroupAccept,
		eGroupDecline,
		eGroupLeave,
		eGroupKick,
		eGroupStory, // the leader: the group shares its story or stops (coop_story.script)
	};

	const u16 PROTOCOL_VERSION = 25;

	// How a peer's character looks and moves, for its puppet (coop_puppet.cpp)
	struct SLook
	{
		enum EFlags : u8
		{
			eReloading = 1 << 0, // the weapon in hands reloads: held by the right hand only
			eTorch = 1 << 1,
			eDead = 1 << 2,      // nothing to stand in for: no stand-in, no puppet
			eDowned = 1 << 3,    // lying wounded for others to help up (coop_death.script): NPCs leave them be
		};

		float look_pitch = 0.f;                             // the camera's, with SPeer::yaw where the player looks
		float body_yaw = 0.f;                               // the actor's model turns by rotateY(body_yaw)
		float torso_yaw = 0.f, torso_pitch = 0.f, torso_roll = 0.f; // where it looks: spine and head follow
		u16 legs = u16(-1), torso = u16(-1), head = u16(-1); // motions, as indices into puppet_motion_names()
		u8 torso_seq = 0;                                   // bumped whenever the torso motion starts again
		shared_str visual;                                  // third-person model, the outfit's
		shared_str item;                                    // section of the item in hands, "" for none
		u8 item_addons = 0;                                 // CWeapon addon flags
		u8 flags = 0;
		shared_str community;                               // "actor_<faction>": the faction NPCs judge it by
		u8 luminocity = 255;                                // how lit the actor is in its own game, 0..255: NPCs
		                                                    // see its stand-in by it, never drawn to be lit here
	};

	struct SPeer
	{
		xr_string name;
		shared_str level;
		Fvector position;
		float yaw;
		u32 last_update; // Device.dwTimeContinual
		bool has_look = false;
		SLook look;
	};

	using peers_t = xr_map<u32, SPeer>;

	bool connect(LPCSTR host, u16 port, LPCSTR name);
	void disconnect();
	void print_status();

	// coop_debug 1: every co-op part logs in detail (the nearest NPC's motions, NPC meets, script events,
	// messages sent and received every 5 s); Lua reads it as get_console():get_integer("coop_debug")
	extern int debug_mode;

	bool is_connected();
	bool is_link_up(); // connecting or connected, welcomed or not
	void send(NET_Packet& P); // dropped unless connected

	// Exchange messages right now instead of on the next frame (frames don't run while a level loads).
	// Only the given message types are handled, the rest stays queued; false on timeout or lost link.
	bool wait_for_messages(const std::function<bool()>& done, u32 timeout_ms, std::initializer_list<u16> types);
	u32 my_id();
	u32 ping_ms(); // the last round trip to the server, 0 before the first
	LPCSTR refusal(); // why the server turned the last connection away: "full", "version", "build" or ""
	// -coop_build <id> on the command line: the launcher's release this game is; "dev" without it
	LPCSTR build_id();
	// -coop_auto on the command line: the launcher started us to enter the profile on top of the list
	bool auto_launch();
	const xr_string& my_name();
	const peers_t& peers();

	// Who runs world logic. The sim master (the longest-connected player) runs offline A-Life and the
	// world of levels nobody is on; a level with players on it is run by the one who came to it first,
	// as the server says (M_LEVELS). Without a connection this client runs everything.
	bool is_sim_master();
	bool is_authority(const shared_str& level_name);

	// The world's headless host (-coop_host <secret>, docs/coop/multiplayer.md): the sim master whenever it runs,
	// never a player. Its actor is a ghost on fake_start; it saves the world.
	bool is_host();               // this game is the host
	bool host_runs_world();       // the host is the sim master: it runs the world
	bool is_host_id(u32 id);      // that client is the host
	const xr_string& host_name(); // "" while there is none
	LPCSTR player_name(u32 id);   // a player or the host of this server run, gone or not; "" if unknown
	LPCSTR server_address();      // "host:port" we connected to, "" before

	// the in-game admin window: the server's admin password, then its commands (coop-server/src/protocol.js ADMIN_*)
	void admin_login(LPCSTR password);
	void admin_command(LPCSTR command);

	// the journal that came with the world (M_JOURNAL), handed over once for the replay
	void take_journal(xr_vector<xr_vector<u8>>& out);
	// messages for OnFrame to handle before the ones waiting (the journal's script events, once the level runs)
	void defer_messages(xr_vector<xr_vector<u8>>& messages);
	// a new download of the world: the world changes waiting for a level are in its journal
	void drop_held_world_changes();

	// Groups of players: names, leader first. same_group: either may be my_id()
	const xr_vector<xr_string>* group_of(const xr_string& name);
	bool same_group(u32 a, u32 b);
	bool group_story(const xr_string& name); // that player's group shares its story
	void group_set_story(bool on);
	// pda: an invite sent from the PDA, answered there (coop_group.script), not in a box
	void group_request(EGroupAction action, u32 peer, LPCSTR name = "", bool pda = false);

	void script_register(lua_State* L);
}
