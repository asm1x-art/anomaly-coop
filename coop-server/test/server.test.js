import { test } from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';
import { startServer } from '../src/server.js';
import { M, REFUSED, ROLLBACK, LOAD, GROUP, GROUP_NOTE, GROUP_FLAG, PROTOCOL_VERSION, encode, createDecoder, encodeText, readStringZ, readStringsZ } from '../src/protocol.js';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// every server gets its own data directory
function options(dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'coop-test-'))) {
  return { port: 0, host: '127.0.0.1', dataDir, log: () => {} };
}

// Minimal client speaking the same wire format as the engine.
function connect(port) {
  const socket = net.connect(port, '127.0.0.1');
  const queue = [];
  const waiters = [];
  // ROLES arrive on every join/leave; kept aside so tests can read the other messages in order
  const client = { socket, roles: [], worldInfo: [], settings: [], groups: [], levels: [], hosts: [], time: [] };
  socket.on('data', createDecoder((type, payload) => {
    const msg = { type, payload: Buffer.from(payload) };
    if (type === M.ROLES) return client.roles.push(msg.payload.readUInt32LE(0));
    if (type === M.WORLD_INFO) return client.worldInfo.push(msg.payload);
    if (type === M.SETTINGS) return client.settings.push(readStringZ(msg.payload, 0));
    if (type === M.GROUPS) return client.groups.push(msg.payload);
    if (type === M.TIME) return client.time.push(timeOf(msg.payload));
    if (type === M.LEVELS) return client.levels.push(parseLevels(msg.payload));
    if (type === M.HOST) return client.hosts.push({ id: msg.payload.readUInt32LE(0), name: readStringZ(msg.payload, 4) });
    const w = waiters.shift();
    w ? w(msg) : queue.push(msg);
  }));
  client.next = () => new Promise((r) => (queue.length ? r(queue.shift()) : waiters.push(r)));
  client.send = (type, payload) => socket.write(encode(type, payload));
  return new Promise((r) => socket.on('connect', () => r(client)));
}

// the world's clock as a TIME message tells it
function timeOf(p) {
  return { game: Number(p.readBigUInt64LE(0)), factor: p.readFloatLE(8), running: (p[12] & 1) !== 0, set: (p[12] & 2) !== 0,
    epoch: p.readUInt32LE(13) };
}

function hello(name, version = PROTOCOL_VERSION, build = 'dev') {
  const p = Buffer.alloc(2);
  p.writeUInt16LE(version, 0);
  return Buffer.concat([p, encodeText(name), Buffer.from([0]), encodeText(build), Buffer.from([0])]);
}

test('hello -> welcome with unique ids, ping -> pong echoes time', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  try {
    const a = await connect(port);
    const b = await connect(port);

    a.send(M.HELLO, hello('artem'));
    b.send(M.HELLO, hello('друг'));
    const wa = await a.next();
    const wb = await b.next();
    assert.equal(wa.type, M.WELCOME);
    assert.equal(wb.type, M.WELCOME);
    assert.notEqual(wa.payload.readUInt32LE(0), wb.payload.readUInt32LE(0));

    const t = Buffer.alloc(4);
    t.writeUInt32LE(123456, 0);
    a.send(M.PING, t);
    const pong = await a.next();
    assert.equal(pong.type, M.PONG);
    assert.equal(pong.payload.readUInt32LE(0), 123456);

    a.socket.destroy();
    b.socket.destroy();
  } finally {
    server.close();
  }
});

test('frames split across chunks are reassembled', async () => {
  const server = await startServer(options());
  try {
    const c = await connect(server.address().port);
    const frame = encode(M.HELLO, hello('split'));
    for (const byte of frame) c.socket.write(Buffer.from([byte]));
    assert.equal((await c.next()).type, M.WELCOME);
    c.socket.destroy();
  } finally {
    server.close();
  }
});

test('wrong protocol version is refused with the server version, then dropped', async () => {
  const server = await startServer(options());
  try {
    const c = await connect(server.address().port);
    const closed = new Promise((r) => c.socket.on('close', r));
    c.send(M.HELLO, hello('old', PROTOCOL_VERSION + 1));
    const msg = await c.next();
    assert.equal(msg.type, M.REFUSED);
    assert.equal(msg.payload[0], REFUSED.VERSION);
    assert.equal(msg.payload.readUInt16LE(1), PROTOCOL_VERSION);
    await closed;
  } finally {
    server.close();
  }
});

test('a full server refuses the next player, saying how many it takes', async () => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'coop-test-'));
  fs.writeFileSync(path.join(dataDir, 'settings.json'), JSON.stringify({ rules: { max_players: 1 } }));
  const server = await startServer(options(dataDir));
  const { port } = server.address();
  try {
    const a = await connect(port);
    a.send(M.HELLO, hello('artem'));
    assert.equal((await a.next()).type, M.WELCOME);
    const b = await connect(port);
    const closed = new Promise((r) => b.socket.on('close', r));
    b.send(M.HELLO, hello('друг'));
    const msg = await b.next();
    assert.equal(msg.type, M.REFUSED);
    assert.equal(msg.payload[0], REFUSED.FULL);
    assert.equal(msg.payload.readUInt16LE(1), 1);
    await closed;
    a.socket.destroy();
  } finally {
    server.close();
  }
});

function actorState(level, x, y, z, yaw) {
  const nums = Buffer.alloc(16);
  [x, y, z, yaw].forEach((v, i) => nums.writeFloatLE(v, i * 4));
  return Buffer.concat([Buffer.from(level + '\0'), nums]);
}

function parsePeerState(payload) {
  const id = payload.readUInt32LE(0);
  const nameEnd = payload.indexOf(0, 4);
  const name = readStringZ(payload, 4);
  const levelEnd = payload.indexOf(0, nameEnd + 1);
  const level = payload.toString('utf8', nameEnd + 1, levelEnd);
  const f = (i) => payload.readFloatLE(levelEnd + 1 + i * 4);
  return { id, name, level, x: f(0), y: f(1), z: f(2), yaw: f(3) };
}

test('actor state is relayed to others, replayed to newcomers, and leave is announced', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  try {
    const a = await connect(port);
    a.send(M.HELLO, hello('artem'));
    const idA = (await a.next()).payload.readUInt32LE(0);
    a.send(M.ACTOR_STATE, actorState('l01_escape', 1.5, 2, -3, 0.25));

    // b joins after a already reported its state
    const b = await connect(port);
    b.send(M.HELLO, hello('друг'));
    const idB = (await b.next()).payload.readUInt32LE(0);
    const replay = await b.next();
    assert.equal(replay.type, M.PEER_STATE);
    assert.deepEqual(parsePeerState(replay.payload),
      { id: idA, name: 'artem', level: 'l01_escape', x: 1.5, y: 2, z: -3, yaw: 0.25 });

    // live update from b reaches a, and not b itself
    b.send(M.ACTOR_STATE, actorState('l02_garbage', 10, 0, 20, 1));
    const live = await a.next();
    assert.equal(live.type, M.PEER_STATE);
    assert.equal(parsePeerState(live.payload).level, 'l02_garbage');
    assert.equal(parsePeerState(live.payload).name, 'друг');

    b.socket.destroy();
    // a runs the world (no host): it keeps what's near where b left (coop_cleanup.script)
    const protect = await a.next();
    assert.equal(protect.type, M.SCRIPT_EVENT);
    assert.deepEqual(readStringsZ(protect.payload, 4, 2), ['coop_protect', 'l02_garbage\t10.00\t0.00\t20.00\tдруг']);
    const left = await a.next();
    assert.equal(left.type, M.PEER_LEFT);
    assert.equal(left.payload.readUInt32LE(0), idB);

    a.socket.destroy();
  } finally {
    server.close();
  }
});

test('messages before HELLO are rejected', async () => {
  const server = await startServer(options());
  try {
    const c = await connect(server.address().port);
    const closed = new Promise((r) => c.socket.on('close', r));
    c.send(M.ACTOR_STATE, actorState('l01_escape', 0, 0, 0, 0));
    await closed;
  } finally {
    server.close();
  }
});

test('entity death is relayed to everyone except the sender', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  try {
    const a = await connect(port);
    const b = await connect(port);
    a.send(M.HELLO, hello('artem'));
    b.send(M.HELLO, hello('друг'));
    await a.next();
    await b.next();

    const death = Buffer.concat([Buffer.from([0x39, 0x05]), Buffer.from('esc_wolf\0'), Buffer.from([0xff, 0xff])]);
    a.send(M.ENTITY_DEATH, death);
    const got = await b.next();
    assert.equal(got.type, M.ENTITY_DEATH);
    assert.deepEqual(got.payload, death);

    // a must not get its own death back: the next message it receives is the reply to this ping
    const t = Buffer.alloc(4);
    a.send(M.PING, t);
    assert.equal((await a.next()).type, M.PONG);

    a.socket.destroy();
    b.socket.destroy();
  } finally {
    server.close();
  }
});

function freeCounts(map) {
  const b = Buffer.alloc(256 * 2);
  for (const [block, count] of Object.entries(map)) b.writeUInt16LE(count, Number(block) * 2);
  return b;
}

test('id blocks: most free unleased block, never shared, kept across reconnect', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  try {
    const a = await connect(port);
    const b = await connect(port);
    a.send(M.HELLO, hello('artem'));
    b.send(M.HELLO, hello('друг'));
    await a.next();
    await b.next();

    // both see the same world: block 7 is the emptiest, then 3; full blocks are never handed out
    const view = freeCounts({ 3: 200, 7: 250, 9: 10 });
    a.send(M.ID_BLOCK_REQUEST, view);
    assert.equal((await a.next()).payload.readUInt16LE(0), 7);
    b.send(M.ID_BLOCK_REQUEST, view);
    assert.equal((await b.next()).payload.readUInt16LE(0), 3);
    a.send(M.ID_BLOCK_REQUEST, view);
    assert.equal((await a.next()).payload.readUInt16LE(0), 9);
    b.send(M.ID_BLOCK_REQUEST, view);
    assert.equal((await b.next()).payload.readUInt16LE(0), 0xffff);

    // a reconnects under the same name and gets its blocks back right after WELCOME
    a.socket.destroy();
    await b.next(); // PEER_LEFT
    const a2 = await connect(port);
    a2.send(M.HELLO, hello('artem'));
    assert.equal((await a2.next()).type, M.WELCOME);
    const regranted = [(await a2.next()).payload.readUInt16LE(0), (await a2.next()).payload.readUInt16LE(0)];
    assert.deepEqual(regranted.sort((x, y) => x - y), [7, 9]);

    a2.socket.destroy();
    b.socket.destroy();
  } finally {
    server.close();
  }
});

test('item, release and spawn events reach others prefixed with the sender id', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  try {
    const a = await connect(port);
    const b = await connect(port);
    a.send(M.HELLO, hello('artem'));
    b.send(M.HELLO, hello('друг'));
    const idA = (await a.next()).payload.readUInt32LE(0);
    await b.next();

    const parent = Buffer.concat([Buffer.from([0x10, 0x27]), Buffer.from('medkit\0'), Buffer.from([2])]);
    a.send(M.ITEM_PARENT, parent);
    const got = await b.next();
    assert.equal(got.type, M.ITEM_PARENT);
    assert.equal(got.payload.readUInt32LE(0), idA);
    assert.deepEqual(got.payload.subarray(4), parent);

    const release = Buffer.concat([Buffer.from([0x10, 0x27]), Buffer.from('medkit\0')]);
    a.send(M.OBJECT_RELEASE, release);
    const rel = await b.next();
    assert.equal(rel.type, M.OBJECT_RELEASE);
    assert.equal(rel.payload.readUInt32LE(0), idA);
    assert.deepEqual(rel.payload.subarray(4), release);

    const spawn = Buffer.concat([Buffer.from([3, 0]), Buffer.from([1, 2, 3])]);
    a.send(M.OBJECT_SPAWN, spawn);
    const sp = await b.next();
    assert.equal(sp.type, M.OBJECT_SPAWN);
    assert.equal(sp.payload.readUInt32LE(0), idA);
    assert.deepEqual(sp.payload.subarray(4), spawn);

    a.socket.destroy();
    b.socket.destroy();
  } finally {
    server.close();
  }
});

