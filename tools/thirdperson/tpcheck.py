r"""Offline check of weapons held in third person (stalkers, the other player's stand-in): does each gun's world model
sit in the hands? The engine hangs it on the right index finger, turned towards the left hand (CWeapon::UpdateXForm,
coop_puppet.cpp hand_xform), then moves it by the section's `position` / `orientation`. Those numbers belong to the
model: a section that keeps another model's numbers (a pack gun with vanilla's) holds its gun under or apart from
the hands. This poses the actor's skeleton with its own animations, places every gun the same way and measures.

Needs: python 3 with numpy and Pillow; vanilla's configs and meshes unpacked (X:\Anomaly\tools\converter.exe -unpack
-xdb <db> -dir <dir>; configs.db0 for the configs; meshes_actors.db0, meshes_weapons.db0, meshes_dynamics.db0 for the
meshes); the weapon pack's meshes are read from its mods (tools\gra\build_pack.py, X:\GRA2.5\MO2).

  tpcheck.py [--configs DIR] [--meshes DIR] [--out DIR] <command>
    --configs   vanilla's unpacked configs (the folder with system.ltx), or env TP_CONFIGS
    --meshes    vanilla's unpacked gamedata (the folder with meshes\), or env TP_MESHES
    --out       where the json and pictures go (the current folder by default)
  commands:
    scan                       every weapon section with a world model: gaps palm-gun, the suspects grouped by model
                               family and offsets (fit.json, bad.json); the repo's gamedata as it is now
    solve <sec> ...            new position for each (orientation kept): the left palm under the fore-end at vanilla's
                               height (fit.SUPPORT), the right one at the grip. Check the result on a picture
    sheet [--zoom] <name> <sec>[=pos;ori] ...   pictures (<name>_0.png, ...): standing, two views a section;
                               =pos;ori tries other numbers
    poses <sec>[=pos;ori]      one section in every hold: standing, walking, running, aiming, sprinting

  e.g. set TP_CONFIGS=H:\stalker-test\anomaly-unpacked\configs & set TP_MESHES=<dir with meshes\>
       tpcheck.py --out %TEMP%\tp scan
       tpcheck.py --out %TEMP%\tp solve wpn_lr300
       tpcheck.py --out %TEMP%\tp --zoom sheet lr300 wpn_ak74 wpn_lr300 "wpn_lr300=-0.026, -0.195, 0;0, 0, 0"
  The numbers are a guide, the pictures decide: a fore grip, a torch or a drum under the fore-end reads as the palm
  inside the gun; a bullpup (AUG) can't fit a rifle's hold whatever its position. Vanilla's own rifles (wpn_ak74)
  are the reference of what looks right. Fixes go into gamedata\configs\mod_system_gra_fixes.ltx as DLTX; a section
  some later mod_system_* file sets (scan shows the value the game ends up with) into the last one,
  mod_system_zzzzzzzzzzzz_gra_aim_fixes.ltx.
"""
import argparse
import collections
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

import fit as fitmod
import ltx
import render
import rig as rigmod

SKIP_CLASSES = ('WP_SCOPE', 'WP_KNIFE', 'WP_BINOC', 'WP_SILEN', 'WP_GLAUN')


def family(vis):
    return os.path.basename(os.path.dirname(vis.replace('\\', '/')))


def cmd_scan(a, cfg, fitter):
    rows = [r for r in cfg.weapons() if r['cls'] not in SKIP_CLASSES]
    cache, out, missing = {}, [], 0
    for r in rows:
        k = (r['vis'], r['pos'], r['ori'], r['slot'])
        if k not in cache:
            try:
                cache[k] = fitter.fit(r['vis'], r['pos'], r['ori'], int(r['slot']))
            except Exception as e:  # a broken or odd model: say so, go on
                print('error', r['sec'], e, file=sys.stderr); cache[k] = None
        if not cache[k]:
            missing += 1
            continue
        out.append(dict(r, mesh=cache[k][0], fit=cache[k][1]))
    json.dump(out, open(os.path.join(a.out, 'fit.json'), 'w'), indent=0)
    groups = collections.defaultdict(list)
    for o in out:
        why = fitmod.bad(o['fit'], o['slot'])
        if why:
            gl, gr = fitmod.gaps(o['fit'])
            groups[(o['mesh'], family(o['vis']), o['slot'], o['pos'], o['ori'])].append(
                (o['sec'], gl, gr, o['fit']['aim_1'][2], o['origin'], why))
    print(f'{len(out)} sections measured ({len(cache)} model/offset pairs), {missing} without a model found')
    print(f"{sum(len(v) for v in groups.values())} off the hands, in {len(groups)} groups (mesh, family, slot, position, orientation):")
    h = lambda x: ' air' if x is None else f'{100 * x:4.1f}'
    for k, v in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][3] or '')):
        print(f"  {k[0]:4} {k[1]:26} slot {k[2]:2} pos [{k[3]}] ori [{k[4]}]  {len(v):3} sections  "
              f"gap cm L {100 * max(x[1] for x in v):4.1f} R {100 * max(x[2] for x in v):4.1f} support {h(v[0][3])}  "
              f"config {v[0][4]}: {v[0][5]}  e.g. {v[0][0]}")
    json.dump({'|'.join(k): [x[0] for x in v] for k, v in groups.items()}, open(os.path.join(a.out, 'bad.json'), 'w'), indent=1)


def fmt_vec(v):
    return ', '.join(f'{x:.3f}'.rstrip('0').rstrip('.') if abs(x) > 1e-9 else '0' for x in v)


