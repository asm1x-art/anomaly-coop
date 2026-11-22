r"""Offline check before any game launch: every motion the hud section names exists where the engine looks for it.
  python tools/spectrum_x/check_motions.py [--gamedata <dir>] [--section dev_spectrum_x_hud]
For each anm_* line of the hud section (hands motion, optional item motion): the hands motion must be in the hands'
.omf, the item's in the item model (.ogf) - in its embedded motions, or, if the model has motion refs, in the files
those refs name (the engine then ignores the embedded ones). Exit 1 on anything missing: a missing one is a FATAL
"model has no motion [idle]" / "motion not found" when the item is drawn."""
import os, re, struct, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "gamedata")
GD = sys.argv[sys.argv.index("--gamedata") + 1] if "--gamedata" in sys.argv else ROOT
SEC = sys.argv[sys.argv.index("--section") + 1] if "--section" in sys.argv else "dev_spectrum_x_hud"
LTX = os.path.join(GD, "configs", "mod_system_spectrum_x.ltx")
OMF = os.path.join(GD, "meshes", "anomaly_weapons", "hud_hands_animation", "dev_hand_spectrum_x_hud_animation.omf")


def chunks(b, o=0, end=None):
    end = len(b) if end is None else end
    while o + 8 <= end:
        cid, sz = struct.unpack_from("<II", b, o); yield cid & 0x7FFFFFFF, b[o + 8:o + 8 + sz]; o += 8 + sz


def motion_names(b):
    """names of the motions in an .omf / .ogf (chunk 14, one sub-chunk a motion, its name first)"""
    out, refs = set(), []
    for cid, d in chunks(b):
        if cid == 14:
            for sid, sd in chunks(d):
                if sid: out.add(sd[:sd.index(b"\0")].decode("latin1"))
        elif cid in (19, 24):
            if cid == 24:
                n = struct.unpack_from("<I", d)[0]; refs = [x.decode("latin1") for x in d[4:].split(b"\0")[:n]]
            else:
                refs = [x for x in d.split(b"\0")[0].decode("latin1").split(",") if x]
    return out, refs


section, lines = None, {}
for raw in open(LTX, "rb").read().decode("cp1251").splitlines():
    l = raw.split(";")[0].strip()
    m = re.match(r"^\[([^\]]+)\]", l)
    if m: section = m.group(1); continue
    if section == SEC and "=" in l:
        k, v = [x.strip() for x in l.split("=", 1)]; lines[k] = v
visual = lines.get("item_visual")
ogf = os.path.join(GD, "meshes", visual + ".ogf")
hands, _ = motion_names(open(OMF, "rb").read())
item, refs = motion_names(open(ogf, "rb").read())
if refs:
    item = set()
    for r in refs:
        p = os.path.join(GD, "meshes", r + ".omf")
        if os.path.exists(p): item |= motion_names(open(p, "rb").read())[0]
        else: print("item model refs %s: not in this gamedata (archives not checked)" % r)
bad = 0
for k, v in sorted(lines.items()):
    if not k.startswith("anm_"): continue
    parts = [x.strip() for x in v.split(",")]
    h = parts[0]; it = parts[1] if len(parts) > 1 and not re.match(r"^[\d.]+$", parts[1]) else h
    ok_h, ok_i = h in hands, it in item
    if not (ok_h and ok_i): bad += 1
    print("%-24s hands %-26s %s   item %-26s %s" % (k, h, "ok" if ok_h else "MISSING", it, "ok" if ok_i else "MISSING"))
print("item model %s: %d motions%s; hands .omf: %d motions" % (visual, len(item), (", refs " + ", ".join(refs)) if refs else ", embedded", len(hands)))
print("FAIL: %d missing" % bad if bad else "all motions found")
sys.exit(1 if bad else 0)
