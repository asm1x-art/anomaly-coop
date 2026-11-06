import { test } from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import crypto from 'node:crypto';
import { startServer } from '../src/server.js';
import { startAdmin, CRASH_MAGIC } from '../src/admin.js';
import { M, PROTOCOL_VERSION, encode, encodeText, createDecoder } from '../src/protocol.js';
import { normalizeSettings, DEFAULT_SETTINGS, settingsText } from '../src/settings.js';

// seed(dataDir): files the server finds when it starts
async function start(seed = () => {}, adminOptions = {}) {
  const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), 'coop-admin-'));
  seed(dataDir);
  const game = await startServer({ port: 0, host: '127.0.0.1', dataDir, log: () => {} });
  const admin = await startAdmin({ port: 0, host: '127.0.0.1', password: 'secret', coop: game.coop, log: () => {}, ...adminOptions });
  const base = `http://127.0.0.1:${admin.address().port}`;
  const call = (method, url, body, password = 'secret') => fetch(base + url, {
    method,
    headers: {
      Authorization: 'Basic ' + Buffer.from('admin:' + password).toString('base64'),
      ...(body ? { 'Content-Type': 'application/json' } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  return { game, admin, dataDir, call, base, close: () => { game.close(); admin.close(); } };
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

test('the help tasks reward rule: off by default, kept when set, sent to the game as 1/0', () => {
  assert.equal(DEFAULT_SETTINGS.rules.help_rewards_all, false);
  const s = normalizeSettings({ rules: { help_rewards_all: true } });
  assert.equal(s.rules.help_rewards_all, true);
  assert.equal(normalizeSettings({ rules: { help_rewards_all: 'yes' } }).rules.help_rewards_all, false);
  assert.match(settingsText(s), /^help_rewards_all=1$/m);
  assert.match(settingsText(normalizeSettings()), /^help_rewards_all=0$/m);
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

// as launcher/src-tauri/src/crash.rs writes it
function crashReport(header, files) {
  const packed = files.map((f) => zlib.gzipSync(f.data));
  const json = Buffer.from(JSON.stringify({ ...header, files: files.map((f, i) => ({ name: f.name, size: packed[i].length, raw: f.data.length })) }));
  const len = Buffer.alloc(4);
  len.writeUInt32LE(json.length, 0);
  return Buffer.concat([Buffer.from(CRASH_MAGIC), len, json, ...packed]);
}

test('crash reports: taken without the password, listed and downloaded with it, bad ones refused', async () => {
  const s = await start(() => {}, { crashMaxMb: 1 });
  try {
    const post = (body) => fetch(s.base + '/crash-report', { method: 'POST', body });
    const log = Buffer.from('[17:00:00] load level\n'.repeat(500) + 'FATAL ERROR\n');
    const dump = crypto.randomBytes(20000);
    const header = { player: 'Тема Ливси', server: '10.10.0.1:7777', time: 1800000000, exit_code: -1073740940, code: '0xC0000374',
      meaning: 'повреждение кучи', comment: 'шёл на Агропром', build_id: 'c99183a2e17a5a59', release: '2026.11.06-1', launcher: '0.2.0' };
    let res = await post(crashReport(header, [{ name: 'xray_artem.log', data: log }, { name: '../evil.mdmp', data: dump }]));
    assert.equal(res.status, 200);
    const { id } = await res.json();
    const list = await (await s.call('GET', '/api/crashes')).json();
    assert.equal(list.length, 1);
    assert.equal(list[0].id, id);
    assert.deepEqual([list[0].player, list[0].code, list[0].comment, list[0].from], ['Тема Ливси', '0xC0000374', 'шёл на Агропром', '127.0.0.1']);
    assert.deepEqual(list[0].files.map((f) => [f.name, f.size]), [['xray_artem.log', log.length], ['evil.mdmp', dump.length]]);
    const file = (name) => s.call('GET', `/api/crash-file?player=${encodeURIComponent('Тема Ливси')}&id=${id}&file=${name}`);
    assert.deepEqual(Buffer.from(await (await file('evil.mdmp')).arrayBuffer()), dump);
    assert.deepEqual(Buffer.from(await (await file('xray_artem.log')).arrayBuffer()), log);
    assert.equal((await file('report.json')).status, 200);
    assert.equal((await s.call('GET', '/api/crashes', null, 'wrong')).status, 401);
    // not a report, sizes that don't add up, no player, too big
    assert.equal((await post(Buffer.from('hello world'))).status, 400);
    const cut = crashReport(header, [{ name: 'a.log', data: log }]);
    assert.equal((await post(cut.subarray(0, cut.length - 3))).status, 400);
    assert.equal((await post(crashReport({ ...header, player: ' ' }, []))).status, 400);
    assert.equal((await post(crashReport(header, [{ name: 'big.mdmp', data: crypto.randomBytes(1100 * 1024) }]))).status, 413);
    // ten an hour from one address
    for (let i = 1; i < 10; i++) assert.equal((await post(crashReport(header, []))).status, 200);
    assert.equal((await post(crashReport(header, []))).status, 429);
    assert.equal((await (await s.call('GET', '/api/crashes')).json()).length, 10);
  } finally {
    s.close();
  }
});

test('crash reports off (crash_max_mb = 0): the route asks for the password like any other', async () => {
  const s = await start(() => {}, { crashMaxMb: 0 });
  try {
    assert.equal((await fetch(s.base + '/crash-report', { method: 'POST', body: crashReport({ player: 'x' }, []) })).status, 401);
  } finally {
    s.close();
  }
});

const factPayload = (key, value) => Buffer.concat([encodeText(key), Buffer.from([0]), encodeText(value), Buffer.from([0])]);
const settle = () => new Promise((r) => setTimeout(r, 150));

test('public status: no password; who is on, where and since when; only the world master\'s important news', async () => {
  const s = await start();
  try {
    const port = s.game.address().port;
    const master = await join(port, 'Мастер');
    const other = await join(port, 'Друг');
    master.write(encode(M.ACTOR_STATE, Buffer.concat([encodeText('l01_escape'), Buffer.from([0]), Buffer.alloc(16)])));
    master.write(encode(M.FACT, factPayload('news', 'cooling\t12.05 14:00\tМастер: Мозговыжигатель остывает, окно рейда открыто')));
    master.write(encode(M.FACT, factPayload('news', 'trade\t12.05 14:01\tСидорович завёз патроны'))); // not important
    other.write(encode(M.FACT, factPayload('news', 'surge\t12.05 14:02\tвыброс!'))); // not the master: ignored
    master.write(encode(M.FACT, factPayload('news', 'cooling\t12.05 14:00\tМастер: Мозговыжигатель остывает, окно рейда открыто'))); // again
    await settle();
    const res = await fetch(s.base + '/api/public/status');
    assert.equal(res.status, 200);
    const st = await res.json();
    assert.equal(st.protocol, PROTOCOL_VERSION);
    assert.equal(st.max_players, 4);
    assert.deepEqual(st.players.map((p) => [p.name, p.level]), [['Мастер', 'l01_escape'], ['Друг', null]]);
    assert.ok(st.players.every((p) => p.since > 0 && p.since <= Date.now()));
    assert.equal('id' in st.players[0] || 'ping' in st.players[0] || 'from' in st.players[0], false);
    assert.deepEqual(st.news.map((n) => [n.type, n.world, n.text]), [['cooling', '12.05 14:00', 'Мастер: Мозговыжигатель остывает, окно рейда открыто']]);
    assert.equal('from' in st.news[0], false);
    // not a fact of the world
    assert.equal(s.game.coop.facts().news, undefined);
    // kept across a restart: data/news.json
    assert.equal(JSON.parse(fs.readFileSync(path.join(s.dataDir, 'news.json'), 'utf8')).length, 1);
    // the rest of the admin API still asks for the password
    assert.equal((await fetch(s.base + '/api/state')).status, 401);
    master.destroy();
    other.destroy();
  } finally {
    s.close();
  }
});

test('bug reports: the crash receiver takes kind "bug", listed with it; a report without kind is a crash', async () => {
  const s = await start(() => {}, { crashMaxMb: 1 });
  try {
    const post = (body) => fetch(s.base + '/crash-report', { method: 'POST', body });
    const png = crypto.randomBytes(5000);
    assert.equal((await post(crashReport({ kind: 'bug', player: 'Тестер', comment: 'дверь в баре не открывается', launcher: '0.3.0' },
      [{ name: 'screenshot.png', data: png }, { name: 'xray_tester.log', data: Buffer.from('log') }]))).status, 200);
    assert.equal((await post(crashReport({ player: 'Тестер', code: '0xC0000005' }, []))).status, 200);
    const list = await (await s.call('GET', '/api/crashes')).json();
    assert.deepEqual(list.map((c) => c.kind).sort(), ['bug', 'crash']);
    const bug = list.find((c) => c.kind === 'bug');
    assert.equal(bug.comment, 'дверь в баре не открывается');
    assert.deepEqual(bug.files.map((f) => f.name), ['screenshot.png', 'xray_tester.log']);
  } finally {
    s.close();
  }
});
