// The world's news journal: the important news every player has been told in the world — Cooling began or
// ended, a surge or psi storm is coming or over, a raid's events, the bar's and the shelter's — kept so the
// launchers can show them (admin.js GET /api/public/status) after the fact. Nothing from the timetables: only
// what the game speaking for the world (the host, else the sim master) has already announced.
//
// A game sends one as the fact "news" (protocol.js FACT): "<type>\t<world time>\t<text>". It is not a fact of the
// world: neither kept with the facts nor relayed. Only the types listed in server.cfg news_types are kept (the
// small news — trade, chatter — are not), the last news_keep of them, in data/news.json, so a restart keeps
// them; a world reset drops them (the news of an old world).

export const NEWS_FACT = 'news';
export const DEFAULT_NEWS_TYPES = ['cooling', 'cooling_end', 'surge', 'surge_end', 'psi', 'psi_end', 'raid', 'bar', 'shelter',
  'zone_event', 'zone_event_end'];
const TEXT_MAX = 400;
const WORLD_MAX = 40;

// "type\tworld\ttext" -> { type, world, text } or null
export function parseNews(value) {
  const parts = String(value ?? '').split('\t');
  if (parts.length < 3) return null;
  const type = parts[0].trim().toLowerCase();
  const world = parts[1].trim().slice(0, WORLD_MAX);
  const text = parts.slice(2).join(' ').replace(/\s+/g, ' ').trim().slice(0, TEXT_MAX);
  if (!/^[a-z][a-z0-9_]{0,31}$/.test(type) || !text) return null;
  return { type, world, text };
}

// load() -> the saved list or null; save(list)
export function createNews({ load, save, types = DEFAULT_NEWS_TYPES, keep = 50, now = Date.now }) {
  const allowed = new Set(types.map((t) => t.trim().toLowerCase()).filter(Boolean));
  let list = Array.isArray(load()) ? load() : [];
  let next = list.reduce((m, e) => Math.max(m, e.id ?? 0), 0) + 1;
  return {
    // a news a game sent; the entry kept, or null (not important, malformed, the same as one just kept)
    add(value, from) {
      if (keep <= 0) return null;
      const n = parseNews(value);
      if (!n || !allowed.has(n.type)) return null;
      // a new master may tell again what the last one told
      if (list.slice(-20).some((e) => e.type === n.type && e.text === n.text && e.world === n.world)) return null;
      const entry = { id: next++, ...n, time: now(), from: from ?? '' };
      list.push(entry);
      if (list.length > keep) list = list.slice(-keep);
      save(list);
      return entry;
    },
    // oldest first
    list: () => list.slice(),
    clear() {
      list = [];
      save(list);
    },
  };
}
