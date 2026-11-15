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
game = { get_game_time = function() return { get = function() return 2012, 1, math.floor(now_h / 24), now_h % 24, 0, 0, 0 end } end }
shared_depth = 0
coop.begin_shared = function() shared_depth = shared_depth + 1 end
coop.end_shared = function() shared_depth = shared_depth - 1 end
tm = { [77] = { cfg_ltx = "x" } }
trade_manager = {
  get_trade_profile = function(id, key) if key then return tm[id] and tm[id][key] end return tm[id] end,
  -- Anomaly's: due 24 game hours after its timer, or with none
  update = function(npc, force)
    local t = tm[npc:id()].resupply_time
    if t and now_h - (t.D * 24 + t.h) < 24 and not force then return end
    tm[npc:id()].resupply_time = { Y = 2012, M = 1, D = math.floor(now_h / 24), h = now_h % 24, m = 0, s = 0, ms = 0 }
    if coop.is_authority(level.name()) then restocked[#restocked + 1] = now_h end
  end,
}
autoinject_runs = {}
trader_autoinject = { timed_update = function(npc) autoinject_runs[#autoinject_runs + 1] = shared_depth; trade_manager.update(npc, true); return true end }
npc = { id = function() return 77 end, name = function() return "bar_barman" end }
'''
facts = {}
def game(name, seed):
    g = Game(name, facts, None, seed)
    g.run(STUB); g.load('coop_trader_restock')
    g.run('coop_trader_restock.on_game_start(); fire("actor_on_first_update")')
    return g
A = game('artem', 1); B = game('friend', 2)
A.authority = True
def at(g, h, force=False):
    g.clock = h * 3600000.0 + 1
    g.run('now_h = %d; trade_manager.update(npc%s)' % (h, ', true' if force else ''))
def restocks(g):
    return list(g.lua.globals().restocked.values())

at(A, 10)
check(restocks(A) == [10] and facts.get('trader_restock:77') == '0', 'a trader the world never restocked: at once, period 0 noted (%s, %s)' % (restocks(A), facts.get('trader_restock:77')))
at(A, 40); at(A, 71)
check(restocks(A) == [10], 'not again in the same period, though Anomaly\'s 24 h passed')
at(B, 50)
check(restocks(B) == [] and not B.reported, 'the other restocks nothing and reports nothing')
# a reconnect / reload: a fresh game, no timer of its own, the authority
C = game('artem', 3); C.authority = True
at(C, 60)
check(restocks(C) == [], 'a game that came in again (no timer of its own) restocks nothing in the period')
at(C, 60, force=True)
check(restocks(C) == [], 'not even when forced')
at(C, 73)
check(restocks(C) == [73] and facts['trader_restock:77'] == '1', 'the next period: the authority then restocks, once (%s)' % restocks(C))
at(C, 100)
check(restocks(C) == [73], 'and not again in it')
A.authority = False; B.authority = True
at(B, 145)
check(restocks(B) == [145] and facts['trader_restock:77'] == '2', 'another authority goes on with the world\'s periods (%s)' % restocks(B))
# autoinject
A.run('trader_autoinject.timed_update(npc)'); B.run('trader_autoinject.timed_update(npc)')
ra = list(A.lua.globals().autoinject_runs.values()); rb = list(B.lua.globals().autoinject_runs.values())
check(ra == [] and rb == [1], 'autoinject: skipped off the authority, run shared on it (%s / %s)' % (ra, rb))
check(restocks(B) == [145, 145], 'an addon forced update within it goes on (%s)' % restocks(B))
print('FAILS:', len(fails)); sys.exit(1 if fails else 0)
