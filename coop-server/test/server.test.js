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
