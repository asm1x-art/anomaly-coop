// Packs the co-op server (coop-server/) into one executable for Windows x64 and one for Linux x64:
//   node tools/server/build.mjs
// Out in _build/server/: anomaly-server.exe, anomaly-server and an example server.cfg (an existing one is kept).
//
// Node's single executable applications (SEA), the Node version that runs this script:
// 1. the server's ES modules become one CommonJS script (SEA runs one CommonJS file, its require() loads only
//    built-in modules), admin.html goes in as an asset (admin.js reads it with node:sea);
// 2. node --experimental-sea-config makes a blob of it; no code cache or snapshot, so one blob does for both systems;
// 3. postject (npx) puts the blob into a copy of node for each system: this node for its own system, the official
//    build of the same version from nodejs.org for the other one (downloaded once into _build/server/cache/,
//    checked against nodejs.org's SHASUMS256.txt).
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import zlib from 'node:zlib';
import { spawnSync } from 'node:child_process';
import { isBuiltin } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { EXAMPLE_CONFIG, CONFIG_FILE } from '../../coop-server/src/config.js';

const ROOT = path.resolve(fileURLToPath(import.meta.url), '../../..');
const SERVER = path.join(ROOT, 'coop-server');
const OUT = path.join(ROOT, '_build', 'server');
const OBJ = path.join(OUT, 'obj');
const CACHE = path.join(OUT, 'cache');
const VERSION = process.version; // v24.22.0
const POSTJECT = 'postject@1.0.0-alpha.6';
const FUSE = 'NODE_SEA_FUSE_fce680ab2cc467b6e072b8b5df1996b2';
const ASSETS = { 'admin.html': path.join(SERVER, 'src', 'admin.html') };
// file: what is built; dist: its node on nodejs.org
const TARGETS = [
  { file: 'anomaly-server.exe', platform: 'win32', arch: 'x64', dist: 'win-x64' },
  { file: 'anomaly-server', platform: 'linux', arch: 'x64', dist: 'linux-x64' },
];

const fail = (text) => {
  console.error(`build: ${text}`);
  process.exit(1);
};
const run = (cmd, args, options = {}) => {
  const r = spawnSync(cmd, args, { stdio: 'inherit', ...options });
  if (r.status !== 0) fail(`${[cmd, ...args].join(' ')}: ${r.error?.message ?? `exit code ${r.status}`}`);
};

// The server's modules as one CommonJS script. Only the forms our code uses are turned over; anything else stops
// the build with the file and line, rather than making a broken executable:
//   import x from 'node:m' / import { a, b as c } from './m.js' / import * as x from '...'
//   export function|async function|class|const|let f...   export { a, b as c }
//   import.meta.url (the source file's URL: admin.js reads admin.html by it when not packaged)
// Top-level await is fine in the entry (index.js), which runs in an async function.
function bundle(entry) {
  const modules = new Map(); // path -> factory source
  const visiting = new Set();
  const id = (file) => path.relative(SERVER, file).split(path.sep).join('/');

  const visit = (file) => {
    if (modules.has(file)) return;
    if (visiting.has(file)) fail(`${id(file)}: imports form a circle, not supported`);
    visiting.add(file);
    let src = fs.readFileSync(file, 'utf8');
    const where = (index) => `${id(file)}:${src.slice(0, index).split('\n').length}`;
    const exported = [];

    const load = (spec, at) => {
      if (spec.startsWith('.')) {
        const dep = path.resolve(path.dirname(file), spec);
        visit(dep);
        return `__module(${JSON.stringify(id(dep))})`;
      }
      if (isBuiltin(spec)) return `require(${JSON.stringify(spec)})`;
      return fail(`${where(at)}: '${spec}' is not a local file nor a Node module (no npm packages here)`);
    };
    src = src.replace(/^import\s+([\s\S]*?)\s+from\s+'([^']+)';?/gm, (all, clause, spec, at) => {
      const from = load(spec, at);
      if (/^\w+$/.test(clause)) {
        if (from.startsWith('__module')) fail(`${where(at)}: default imports of our own modules are not supported`);
        return `const ${clause} = ${from};`;
      }
      const star = clause.match(/^\*\s+as\s+(\w+)$/);
      if (star) return `const ${star[1]} = ${from};`;
      if (/^\{[\s\w,]*\}$/.test(clause)) return `const ${clause.replace(/(\w+)\s+as\s+(\w+)/g, '$1: $2')} = ${from};`;
      return fail(`${where(at)}: import form not supported: ${clause}`);
    });
    src = src.replace(/^export\s+((?:async\s+)?function\*?|class|const|let|var)\s+(\w+)/gm, (all, kind, name) => {
      exported.push([name, name]);
      return `${kind} ${name}`;
    });
    src = src.replace(/^export\s*\{([^}]*)\};?/gm, (all, list) => {
      for (const item of list.split(',').map((s) => s.trim()).filter(Boolean)) {
        const [local, as = local] = item.split(/\s+as\s+/);
        exported.push([as, local]);
      }
      return '';
    });
    src = src.replace(/\bimport\.meta\.url\b/g, JSON.stringify(pathToFileURL(file).href));
    for (const [pattern, what] of [[/^export\b/m, 'this export form'], [/^import\b/m, 'this import form'],
      [/\bimport\.meta\b/, 'import.meta other than .url'], [/\bimport\s*\(/, 'import()']]) {
      const m = src.match(pattern);
      if (m) fail(`${where(m.index)}: ${what} is not supported by the bundler (tools/server/build.mjs)`);
    }
    // exports read live, as in ES modules
    const getters = exported.map(([as, local]) => `get ${as}() { return ${local}; }`).join(', ');
    modules.set(file, `${src}\nreturn { ${getters} };`);
    visiting.delete(file);
  };

  visit(entry);
  const entrySrc = modules.get(entry).replace(/\nreturn \{ {2}\};$/, '');
  modules.delete(entry);
  return [
    "'use strict';",
    `// coop-server bundled by tools/server/build.mjs (${new Date().toISOString()}), don't edit`,
    'const __factories = {',
    ...[...modules].map(([file, body]) => `${JSON.stringify(id(file))}: () => {\n${body}\n},`),
    '};',
    'const __cache = {};',
    'const __module = (id) => (__cache[id] ??= __factories[id]());',
    '(async () => {',
    entrySrc,
    '})().catch((e) => {',
    '  console.error(e);',
    '  process.exit(1);',
    '});',
    '',
  ].join('\n');
}