async function roundTrip(c) {
  // the server answers in order, so after a PONG everything sent before it has arrived
  c.send(M.PING, Buffer.alloc(4));
  assert.equal((await c.next()).type, M.PONG);
}

test('the longest-connected player is sim master, handed over when it leaves', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  try {
    const a = await connect(port);
    a.send(M.HELLO, hello('artem'));
    const idA = (await a.next()).payload.readUInt32LE(0);
    const b = await connect(port);
    b.send(M.HELLO, hello('друг'));
    const idB = (await b.next()).payload.readUInt32LE(0);
    await roundTrip(a);
    await roundTrip(b);
    assert.equal(a.roles.at(-1), idA);
    assert.equal(b.roles.at(-1), idA);

    a.socket.destroy();
    assert.equal((await b.next()).type, M.PEER_LEFT);
    await roundTrip(b);
    assert.equal(b.roles.at(-1), idB);
    b.socket.destroy();
  } finally {
    server.close();
  }
});

// like roundTrip, skipping whatever else came first
async function settle(c) {
  c.send(M.PING, Buffer.alloc(4));
  await until(c, M.PONG);
}

// level -> its authority's id
function parseLevels(payload) {
  const out = {};
  let at = 1;
  for (let i = 0; i < payload[0]; i++) {
    const level = readStringZ(payload, at);
    at = payload.indexOf(0, at) + 1;
    out[level] = payload.readUInt32LE(at);
    at += 4;
  }
  return out;
}

test('a level is run by the player who came to it first, then by the next to have come', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  try {
    const a = await connect(port);
    a.send(M.HELLO, hello('artem'));
    const idA = (await a.next()).payload.readUInt32LE(0);
    const b = await connect(port);
    b.send(M.HELLO, hello('друг'));
    const idB = (await b.next()).payload.readUInt32LE(0);

    // b comes to Cordon first, though a has the lower id
    b.send(M.ACTOR_STATE, actorState('l01_escape', 0, 0, 0, 0));
    a.send(M.ACTOR_STATE, actorState('l02_garbage', 0, 0, 0, 0));
    await settle(b);
    await settle(a);
    a.send(M.ACTOR_STATE, actorState('l01_escape', 0, 0, 0, 0));
    await settle(a);
    await settle(b);
    assert.deepEqual(a.levels.at(-1), { l01_escape: idB });
    assert.deepEqual(b.levels.at(-1), { l01_escape: idB });

    // b goes away and comes back: a has been there longer now
    b.send(M.ACTOR_STATE, actorState('l02_garbage', 0, 0, 0, 0));
    await settle(b);
    b.send(M.ACTOR_STATE, actorState('l01_escape', 0, 0, 0, 0));
    await settle(b);
    await settle(a);
    assert.deepEqual(a.levels.at(-1), { l01_escape: idA });
    const count = b.levels.length;
    b.send(M.ACTOR_STATE, actorState('l01_escape', 5, 0, 0, 0)); // moving about there changes nothing
    await settle(b);
    assert.equal(b.levels.length, count);

    // a newcomer learns who runs what at once
    const c = await connect(port);
    c.send(M.HELLO, hello('третий'));
    await c.next();
    await settle(c);
    assert.deepEqual(c.levels.at(-1), { l01_escape: idA });

    // a goes to the menu, then b runs it; b leaves the server: nobody does
    a.send(M.LEFT_WORLD);
    await settle(a);
    await settle(c);
    assert.deepEqual(c.levels.at(-1), { l01_escape: idB });
    b.socket.destroy();
    assert.equal((await until(c, M.PEER_LEFT)).payload.readUInt32LE(0), idB);
    await settle(c);
    assert.deepEqual(c.levels.at(-1), {});
    a.socket.destroy();
    c.socket.destroy();
  } finally {
    server.close();
  }
});

function hostHello(name, secret) {
  return Buffer.concat([hello(name), Buffer.from([1]), encodeText(secret), Buffer.from([0])]);
}

test('the host: let in by its secret, the sim master once in the world, never a player', async () => {
  const server = await startServer({ ...options(), hostSecret: 'f00d' });
  const { port } = server.address();
  try {
    const a = await player(port, 'artem');
    await settle(a);
    const idA = a.roles.at(-1);
    a.send(M.ACTOR_STATE, actorState('l01_escape', 0, 0, 0, 0));
    await settle(a);
    assert.deepEqual(a.hosts.at(-1), { id: 0, name: '' });

    const wrong = await connect(port);
    wrong.send(M.HELLO, hostHello('host', 'beef'));
    const refused = await wrong.next();
    assert.equal(refused.type, M.REFUSED);
    assert.equal(refused.payload[0], REFUSED.HOST);

    const h = await connect(port);
    h.send(M.HELLO, hostHello('host', 'f00d'));
    const idH = (await h.next()).payload.readUInt32LE(0);
    await settle(a);
    assert.deepEqual(a.hosts.at(-1), { id: idH, name: 'host' });
    assert.equal(a.roles.at(-1), idA); // not in the world yet
    const second = await connect(port);
    second.send(M.HELLO, hostHello('host2', 'f00d'));
    assert.equal((await second.next()).payload[0], REFUSED.HOST);

    // in the world: the sim master; nobody sees it on a level
    h.send(M.ACTOR_STATE, actorState('fake_start', 0, 0, 0, 0));
    await settle(h);
    await settle(a);
    assert.equal(a.roles.at(-1), idH);
    assert.deepEqual(a.levels.at(-1), { l01_escape: idA });
    const status = server.coop.status();
    assert.deepEqual(status.online.map((p) => p.name), ['artem']);
    assert.equal(status.host.connected, true);
    assert.equal(status.host.master, true);

    // a newcomer doesn't see it either, and the host doesn't count against the player limit
    const b = await player(port, 'друг');
    await settle(b);
    assert.equal(b.hosts.at(-1).id, idH);
    assert.equal(b.roles.at(-1), idH);

    h.socket.destroy();
    await settle(a);
    assert.deepEqual(a.hosts.at(-1), { id: 0, name: '' });
    assert.equal(a.roles.at(-1), idA);
    a.socket.destroy();
    b.socket.destroy();
  } finally {
    server.close();
  }
});

test('the host: its autosave interval with the settings; without offline_sim paused while no player is in the world', async () => {
  const server = await startServer({ ...options(), hostSecret: 'f00d', autosaveMinutes: 7, pauseWhenEmpty: true });
  const { port } = server.address();
  try {
    const h = await connect(port);
    h.send(M.HELLO, hostHello('host', 'f00d'));
    await h.next();
    await settle(h);
    assert.match(h.settings.at(-1), /^autosave_minutes=7$/m);
    h.send(M.ACTOR_STATE, actorState('fake_start', 0, 0, 0, 0));
    // offline_sim (on by default): the empty world lives on, its clock runs
    assert.ok(!(await drain(h)).includes(M.PAUSED));
    const s = server.coop.settings();
    server.coop.saveSettings({ ...s, rules: { ...s.rules, offline_sim: false } });
    assert.deepEqual([...(await until(h, M.PAUSED)).payload], [1, ...Buffer.from('server'), 0]);

    const a = await player(port, 'artem');
    await settle(a);
    a.send(M.ACTOR_STATE, actorState('l01_escape', 0, 0, 0, 0));
    assert.equal((await until(h, M.PAUSED)).payload[0], 0);
    assert.ok(!(await drain(a)).includes(M.PAUSED)); // the players never hear of it
    a.send(M.LEFT_WORLD);
    assert.equal((await until(h, M.PAUSED)).payload[0], 1);
    h.socket.destroy();
    a.socket.destroy();
  } finally {
    server.close();
  }
});

test('the admin window: the admin password, then the admin page commands; the state after each', async () => {
  const server = await startServer({ ...options(), adminPassword: 'секрет' });
  const { port } = server.address();
  const text = (msg) => readStringZ(msg.payload, 0);
  const line = (str) => Buffer.concat([encodeText(str), Buffer.from([0])]);
  const auth = async (c) => text(await until(c, M.ADMIN_STATE)).split('\n')[0].split('\t');
  try {
    const a = await player(port, 'artem');
    const b = await player(port, 'друг');
    a.send(M.ADMIN_COMMAND, line('save'));
    assert.deepEqual((await auth(a)).slice(0, 2), ['auth', 'need']);
    a.send(M.ADMIN_LOGIN, line('не тот'));
    const wrong = await auth(a);
    assert.deepEqual(wrong.slice(0, 2), ['auth', 'wrong']);
    assert.match(wrong[3], /Неверный/);
    a.send(M.ADMIN_LOGIN, line('секрет'));
    const state = text(await until(a, M.ADMIN_STATE)).split('\n').map((l) => l.split('\t'));
    assert.deepEqual(state[0].slice(0, 2), ['auth', 'ok']);
    assert.match(state[0][2], /^token:[0-9a-f]{64}$/);
    assert.deepEqual(state.find((l) => l[0] === 'host').slice(0, 2), ['host', 'нет: мир держит игра игрока']);
    assert.deepEqual(state.find((l) => l[2] === 'group_max').slice(0, 4), ['setting', 'rules', 'group_max', '4']);
    assert.deepEqual(state.filter((l) => l[0] === 'player').map((l) => l[1]), ['artem', 'друг']);
    assert.deepEqual(state.find((l) => l[1] === 'monolith').slice(0, 3), ['faction', 'monolith', '1']);

    a.send(M.ADMIN_COMMAND, line('set\tgroup_max\t3'));
    assert.match(text(await until(a, M.ADMIN_RESULT)), /3$/);
    assert.equal(server.coop.settings().rules.group_max, 3);
    assert.match(text(await until(a, M.ADMIN_STATE)), /setting\trules\tgroup_max\t3/);
    a.send(M.ADMIN_COMMAND, line('faction\tmonolith\toff'));
    assert.match(text(await until(a, M.ADMIN_RESULT)), /Монолит: нет/);
    assert.ok(!server.coop.settings().factions.includes('monolith'));
    a.send(M.ADMIN_COMMAND, line('kick\tдруг'));
    assert.match(text(await until(a, M.ADMIN_RESULT)), /Отключён: друг/);
    await until(a, M.PEER_LEFT);
    a.socket.destroy();
    b.socket.destroy();
  } finally {
    server.close();
  }
});

test('the admin window: a token instead of the password; it stops working once the password changes', async () => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'coop-test-'));
  const text = (msg) => readStringZ(msg.payload, 0);
  const line = (str) => Buffer.concat([encodeText(str), Buffer.from([0])]);
  let server = await startServer({ ...options(dataDir), adminPassword: 'секрет' });
  let token;
  try {
    const a = await player(server.address().port, 'artem');
    a.send(M.ADMIN_LOGIN, line('секрет'));
    token = text(await until(a, M.ADMIN_STATE)).split('\n')[0].split('\t')[2];
    assert.ok(!token.includes('секрет'));
    const b = await player(server.address().port, 'друг');
    b.send(M.ADMIN_LOGIN, line(token));
    assert.deepEqual(text(await until(b, M.ADMIN_STATE)).split('\n')[0].split('\t'), ['auth', 'ok', token]);
    a.socket.destroy();
    b.socket.destroy();
  } finally {
    server.close();
  }
  // the same data (the salt) with another password: the old token is a wrong password
  server = await startServer({ ...options(dataDir), adminPassword: 'другой' });
  try {
    const a = await player(server.address().port, 'artem');
    a.send(M.ADMIN_LOGIN, line(token));
    assert.equal(text(await until(a, M.ADMIN_STATE)).split('\t')[1], 'wrong');
    a.socket.destroy();
  } finally {
    server.close();
  }
});

