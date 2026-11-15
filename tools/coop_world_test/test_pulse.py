import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from game import Game
fails = []
def check(cond, what):
    print(('ok   ' if cond else 'FAIL ') + what)
    if not cond: fails.append(what)

STUB = r'''
struck = {}
bind_anomaly_field = {
  pulse_anomaly_spawn = function() own_spawned = (own_spawned or 0) + 1 end,
  pulse_anomaly_roll = function(pos) rolls = (rolls or 0) + 1; return vector():set(pos.x + 10, pos.y + 60, pos.z) end,
  pulse_anomaly_delay = function() return 120000 end,
  pulse_anomaly_at = function(pos, since) table.insert(struck, string.format("%.0f,%.0f,%.0f|%.1f", pos.x, pos.y, pos.z, since)) end,
}
level = { name = function() return "l01_escape" end, get_time_factor = function() return 6 end }
db = { actor = { position = function() return vector():set(my_x, 0, 0) end } }
'''
def setup(bx):
    facts = {}
    A = Game('artem', facts, None, 1); B = Game('friend', facts, None, 2)
    for g, x, other, ox in ((A, 0, 'friend', bx), (B, bx, 'artem', 0)):
        g.run(STUB); g.run('my_x = %d' % x)
        g.run('peer_list = { { name = "%s", level = "l01_escape", position = vector():set(%d, 0, 0), age = 100 } }' % (other, ox))
        g.load('coop_pulse_anomaly')
        g.run('coop_pulse_anomaly.on_game_start(); fire("actor_on_first_update")')
    A.authority = True
    return facts, A, B
def tick(games, seconds):
    for _ in range(int(seconds * 4)):
        for g in games:
            g.clock += 250 * 6
            g.run('now_ms = now_ms + 250; fire("actor_on_update")')

# together: one roll for both, every 2 min
facts, A, B = setup(50)
tick([A, B], 125)
sa = list(A.lua.globals().struck.values()); sb = list(B.lua.globals().struck.values())
check(len(sa) == 1 and len(sb) == 1, 'together: one pulse in 125 s, struck in both games (%s / %s)' % (sa, sb))
check(sa and sb and sa[0].split('|')[0] == sb[0].split('|')[0], 'together: the same point in both games')
check(A.lua.globals().rolls == 1, 'together: one roll for the two players (%s)' % A.lua.globals().rolls)
check(not B.reported, 'the non-authority reports nothing')
check(B.lua.globals().rolls is None, 'the non-authority rolls nothing')
A.run('bind_anomaly_field.pulse_anomaly_spawn()'); B.run('bind_anomaly_field.pulse_anomaly_spawn()')
check(A.lua.globals().own_spawned is None and B.lua.globals().own_spawned is None, "Anomaly's own spawn does nothing in co-op")
tick([A, B], 120)
check(len(list(B.lua.globals().struck.values())) == 2, 'together: the second one 2 min later, once')

# apart: one each, around each player
facts, A, B = setup(1000)
tick([A, B], 125)
sa = sorted(s.split('|')[0] for s in A.lua.globals().struck.values()); sb = sorted(s.split('|')[0] for s in B.lua.globals().struck.values())
check(len(sa) == 2 and sa == sb, 'apart: two pulses, the same two in both games (%s / %s)' % (sa, sb))
check('10,60,0' in sa and '1010,60,0' in sa, 'apart: one around each player')

# a late one (a join) is not struck; the authority changes: the other rolls on
facts, A, B = setup(50)
A.clock = B.clock = 600000.0
facts['pulse_anom:l01_escape'] = '%.0f,1,5.0,60.0,0.0' % (B.clock - 30000 * 6)
tick([B], 1)
check(len(list(B.lua.globals().struck.values())) == 0, 'a pulse 30 s old is not struck')
A.authority = False; B.authority = True
tick([A, B], 125)
check(len(list(A.lua.globals().struck.values())) == 1 and B.lua.globals().rolls == 1, 'the new authority rolls, the old one strikes it')
print('FAILS:', len(fails)); sys.exit(1 if fails else 0)
