import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { normalizeSettings } from './settings.js';

// Everything the server keeps between runs, in one directory:
//   saves/<revision>/       every world the server was given; the last one is the world now:
//     world.scop, world.scoc  a save of the sim master's game (.scoc holds Lua state)
//     characters.json         the players' records as they were then, to go back to with it
//     meta.json               { revision, owner, time, name, reason, who, from?, clock? }: owner is whose actor
//                             the save's actor is; reason: auto, quick, named, join, leave, exit, new,
//                             rollback (from: the save it went back to); who: the player it was for; clock:
//                             the world's game time (ms) when it came, for a rollback to take the clock back to
//   leases.json             { block: player }: id blocks, they must outlive restarts like the world does
//   characters.json         { player: base64 record }: position, money... as the client sent it
//   facts.json              { key: value }: facts about the world the games report (protocol.js FACT); saves keep
//                            a copy, a rollback brings it back
//   logs/<hex name>/<file>   the logs and crash dumps a player's game sent, the last MAX_LOGS (not the world's:
//                            a reset keeps them)
//   crashes/<hex name>/<id>/ a crash report the launcher sent on the player's consent (admin.js POST /crash-report):
//                            report.json { player, time, code, meaning, comment, build_id, release, launcher, files,
//                            skipped, received, from } and the files unpacked; the last MAX_CRASHES per player, a
//                            reset keeps them
//   progress/<hex name>.bin  a player's own progress (tasks, story, rank...) as the client sent it; saves keep a
//                            copy of the folder (saves/<revision>/progress/), a rollback brings it back
//   settings.json           world settings and allowed factions (settings.js), set on the admin page
//   clock.json              { game, factor, epoch }: the world's clock (clock.js), gone with the world
//   groups.json             [{ members: [leader, member...], story }]: groups of players, by character name
//   admin.json              { password } for the admin page, made up on the first start
//   personal/<hex name>/<id>/ a character's own save: snapshot.bin (as its game sent it, protocol.js SNAPSHOT) and
//                            meta.json { id, time, name, by, group }: group, the members' names of a group's save
//                            (the same id in every member's folder); personal_next.json, the next id
//   personal/<hex name>/things.bin  the things of a save the character was put back to, for its next download
//                            (then the TAKEN entries since that save, for the things to go back where they were)
//   personal/<hex name>/taken.jsonl  where the character took each thing from, a { t, m: base64 TAKEN } line each;
//                            meta.json of an exit save (made when the player leaves) has exit: true, one per character;
//                            of an autosave (protocol.js AUTO_SAVE_NAME) auto: true, one per character
//   journal.jsonl           the world changes since the last save (server.js), a { t, m: base64 } line each, so a
//                            server started again still has them
//   news.json               [{ id, type, world, text, time, from }]: the world's important news, the last ones
//                            (news.js), for the launchers; gone with the world
//   clients.json            { id: name }: every client id given out, so ids go on growing across runs (the journal's
//                            changes are by id)
export const WORLD_FILES = ['world.scop', 'world.scoc'];
export const MAX_LOGS = 50; // per player
export const MAX_CRASHES = 30; // crash reports per player
export const MAX_TAKEN = 2000; // where a character took its things from, per character

