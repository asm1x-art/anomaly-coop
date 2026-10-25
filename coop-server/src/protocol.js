// Wire format shared with the engine (src/xrGame/coop/coop_net.h):
// u32 size | NET_Packet bytes (u16 type | payload), little-endian.

export const PROTOCOL_VERSION = 15;

// engine id generator (xrServer::id_generator_type): ids 0..65534 in 256 blocks of 256
export const ID_BLOCK_COUNT = 256;
export const NO_BLOCK = 0xffff;

export const M = {
  HELLO: 1,   // c->s: u16 protocol version, stringZ name
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
  GROUP: 26,          // c->s: u8 GROUP action, then u32 peer id (INVITE, ACCEPT, DECLINE) or stringZ name (KICK);
                      // INVITE then u8 1 when sent from the PDA (answered there, later)
  GROUP_INVITE: 27,   // s->c: u32 inviter id, stringZ inviter name, u8 1 from the PDA
  GROUPS: 28,         // s->c: u8 count, per group u8 size and the names, leader first; to all on every change
  GROUP_NOTE: 29,     // s->c: u8 GROUP_NOTE, stringZ the other player's name: why an invite came to nothing
  // the world's saves (storage.js): every upload is one, the last is the world
  LEFT_WORLD: 32,     // c->s: our game went back to the main menu, still connected
  SAVE_REQUEST: 33,   // c->s: stringZ name ('' for a quick save): save the world now
  SAVE_NOW: 34,       // s->c, to the sim master: stringZ name, reason, who: save now, the upload carries them back
  SAVES_REQUEST: 35,  // c->s: the list of saves, please
  SAVES: 36,          // s->c: u16 count, newest first (at most MAX_SAVES_LISTED), each u32 revision, u32 time (unix s),
                      // stringZ name, reason, who, u32 the revision it went back to (rollback) or 0
  ROLLBACK_PROPOSE: 37, // c->s: u32 revision: take the world back to that save, if everyone agrees
  ROLLBACK_VOTE: 38,  // s->c, to all: u32 proposer id, stringZ proposer name, u32 revision, u32 time, stringZ name, reason
  ROLLBACK_ANSWER: 39, // c->s: u8 1 yes, 0 no: the answer to whatever vote is on (a rollback, a pause)
  ROLLBACK_RESULT: 40, // s->c, to all: u8 ROLLBACK result, stringZ the player it came to (said no, didn't answer, left),
                      // u32 the world's new revision (ACCEPTED)
  WORLD_RELOAD: 41,   // s->c: the world went back to a save: a game running it loads it again (WORLD_INFO follows)
  // pausing the world: everyone in it agrees, as with a rollback
  PAUSE_PROPOSE: 42,  // c->s: u8 1 pause, 0 go on
  PAUSE_VOTE: 43,     // s->c, to all: u32 proposer id, stringZ proposer name, u8 1 pause, 0 go on
  PAUSE_RESULT: 44,   // s->c, to all: u8 ROLLBACK result, stringZ the player it came to, u8 1 pause, 0 go on
  PAUSED: 45,         // s->c: u8 paused, stringZ who asked for it; to all on every change, and after WELCOME
  REFUSED: 31,        // s->c: u8 REFUSED reason, u16 the server's player limit or protocol version; then it closes
  WORLD_CLAIM: 30,    // c->s: u8 1: this player starts the world on an empty server, the first to ask gets it
                      // (WORLD_INFO); 0: they gave it up
};

export const REFUSED = { FULL: 0, VERSION: 1 };
export const ROLLBACK = { ACCEPTED: 0, DECLINED: 1, TIMEOUT: 2, CANCELLED: 3, BUSY: 4 };
export const MAX_SAVES_LISTED = 200;
export const GROUP = { INVITE: 0, ACCEPT: 1, DECLINE: 2, LEAVE: 3, KICK: 4 };
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
