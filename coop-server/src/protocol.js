// Wire format shared with the engine (src/xrGame/coop/coop_net.h):
// u32 size | NET_Packet bytes (u16 type | payload), little-endian.

export const PROTOCOL_VERSION = 4;

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
};

const MAX_MESSAGE_SIZE = 16 * 1024; // NET_PacketSizeLimit

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

export function stringZ(str) {
  return Buffer.concat([Buffer.from(str, 'utf8'), Buffer.from([0])]);
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
  return buf.toString('utf8', offset, end === -1 ? buf.length : end);
}
