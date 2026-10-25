import http from 'node:http';
import crypto from 'node:crypto';
import fs from 'node:fs';
import { FACTIONS } from './settings.js';

// The admin page: world settings, allowed factions, who is online, world reset.
// HTTP basic auth, any user name, the server's admin password.

const PAGE = fs.readFileSync(new URL('./admin.html', import.meta.url));
const BODY_LIMIT = 64 * 1024;

const sha256 = (text) => crypto.createHash('sha256').update(text).digest();

export function startAdmin({ port = 8080, host = '0.0.0.0', password, coop, log = console.log }) {
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

  const state = () => ({ ...coop.status(), settings: coop.settings(), factions: FACTIONS });

  const server = http.createServer(async (req, res) => {
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
        case 'GET /api/log': {
          const file = url.searchParams.get('file') ?? '';
          const data = coop.logFile(url.searchParams.get('player') ?? '', file);
          if (!data) return reply(res, 404, { error: 'no such log' });
          res.writeHead(200, { 'Content-Type': 'application/octet-stream', 'Cache-Control': 'no-store',
            'Content-Disposition': `attachment; filename="${file.replace(/[^\w.-]/g, '_')}"` });
          return res.end(data);
        }
        case 'POST /api/resume':
          coop.resume();
          return reply(res, 200, state());
        case 'POST /api/rollback':
          if (!coop.rollback(Number((await readJson(req)).revision))) return reply(res, 404, { error: 'no such save' });
          return reply(res, 200, state());
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
