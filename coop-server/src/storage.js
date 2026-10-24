import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { normalizeSettings } from './settings.js';

// Everything the server keeps between runs, in one directory:
//   world.scop, world.scoc  the shared world: a save of the sim master's game (.scoc holds Lua state)
//   world.json              { owner, revision }: whose actor the save's actor is, bumped on every upload
//   leases.json             { block: player }: id blocks, they must outlive restarts like the world does
//   characters.json         { player: base64 record }: position, money... as the client sent it
//   settings.json           world settings and allowed factions (settings.js), set on the admin page
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
      const info = readJson('world.json', null);
      return info && WORLD_FILES.every((f) => fs.existsSync(file(f))) ? info : null;
    },
    readWorld() {
      return WORLD_FILES.map((f) => fs.readFileSync(file(f)));
    },
    // the world and everything that only makes sense with it: characters, id leases
    resetWorld() {
      for (const f of [...WORLD_FILES, 'world.json', 'leases.json', 'characters.json']) fs.rmSync(file(f), { force: true });
      characters = {};
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

    writeWorld(owner, files) {
      const revision = (this.worldInfo()?.revision ?? 0) + 1;
      WORLD_FILES.forEach((f, i) => writeAtomic(f, files[i]));
      writeAtomic('world.json', JSON.stringify({ owner, revision }));
      return revision;
    },
  };
}
