import { test } from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';
import { startServer } from '../src/server.js';
import { M, PROTOCOL_VERSION, encode, createDecoder } from '../src/protocol.js';

// Minimal client speaking the same wire format as the engine.
function connect(port) {
  const socket = net.connect(port, '127.0.0.1');
  const queue = [];
  const waiters = [];
  socket.on('data', createDecoder((type, payload) => {
    const msg = { type, payload: Buffer.from(payload) };
    const w = waiters.shift();
    w ? w(msg) : queue.push(msg);
  }));
  const next = () => new Promise((r) => (queue.length ? r(queue.shift()) : waiters.push(r)));
  const send = (type, payload) => socket.write(encode(type, payload));
  return new Promise((r) => socket.on('connect', () => r({ socket, next, send })));
}

function hello(name, version = PROTOCOL_VERSION) {
  const p = Buffer.alloc(2 + Buffer.byteLength(name) + 1);
  p.writeUInt16LE(version, 0);
  p.write(name, 2);
  return p;
}

test('hello -> welcome with unique ids, ping -> pong echoes time', async () => {
  const server = await startServer({ port: 0, host: '127.0.0.1', log: () => {} });
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
  const server = await startServer({ port: 0, host: '127.0.0.1', log: () => {} });
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

test('wrong protocol version is dropped', async () => {
  const server = await startServer({ port: 0, host: '127.0.0.1', log: () => {} });
  try {
    const c = await connect(server.address().port);
    const closed = new Promise((r) => c.socket.on('close', r));
    c.send(M.HELLO, hello('old', PROTOCOL_VERSION + 1));
    await closed;
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
  const name = payload.toString('utf8', 4, nameEnd);
  const levelEnd = payload.indexOf(0, nameEnd + 1);
  const level = payload.toString('utf8', nameEnd + 1, levelEnd);
  const f = (i) => payload.readFloatLE(levelEnd + 1 + i * 4);
  return { id, name, level, x: f(0), y: f(1), z: f(2), yaw: f(3) };
}

test('actor state is relayed to others, replayed to newcomers, and leave is announced', async () => {
  const server = await startServer({ port: 0, host: '127.0.0.1', log: () => {} });
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
  const server = await startServer({ port: 0, host: '127.0.0.1', log: () => {} });
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
  const server = await startServer({ port: 0, host: '127.0.0.1', log: () => {} });
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
  const server = await startServer({ port: 0, host: '127.0.0.1', log: () => {} });
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

test('item and release events reach others prefixed with the sender id', async () => {
  const server = await startServer({ port: 0, host: '127.0.0.1', log: () => {} });
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

    a.socket.destroy();
    b.socket.destroy();
  } finally {
    server.close();
  }
});