def cmd_solve(a, cfg, fitter):
    """moves each gun (its position only, its orientation kept) so the left palm is under the fore-end at vanilla's
    height and the right palm stays at the grip"""
    rows = {r['sec']: r for r in cfg.weapons()}
    for sec in a.args:
        r = rows[sec]
        V, _ = fitter.verts(r['vis'])
        if len(V) > 6000:
            V = V[np.linspace(0, len(V) - 1, 6000).astype(int)]
        holds = {k: v for k, v in fitter.holds(int(r['slot'])).items() if k in ('aim_0', 'aim_1')}
        p0 = rigmod.vec(r['pos'])
        best = None
        for dz in np.arange(-0.12, 0.1201, 0.01):
            for dy in np.arange(-0.12, 0.1201, 0.005):
                pos = [p0[0], p0[1] + dy, p0[2] + dz]
                res = fitmod.measure(V, rigmod.offset(fmt_vec(pos), r['ori']), holds)
                cost = 0
                for gl, gr, h in res.values():
                    cost += 1 if h is None else abs(h - fitmod.SUPPORT)
                    cost += 2 * max(0, gr - 0.025)
                cost += 0.2 * abs(dz)
                if best is None or cost < best[0]:
                    best = (cost, pos, res)
        cur = fitmod.measure(V, rigmod.offset(r['pos'], r['ori']), holds)['aim_1']
        new = best[2]['aim_1']
        h = lambda x: '  air' if x is None else f'{100 * x:5.1f}'
        print(f"{sec}: [{r['pos']}] -> [{fmt_vec(best[1])}]  (orientation {r['ori']})  "
              f"support {h(cur[2])} -> {h(new[2])} cm, right gap {100 * cur[1]:.1f} -> {100 * new[1]:.1f} cm")


def parse_items(args, rows):
    items = []
    for x in args:
        sec, pos, ori = x, None, None
        if '=' in x:
            sec, rest = x.split('=', 1); pos, ori = rest.split(';')
        r = rows[sec]
        items.append((sec, r, pos or r['pos'], ori or r['ori']))
    return items


def label(img, text):
    ImageDraw.Draw(img).text((4, img.height - 14), text, fill=(200, 0, 0))
    return img


def tile(cells, cols):
    w = max(c.width for c in cells); h = max(c.height for c in cells)
    img = Image.new('RGB', (cols * w, ((len(cells) + cols - 1) // cols) * h), (255, 255, 255))
    for i, c in enumerate(cells):
        img.paste(c, ((i % cols) * w, (i // cols) * h))
    return img


def cmd_sheet(a, cfg, painter):
    rows = {r['sec']: r for r in cfg.weapons()}
    name, items = a.args[0], parse_items(a.args[1:], rows)
    for i in range(0, len(items), 8):
        cells = []
        for sec, r, pos, ori in items[i:i + 8]:
            views = [render.RIGHT, render.LEFT] if a.zoom else [render.view(45), render.RIGHT]
            img = painter.shot(f"norm_torso_{r['slot']}_aim_1", 'norm_idle_0', r['vis'], pos, ori, views,
                               span=0.5 if a.zoom else 0.8)
            cells.append(label(img, f"{sec} slot {r['slot']} pos {pos} ori {ori} [{r['origin']}]"))
        out = os.path.join(a.out, f'{name}_{i // 8}.png')
        tile(cells, 2).save(out); print(out)


POSES = [('stand (aim_1)', '{b}_torso_{s}_aim_1', '{b}_idle_0'), ('walk (aim_2)', '{b}_torso_{s}_aim_2', '{b}_walk_fwd_0'),
         ('run (aim_3)', '{b}_torso_{s}_aim_3', '{b}_run_fwd_0'), ('aim (aim_0)', '{b}_torso_{s}_aim_0', '{b}_idle_0'),
         ('sprint (escape_0)', 'norm_torso_{s}_escape_0', 'norm_escape_00')]


def cmd_poses(a, cfg, painter):
    rows = {r['sec']: r for r in cfg.weapons()}
    for sec, r, pos, ori in parse_items(a.args, rows):
        cells = []
        for title, t, l in POSES:
            t = t.format(b='norm', s=r['slot']); l = l.format(b='norm')
            if t in painter.rig.M and l in painter.rig.M:
                cells.append(label(painter.shot(t, l, r['vis'], pos, ori, [render.view(45), render.ABOVE]), f'{sec} {title}'))
        out = os.path.join(a.out, f'{sec}_poses.png')
        tile(cells, 1).save(out); print(out)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--configs', default=os.environ.get('TP_CONFIGS'))
    p.add_argument('--meshes', default=os.environ.get('TP_MESHES'))
    p.add_argument('--out', default='.')
    p.add_argument('--zoom', action='store_true', help='sheet: the hands close up, from the right and from the left')
    p.add_argument('command', choices=['scan', 'solve', 'sheet', 'poses'])
    p.add_argument('args', nargs='*')
    a = p.parse_args()
    if not a.configs or not a.meshes:
        p.error('--configs and --meshes (or TP_CONFIGS, TP_MESHES) are needed')
    os.makedirs(a.out, exist_ok=True)
    cfg = ltx.Configs(a.configs)
    meshes = rigmod.Meshes(a.meshes)
    rig = rigmod.Rig(meshes)
    if a.command in ('scan', 'solve'):
        globals()['cmd_' + a.command](a, cfg, fitmod.Fitter(rig, meshes))
    else:
        globals()['cmd_' + a.command](a, cfg, render.Painter(rig, meshes))


if __name__ == '__main__':
    main()
