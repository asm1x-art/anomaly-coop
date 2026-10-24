import fs from 'node:fs';
import path from 'node:path';

// Everything the server keeps between runs, in one directory:
//   world.scop, world.scoc  the shared world: a save of the sim master's game (.scoc holds Lua state)
//   world.json              { owner, revision }: whose actor the save's actor is, bumped on every upload
//   leases.json             { block: player }: id blocks, they must outlive restarts like the world does
//   characters.json         { player: base64 record }: position, money... as the client sent it
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

  const characters = readJson('characters.json', {});

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
    writeWorld(owner, files) {
      const revision = (this.worldInfo()?.revision ?? 0) + 1;
      WORLD_FILES.forEach((f, i) => writeAtomic(f, files[i]));
      writeAtomic('world.json', JSON.stringify({ owner, revision }));
      return revision;
    },
  };
}
