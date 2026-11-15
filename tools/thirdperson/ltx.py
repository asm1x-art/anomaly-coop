"""The weapon sections as the game sees them: vanilla's configs, overlaid by the repo's (a file the repo has replaces
vanilla's), read from system.ltx through its #includes, then the root mod_system_*.ltx (DLTX) in name order."""
import fnmatch
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_CONFIGS = os.path.normpath(os.path.join(HERE, '..', '..', 'gamedata', 'configs'))
PACK_FILES = os.path.normpath(os.path.join(HERE, '..', 'gra', 'pack_files.txt'))

SECTION = re.compile(r'^([!@]?)\[([^\]]+)\]\s*(?::\s*(.*))?$')


class Configs:
    def __init__(self, vanilla, repo=REPO_CONFIGS):
        pack = set()
        if os.path.isfile(PACK_FILES):
            pack = {l.strip().lower()[len('configs/'):].replace('/', os.sep) for l in open(PACK_FILES, encoding='utf-8')
                    if l.strip().lower().startswith('configs/')}
        self.files = {}  # relative path (lower case) -> (path, origin: van | repo | pack)
        for root in (vanilla, repo):
            for dp, _, fn in os.walk(root):
                for f in fn:
                    if f.lower().endswith('.ltx'):
                        rel = os.path.relpath(os.path.join(dp, f), root).lower()
                        origin = 'van' if root == vanilla else ('pack' if rel in pack else 'repo')
                        self.files[rel] = (os.path.join(dp, f), origin)
        self.secs = {}
        self.done = set()
        self.walk('system.ltx')
        for rel in sorted(self.files):
            if os.path.dirname(rel) == '' and rel.startswith('mod_system_'):
                self.walk(rel)

    def walk(self, rel):
        rel = rel.lower().replace('/', os.sep)
        if rel in self.done or rel not in self.files:
            return
        self.done.add(rel)
        path, origin = self.files[rel]
        txt = open(path, encoding='cp1251', errors='replace').read()
        # the includes before the file's own sections (near enough: they come first in the configs that matter)
        for m in re.finditer(r'^\s*#include\s+"([^"]+)"', txt, re.M):
            inc = os.path.normpath(os.path.join(os.path.dirname(rel), m.group(1))).lower()
            if '*' in inc:
                for r in sorted(self.files):
                    if fnmatch.fnmatch(r, inc):
                        self.walk(r)
            else:
                self.walk(inc)
        self.parse(txt, origin, rel)

    def parse(self, txt, origin, rel):
        cur = None
        for line in txt.splitlines():
            line = line.split(';')[0].strip()
            if not line:
                continue
            m = SECTION.match(line)
            if m:
                mod, name, par = m.group(1), m.group(2).strip().lower(), m.group(3)
                pars = [p.strip().lower() for p in par.split(',') if p.strip()] if par else []
                if mod and name in self.secs:  # DLTX override of an existing section
                    cur = self.secs[name]
                    cur['parents'] += [p for p in pars if p not in cur['parents']]
                    cur['dltx'].append(rel)
                elif mod == '!':  # override of a missing section: ignored by the game
                    cur = {'parents': [], 'kv': {}, 'src': rel, 'origin': origin, 'dltx': []}
                else:
                    cur = self.secs[name] = {'parents': pars, 'kv': {}, 'src': rel, 'origin': origin, 'dltx': []}
                continue
            if cur is None or line.startswith('#'):
                continue
            if '=' in line:
                k, v = line.split('=', 1); k = k.strip().lower(); v = v.strip()
                if k.startswith('!'):
                    cur['kv'].pop(k[1:], None)
                else:
                    cur['kv'][k] = v
            else:
                cur['kv'][line.lower()] = ''

    def get(self, name, key, seen=None):
        seen = seen or set()
        if name in seen or name not in self.secs:
            return None
        seen.add(name); s = self.secs[name]
        if key in s['kv']:
            return s['kv'][key]
        for p in reversed(s['parents']):
            v = self.get(p, key, seen)
            if v is not None:
                return v
        return None

    def weapons(self):
        """every section the engine makes a weapon of (class WP_*) that has a world model and a hold"""
        rows = []
        for name, s in self.secs.items():
            cls = self.get(name, 'class')
            if not cls or not cls.startswith('WP_'):
                continue
            vis, slot = self.get(name, 'visual'), self.get(name, 'animation_slot')
            if vis is None or slot is None:
                continue
            rows.append(dict(sec=name, cls=cls, slot=slot, pos=self.get(name, 'position'), ori=self.get(name, 'orientation'),
                             hd=self.get(name, 'hand_dependence'), vis=vis, origin=s['origin'], src=s['src'],
                             parent=s['parents'][:1], dltx=s['dltx']))
        return rows
