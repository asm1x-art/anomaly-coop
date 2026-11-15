# Offline test of gamedata/scripts/coop_time.script with stubs, no game (pip install lupa):
#   python tools/coop_time_test/run.py
# adopt_test.lua: a host that starts again from an old save takes the world's weather, cycle period and surge/psi
# storm timetables from the server's facts before it publishes anything.
import os
import sys
from lupa import luajit21

here = os.path.dirname(os.path.abspath(__file__))
script = os.path.join(here, '..', '..', 'gamedata', 'scripts', 'coop_time.script')
lua = luajit21.LuaRuntime()
lua.execute(open(os.path.join(here, 'adopt_test.lua'), encoding='utf-8').read(),
            open(script, 'rb').read().decode('cp1251'))
sys.exit(1 if lua.globals().FAILED else 0)
