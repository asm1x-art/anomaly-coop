import net from 'node:net';
import { M, PROTOCOL_VERSION, ID_BLOCK_COUNT, NO_BLOCK, CHUNK_SIZE, encode, createDecoder, readStringZ, stringZ, u16, u32 } from './protocol.js';
import { openStorage, WORLD_FILES } from './storage.js';
import { settingsText } from './settings.js';

export function startServer({ port = 7777, host = '0.0.0.0', dataDir = 'data', log = console.log } = {}) {
  const storage = openStorage(dataDir);
  let nextId = 1;
  const clients = new Map(); // id -> { send, name, state }
  // id block -> player name. Leases follow the name, so a player who reconnects
  // gets the same blocks back and keeps owning the objects created with them.
  const idLeases = storage.loadLeases();

  const leaseBlock = (name, freeCounts) => {
    let best = -1;
    for (let block = 0; block < ID_BLOCK_COUNT; block++) {
      if (idLeases.has(block) || freeCounts[block] === 0) continue;
      if (best === -1 || freeCounts[block] > freeCounts[best]) best = block;
    }
    if (best !== -1) {
      idLeases.set(best, name);
      storage.saveLeases(idLeases);
    }
    return best;
  };

  const broadcast = (fromId, type, payload) => {
    for (const [id, c] of clients) if (id !== fromId) c.send(type, payload);
  };
  const peerState = (id, c) => Buffer.concat([u32(id), stringZ(c.name), c.state]);
  // the sim master runs offline A-Life and world spawns for empty levels: the longest-connected
  // player, i.e. the lowest id, since ids only grow
  const masterId = () => Math.min(...clients.keys());
  const announceRoles = () => {
    if (!clients.size) return;
    for (const c of clients.values()) c.send(M.ROLES, u32(masterId()));
  };

  const worldInfo = () => {
    const info = storage.worldInfo();
    return Buffer.concat([Buffer.from([info ? 1 : 0]), stringZ(info?.owner ?? ''), u32(info?.revision ?? 0)]);
  };
  const sendWorld = (send) => {
    const info = storage.worldInfo();
    storage.readWorld().forEach((data, file) => {
      for (let offset = 0; offset < data.length; offset += CHUNK_SIZE)
        send(M.WORLD_CHUNK, Buffer.concat([Buffer.from([file]), u32(offset), data.subarray(offset, offset + CHUNK_SIZE)]));
    });
    send(M.WORLD_DONE, Buffer.concat([stringZ(info.owner), u32(info.revision)]));
  };

  const server = net.createServer((socket) => {
    socket.setNoDelay(true);
    const id = nextId++;
    const addr = `${socket.remoteAddress}:${socket.remotePort}`;
    const send = (type, payload) => socket.write(encode(type, payload));
    let client = null; // set after HELLO
    let upload = null; // { files: Buffer[] } while this client sends the world

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
          // before WORLD_INFO: a client loading the world needs it to put its own character in
          const record = storage.character(client.name);
          if (record) send(M.CHARACTER, record);
          for (const [block, owner] of idLeases) if (owner === client.name) send(M.ID_BLOCK_GRANT, u16(block));
          announceRoles();
          send(M.SETTINGS, stringZ(settingsText(storage.settings())));
          send(M.WORLD_INFO, worldInfo());
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
        case M.CHARACTER:
          storage.saveCharacter(client.name, Buffer.from(payload));
          break;
        case M.WORLD_REQUEST:
          if (storage.worldInfo()) sendWorld(send);
          else send(M.WORLD_INFO, worldInfo());
          break;
        case M.WORLD_UPLOAD: {
          // the sim master's game is the world; anyone may start one on an empty server
          if (storage.worldInfo() && id !== masterId()) {
            log(`[${id}] '${client.name}' is not the sim master, world upload ignored`);
            upload = null;
            break;
          }
          upload = { files: WORLD_FILES.map((_, i) => Buffer.alloc(payload.readUInt32LE(i * 4))) };
          break;
        }
        case M.WORLD_CHUNK:
          if (upload) payload.copy(upload.files[payload[0]], payload.readUInt32LE(1), 5);
          break;
        case M.WORLD_DONE: {
          if (!upload) break;
          const revision = storage.writeWorld(client.name, upload.files);
          upload = null;
          log(`[${id}] '${client.name}' uploaded the world, revision ${revision}`);
          const info = worldInfo();
          for (const c of clients.values()) c.send(M.WORLD_INFO, info);
          break;
        }
        case M.ENTITY_DEATH:
          broadcast(id, type, Buffer.from(payload));
          break;
        case M.ITEM_PARENT:
        case M.OBJECT_RELEASE:
        case M.OBJECT_SPAWN:
        case M.SCRIPT_EVENT:
        case M.ACTOR_ACTION:
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
      announceRoles();
    });
  });

  // what the admin page (admin.js) sees and does
  server.coop = {
    status() {
      const master = clients.size ? masterId() : null;
      return {
        online: [...clients].map(([cid, c]) =>
          ({ id: cid, name: c.name, level: c.state ? readStringZ(c.state, 0) : null, master: cid === master })),
        world: storage.worldInfo(),
      };
    },
    settings: () => storage.settings(),
    adminPassword: () => storage.adminPassword(),
    saveSettings(settings) {
      storage.saveSettings(settings);
      log('settings changed on the admin page');
      const text = stringZ(settingsText(storage.settings()));
      for (const c of clients.values()) c.send(M.SETTINGS, text);
      return storage.settings();
    },
    // only with nobody online: their games run the old world
    resetWorld() {
      if (clients.size) return false;
      storage.resetWorld();
      idLeases.clear();
      log('world reset on the admin page');
      return true;
    },
  };

  return new Promise((resolve) => {
    server.listen(port, host, () => {
      log(`coop server listening on ${host}:${server.address().port}`);
      resolve(server);
    });
  });
}
