import { test } from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { startServer } from '../src/server.js';
import { M, REFUSED, PROTOCOL_VERSION, encode, createDecoder, encodeText } from '../src/protocol.js';

// Sessions that are dead but not closed: a game whose connection was lost without a word (its packets lost on the
// way) stays "online" for the server. Here such a session is a socket that is left open and says nothing more.

function start(extra = {}, settings = null) {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'coop-test-'));
  if (settings) fs.writeFileSync(path.join(dataDir, 'settings.json'), JSON.stringify(settings));
  const lines = [];
  return startServer({ port: 0, host: '127.0.0.1', dataDir, log: (line) => lines.push(line), ...extra })
    .then((server) => Object.assign(server, { lines }));
}

function connect(port) {
  const socket = net.connect(port, '127.0.0.1');
  const got = [];
  const waiters = [];
  const client = { socket, got, closed: new Promise((r) => socket.on('close', () => r(true))) };
  socket.on('error', () => {});
  socket.on('data', createDecoder((type, payload) => {
    got.push({ type, payload: Buffer.from(payload) });
    for (const w of waiters.splice(0)) w();
  }));
  // the first message of that type, from those that came and those to come
  client.wait = async (type) => {
    for (;;) {
      const at = got.findIndex((m) => m.type === type);
      if (at !== -1) return got.splice(at, 1)[0];
      await new Promise((r) => waiters.push(r));
    }
  };
  client.send = (type, payload) => socket.write(encode(type, payload));
  return new Promise((r) => socket.on('connect', () => r(client)));
}

function hello(name) {
  const p = Buffer.alloc(2);
  p.writeUInt16LE(PROTOCOL_VERSION, 0);
  return Buffer.concat([p, encodeText(name), Buffer.from([0]), encodeText('dev'), Buffer.from([0])]);
}

async function join(port, name) {
  const c = await connect(port);
  c.send(M.HELLO, hello(name));
  c.id = (await c.wait(M.WELCOME)).payload.readUInt32LE(0);
  return c;
}

const soon = (ms) => new Promise((r) => setTimeout(r, ms));
const online = (server) => server.coop.status().online.map((p) => p.name);

test('the same player from the same address again takes the place of the session they had', async () => {
  const server = await start({}, { rules: { max_players: 2 } });
  const { port } = server.address();
  try {
    const friend = await join(port, 'друг');
    const stale = await join(port, 'АРЕС'); // stays open and silent: the server has no way to know it is dead
    assert.deepEqual(online(server), ['друг', 'АРЕС']);

    // the server is full, and still the player gets in: their own old session is what holds the place
    const again = await join(port, 'АРЕС');
    assert.notEqual(again.id, stale.id);
    assert.deepEqual(online(server), ['друг', 'АРЕС']);
    assert.equal(server.coop.status().online.find((p) => p.name === 'АРЕС').id, again.id);
    // the others are told the old one left, the old connection is closed
    assert.equal((await friend.wait(M.PEER_LEFT)).payload.readUInt32LE(0), stale.id);
    assert.equal(await stale.closed, true);
    assert.ok(server.lines.some((l) => l.includes(`[${stale.id}] 'АРЕС' comes in again`)));
    assert.equal(server.lines.filter((l) => l.includes("'АРЕС' left")).length, 1);

    // the new session works, and leaving is told once
    again.send(M.PING, Buffer.alloc(8));
    await again.wait(M.PONG);
    again.socket.destroy();
    assert.equal((await friend.wait(M.PEER_LEFT)).payload.readUInt32LE(0), again.id);
    assert.deepEqual(online(server), ['друг']);
    friend.socket.destroy();
  } finally {
    server.close();
  }
});

test('three stale sessions of one player: the next start gets in, the server is not "full"', async () => {
  const server = await start({}, { rules: { max_players: 4 } });
  const { port } = server.address();
  try {
    const friend = await join(port, 'Чепух');
    // as on 2026-11-14: each start of the game left a session behind
    const first = await join(port, 'АРЕС');
    const second = await join(port, 'АРЕС');
    const third = await join(port, 'АРЕС');
    assert.deepEqual(online(server), ['Чепух', 'АРЕС']);
    assert.equal(await first.closed, true);
    assert.equal(await second.closed, true);
    assert.ok(!server.lines.some((l) => l.includes('turned away')));
    third.socket.destroy();
    friend.socket.destroy();
  } finally {
    server.close();
  }
});

test('a full server still refuses another player, and a refused one takes nobody\'s place', async () => {
  const server = await start({}, { rules: { max_players: 1 } });
  const { port } = server.address();
  try {
    const a = await join(port, 'АРЕС');
    const b = await connect(port);
    b.send(M.HELLO, hello('друг'));
    assert.equal((await b.wait(M.REFUSED)).payload[0], REFUSED.FULL);
    assert.equal(await b.closed, true);
    assert.deepEqual(online(server), ['АРЕС']);
    a.send(M.PING, Buffer.alloc(8));
    await a.wait(M.PONG);
    a.socket.destroy();
  } finally {
    server.close();
  }
});

test('a connection nothing comes from is dropped as dead after idleTimeoutMs, a talking one stays', async () => {
  const server = await start({ idleTimeoutMs: 300 });
  const { port } = server.address();
  try {
    const alive = await join(port, 'друг');
    const pings = setInterval(() => alive.send(M.PING, Buffer.alloc(8)), 50);
    const dead = await join(port, 'АРЕС');
    const mute = await connect(port); // never says hello
    assert.deepEqual(online(server), ['друг', 'АРЕС']);

    assert.equal(await dead.closed, true);
    assert.equal(await mute.closed, true);
    assert.deepEqual(online(server), ['друг']);
    assert.equal((await alive.wait(M.PEER_LEFT)).payload.readUInt32LE(0), dead.id);
    assert.ok(server.lines.some((l) => l.includes(`[${dead.id}] 'АРЕС': nothing from it for`) && l.includes('dropped as dead')));
    assert.ok(server.lines.some((l) => l.includes('a connection that never said hello')));

    await soon(700); // more than two timeouts on: the one that pings is still here
    assert.deepEqual(online(server), ['друг']);
    assert.equal(alive.socket.destroyed, false);
    clearInterval(pings);
    alive.socket.destroy();
  } finally {
    server.close();
  }
});

test('idleTimeoutMs 0: a silent connection stays', async () => {
  const server = await start({ idleTimeoutMs: 0 });
  const { port } = server.address();
  try {
    const silent = await join(port, 'АРЕС');
    await soon(400);
    assert.deepEqual(online(server), ['АРЕС']);
    assert.equal(silent.socket.destroyed, false);
    silent.socket.destroy();
  } finally {
    server.close();
  }
});
