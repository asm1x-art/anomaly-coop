import { test } from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';
import { startServer } from '../src/server.js';
import { M, REFUSED, ROLLBACK, GROUP, GROUP_NOTE, PROTOCOL_VERSION, encode, createDecoder, encodeText, readStringZ, readStringsZ } from '../src/protocol.js';
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
  const client = { socket, roles: [], worldInfo: [], settings: [], groups: [] };
  socket.on('data', createDecoder((type, payload) => {
    const msg = { type, payload: Buffer.from(payload) };
    if (type === M.ROLES) return client.roles.push(msg.payload.readUInt32LE(0));
    if (type === M.WORLD_INFO) return client.worldInfo.push(msg.payload);
    if (type === M.SETTINGS) return client.settings.push(readStringZ(msg.payload, 0));
    if (type === M.GROUPS) return client.groups.push(msg.payload);
    const w = waiters.shift();
    w ? w(msg) : queue.push(msg);
  }));
  client.next = () => new Promise((r) => (queue.length ? r(queue.shift()) : waiters.push(r)));
  client.send = (type, payload) => socket.write(encode(type, payload));
  return new Promise((r) => socket.on('connect', () => r(client)));
}

function hello(name, version = PROTOCOL_VERSION) {
  const p = Buffer.alloc(2);
  p.writeUInt16LE(version, 0);
  return Buffer.concat([p, encodeText(name), Buffer.from([0])]);
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

    server.coop.saveSettings({ world: { warfare: true }, factions: ['monolith'] });
    await new Promise((r) => setTimeout(r, 20));
    assert.match(a.settings[1], /^warfare=1$/m);
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

test('groups: invite, accept, leader kicks, leaving dissolves a group of two', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  const wait = () => new Promise((r) => setTimeout(r, 30));
  const names = (payload) => {
    const out = [];
    let at = 1;
    for (let g = 0; g < payload[0]; g++) {
      const members = [];
      for (let n = payload[at++]; n > 0; n--) {
        const name = readStringZ(payload, at);
        members.push(name);
        at = payload.indexOf(0, at) + 1;
      }
      out.push(members);
    }
    return out;
  };
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

    // only the leader puts one out
    b.send(M.GROUP, Buffer.concat([Buffer.from([GROUP.KICK]), encodeText('third'), Buffer.from([0])]));
    a.send(M.GROUP, Buffer.concat([Buffer.from([GROUP.KICK]), encodeText('third'), Buffer.from([0])]));
    await wait();
    assert.deepEqual(names(a.groups.at(-1)), [['artem', 'друг']]);

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

test('saves: the master is whoever is in the world; it saves for players coming in, leaving and asking', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  try {
    const menu = await player(port, 'menu');       // lowest id, stays in the main menu
    const master = await player(port, 'master');
    await uploadSave(master, [Buffer.from('w1'), Buffer.from('l1')], 0, '', 'new', 'master');
    await roundTrip(master);
    master.send(M.ACTOR_STATE, actorState('l01_escape', 0, 0, 0, 0));
    await roundTrip(master);
    assert.equal(master.roles.at(-1), 2); // in the world: the master now, not the one in the menu

    // a player coming in: the master saves first, then the newcomer gets that world
    const joiner = await player(port, 'joiner');
    joiner.send(M.WORLD_REQUEST);
    assert.deepEqual(saveNow(await until(master, M.SAVE_NOW)), { name: '', reason: 'join', who: 'joiner' });
    await uploadSave(master, [Buffer.from('w2'), Buffer.from('l2')], 1, '', 'join', 'joiner');
    const done = await until(joiner, M.WORLD_DONE);
    assert.equal(done.payload.readUInt32LE(done.payload.indexOf(0) + 1), 2);

    // asked by name
    menu.send(M.SAVE_REQUEST, Buffer.from('Перед Баром\0', 'latin1').length ? Buffer.concat([encodeText('Перед Баром'), Buffer.from([0])]) : null);
    assert.deepEqual(saveNow(await until(master, M.SAVE_NOW)), { name: 'Перед Баром', reason: 'named', who: 'menu' });

    // a player in the world leaving
    joiner.send(M.ACTOR_STATE, actorState('l01_escape', 1, 0, 0, 0));
    await roundTrip(joiner);
    joiner.socket.destroy();
    assert.deepEqual(saveNow(await until(master, M.SAVE_NOW)), { name: '', reason: 'leave', who: 'joiner' });

    menu.send(M.SAVES_REQUEST);
    const saves = await until(menu, M.SAVES);
    assert.equal(saves.payload.readUInt16LE(0), 2);
    assert.equal(saves.payload.readUInt32LE(2), 2); // newest first
    assert.deepEqual(readStringsZ(saves.payload, 10, 3), ['', 'join', 'joiner']);
    menu.socket.destroy();
    master.socket.destroy();
  } finally {
    server.close();
  }
});

test('rollback: everyone must agree; then all reload, characters go back, old games may not upload', async () => {
  const server = await startServer(options());
  const { port } = server.address();
  try {
    const a = await player(port, 'artem');
    const b = await player(port, 'друг');
    a.send(M.ACTOR_STATE, actorState('l01_escape', 0, 0, 0, 0));
    b.send(M.ACTOR_STATE, actorState('l01_escape', 1, 0, 0, 0)); // b votes: in the world
    a.send(M.CHARACTER, Buffer.from('at the start'));
    await uploadSave(a, [Buffer.from('w1'), Buffer.from('l1')], 0, '', 'new', 'artem');
    a.send(M.CHARACTER, Buffer.from('much later'));
    await uploadSave(a, [Buffer.from('w2'), Buffer.from('l2')], 1);
    await roundTrip(a);

    // a no ends it
    a.send(M.ROLLBACK_PROPOSE, u32le(1));
    const ask = await until(b, M.ROLLBACK_VOTE);
    assert.equal(ask.payload.readUInt32LE(0), 1); // proposer id
    b.send(M.ROLLBACK_ANSWER, Buffer.from([0]));
    const no = await until(a, M.ROLLBACK_RESULT);
    assert.equal(no.payload[0], ROLLBACK.DECLINED);
    assert.equal(readStringZ(no.payload, 1), 'друг');

    // all yes: back to save 1 as save 3
    a.send(M.ROLLBACK_PROPOSE, u32le(1));
    await until(b, M.ROLLBACK_VOTE);
    b.send(M.ROLLBACK_ANSWER, Buffer.from([1]));
    await until(b, M.WORLD_RELOAD);
    const yes = await until(b, M.ROLLBACK_RESULT);
    assert.equal(yes.payload[0], ROLLBACK.ACCEPTED);
    assert.equal(yes.payload.readUInt32LE(yes.payload.indexOf(0, 1) + 1), 3);
    await roundTrip(b);
    assert.deepEqual(worldInfo(b.worldInfo.at(-1)), { has: true, owner: 'artem', revision: 3, creator: '' });
    await until(a, M.WORLD_RELOAD); // the one who asked reloads too
    await until(a, M.ROLLBACK_RESULT);

    // the master's game still runs revision 1's successor: its upload is turned down until it reloads
    await uploadSave(a, [Buffer.from('stale'), Buffer.from('x')], 1);
    await roundTrip(a);
    assert.equal(worldInfo(a.worldInfo.at(-1)).revision, 3);
    await uploadSave(a, [Buffer.from('w4'), Buffer.from('l4')], 3);
    await roundTrip(a);
    assert.equal(worldInfo(a.worldInfo.at(-1)).revision, 4);

    // characters went back with the world
    const c = await connect(port);
    c.send(M.HELLO, hello('artem'));
    await c.next();
    assert.equal((await c.next()).payload.toString(), 'at the start');
    a.socket.destroy();
    b.socket.destroy();
    c.socket.destroy();
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
    await uploadSave(a, [Buffer.from('w1'), Buffer.from('l1')], 0, '', 'new', 'artem');
    await roundTrip(a);

    // a save: everyone in the world is asked for their progress
    b.send(M.SAVE_REQUEST, Buffer.from([0]));
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

    // b comes back: its latest progress comes with the world, before WORLD_DONE
    b.socket.destroy();
    await until(a, M.SAVE_NOW); // b's leave save
    await uploadSave(a, [Buffer.from('w3'), Buffer.from('l3')], 2, '', 'leave', 'друг');
    await roundTrip(a);
    const b2 = await player(port, 'друг');
    b2.send(M.WORLD_REQUEST);
    await until(a, M.SAVE_NOW); // join save
    await uploadSave(a, [Buffer.from('w4'), Buffer.from('l4')], 3, '', 'join', 'друг');
    assert.deepEqual(await downloadProgress(b2), late);

    // a player without progress gets none
    const c = await player(port, 'третий');
    c.send(M.WORLD_REQUEST);
    await until(a, M.SAVE_NOW);
    await uploadSave(a, [Buffer.from('w5'), Buffer.from('l5')], 4, '', 'join', 'третий');
    assert.equal(await downloadProgress(c), null);

    // back to revision 2: the progress kept with it
    assert.ok(server.coop.rollback(2));
    await until(b2, M.WORLD_RELOAD);
    b2.send(M.WORLD_REQUEST);
    await until(a, M.SAVE_NOW);
    await uploadSave(a, [Buffer.from('w7'), Buffer.from('l7')], 6, '', 'join', 'друг');
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
