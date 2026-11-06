import fs from 'node:fs';
import path from 'node:path';
import { isSea } from 'node:sea';
import { RULE_LIMITS } from './settings.js';
import { DEFAULT_NEWS_TYPES } from './news.js';

// server.cfg: how the server runs (ports, password, where the world is kept, the host, the Telegram bot).
// The world's own settings are not here: they are in data/settings.json, changed on the admin page or by the bot.
// "[section]" lines, "key = value" lines; "#" starts a comment, at the start of a line or after a space
// (so a password may hold a "#", just not " #"). An empty value is the default.
// Where: the path given as the first argument or with --config; else next to the executable when packaged
// (tools/server/build.mjs), next to where it's run from otherwise. Missing: an example is written there.
// The environment overrides the file: COOP_PORT, COOP_HTTP_PORT, COOP_ADMIN_PASSWORD, COOP_BUILDS_FILE, COOP_ALLOW_DEV.

export const CONFIG_FILE = 'server.cfg';

// section -> key -> default; the default's type is the value's
const DEFAULTS = {
  server: { port: 7777, admin_port: 8080, admin_password: '', data_dir: 'data', max_players: 4, builds_file: '',
    allow_dev: false, crash_max_mb: 64, news_keep: 50, news_types: DEFAULT_NEWS_TYPES.join(',') },
  host: { game_dir: '', exe: 'bin\\AnomalyDX11.exe', args: '', autosave_minutes: 5, pause_when_empty: true },
  telegram: { token: '', admins: [] },
};

// [min, max] of the numbers
const LIMITS = {
  port: [1, 65535],
  admin_port: [0, 65535], // 0: no admin page
  max_players: RULE_LIMITS.max_players,
  autosave_minutes: [0, 24 * 60], // 0: no autosaves
  crash_max_mb: [0, 1024], // 0: no crash reports from the launchers
  news_keep: [0, 1000], // 0: no news journal
};

const ENV = { COOP_PORT: ['server', 'port'], COOP_HTTP_PORT: ['server', 'admin_port'], COOP_ADMIN_PASSWORD: ['server', 'admin_password'],
  COOP_BUILDS_FILE: ['server', 'builds_file'], COOP_ALLOW_DEV: ['server', 'allow_dev'] };

const YES = ['1', 'true', 'yes', 'on', 'да'];
const NO = ['0', 'false', 'no', 'off', 'нет'];

export const EXAMPLE_CONFIG = `# Сервер Anomaly co-op. Строки «ключ = значение» по секциям, после # — комментарий.
# Пустое значение — значение по умолчанию. После правки перезапустите сервер.

[server]
port = 7777            # порт для игр (TCP), его открывают для друзей
admin_port = 8080      # веб-админка; 0 — выключена
admin_password =       # пусто — придумается и запишется в data/admin.json
data_dir = data        # где хранится мир; путь от папки этого файла
max_players = 4        # игроков на сервере одновременно
builds_file =          # builds.json лаунчера: пускать только выпущенные сборки; пусто — пускать все
allow_dev = 0          # с builds_file: пускать и сборки «dev» (без лаунчера): 1 — да, 0 — нет
crash_max_mb = 64      # отчёты о вылетах и баги от лаунчеров (на порт админки, без пароля): размер одного, МБ; 0 — не принимать
news_keep = 50         # журнал важных новостей мира для лаунчеров (data/news.json): сколько последних хранить; 0 — не вести
news_types = ${DEFAULT_NEWS_TYPES.join(',')}  # какие новости важные (присылает хост или мастер симуляции)

[host]
game_dir =             # папка игры для хоста; пусто — без хоста (мир держит игрок, как раньше)
exe = bin\\AnomalyDX11.exe  # exe игры, путь от game_dir; своя папка bin, если на этом ПК играют из той же игры
args =                 # ещё параметры игры хоста, например своя appdata: -fsltx ..\\fsgame_host.ltx
autosave_minutes = 5   # автосохранение мира хостом, минут; 0 — выключено
pause_when_empty = 1   # мир стоит, пока в нём нет игроков: 1 — да, 0 — нет

[telegram]
token =                # токен бота от @BotFather; пусто — без бота
admins =               # id пользователей Telegram через запятую
`;

