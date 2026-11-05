// Wire format shared with the engine (src/xrGame/coop/coop_net.h):
// u32 size | NET_Packet bytes (u16 type | payload), little-endian.

export const PROTOCOL_VERSION = 25;

// engine id generator (xrServer::id_generator_type): ids 0..65534 in 256 blocks of 256
export const ID_BLOCK_COUNT = 256;
export const NO_BLOCK = 0xffff;

export const M = {
  HELLO: 1,   // c->s: u16 protocol version, stringZ name, stringZ build id ("dev" without the launcher: builds.js),
              // u8 1 for the world's host (else 0), stringZ the host's secret
  WELCOME: 2, // s->c: u32 client id
  PING: 3,    // c->s: u32 client time (ms), u32 the client's last round trip (ms), for the admin page
  PONG: 4,    // s->c: u32 echoed client time (ms)
  ACTOR_STATE: 5, // c->s: stringZ level, vec3 position (f32 x, y, z), f32 yaw
  PEER_STATE: 6,  // s->c: u32 id, stringZ name, then ACTOR_STATE payload
  PEER_LEFT: 7,   // s->c: u32 id
  ENTITY_DEATH: 8, // c->s->others: u16 object id, stringZ section, u16 killer id, where the body lies (vec3, u16, u32)
  ID_BLOCK_REQUEST: 9, // c->s: u16 free ids per id block, for all ID_BLOCK_COUNT blocks
  ID_BLOCK_GRANT: 10,  // s->c: u16 block leased to this player, NO_BLOCK when none are left
  // world changes relayed with the sender's client id in front (s->c: u32 sender id, then the c->s payload)
  ITEM_PARENT: 11,    // c->s: u16 item, stringZ section, u8 place (PLACE), place data
  OBJECT_RELEASE: 12, // c->s: u16 object, stringZ section
  OBJECT_SPAWN: 13,   // c->s: u16 size, the engine's M_SPAWN packet for the new object
  OBJECT_STATE: 50,   // c->s: u16 size, M_SPAWN packet, u16 size, client data, stringZ Lua data: an item of the player's as it is now
  SCRIPT_EVENT: 14,   // c->s: stringZ name, stringZ payload (Lua-level state sync), relayed like the above
  ROLES: 15,          // s->c: u32 sim master id (the longest-connected player), sent to all on every join/leave
  // The shared world is a save stored on the server (storage.js). Files go in chunks both ways.
  WORLD_INFO: 16,     // s->c: u8 has world, stringZ owner, u32 revision, stringZ who is creating it ('' if nobody);
                      // after WELCOME and to all on every upload and claim
  WORLD_REQUEST: 17,  // c->s: send me the world
  WORLD_UPLOAD: 18,   // c->s: u32 size per world file (WORLD_FILES order), u32 the revision the game runs (0: a new
                      // world), stringZ name, reason, who (storage.js meta.json); only from the sim master, or into
                      // an empty server from whoever claimed it
  WORLD_CHUNK: 19,    // both: u8 file, u32 offset, data
  WORLD_DONE: 20,     // c->s: upload complete; s->c: download complete, stringZ owner, u32 revision
  CHARACTER: 21,      // c->s: the player's own record (opaque here); s->c: that record, right after WELCOME
  SETTINGS: 22,       // s->c: stringZ "key=value" lines (settingsText), after WELCOME and to all when they change
  ACTOR_ACTION: 23,   // c->s: what the player's actor does (shots...), for the others' puppets; relayed like the above
  NPC_STATES: 24,     // c->s: the level authority's online NPCs, for the others' NPC puppets; relayed like the above
  COOP_HIT: 25,       // c->s: a hit for another game (an NPC it runs, a player's stand-in) or a grudge; relayed like the above
  // groups of players (server.js keeps them, by character name)
  GROUP: 26,          // c->s: u8 GROUP action, then u32 peer id (INVITE, ACCEPT, DECLINE) or stringZ name (KICK)
                      // or u8 1/0 (STORY, the leader only); INVITE then u8 1 when sent from the PDA (answered
                      // there, later)
  GROUP_INVITE: 27,   // s->c: u32 inviter id, stringZ inviter name, u8 1 from the PDA
  GROUPS: 28,         // s->c: u8 count, per group u8 size, the names (leader first), u8 GROUP_FLAG bits; to all on
                      // every change
  GROUP_NOTE: 29,     // s->c: u8 GROUP_NOTE, stringZ the other player's name: why an invite came to nothing
  // The world's saves (storage.js) are the sim master's uploads, the last is the world. The players save their
  // characters (docs/coop/multiplayer.md «Сохранения»): a character's save is a snapshot its game makes, a group's
  // leader saves and loads the whole group; the world never goes back for them.
  LEFT_WORLD: 32,     // c->s: our game went back to the main menu, still connected
  SAVE_REQUEST: 33,   // c->s: stringZ name ('' for a quick save): save my character (a group's leader: the group's);
                      // AUTO_SAVE_NAME: my character's autosave, its own even in a group, one per character
  SAVE_NOW: 34,       // s->c, to the sim master: stringZ name, reason, who: save the world now, the upload carries them
  SAVES_REQUEST: 35,  // c->s: the list of my character's saves, please
  SAVES: 36,          // s->c: u16 count, newest first (at most MAX_SAVES_LISTED), each u32 id, u32 time (unix s),
                      // stringZ name, reason ('quick', 'named', 'group', 'auto', 'exit'), who (the one who saved it), u32 0
  LOAD_REQUEST: 37,   // c->s: u32 id: my character (a group's save: the whole group, the leader asks) as that save has it;
                      // id 0: died with nobody to help: my character alone as my newest save but the exit save has it
                      // (the autosave counts)
  // 38: was a world rollback's vote
  ROLLBACK_ANSWER: 39, // c->s: u8 1 yes, 0 no: the answer to whatever vote is on (a pause)
  LOAD_RESULT: 40,    // s->c: u8 LOAD result, u32 the save's id
  WORLD_RELOAD: 41,   // s->c: the world, or our character in it, went back to a save: a game running it loads it again
                      // (WORLD_INFO follows)
  // pausing the world: everyone in it agrees, as with a rollback
  PAUSE_PROPOSE: 42,  // c->s: u8 1 pause, 0 go on
  PAUSE_VOTE: 43,     // s->c, to all: u32 proposer id, stringZ proposer name, u8 1 pause, 0 go on
  PAUSE_RESULT: 44,   // s->c, to all: u8 ROLLBACK result, stringZ the player it came to, u8 1 pause, 0 go on
  PAUSED: 45,         // s->c: u8 paused, stringZ who asked for it; to all on every change, and after WELCOME
  // a player's own progress (tasks, story, rank...: src/xrGame/coop/coop_progress.cpp), opaque here, kept per
  // character with every save (storage.js)
  PROGRESS_REQUEST: 46, // s->c, to all in the world when it is to be saved: send your progress
  PROGRESS: 47,       // both: u32 total size, u32 offset, data (chunks of at most CHUNK_SIZE, offset 0 first); c->s
                      // the player's progress, s->c theirs right before WORLD_DONE (total 0: none kept)
  LOG: 48,            // c->s: stringZ file name, u32 size, u32 packed size (zlib), u32 offset, data: a log or crash
                      // dump of the player's game (storage.js data/logs), offset 0 first
  // Facts about the world the server keeps itself (storage.js facts.json): world infos, faction relations...
  // A game reports a change, the server keeps it and passes it on; a game loading the world gets them all.
  FACT: 49,           // both: stringZ key ("info:<name>", "rel:<faction>:<faction>"...), stringZ value ('' gone);
                      // s->c also every one kept, right before WORLD_DONE. "once:" keys: the first value stays, and
                      // the one who reported gets the fact back either way (theirs: it's theirs; another: it isn't)
  REFUSED: 31,        // s->c: u8 REFUSED reason, u16 the server's player limit or protocol version (0 for BUILD); then
                      // it closes
  WORLD_CLAIM: 30,    // c->s: u8 1: this player starts the world on an empty server, the first to ask gets it
                      // (WORLD_INFO); 0: they gave it up
  LEVELS: 51,         // s->c: u8 count, per level with players on it stringZ level, u32 its authority: the player
                      // there longest (the first to come); to all on every change
  HOST: 52,           // s->c: u32 the world's host (0: none), stringZ its name; after WELCOME and to all on every change.
                      // The host (the game the server started with -coop_host) is the sim master whenever it is in the
                      // world, and no player: no PEER_STATE, no level, no group, no say in votes
  // Joining: the world's last save comes with the changes made since (the journal); the game replays them while
  // it loads, so nobody saves for a player to come in or go
  JOURNAL: 53,        // s->c: a world change made since the save: u16 type, then the message as it was relayed;
                      // after the facts, before WORLD_DONE
  NAMES: 54,          // s->c: u16 count, per player u32 id, stringZ name: everyone of this server run (the journal's
                      // changes are by ids, some of players gone), before the journal
  SNAPSHOT_REQUEST: 55, // s->c: u32 save id: send a snapshot of your character for that save
  SNAPSHOT: 56,       // c->s: u32 save id, u32 total size, u32 offset, data (offset 0 first): u32 size, the character's
                      // record (as CHARACTER); u32 size, its progress (as PROGRESS); then its things (the game's own)
  SNAPSHOT_THINGS: 57, // s->c: u32 total size, u32 offset, data: the things of the save the character was put back to,
                      // with the world (before WORLD_DONE), once
  // The in-game admin window (ui_coop_admin.script): the admin page's password, then what the page and the bot do
  ADMIN_LOGIN: 58,    // c->s: stringZ the admin password: ADMIN_STATE back, or ADMIN_RESULT saying it is wrong
  ADMIN_STATE: 59,    // s->c: stringZ lines of tab-split fields: host <text> | world <revision> <owner> | player <name>
                      // <level> <ping> <1: runs its level> | setting <world|rules> <key> <value> <min> <max> <title> |
                      // faction <id> <1: allowed> <title> | save <revision> <unix time> <text>
  ADMIN_COMMAND: 60,  // c->s: stringZ tab-split: state | set <key> <value> | faction <id> <on|off> | save | restart_host |
                      // kick <name> | rollback <revision>; ADMIN_RESULT (but for state), then ADMIN_STATE back
  ADMIN_RESULT: 61,   // s->c: stringZ what happened, as the admin reads it (Russian)
  // the world's clock (clock.js): every game in the world runs the server's game time
  TIME: 62,           // s->c: u64 game time (ms), f32 factor, u8 TIME_FLAG bits, u32 epoch; after WELCOME, to all on
                      // every change and every TIME_TICK_MS
  TIME_SET: 63,       // c->s: u8 TIME_SET kind, then INIT: u64 game time, f32 factor (taken only while the server has
                      // no clock); JUMP: u32 ms forward; FACTOR: f32 (the sim master's only)
  // A player's exit save and their things going back (docs/coop/multiplayer.md «Сохранения»)
  TAKEN: 64,          // c->s: where our actor took a thing from: u16 thing, stringZ its section, u8 TAKEN_FROM, then
                      // OBJECT: u16 holder, stringZ its section; both: vec3 where, u16 game vertex, u32 level vertex,
                      // stringZ level. Kept per character (storage.js taken); going back to a save, the ones taken
                      // since come after its things (SNAPSHOT_THINGS) and those things go back there
  SAVE_CHOICE: 65,    // s->c: as SAVES, after WELCOME and before WORLD_INFO, when the character has an exit save and
                      // another to choose from: the game asks the player which (LOAD_REQUEST, or none), then the world
  EXIT_THINGS_REQUEST: 66, // s->c, to the host: u32 save id, stringZ name: the things that player's shadow holds
  EXIT_THINGS: 67,    // c->s, the host: u32 save id, u32 total, u32 offset, data (u16 count, per thing u16 size and
                      // its state as OBJECT_STATE has it): with the record and progress the server has, the exit save
};

