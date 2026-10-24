// Wire format shared with the engine (src/xrGame/coop/coop_net.h):
// u32 size | NET_Packet bytes (u16 type | payload), little-endian.

export const PROTOCOL_VERSION = 9;

// engine id generator (xrServer::id_generator_type): ids 0..65534 in 256 blocks of 256
export const ID_BLOCK_COUNT = 256;
export const NO_BLOCK = 0xffff;

export const M = {
  HELLO: 1,   // c->s: u16 protocol version, stringZ name
  WELCOME: 2, // s->c: u32 client id
  PING: 3,    // c->s: u32 client time (ms)
  PONG: 4,    // s->c: u32 echoed client time (ms)
  ACTOR_STATE: 5, // c->s: stringZ level, vec3 position (f32 x, y, z), f32 yaw
  PEER_STATE: 6,  // s->c: u32 id, stringZ name, then ACTOR_STATE payload
  PEER_LEFT: 7,   // s->c: u32 id
  ENTITY_DEATH: 8, // c->s->others: u16 object id, stringZ section, u16 killer id
  ID_BLOCK_REQUEST: 9, // c->s: u16 free ids per id block, for all ID_BLOCK_COUNT blocks
  ID_BLOCK_GRANT: 10,  // s->c: u16 block leased to this player, NO_BLOCK when none are left
  // world changes relayed with the sender's client id in front (s->c: u32 sender id, then the c->s payload)
  ITEM_PARENT: 11,    // c->s: u16 item, stringZ section, u8 place (PLACE), place data
  OBJECT_RELEASE: 12, // c->s: u16 object, stringZ section
  OBJECT_SPAWN: 13,   // c->s: u16 size, the engine's M_SPAWN packet for the new object
  SCRIPT_EVENT: 14,   // c->s: stringZ name, stringZ payload (Lua-level state sync), relayed like the above
  ROLES: 15,          // s->c: u32 sim master id (the longest-connected player), sent to all on every join/leave
  // The shared world is a save stored on the server (storage.js). Files go in chunks both ways.
  WORLD_INFO: 16,     // s->c: u8 has world, stringZ owner, u32 revision; after WELCOME and to all on every upload
  WORLD_REQUEST: 17,  // c->s: send me the world
  WORLD_UPLOAD: 18,   // c->s: u32 size per world file (WORLD_FILES order); only from the sim master, or into an empty server
  WORLD_CHUNK: 19,    // both: u8 file, u32 offset, data
  WORLD_DONE: 20,     // c->s: upload complete; s->c: download complete, stringZ owner, u32 revision
  CHARACTER: 21,      // c->s: the player's own record (opaque here); s->c: that record, right after WELCOME
  SETTINGS: 22,       // s->c: stringZ "key=value" lines (settingsText), after WELCOME and to all when they change
};

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
