import fs from 'node:fs';

// Which game builds may join: the launcher starts the game with -coop_build <id> from its release, the game sends
// it in HELLO; builds without the launcher send "dev". The list is builds.json, written by the launcher's
// release tool (anomaly-coop-launcher release/publish.mjs): { builds: [{ id, release, channel }] }.
// Without a file (COOP_BUILDS_FILE unset: a local test server) every build gets in. A file that can't be read
// lets everyone in too, with a warning: a broken publish must not lock the players out.
export function createBuildCheck({ file, allowDev = false, log = console.log } = {}) {
  if (!file) return () => true;
  let cache = { mtimeMs: -1, ids: null };
  const ids = () => {
    try {
      const st = fs.statSync(file);
      if (st.mtimeMs !== cache.mtimeMs) {
        const list = JSON.parse(fs.readFileSync(file, 'utf8')).builds ?? [];
        cache = { mtimeMs: st.mtimeMs, ids: new Set(list.map((b) => String(b.id).toLowerCase())) };
      }
      return cache.ids;
    } catch (e) {
      log(`! builds file ${file}: ${e.message}; letting every build in`);
      return null;
    }
  };
  return (build) => {
    const id = String(build ?? '').toLowerCase();
    if (id === 'dev' || id === '') return allowDev;
    const allowed = ids();
    return allowed === null || allowed.has(id);
  };
}
