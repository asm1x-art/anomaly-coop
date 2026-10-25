import { test } from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import { startServer } from '../src/server.js';
import { startAdmin } from '../src/admin.js';
import { M, PROTOCOL_VERSION, encode, encodeText, createDecoder } from '../src/protocol.js';
import { normalizeSettings, DEFAULT_SETTINGS } from '../src/settings.js';

// seed(dataDir): files the server finds when it starts
async function start(seed = () => {}) {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'coop-admin-'));
  seed(dataDir);
  const game = await startServer({ port: 0, host: '127.0.0.1', dataDir, log: () => {} });
  const admin = await startAdmin({ port: 0, host: '127.0.0.1', password: 'secret', coop: game.coop, log: () => {} });
  const base = `http://127.0.0.1:${admin.address().port}`;
  const call = (method, url, body, password = 'secret') => fetch(base + url, {
    method,
    headers: {
      Authorization: 'Basic ' + Buffer.from('admin:' + password).toString('base64'),
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  return { game, admin, dataDir, call, close: () => { game.close(); admin.close(); } };
}

function join(port, name) {
  const socket = net.connect(port, '127.0.0.1');
  const hello = Buffer.alloc(2);
  hello.writeUInt16LE(PROTOCOL_VERSION, 0);
  socket.on('connect', () => socket.write(encode(M.HELLO, Buffer.concat([hello, encodeText(name), Buffer.from([0])]))));
  return new Promise((r) => socket.once('data', () => r(socket))); // WELCOME
}

test('settings are normalized: bad values fall back, unknown factions dropped, never none', () => {
  assert.deepEqual(normalizeSettings(), DEFAULT_SETTINGS);
  const s = normalizeSettings({ world: { story: 'yes', difficulty: 9, ironman_regen: 5, extra: 1 }, factions: ['dolg', 'zombied'] });
  assert.equal(s.world.story, true);
  assert.equal(s.world.difficulty, 3);
  assert.equal(s.world.ironman_regen, 0);
  assert.equal('extra' in s.world, false);
  assert.deepEqual(s.factions, ['dolg']);
  assert.deepEqual(normalizeSettings({ factions: [] }).factions, DEFAULT_SETTINGS.factions);
});

test('admin: password required, settings saved and kept, players listed', async () => {
  const s = await start();
  try {
    assert.equal((await s.call('GET', '/api/state', null, 'wrong')).status, 401);
    assert.match(await (await s.call('GET', '/')).text(), /<title>/);

    let res = await s.call('PUT', '/api/settings', { world: { warfare: true, economy: 2 }, factions: ['monolith', 'dolg'] });
    assert.equal(res.status, 200);
    const state = await res.json();
    assert.equal(state.settings.world.warfare, false); // off in co-op whatever is asked
    assert.equal(state.settings.world.economy, 2);
    assert.deepEqual(state.settings.factions, ['dolg', 'monolith']);
    assert.deepEqual(JSON.parse(fs.readFileSync(path.join(s.dataDir, 'settings.json'), 'utf8')), state.settings);

    const socket = await join(s.game.address().port, 'Друг');
    res = await s.call('GET', '/api/state');
    const online = (await res.json()).online;
    assert.equal(online.length, 1);
    assert.equal(online[0].name, 'Друг');
    assert.equal(online[0].master, true);
    assert.equal(online[0].ping, null);

    const ping = Buffer.alloc(8);
    ping.writeUInt32LE(42, 4); // the client's last round trip
    socket.write(encode(M.PING, ping));
    await new Promise((r) => socket.on('data', createDecoder((type) => type === M.PONG && r())));
    assert.equal((await (await s.call('GET', '/api/state')).json()).online[0].ping, 42);
    socket.destroy();
  } finally {
    s.close();
  }
});

test('admin: world reset only with nobody online, and it clears saves, characters and leases', async () => {
  // a world kept the old way: it becomes save 3
  const s = await start((dataDir) => {
    for (const f of ['world.scop', 'world.scoc', 'characters.json', 'leases.json']) fs.writeFileSync(path.join(dataDir, f), '{}');
    fs.writeFileSync(path.join(dataDir, 'world.json'), JSON.stringify({ owner: 'artem', revision: 3 }));
  });
  try {
    assert.deepEqual((await (await s.call('GET', '/api/state')).json()).world, { owner: 'artem', revision: 3 });
    assert.equal(fs.existsSync(path.join(s.dataDir, 'saves', '3', 'world.scop')), true);

    const socket = await join(s.game.address().port, 'artem');
    assert.equal((await s.call('POST', '/api/reset-world')).status, 409);
    socket.destroy();
    await new Promise((r) => setTimeout(r, 50)); // the server notices the leave

    const res = await s.call('POST', '/api/reset-world');
    assert.equal(res.status, 200);
    assert.equal((await res.json()).world, null);
    for (const f of ['saves', 'world.scop', 'world.json', 'characters.json', 'leases.json'])
      assert.equal(fs.existsSync(path.join(s.dataDir, f)), false, f);
  } finally {
    s.close();
  }
});

test('admin: saves listed newest first; rollback makes the old save the world again', async () => {
  const s = await start((dataDir) => {
    for (const f of ['world.scop', 'world.scoc']) fs.writeFileSync(path.join(dataDir, f), 'old');
    fs.writeFileSync(path.join(dataDir, 'world.json'), JSON.stringify({ owner: 'artem', revision: 3 }));
  });
  try {
    let state = await (await s.call('GET', '/api/state')).json();
    assert.deepEqual(state.saves.map((m) => m.revision), [3]);
    assert.equal((await s.call('POST', '/api/rollback', { revision: 9 })).status, 404);
    state = await (await s.call('POST', '/api/rollback', { revision: 3 })).json();
    assert.deepEqual(state.world, { owner: 'artem', revision: 4 });
    assert.deepEqual(state.saves.map((m) => [m.revision, m.reason, m.from]), [[4, 'rollback', 3], [3, 'auto', undefined]]);
  } finally {
    s.close();
  }
});

test('logs: a game sends them in packed chunks; listed newest first and downloadable; unreadable ones dropped', async () => {
  const s = await start();
  try {
    const socket = await join(s.game.address().port, 'друг');
    const send = (file, raw, packed) => {
      for (let offset = 0; offset === 0 || offset < packed.length; offset += 14000) {
        const head = Buffer.alloc(12);
        head.writeUInt32LE(raw.length, 0);
        head.writeUInt32LE(packed.length, 4);
        head.writeUInt32LE(offset, 8);
        socket.write(encode(M.LOG, Buffer.concat([Buffer.from(file + '\0'), head, packed.subarray(offset, offset + 14000)])));
      }
    };
    const log = Buffer.from('FATAL ERROR\n'.repeat(20000)); // packs into several chunks? no: tiny packed; still offsets work
    const big = Buffer.from(Array.from({ length: 60000 }, (_, i) => String.fromCharCode(32 + (i * 7919) % 90)).join(''));
    send('xray_friend_2026-10-25_18-00-00.log', log, zlib.deflateSync(log));
    send('xray_player_10-25-26_18-01-00.mdmp', big, zlib.deflateSync(big)); // several chunks
    send('../../evil name.log', Buffer.from('x'), Buffer.from('not zlib'));
    for (let i = 0; i < 50 && (await (await s.call('GET', '/api/logs')).json()).length < 2; i++)
      await new Promise((r) => setTimeout(r, 20));
    const logs = await (await s.call('GET', '/api/logs')).json();
    assert.deepEqual(logs.map((l) => [l.player, l.file, l.size]).sort(), [
      ['друг', 'xray_friend_2026-10-25_18-00-00.log', log.length],
      ['друг', 'xray_player_10-25-26_18-01-00.mdmp', big.length],
    ]);
    const res = await s.call('GET', `/api/log?player=${encodeURIComponent('друг')}&file=xray_player_10-25-26_18-01-00.mdmp`);
    assert.equal(res.status, 200);
    assert.deepEqual(Buffer.from(await res.arrayBuffer()), big);
    assert.equal((await s.call('GET', `/api/log?player=x&file=nope.log`)).status, 404);
    socket.destroy();
  } finally {
    s.close();
  }
});
