import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from game import Game
fails = []
def check(cond, what):
    print(('ok   ' if cond else 'FAIL ') + what)
    if not cond: fails.append(what)

STUB = r'''
now_h = 0
restocked = {}
level = { name = function() return "l05_bar" end }
shared_depth = 0
coop.begin_shared = function() shared_depth = shared_depth + 1 end
coop.end_shared = function() shared_depth = shared_depth - 1 end
tm = { [77] = { cfg_ltx = "x" } }
trade_manager = {
  get_trade_profile = function(id, key) if key then return tm[id] and tm[id][key] end return tm[id] end,
  update = function(npc, force)
    local t = tm[npc:id()].resupply_time
    if t and now_h - (t.D * 24 + t.h) < 24 and not force then return end
    tm[npc:id()].resupply_time = { Y = 2012, M = 1, D = math.floor(now_h / 24), h = now_h % 24, m = 0, s = 0, ms = 0 }
    if coop.is_authority(level.name()) then restocked[#restocked + 1] = now_h end
  end,
}
autoinject_runs = {}
trader_autoinject = { timed_update = function(npc) autoinject_runs[#autoinject_runs + 1] = shared_depth; return true end }
npc = { id = function() return 77 end, name = function() return "bar_barman" end }
'''
facts = {}
A = Game('artem', facts, None, 1); B = Game('friend', facts, None, 2)
for g in (A, B):
    g.run(STUB); g.load('coop_trader_restock')
    g.run('coop_trader_restock.on_game_start(); fire("actor_on_first_update")')
A.authority = True
def at(g, h):
    g.run('now_h = %d; trade_manager.update(npc)' % h)
at(A, 0)
check(facts.get('trader_restock:77') == '2012,1,0,0,0,0,0', 'the authority restocks at 0 h and publishes it (%s)' % facts.get('trader_restock:77'))
at(B, 5)
check(len(list(B.lua.globals().restocked.values())) == 0 and len(B.reported) == 0, 'the other restocks nothing and reports nothing')
at(A, 10)
check(len(list(A.lua.globals().restocked.values())) == 1, 'not due at 10 h')
A.authority = False; B.authority = True
at(B, 20)
check(len(list(B.lua.globals().restocked.values())) == 0, 'the new authority at 20 h: not due by the world (its own timer said 5 h)')
at(B, 26)
check(list(B.lua.globals().restocked.values()) == [26], 'the new authority restocks at 26 h by the world\'s timer, not 29 h by its own')
check(facts['trader_restock:77'] == '2012,1,1,2,0,0,0', 'and publishes it (%s)' % facts['trader_restock:77'])
# autoinject
A.run('trader_autoinject.timed_update(npc)'); B.run('trader_autoinject.timed_update(npc)')
ra = list(A.lua.globals().autoinject_runs.values()); rb = list(B.lua.globals().autoinject_runs.values())
check(ra == [] and rb == [1], 'autoinject: skipped off the authority, run shared on it (%s / %s)' % (ra, rb))
print('FAILS:', len(fails)); sys.exit(1 if fails else 0)
