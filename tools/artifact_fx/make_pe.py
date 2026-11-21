r"""Writes the artefacts' ground particles, gamedata/particles/coop/artefact_fx/<family>_<density>.pe (text .pe, the
format of gamedata/particles/coop/ash_embers.pe, read by the engine over particles.xr).

One effect a family (artefact_fx.script, [artefact_fx_family_*] in mod_system_artefact_fx.ltx picks it by name), three
densities each (1 sparse, 2 normal, 3 dense: the .ltx's particles_density): only the birth rate and the cap change.
Everything sits round the emitter, which the script keeps on the artefact: a few cheap sprites within half a metre.

  python tools/artifact_fx/make_pe.py            writes the files
  python tools/artifact_fx/make_pe.py --check    exits 1 if a written file differs from what this script makes

Action parameters go in the engine's own order: alphabetical by the editor's name (EParticleAction floats, vectors,
domains, bools are maps keyed by name), see src/Layers/xrRender/ParticleEffectActions.cpp.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "gamedata", "particles", "coop", "artefact_fx")

DENSITY = {1: 0.5, 2: 1.0, 3: 1.8}

# family: what it looks like. rate a second (density 2), age s, texture + frames, size range (m), colour at its
# brightest, spawn domain, velocity domain, extra motion
FAMILIES = {
    # fire: embers rising off it
    "thermo": dict(
        note="fire: orange embers drifting up off it",
        texture="pfx\\pfx_sparks1", frames=(0.25, 0.5, 4, 8, 12),
        rate=10, age=1.6, size=(0.025, 0.055), color=(1.0, 0.42, 0.12), alpha=1.0, scale=3.0,
        source=(5, (0, 0.05, 0), (0.08, 0.3, 0)),
        velocity=(4, (-0.06, 0.18, -0.06), (0.06, 0.45, 0.06)),
        turbulence=(0.6, 0.4), orbit=None),
    # electric: short arcs flicking on and off round it
    "electro": dict(
        note="electric: short arcs flicking round it",
        texture="pfx\\pfx_electrostatic", frames=(0.25, 0.25, 4, 16, 40),
        rate=14, age=0.22, size=(0.07, 0.14), color=(0.55, 0.75, 1.0), alpha=1.0, scale=4.0,
        source=(5, (0, 0.08, 0), (0.12, 0.3, 0)),
        velocity=(0, (0, 0, 0), (0, 0, 0)),
        turbulence=None, orbit=None),
    # chemical: green, radiation-like motes rising slowly and swaying
    "chem": dict(
        note="chemical: green motes rising slowly, swaying",
        texture="pfx\\snowo", frames=(0.5, 0.5, 2, 4, 6),
        rate=7, age=2.6, size=(0.02, 0.045), color=(0.35, 1.0, 0.3), alpha=1.0, scale=3.0,
        source=(5, (0, 0.03, 0), (0.05, 0.35, 0)),
        velocity=(4, (-0.03, 0.06, -0.03), (0.03, 0.2, 0.03)),
        turbulence=(0.8, 0.35), orbit=None),
    # gravitational: dust pulled in round it
    "gravi": dict(
        note="gravitational: dust motes pulled in and circling",
        texture="pfx\\snowo", frames=(0.5, 0.5, 2, 4, 6),
        rate=9, age=2.0, size=(0.018, 0.035), color=(0.85, 0.7, 1.0), alpha=1.0, scale=2.5,
        source=(5, (0, 0.1, 0), (0.3, 0.6, 0)),
        velocity=(4, (-0.05, -0.02, -0.05), (0.05, 0.08, 0.05)),
        turbulence=None, orbit=(0.25, 0.6)),
    # everything else (no nature, junk): faint pale motes
    "plain": dict(
        note="no nature: a few faint pale motes",
        texture="pfx\\snowo", frames=(0.5, 0.5, 2, 4, 6),
        rate=3, age=2.2, size=(0.015, 0.03), color=(0.8, 0.9, 1.0), alpha=0.8, scale=2.0,
        source=(5, (0, 0.05, 0), (0.08, 0.3, 0)),
        velocity=(4, (-0.02, 0.04, -0.02), (0.02, 0.12, 0.02)),
        turbulence=(0.6, 0.2), orbit=None),
}


def v3(v):
    return ", ".join(("%g" % x) for x in v)


def domain(name, idx, act, d):
    t, a, b = d
    return "[domain_action_%04d_%04d] ; %s\ntype = %d\nv0 = %s\nv1 = %s\nv2 = 0, 0, 0\n\n" % (act, idx, name, t, v3(a), v3(b))


def effect(fam, f, dens):
    rate = f["rate"] * DENSITY[dens]
    cap = max(4, int(round(rate * f["age"] * 1.3 + 2)))
    tu, tv, dim_x, count, speed = f["frames"]
    acts = []
    acts.append("; KillOld\n[action_%04d]\naction_type = 10\nversion = 1\naction_name = killold\nflags = 1\n"
                "flt_0000 = %g ; Age Limit\nbool_0000 = off ; Kill Less Than\n\n" % (0, f["age"]))
    n = len(acts)
    src = ("; Source\n[action_%04d]\naction_type = 21\nversion = 1\naction_name = source\nflags = 1\n"
           "flt_0000 = %g ; Age Sigma\nflt_0001 = 0 ; Color\\Alpha\nflt_0002 = 1 ; Parent Motion\nflt_0003 = %g ; Rate\n"
           "flt_0004 = 0 ; Starting Age\nbool_0000 = off ; Allow Rotate\nbool_0001 = on ; Single Size\n\n"
           % (n, f["age"] * 0.2, rate))
    src += domain("Color Point", 0, n, (0, (0, 0, 0), (0, 0, 0)))
    src += domain("Domain", 1, n, f["source"])
    src += domain("Rotation Point", 2, n, (0, (0, 0, 0), (0, 0, 0)))
    s0, s1 = f["size"]
    src += domain("Size Line", 3, n, (1, (s0, s0, s0), (s1, s1, s1)))
    src += domain("Velocity", 4, n, f["velocity"])
    acts.append(src)
    n = len(acts)
    acts.append("; TargetColor: glows up\n[action_%04d]\naction_type = 23\nversion = 1\naction_name = targetcolor\nflags = 1\n"
                "flt_0000 = %g ; Alpha\nflt_0001 = %g ; Scale\nflt_0002 = 0 ; TimeFrom\nflt_0003 = 0.3 ; TimeTo\n"
                "vec_0000 = %s ; Color\n\n" % (n, f["alpha"], f["scale"], v3(f["color"])))
    n = len(acts)
    acts.append("; TargetColor: goes out\n[action_%04d]\naction_type = 23\nversion = 1\naction_name = targetcolor\nflags = 1\n"
                "flt_0000 = 0 ; Alpha\nflt_0001 = 1.5 ; Scale\nflt_0002 = 0.6 ; TimeFrom\nflt_0003 = 1 ; TimeTo\n"
                "vec_0000 = 0, 0, 0 ; Color\n\n" % n)
    if f["turbulence"]:
        n = len(acts)
        freq, mag = f["turbulence"]
        acts.append("; Turbulence\n[action_%04d]\naction_type = 30\nversion = 1\naction_name = turbulence\nflags = 1\n"
                    "flt_0000 = 0.01 ; Delta\nflt_0001 = %g ; Frequency\nflt_0002 = %g ; Magnitude\n"
                    "vec_0000 = 1, 1, 1 ; Movement\nint_0000 = 1 ; Octaves\n\n" % (n, freq, mag))
    if f["orbit"]:
        n = len(acts)
        mag, maxr = f["orbit"]
        acts.append("; OrbitPoint: round the artefact\n[action_%04d]\naction_type = 14\nversion = 1\naction_name = orbitpoint\nflags = 1\n"
                    "flt_0000 = 0.05 ; Epsilon\nflt_0001 = %g ; Magnitude\nflt_0002 = %g ; Max Radius\n"
                    "vec_0000 = 0, 0.15, 0 ; Center\nbool_0000 = on ; Allow Rotate\n\n" % (n, mag, maxr))
        n = len(acts)
        acts.append("; Damping: it doesn't fly off\n[action_%04d]\naction_type = 4\nversion = 1\naction_name = damping\nflags = 1\n"
                    "flt_0000 = 1e+10 ; V High\nflt_0001 = 0 ; V Low\nvec_0000 = 0.97, 0.97, 0.97 ; Damping\n\n" % n)
    n = len(acts)
    acts.append("; Move\n[action_%04d]\naction_type = 12\nversion = 1\naction_name = move\nflags = 1\n" % n)
    head = ("; Co-op: an artefact's ground particles, family %s, density %d (generated by tools/artifact_fx/make_pe.py,\n"
            "; change the numbers there and run it again). %s. Additive sprites, artefact_fx.script keeps the\n"
            "; emitter on the artefact while it lies near the player.\n"
            "[_effect]\nversion = 1\nmax_particles = %d\nflags = 5121\naction_count = %d\n\n"
            "[sprite]\nshader = particles\\add\ntexture = %s\n\n"
            "[frame]\ntex_size = %g, %g\nreserved = 0, 0\ndim_x = %d\nframe_count = %d\nspeed = %g\n\n"
            % (fam, dens, f["note"].capitalize(), cap, len(acts), f["texture"], tu, tv, dim_x, count, speed))
    return head + "".join(acts)


def main():
    check = "--check" in sys.argv
    os.makedirs(OUT, exist_ok=True)
    bad = 0
    for fam, f in FAMILIES.items():
        for dens in DENSITY:
            path = os.path.join(OUT, "%s_%d.pe" % (fam, dens))
            text = effect(fam, f, dens)
            if check:
                old = open(path, encoding="ascii").read() if os.path.exists(path) else None
                if old != text:
                    print("differs:", path)
                    bad += 1
            else:
                with open(path, "w", encoding="ascii", newline="\n") as fh:
                    fh.write(text)
    print("checked" if check else "written", len(FAMILIES) * len(DENSITY), "effects,", bad, "differ")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