test('the admin window: 5 wrong passwords lock the address out with an answer, a reconnect too, until the time is up', async () => {
  const server = await startServer({ ...options(), adminPassword: 'секрет', adminLockMs: 400 });
  const { port } = server.address();
  const text = (msg) => readStringZ(msg.payload, 0);
  const line = (str) => Buffer.concat([encodeText(str), Buffer.from([0])]);
  const auth = async (c) => text(await until(c, M.ADMIN_STATE)).split('\t');
  try {
    const a = await player(port, 'artem');
    for (let i = 0; i < 4; i++) {
      a.send(M.ADMIN_LOGIN, line('не тот'));
      assert.equal((await auth(a))[1], 'wrong');
    }
    a.send(M.ADMIN_LOGIN, line('не тот'));
    const locked = await auth(a);
    assert.equal(locked[1], 'locked');
    assert.equal(locked[2], '1');
    assert.match(locked[3], /закрыт на 1 с/);
    // the right password doesn't help while locked, nor another connection from there
    a.send(M.ADMIN_LOGIN, line('секрет'));
    assert.equal((await auth(a))[1], 'locked');
    const b = await player(port, 'друг');
    b.send(M.ADMIN_LOGIN, line('секрет'));
    assert.equal((await auth(b))[1], 'locked');
    await new Promise((r) => setTimeout(r, 450));
    b.send(M.ADMIN_LOGIN, line('секрет'));
    assert.equal((await auth(b))[1], 'ok');
    a.socket.destroy();
    b.socket.destroy();
  } finally {
    server.close();
  }
});

test('a level NPC stream goes to the players on that level and the host only', async () => {
  const server = await startServer({ ...options(), hostSecret: 'f00d' });
  const { port } = server.address();
  try {
    const a = await player(port, 'artem');
    const b = await player(port, 'друг');
    const c = await player(port, 'третий');
    const h = await connect(port);
    h.send(M.HELLO, hostHello('host', 'f00d'));
    await h.next();
    a.send(M.ACTOR_STATE, actorState('l01_escape', 0, 0, 0, 0));
    b.send(M.ACTOR_STATE, actorState('l01_escape', 1, 0, 0, 0));
    c.send(M.ACTOR_STATE, actorState('l05_bar', 0, 0, 0, 0));
    await settle(a);
    await settle(b);
    await settle(c);
    await settle(h);
    a.send(M.NPC_STATES, Buffer.concat([encodeText('l01_escape'), Buffer.from([0]), Buffer.from('npcs')]));
    await settle(a);
    assert.equal((await until(b, M.NPC_STATES)).payload.readUInt32LE(0), a.roles.at(-1));
    await until(h, M.NPC_STATES);
    assert.ok(!(await drain(c)).includes(M.NPC_STATES));
    for (const x of [a, b, c, h]) x.socket.destroy();
  } finally {
    server.close();
  }
});

test('script events reach others with the sender id', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  try {
    const a = await connect(port);
    const b = await connect(port);
    a.send(M.HELLO, hello('artem'));
    b.send(M.HELLO, hello('друг'));
    const idA = (await a.next()).payload.readUInt32LE(0);
    await b.next();

    const event = Buffer.from('stash_opened ' + '1234 ');
    a.send(M.SCRIPT_EVENT, event);
    const got = await b.next();
    assert.equal(got.type, M.SCRIPT_EVENT);
    assert.equal(got.payload.readUInt32LE(0), idA);
    assert.deepEqual(got.payload.subarray(4), event);
    a.socket.destroy();
    b.socket.destroy();
  } finally {
    server.close();
  }
});

function worldInfo(payload) {
  const end = payload.indexOf(0, 1);
  return { has: payload[0] === 1, owner: readStringZ(payload, 1), revision: payload.readUInt32LE(end + 1),
    creator: readStringZ(payload, end + 5) };
}

function chunks(data, file) {
  const out = [];
  for (let offset = 0; offset < data.length; offset += 15000)
    out.push(Buffer.concat([Buffer.from([file]), (() => { const b = Buffer.alloc(4); b.writeUInt32LE(offset); return b; })(), data.subarray(offset, offset + 15000)]));
  return out;
}

async function uploadWorld(c, files) {
  const sizes = Buffer.alloc(8);
  sizes.writeUInt32LE(files[0].length, 0);
  sizes.writeUInt32LE(files[1].length, 4);
  c.send(M.WORLD_UPLOAD, sizes);
  files.forEach((data, file) => chunks(data, file).forEach((ch) => c.send(M.WORLD_CHUNK, ch)));
  c.send(M.WORLD_DONE);
}

test('world: uploaded into an empty server, announced to all, downloaded in chunks', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  try {
    const a = await connect(port);
    a.send(M.HELLO, hello('artem'));
    await a.next();
    await roundTrip(a);
    assert.deepEqual(worldInfo(a.worldInfo[0]), { has: false, owner: '', revision: 0, creator: '' });

    const scop = Buffer.alloc(40000, 7);
    scop.write('scop', 0);
    const scoc = Buffer.from('lua state');
    await uploadWorld(a, [scop, scoc]);
    await roundTrip(a);
    assert.deepEqual(worldInfo(a.worldInfo.at(-1)), { has: true, owner: 'artem', revision: 1, creator: '' });

    const b = await connect(port);
    b.send(M.HELLO, hello('друг'));
    await b.next();
    await roundTrip(b);
    assert.deepEqual(worldInfo(b.worldInfo[0]), { has: true, owner: 'artem', revision: 1, creator: '' });

    b.send(M.WORLD_REQUEST);
    const files = [Buffer.alloc(scop.length), Buffer.alloc(scoc.length)];
    for (;;) {
      const msg = await b.next();
      if (msg.type === M.WORLD_DONE) {
        assert.equal(msg.payload.toString('utf8', 0, msg.payload.indexOf(0)), 'artem');
        break;
      }
      if (msg.type === M.PROGRESS) {
        assert.equal(msg.payload.readUInt32LE(0), 0); // none kept for this player
        continue;
      }
      if (msg.type === M.NAMES) continue; // the journal's names (here, no journal)
      assert.equal(msg.type, M.WORLD_CHUNK);
      msg.payload.copy(files[msg.payload[0]], msg.payload.readUInt32LE(1), 5);
    }
    assert.deepEqual(files[0], scop);
    assert.deepEqual(files[1], scoc);
    a.socket.destroy();
    b.socket.destroy();
  } finally {
    server.close();
  }
});

test('world: only the sim master replaces an existing world', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  try {
    const a = await connect(port);
    a.send(M.HELLO, hello('artem'));
    await a.next();
    await uploadWorld(a, [Buffer.from('first'), Buffer.from('x')]);
    const b = await connect(port);
    b.send(M.HELLO, hello('друг'));
    await b.next();
    await uploadWorld(b, [Buffer.from('second'), Buffer.from('y')]);
    await roundTrip(b);
    await roundTrip(a);
    assert.equal(worldInfo(b.worldInfo.at(-1)).revision, 1);
    assert.equal(worldInfo(a.worldInfo.at(-1)).owner, 'artem');
    a.socket.destroy();
    b.socket.destroy();
  } finally {
    server.close();
  }
});

test('world: on an empty server only the first claim may create it, free again when that player leaves', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  try {
    const a = await connect(port);
    a.send(M.HELLO, hello('artem'));
    await a.next();
    const b = await connect(port);
    b.send(M.HELLO, hello('друг'));
    await b.next();

    a.send(M.WORLD_CLAIM, Buffer.from([1]));
    await roundTrip(a);
    b.send(M.WORLD_CLAIM, Buffer.from([1]));
    await roundTrip(b);
    assert.equal(worldInfo(a.worldInfo.at(-1)).creator, 'artem');
    assert.deepEqual(worldInfo(b.worldInfo.at(-1)), { has: false, owner: '', revision: 0, creator: 'artem' });

    await uploadWorld(b, [Buffer.from('second'), Buffer.from('y')]);
    await roundTrip(b);
    assert.equal(worldInfo(b.worldInfo.at(-1)).has, false);

    a.socket.destroy();
    assert.equal((await b.next()).type, M.PEER_LEFT);
    await roundTrip(b);
    assert.equal(worldInfo(b.worldInfo.at(-1)).creator, '');

    b.send(M.WORLD_CLAIM, Buffer.from([1]));
    await roundTrip(b);
    assert.equal(worldInfo(b.worldInfo.at(-1)).creator, 'друг');
    b.send(M.WORLD_CLAIM, Buffer.from([0])); // backed out of the new game screen
    await roundTrip(b);
    assert.equal(worldInfo(b.worldInfo.at(-1)).creator, '');

    b.send(M.WORLD_CLAIM, Buffer.from([1]));
    await uploadWorld(b, [Buffer.from('second'), Buffer.from('y')]);
    await roundTrip(b);
    assert.deepEqual(worldInfo(b.worldInfo.at(-1)), { has: true, owner: 'друг', revision: 1, creator: '' });
    b.socket.destroy();
  } finally {
    server.close();
  }
});

test('characters, leases and the world survive a server restart', async () => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'coop-test-'));
  let server = await startServer(options(dataDir));
  const view = Buffer.alloc(512);
  view.writeUInt16LE(100, 5 * 2);
  try {
    const a = await connect(server.address().port);
    a.send(M.HELLO, hello('artem'));
    await a.next();
    a.send(M.CHARACTER, Buffer.from('my record'));
    a.send(M.ID_BLOCK_REQUEST, view);
    assert.equal((await a.next()).payload.readUInt16LE(0), 5);
    await uploadWorld(a, [Buffer.from('world'), Buffer.from('lua')]);
    await roundTrip(a);
    a.socket.destroy();
  } finally {
    server.close();
  }

  server = await startServer(options(dataDir));
  try {
    const a = await connect(server.address().port);
    a.send(M.HELLO, hello('artem'));
    assert.equal((await a.next()).type, M.WELCOME);
    const record = await a.next();
    assert.equal(record.type, M.CHARACTER);
    assert.equal(record.payload.toString(), 'my record');
    assert.equal((await a.next()).payload.readUInt16LE(0), 5); // the block is still ours
    await roundTrip(a);
    assert.deepEqual(worldInfo(a.worldInfo[0]), { has: true, owner: 'artem', revision: 1, creator: '' });
    a.socket.destroy();
  } finally {
    server.close();
  }
});

test('settings: sent after welcome and to everyone when the admin changes them', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  try {
    const a = await connect(port);
    a.send(M.HELLO, hello('artem'));
    await a.next(); // WELCOME
    await new Promise((r) => setTimeout(r, 20));
    assert.match(a.settings[0], /^story=1$/m);
    assert.match(a.settings[0], /^factions=stalker,dolg,/m);

    server.coop.saveSettings({ world: { survival: true }, factions: ['monolith'] });
    await new Promise((r) => setTimeout(r, 20));
    assert.match(a.settings[1], /^survival=1$/m);
    assert.match(a.settings[1], /^factions=monolith$/m);
    a.socket.destroy();
  } finally {
    server.close();
  }
});

