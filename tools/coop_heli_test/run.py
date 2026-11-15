"""Offline check of gamedata/scripts/coop_heli.script (helicopters in co-op) with Anomaly's own bind_heli.script and
heli_combat.script on stubs: python tools/coop_heli_test/run.py [vanilla scripts folder]
(default H:/stalker-test/anomaly-unpacked/scripts). Needs lupa (pip install lupa). Exit code 1 on any failed check."""
import os
import sys

import lupa.luajit21 as lupa

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
VANILLA = sys.argv[1] if len(sys.argv) > 1 else r"H:/stalker-test/anomaly-unpacked/scripts"


def source(name):
    for folder in (os.path.join(REPO, "gamedata", "scripts"), VANILLA):
        path = os.path.join(folder, name + ".script")
        if os.path.exists(path):
            return open(path, "rb").read().decode("cp1251"), path
    raise FileNotFoundError(name)


def main():
    L = lupa.LuaRuntime(unpack_returned_tuples=True)
    L.execute(open(os.path.join(HERE, "harness.lua"), encoding="utf-8").read())
    # each script in its own namespace on top of _G, as Anomaly loads them
    make_module = L.eval("""function(src, name)
        local chunk, err = loadstring(src, "@" .. name)
        if not chunk then error(err) end
        local env = setmetatable({}, { __index = _G })
        setfenv(chunk, env)
        chunk()
        return env
    end""")

    def load(name):
        src, path = source(name)
        return make_module(src, path)

    results = L.globals().run(load)
    failed = 0
    for i in range(1, len(results) + 1):
        r = results[i]
        ok = r["ok"]
        failed += 0 if ok else 1
        print(("ok    " if ok else "FAIL  ") + r["name"] + ("" if ok or not r["detail"] else "  (" + r["detail"] + ")"))
    print("%d checks, %d failed" % (len(results), failed))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
