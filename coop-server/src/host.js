import { spawn } from 'node:child_process';
import path from 'node:path';

// The world's host (docs/coop/multiplayer.md): the game started headless (-coop_host <secret>), the sim master
// whenever it runs the world. Started here and started again whenever it stops; stopping CRASH_LIMIT times within
// CRASH_WINDOW_MS leaves it down until restart() (the bot's /restart_host).
const CRASH_LIMIT = 3;
const CRASH_WINDOW_MS = 5 * 60000;
const RESTART_DELAY_MS = 5000;
export const HOST_NAME = 'host';

// "a b \"c d\"" -> ['a', 'b', 'c d']
export function splitArgs(text) {
  return [...String(text).matchAll(/"([^"]*)"|(\S+)/g)].map((m) => m[1] ?? m[2]);
}

// gameDir, exe (from gameDir), args (more of the game's command line, e.g. its own -fsltx); port: the server's;
// events: the server's (coop.on), told host_down { code, restarting }
export function startHost({ gameDir, exe, args = '', port, secret, events, log = console.log }) {
  const exePath = path.resolve(gameDir, exe);
  // -coop_connect last: it takes the words after it (coop_connect <host>[:port] [name])
  // -silent_error_mode: a crash ends it, with a report but no window to answer (the engine's own errors end it too)
  const argv = ['-coop_host', secret, '-nosound', '-silent_error_mode', ...splitArgs(args), '-coop_connect',
    `127.0.0.1:${port}`, HOST_NAME];
  let child = null;
  let startedAt = 0;
  let timer = null;
  let stopping = false;
  let gaveUp = false;
  let stops = []; // when it stopped on its own lately

  const launch = () => {
    timer = null;
    gaveUp = false;
    child = spawn(exePath, argv, { cwd: path.dirname(exePath), stdio: 'ignore', windowsHide: true });
    startedAt = Date.now();
    log(`host: started ${exePath} (pid ${child.pid})`);
    const self = child;
    self.on('error', (e) => log(`host: ${e.message}`)); // 'exit' follows when it ran at all
    self.on('exit', (code) => {
      if (child !== self) return;
      child = null;
      if (stopping) return;
      const now = Date.now();
      stops = stops.filter((t) => now - t < CRASH_WINDOW_MS);
      stops.push(now);
      gaveUp = stops.length >= CRASH_LIMIT;
      log(gaveUp ? `host: stopped (code ${code}) ${CRASH_LIMIT} times in ${CRASH_WINDOW_MS / 60000} minutes, left down`
        : `host: stopped (code ${code}), starting it again in ${RESTART_DELAY_MS / 1000} s`);
      events.emit('host_down', { code, restarting: !gaveUp });
      if (!gaveUp) timer = setTimeout(launch, RESTART_DELAY_MS);
    });
  };
  launch();

  return {
    status: () => ({ running: !!child, pid: child?.pid ?? null, uptime: child ? Math.floor((Date.now() - startedAt) / 1000) : 0,
      gave_up: gaveUp }),
    // started again at once, whatever it was doing (the world since its last save is lost to it)
    restart() {
      clearTimeout(timer);
      stops = [];
      if (child) {
        const old = child;
        child = null;
        old.kill();
        log('host: restarting');
      }
      launch();
      return true;
    },
    stop() {
      stopping = true;
      clearTimeout(timer);
      child?.kill();
      child = null;
    },
  };
}