test('actor actions reach others with the sender id, not the sender', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  try {
    const a = await connect(port);
    const b = await connect(port);
    a.send(M.HELLO, hello('artem'));
    b.send(M.HELLO, hello('friend'));
    const idA = (await a.next()).payload.readUInt32LE(0);
    await b.next();

    const shot = Buffer.from([0, 2]); // eShot, silenced
    a.send(M.ACTOR_ACTION, shot);
    const got = await b.next();
    assert.equal(got.type, M.ACTOR_ACTION);
    assert.equal(got.payload.readUInt32LE(0), idA);
    assert.deepEqual(got.payload.subarray(4), shot);
    a.socket.destroy();
    b.socket.destroy();
  } finally {
    server.close();
  }
});

// GROUPS as [[members...]], or with story: [{ members, story }]
function groupsOf(payload, withFlags = false) {
  const out = [];
  let at = 1;
  for (let g = 0; g < payload[0]; g++) {
    const members = [];
    for (let n = payload[at++]; n > 0; n--) {
      members.push(readStringZ(payload, at));
      at = payload.indexOf(0, at) + 1;
    }
    const flags = payload[at++];
    out.push(withFlags ? { members, story: (flags & GROUP_FLAG.STORY) !== 0 } : members);
  }
  return out;
}

test('groups: invite, accept, leader kicks, leaving dissolves a group of two', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  const wait = () => new Promise((r) => setTimeout(r, 30));
  const names = (payload) => groupsOf(payload);
  const action = (kind, id) => {
    const p = Buffer.alloc(5);
    p[0] = kind;
    p.writeUInt32LE(id, 1);
    return p;
  };
  try {
    const a = await connect(port);
    const b = await connect(port);
    const c = await connect(port);
    a.send(M.HELLO, hello('artem'));
    b.send(M.HELLO, hello('друг'));
    c.send(M.HELLO, hello('third'));
    const idA = (await a.next()).payload.readUInt32LE(0);
    const idB = (await b.next()).payload.readUInt32LE(0);
    const idC = (await c.next()).payload.readUInt32LE(0);
    await wait();
    assert.deepEqual(names(a.groups.at(-1)), []);

    a.send(M.GROUP, action(GROUP.INVITE, idB));
    const invite = await b.next();
    assert.equal(invite.type, M.GROUP_INVITE);
    assert.equal(invite.payload.readUInt32LE(0), idA);
    assert.equal(readStringZ(invite.payload, 4), 'artem');
    b.send(M.GROUP, action(GROUP.ACCEPT, idA));
    await wait();
    assert.deepEqual(names(c.groups.at(-1)), [['artem', 'друг']]);

    // a member invites too; the leader stays
    b.send(M.GROUP, action(GROUP.INVITE, idC));
    assert.equal((await c.next()).type, M.GROUP_INVITE);
    c.send(M.GROUP, action(GROUP.ACCEPT, idB));
    await wait();
    assert.deepEqual(names(a.groups.at(-1)), [['artem', 'друг', 'third']]);

    // only the leader shares the group's story, and stops it
    b.send(M.GROUP, Buffer.from([GROUP.STORY, 1]));
    await wait();
    assert.deepEqual(groupsOf(a.groups.at(-1), true), [{ members: ['artem', 'друг', 'third'], story: false }]);
    a.send(M.GROUP, Buffer.from([GROUP.STORY, 1]));
    await wait();
    assert.deepEqual(groupsOf(c.groups.at(-1), true), [{ members: ['artem', 'друг', 'third'], story: true }]);

    // only the leader puts one out
    b.send(M.GROUP, Buffer.concat([Buffer.from([GROUP.KICK]), encodeText('third'), Buffer.from([0])]));
    a.send(M.GROUP, Buffer.concat([Buffer.from([GROUP.KICK]), encodeText('third'), Buffer.from([0])]));
    await wait();
    assert.deepEqual(groupsOf(a.groups.at(-1), true), [{ members: ['artem', 'друг'], story: true }]);

    // an invite not accepted in time, or never sent, joins nobody
    c.send(M.GROUP, action(GROUP.ACCEPT, idA));
    const note = await c.next();
    assert.equal(note.type, M.GROUP_NOTE);
    assert.equal(note.payload[0], GROUP_NOTE.EXPIRED);

    b.send(M.GROUP, Buffer.from([GROUP.LEAVE]));
    await wait();
    assert.deepEqual(names(a.groups.at(-1)), []);
    for (const x of [a, b, c]) x.socket.destroy();
  } finally {
    server.close();
  }
});

// skips other messages until one of that type
async function until(c, type) {
  for (;;) {
    const msg = await c.next();
    if (msg.type === type) return msg;
  }
}

function uploadMeta(files, base, name, reason, who) {
  const head = Buffer.alloc(12);
  head.writeUInt32LE(files[0].length, 0);
  head.writeUInt32LE(files[1].length, 4);
  head.writeUInt32LE(base, 8);
  return Buffer.concat([head, ...[name, reason, who].map((s) => Buffer.concat([encodeText(s), Buffer.from([0])]))]);
}

async function uploadSave(c, files, base, name = '', reason = 'auto', who = '') {
  c.send(M.WORLD_UPLOAD, uploadMeta(files, base, name, reason, who));
  files.forEach((data, file) => chunks(data, file).forEach((ch) => c.send(M.WORLD_CHUNK, ch)));
  c.send(M.WORLD_DONE);
}

function saveNow(msg) {
  const [name, reason, who] = readStringsZ(msg.payload, 0, 3);
  return { name, reason, who };
}

async function player(port, name) {
  const c = await connect(port);
  c.send(M.HELLO, hello(name));
  assert.equal((await c.next()).type, M.WELCOME);
  return c;
}

// the message types that came before a round trip's PONG
async function drain(c) {
  c.send(M.PING, Buffer.alloc(4));
  const types = [];
  for (;;) {
    const msg = await c.next();
    if (msg.type === M.PONG) return types;
    types.push(msg.type);
  }
}

function event(name, payload) {
  return Buffer.concat([encodeText(name), Buffer.from([0]), encodeText(payload), Buffer.from([0])]);
}

function u16le(v) {
  const b = Buffer.alloc(2);
  b.writeUInt16LE(v, 0);
  return b;
}

test('saves: the master saves when asked; a player coming in gets the last save and the journal since, nobody saves', async () => {
  const server = await startServer({ ...options(), journalOverlapMs: 0 });
  const { port } = server.address();
  try {
    const menu = await player(port, 'menu');       // lowest id, stays in the main menu
    const master = await player(port, 'master');
    await uploadSave(master, [Buffer.from('w1'), Buffer.from('l1')], 0, '', 'new', 'master');
    await roundTrip(master);
    master.send(M.ACTOR_STATE, actorState('l01_escape', 0, 0, 0, 0));
    await roundTrip(master);
    assert.equal(master.roles.at(-1), 2); // in the world: the master now, not the one in the menu

    // world changes since the save are kept; Lua events only when they change the world
    master.send(M.ITEM_PARENT, Buffer.from('item 1'));
    master.send(M.SCRIPT_EVENT, event('news', 'hello'));
    master.send(M.SCRIPT_EVENT, event('stash_opened', '77'));
    master.send(M.ENTITY_DEATH, Buffer.from('death'));
    master.send(M.NPC_STATES, Buffer.from('npcs'));
    await roundTrip(master);

    // a player coming in: the save and the journal at once, nobody saves
    const joiner = await player(port, 'joiner');
    joiner.send(M.WORLD_REQUEST);
    const journal = [];
    let names = null;
    for (;;) {
      const msg = await joiner.next();
      if (msg.type === M.NAMES) names = msg.payload;
      if (msg.type === M.JOURNAL) journal.push(msg.payload);
      if (msg.type !== M.WORLD_DONE) continue;
      assert.equal(msg.payload.readUInt32LE(msg.payload.indexOf(0) + 1), 1);
      break;
    }
    const by = (type, payload, id = 2) => Buffer.concat([u16le(type), ...(id ? [u32le(id)] : []), payload]);
    assert.deepEqual(journal, [by(M.ITEM_PARENT, Buffer.from('item 1')), by(M.SCRIPT_EVENT, event('stash_opened', '77')),
      by(M.ENTITY_DEATH, Buffer.from('death'), 0)]);
    assert.equal(names.readUInt16LE(0), 3);
    assert.deepEqual(readStringsZ(names, 2 + 4, 1), ['menu']);
    assert.ok(!(await drain(master)).includes(M.SAVE_NOW));

    // the admin asks (players save their characters, not the world)
    assert.ok(server.coop.saveWorld());
    assert.deepEqual(saveNow(await until(master, M.SAVE_NOW)), { name: '', reason: 'admin', who: 'admin' });
    await uploadSave(master, [Buffer.from('w2'), Buffer.from('l2')], 1, '', 'admin', 'admin');
    await roundTrip(master);

    // a player in the world leaving: no save either; the new save started the journal again
    joiner.send(M.ACTOR_STATE, actorState('l01_escape', 1, 0, 0, 0));
    await roundTrip(joiner);
    joiner.socket.destroy();
    await until(master, M.PEER_LEFT);
    assert.ok(!(await drain(master)).includes(M.SAVE_NOW));
    const late = await player(port, 'late');
    late.send(M.WORLD_REQUEST);
    const types = [];
    for (let msg = await late.next(); msg.type !== M.WORLD_DONE; msg = await late.next()) types.push(msg.type);
    assert.ok(!types.includes(M.JOURNAL));

    assert.deepEqual(server.coop.status().saves.map((m) => [m.revision, m.reason]), [[2, 'admin'], [1, 'new']]);
    menu.socket.destroy();
    master.socket.destroy();
    late.socket.destroy();
  } finally {
    server.close();
  }
});

test('the journal and the client ids outlive a server restart', async () => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'coop-test-'));
  let server = await startServer(options(dataDir));
  try {
    const a = await player(server.address().port, 'artem');
    await uploadSave(a, [Buffer.from('w1'), Buffer.from('l1')], 0, '', 'new', 'artem');
    a.send(M.ITEM_PARENT, Buffer.from('item 1'));
    await roundTrip(a);
    a.socket.destroy();
  } finally {
    server.close();
  }
  server = await startServer(options(dataDir));
  try {
    const b = await connect(server.address().port);
    b.send(M.HELLO, hello('друг'));
    assert.equal((await b.next()).payload.readUInt32LE(0), 2); // after artem's 1
    b.send(M.WORLD_REQUEST);
    const journal = [];
    let names = null;
    for (let msg = await b.next(); msg.type !== M.WORLD_DONE; msg = await b.next()) {
      if (msg.type === M.JOURNAL) journal.push(msg.payload);
      if (msg.type === M.NAMES) names = msg.payload;
    }
    assert.deepEqual(journal, [Buffer.concat([u16le(M.ITEM_PARENT), u32le(1), Buffer.from('item 1')])]);
    assert.equal(names.readUInt16LE(0), 2);
    assert.deepEqual(readStringsZ(names, 2 + 4, 1), ['artem']);
    b.socket.destroy();
  } finally {
    server.close();
  }
});

function snapshot(record, progress, things) {
  const sized = (b) => Buffer.concat([u32le(b.length), b]);
  return Buffer.concat([sized(Buffer.from(record)), sized(Buffer.from(progress)), Buffer.from(things)]);
}

function sendSnapshot(c, saveId, data) {
  for (let offset = 0; offset === 0 || offset < data.length; offset += 15000)
    c.send(M.SNAPSHOT, Buffer.concat([u32le(saveId), u32le(data.length), u32le(offset), data.subarray(offset, offset + 15000)]));
}

