import { startServer } from './src/server.js';
import { startAdmin } from './src/admin.js';
import { startTelegram } from './src/telegram.js';
import { loadConfig } from './src/config.js';
import { startHost } from './src/host.js';
import crypto from 'node:crypto';

// server.cfg (config.js): next to the executable, or the path given as the first argument
const config = loadConfig();
console.log(config.created ? `no config: an example written to ${config.file}, defaults used` : `config: ${config.file}`);
for (const warning of config.warnings) console.log(`config: ${warning}`);

// the world's host, when there is a game for it: only the game started here knows the secret
const hostSecret = config.host.game_dir ? crypto.randomBytes(8).toString('hex') : null;
const server = await startServer({ port: config.server.port, dataDir: config.server.data_dir, hostSecret });
if (hostSecret) {
  const host = startHost({ gameDir: config.host.game_dir, exe: config.host.exe, args: config.host.args,
    port: config.server.port, secret: hostSecret, events: server.coop.events });
  server.coop.setHostProcess(host);
  const stop = () => {
    host.stop();
    process.exit(0);
  };
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
} else console.log("no host (no game_dir in [host]): a player's game keeps the world");

if (config.server.admin_port) {
  // admin_password, or the one in data/admin.json (made up and shown on the first start)
  let password = config.server.admin_password;
  if (!password) {
    const admin = server.coop.adminPassword();
    password = admin.password;
    console.log(admin.created ? `admin page password: ${password} (kept in data/admin.json)` : 'admin page password: see data/admin.json');
  }
  await startAdmin({ port: config.server.admin_port, password, coop: server.coop });
} else console.log('admin page off (admin_port = 0)');

const { token, admins } = config.telegram;
if (!token) console.log('telegram bot off (no token in server.cfg)');
else {
  console.log(admins.length ? `telegram bot on, admins: ${admins.join(', ')}` : 'telegram bot on, but no admins in server.cfg: it answers nobody');
  startTelegram({ token, admins, coop: server.coop });
}
