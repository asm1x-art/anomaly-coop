import net from 'node:net';
import { M, PROTOCOL_VERSION, ID_BLOCK_COUNT, NO_BLOCK, encode, createDecoder, readStringZ, stringZ, u16, u32 } from './protocol.js';

export function startServer({ port = 7777, host = '0.0.0.0', log = console.log } = {}) {
  let nextId = 1;
  const clients = new Map(); // id -> { send, name, state }
  // id block -> player name. Leases follow the name, so a player who reconnects
  // gets the same blocks back and keeps owning the objects created with them.
  const idLeases = new Map();

  const leaseBlock = (name, freeCounts) => {
    let best = -1;
    for (let block = 0; block < ID_BLOCK_COUNT; block++) {
      if (idLeases.has(block) || freeCounts[block] === 0) continue;
      if (best === -1 || freeCounts[block] > freeCounts[best]) best = block;
    }
    if (best !== -1) idLeases.set(best, name);
    return best;
  };

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
          for (const [block, owner] of idLeases) if (owner === client.name) send(M.ID_BLOCK_GRANT, u16(block));
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
        case M.ID_BLOCK_REQUEST: {
          const freeCounts = [];
          for (let block = 0; block < ID_BLOCK_COUNT; block++) freeCounts.push(payload.readUInt16LE(block * 2));
          const block = leaseBlock(client.name, freeCounts);
          if (block === -1) log(`[${id}] '${client.name}' asked for an id block, none left`);
          else log(`[${id}] '${client.name}' leased id block ${block} (${freeCounts[block]} free)`);
          send(M.ID_BLOCK_GRANT, u16(block === -1 ? NO_BLOCK : block));
          break;
        }
        case M.ENTITY_DEATH:
          broadcast(id, type, Buffer.from(payload));
          break;
        case M.ITEM_PARENT:
        case M.OBJECT_RELEASE:
        case M.OBJECT_SPAWN:
          // receivers need to know whose actor "the sender's actor" is
          broadcast(id, type, Buffer.concat([u32(id), payload]));
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
