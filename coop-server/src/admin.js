import http from 'node:http';
import crypto from 'node:crypto';
import fs from 'node:fs';
import zlib from 'node:zlib';
import { isSea, getAsset } from 'node:sea';
import { FACTIONS } from './settings.js';
import { WORLD_EVENTS, eventsText } from './admin_commands.js';

// The admin page: world settings, allowed factions, who is online, world reset, crash and bug reports.
// HTTP basic auth, any user name, the server's admin password. Two routes without it (the admin port is reached
// through the tunnel, like the game's): POST /crash-report, the launchers' crash and bug reports (see
// readCrashReport), and GET /api/public/status, who is on and the world's news for the launchers (server.js
// publicStatus: no addresses, saves or timetables).

// packaged (tools/server/build.mjs), the page is inside the executable
const PAGE = isSea() ? Buffer.from(getAsset('admin.html')) : fs.readFileSync(new URL('./admin.html', import.meta.url));
const BODY_LIMIT = 64 * 1024;

const sha256 = (text) => crypto.createHash('sha256').update(text).digest();

export const CRASH_MAGIC = 'ACR1';
const CRASH_HEADER_LIMIT = 64 * 1024;
const CRASH_PER_HOUR = 10; // reports from one address

// A launcher's crash report (launcher/src-tauri/src/crash.rs): "ACR1", u32 LE length of a JSON header, the header
// ({ kind, player, server, time, exit_code, code, meaning, hint, comment, build_id, release, launcher,
// files: [{ name, size, raw, cut }], skipped }), then each file gzipped, in the header's order. kind "bug": a
// bug the player reported (comment: what happened; a screenshot and the last log), else a crash.
// Returns { report, files: [{ name, data }] } or throws with an HTTP status.
export function readCrashReport(body, maxBytes) {
  const fail = (status, message) => Object.assign(new Error(message), { status });
  if (body.length < 8 || body.toString('latin1', 0, 4) !== CRASH_MAGIC) throw fail(400, 'not a crash report');
  const len = body.readUInt32LE(4);
  if (len > CRASH_HEADER_LIMIT || 8 + len > body.length) throw fail(400, 'bad header');
  let header;
  try {
    header = JSON.parse(body.toString('utf8', 8, 8 + len));
  } catch {
    throw fail(400, 'bad header');
  }
  const text = (v, max) => (typeof v === 'string' ? v : '').slice(0, max);
  const player = text(header.player, 64).trim();
  if (!player) throw fail(400, 'no player');
  const list = Array.isArray(header.files) ? header.files.slice(0, 16) : [];
  let at = 8 + len;
  const files = [];
  let unpacked = 0;
  for (const f of list) {
    const size = Number(f?.size);
    if (!Number.isSafeInteger(size) || size < 0 || at + size > body.length) throw fail(400, 'bad file sizes');
    let data;
    try {
      // a dump packs ~4:1 at most, a log ~10:1; the limit keeps a gzip bomb out
      data = zlib.gunzipSync(body.subarray(at, at + size), { maxOutputLength: Math.max(1, maxBytes * 16 - unpacked) });
    } catch {
      throw fail(400, `${text(f?.name, 120)} does not unpack`);
    }
    unpacked += data.length;
    files.push({ name: text(f?.name, 120) || 'file', data });
    at += size;
  }
  if (at !== body.length) throw fail(400, 'bad file sizes');
  const exit = Number.isSafeInteger(header.exit_code) ? header.exit_code : null;
  const report = {
    kind: header.kind === 'bug' ? 'bug' : 'crash',
    player, server: text(header.server, 120), time: Number.isSafeInteger(header.time) ? header.time : null,
    exit_code: exit, code: text(header.code, 32), meaning: text(header.meaning, 120), hint: text(header.hint, 400),
    comment: text(header.comment, 4000), build_id: text(header.build_id, 64), release: text(header.release, 64),
    launcher: text(header.launcher, 32),
    files: files.map((f, i) => ({ name: f.name, size: f.data.length, cut: !!list[i]?.cut })),
    skipped: Array.isArray(header.skipped) ? header.skipped.slice(0, 16).map((s) => text(s, 200)) : [],
  };
  return { report, files };
}