export const TAKEN_FROM = { GROUND: 0, OBJECT: 1 };
export const EXIT_SAVE_NAME = 'выход';
export const AUTO_SAVE_NAME = 'авто'; // a character's autosave (coop_autosave.script): its game asks for it by this name

export const TIME_FLAG = { RUNNING: 1, SET: 2 };
export const TIME_SET = { INIT: 0, JUMP: 1, FACTOR: 2 };
export const TIME_TICK_MS = 5000;

export const REFUSED = { FULL: 0, VERSION: 1, BUILD: 2, HOST: 3 }; // HOST: a wrong secret, or a host is there already
export const ROLLBACK = { ACCEPTED: 0, DECLINED: 1, TIMEOUT: 2, CANCELLED: 3, BUSY: 4 }; // a vote's result (a pause)
export const LOAD = { DONE: 0, NO_SAVE: 1, LEADER_ONLY: 2 }; // LEADER_ONLY: a group's save, the leader loads it
export const MAX_SAVES_LISTED = 200;
export const GROUP = { INVITE: 0, ACCEPT: 1, DECLINE: 2, LEAVE: 3, KICK: 4, STORY: 5 };
export const GROUP_FLAG = { STORY: 1 }; // the group shares its story (coop_story.script)
export const GROUP_NOTE = { DECLINED: 0, FULL: 1, ALREADY: 2, EXPIRED: 3 };