async function download(url, file) {
  console.log(`downloading ${url}`);
  const res = await fetch(url);
  if (!res.ok) fail(`${url}: HTTP ${res.status}`);
  fs.writeFileSync(file + '.part', Buffer.from(await res.arrayBuffer()));
  fs.renameSync(file + '.part', file);
}

// a file from nodejs.org/dist/<version>/, kept in the cache and checked against SHASUMS256.txt
async function fromNodejs(name) {
  const sums = path.join(CACHE, `SHASUMS256-${VERSION}.txt`);
  if (!fs.existsSync(sums)) await download(`https://nodejs.org/dist/${VERSION}/SHASUMS256.txt`, sums);
  const expected = fs.readFileSync(sums, 'utf8').split('\n').map((l) => l.trim().split(/\s+/)).find(([, n]) => n === name)?.[0];
  if (!expected) fail(`${name} is not in nodejs.org's SHASUMS256.txt for ${VERSION}`);
  const file = path.join(CACHE, name.replaceAll('/', '-'));
  const hash = () => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
  if (!fs.existsSync(file) || hash() !== expected) {
    await download(`https://nodejs.org/dist/${VERSION}/${name}`, file);
    if (hash() !== expected) fail(`${name}: checksum does not match nodejs.org's`);
  }
  return file;
}

// a file out of a .tar.gz: 512-byte headers, each followed by its data padded to 512
function untarFile(tgz, wanted) {
  const tar = zlib.gunzipSync(fs.readFileSync(tgz));
  for (let at = 0; at + 512 <= tar.length;) {
    const header = tar.subarray(at, at + 512);
    if (header.every((b) => b === 0)) break;
    const field = (start, length) => header.subarray(start, start + length).toString('utf8').replace(/\0.*$/s, '');
    const name = [field(345, 155), field(0, 100)].filter(Boolean).join('/'); // ustar prefix + name
    const size = parseInt(field(124, 12).trim() || '0', 8);
    if (name === wanted) return tar.subarray(at + 512, at + 512 + size);
    at += 512 + Math.ceil(size / 512) * 512;
  }
  return fail(`${wanted} not found in ${tgz}`);
}

// node for a target: this one when it is for that system, else the official build of the same version
async function nodeFor(target) {
  if (process.platform === target.platform && process.arch === target.arch) return process.execPath;
  if (target.platform === 'win32') return fromNodejs(`${target.dist}/node.exe`);
  const dir = `node-${VERSION}-${target.dist}`;
  const binary = path.join(CACHE, `${dir}-node`);
  if (!fs.existsSync(binary)) fs.writeFileSync(binary, untarFile(await fromNodejs(`${dir}.tar.gz`), `${dir}/bin/node`));
  return binary;
}

fs.mkdirSync(OBJ, { recursive: true });
fs.mkdirSync(CACHE, { recursive: true });

console.log(`bundling ${path.relative(ROOT, SERVER)} (node ${VERSION})`);
const script = path.join(OBJ, 'server.cjs');
fs.writeFileSync(script, bundle(path.join(SERVER, 'index.js')));
run(process.execPath, ['--check', script]);

const blob = path.join(OBJ, 'sea.blob');
const seaConfig = path.join(OBJ, 'sea-config.json');
fs.writeFileSync(seaConfig, JSON.stringify({
  main: script, output: blob, disableExperimentalSEAWarning: true, useSnapshot: false, useCodeCache: false, assets: ASSETS,
}, null, 2));
run(process.execPath, ['--experimental-sea-config', seaConfig]);

for (const target of TARGETS) {
  const exe = path.join(OUT, target.file);
  console.log(`making ${path.relative(ROOT, exe)}`);
  fs.rmSync(exe, { force: true });
  fs.copyFileSync(await nodeFor(target), exe);
  // node.exe's signature no longer matches once the blob is in: postject warns, Windows runs it unsigned.
  // A command line through the shell: npx is npx.cmd on Windows; nothing here has spaces.
  run(`npx --yes ${POSTJECT} ${target.file} NODE_SEA_BLOB ${path.relative(OUT, blob)} --sentinel-fuse ${FUSE}`, [],
    { cwd: OUT, shell: true });
  fs.chmodSync(exe, 0o755);
}

const cfg = path.join(OUT, CONFIG_FILE);
if (fs.existsSync(cfg)) console.log(`kept the existing ${path.relative(ROOT, cfg)}`);
else fs.writeFileSync(cfg, EXAMPLE_CONFIG);
console.log(`done: ${path.relative(ROOT, OUT)}`);
for (const f of [...TARGETS.map((t) => t.file), CONFIG_FILE])
  console.log(`  ${f}  ${(fs.statSync(path.join(OUT, f)).size / 1024 / 1024).toFixed(1)} MB`);