// [{ id, name, reason, who }] of a SAVES
function charSaves(payload) {
  const out = [];
  let at = 2;
  for (let i = 0; i < payload.readUInt16LE(0); i++) {
    const id = payload.readUInt32LE(at);
    const [name, reason, who] = readStringsZ(payload, at + 8, 3);
    at += 8 + [name, reason, who].reduce((n, t) => n + encodeText(t).length + 1, 0) + 4;
    out.push({ id, name, reason, who });
  }
  return out;
}

// what a world download brings: the things of a save gone back to, the progress
async function download(c) {
  c.send(M.WORLD_REQUEST);
  let things = null;
  let progress = null;
  for (;;) {
    const msg = await c.next();
    if (msg.type === M.WORLD_DONE) return { things, progress };
    if (msg.type === M.SNAPSHOT_THINGS) {
      things ??= Buffer.alloc(msg.payload.readUInt32LE(0));
      msg.payload.copy(things, msg.payload.readUInt32LE(4), 8);
    }
    if (msg.type === M.PROGRESS && msg.payload.readUInt32LE(0)) {
      progress ??= Buffer.alloc(msg.payload.readUInt32LE(0));
      msg.payload.copy(progress, msg.payload.readUInt32LE(4), 8);
    }
  }
}

test('character saves: a snapshot of the character; going back puts it back, with its things, the world stays', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  const action = (kind, id) => Buffer.concat([Buffer.from([kind]), u32le(id), Buffer.from([0])]);
  try {
    const a = await player(port, 'artem');
    const b = await player(port, 'друг');
    const idA = a.roles.at(-1) ?? 1;
    a.send(M.ACTOR_STATE, actorState('l01_escape', 0, 0, 0, 0));
    b.send(M.ACTOR_STATE, actorState('l01_escape', 1, 0, 0, 0));
    await uploadSave(a, [Buffer.from('w1'), Buffer.from('l1')], 0, '', 'new', 'artem');
    await settle(a);
    await settle(b);

    // alone: their own game makes it
    a.send(M.SAVE_REQUEST, Buffer.concat([encodeText('Перед Баром'), Buffer.from([0])]));
    const asked = await until(a, M.SNAPSHOT_REQUEST);
    const id1 = asked.payload.readUInt32LE(0);
    sendSnapshot(a, id1, snapshot('record 1', 'progress 1', Buffer.alloc(20000, 3)));
    a.send(M.CHARACTER, Buffer.from('record later'));
    await settle(a);
    a.send(M.SAVES_REQUEST);
    assert.deepEqual(charSaves((await until(a, M.SAVES)).payload), [{ id: id1, name: 'Перед Баром', reason: 'named', who: 'artem' }]);
    b.send(M.SAVES_REQUEST);
    assert.deepEqual(charSaves((await until(b, M.SAVES)).payload), []);

    // back to it: the record, a reload, and the things with the next download, once
    a.send(M.LOAD_REQUEST, u32le(id1));
    assert.equal((await until(a, M.CHARACTER)).payload.toString(), 'record 1');
    await until(a, M.WORLD_RELOAD);
    const done = await until(a, M.LOAD_RESULT);
    assert.equal(done.payload[0], LOAD.DONE);
    const got = await download(a);
    assert.deepEqual(got.things, Buffer.concat([Buffer.alloc(20000, 3), Buffer.alloc(2)])); // nothing taken since
    assert.equal(got.progress.toString(), 'progress 1');
    assert.equal((await download(a)).things, null);
    assert.equal(server.coop.status().world.revision, 1); // the world didn't go back

    // a group: its leader saves everyone in the world; the others don't, and can't load it
    a.send(M.GROUP, action(GROUP.INVITE, 2));
    await until(b, M.GROUP_INVITE);
    b.send(M.GROUP, action(GROUP.ACCEPT, idA));
    await settle(b);
    b.send(M.SAVE_REQUEST, Buffer.from([0]));
    assert.ok(!(await drain(b)).includes(M.SNAPSHOT_REQUEST));
    a.send(M.SAVE_REQUEST, Buffer.from([0]));
    const id2 = (await until(a, M.SNAPSHOT_REQUEST)).payload.readUInt32LE(0);
    assert.equal((await until(b, M.SNAPSHOT_REQUEST)).payload.readUInt32LE(0), id2);
    sendSnapshot(a, id2, snapshot('record a', '', 'things a'));
    sendSnapshot(b, id2, snapshot('record b', 'progress b', 'things b'));
    await until(a, M.SCRIPT_EVENT); // a runs the world: it keeps what's near where b saved
    await settle(a);
    await settle(b);
    b.send(M.SAVES_REQUEST);
    assert.deepEqual(charSaves((await until(b, M.SAVES)).payload), [{ id: id2, name: '', reason: 'group', who: 'artem' }]);
    b.send(M.LOAD_REQUEST, u32le(id2));
    assert.equal((await until(b, M.LOAD_RESULT)).payload[0], LOAD.LEADER_ONLY);
    a.send(M.LOAD_REQUEST, u32le(999));
    assert.equal((await until(a, M.LOAD_RESULT)).payload[0], LOAD.NO_SAVE);
    a.send(M.LOAD_REQUEST, u32le(id2));
    assert.equal((await until(b, M.CHARACTER)).payload.toString(), 'record b');
    await until(b, M.WORLD_RELOAD);
    assert.equal((await until(a, M.CHARACTER)).payload.toString(), 'record a');
    assert.equal((await download(b)).things.toString(), 'things b\0\0');
    assert.equal((await download(a)).progress.toString(), 'progress 1'); // none in the save: theirs stays
    a.socket.destroy();
    b.socket.destroy();
  } finally {
    server.close();
  }
});

function sendProgress(c, data) {
  for (let offset = 0; offset === 0 || offset < data.length; offset += 15000)
    c.send(M.PROGRESS, Buffer.concat([u32le(data.length), u32le(offset), data.subarray(offset, offset + 15000)]));
}

// the progress that comes with a world download, null when the server keeps none
async function downloadProgress(c) {
  let progress = null;
  for (;;) {
    const msg = await c.next();
    if (msg.type === M.WORLD_DONE) return progress;
    if (msg.type !== M.PROGRESS) continue;
    const total = msg.payload.readUInt32LE(0);
    if (!total) continue;
    progress ??= Buffer.alloc(total);
    msg.payload.copy(progress, msg.payload.readUInt32LE(4), 8);
  }
}

test('progress: asked of everyone in the world with each save, given back with the world, rolled back with it', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  try {
    const a = await player(port, 'artem');
    const b = await player(port, 'друг');
    a.send(M.ACTOR_STATE, actorState('l01_escape', 0, 0, 0, 0));
    b.send(M.ACTOR_STATE, actorState('l01_escape', 1, 0, 0, 0));
    await until(a, M.PEER_STATE); // b's state reaches a in no fixed order with a's own replies
    await uploadSave(a, [Buffer.from('w1'), Buffer.from('l1')], 0, '', 'new', 'artem');
    await roundTrip(a);

    // a save: everyone in the world is asked for their progress
    assert.ok(server.coop.saveWorld());
    await until(a, M.PROGRESS_REQUEST); // the master too
    await until(a, M.SAVE_NOW);
    await until(b, M.PROGRESS_REQUEST);
    const early = Buffer.alloc(40000, 1); // three chunks
    early.write('early', 0);
    sendProgress(b, early);
    await roundTrip(b);
    await uploadSave(a, [Buffer.from('w2'), Buffer.from('l2')], 1);
    await roundTrip(a);
    const late = Buffer.from('late');
    sendProgress(b, late);
    sendProgress(b, Buffer.alloc(0)); // nothing to keep: no change
    await roundTrip(b);

    // b comes back: its latest progress comes with the world, before WORLD_DONE (no save for leaving or coming)
    b.socket.destroy();
    const b2 = await player(port, 'друг');
    b2.send(M.WORLD_REQUEST);
    assert.deepEqual(await downloadProgress(b2), late);

    // a player without progress gets none
    const c = await player(port, 'третий');
    c.send(M.WORLD_REQUEST);
    assert.equal(await downloadProgress(c), null);

    // the world as it is can't be gone back to; a save after it, then back to revision 2: the progress kept with it
    assert.equal(server.coop.rollback(2), 0);
    await uploadSave(a, [Buffer.from('w3'), Buffer.from('l3')], 2);
    a.send(M.PING, Buffer.alloc(4));
    await until(a, M.PONG);
    assert.ok(server.coop.rollback(2));
    await until(b2, M.WORLD_RELOAD);
    b2.send(M.WORLD_REQUEST);
    assert.deepEqual(await downloadProgress(b2), early);
    a.socket.destroy();
    b2.socket.destroy();
    c.socket.destroy();
  } finally {
    server.close();
  }
});

function u32le(v) {
  const b = Buffer.alloc(4);
  b.writeUInt32LE(v, 0);
  return b;
}

test('pause: everyone in the world agrees to pause and to go on; alone, at once; newcomers learn it', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  const pausedOf = (msg) => ({ paused: msg.payload[0] === 1, by: readStringZ(msg.payload, 1) });
  try {
    const a = await player(port, 'artem');
    a.send(M.ACTOR_STATE, actorState('l01_escape', 0, 0, 0, 0));
    await roundTrip(a);
    a.send(M.PAUSE_PROPOSE, Buffer.from([1])); // alone in the world: no vote
    assert.deepEqual(pausedOf(await until(a, M.PAUSED)), { paused: true, by: 'artem' });
    a.send(M.PAUSE_PROPOSE, Buffer.from([0]));
    assert.deepEqual(pausedOf(await until(a, M.PAUSED)), { paused: false, by: '' });

    const b = await player(port, 'друг');
    b.send(M.ACTOR_STATE, actorState('l01_escape', 1, 0, 0, 0));
    b.send(M.PING, Buffer.alloc(4));
    await until(b, M.PONG); // b is in the world now: it has a say
    a.send(M.PAUSE_PROPOSE, Buffer.from([1]));
    const ask = await until(b, M.PAUSE_VOTE);
    assert.equal(readStringZ(ask.payload, 4), 'artem');
    b.send(M.ROLLBACK_ANSWER, Buffer.from([1]));
    assert.deepEqual(pausedOf(await until(b, M.PAUSED)), { paused: true, by: 'artem' });
    assert.equal((await until(b, M.PAUSE_RESULT)).payload[0], ROLLBACK.ACCEPTED);

    const c = await player(port, 'третий'); // comes in while paused
    assert.deepEqual(pausedOf(await until(c, M.PAUSED)), { paused: true, by: 'artem' });

    b.send(M.PAUSE_PROPOSE, Buffer.from([0]));
    await until(a, M.PAUSE_VOTE);
    a.send(M.ROLLBACK_ANSWER, Buffer.from([0])); // no
    const no = await until(b, M.PAUSE_RESULT);
    assert.equal(no.payload[0], ROLLBACK.DECLINED);
    a.socket.destroy();
    b.socket.destroy();
    c.socket.destroy();
  } finally {
    server.close();
  }
});

function fact(key, value) {
  return Buffer.concat([encodeText(key), Buffer.from([0]), encodeText(value), Buffer.from([0])]);
}

// the facts that come with a world download, as { key: value }
async function downloadFacts(c) {
  const facts = {};
  for (;;) {
    const msg = await c.next();
    if (msg.type === M.WORLD_DONE) return facts;
    if (msg.type === M.FACT) {
      const [key, value] = readStringsZ(msg.payload, 0, 2);
      facts[key] = value;
    }
  }
}

