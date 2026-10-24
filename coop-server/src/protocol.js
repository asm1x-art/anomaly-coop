// Wire format shared with the engine (src/xrGame/coop/coop_net.h):
// u32 size (of type + payload) | u16 type | payload, little-endian.

export const PROTOCOL_VERSION = 1;

export const M = {
  HELLO: 1,   // c->s: u16 protocol version, stringZ name
  WELCOME: 2, // s->c: u32 client id
  PING: 3,    // c->s: u32 client time (ms)
  PONG: 4,    // s->c: u32 echoed client time (ms)
};

const MAX_MESSAGE_SIZE = 1024 * 1024;

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

export function readStringZ(buf, offset) {
  const end = buf.indexOf(0, offset);
  return buf.toString('utf8', offset, end === -1 ? buf.length : end);
}