const MAX_MESSAGE_SIZE = 16 * 1024; // NET_PacketSizeLimit
export const CHUNK_SIZE = 15000; // file data per WORLD_CHUNK, fits a NET_Packet with its header

export function encode(type, payload = Buffer.alloc(0)) {
  const frame = Buffer.alloc(6 + payload.length);
  frame.writeUInt32LE(2 + payload.length, 0);
  frame.writeUInt16LE(type, 4);
  payload.copy(frame, 6);
  return frame;
}

// Feeds raw socket chunks, calls onMessage(type, payload) per complete frame.
export function createDecoder(onMessage) {
  let pending = Buffer.alloc(0);
  return (chunk) => {
    pending = pending.length ? Buffer.concat([pending, chunk]) : chunk;
    while (pending.length >= 4) {
      const size = pending.readUInt32LE(0);
      if (size < 2 || size > MAX_MESSAGE_SIZE) throw new Error(`bad message size ${size}`);
      if (pending.length < 4 + size) break;
      onMessage(pending.readUInt16LE(4), pending.subarray(6, 4 + size));
      pending = pending.subarray(4 + size);
    }
  };
}

// The engine's strings are Windows-1251 bytes (player names can be Cyrillic); here they are JS strings.
const CP1251 = new TextDecoder('windows-1251');
const CP1251_BYTE = new Map([...CP1251.decode(Uint8Array.from({ length: 256 }, (_, i) => i))].map((ch, i) => [ch, i]));

export function encodeText(str) {
  return Buffer.from([...str].map((ch) => CP1251_BYTE.get(ch) ?? 0x3f)); // '?' for what 1251 can't hold
}

export function stringZ(str) {
  return Buffer.concat([encodeText(str), Buffer.from([0])]);
}

export function u16(value) {
  const b = Buffer.alloc(2);
  b.writeUInt16LE(value, 0);
  return b;
}

export function u32(value) {
  const b = Buffer.alloc(4);
  b.writeUInt32LE(value, 0);
  return b;
}

export function readStringZ(buf, offset) {
  const end = buf.indexOf(0, offset);
  return CP1251.decode(buf.subarray(offset, end === -1 ? buf.length : end));
}

// count zero-terminated strings one after another from offset; '' for those the buffer runs out before
export function readStringsZ(buf, offset, count) {
  const out = [];
  for (let i = 0; i < count; i++) {
    const end = offset < buf.length ? buf.indexOf(0, offset) : -1;
    out.push(offset < buf.length ? CP1251.decode(buf.subarray(offset, end === -1 ? buf.length : end)) : '');
    offset = end === -1 ? buf.length : end + 1;
  }
  return out;
}