test('facts: kept by the server, passed on when they change, given with the world, rolled back with it', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  try {
    const a = await player(port, 'artem');
    const b = await player(port, 'друг');
    a.send(M.ACTOR_STATE, actorState('l01_escape', 0, 0, 0, 0));
    b.send(M.ACTOR_STATE, actorState('l01_escape', 1, 0, 0, 0));
    await until(a, M.PEER_STATE); // b's state reaches a in no fixed order with a's own replies
    await uploadSave(a, [Buffer.from('w1'), Buffer.from('l1')], 0, '', 'new', 'artem');
    await roundTrip(a);

    a.send(M.FACT, fact('info:esc_bandit_squad_dead', '1'));
    let got = await until(b, M.FACT);
    assert.deepEqual(readStringsZ(got.payload, 0, 2), ['info:esc_bandit_squad_dead', '1']);
    a.send(M.FACT, fact('info:esc_bandit_squad_dead', '1')); // no change: not passed on
    a.send(M.FACT, fact('rel:dolg:freedom', '-5000'));
    got = await until(b, M.FACT);
    assert.deepEqual(readStringsZ(got.payload, 0, 2), ['rel:dolg:freedom', '-5000']);
    await uploadSave(a, [Buffer.from('w2'), Buffer.from('l2')], 1); // revision 2 keeps both
    a.send(M.FACT, fact('tool:esc_mechanic:1', 'artem'));
    await until(b, M.FACT);
    b.send(M.FACT, fact('tool:esc_mechanic:1', 'друг')); // too late: the first one stays
    b.send(M.PING, Buffer.alloc(4));
    await until(b, M.PONG);
    assert.equal(server.coop.facts()['tool:esc_mechanic:1'], 'artem');
    // a claim: the first stays, each claimer is told who has it
    a.send(M.FACT, fact('once:create_squad(lazarus_dolg_squad,bar_dolg_general)', 'artem'));
    got = await until(a, M.FACT);
    assert.deepEqual(readStringsZ(got.payload, 0, 2), ['once:create_squad(lazarus_dolg_squad,bar_dolg_general)', 'artem']);
    got = await until(b, M.FACT);
    assert.deepEqual(readStringsZ(got.payload, 0, 2), ['once:create_squad(lazarus_dolg_squad,bar_dolg_general)', 'artem']);
    b.send(M.FACT, fact('once:create_squad(lazarus_dolg_squad,bar_dolg_general)', 'друг'));
    got = await until(b, M.FACT);
    assert.deepEqual(readStringsZ(got.payload, 0, 2), ['once:create_squad(lazarus_dolg_squad,bar_dolg_general)', 'artem']);
    assert.equal(server.coop.facts()['once:create_squad(lazarus_dolg_squad,bar_dolg_general)'], 'artem');
    a.send(M.FACT, fact('once:create_squad(lazarus_dolg_squad,bar_dolg_general)', '')); // a claim stays
    got = await until(a, M.FACT);
    assert.deepEqual(readStringsZ(got.payload, 0, 2), ['once:create_squad(lazarus_dolg_squad,bar_dolg_general)', 'artem']);
    a.send(M.FACT, fact('tool:esc_mechanic:1', '')); // cleared, as any fact can be
    a.send(M.PING, Buffer.alloc(4));
    await until(a, M.PONG);
    await until(b, M.FACT); // b learns it is gone

    b.send(M.FACT, fact('rel:dolg:freedom', '0'));
    b.send(M.FACT, fact('info:esc_bandit_squad_dead', '')); // gone
    await roundTrip(b);
    assert.deepEqual(server.coop.facts(), { 'rel:dolg:freedom': '0',
      'once:create_squad(lazarus_dolg_squad,bar_dolg_general)': 'artem' });

    const c = await player(port, 'третий');
    c.send(M.WORLD_REQUEST);
    assert.deepEqual(await downloadFacts(c), { 'rel:dolg:freedom': '0',
      'once:create_squad(lazarus_dolg_squad,bar_dolg_general)': 'artem' });

    assert.equal(server.coop.rollback(2), 0); // the world as it is: refused
    await uploadSave(a, [Buffer.from('w3'), Buffer.from('l3')], 2);
    a.send(M.PING, Buffer.alloc(4));
    await until(a, M.PONG);
    assert.ok(server.coop.rollback(2));
    assert.deepEqual(server.coop.facts(), { 'info:esc_bandit_squad_dead': '1', 'rel:dolg:freedom': '-5000' });
    a.socket.destroy();
    b.socket.destroy();
    c.socket.destroy();
  } finally {
    server.close();
  }
});

function timeSet(kind, ...values) {
  const parts = [Buffer.from([kind])];
  for (const [type, v] of values) {
    const b = Buffer.alloc(type === 'u64' ? 8 : 4);
    if (type === 'u64') b.writeBigUInt64LE(BigInt(v));
    else if (type === 'f32') b.writeFloatLE(v);
    else b.writeUInt32LE(v);
    parts.push(b);
  }
  return Buffer.concat(parts);
}

test('clock: set by the first game in the world, runs only while someone is in it and not paused, jumps, factor from the master', async () => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'coop-test-'));
  let server = await startServer(options(dataDir));
  let { port } = server.address();
  try {
    const a = await player(port, 'artem');
    await settle(a);
    assert.equal(a.time.at(-1).set, false); // told after WELCOME: no clock yet

    // not in the world: not taken
    a.send(M.TIME_SET, timeSet(0, ['u64', 7_000_000], ['f32', 6]));
    await settle(a);
    assert.equal(a.time.at(-1).set, false);

    a.send(M.ACTOR_STATE, actorState('l01_escape', 0, 0, 0, 0));
    a.send(M.TIME_SET, timeSet(0, ['u64', 7_000_000], ['f32', 6]));
    await settle(a);
    let t = a.time.at(-1);
    assert.equal(t.set, true);
    assert.equal(t.running, true);
    assert.equal(t.factor, 6);
    assert.ok(t.game >= 7_000_000 && t.game < 7_000_000 + 6 * 1000);

    const b = await player(port, 'друг');
    await settle(b);
    assert.equal(b.time.at(-1).set, true);
    b.send(M.ACTOR_STATE, actorState('l01_escape', 1, 0, 0, 0));
    b.send(M.TIME_SET, timeSet(0, ['u64', 1], ['f32', 6])); // too late: the clock stays
    b.send(M.TIME_SET, timeSet(2, ['f32', 10]));            // not the master: no
    await settle(b);
    assert.ok(b.time.at(-1).game >= 7_000_000);
    assert.equal(b.time.at(-1).factor, 6);

    a.send(M.TIME_SET, timeSet(2, ['f32', 10]));
    b.send(M.TIME_SET, timeSet(1, ['u32', 8 * 3600_000]));
    await settle(a);
    await settle(b);
    t = b.time.at(-1);
    assert.equal(t.factor, 10);
    assert.equal(t.epoch, 2);
    assert.ok(t.game >= 7_000_000 + 8 * 3600_000);

    // a pause stops it; both leaving stops it too
    a.send(M.PAUSE_PROPOSE, Buffer.from([1]));
    await until(b, M.PAUSE_VOTE);
    b.send(M.ROLLBACK_ANSWER, Buffer.from([1]));
    await until(a, M.PAUSED);
    await settle(a);
    assert.equal(a.time.at(-1).running, false);
    const paused = a.time.at(-1).game;
    await new Promise((r) => setTimeout(r, 50));
    a.send(M.PAUSE_PROPOSE, Buffer.from([0]));
    await until(b, M.PAUSE_VOTE);
    b.send(M.ROLLBACK_ANSWER, Buffer.from([1]));
    await until(a, M.PAUSED);
    await settle(a);
    assert.equal(a.time.at(-1).running, true);
    assert.ok(a.time.at(-1).game - paused < 50 * 10); // the paused time didn't count

    a.send(M.LEFT_WORLD);
    b.socket.destroy();
    await settle(a);
    assert.equal(a.time.at(-1).running, false);
    const left = a.time.at(-1).game;
    a.socket.destroy();
    server.close();

    // kept over a restart, standing where it was
    server = await startServer(options(dataDir));
    port = server.address().port;
    const c = await player(port, 'artem');
    await settle(c);
    assert.equal(c.time.at(-1).game, left);
    assert.equal(c.time.at(-1).running, false);
    c.socket.destroy();
  } finally {
    server.close();
  }
});

test('clock: each save keeps the game time, a rollback takes the clock back to it', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  try {
    const a = await player(port, 'artem');
    a.send(M.ACTOR_STATE, actorState('l01_escape', 0, 0, 0, 0));
    a.send(M.TIME_SET, timeSet(0, ['u64', 7_000_000], ['f32', 6]));
    await uploadSave(a, [Buffer.from('w1'), Buffer.from('l1')], 0, '', 'new', 'artem');
    await settle(a);
    a.send(M.TIME_SET, timeSet(1, ['u32', 3600_000]));
    await uploadSave(a, [Buffer.from('w2'), Buffer.from('l2')], 1);
    await settle(a);
    assert.ok(a.time.at(-1).game >= 7_000_000 + 3600_000);

    assert.ok(server.coop.rollback(1)); // the admin's
    await until(a, M.WORLD_RELOAD);
    await settle(a);
    const t = a.time.at(-1);
    assert.ok(t.game >= 7_000_000 && t.game < 7_000_000 + 3600_000);
    assert.equal(t.epoch, 3);
    a.socket.destroy();
  } finally {
    server.close();
  }
});

test('with a builds file only listed builds get in, dev ones by the flag', async () => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'coop-test-'));
  const file = path.join(dataDir, 'builds.json');
  fs.writeFileSync(file, JSON.stringify({ builds: [{ id: '0123456789abcdef', release: '2026.11.06-1', channel: 'stable' }] }));
  const tryJoin = async (server, name, build) => {
    const c = await connect(server.address().port);
    c.send(M.HELLO, hello(name, PROTOCOL_VERSION, build));
    const msg = await c.next();
    c.socket.destroy();
    return msg;
  };
  for (const allowDev of [false, true]) {
    const server = await startServer({ ...options(), builds: { file, allowDev } });
    try {
      assert.equal((await tryJoin(server, 'friend', '0123456789ABCDEF')).type, M.WELCOME);
      const old = await tryJoin(server, 'old', 'ffffffffffffffff');
      assert.equal(old.type, M.REFUSED);
      assert.equal(old.payload[0], REFUSED.BUILD);
      assert.equal((await tryJoin(server, 'artem', 'dev')).type, allowDev ? M.WELCOME : M.REFUSED);
    } finally {
      server.close();
    }
  }
  // a file that is not there lets everyone in (a broken publish must not lock players out)
  const server = await startServer({ ...options(), builds: { file: path.join(dataDir, 'none.json'), allowDev: false } });
  try {
    assert.equal((await tryJoin(server, 'friend', 'ffffffffffffffff')).type, M.WELCOME);
  } finally {
    server.close();
  }
});

