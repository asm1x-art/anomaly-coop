import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { normalizeSettings } from './settings.js';

// Everything the server keeps between runs, in one directory:
//   saves/<revision>/       every world the server was given; the last one is the world now:
//     world.scop, world.scoc  a save of the sim master's game (.scoc holds Lua state)
//     characters.json         the players' records as they were then, to go back to with it
//     meta.json               { revision, owner, time, name, reason, who, from? }: owner is whose actor
//                             the save's actor is; reason: auto, quick, named, join, leave, exit, new,
//                             rollback (from: the save it went back to); who: the player it was for
//   leases.json             { block: player }: id blocks, they must outlive restarts like the world does
//   characters.json         { player: base64 record }: position, money... as the client sent it
//   settings.json           world settings and allowed factions (settings.js), set on the admin page
//   groups.json             [[leader, member...]]: groups of players, by character name
//   admin.json              { password } for the admin page, made up on the first start
export const WORLD_FILES = ['world.scop', 'world.scoc'];

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

  const saveFile = (revision, name) => path.join('saves', String(revision), name);
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
      for (const f of ['leases.json', 'characters.json', 'groups.json'])
        fs.rmSync(file(f), { force: true });
      saves.length = 0;
      characters = {};
    },

    loadGroups() {
      const groups = readJson('groups.json', []);
      return Array.isArray(groups) ? groups.filter((g) => Array.isArray(g) && g.length > 1) : [];
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

    // a new save, the world from now on, with the players' records as they are
    writeWorld(owner, files, { name = '', reason = 'auto', who = '', from } = {}) {
      const revision = (saves.at(-1)?.revision ?? 0) + 1;
      fs.mkdirSync(file(saveFile(revision, '')), { recursive: true });
      WORLD_FILES.forEach((f, i) => writeAtomic(saveFile(revision, f), files[i]));
      writeAtomic(saveFile(revision, 'characters.json'), JSON.stringify(characters, null, 1));
      const meta = { revision, owner, time: Date.now(), name, reason, who, ...(from ? { from } : {}) };
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
      return this.writeWorld(from.owner, this.readWorld(revision), { name: from.name, reason: 'rollback', from: revision });
    },
  };
}
