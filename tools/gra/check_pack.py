r"""Static checks of the gamedata after build_pack.py: the scripts compile; no script calls a module of a GRA mod left out;
every ltx parent section, ltx #include and shader #include points at something that exists (vanilla, this repo or
the pack); DLTX overrides of missing sections are counted.
  check_pack.py <vanilla configs dir> <vanilla scripts dir>
(the vanilla dirs: Anomaly's configs.db0 and scripts unpacked with X:\Anomaly\tools\converter.exe -unpack -xdb into
<dir>\configs\configs; its shaders.db0 is expected unpacked next to it, into <dir>\shaders\shaders)
"""
import os
import re
import sys

import lupa.luajit21 as lupa

HERE = os.path.dirname(os.path.abspath(__file__))
GAMEDATA = os.path.normpath(os.path.join(HERE, "..", "..", "gamedata"))
MO2 = r"X:\GRA2.5\MO2\mods"
sys.path.insert(0, HERE)
from build_pack import MODS  # noqa: E402

vanilla_configs, vanilla_scripts = sys.argv[1], sys.argv[2]


def files(root, ext):
    for dirpath, _, names in os.walk(root):
        for n in names:
            if n.lower().endswith(ext):
                yield os.path.join(dirpath, n)


def read(path):
    return open(path, "rb").read().decode("cp1251", "replace")


problems = 0


def problem(text):
    global problems
    problems += 1
    print(text)


# scripts compile
lua = lupa.LuaRuntime()
compile_ = lua.eval("function(s, n) local f, e = loadstring(s, n) return e end")
ours = list(files(os.path.join(GAMEDATA, "scripts"), ".script"))
for p in ours:
    err = compile_(read(p), os.path.basename(p))
    if err:
        problem(f"syntax: {err}")

# modules of GRA mods not taken
known = {os.path.basename(p)[:-7].lower() for p in ours} | {n[:-7].lower() for n in os.listdir(vanilla_scripts) if n.endswith(".script")}
others = {}
for mod in os.listdir(MO2):
    if mod in MODS:
        continue
    for p in files(os.path.join(MO2, mod, "gamedata", "scripts"), ".script"):
        name = os.path.basename(p)[:-7].lower()
        if name not in known:
            others.setdefault(name, mod)
for p in ours:
    text = read(p)
    for name in sorted({m.lower() for m in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\.[A-Za-z_]", text)} & set(others)):
        problem(f"{os.path.basename(p)} uses {name}, a module of {others[name]} (not taken)")

# ltx: sections, parents, DLTX overrides, includes
SECTION = re.compile(r"^[ \t]*(!|@)?\[([^\]\r\n]+)\][ \t]*(?::[ \t]*([^;\r\n]*))?", re.M)
INCLUDE = re.compile(r'^\s*#include\s+"([^"]+)"', re.M)
defined, uses = set(), []
for root in (vanilla_configs, os.path.join(GAMEDATA, "configs")):
    for p in files(root, ".ltx"):
        text = read(p)
        for mark, sec, parents in SECTION.findall(text):
            sec = sec.strip().lower()
            if mark != "!":  # @[...] creates the section when it's missing
                defined.add(sec)
            if root != vanilla_configs:
                uses.append((p, mark, sec, [x.strip().lower() for x in (parents or "").split(",") if x.strip()]))
        if root != vanilla_configs:
            for inc in INCLUDE.findall(text):
                if "*" in inc:
                    continue
                target = os.path.normpath(os.path.join(os.path.dirname(p), inc))
                rel = os.path.relpath(target, os.path.join(GAMEDATA, "configs"))
                if not os.path.exists(target) and not os.path.exists(os.path.join(vanilla_configs, rel)):
                    problem(f"{os.path.relpath(p, GAMEDATA)}: #include \"{inc}\" not found")
missing_overrides = 0  # ![...] of a section defined nowhere: DLTX only warns in the log and leaves it out
for p, mark, sec, parents in uses:
    where = os.path.relpath(p, GAMEDATA)
    if mark == "!" and sec not in defined:
        missing_overrides += 1
    for parent in parents:
        if parent not in defined and not parent.startswith("!"):  # !parent: DLTX takes that parent away
            problem(f"{where}: [{sec}] inherits [{parent}], defined nowhere")
# shaders: every #include found next to it (this repo's gamedata or vanilla's shaders of the same renderer)
vanilla_shaders = os.path.normpath(os.path.join(vanilla_configs, "..", "..", "shaders", "shaders"))
shader_files = 0
for p in files(os.path.join(GAMEDATA, "shaders"), ""):
    if not p.lower().endswith((".ps", ".vs", ".gs", ".hs", ".ds", ".cs", ".h", ".s", ".hlsl")):
        continue
    shader_files += 1
    renderer = os.path.relpath(p, os.path.join(GAMEDATA, "shaders")).split(os.sep)[0]
    for inc in re.findall(r'^[ 	]*#include[ 	]+"([^"]+)"', read(p), re.M):
        rel = os.path.join(os.path.dirname(os.path.relpath(p, os.path.join(GAMEDATA, "shaders"))), inc)
        if not (os.path.exists(os.path.join(GAMEDATA, "shaders", rel)) or os.path.exists(os.path.join(vanilla_shaders, rel))):
            problem(f"{os.path.relpath(p, GAMEDATA)}: #include \"{inc}\" not found ({renderer})")
print(f"{shader_files} shader files checked")
print(f"{len(ours)} scripts, {len(uses)} ltx sections checked; {problems} problems; "
      f"{missing_overrides} overrides of sections defined nowhere (DLTX warnings)")