test('exit saves: made by the server from the host\'s things as a player leaves, chosen on the way back in; a lone death goes back to the newest own save; things taken since go back', async () => {
  const server = await startServer({ ...options(), hostSecret: 'f00d' });
  const { port } = server.address();
  try {
    const h = await connect(port);
    h.send(M.HELLO, hostHello('host', 'f00d'));
    await h.next();
    h.send(M.ACTOR_STATE, actorState('fake_start', 0, 0, 0, 0));
    await uploadSave(h, [Buffer.from('w1'), Buffer.from('l1')], 0, '', 'new', 'host');
    await settle(h);

    let a = await player(port, 'artem');
    a.send(M.ACTOR_STATE, actorState('l01_escape', 5, 1, 7, 0));
    a.send(M.CHARACTER, Buffer.from('record 1'));
    await settle(a);
    a.send(M.SAVE_REQUEST, Buffer.from([0]));
    const id1 = (await until(a, M.SNAPSHOT_REQUEST)).payload.readUInt32LE(0);
    sendSnapshot(a, id1, snapshot('record 1', 'progress 1', 'things 1'));
    await settle(a);
    // the host keeps the bodies and boxes near where the player saved
    const near = await until(h, M.SCRIPT_EVENT);
    assert.deepEqual(readStringsZ(near.payload, 4, 2), ['coop_protect', 'l01_escape\t5.00\t1.00\t7.00\tartem']);

    // taken since the save: comes back with it
    a.send(M.TAKEN, Buffer.from('taken after'));
    a.send(M.CHARACTER, Buffer.from('record 2'));
    await settle(a);

    // gone without saving: the host is asked for the things in their shadow, the exit save is made with them
    a.socket.destroy();
    const ask = await until(h, M.EXIT_THINGS_REQUEST);
    const exitId = ask.payload.readUInt32LE(0);
    assert.equal(readStringZ(ask.payload, 4), 'artem');
    const things = Buffer.from('shadow things');
    h.send(M.EXIT_THINGS, Buffer.concat([u32le(exitId), u32le(things.length), u32le(0), things]));
    await settle(h);

    // back: a choice between the exit save and the own one, newest first
    a = await connect(port);
    a.send(M.HELLO, hello('artem'));
    await a.next();
    assert.equal((await until(a, M.CHARACTER)).payload.toString(), 'record 2');
    const choice = await until(a, M.SAVE_CHOICE);
    assert.deepEqual(charSaves(choice.payload).map((s) => [s.id, s.name, s.reason]),
      [[exitId, 'выход', 'exit'], [id1, '', 'quick']]);
    a.send(M.LOAD_REQUEST, u32le(exitId));
    assert.equal((await until(a, M.CHARACTER)).payload.toString(), 'record 2');
    assert.equal((await until(a, M.LOAD_RESULT)).payload[0], LOAD.DONE);
    assert.deepEqual((await download(a)).things, Buffer.concat([things, Buffer.alloc(2)]));

    // died alone: the newest own save, never the exit one; what was taken since it comes after its things
    a.send(M.ACTOR_STATE, actorState('l01_escape', 5, 1, 7, 0));
    await settle(a);
    a.send(M.LOAD_REQUEST, u32le(0));
    assert.equal((await until(a, M.CHARACTER)).payload.toString(), 'record 1');
    const back = await until(a, M.LOAD_RESULT);
    assert.equal(back.payload[0], LOAD.DONE);
    assert.equal(back.payload.readUInt32LE(1), 0);
    const taken = Buffer.from('taken after');
    assert.deepEqual((await download(a)).things,
      Buffer.concat([Buffer.from('things 1'), Buffer.from([1, 0, taken.length, 0]), taken]));

    // one exit save per character
    a.send(M.LEFT_WORLD);
    const again = (await until(h, M.EXIT_THINGS_REQUEST)).payload.readUInt32LE(0);
    h.send(M.EXIT_THINGS, Buffer.concat([u32le(again), u32le(2), u32le(0), Buffer.alloc(2)]));
    await settle(h);
    a.send(M.SAVES_REQUEST);
    assert.deepEqual(charSaves((await until(a, M.SAVES)).payload).map((s) => s.id), [again, id1]);
    a.socket.destroy();
    h.socket.destroy();
  } finally {
    server.close();
  }
});

test('exit saves without a host: the record and progress only; a lone death with no save of their own says so', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  try {
    let a = await player(port, 'artem');
    a.send(M.ACTOR_STATE, actorState('l01_escape', 0, 0, 0, 0));
    await uploadSave(a, [Buffer.from('w1'), Buffer.from('l1')], 0, '', 'new', 'artem');
    await settle(a);
    a.send(M.LOAD_REQUEST, u32le(0));
    assert.equal((await until(a, M.LOAD_RESULT)).payload[0], LOAD.NO_SAVE);
    a.send(M.CHARACTER, Buffer.from('record'));
    await settle(a);
    a.send(M.LEFT_WORLD);
    await settle(a);
    a.send(M.SAVES_REQUEST);
    const [exit] = charSaves((await until(a, M.SAVES)).payload);
    assert.equal(exit.reason, 'exit');
    a.socket.destroy();
    // only an exit save: nothing to choose
    a = await connect(port);
    a.send(M.HELLO, hello('artem'));
    await a.next();
    assert.ok(!(await drain(a)).includes(M.SAVE_CHOICE));
    a.socket.destroy();
  } finally {
    server.close();
  }
});

test('autosaves: the character\'s own even in a group, one per character, listed as auto; a lone death and the way back in count it', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  const action = (kind, id) => Buffer.concat([Buffer.from([kind]), u32le(id), Buffer.from([0])]);
  const auto = Buffer.concat([encodeText('авто'), Buffer.from([0])]);
  try {
    const a = await player(port, 'artem');
    let b = await player(port, 'друг');
    const idA = a.roles.at(-1) ?? 1;
    a.send(M.ACTOR_STATE, actorState('l01_escape', 0, 0, 0, 0));
    b.send(M.ACTOR_STATE, actorState('l01_escape', 1, 0, 0, 0));
    await uploadSave(a, [Buffer.from('w1'), Buffer.from('l1')], 0, '', 'new', 'artem');
    await settle(a);
    await settle(b);
    // b in a's group: a group's member saves nothing by hand, but autosaves alone; a isn't asked, nothing is kept
    a.send(M.GROUP, action(GROUP.INVITE, 2));
    await until(b, M.GROUP_INVITE);
    b.send(M.GROUP, action(GROUP.ACCEPT, idA));
    await settle(b);
    b.send(M.SAVE_REQUEST, auto);
    const auto1 = (await until(b, M.SNAPSHOT_REQUEST)).payload.readUInt32LE(0);
    sendSnapshot(b, auto1, snapshot('record auto 1', '', 'things auto 1'));
    await settle(b);
    const seenA = await drain(a);
    assert.ok(!seenA.includes(M.SNAPSHOT_REQUEST) && !seenA.includes(M.SCRIPT_EVENT));
    b.send(M.SAVES_REQUEST);
    assert.deepEqual(charSaves((await until(b, M.SAVES)).payload), [{ id: auto1, name: 'авто', reason: 'auto', who: 'друг' }]);

    // the leader's group save goes on as before, the autosave stays
    a.send(M.SAVE_REQUEST, Buffer.from([0]));
    const group = (await until(a, M.SNAPSHOT_REQUEST)).payload.readUInt32LE(0);
    assert.equal((await until(b, M.SNAPSHOT_REQUEST)).payload.readUInt32LE(0), group);
    sendSnapshot(a, group, snapshot('record a', '', 'things a'));
    sendSnapshot(b, group, snapshot('record group', '', 'things group'));
    await settle(a);
    await settle(b);
    // a lone death: the newest, the group's part now
    b.send(M.LOAD_REQUEST, u32le(0));
    assert.equal((await until(b, M.CHARACTER)).payload.toString(), 'record group');
    assert.equal((await until(b, M.LOAD_RESULT)).payload[0], LOAD.DONE);

    // a new autosave takes the old one's place; the group's save stays
    b.send(M.SAVE_REQUEST, auto);
    const auto2 = (await until(b, M.SNAPSHOT_REQUEST)).payload.readUInt32LE(0);
    sendSnapshot(b, auto2, snapshot('record auto 2', '', 'things auto 2'));
    await settle(b);
    b.send(M.SAVES_REQUEST);
    assert.deepEqual(charSaves((await until(b, M.SAVES)).payload).map((s) => [s.id, s.reason]), [[auto2, 'auto'], [group, 'group']]);
    a.send(M.SAVES_REQUEST);
    assert.deepEqual(charSaves((await until(a, M.SAVES)).payload).map((s) => [s.id, s.reason]), [[group, 'group']]);
    // a lone death: the autosave, newer now
    b.send(M.LOAD_REQUEST, u32le(0));
    assert.equal((await until(b, M.CHARACTER)).payload.toString(), 'record auto 2');

    // gone: the exit save; back in, a choice of the exit save, the autosave and the group's, newest first
    b.socket.destroy();
    await settle(a);
    b = await connect(port);
    b.send(M.HELLO, hello('друг'));
    await b.next();
    const choice = await until(b, M.SAVE_CHOICE);
    const listed = charSaves(choice.payload).map((s) => s.reason);
    assert.deepEqual(listed, ['exit', 'auto', 'group']);
    b.socket.destroy();
    a.socket.destroy();
  } finally {
    server.close();
  }
});

// the admin window's helpers: a logged-in admin, a script event's [sender, name, fields]
const adminText = (msg) => readStringZ(msg.payload, 0);
const adminLine = (str) => Buffer.concat([encodeText(str), Buffer.from([0])]);
async function adminState(c) {
  return adminText(await until(c, M.ADMIN_STATE)).split('\n').map((l) => l.split('\t'));
}
function scriptEvent(msg) {
  const [name, payload] = readStringsZ(msg.payload, 4, 2);
  return { sender: msg.payload.readUInt32LE(0), name, fields: payload.split('\t') };
}
async function untilEvent(c, name) {
  for (;;) {
    const e = scriptEvent(await until(c, M.SCRIPT_EVENT));
    if (e.name === name) return e;
  }
}