export function openStorage(dir) {
  fs.mkdirSync(dir, { recursive: true });
  const file = (name) => path.join(dir, name);

  const readJson = (name, fallback) => {
    try {
      return JSON.parse(fs.readFileSync(file(name), 'utf8'));
    } catch {
      return fallback;
    }
  };
  // write-then-rename, so a crash never leaves half a file behind
  const writeAtomic = (name, data) => {
    fs.writeFileSync(file(name) + '.tmp', data);
    fs.renameSync(file(name) + '.tmp', file(name));
  };

  let characters = readJson('characters.json', {});
  let facts = readJson('facts.json', {});

  const saveFile = (revision, name) => path.join('saves', String(revision), name);
  const playerDir = (name) => Buffer.from(name, 'utf8').toString('hex');
  const text2taken = (text) => text.split('\n').filter(Boolean).flatMap((line) => {
    try {
      const { t, m } = JSON.parse(line);
      return [{ time: t, message: Buffer.from(m, 'base64') }];
    } catch {
      return []; // a line cut short by a crash
    }
  });
  // a file name from a client: no paths, nothing odd
  const safeName = (file) => String(file).replace(/^.*[\\/]/, '').replace(/[^\w.-]/g, '_').slice(0, 120) || 'unnamed';
  const progressFile = (name) => path.join('progress', Buffer.from(name, 'utf8').toString('hex') + '.bin');
  const copyProgress = (from, to) => {
    fs.rmSync(file(to), { recursive: true, force: true });
    if (fs.existsSync(file(from))) fs.cpSync(file(from), file(to), { recursive: true });
  };
  // a world kept the old way, in the directory itself, becomes the first save
  const old = readJson('world.json', null);
  if (old && WORLD_FILES.every((f) => fs.existsSync(file(f)))) {
    fs.mkdirSync(file(saveFile(old.revision, '')), { recursive: true });
    for (const f of WORLD_FILES) fs.renameSync(file(f), file(saveFile(old.revision, f)));
    writeAtomic(saveFile(old.revision, 'characters.json'), JSON.stringify(characters, null, 1));
    writeAtomic(saveFile(old.revision, 'meta.json'), JSON.stringify(
      { revision: old.revision, owner: old.owner, time: Date.now(), name: '', reason: 'auto', who: '' }));
    fs.rmSync(file('world.json'));
  }
  // oldest first; a save counts once its meta.json, written last, is there
  const saves = fs.existsSync(file('saves')) ? fs.readdirSync(file('saves'))
    .map((d) => readJson(path.join('saves', d, 'meta.json'), null))
    .filter((m) => m && WORLD_FILES.every((f) => fs.existsSync(file(saveFile(m.revision, f)))))
    .sort((a, b) => a.revision - b.revision) : [];

  return {
    loadLeases() {
      return new Map(Object.entries(readJson('leases.json', {})).map(([block, name]) => [Number(block), name]));
    },
    saveLeases(leases) {
      writeAtomic('leases.json', JSON.stringify(Object.fromEntries(leases), null, 1));
    },

    character(name) {
      return characters[name] ? Buffer.from(characters[name], 'base64') : null;
    },
    saveCharacter(name, record) {
      characters[name] = record.toString('base64');
      writeAtomic('characters.json', JSON.stringify(characters, null, 1));
    },

    progress(name) {
      try {
        return fs.readFileSync(file(progressFile(name)));
      } catch {
        return null;
      }
    },
    saveProgress(name, data) {
      fs.mkdirSync(file('progress'), { recursive: true });
      writeAtomic(progressFile(name), data);
    },

    saveLog(name, fileName, data) {
      const dir = path.join('logs', playerDir(name));
      fs.mkdirSync(file(dir), { recursive: true });
      writeAtomic(path.join(dir, safeName(fileName)), data);
      const kept = fs.readdirSync(file(dir))
        .map((f) => ({ f, time: fs.statSync(file(path.join(dir, f))).mtimeMs }))
        .sort((a, b) => b.time - a.time);
      for (const { f } of kept.slice(MAX_LOGS)) fs.rmSync(file(path.join(dir, f)), { force: true });
    },
    // [{ player, file, size, time }], newest first
    logs() {
      if (!fs.existsSync(file('logs'))) return [];
      const list = [];
      for (const dir of fs.readdirSync(file('logs'))) {
        const player = Buffer.from(dir, 'hex').toString('utf8');
        for (const f of fs.readdirSync(file(path.join('logs', dir)))) {
          const st = fs.statSync(file(path.join('logs', dir, f)));
          list.push({ player, file: f, size: st.size, time: st.mtimeMs });
        }
      }
      return list.sort((a, b) => b.time - a.time);
    },
    logFile(name, f) {
      try {
        return fs.readFileSync(file(path.join('logs', playerDir(name), safeName(f))));
      } catch {
        return null;
      }
    },

    loadNews: () => readJson('news.json', null),
    saveNews: (list) => writeAtomic('news.json', JSON.stringify(list)),

    // id (the time it came, "2026-11-06_17-33-41" UTC, with -2, -3... when taken)
    saveCrash(name, report, files) {
      const dir = path.join('crashes', playerDir(name));
      fs.mkdirSync(file(dir), { recursive: true });
      const stamp = new Date(report.received).toISOString().slice(0, 19).replace('T', '_').replace(/:/g, '-');
      let id = stamp;
      for (let n = 2; fs.existsSync(file(path.join(dir, id))); n++) id = `${stamp}-${n}`;
      const at = path.join(dir, id);
      fs.mkdirSync(file(at + '.tmp'), { recursive: true });
      const names = [];
      for (const f of files) {
        let n = safeName(f.name);
        while (names.includes(n) || n === 'report.json') n = '_' + n;
        names.push(n);
        fs.writeFileSync(file(path.join(at + '.tmp', n)), f.data);
      }
      const meta = { ...report, files: report.files.map((f, i) => ({ ...f, name: names[i] })) };
      fs.writeFileSync(file(path.join(at + '.tmp', 'report.json')), JSON.stringify(meta, null, 1));
      fs.renameSync(file(at + '.tmp'), file(at));
      const kept = fs.readdirSync(file(dir)).filter((d) => !d.endsWith('.tmp')).sort().reverse();
      for (const old of kept.slice(MAX_CRASHES)) fs.rmSync(file(path.join(dir, old)), { recursive: true, force: true });
      return id;
    },
    // [{ id, player, time, code, meaning, comment, ..., files }], newest first
    crashes() {
      if (!fs.existsSync(file('crashes'))) return [];
      const list = [];
      for (const dir of fs.readdirSync(file('crashes'))) {
        for (const id of fs.readdirSync(file(path.join('crashes', dir)))) {
          if (id.endsWith('.tmp')) continue;
          try {
            const meta = JSON.parse(fs.readFileSync(file(path.join('crashes', dir, id, 'report.json')), 'utf8'));
            list.push({ ...meta, id, player: Buffer.from(dir, 'hex').toString('utf8') });
          } catch {
            // half written or not a report
          }
        }
      }
      return list.sort((a, b) => b.received - a.received);
    },
    crashFile(name, id, f) {
      try {
        return fs.readFileSync(file(path.join('crashes', playerDir(name), safeName(id), safeName(f))));
      } catch {
        return null;
      }
    },

    facts: () => ({ ...facts }),
    // true when it changed
    setFact(key, value) {
      if ((facts[key] ?? '') === value) return false;
      if (value) facts[key] = value;
      else delete facts[key];
      writeAtomic('facts.json', JSON.stringify(facts, null, 1));
      return true;
    },

    worldInfo() {
      const last = saves.at(-1);
      return last ? { owner: last.owner, revision: last.revision } : null;
    },
    readWorld(revision = saves.at(-1).revision) {
      return WORLD_FILES.map((f) => fs.readFileSync(file(saveFile(revision, f))));
    },
    saves: () => saves.slice(),
    // the last save that went back to an older one: games running anything from before it run an old world
    lastRollback: () => saves.findLast((m) => m.reason === 'rollback')?.revision ?? 0,
    // the world and everything that only makes sense with it: saves, characters, id leases, groups
    resetWorld() {
      fs.rmSync(file('saves'), { recursive: true, force: true });
      for (const f of ['leases.json', 'characters.json', 'groups.json', 'facts.json', 'clock.json', 'journal.jsonl'])
        fs.rmSync(file(f), { force: true });
      facts = {};
      fs.rmSync(file('progress'), { recursive: true, force: true });
      fs.rmSync(file('personal'), { recursive: true, force: true }); // the characters' saves are of this world
      fs.rmSync(file('personal_next.json'), { force: true });
      saves.length = 0;
      characters = {};
    },

    loadClock: () => readJson('clock.json', null),
    saveClock(clock) {
      if (clock) writeAtomic('clock.json', JSON.stringify(clock));
      else fs.rmSync(file('clock.json'), { force: true });
    },

    // [{ time, message }], oldest first
    journal() {
      let text = '';
      try {
        text = fs.readFileSync(file('journal.jsonl'), 'utf8');
      } catch {
        return [];
      }
      return text.split('\n').filter(Boolean).flatMap((line) => {
        try {
          const { t, m } = JSON.parse(line);
          return [{ time: t, message: Buffer.from(m, 'base64') }];
        } catch {
          return []; // a line cut short by a crash
        }
      });
    },
    appendJournal({ time, message }) {
      fs.appendFileSync(file('journal.jsonl'), JSON.stringify({ t: time, m: message.toString('base64') }) + '\n');
    },
    saveJournal(entries) {
      writeAtomic('journal.jsonl', entries.map(({ time, message }) =>
        JSON.stringify({ t: time, m: message.toString('base64') }) + '\n').join(''));
    },
    clientNames() {
      return new Map(Object.entries(readJson('clients.json', {})).map(([id, name]) => [Number(id), name]));
    },
    saveClientNames(names) {
      writeAtomic('clients.json', JSON.stringify(Object.fromEntries(names)));
    },

    nextCharacterSaveId() {
      const id = readJson('personal_next.json', 1);
      writeAtomic('personal_next.json', JSON.stringify(id + 1));
      return id;
    },
    saveCharacterSave(name, meta, snapshot) {
      const dir = path.join('personal', playerDir(name), String(meta.id));
      fs.mkdirSync(file(dir), { recursive: true });
      writeAtomic(path.join(dir, 'snapshot.bin'), snapshot);
      writeAtomic(path.join(dir, 'meta.json'), JSON.stringify(meta));
    },
    // newest first; a save counts once its meta.json, written last, is there
    characterSaves(name) {
      const dir = path.join('personal', playerDir(name));
      if (!fs.existsSync(file(dir))) return [];
      return fs.readdirSync(file(dir)).filter((d) => /^\d+$/.test(d))
        .map((d) => readJson(path.join(dir, d, 'meta.json'), null)).filter(Boolean).sort((a, b) => b.id - a.id);
    },
    // { meta, snapshot } or null
    characterSave(name, id) {
      const dir = path.join('personal', playerDir(name), String(id));
      const meta = readJson(path.join(dir, 'meta.json'), null);
      if (!meta) return null;
      try {
        return { meta, snapshot: fs.readFileSync(file(path.join(dir, 'snapshot.bin'))) };
      } catch {
        return null;
      }
    },
    things(name) {
      try {
        return fs.readFileSync(file(path.join('personal', playerDir(name), 'things.bin')));
      } catch {
        return null;
      }
    },
    // null: given, none left
    setThings(name, data) {
      const dir = path.join('personal', playerDir(name));
      if (!data) return fs.rmSync(file(path.join(dir, 'things.bin')), { force: true });
      fs.mkdirSync(file(dir), { recursive: true });
      writeAtomic(path.join(dir, 'things.bin'), data);
    },
    deleteCharacterSave(name, id) {
      fs.rmSync(file(path.join('personal', playerDir(name), String(id))), { recursive: true, force: true });
    },
    // where the character took each thing from (protocol.js TAKEN): [{ time, message }], oldest first, the last
    // MAX_TAKEN kept
    taken(name) {
      try {
        return text2taken(fs.readFileSync(file(path.join('personal', playerDir(name), 'taken.jsonl')), 'utf8'));
      } catch {
        return [];
      }
    },
    appendTaken(name, { time, message }) {
      const dir = path.join('personal', playerDir(name));
      fs.mkdirSync(file(dir), { recursive: true });
      const at = path.join(dir, 'taken.jsonl');
      const line = (e) => JSON.stringify({ t: e.time, m: e.message.toString('base64') }) + '\n';
      fs.appendFileSync(file(at), line({ time, message }));
      if (fs.statSync(file(at)).size < MAX_TAKEN * 2 * 150) return; // ~100 bytes a line: cut now and then
      const all = text2taken(fs.readFileSync(file(at), 'utf8'));
      if (all.length > MAX_TAKEN) writeAtomic(at, all.slice(-MAX_TAKEN).map(line).join(''));
    },

    // [{ members: [leader, ...], story }]; a group was a plain list of names before
    loadGroups() {
      const groups = readJson('groups.json', []);
      if (!Array.isArray(groups)) return [];
      return groups.map((g) => (Array.isArray(g) ? { members: g, story: false } : g))
        .filter((g) => Array.isArray(g?.members) && g.members.length > 1)
        .map((g) => ({ members: g.members, story: g.story === true }));
    },
    saveGroups(groups) {
      writeAtomic('groups.json', JSON.stringify(groups, null, 1));
    },

    settings() {
      return normalizeSettings(readJson('settings.json', {}));
    },
    saveSettings(settings) {
      writeAtomic('settings.json', JSON.stringify(normalizeSettings(settings), null, 1));
    },

    // { password, created }: created is true when it was made up just now
    adminPassword() {
      const saved = readJson('admin.json', null);
      if (saved?.password) return { password: saved.password, created: false };
      const password = crypto.randomBytes(9).toString('base64url');
      writeAtomic('admin.json', JSON.stringify({ password }));
      return { password, created: true };
    },
    // a save that is not the world (not the newest) gone; true when it was there
    deleteSave(revision) {
      const at = saves.findIndex((m) => m.revision === revision);
      if (at === -1 || at === saves.length - 1) return false;
      fs.rmSync(file(saveFile(revision, '')), { recursive: true, force: true });
      saves.splice(at, 1);
      return true;
    },
    // what the admins did from the in-game window (server.js journalAdmin), oldest first: { time, who, text }
    adminLog() {
      try {
        return fs.readFileSync(file('admin_log.jsonl'), 'utf8').split('\n').filter(Boolean).flatMap((l) => {
          try {
            return [JSON.parse(l)];
          } catch {
            return [];
          }
        });
      } catch {
        return [];
      }
    },
    appendAdminLog(entry) {
      fs.appendFileSync(file('admin_log.jsonl'), JSON.stringify(entry) + '\n');
    },
    // a random salt for the admin window's tokens (server.js adminToken), made up once; outlives the world
    adminSalt() {
      const saved = readJson('admin_salt.json', null);
      if (saved?.salt) return saved.salt;
      const salt = crypto.randomBytes(16).toString('hex');
      writeAtomic('admin_salt.json', JSON.stringify({ salt }));
      return salt;
    },

    // a new save, the world from now on, with the players' records as they are
    // (empty: an autosave of a world nobody was in, server.js keeps only the newest of a run of them)
    writeWorld(owner, files, { name = '', reason = 'auto', who = '', from, clock, empty } = {}) {
      const revision = (saves.at(-1)?.revision ?? 0) + 1;
      fs.mkdirSync(file(saveFile(revision, '')), { recursive: true });
      WORLD_FILES.forEach((f, i) => writeAtomic(saveFile(revision, f), files[i]));
      writeAtomic(saveFile(revision, 'characters.json'), JSON.stringify(characters, null, 1));
      writeAtomic(saveFile(revision, 'facts.json'), JSON.stringify(facts, null, 1));
      copyProgress('progress', saveFile(revision, 'progress'));
      const meta = { revision, owner, time: Date.now(), name, reason, who, ...(from ? { from } : {}), ...(clock ? { clock } : {}),
        ...(empty ? { empty } : {}) };
      writeAtomic(saveFile(revision, 'meta.json'), JSON.stringify(meta));
      saves.push(meta);
      return revision;
    },
    // the world as it was in an older save, as a new one; the players' records go back with it
    rollback(revision) {
      const from = saves.find((m) => m.revision === revision);
      if (!from) return 0;
      characters = readJson(saveFile(revision, 'characters.json'), {});
      writeAtomic('characters.json', JSON.stringify(characters, null, 1));
      facts = readJson(saveFile(revision, 'facts.json'), {});
      writeAtomic('facts.json', JSON.stringify(facts, null, 1));
      copyProgress(saveFile(revision, 'progress'), 'progress');
      return this.writeWorld(from.owner, this.readWorld(revision),
        { name: from.name, reason: 'rollback', from: revision, clock: from.clock });
    },
  };
}