export function startAdmin({ port = 8080, host = '0.0.0.0', password, coop, log = console.log, crashMaxMb = 64 }) {
  const expected = sha256(password);
  const authorized = (req) => {
    const [scheme, encoded] = (req.headers.authorization ?? '').split(' ');
    if (scheme !== 'Basic' || !encoded) return false;
    const decoded = Buffer.from(encoded, 'base64').toString('utf8');
    return crypto.timingSafeEqual(sha256(decoded.slice(decoded.indexOf(':') + 1)), expected);
  };

  const reply = (res, status, body, type = 'application/json; charset=utf-8') => {
    res.writeHead(status, { 'Content-Type': type, 'Cache-Control': 'no-store' });
    res.end(type.startsWith('application/json') ? JSON.stringify(body) : body);
  };

  const readJson = (req) => new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > BODY_LIMIT) reject(new Error('body too large'));
      else chunks.push(chunk);
    });
    req.on('end', () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
      } catch (e) {
        reject(e);
      }
    });
    req.on('error', reject);
  });

  // events: the world's events as its game last told them (server.js events), with their list and the lines to show
  const events = () => {
    if (typeof coop.events !== 'function') return null;
    const now = coop.events();
    return { ...now, list: WORLD_EVENTS, lines: eventsText(now) };
  };
  const state = () => ({ ...coop.status(), settings: coop.settings(), factions: FACTIONS, events: events() });

  const crashLimit = crashMaxMb * 1024 * 1024;
  const recent = new Map(); // address -> times of its reports in the last hour
  const takeCrash = (req, res) => {
    const from = req.socket.remoteAddress ?? '';
    const now = Date.now();
    const times = (recent.get(from) ?? []).filter((t) => now - t < 3600e3);
    if (times.length >= CRASH_PER_HOUR) {
      req.resume();
      return reply(res, 429, { error: 'too many reports' });
    }
    if (Number(req.headers['content-length']) > crashLimit) {
      req.resume();
      return reply(res, 413, { error: 'too large' });
    }
    const chunks = [];
    let size = 0;
    let over = false;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > crashLimit) over = true;
      else chunks.push(chunk);
    });
    req.on('end', () => {
      if (over) return reply(res, 413, { error: 'too large' });
      try {
        const { report, files } = readCrashReport(Buffer.concat(chunks), crashLimit);
        times.push(now);
        recent.set(from, times);
        const id = coop.saveCrash({ ...report, received: now, from }, files);
        reply(res, 200, { ok: true, id });
      } catch (e) {
        reply(res, e.status ?? 500, { error: e.message });
      }
    });
    req.on('error', () => {});
  };

  const server = http.createServer(async (req, res) => {
    if (req.method === 'POST' && req.url === '/crash-report' && crashLimit > 0) return takeCrash(req, res);
    if (req.method === 'GET' && req.url.split('?')[0] === '/api/public/status') return reply(res, 200, coop.publicStatus());
    if (!authorized(req)) {
      res.writeHead(401, { 'WWW-Authenticate': 'Basic realm="Anomaly co-op", charset="UTF-8"' });
      res.end();
      return;
    }
    const url = new URL(req.url, 'http://x');
    const route = `${req.method} ${url.pathname}`;
    try {
      switch (route) {
        case 'GET /':
          return reply(res, 200, PAGE, 'text/html; charset=utf-8');
        case 'GET /api/state':
          return reply(res, 200, state());
        case 'PUT /api/settings':
          coop.saveSettings(await readJson(req));
          return reply(res, 200, state());
        case 'POST /api/reset-world':
          if (!coop.resetWorld()) return reply(res, 409, { error: 'players are online' });
          return reply(res, 200, state());
        case 'GET /api/logs':
          return reply(res, 200, coop.logs());
        case 'GET /api/crashes':
          return reply(res, 200, coop.crashes());
        case 'GET /api/crash-file': {
          const file = url.searchParams.get('file') ?? '';
          const data = coop.crashFile(url.searchParams.get('player') ?? '', url.searchParams.get('id') ?? '', file);
          if (!data) return reply(res, 404, { error: 'no such file' });
          res.writeHead(200, { 'Content-Type': 'application/octet-stream', 'Cache-Control': 'no-store',
            'Content-Disposition': `attachment; filename="${file.replace(/[^\w.-]/g, '_')}"` });
          return res.end(data);
        }
        case 'GET /api/log': {
          const file = url.searchParams.get('file') ?? '';
          const data = coop.logFile(url.searchParams.get('player') ?? '', file);
          if (!data) return reply(res, 404, { error: 'no such log' });
          res.writeHead(200, { 'Content-Type': 'application/octet-stream', 'Cache-Control': 'no-store',
            'Content-Disposition': `attachment; filename="${file.replace(/[^\w.-]/g, '_')}"` });
          return res.end(data);
        }
        case 'POST /api/event': {
          // a world's event started or stopped: { name, action: start|stop }; the server's answer and the state
          const { name, action } = await readJson(req);
          const answer = coop.worldEvent(String(name ?? ''), String(action ?? ''), 'админ-страница');
          return reply(res, 200, { answer, ...state() });
        }
        case 'POST /api/resume':
          coop.resume();
          return reply(res, 200, state());
        case 'POST /api/rollback': {
          const revision = Number((await readJson(req)).revision);
          if (revision === coop.status().world?.revision) return reply(res, 409, { error: 'that save is the world now' });
          if (!coop.rollback(revision)) return reply(res, 404, { error: 'no such save' });
          return reply(res, 200, state());
        }
        default:
          return reply(res, 404, { error: 'not found' });
      }
    } catch (e) {
      return reply(res, 400, { error: e.message });
    }
  });

  return new Promise((resolve) => {
    server.listen(port, host, () => {
      log(`admin page on http://${host === '0.0.0.0' ? 'localhost' : host}:${server.address().port}`);
      resolve(server);
    });
  });
}