test('the admin window: commands on a player go to their game as the server\'s own event, and into the journal', async () => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'coop-test-'));
  const server = await startServer({ ...options(dataDir), adminPassword: 'секрет' });
  const { port } = server.address();
  try {
    const a = await player(port, 'artem');
    const b = await player(port, 'друг');
    a.send(M.ACTOR_STATE, actorState('l01_escape', 1, 2, 3, 0));
    b.send(M.ACTOR_STATE, actorState('l01_escape', 10, 20, 30, 0));
    await settle(a);
    await settle(b);
    a.send(M.ADMIN_LOGIN, adminLine('секрет'));
    await until(a, M.ADMIN_STATE);
    // asked for its report: the game answers the server alone, never the other players
    assert.deepEqual(await untilEvent(b, 'coop_admin'), { sender: 0, name: 'coop_admin', fields: ['report', 'server'] });
    b.send(M.SCRIPT_EVENT, event('coop_admin_info', '87\t1200\t0\t5000\t77\t12'));
    await settle(b);
    // a game can't send the server's own event to another
    b.send(M.SCRIPT_EVENT, event('coop_admin', 'god\t1\tдруг'));
    await settle(b);
    a.send(M.ADMIN_COMMAND, adminLine('state'));
    const state = await adminState(a);
    const card = state.find((l) => l[0] === 'player' && l[1] === 'друг');
    assert.deepEqual(card.slice(9, 16), ['87', '1200', '0', '5000', '10.0', '20.0', '30.0']);
    assert.ok(!(await drain(a)).includes(M.SCRIPT_EVENT));

    a.send(M.ADMIN_COMMAND, adminLine('give\tдруг\twpn_pm\t3'));
    assert.match(adminText(await until(a, M.ADMIN_RESULT)), /wpn_pm x 3/);
    assert.deepEqual((await untilEvent(b, 'coop_admin')).fields, ['give', 'wpn_pm', '3', 'artem']);
    a.send(M.ADMIN_COMMAND, adminLine('give\tдруг\tbad section\t3'));
    assert.match(adminText(await until(a, M.ADMIN_RESULT)), /Как: give/);
    a.send(M.ADMIN_COMMAND, adminLine('money\tдруг\t-500'));
    assert.match(adminText(await until(a, M.ADMIN_RESULT)), /забрано 500/);
    assert.deepEqual((await untilEvent(b, 'coop_admin')).fields, ['money', '-500', 'artem']);
    a.send(M.ADMIN_COMMAND, adminLine('god\tдруг\ton'));
    assert.match(adminText(await until(a, M.ADMIN_RESULT)), /бессмертие включено/);
    assert.deepEqual((await untilEvent(b, 'coop_admin')).fields, ['god', '1', 'artem']);
    a.send(M.ADMIN_COMMAND, adminLine('heal\tдруг'));
    assert.deepEqual((await untilEvent(b, 'coop_admin')).fields, ['heal', 'artem']);
    await until(a, M.ADMIN_RESULT);
    // to him: the admin's own game moves (the same level: no vertices); him to me: his
    a.send(M.ADMIN_COMMAND, adminLine('goto\tдруг'));
    assert.deepEqual((await untilEvent(a, 'coop_admin')).fields, ['teleport', 'l01_escape', '10.00', '20.00', '30.00', '', '', 'artem']);
    await until(a, M.ADMIN_RESULT);
    a.send(M.ADMIN_COMMAND, adminLine('bring\tдруг'));
    assert.deepEqual((await untilEvent(b, 'coop_admin')).fields, ['teleport', 'l01_escape', '1.00', '2.00', '3.00', '', '', 'artem']);
    await until(a, M.ADMIN_RESULT);
    // another level: the target's vertices from its report, unknown yet for the admin
    b.send(M.ACTOR_STATE, actorState('l02_garbage', 5, 6, 7, 0));
    await settle(b);
    a.send(M.ADMIN_COMMAND, adminLine('goto\tдруг'));
    assert.deepEqual((await untilEvent(a, 'coop_admin')).fields, ['teleport', 'l02_garbage', '5.00', '6.00', '7.00', '77', '12', 'artem']);
    await until(a, M.ADMIN_RESULT);
    a.send(M.ADMIN_COMMAND, adminLine('bring\tдруг'));
    assert.match(adminText(await until(a, M.ADMIN_RESULT)), /повторите/);
    a.send(M.ADMIN_COMMAND, adminLine('say\tвсем привет'));
    assert.match(adminText(await until(a, M.ADMIN_RESULT)), /Отправлено 2/);
    assert.deepEqual((await untilEvent(b, 'coop_admin')).fields, ['say', 'всем привет', 'artem']);
    // cheats on oneself and the test modes: a test server's only
    a.send(M.ADMIN_COMMAND, adminLine('god\tartem\ton'));
    assert.match(adminText(await until(a, M.ADMIN_RESULT)), /только на тестовом сервере/);
    a.send(M.ADMIN_COMMAND, adminLine('test\tbase_cooling'));
    assert.match(adminText(await until(a, M.ADMIN_RESULT)), /только на тестовом сервере/);
    a.send(M.ADMIN_COMMAND, adminLine('give\tникто\twpn_pm\t1'));
    assert.match(adminText(await until(a, M.ADMIN_RESULT)), /нет в мире/);

    a.send(M.ADMIN_COMMAND, adminLine('state'));
    const journal = (await adminState(a)).filter((l) => l[0] === 'journal');
    assert.equal(journal.length, 8); // the newest
    assert.ok(journal.every((l) => l[2] === 'artem'));
    assert.match(journal.at(-1)[3], /^give никто wpn_pm 1 - /);
    const kept = fs.readFileSync(path.join(dataDir, 'admin_log.jsonl'), 'utf8');
    assert.ok(kept.split('\n').filter(Boolean).length >= 10);
    a.socket.destroy();
    b.socket.destroy();
  } finally {
    server.close();
  }
});

test('the admin window on a test server: cheats on oneself, the test modes; the games know it is one', async () => {
  const server = await startServer({ ...options(), adminPassword: 'секрет', allowTests: true });
  const { port } = server.address();
  try {
    const a = await player(port, 'artem');
    assert.match(a.settings.at(-1) ?? (await settle(a), a.settings.at(-1)), /^tests=1$/m);
    a.send(M.ACTOR_STATE, actorState('l01_escape', 1, 2, 3, 0));
    a.send(M.ADMIN_LOGIN, adminLine('секрет'));
    const state = await adminState(a);
    assert.equal(state.find((l) => l[0] === 'server')[1], '1');
    a.send(M.ADMIN_COMMAND, adminLine('god\tartem\ton'));
    assert.deepEqual((await untilEvent(a, 'coop_admin')).fields, ['god', '1', 'artem']);
    a.send(M.ADMIN_COMMAND, adminLine('test\tbase_cooling'));
    assert.deepEqual((await untilEvent(a, 'coop_admin')).fields, ['test', 'base_cooling', 'artem']);
    await until(a, M.ADMIN_RESULT);
    a.send(M.ADMIN_COMMAND, adminLine('test\tbad action!'));
    assert.match(adminText(await until(a, M.ADMIN_RESULT)), /Нет такого тест-действия/);
    a.socket.destroy();
  } finally {
    server.close();
  }
});

test('the admin window: saves a page at a time; the pause lifted; autosaves of an empty world kept one', async () => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'coop-test-'));
  const server = await startServer({ ...options(dataDir), adminPassword: 'секрет' });
  const { port } = server.address();
  try {
    const a = await player(port, 'artem');
    await uploadSave(a, [Buffer.from('w'), Buffer.from('l')], 0, '', 'new', 'artem');
    // nobody in the world: a run of autosaves leaves only its newest
    for (let i = 0; i < 3; i++) {
      await uploadSave(a, [Buffer.from('w'), Buffer.from('l')], i + 1);
      a.send(M.PING, Buffer.alloc(4));
      await until(a, M.PONG);
    }
    assert.deepEqual(server.coop.status().saves.map((m) => [m.revision, m.reason]), [[4, 'auto'], [1, 'new']]);
    assert.ok(!fs.existsSync(path.join(dataDir, 'saves', '2')));
    // in the world: each kept
    a.send(M.ACTOR_STATE, actorState('l01_escape', 0, 0, 0, 0));
    for (let i = 0; i < 12; i++) {
      await uploadSave(a, [Buffer.from('w'), Buffer.from('l')], i + 4);
      a.send(M.PING, Buffer.alloc(4));
      await until(a, M.PONG);
    }
    a.send(M.ADMIN_LOGIN, adminLine('секрет'));
    let state = await adminState(a);
    assert.deepEqual(state.find((l) => l[0] === 'saves'), ['saves', '14', '0']);
    assert.equal(state.filter((l) => l[0] === 'save').length, 10);
    a.send(M.ADMIN_COMMAND, adminLine('saves\t10'));
    state = await adminState(a);
    assert.deepEqual(state.filter((l) => l[0] === 'save').map((l) => l[1]), ['6', '5', '4', '1']);
    a.send(M.ADMIN_COMMAND, adminLine('resume'));
    assert.match(adminText(await until(a, M.ADMIN_RESULT)), /не на паузе/);
    a.socket.destroy();
  } finally {
    server.close();
  }
});

test('the admin window: the world\'s events go to the sim master (a stop of a storm and the weather to every game); its report in the state and the journal', async () => {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'coop-test-'));
  const server = await startServer({ ...options(dataDir), adminPassword: 'секрет' });
  const { port } = server.address();
  try {
    const a = await player(port, 'artem');
    const b = await player(port, 'друг');
    // nobody in the world: nobody to start it
    assert.match(server.coop.worldEvent('psi', 'start', 'бот'), /никто не держит/);
    a.send(M.ACTOR_STATE, actorState('l01_escape', 1, 2, 3, 0));
    b.send(M.ACTOR_STATE, actorState('l01_escape', 10, 20, 30, 0));
    await settle(a);
    await settle(b);
    // the master (artem, in first) is asked for its report with the others' reports, as the window logs in
    a.send(M.ADMIN_LOGIN, adminLine('секрет'));
    assert.deepEqual((await untilEvent(a, 'coop_admin')).fields, ['report', 'server']);
    assert.deepEqual((await untilEvent(a, 'coop_admin')).fields, ['events_report', 'server']);
    assert.deepEqual((await untilEvent(b, 'coop_admin')).fields, ['report', 'server']);
    await until(a, M.ADMIN_STATE);

    a.send(M.ADMIN_COMMAND, adminLine('event\tsurge\tstart'));
    assert.deepEqual((await untilEvent(a, 'coop_admin')).fields, ['event', 'surge', 'start', 'artem']);
    assert.match(adminText(await until(a, M.ADMIN_RESULT)), /Выброс: запуск - отправлено мастеру симуляции \(artem\)/);
    assert.ok(!(await drain(b)).includes(M.SCRIPT_EVENT));
    // stopping a surge, the weather: every game in the world
    a.send(M.ADMIN_COMMAND, adminLine('event\tsurge\tstop'));
    assert.deepEqual((await untilEvent(a, 'coop_admin')).fields, ['event', 'surge', 'stop', 'artem']);
    assert.deepEqual((await untilEvent(b, 'coop_admin')).fields, ['event', 'surge', 'stop', 'artem']);
    assert.match(server.coop.worldEvent('weather_rain', 'start', 'бот'), /Погода: дождь: запуск/);
    assert.deepEqual((await untilEvent(a, 'coop_admin')).fields, ['event', 'weather_rain', 'start', 'бот']);
    assert.deepEqual((await untilEvent(b, 'coop_admin')).fields, ['event', 'weather_rain', 'start', 'бот']);
    // what can't be
    a.send(M.ADMIN_COMMAND, adminLine('event\tbar_gift\tstop'));
    assert.match(adminText(await until(a, M.ADMIN_RESULT)), /остановить нельзя/);
    a.send(M.ADMIN_COMMAND, adminLine('event\tnope\tstart'));
    assert.match(adminText(await until(a, M.ADMIN_RESULT)), /Нет такого события: nope/);
    a.send(M.ADMIN_COMMAND, adminLine('event\tpsi\tnow'));
    assert.match(adminText(await until(a, M.ADMIN_RESULT)), /start\|stop/);

    // the master's report: in the window's state, what it did in the journal; another game's is not heard
    b.send(M.SCRIPT_EVENT, event('coop_admin_events', 'surge=0\tresult=не мастер'));
    await settle(b);
    a.send(M.SCRIPT_EVENT, event('coop_admin_events', 'surge=1\tsurge_in=-3\tpsi=0\tpsi_in=7200\tfactor=10\tweather=rain\tresult=Выброс начнётся через 15 с.'));
    await settle(a);
    assert.ok(!(await drain(b)).includes(M.SCRIPT_EVENT)); // not relayed
    a.send(M.ADMIN_COMMAND, adminLine('state'));
    const state = await adminState(a);
    assert.deepEqual(state.find((l) => l[0] === 'events').slice(2), ['artem']);
    assert.deepEqual(state.filter((l) => l[0] === 'ev').map((l) => l.slice(1)),
      [['surge', '1'], ['surge_in', '-3'], ['psi', '0'], ['psi_in', '7200'], ['factor', '10'], ['weather', 'rain']]);
    assert.equal(state.find((l) => l[0] === 'event_result')[2], 'Выброс начнётся через 15 с.');
    const ev = server.coop.events();
    assert.equal(ev.values.surge, '1');
    assert.equal(ev.result.text, 'Выброс начнётся через 15 с.');
    const kept = fs.readFileSync(path.join(dataDir, 'admin_log.jsonl'), 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
    assert.ok(kept.some((e) => e.who === 'artem' && e.text === 'Выброс начнётся через 15 с.'));
    assert.ok(kept.some((e) => e.who === 'бот' && /^event weather_rain start - /.test(e.text)));
    assert.ok(!kept.some((e) => e.text === 'не мастер'));
    a.socket.destroy();
    b.socket.destroy();
  } finally {
    server.close();
  }
});
