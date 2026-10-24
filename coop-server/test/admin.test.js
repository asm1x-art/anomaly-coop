import { test } from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { startServer } from '../src/server.js';
import { startAdmin } from '../src/admin.js';
import { M, PROTOCOL_VERSION, encode, encodeText } from '../src/protocol.js';
import { normalizeSettings, DEFAULT_SETTINGS } from '../src/settings.js';

async function start() {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'coop-admin-'));
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
    assert.equal(state.settings.world.warfare, true);
    assert.equal(state.settings.world.economy, 2);
    assert.deepEqual(state.settings.factions, ['dolg', 'monolith']);
    assert.deepEqual(JSON.parse(fs.readFileSync(path.join(s.dataDir, 'settings.json'), 'utf8')), state.settings);

    const socket = await join(s.game.address().port, 'Друг');
    res = await s.call('GET', '/api/state');
    const online = (await res.json()).online;
    assert.equal(online.length, 1);
    assert.equal(online[0].name, 'Друг');
    assert.equal(online[0].master, true);
    socket.destroy();
  } finally {
    s.close();
  }
});

test('admin: world reset only with nobody online, and it clears world, characters and leases', async () => {
  const s = await start();
  try {
    for (const f of ['world.scop', 'world.scoc', 'characters.json', 'leases.json']) fs.writeFileSync(path.join(s.dataDir, f), '{}');
    fs.writeFileSync(path.join(s.dataDir, 'world.json'), JSON.stringify({ owner: 'artem', revision: 3 }));

    const socket = await join(s.game.address().port, 'artem');
    assert.equal((await s.call('POST', '/api/reset-world')).status, 409);
    socket.destroy();
    await new Promise((r) => setTimeout(r, 50)); // the server notices the leave

    const res = await s.call('POST', '/api/reset-world');
    assert.equal(res.status, 200);
    assert.equal((await res.json()).world, null);
    for (const f of ['world.scop', 'world.scoc', 'world.json', 'characters.json', 'leases.json'])
      assert.equal(fs.existsSync(path.join(s.dataDir, f)), false, f);
  } finally {
    s.close();
  }
});
