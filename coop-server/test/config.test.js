import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { loadConfig, EXAMPLE_CONFIG } from '../src/config.js';
import { DEFAULT_NEWS_TYPES } from '../src/news.js';

const tempDir = () => fs.mkdtempSync(path.join(os.tmpdir(), 'coop-config-'));
const load = (dir, options = {}) => loadConfig({ argv: [], env: {}, cwd: dir, packaged: false, ...options });

test('config: sections, comments, inline comments, types; data_dir from the config\'s directory', () => {
  const dir = tempDir();
  fs.writeFileSync(path.join(dir, 'server.cfg'), '﻿' + [
    '# a comment',
    '[server]',
    'port = 7790   # for games',
    'admin_port=0',
    'admin_password = pa#ss  # a "#" inside a value stays',
    'data_dir = world/data',
    '',
    '[host]',
    'game_dir = ../Anomaly',
    'exe = bin\\AnomalyDX11AVX.exe',
    'pause_when_empty = нет',
    '[telegram]',
    'token = 123:ABC-def',
    'admins = 111, 222 333',
  ].join('\r\n'));
  const c = load(dir);
  assert.equal(c.file, path.join(dir, 'server.cfg'));
  assert.equal(c.created, false);
  assert.deepEqual(c.warnings, []);
  assert.deepEqual(c.server, { port: 7790, admin_port: 0, admin_password: 'pa#ss', data_dir: path.join(dir, 'world', 'data'), max_players: 4,
    builds_file: '', allow_dev: false, allow_tests: false, crash_max_mb: 64, news_keep: 50, news_types: DEFAULT_NEWS_TYPES.join(','), language: 'rus', idle_timeout: 300 });
  assert.deepEqual(c.host, { game_dir: path.resolve(dir, '../Anomaly'), exe: 'bin\\AnomalyDX11AVX.exe', args: '', autosave_minutes: 5, pause_when_empty: false });
  assert.deepEqual(c.telegram, { token: '123:ABC-def', admins: [111, 222, 333] });
});

test('config: unknown keys and bad values are warnings, the defaults stay', () => {
  const dir = tempDir();
  fs.writeFileSync(path.join(dir, 'server.cfg'), [
    'stray = 1',
    '[server]',
    'port = 99999',
    'colour = red',
    'just text',
    'max_players = 6',
    '[sound]',
    'volume = 3',
    '[host]',
    'pause_when_empty = maybe',
    '[telegram]',
    'admins = 1, bob',
  ].join('\n'));
  const c = load(dir);
  assert.equal(c.server.port, 7777);
  assert.equal(c.server.max_players, 6);
  assert.equal(c.host.pause_when_empty, true);
  assert.deepEqual(c.telegram.admins, [1]);
  assert.equal(c.warnings.length, 7, c.warnings.join('\n'));
  for (const [i, word] of ['stray', 'port', 'colour', 'line 5', 'sound', 'pause_when_empty', 'bob'].entries())
    assert.match(c.warnings[i], new RegExp(word));
});

test('config: the environment overrides the file', () => {
  const dir = tempDir();
  fs.writeFileSync(path.join(dir, 'server.cfg'), '[server]\nport = 7790\nadmin_port = 8090\nadmin_password = file\n');
  const c = load(dir, { env: { COOP_PORT: '7791', COOP_HTTP_PORT: '0', COOP_ADMIN_PASSWORD: 'env' } });
  assert.equal(c.server.port, 7791);
  assert.equal(c.server.admin_port, 0);
  assert.equal(c.server.admin_password, 'env');
  assert.equal(load(dir, { env: { COOP_PORT: 'x' } }).server.port, 7790);
});

test('config: missing, an example is written and the defaults used; the example reads back as the defaults', () => {
  const dir = tempDir();
  const c = load(dir);
  assert.equal(c.created, true);
  assert.equal(fs.readFileSync(path.join(dir, 'server.cfg'), 'utf8'), EXAMPLE_CONFIG);
  assert.deepEqual(c.warnings, []);
  assert.equal(c.server.port, 7777);
  assert.equal(c.server.admin_port, 8080);
  assert.equal(c.server.data_dir, path.join(dir, 'data'));
  assert.equal(c.host.game_dir, '');
  assert.equal(c.telegram.token, '');

  const again = load(dir);
  assert.equal(again.created, false);
  assert.deepEqual({ ...again, created: true }, c);
});

test('config: where it is looked for', () => {
  const dir = tempDir();
  const exeDir = path.join(dir, 'bin');
  assert.equal(load(dir, { packaged: true, execPath: path.join(exeDir, 'anomaly-server.exe') }).file, path.join(exeDir, 'server.cfg'));
  assert.equal(load(dir, { argv: ['other.cfg'] }).file, path.join(dir, 'other.cfg'));
  assert.equal(load(dir, { argv: ['--config', 'a/b.cfg'] }).file, path.join(dir, 'a', 'b.cfg'));
  assert.equal(load(dir, { argv: ['--config=c.cfg'] }).file, path.join(dir, 'c.cfg'));
  assert.equal(fs.existsSync(path.join(dir, 'a', 'b.cfg')), true);
});

test('config: the world\'s language, rus by default; eng taken, anything else a warning', () => {
  const dir = tempDir();
  assert.equal(load(dir).server.language, 'rus');
  fs.writeFileSync(path.join(dir, 'server.cfg'), '[server]\nlanguage = ENG\n');
  const eng = load(dir);
  assert.equal(eng.server.language, 'eng');
  assert.deepEqual(eng.warnings, []);
  fs.writeFileSync(path.join(dir, 'server.cfg'), '[server]\nlanguage = ukr\n');
  const bad = load(dir);
  assert.equal(bad.server.language, 'rus');
  assert.match(bad.warnings[0], /language/);
});
