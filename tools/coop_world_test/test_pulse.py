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
            g.utc += 0.25
            g.run('now_ms = now_ms + 250; fire("actor_on_update")')

T0 = 1800000000.0 + 0.1 # the server's clock just after a slot began (Anomaly's 2 min each)
def at_time(games, utc):
    for g in games:
        g.utc = utc
def struck(g):
    return [s.split('|')[0] for s in g.lua.globals().struck.values()]
def rolls(g):
    return g.lua.globals().rolls or 0

# together: the slot's roll at once, then one each slot
facts, A, B = setup(50)
at_time([A, B], T0)
tick([A, B], 1)
check(len(struck(A)) == 1 and struck(A) == struck(B), 'together: the slot rolled at once, struck in both games (%s / %s)' % (struck(A), struck(B)))
check(rolls(A) == 1, 'together: one roll for the two players (%s)' % rolls(A))
check(not B.reported and rolls(B) == 0, 'the non-authority rolls and reports nothing')
check(facts.get('pulse_slot:l01_escape') == str(int(T0 * 1000 // 120000)), 'the slot rolled is the server fact (%s)' % facts.get('pulse_slot:l01_escape'))
A.run('bind_anomaly_field.pulse_anomaly_spawn()'); B.run('bind_anomaly_field.pulse_anomaly_spawn()')
check(A.lua.globals().own_spawned is None and B.lua.globals().own_spawned is None, "Anomaly's own spawn does nothing in co-op")
tick([A, B], 118)
check(len(struck(B)) == 1, 'nothing more within the slot')
tick([A, B], 2)
check(len(struck(B)) == 2 and rolls(A) == 2, 'the next slot: the second one, once')

# apart: one roll for the level each slot, around the players in turn
facts, A, B = setup(1000)
at_time([A, B], T0)
tick([A, B], 1)
tick([A, B], 120)
check(sorted(struck(A)) == sorted(struck(B)) == ['1010,60,0', '10,60,0'] or sorted(struck(A)) == sorted(struck(B)) == ['10,60,0', '1010,60,0'],
      'apart: two slots, one around each player, the same in both games (%s / %s)' % (struck(A), struck(B)))
check(rolls(A) == 2, 'apart: two rolls in two slots, as for one player (%s)' % rolls(A))

# the authority changes within a slot: the slot isn't rolled again, the new one rolls the next at its start
facts, A, B = setup(50)
at_time([A, B], T0)
tick([A, B], 1)
A.authority = False; B.authority = True
tick([A, B], 60)
check(rolls(B) == 0 and len(struck(A)) == 1, 'the new authority leaves the slot rolled already')
tick([A, B], 60)
check(rolls(B) == 1 and len(struck(A)) == 2 and struck(A) == struck(B), 'it rolls the next slot right at its start, no wait of its own; the old one strikes it')

# a late one (a join) is not struck; no server clock: no rolls
facts, A, B = setup(50)
A.clock = B.clock = 600000.0
facts['pulse_anom:l01_escape'] = '%.0f,1,5.0,60.0,0.0' % (B.clock - 30000 * 6)
facts['pulse_slot:l01_escape'] = str(int(B.utc * 1000 // 120000) + 5)
tick([B], 1)
check(len(struck(B)) == 0, 'a pulse 30 s old is not struck')
facts, A, B = setup(50)
A.run('coop.server_time = function() return 0 end')
tick([A], 3)
check(rolls(A) == 0, 'no rolls before the server clock is known')
print('FAILS:', len(fails)); sys.exit(1 if fails else 0)