// the config's path: the argument, or the default place
function configPath(argv, cwd, packaged, execPath) {
  const at = argv.findIndex((a) => a === '--config' || a.startsWith('--config='));
  const given = at === -1 ? argv.find((a) => !a.startsWith('-')) : argv[at].slice('--config='.length) || argv[at + 1];
  if (given) return path.resolve(cwd, given);
  return path.join(packaged ? path.dirname(execPath) : cwd, CONFIG_FILE);
}

// a value from the file or the environment as the default's type; undefined (and a warning) when it isn't one
function parseValue(key, text, def, warn) {
  if (typeof def === 'string') return text;
  if (typeof def === 'boolean') {
    const word = text.toLowerCase();
    if (YES.includes(word)) return true;
    if (NO.includes(word)) return false;
    return warn(`${key}: "${text}" is not 1 or 0, the default is used`);
  }
  if (Array.isArray(def)) {
    const ids = text.split(/[\s,]+/).filter(Boolean);
    const bad = ids.filter((id) => !/^-?\d+$/.test(id));
    if (bad.length) warn(`${key}: not Telegram ids, left out: ${bad.join(', ')}`);
    return ids.filter((id) => !bad.includes(id)).map(Number);
  }
  const [min, max] = LIMITS[key] ?? [0, Number.MAX_SAFE_INTEGER];
  const n = Number(text);
  if (Number.isInteger(n) && n >= min && n <= max) return n;
  return warn(`${key}: "${text}" is not a whole number from ${min} to ${max}, the default is used`);
}

// { file, created, warnings, server, host, telegram }: every key there, with its default when the file has none;
// data_dir and game_dir absolute (relative ones are from the config's directory). created: the file was missing
// and an example was written.
export function loadConfig({ argv = process.argv.slice(2), env = process.env, cwd = process.cwd(),
  packaged = isSea(), execPath = process.execPath } = {}) {
  const file = configPath(argv, cwd, packaged, execPath);
  const warnings = [];
  const warn = (text) => void warnings.push(text);
  const config = Object.fromEntries(Object.entries(DEFAULTS).map(([section, keys]) =>
    [section, Object.fromEntries(Object.entries(keys).map(([key, def]) => [key, Array.isArray(def) ? [...def] : def]))]));

  let text = null;
  let created = false;
  try {
    text = fs.readFileSync(file, 'utf8');
  } catch {
    try {
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(file, EXAMPLE_CONFIG);
      created = true;
    } catch (e) {
      warn(`no ${file}, and no example could be written there: ${e.message}`);
    }
  }

  let section = null;
  (text ?? '').replace(/^﻿/, '').split(/\r?\n/).forEach((raw, i) => {
    const line = raw.replace(/(^|\s)#.*$/, '').trim();
    if (!line) return;
    const where = `line ${i + 1}`;
    const head = line.match(/^\[\s*([^\]]*?)\s*\]$/);
    if (head) {
      section = head[1].toLowerCase();
      if (!DEFAULTS[section]) warn(`${where}: unknown section [${head[1]}], its keys are ignored`);
      return;
    }
    const eq = line.indexOf('=');
    if (eq === -1) return warn(`${where}: not "key = value", ignored`);
    const key = line.slice(0, eq).trim().toLowerCase();
    const value = line.slice(eq + 1).trim();
    if (!section) return warn(`${where}: "${key}" is outside any section, ignored`);
    if (!DEFAULTS[section]) return;
    if (!(key in DEFAULTS[section])) return warn(`${where}: unknown key "${key}" in [${section}], ignored`);
    if (value === '') return;
    const parsed = parseValue(key, value, DEFAULTS[section][key], (t) => warn(`${where}: ${t}`));
    if (parsed !== undefined) config[section][key] = parsed;
  });

  for (const [name, [section, key]] of Object.entries(ENV)) {
    if (env[name] === undefined || env[name] === '') continue;
    const parsed = parseValue(key, env[name], DEFAULTS[section][key], (t) => warn(`${name}: ${t}`));
    if (parsed !== undefined) config[section][key] = parsed;
  }

  const dir = path.dirname(file);
  config.server.data_dir = path.resolve(dir, config.server.data_dir);
  if (config.host.game_dir) config.host.game_dir = path.resolve(dir, config.host.game_dir);
  if (config.server.builds_file) config.server.builds_file = path.resolve(dir, config.server.builds_file);
  return { file, created, warnings, ...config };
}
