import net from 'node:net';
import { M, PROTOCOL_VERSION, encode, createDecoder, readStringZ, stringZ, u32 } from './protocol.js';

export function startServer({ port = 7777, host = '0.0.0.0', log = console.log } = {}) {
  let nextId = 1;
  const clients = new Map(); // id -> { send, name, state }

  const broadcast = (fromId, type, payload) => {
    for (const [id, c] of clients) if (id !== fromId) c.send(type, payload);
  };
  const peerState = (id, c) => Buffer.concat([u32(id), stringZ(c.name), c.state]);

  const server = net.createServer((socket) => {
    socket.setNoDelay(true);
    const id = nextId++;
    const addr = `${socket.remoteAddress}:${socket.remotePort}`;
    const send = (type, payload) => socket.write(encode(type, payload));
    let client = null; // set after HELLO

    const handle = (type, payload) => {
      if (!client && type !== M.HELLO) {
        log(`[${id}] message ${type} before HELLO, dropping`);
        socket.destroy();
        return;
      }
      switch (type) {
        case M.HELLO: {
          const version = payload.readUInt16LE(0);
          if (version !== PROTOCOL_VERSION) {
            log(`[${id}] protocol mismatch: client ${version}, server ${PROTOCOL_VERSION}`);
            socket.destroy();
            return;
          }
          client = { send, name: readStringZ(payload, 2), state: null };
          clients.set(id, client);
          log(`[${id}] '${client.name}' joined from ${addr} (${clients.size} online)`);
          send(M.WELCOME, u32(id));
          // let the newcomer see players who are standing still
          for (const [otherId, other] of clients)
            if (otherId !== id && other.state) send(M.PEER_STATE, peerState(otherId, other));
          break;
        }
        case M.PING:
          send(M.PONG, payload.subarray(0, 4));
          break;
        case M.ACTOR_STATE:
          client.state = Buffer.from(payload);
          broadcast(id, M.PEER_STATE, peerState(id, client));
          break;
        default:
          log(`[${id}] unknown message type ${type}`);
      }
    };

    const decode = createDecoder(handle);
    socket.on('data', (chunk) => {
      try {
        decode(chunk);
      } catch (e) {
        log(`[${id}] ${e.message}, dropping`);
        socket.destroy();
      }
    });
    socket.on('error', () => {}); // 'close' follows and reports
    socket.on('close', () => {
      if (!clients.delete(id)) return;
      log(`[${id}] '${client.name}' left (${clients.size} online)`);
      broadcast(id, M.PEER_LEFT, u32(id));
    });
  });

  return new Promise((resolve) => {
    server.listen(port, host, () => {
      log(`coop server listening on ${host}:${server.address().port}`);
      resolve(server);
    });
  });
}
