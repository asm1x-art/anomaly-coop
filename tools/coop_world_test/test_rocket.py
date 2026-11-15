import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from game import Game
fails = []
def check(cond, what):
    print(('ok   ' if cond else 'FAIL ') + what)
    if not cond: fails.append(what)

STUB = r'''
level = { name = function() return "l01_escape" end }
outbox = {}
handlers = {}
coop_sync = { send_event = function(name, ...) outbox[#outbox + 1] = { name, table.concat({ ... }, "\t") } end,
              on_event = function(name, f) handlers[name] = f end }
launched = 0
local rocket = { flying = false }
function rocket:is_flying() return self.flying end
function rocket:launch() self.flying = true; launched = launched + 1 end
db = { actor = {}, signal_light = { esc_rocket = rocket } }
xr_effects = { launch_signal_rocket = function(actor, obj, p) own = true; db.signal_light[p[1]]:launch() end }
function land() rocket.flying = false end
'''
games = {}
def game(name, auth):
    g = Game(name, {}, None, 1); g.run(STUB); g.load('coop_signal_rocket'); g.run('coop_signal_rocket.on_game_start()')
    g.authority = auth; games[name] = g
    return g
A = game('artem', True); B = game('friend', False)
def deliver():
    moved = True
    while moved:
        moved = False
        for name, g in games.items():
            out = list(g.lua.eval('outbox').values())
            g.run('outbox = {}')
            for ev in out:
                moved = True
                for other, h in games.items():
                    if other != name:
                        h.lua.eval('handlers')[ev[1]](name, ev[2])
def launched(g): return g.lua.eval('launched')
A.run('xr_effects.launch_signal_rocket(nil, nil, { "esc_rocket" })'); deliver()
check(launched(A) == 1 and launched(B) == 1, 'the authority launches it: up in both games')
for g in (A, B): g.run('land()')
B.run('xr_effects.launch_signal_rocket(nil, nil, { "esc_rocket" })')
check(launched(B) == 1, 'the other\'s own logic launches nothing itself')
deliver()
check(launched(A) == 2 and launched(B) == 2, 'it asks the authority: up in both games')
for g in (A, B): g.run('land()')
A.run('xr_effects.launch_signal_rocket(nil, nil, { "esc_rocket" })'); B.run('xr_effects.launch_signal_rocket(nil, nil, { "esc_rocket" })'); deliver()
check(launched(A) == 3 and launched(B) == 3, 'both logics at once: one rocket, not two')
check(A.lua.eval('own') is None and B.lua.eval('own') is None, 'Anomaly\'s own launch is not used in co-op')
print('FAILS:', len(fails)); sys.exit(1 if fails else 0)
