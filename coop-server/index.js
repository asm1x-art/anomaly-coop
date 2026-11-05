import { startServer } from './src/server.js';
import { startAdmin } from './src/admin.js';

const port = Number(process.env.COOP_PORT ?? 7777);
// COOP_BUILDS_FILE: the launcher's builds.json, only those builds get in (and "dev" ones with COOP_ALLOW_DEV=1)
const builds = { file: process.env.COOP_BUILDS_FILE || null, allowDev: process.env.COOP_ALLOW_DEV === '1' };
const server = await startServer({ port, builds });

// COOP_ADMIN_PASSWORD, or the one in data/admin.json (made up and shown on the first start)
let password = process.env.COOP_ADMIN_PASSWORD;
if (!password) {
  const admin = server.coop.adminPassword();
  password = admin.password;
  console.log(admin.created ? `admin page password: ${password} (kept in data/admin.json)` : 'admin page password: see data/admin.json');
}
await startAdmin({ port: Number(process.env.COOP_HTTP_PORT ?? 8080), password, coop: server.coop });
