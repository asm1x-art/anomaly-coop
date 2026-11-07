import net from 'node:net';
import crypto from 'node:crypto';
import zlib from 'node:zlib';
import { EventEmitter } from 'node:events';
import { M, REFUSED, ROLLBACK, LOAD, GROUP, GROUP_NOTE, GROUP_FLAG, PROTOCOL_VERSION, ID_BLOCK_COUNT, NO_BLOCK, CHUNK_SIZE, MAX_SAVES_LISTED,
  EXIT_SAVE_NAME, AUTO_SAVE_NAME, TIME_FLAG, TIME_SET, TIME_TICK_MS, encode, createDecoder, readStringZ, readStringsZ, stringZ, u16, u32 } from './protocol.js';
import { openStorage, WORLD_FILES } from './storage.js';
import { settingsText, FACTIONS } from './settings.js';
import { WORLD, RULES, FACTION_NAMES, setSetting, setFaction, saveLabel, yesNo } from './admin_commands.js';
import { createClock } from './clock.js';
import { createBuildCheck } from './builds.js';
import { createNews, NEWS_FACT, DEFAULT_NEWS_TYPES } from './news.js';

const PUBLIC_NEWS = 30; // the newest news in the public status

// hostSecret: the world's host (the headless game host.js starts) says it in its HELLO; null: no host is let in
// journalOverlapMs: how long before a save's upload began the journal keeps its changes (tests make it 0).
// autosaveMinutes, pauseWhenEmpty: server.cfg's [host] (config.js), for the host. adminPassword: the admin page's,
// for the in-game admin window too (null: the one made up in data/admin.json). builds: { file, allowDev } for
// builds.js; none lets every build in
export function startServer({ port = 7777, host = '0.0.0.0', dataDir = 'data', log = console.log, hostSecret = null,
  journalOverlapMs = 60000, autosaveMinutes = null, pauseWhenEmpty = false, adminPassword = null, builds = {},
  news: newsConfig = {}, adminLockMs = 5 * 60000 } = {}) {
  const storage = openStorage(dataDir);
  // the world's important news, for the launchers (news.js)
  const news = createNews({ load: () => storage.loadNews(), save: (list) => storage.saveNews(list),
    types: newsConfig.types ?? DEFAULT_NEWS_TYPES, keep: newsConfig.keep ?? 50 });
  const buildAllowed = createBuildCheck({ ...builds, log });
  const clock = createClock({ load: () => storage.loadClock(), save: (state) => storage.saveClock(state) });
  // id -> name: every player and the host so far, for the journal's ids; ids go on growing across runs
  const names = storage.clientNames();
  let nextId = Math.max(0, ...names.keys()) + 1;
  const clients = new Map(); // id -> { send, name, state, host, socket }
  // what happened, for the Telegram bot (coop.on): joined, left { name }; host_up, host_down; save_failed
  const events = new EventEmitter();
  const traffic = { in: 0, out: 0, since: Date.now() }; // bytes through the game port, for the admins
  let hostId = null; // the world's host, connected
  const players = () => [...clients].filter(([, c]) => !c.host);
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
  // the sim master runs offline A-Life and world spawns for empty levels, and saves the world: the host once it
  // runs the world; else the longest-connected player in the world (ids only grow), or anyone while nobody is in it
  const masterId = () => {
    if (hostId !== null && clients.get(hostId).inWorld) return hostId;
    const all = players().map(([cid]) => cid);
    const inWorld = players().filter(([, c]) => c.inWorld).map(([cid]) => cid);
    return Math.min(...(inWorld.length ? inWorld : all.length ? all : clients.keys()));
  };
  // the world's settings for the games; the host also takes its autosave interval from them
  const settingsPayload = () => stringZ(settingsText(storage.settings()) +
    (autosaveMinutes === null ? '' : `
autosave_minutes=${autosaveMinutes}`));
  // pauseWhenEmpty: the host's world stands while no player is in it (time in the Zone runs many times faster);
  // only the host is told, the players' games never run an empty world
  let emptyPaused = false;
  let saveWhileEmpty = false; // the host goes on for a save asked while the world stood empty
  const updateEmptyPause = () => {
    const hostClient = hostId === null ? null : clients.get(hostId);
    const empty = pauseWhenEmpty && !!hostClient?.inWorld && !pausedBy && !players().some(([, c]) => c.inWorld);
    if (empty !== emptyPaused) {
      emptyPaused = empty;
      log(empty ? 'nobody in the world: the host pauses it' : 'a player is in the world: the host lets it go on');
      hostClient?.send(M.PAUSED, Buffer.concat([Buffer.from([empty ? 1 : 0]), stringZ(empty ? 'server' : '')]));
    }
    updateClock(); // the clock stands with the world
  };
  const hostPayload = () => Buffer.concat([u32(hostId ?? 0), stringZ(hostId === null ? '' : clients.get(hostId).name)]);
  const announceHost = () => {
    const payload = hostPayload();
    for (const c of clients.values()) c.send(M.HOST, payload);
  };
  const announceRoles = () => {
    if (!clients.size) return;
    for (const c of clients.values()) c.send(M.ROLES, u32(masterId()));
  };

  // A level with players on it is run by the one who came to it first (its authority); when they go, by the
  // next to have come. level -> ids in the order they came.
  const levels = new Map();
  const levelsPayload = () => Buffer.concat([Buffer.from([levels.size]),
    ...[...levels].map(([level, ids]) => Buffer.concat([stringZ(level), u32(ids[0])]))]);
  const announceLevels = () => {
    const payload = levelsPayload();
    for (const c of clients.values()) c.send(M.LEVELS, payload);
  };
  // the player is on that level now (null: on none); true when a level's authority changed
  const moveToLevel = (id, client, level) => {
    if (client.level === level) return false;
    let changed = false;
    const queue = levels.get(client.level);
    if (queue) {
      const at = queue.indexOf(id);
      if (at !== -1) queue.splice(at, 1);
      if (!queue.length) levels.delete(client.level);
      if (at === 0) changed = true;
    }
    client.level = level;
    if (level) {
      if (!levels.has(level)) {
        levels.set(level, []);
        changed = true;
      }
      levels.get(level).push(id);
    }
    return changed;
  };

  // Groups of players, by character name, leader first; kept between runs like the characters.
  // An invite lasts a minute and makes a group of two when the inviter has none. The leader may make the group
  // share its story ({ members, story }).
  const INVITE_MS = 60000;
  const PDA_INVITE_MS = 30 * 60000; // one sent from the PDA waits there to be answered
  const groups = storage.loadGroups();
  const invites = new Map(); // `${inviter id}:${invited id}` -> when it runs out
  const groupOf = (name) => groups.find((g) => g.members.includes(name));
  const groupsPayload = () => Buffer.concat([Buffer.from([groups.length]),
    ...groups.map((g) => Buffer.concat([Buffer.from([g.members.length]), ...g.members.map(stringZ),
      Buffer.from([g.story ? GROUP_FLAG.STORY : 0])]))]);
  const announceGroups = () => {
    storage.saveGroups(groups);
    const payload = groupsPayload();
    for (const c of clients.values()) c.send(M.GROUPS, payload);
  };
  const leaveGroup = (name) => {
    const g = groupOf(name);
    if (!g) return;
    g.members.splice(g.members.indexOf(name), 1);
    if (g.members.length < 2) groups.splice(groups.indexOf(g), 1);
  };
  const groupNote = (c, note, name) => c.send(M.GROUP_NOTE, Buffer.concat([Buffer.from([note]), stringZ(name)]));
  const onGroup = (id, client, payload) => {
    const max = storage.settings().rules.group_max;
    const action = payload[0];
    if (action === GROUP.INVITE || action === GROUP.ACCEPT || action === GROUP.DECLINE) {
      const otherId = payload.readUInt32LE(1);
      const other = clients.get(otherId);
      if (!other || other.host) return;
      if (action === GROUP.INVITE) {
        const g = groupOf(client.name);
        if (g?.members.includes(other.name)) return groupNote(client, GROUP_NOTE.ALREADY, other.name);
        if (g && g.members.length >= max) return groupNote(client, GROUP_NOTE.FULL, other.name);
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
      if (g?.members.includes(client.name)) return;
      if (g && g.members.length >= max) return groupNote(client, GROUP_NOTE.FULL, other.name);
      leaveGroup(client.name);
      if (g) g.members.push(client.name);
      else groups.push({ members: [other.name, client.name], story: false });
      log(`[${id}] '${client.name}' joined the group of '${other.name}'`);
    } else if (action === GROUP.LEAVE) {
      if (!groupOf(client.name)) return;
      leaveGroup(client.name);
      log(`[${id}] '${client.name}' left their group`);
    } else if (action === GROUP.KICK) {
      const name = readStringZ(payload, 1);
      const g = groupOf(client.name);
      if (!g || g.members[0] !== client.name || name === client.name || !g.members.includes(name)) return;
      leaveGroup(name);
      log(`[${id}] '${client.name}' put '${name}' out of the group`);
    } else if (action === GROUP.STORY) {
      const g = groupOf(client.name);
      if (!g || g.members[0] !== client.name) return;
      g.story = payload[1] === 1;
      log(`[${id}] '${client.name}' turned the group's common story ${g.story ? 'on' : 'off'}`);
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
  // The journal: the world changes since the world's last save, as relayed. A player coming in gets the save and
  // then these, and replays them while it loads: nobody saves for them. A new save keeps those that came within
  // journalOverlapMs before its upload began (the game made the save a little earlier, and may not have applied
  // the latest yet); replaying one the save has changes nothing.
  // Lua events that change the world (coop_sync.script, coop_events.script); the others are for the players there
  const JOURNAL_EVENTS = new Set(['loot_created', 'mutant_loot', 'stash_revealed', 'stash_opened', 'logic_assign']);
  let journal = storage.journal(); // { time, message: u16 type, then the payload as relayed }, on disk too
  const record = (type, payload) => {
    if (!storage.worldInfo()) return;
    const entry = { time: Date.now(), message: Buffer.concat([u16(type), payload]) };
    journal.push(entry);
    storage.appendJournal(entry);
  };
  const setJournal = (entries) => {
    journal = entries;
    storage.saveJournal(entries);
  };
  const namesPayload = () => Buffer.concat([u16(names.size),
    ...[...names].map(([cid, n]) => Buffer.concat([u32(cid), stringZ(n)]))]);

  // the player's own progress goes with it, before WORLD_DONE: the game puts it on its actor while loading
  const sendWorld = (send, name) => {
    const info = storage.worldInfo();
    storage.readWorld().forEach((data, file) => {
      for (let offset = 0; offset < data.length; offset += CHUNK_SIZE)
        send(M.WORLD_CHUNK, Buffer.concat([Buffer.from([file]), u32(offset), data.subarray(offset, offset + CHUNK_SIZE)]));
    });
    for (const [key, value] of Object.entries(storage.facts())) send(M.FACT, Buffer.concat([stringZ(key), stringZ(value)]));
    send(M.NAMES, namesPayload());
    for (const entry of journal) send(M.JOURNAL, entry.message);
    // the things of a save the character was put back to: given once
    const things = storage.things(name);
    if (things) {
      for (let at = 0; at < things.length; at += CHUNK_SIZE)
        send(M.SNAPSHOT_THINGS, Buffer.concat([u32(things.length), u32(at), things.subarray(at, at + CHUNK_SIZE)]));
      storage.setThings(name, null);
    }
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
    // the host stands while the world is empty: it goes on for the save, then stands again (WORLD_DONE)
    if (emptyPaused && master.host) {
      emptyPaused = false;
      saveWhileEmpty = true;
      master.send(M.PAUSED, Buffer.concat([Buffer.from([0]), stringZ('')]));
    }
    for (const c of clients.values()) if (c.inWorld) c.send(M.PROGRESS_REQUEST);
    master.send(M.SAVE_NOW, Buffer.concat([stringZ(name), stringZ(reason), stringZ(who)]));
    return true;
  };
  // A character's saves: the game's snapshots (SNAPSHOT), asked of everyone saved together. snapshots: save id ->
  // { meta, waiting: names }; each game's snapshot is kept as it comes, the save is listed once all are in.
  const SNAPSHOT_WAIT_MS = 60000;
  const snapshots = new Map();
  const savesPayload = (name) => {
    const list = storage.characterSaves(name).slice(0, MAX_SAVES_LISTED);
    return Buffer.concat([u16(list.length), ...list.map((m) => Buffer.concat([u32(m.id), u32(Math.floor(m.time / 1000)),
      stringZ(m.name), stringZ(m.exit ? 'exit' : m.auto ? 'auto' : m.group ? 'group' : m.name ? 'named' : 'quick'),
      stringZ(m.by), u32(0)]))]);
  };
  // a snapshot: u32 size, the record; u32 size, the progress; the things
  const splitSnapshot = (data) => {
    const recordEnd = 4 + data.readUInt32LE(0);
    const progressEnd = recordEnd + 4 + data.readUInt32LE(recordEnd);
    return { record: data.subarray(4, recordEnd), progress: data.subarray(recordEnd + 4, progressEnd),
      things: data.subarray(progressEnd) };
  };
  // the character as the save has it: record, progress, and its things for its next download; a game running the
  // world loads it again
  // What the character took since the save (TAKEN) comes after the things: those things go back where they were
  // taken from (coop_world.cpp restore_things).
  const putBack = (name, snapshot, since) => {
    const { record, progress, things } = splitSnapshot(snapshot);
    storage.saveCharacter(name, Buffer.from(record));
    if (progress.length) storage.saveProgress(name, Buffer.from(progress));
    const taken = storage.taken(name).filter((e) => e.time >= since); // in the save too: the save says
    storage.setThings(name, Buffer.concat([things.length ? things : u16(0), u16(taken.length),
      ...taken.map((e) => Buffer.concat([u16(e.message.length), e.message]))]));
    const found = players().find(([, c]) => c.name === name);
    if (!found) return;
    found[1].send(M.CHARACTER, record); // a game in the menu loads the world with it
    if (!found[1].inWorld) return;
    found[1].send(M.WORLD_RELOAD);
    found[1].send(M.WORLD_INFO, worldInfo());
  };

  // A player who leaves the world (to the menu, quitting, a lost connection) gets an exit save: their record and
  // progress as the server has them, and the things the host's world has in their shadow (EXIT_THINGS_REQUEST;
  // none without a host). One per character, made anew each time; next time in they choose (SAVE_CHOICE).
  const EXIT_THINGS_WAIT_MS = 15000;
  const exits = new Map(); // save id -> { name, record, progress, data, got, timer }
  const writeExitSave = (saveId, things) => {
    const pending = exits.get(saveId);
    if (!pending) return;
    exits.delete(saveId);
    clearTimeout(pending.timer);
    const { name, record, progress } = pending;
    const meta = { id: saveId, time: Date.now(), name: EXIT_SAVE_NAME, by: name, group: null, exit: true };
    for (const old of storage.characterSaves(name)) if (old.exit) storage.deleteCharacterSave(name, old.id);
    storage.saveCharacterSave(name, meta, Buffer.concat([u32(record.length), record, u32(progress.length), progress,
      things ?? u16(0)]));
    log(`'${name}' left: exit save ${saveId}${things ? '' : ' (no things from the host)'}`);
  };
  const makeExitSave = (name) => {
    const record = storage.character(name);
    if (!record) return;
    const saveId = storage.nextCharacterSaveId();
    exits.set(saveId, { name, record, progress: storage.progress(name) ?? Buffer.alloc(0), data: null, got: 0,
      timer: setTimeout(() => writeExitSave(saveId, null), EXIT_THINGS_WAIT_MS).unref() });
    const hostClient = hostId === null ? null : clients.get(hostId);
    if (hostClient?.inWorld) hostClient.send(M.EXIT_THINGS_REQUEST, Buffer.concat([u32(saveId), stringZ(name)]));
    else writeExitSave(saveId, null);
  };
  // The sim master keeps bodies and boxes with good things near where a player left or saved from the game's
  // cleanup for a while (coop_cleanup.script): a script event from the server, "level\tx\ty\tz\tname"
  const protectNear = (c) => {
    if (!c.state) return;
    const level = readStringZ(c.state, 0);
    const at = c.state.indexOf(0) + 1;
    const [x, y, z] = [0, 4, 8].map((o) => c.state.readFloatLE(at + o));
    const master = clients.get(masterId());
    if (!master?.inWorld || master === c) return;
    master.send(M.SCRIPT_EVENT, Buffer.concat([u32(0), stringZ('coop_protect'),
      stringZ([level, x.toFixed(2), y.toFixed(2), z.toFixed(2), c.name].join('\t'))]));
  };
  // what's left of a player in the world as they go out of it
  const leaving = (c) => {
    protectNear(c);
    makeExitSave(c.name);
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
    emptyPaused = false; // the host was told with the others
    updateEmptyPause();
  };

  // The world's clock (clock.js): every game in the world runs its game time. It runs while someone is in the
  // world and the world isn't paused, and stands still otherwise.
  const timePayload = () => {
    const p = Buffer.alloc(17);
    p.writeBigUInt64LE(BigInt(clock.now()), 0);
    p.writeFloatLE(clock.factor(), 8);
    p[12] = (clock.running() ? TIME_FLAG.RUNNING : 0) | (clock.isSet() ? TIME_FLAG.SET : 0);
    p.writeUInt32LE(clock.epoch(), 13);
    return p;
  };
  const announceTime = () => {
    const payload = timePayload();
    for (const c of clients.values()) c.send(M.TIME, payload);
  };
  const updateClock = () => {
    if (!clock.setRunning([...clients.values()].some((c) => c.inWorld) && !pausedBy && !emptyPaused)) return;
    if (clock.isSet()) log(`clock ${clock.running() ? 'runs' : 'stands'} at ${clock.now()}`);
    announceTime();
  };
  const onTimeSet = (id, client, payload) => {
    const kind = payload[0];
    if (kind === TIME_SET.INIT && payload.length >= 13) {
      const game = Number(payload.readBigUInt64LE(1));
      if (!client.inWorld || !clock.init(game, payload.readFloatLE(9))) return sendTo(id, M.TIME, timePayload());
      log(`[${id}] '${client.name}' set the clock: ${game}, x${clock.factor()}`);
    } else if (kind === TIME_SET.JUMP && payload.length >= 5) {
      const ms = payload.readUInt32LE(1);
      if (!client.inWorld || !clock.jump(ms)) return;
      log(`[${id}] '${client.name}' moved the clock ${Math.round(ms / 60000)} game min on`);
    } else if (kind === TIME_SET.FACTOR && payload.length >= 5) {
      const factor = payload.readFloatLE(1);
      if (id !== masterId() || !clock.setFactor(factor)) return;
      log(`[${id}] '${client.name}' set the time factor x${factor}`);
    } else return;
    announceTime();
  };
  const sendTo = (id, type, payload) => clients.get(id)?.send(type, payload);
  const tick = setInterval(() => {
    if (!clock.isSet()) return;
    clock.persist();
    announceTime();
  }, TIME_TICK_MS).unref();
  const rollback = (revision, how) => {
    const now = storage.rollback(revision);
    if (!now) return 0;
    setJournal([]); // the changes since were made to the world as it was
    log(`world taken back to revision ${revision} (${how}): revision ${now}`);
    // the clock goes back with it, to the time that save was made
    const back = storage.saves().at(-1).clock;
    if (back && clock.set(back)) {
      log(`clock taken back to ${back}`);
      announceTime();
    }
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
    const { kind, proposer, timer } = vote;
    clearTimeout(timer);
    vote = null;
    const accepted = result === ROLLBACK.ACCEPTED;
    if (accepted) setPaused(kind === 'pause' ? proposer : '');
    const payload = Buffer.concat([Buffer.from([result]), stringZ(who), Buffer.from([kind === 'pause' ? 1 : 0])]);
    for (const c of clients.values()) c.send(M.PAUSE_RESULT, payload);
  };
  // asks the others in the world (msg with ask to all), or decides at once when there are none
  const startVote = (kind, id, client, extra, msg, ask) => {
    vote = { kind, ...extra, proposer: client.name, proposerId: id,
      waiting: new Set(players().filter(([cid, c]) => cid !== id && c.inWorld).map(([cid]) => cid)) };
    if (!vote.waiting.size) return endVote(ROLLBACK.ACCEPTED);
    vote.timer = setTimeout(() => endVote(ROLLBACK.TIMEOUT,
      [...vote.waiting].map((cid) => clients.get(cid)?.name).filter(Boolean).join(', ')), VOTE_MS).unref();
    for (const c of clients.values()) c.send(msg, ask);
  };

  // The in-game admin window: a connection that gave the admin password may do what the admin page does.
  // ADMIN_TRIES wrong passwords from one address close the window's login there for adminLockMs (a reconnect
  // doesn't lift it). The window keeps a token, not the password: the password's HMAC with this server's salt, so
  // it stops working once the password changes, and the password (the admin page's too) is never on the disk.
  const ADMIN_TRIES = 5;
  const adminLocks = new Map(); // address -> { tries, until }
  const adminPasswordNow = () => adminPassword || storage.adminPassword().password;
  const adminToken = () => 'token:' + crypto.createHmac('sha256', adminPasswordNow()).update(`coop-admin:${storage.adminSalt()}`).digest('hex');
  const sameText = (a, b) => {
    const [x, y] = [Buffer.from(a), Buffer.from(b)];
    return x.length === y.length && crypto.timingSafeEqual(x, y);
  };
  // the password or the token: 'ok'; a wrong one: 'wrong', or 'locked' with the seconds left
  const adminCheck = (address, secret) => {
    const now = Date.now();
    let lock = adminLocks.get(address);
    if (lock?.until && lock.until <= now) {
      adminLocks.delete(address); // served its time: tries from nothing again
      lock = null;
    }
    if (lock?.until) return { result: 'locked', seconds: Math.ceil((lock.until - now) / 1000) };
    if (sameText(secret, adminPasswordNow()) || sameText(secret, adminToken())) {
      adminLocks.delete(address);
      return { result: 'ok' };
    }
    lock ??= { tries: 0, until: 0 };
    lock.tries++;
    if (lock.tries >= ADMIN_TRIES) lock.until = now + adminLockMs;
    adminLocks.set(address, lock);
    return lock.until ? { result: 'locked', seconds: Math.ceil(adminLockMs / 1000) } : { result: 'wrong', left: ADMIN_TRIES - lock.tries };
  };
  const minutes = (seconds) => (seconds < 60 ? `${seconds} с` : `${Math.ceil(seconds / 60)} мин`);
  // the window's login, as the first line of ADMIN_STATE: auth ok <token> | auth wrong 0 <text> | auth locked
  // <seconds> <text> | auth need 0 <text>
  const authLine = (check) => {
    if (check.result === 'ok') return ['auth', 'ok', adminToken()].join('\t');
    if (check.result === 'locked')
      return ['auth', 'locked', check.seconds, `Слишком много неверных паролей: вход в админку закрыт на ${minutes(check.seconds)}.`].join('\t');
    if (check.result === 'need') return ['auth', 'need', 0, 'Сначала пароль админки.'].join('\t');
    return ['auth', 'wrong', 0, `Неверный пароль админки. Попыток до блокировки: ${check.left}.`].join('\t');
  };
  const adminStatePayload = () => {
    const st = server.coop.status();
    const s = storage.settings();
    const h = st.host;
    const lines = [['host', !h ? 'нет: мир держит игра игрока' : [h.running === false ? 'не работает' : 'работает',
      h.master ? 'держит мир' : h.connected ? 'загружает мир' : 'не подключён', h.gave_up ? 'упал 3 раза, ждёт перезапуска' : '']
      .filter(Boolean).join(', ')]];
    if (st.world) lines.push(['world', st.world.revision, st.world.owner]);
    for (const p of st.online) lines.push(['player', p.name, p.level ?? '', p.ping ?? '', p.authority ? 1 : 0]);
    for (const [group, list] of [['world', WORLD], ['rules', RULES]])
      for (const [key, title, min, max] of list) lines.push(['setting', group, key, Number(s[group][key]), min ?? '', max ?? '', title]);
    for (const f of FACTIONS) lines.push(['faction', f, s.factions.includes(f) ? 1 : 0, FACTION_NAMES[f] ?? f]);
    for (const m of st.saves.slice(0, 20)) lines.push(['save', m.revision, Math.floor(m.time / 1000), saveLabel(m)]);
    return stringZ([authLine({ result: 'ok' }), ...lines.map((l) => l.join('\t'))].join('\n'));
  };
  // '' for state: nothing to say
  const adminCommand = ([cmd, a = '', b = '']) => {
    switch (cmd) {
      case 'state':
        return '';
      case 'set':
        return setSetting(server.coop, a, b);
      case 'faction':
        return setFaction(server.coop, a, b) ?? `${FACTION_NAMES[a] ?? a}: ${yesNo(storage.settings().factions.includes(a))}`;
      case 'save':
        return server.coop.saveWorld() ? 'Мир сохраняется.' : 'Сохранить сейчас некому: мир никто не держит.';
      case 'restart_host':
        return server.coop.restartHost() ? 'Хост перезапускается.' : 'Хоста нет: в server.cfg не указана папка игры.';
      case 'kick':
        return server.coop.kick(a) ? `Отключён: ${a}` : `Нет такого игрока онлайн: ${a}`;
      case 'rollback':
        return server.coop.rollback(Number(a)) ? `Мир возвращён к №${a}.` : `Нет сохранения №${a}.`;
      default:
        return `Не знаю такой команды: ${cmd}`;
    }
  };

  const server = net.createServer((socket) => {
    socket.setNoDelay(true);
    const id = nextId++;
    const addr = `${socket.remoteAddress}:${socket.remotePort}`;
    const send = (type, payload) => {
      const frame = encode(type, payload);
      traffic.out += frame.length;
      socket.write(frame);
    };
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
          const name = readStringZ(payload, 2);
          const buildAt = payload.indexOf(0, 2) + 1;
          const build = buildAt > 0 ? readStringZ(payload, buildAt) : '';
          if (!buildAllowed(build)) {
            log(`[${id}] '${name}' turned away: build '${build || 'none'}' is not let in`);
            return refuse(REFUSED.BUILD, 0);
          }
          const roleAt = buildAt > 0 ? payload.indexOf(0, buildAt) + 1 : 0;
          const isHost = roleAt > 0 && payload[roleAt] === 1;
          if (isHost && (!hostSecret || readStringZ(payload, roleAt + 1) !== hostSecret || hostId !== null)) {
            log(`[${id}] '${name}' says it is the host: ${hostId !== null ? 'there is one' : 'wrong secret'}, turned away`);
            return refuse(REFUSED.HOST, 0);
          }
          const max = storage.settings().rules.max_players;
          if (!isHost && players().length >= max) {
            log(`[${id}] '${name}' turned away: ${players().length} of ${max} online`);
            return refuse(REFUSED.FULL, max);
          }
          client = { send, name, state: null, host: isHost, socket, since: Date.now() };
          clients.set(id, client);
          names.set(id, name);
          storage.saveClientNames(names);
          log(`[${id}] '${client.name}' joined from ${addr} (${players().length} online${isHost ? ', the world host' : ''})`);
          send(M.WELCOME, u32(id));
          if (isHost) {
            hostId = id;
            announceHost();
            events.emit('host_up', { name });
          } else {
            send(M.HOST, hostPayload());
            events.emit('joined', { name });
          }
          // before WORLD_INFO: a client loading the world needs it to put its own character in
          const record = storage.character(client.name);
          if (record) send(M.CHARACTER, record);
          // an exit save and another one: the player chooses which to go on from
          const own = isHost ? [] : storage.characterSaves(client.name);
          if (own.some((m) => m.exit) && own.some((m) => !m.exit)) send(M.SAVE_CHOICE, savesPayload(client.name));
          for (const [block, owner] of idLeases) if (owner === client.name) send(M.ID_BLOCK_GRANT, u16(block));
          announceRoles();
          send(M.SETTINGS, settingsPayload());
          send(M.GROUPS, groupsPayload());
          send(M.WORLD_INFO, worldInfo());
          if (pausedBy) send(M.PAUSED, pausedPayload());
          send(M.TIME, timePayload());
          if (levels.size) send(M.LEVELS, levelsPayload());
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
          // the host's state only says its game runs the world: it is on no level and nobody sees it
          if (client.host) {
            if (!client.inWorld) {
              client.inWorld = true;
              log(`[${id}] the host runs the world: the sim master now`);
              announceRoles();
              updateEmptyPause();
            }
            break;
          }
          client.state = Buffer.from(payload);
          // before the state: a game that sees a player on its level knows by then who runs it
          if (moveToLevel(id, client, readStringZ(payload, 0))) {
            log(`[${id}] '${client.name}' is on ${client.level}, run by '${clients.get(levels.get(client.level)[0]).name}'`);
            announceLevels();
          }
          broadcast(id, M.PEER_STATE, peerState(id, client));
          if (!client.inWorld) {
            client.inWorld = true;
            announceRoles();
            updateEmptyPause();
          }
          break;
        case M.LEFT_WORLD: {
          if (!client.inWorld) break;
          leaving(client);
          client.inWorld = false;
          client.state = null;
          log(`[${id}] '${client.name}' went back to the menu`);
          announceRoles();
          if (moveToLevel(id, client, null)) announceLevels();
          updateEmptyPause();
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
        case M.FACT: {
          const [key, value] = readStringsZ(payload, 0, 2);
          // a news told to every player: for the journal, from the game speaking for the world only
          if (key === NEWS_FACT) {
            if (client.host || id === masterId()) {
              const entry = news.add(value, client.name);
              if (entry) log(`news (${entry.type}) from '${client.name}': ${entry.text.slice(0, 120)}`);
            } else log(`[${id}] '${client.name}' sent a news, but neither hosts nor runs the world: ignored`);
            break;
          }
          // who brought a mechanic his tools: the first one stays (two finishing the task at once)
          if (key.startsWith('tool:') && value && storage.facts()[key]) break;
          // a claim: the first stays, and the claimer learns whether it is theirs
          if (key.startsWith('once:')) {
            const kept = storage.facts()[key];
            if (!kept && value) {
              storage.setFact(key, value);
              broadcast(id, M.FACT, Buffer.from(payload));
            }
            send(M.FACT, Buffer.concat([stringZ(key), stringZ(kept || value)]));
            break;
          }
          if (key && storage.setFact(key, value)) broadcast(id, M.FACT, Buffer.from(payload));
          break;
        }
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
          else {
            sendWorld(send, client.name);
            log(`[${id}] '${client.name}' got the world, revision ${storage.worldInfo().revision}, and ${journal.length} change(s) since`);
          }
          break;
        case M.SAVE_REQUEST: {
          const name = readStringZ(payload, 0);
          if (name === AUTO_SAVE_NAME) {
            // the character's autosave: its own, in a group too; the one before goes once the new one is in
            if (client.host || !client.inWorld) break;
            const meta = { id: storage.nextCharacterSaveId(), time: Date.now(), name, by: client.name, group: null, auto: true };
            snapshots.set(meta.id, { meta, waiting: new Set([client.name]) });
            setTimeout(() => snapshots.delete(meta.id), SNAPSHOT_WAIT_MS).unref();
            send(M.SNAPSHOT_REQUEST, u32(meta.id));
            break;
          }
          // a group's leader saves the group, its other members nothing
          const g = groupOf(client.name);
          if (g && g.members[0] !== client.name) break;
          const members = g ? [...g.members] : [client.name];
          const saving = players().filter(([, c]) => c.inWorld && members.includes(c.name));
          if (!saving.length) break;
          const meta = { id: storage.nextCharacterSaveId(), time: Date.now(), name, by: client.name, group: g ? members : null };
          snapshots.set(meta.id, { meta, waiting: new Set(saving.map(([, c]) => c.name)) });
          setTimeout(() => snapshots.delete(meta.id), SNAPSHOT_WAIT_MS).unref();
          for (const [, c] of saving) {
            c.send(M.SNAPSHOT_REQUEST, u32(meta.id));
            protectNear(c);
          }
          log(`[${id}] '${client.name}' saves ${g ? `the group (${saving.length} in the world)` : 'their character'}, save ${meta.id}`);
          break;
        }
        case M.SNAPSHOT: {
          const saveId = payload.readUInt32LE(0);
          const total = payload.readUInt32LE(4);
          const offset = payload.readUInt32LE(8);
          const pending = snapshots.get(saveId);
          if (!pending?.waiting.has(client.name)) break;
          if (offset === 0) client.snapshot = { saveId, data: Buffer.alloc(total), got: 0 };
          if (client.snapshot?.saveId !== saveId || client.snapshot.data.length !== total) break;
          client.snapshot.got += payload.copy(client.snapshot.data, offset, 12);
          if (client.snapshot.got < total) break;
          storage.saveCharacterSave(client.name, pending.meta, client.snapshot.data);
          if (pending.meta.auto)
            for (const old of storage.characterSaves(client.name)) if (old.auto && old.id !== saveId) storage.deleteCharacterSave(client.name, old.id);
          client.snapshot = null;
          pending.waiting.delete(client.name);
          if (!pending.waiting.size) snapshots.delete(saveId);
          log(`[${id}] '${client.name}' ${pending.meta.auto ? 'autosaved' : 'saved'}, save ${saveId} (${total} bytes)`);
          break;
        }
        case M.SAVES_REQUEST:
          send(M.SAVES, savesPayload(client.name));
          break;
        case M.TAKEN:
          if (!client.host) storage.appendTaken(client.name, { time: Date.now(), message: Buffer.from(payload) });
          break;
        case M.EXIT_THINGS: {
          const saveId = payload.readUInt32LE(0);
          const total = payload.readUInt32LE(4);
          const offset = payload.readUInt32LE(8);
          const pending = exits.get(saveId);
          if (!client.host || !pending) break;
          if (offset === 0) pending.data = Buffer.alloc(total);
          if (!pending.data || pending.data.length !== total) break;
          pending.got += payload.copy(pending.data, offset, 12);
          if (pending.got >= total) writeExitSave(saveId, pending.data);
          break;
        }
        case M.ADMIN_LOGIN: {
          const check = adminCheck(socket.remoteAddress, readStringZ(payload, 0));
          if (check.result !== 'ok') {
            log(`[${id}] '${client.name}' gave a wrong admin password${check.result === 'locked' ? ` (locked for ${check.seconds} s)` : ''}`);
            send(M.ADMIN_STATE, stringZ(authLine(check)));
            break;
          }
          if (!client.admin) log(`[${id}] '${client.name}' opened the admin window`);
          client.admin = true;
          send(M.ADMIN_STATE, adminStatePayload());
          break;
        }
        case M.ADMIN_COMMAND: {
          if (!client.admin) {
            send(M.ADMIN_STATE, stringZ(authLine({ result: 'need' })));
            break;
          }
          const fields = readStringZ(payload, 0).split('\t');
          const answer = adminCommand(fields);
          if (answer) {
            log(`[${id}] '${client.name}' (admin): ${fields.join(' ')} - ${answer}`);
            send(M.ADMIN_RESULT, stringZ(answer));
          }
          if (clients.has(id)) send(M.ADMIN_STATE, adminStatePayload()); // kicked themselves: gone
          break;
        }
        case M.LOAD_REQUEST: {
          const saveId = payload.readUInt32LE(0);
          const result = (code) => send(M.LOAD_RESULT, Buffer.concat([Buffer.from([code]), u32(saveId)]));
          if (saveId === 0) {
            // died with nobody to help: back to the newest of the character's own saves (its part of a group's, its
            // autosave)
            const newest = storage.characterSaves(client.name).find((m) => !m.exit);
            const back = newest && storage.characterSave(client.name, newest.id);
            if (!back) return result(LOAD.NO_SAVE);
            putBack(client.name, back.snapshot, back.meta.time);
            log(`[${id}] '${client.name}' died alone: back to save ${newest.id}`);
            return result(LOAD.DONE);
          }
          const save = storage.characterSave(client.name, saveId);
          if (!save) return result(LOAD.NO_SAVE);
          if (save.meta.group && save.meta.by !== client.name) return result(LOAD.LEADER_ONLY);
          const names = save.meta.group ?? [client.name];
          for (const name of names) {
            const own = name === client.name ? save : storage.characterSave(name, saveId);
            if (own) putBack(name, own.snapshot, save.meta.time);
          }
          log(`[${id}] '${client.name}' went back to save ${saveId}${save.meta.group ? ` with ${names.join(', ')}` : ''}`);
          result(LOAD.DONE);
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
          // the save was just made: the clock now is its time, near enough
          upload = { files: WORLD_FILES.map((_, i) => Buffer.alloc(payload.readUInt32LE(i * 4))),
            meta: { name, reason: reason || 'auto', who, clock: clock.isSet() ? clock.now() : undefined }, startedAt: Date.now() };
          break;
        }
        case M.WORLD_CHUNK:
          if (upload) payload.copy(upload.files[payload[0]], payload.readUInt32LE(1), 5);
          break;
        case M.WORLD_DONE: {
          if (!upload) break;
          const revision = storage.writeWorld(client.name, upload.files, upload.meta);
          log(`[${id}] '${client.name}' uploaded the world, revision ${revision} (${upload.meta.reason})`);
          setJournal(journal.filter((entry) => entry.time >= upload.startedAt - journalOverlapMs));
          upload = null;
          creatorId = null;
          announceWorld();
          if (saveWhileEmpty) {
            saveWhileEmpty = false;
            updateEmptyPause(); // still empty: it stands again
          }
          break;
        }
        case M.ENTITY_DEATH:
          record(type, payload);
          broadcast(id, type, Buffer.from(payload));
          break;
        case M.GROUP:
          onGroup(id, client, payload);
          break;
        case M.TIME_SET:
          onTimeSet(id, client, payload);
          break;
        case M.ITEM_PARENT:
        case M.OBJECT_RELEASE:
        case M.OBJECT_SPAWN:
        case M.OBJECT_STATE:
        case M.SCRIPT_EVENT:
          if (type !== M.SCRIPT_EVENT || JOURNAL_EVENTS.has(readStringZ(payload, 0)))
            record(type, Buffer.concat([u32(id), payload]));
          broadcast(id, type, Buffer.concat([u32(id), payload]));
          break;
        case M.NPC_STATES: {
          // a level's NPCs: for the players on it, and the host (it follows which squads are online where)
          const level = readStringZ(payload, 0);
          const relayed = Buffer.concat([u32(id), payload]);
          for (const [cid, c] of clients) if (cid !== id && (c.host || c.level === level)) c.send(type, relayed);
          break;
        }
        case M.ACTOR_ACTION:
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
      traffic.in += chunk.length;
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
      clients.delete(id);
      if (!client.host && client.inWorld) leaving(client);
      if (client.host) {
        hostId = null;
        emptyPaused = false;
        log(`[${id}] the host left: the sim master is a player's game again`);
        announceHost();
        announceRoles();
        updateClock();
        return;
      }
      log(`[${id}] '${client.name}' left (${players().length} online)`);
      events.emit('left', { name: client.name });
      broadcast(id, M.PEER_LEFT, u32(id));
      announceRoles();
      if (moveToLevel(id, client, null)) announceLevels();
      if (creatorId === id) {
        creatorId = null;
        log(`[${id}] '${client.name}' left before the world was made: anyone may create it`);
        announceWorld();
      }
      if (vote?.proposerId === id) endVote(ROLLBACK.CANCELLED, client.name);
      else if (vote?.waiting.delete(id) && !vote.waiting.size) endVote(ROLLBACK.ACCEPTED);
      if (!players().length && pausedBy) setPaused(''); // nobody left to let it go on
      updateEmptyPause();
    });
  });

  let hostProcess = null; // host.js, when this server starts the host itself

  // what the admin page (admin.js) and the Telegram bot (telegram.js) see and do
  server.coop = {
    status() {
      const master = clients.size ? masterId() : null;
      const hostClient = hostId === null ? null : clients.get(hostId);
      const host = hostProcess || hostClient ? { ...hostProcess?.status(), connected: !!hostClient,
        in_world: !!hostClient?.inWorld, master: hostId !== null && hostId === master } : null;
      return {
        host,
        online: players().map(([cid, c]) =>
          ({ id: cid, name: c.name, level: c.state ? readStringZ(c.state, 0) : null, master: cid === master,
            authority: !!c.level && levels.get(c.level)[0] === cid, ping: c.ping ?? null })),
        world: storage.worldInfo(),
        paused: pausedBy || null,
        clock: clock.isSet() ? { game: clock.now(), factor: clock.factor(), running: clock.running() } : null,
        traffic: { ...traffic },
        saves: storage.saves().reverse().slice(0, MAX_SAVES_LISTED),
      };
    },
    // what anyone on the tunnel may see (admin.js GET /api/public/status): who is on, where and since when, the
    // host, and the news already told in the world. No addresses, ids, saves or timetables.
    publicStatus() {
      const hostClient = hostId === null ? null : clients.get(hostId);
      return {
        protocol: PROTOCOL_VERSION,
        time: Date.now(),
        max_players: storage.settings().rules?.max_players ?? null,
        host: hostProcess || hostClient ? { in_world: !!hostClient?.inWorld } : null,
        paused: !!pausedBy,
        players: players().map(([, c]) => ({ name: c.name, level: c.state ? readStringZ(c.state, 0) : null, since: c.since ?? null })),
        news: news.list().slice(-PUBLIC_NEWS).map(({ id, type, world, text, time }) => ({ id, type, world, text, time })),
      };
    },
    news: () => news.list(),
    // the world's pause, lifted without a vote (a vote nobody could answer...)
    resume() {
      if (!pausedBy) return false;
      if (vote) endVote(ROLLBACK.CANCELLED, 'admin');
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
    facts: () => storage.facts(),
    logFile: (player, file) => storage.logFile(player, file),
    // a crash or bug report from a launcher (admin.js): kept and logged
    saveCrash(report, files) {
      const id = storage.saveCrash(report.player, report, files);
      const what = report.kind === 'bug' ? 'bug report' : `crash report`;
      log(`${what} from '${report.player}': ${report.code || '-'}${report.meaning ? ` (${report.meaning})` : ''}, ${files.length} file(s)`
        + `${report.comment ? `: "${report.comment.slice(0, 120)}"` : ''}`);
      return id;
    },
    crashes: () => storage.crashes(),
    crashFile: (player, id, file) => storage.crashFile(player, id, file),
    adminPassword: () => storage.adminPassword(),
    saveSettings(settings) {
      storage.saveSettings(settings);
      log('settings changed on the admin page');
      const text = settingsPayload();
      for (const c of clients.values()) c.send(M.SETTINGS, text);
      return storage.settings();
    },
    // only with no player online: their games run the old world. The host's does too: it is sent off, comes
    // back (host.js) and waits for a new world.
    resetWorld() {
      if (players().length) return false;
      if (hostId !== null) clients.get(hostId).socket.destroy();
      storage.resetWorld();
      news.clear();
      clock.clear();
      journal = [];
      idLeases.clear();
      groups.length = 0;
      log('world reset on the admin page');
      return true;
    },
    on: (event, handler) => events.on(event, handler),
    events, // host.js tells host_down through it
    // the master (the host, if it runs the world) saves it now
    saveWorld: () => requestSave('admin', 'admin'),
    // that player is off the server (their game says it lost the connection)
    kick(name) {
      const found = players().find(([, c]) => c.name === name);
      if (!found) return false;
      log(`[${found[0]}] '${name}' put off the server by an admin`);
      found[1].socket.destroy();
      return true;
    },
    setHostProcess(process) {
      hostProcess = process;
    },
    restartHost: () => hostProcess?.restart() ?? false,
  };

  server.on('close', () => clearInterval(tick));

  return new Promise((resolve) => {
    server.listen(port, host, () => {
      log(`coop server listening on ${host}:${server.address().port}`);
      resolve(server);
    });
  });
}
