import net from 'node:net';
import zlib from 'node:zlib';
import { M, REFUSED, ROLLBACK, GROUP, GROUP_NOTE, PROTOCOL_VERSION, ID_BLOCK_COUNT, NO_BLOCK, CHUNK_SIZE, MAX_SAVES_LISTED,
  encode, createDecoder, readStringZ, readStringsZ, stringZ, u16, u32 } from './protocol.js';
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
  // the sim master runs offline A-Life and world spawns for empty levels, and saves the world: the
  // longest-connected player in the world (ids only grow), or anyone while nobody is in it
  const masterId = () => {
    const inWorld = [...clients].filter(([, c]) => c.inWorld).map(([cid]) => cid);
    return Math.min(...(inWorld.length ? inWorld : clients.keys()));
  };
  const announceRoles = () => {
    if (!clients.size) return;
    for (const c of clients.values()) c.send(M.ROLES, u32(masterId()));
  };

  // Groups of players, by character name, leader first; kept between runs like the characters.
  // An invite lasts a minute and makes a group of two when the inviter has none.
  const INVITE_MS = 60000;
  const PDA_INVITE_MS = 30 * 60000; // one sent from the PDA waits there to be answered
  const groups = storage.loadGroups();
  const invites = new Map(); // `${inviter id}:${invited id}` -> when it runs out
  const groupOf = (name) => groups.find((g) => g.includes(name));
  const groupsPayload = () => Buffer.concat([Buffer.from([groups.length]),
    ...groups.map((g) => Buffer.concat([Buffer.from([g.length]), ...g.map(stringZ)]))]);
  const announceGroups = () => {
    storage.saveGroups(groups);
    const payload = groupsPayload();
    for (const c of clients.values()) c.send(M.GROUPS, payload);
  };
  const leaveGroup = (name) => {
    const g = groupOf(name);
    if (!g) return;
    g.splice(g.indexOf(name), 1);
    if (g.length < 2) groups.splice(groups.indexOf(g), 1);
  };
  const groupNote = (c, note, name) => c.send(M.GROUP_NOTE, Buffer.concat([Buffer.from([note]), stringZ(name)]));
  const onGroup = (id, client, payload) => {
    const max = storage.settings().rules.group_max;
    const action = payload[0];
    if (action === GROUP.INVITE || action === GROUP.ACCEPT || action === GROUP.DECLINE) {
      const otherId = payload.readUInt32LE(1);
      const other = clients.get(otherId);
      if (!other) return;
      if (action === GROUP.INVITE) {
        const g = groupOf(client.name);
        if (g?.includes(other.name)) return groupNote(client, GROUP_NOTE.ALREADY, other.name);
        if (g && g.length >= max) return groupNote(client, GROUP_NOTE.FULL, other.name);
        const viaPda = payload[5] === 1;
        invites.set(`${id}:${otherId}`, Date.now() + (viaPda ? PDA_INVITE_MS : INVITE_MS));
        other.send(M.GROUP_INVITE, Buffer.concat([u32(id), stringZ(client.name), Buffer.from([viaPda ? 1 : 0])]));
        log(`[${id}] '${client.name}' invited '${other.name}' to a group`);
        return;
      }
      const key = `${otherId}:${id}`;
      const valid = (invites.get(key) ?? 0) > Date.now();
      invites.delete(key);
      if (action === GROUP.DECLINE) return groupNote(other, GROUP_NOTE.DECLINED, client.name);
      if (!valid) return groupNote(client, GROUP_NOTE.EXPIRED, other.name);
      const g = groupOf(other.name);
      if (g?.includes(client.name)) return;
      if (g && g.length >= max) return groupNote(client, GROUP_NOTE.FULL, other.name);
      leaveGroup(client.name);
      if (g) g.push(client.name);
      else groups.push([other.name, client.name]);
      log(`[${id}] '${client.name}' joined the group of '${other.name}'`);
    } else if (action === GROUP.LEAVE) {
      if (!groupOf(client.name)) return;
      leaveGroup(client.name);
      log(`[${id}] '${client.name}' left their group`);
    } else if (action === GROUP.KICK) {
      const name = readStringZ(payload, 1);
      const g = groupOf(client.name);
      if (!g || g[0] !== client.name || name === client.name || !g.includes(name)) return;
      leaveGroup(name);
      log(`[${id}] '${client.name}' put '${name}' out of the group`);
    } else return;
    announceGroups();
  };

  // two new games on an empty server would be two worlds: the first player to claim it makes it, until
  // the upload or until they leave
  let creatorId = null;
  const worldInfo = () => {
    const info = storage.worldInfo();
    const creator = creatorId === null ? '' : clients.get(creatorId).name;
    return Buffer.concat([Buffer.from([info ? 1 : 0]), stringZ(info?.owner ?? ''), u32(info?.revision ?? 0), stringZ(creator)]);
  };
  const announceWorld = () => {
    const info = worldInfo();
    for (const c of clients.values()) c.send(M.WORLD_INFO, info);
  };
  // the player's own progress goes with it, before WORLD_DONE: the game puts it on its actor while loading
  const sendWorld = (send, name) => {
    const info = storage.worldInfo();
    storage.readWorld().forEach((data, file) => {
      for (let offset = 0; offset < data.length; offset += CHUNK_SIZE)
        send(M.WORLD_CHUNK, Buffer.concat([Buffer.from([file]), u32(offset), data.subarray(offset, offset + CHUNK_SIZE)]));
    });
    const progress = storage.progress(name) ?? Buffer.alloc(0);
    let offset = 0;
    do {
      send(M.PROGRESS, Buffer.concat([u32(progress.length), u32(offset), progress.subarray(offset, offset + CHUNK_SIZE)]));
      offset += CHUNK_SIZE;
    } while (offset < progress.length);
    send(M.WORLD_DONE, Buffer.concat([stringZ(info.owner), u32(info.revision)]));
  };

  // Saves (storage.js): the master's game saves the world when asked and uploads it with the reason
  // Everyone in the world sends their own progress with it, kept with the save (storage.writeWorld).
  const requestSave = (reason, who, name = '') => {
    const master = clients.get(masterId());
    if (!master?.inWorld) return false;
    for (const c of clients.values()) if (c.inWorld) c.send(M.PROGRESS_REQUEST);
    master.send(M.SAVE_NOW, Buffer.concat([stringZ(name), stringZ(reason), stringZ(who)]));
    return true;
  };
  // a player coming in waits for the master's save of the world as it is now, JOIN_WAIT_MS at most
  const JOIN_WAIT_MS = 30000;
  const awaiting = new Map(); // id -> timer
  const giveWorld = (cid) => {
    clearTimeout(awaiting.get(cid));
    awaiting.delete(cid);
    const c = clients.get(cid);
    if (c && storage.worldInfo()) sendWorld(c.send, c.name);
  };
  const savesPayload = () => {
    const list = storage.saves().reverse().slice(0, MAX_SAVES_LISTED);
    return Buffer.concat([u16(list.length), ...list.map((m) => Buffer.concat([u32(m.revision),
      u32(Math.floor(m.time / 1000)), stringZ(m.name), stringZ(m.reason), stringZ(m.who), u32(m.from ?? 0)]))]);
  };

  // Votes: everyone in the world agrees (the one who asks does), within VOTE_MS; those in the menu don't run
  // it and have no say. A vote takes the world back to a save, or pauses it, or lets it go on again.
  const VOTE_MS = 30000;
  let vote = null; // { kind: 'rollback' | 'pause' | 'resume', revision, proposer, proposerId, waiting: Set of ids, timer }
  let pausedBy = ''; // who asked for the pause the world is in, '' while it goes on
  const pausedPayload = () => Buffer.concat([Buffer.from([pausedBy ? 1 : 0]), stringZ(pausedBy)]);
  const setPaused = (by) => {
    pausedBy = by;
    log(by ? `world paused ('${by}' asked)` : 'world goes on');
    const payload = pausedPayload();
    for (const c of clients.values()) c.send(M.PAUSED, payload);
  };
  const rollback = (revision, how) => {
    const now = storage.rollback(revision);
    if (!now) return 0;
    log(`world taken back to revision ${revision} (${how}): revision ${now}`);
    // each game puts its character where that save had it
    for (const c of clients.values()) {
      const record = storage.character(c.name);
      if (record) c.send(M.CHARACTER, record);
      c.send(M.WORLD_RELOAD);
    }
    announceWorld();
    return now;
  };
  const endVote = (result, who = '') => {
    const { kind, revision, proposer, timer } = vote;
    clearTimeout(timer);
    vote = null;
    const accepted = result === ROLLBACK.ACCEPTED;
    if (kind === 'rollback') {
      const now = accepted ? rollback(revision, `everyone agreed, '${proposer}' asked`) : 0;
      const payload = Buffer.concat([Buffer.from([result]), stringZ(who), u32(now)]);
      for (const c of clients.values()) c.send(M.ROLLBACK_RESULT, payload);
      return;
    }
    if (accepted) setPaused(kind === 'pause' ? proposer : '');
    const payload = Buffer.concat([Buffer.from([result]), stringZ(who), Buffer.from([kind === 'pause' ? 1 : 0])]);
    for (const c of clients.values()) c.send(M.PAUSE_RESULT, payload);
  };
  // asks the others in the world (msg with ask to all), or decides at once when there are none
  const startVote = (kind, id, client, extra, msg, ask) => {
    vote = { kind, ...extra, proposer: client.name, proposerId: id,
      waiting: new Set([...clients].filter(([cid, c]) => cid !== id && c.inWorld).map(([cid]) => cid)) };
    if (!vote.waiting.size) return endVote(ROLLBACK.ACCEPTED);
    vote.timer = setTimeout(() => endVote(ROLLBACK.TIMEOUT,
      [...vote.waiting].map((cid) => clients.get(cid)?.name).filter(Boolean).join(', ')), VOTE_MS).unref();
    for (const c of clients.values()) c.send(msg, ask);
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
          // refused with a reason the game can show, then closed once that is out
          const refuse = (reason, value) => {
            send(M.REFUSED, Buffer.concat([Buffer.from([reason]), u16(value)]));
            socket.end();
          };
          if (version !== PROTOCOL_VERSION) {
            log(`[${id}] protocol mismatch: client ${version}, server ${PROTOCOL_VERSION}`);
            return refuse(REFUSED.VERSION, PROTOCOL_VERSION);
          }
          const max = storage.settings().rules.max_players;
          if (clients.size >= max) {
            log(`[${id}] '${readStringZ(payload, 2)}' turned away: ${clients.size} of ${max} online`);
            return refuse(REFUSED.FULL, max);
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
          send(M.GROUPS, groupsPayload());
          send(M.WORLD_INFO, worldInfo());
          if (pausedBy) send(M.PAUSED, pausedPayload());
          // let the newcomer see players who are standing still
          for (const [otherId, other] of clients)
            if (otherId !== id && other.state) send(M.PEER_STATE, peerState(otherId, other));
          break;
        }
        case M.PING:
          if (payload.length >= 8) client.ping = payload.readUInt32LE(4);
          send(M.PONG, payload.subarray(0, 4));
          break;
        case M.ACTOR_STATE:
          client.state = Buffer.from(payload);
          broadcast(id, M.PEER_STATE, peerState(id, client));
          if (!client.inWorld) {
            client.inWorld = true;
            announceRoles();
          }
          break;
        case M.LEFT_WORLD: {
          if (!client.inWorld) break;
          const wasMaster = masterId() === id;
          client.inWorld = false;
          client.state = null;
          log(`[${id}] '${client.name}' went back to the menu`);
          announceRoles();
          // their things are in the master's world: saved now, unless they were the master (saved on the way)
          if (!wasMaster) requestSave('leave', client.name);
          break;
        }
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
        case M.LOG: {
          const file = readStringZ(payload, 0);
          const at = payload.indexOf(0) + 1;
          const raw = payload.readUInt32LE(at);
          const total = payload.readUInt32LE(at + 4);
          const offset = payload.readUInt32LE(at + 8);
          client.logs ??= new Map();
          if (offset === 0) client.logs.set(file, { data: Buffer.alloc(total), got: 0 });
          const upload = client.logs.get(file);
          if (!upload || upload.data.length !== total) break; // a piece of an upload we didn't see begin
          upload.got += payload.copy(upload.data, offset, at + 12);
          if (upload.got < total) break;
          client.logs.delete(file);
          try {
            const data = zlib.inflateSync(upload.data);
            if (data.length !== raw) throw new Error(`${data.length} bytes, ${raw} expected`);
            storage.saveLog(client.name, file, data);
            log(`[${id}] '${client.name}' sent ${file} (${raw} bytes)`);
          } catch (e) {
            log(`[${id}] '${client.name}' sent ${file}, unreadable: ${e.message}`);
          }
          break;
        }
        case M.PROGRESS: {
          const total = payload.readUInt32LE(0);
          const offset = payload.readUInt32LE(4);
          if (!total) break; // nothing to keep: what we have stays
          if (offset === 0) client.progress = { data: Buffer.alloc(total), got: 0 };
          if (!client.progress || client.progress.data.length !== total) break; // a piece of an upload we didn't see begin
          client.progress.got += payload.copy(client.progress.data, offset, 8);
          if (client.progress.got >= total) {
            storage.saveProgress(client.name, client.progress.data);
            log(`[${id}] '${client.name}' sent their progress (${total} bytes)`);
            client.progress = null;
          }
          break;
        }
        case M.WORLD_REQUEST:
          if (!storage.worldInfo()) send(M.WORLD_INFO, worldInfo());
          // a player coming in gets the world as it is now: the master saves it first
          else if (!awaiting.has(id) && requestSave('join', client.name))
            awaiting.set(id, setTimeout(() => giveWorld(id), JOIN_WAIT_MS).unref());
          else if (!awaiting.has(id)) sendWorld(send, client.name);
          break;
        case M.SAVE_REQUEST: {
          const name = readStringZ(payload, 0);
          if (!requestSave(name ? 'named' : 'quick', client.name, name))
            log(`[${id}] '${client.name}' asked for a save, but nobody runs the world`);
          break;
        }
        case M.SAVES_REQUEST:
          send(M.SAVES, savesPayload());
          break;
        case M.ROLLBACK_PROPOSE: {
          const save = storage.saves().find((m) => m.revision === payload.readUInt32LE(0));
          if (!save) break;
          if (vote) {
            send(M.ROLLBACK_RESULT, Buffer.concat([Buffer.from([ROLLBACK.BUSY]), stringZ(vote.proposer), u32(0)]));
            break;
          }
          log(`[${id}] '${client.name}' asks to take the world back to revision ${save.revision}`);
          startVote('rollback', id, client, { revision: save.revision }, M.ROLLBACK_VOTE, Buffer.concat([u32(id),
            stringZ(client.name), u32(save.revision), u32(Math.floor(save.time / 1000)), stringZ(save.name), stringZ(save.reason)]));
          break;
        }
        case M.PAUSE_PROPOSE: {
          const pause = payload[0] === 1;
          if (pause === !!pausedBy) break; // so it is already
          if (vote) {
            send(M.PAUSE_RESULT, Buffer.concat([Buffer.from([ROLLBACK.BUSY]), stringZ(vote.proposer), Buffer.from([pause ? 1 : 0])]));
            break;
          }
          log(`[${id}] '${client.name}' asks to ${pause ? 'pause the world' : 'let the world go on'}`);
          startVote(pause ? 'pause' : 'resume', id, client, {}, M.PAUSE_VOTE,
            Buffer.concat([u32(id), stringZ(client.name), Buffer.from([pause ? 1 : 0])]));
          break;
        }
        case M.ROLLBACK_ANSWER:
          if (!vote?.waiting.has(id)) break;
          if (!payload[0]) {
            endVote(ROLLBACK.DECLINED, client.name);
            break;
          }
          vote.waiting.delete(id);
          if (!vote.waiting.size) endVote(ROLLBACK.ACCEPTED);
          break;
        case M.WORLD_CLAIM:
          if (payload[0] === 0) {
            if (creatorId !== id) break;
            creatorId = null;
            log(`[${id}] '${client.name}' gave up creating the world`);
            announceWorld();
          } else if (!storage.worldInfo() && creatorId === null) {
            creatorId = id;
            log(`[${id}] '${client.name}' is creating the world`);
            announceWorld();
          } else send(M.WORLD_INFO, worldInfo()); // too late: it tells them who
          break;
        case M.WORLD_UPLOAD: {
          const sizes = WORLD_FILES.length * 4;
          const base = payload.length >= sizes + 4 ? payload.readUInt32LE(sizes) : 0;
          const [name, reason, who] = readStringsZ(payload, sizes + 4, 3);
          // the sim master's game is the world; on an empty server, the game of whoever claimed it; never a
          // game still running the world from before it was taken back to a save
          if (storage.worldInfo() ? id !== masterId() || base < storage.lastRollback() : creatorId !== null && creatorId !== id) {
            log(`[${id}] '${client.name}' may not upload the world now, ignored`);
            upload = null;
            break;
          }
          upload = { files: WORLD_FILES.map((_, i) => Buffer.alloc(payload.readUInt32LE(i * 4))),
            meta: { name, reason: reason || 'auto', who } };
          break;
        }
        case M.WORLD_CHUNK:
          if (upload) payload.copy(upload.files[payload[0]], payload.readUInt32LE(1), 5);
          break;
        case M.WORLD_DONE: {
          if (!upload) break;
          const revision = storage.writeWorld(client.name, upload.files, upload.meta);
          log(`[${id}] '${client.name}' uploaded the world, revision ${revision} (${upload.meta.reason})`);
          upload = null;
          creatorId = null;
          announceWorld();
          for (const cid of [...awaiting.keys()]) giveWorld(cid);
          break;
        }
        case M.ENTITY_DEATH:
          broadcast(id, type, Buffer.from(payload));
          break;
        case M.GROUP:
          onGroup(id, client, payload);
          break;
        case M.ITEM_PARENT:
        case M.OBJECT_RELEASE:
        case M.OBJECT_SPAWN:
        case M.SCRIPT_EVENT:
        case M.ACTOR_ACTION:
        case M.NPC_STATES:
        case M.COOP_HIT:
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
      if (!clients.has(id)) return;
      const wasMaster = masterId() === id;
      clients.delete(id);
      log(`[${id}] '${client.name}' left (${clients.size} online)`);
      broadcast(id, M.PEER_LEFT, u32(id));
      announceRoles();
      if (creatorId === id) {
        creatorId = null;
        log(`[${id}] '${client.name}' left before the world was made: anyone may create it`);
        announceWorld();
      }
      clearTimeout(awaiting.get(id));
      awaiting.delete(id);
      // their things are in the master's world: saved now, unless they were the master (saved on the way)
      if (client.inWorld && !wasMaster) requestSave('leave', client.name);
      if (vote?.proposerId === id) endVote(ROLLBACK.CANCELLED, client.name);
      else if (vote?.waiting.delete(id) && !vote.waiting.size) endVote(ROLLBACK.ACCEPTED);
      if (!clients.size && pausedBy) setPaused(''); // nobody left to let it go on
    });
  });

  // what the admin page (admin.js) sees and does
  server.coop = {
    status() {
      const master = clients.size ? masterId() : null;
      return {
        online: [...clients].map(([cid, c]) =>
          ({ id: cid, name: c.name, level: c.state ? readStringZ(c.state, 0) : null, master: cid === master, ping: c.ping ?? null })),
        world: storage.worldInfo(),
        paused: pausedBy || null,
        saves: storage.saves().reverse().slice(0, MAX_SAVES_LISTED),
      };
    },
    // the world's pause, lifted without a vote (a vote nobody could answer...)
    resume() {
      if (!pausedBy) return false;
      if (vote && vote.kind !== 'rollback') endVote(ROLLBACK.CANCELLED, 'admin');
      setPaused('');
      return true;
    },
    // no vote: whoever is in the game loads the world again
    rollback(revision) {
      if (vote) endVote(ROLLBACK.CANCELLED, 'admin');
      return rollback(revision, 'admin page');
    },
    settings: () => storage.settings(),
    logs: () => storage.logs(),
    logFile: (player, file) => storage.logFile(player, file),
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
      groups.length = 0;
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
