"""Syntax check for every .script file in the repo (LuaJIT 2.1, as the engine).

Usage: python tools/ci/lua_check.py [root]
Prints file:line: error for each file that does not compile; exit code 1 if any.
Needs: pip install lupa
"""
import pathlib
import sys

from lupa import luajit21


def main():
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    lua = luajit21.LuaRuntime()
    compile_chunk = lua.eval("function(src, name) local f, err = loadstring(src, name) return err end")
    files = sorted(p for p in root.rglob("*.script") if ".git" not in p.parts)
    bad = 0
    for path in files:
        name = path.relative_to(root).as_posix()
        # Scripts are cp1251; the engine hands the raw bytes to LuaJIT.
        src = path.read_bytes().decode("cp1251", errors="replace")
        err = compile_chunk(src, "@" + name)
        if err:
            bad += 1
            print(err)
    print(f"{len(files)} scripts checked, {bad} with errors")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
