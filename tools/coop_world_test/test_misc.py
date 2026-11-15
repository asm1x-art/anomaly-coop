import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from game import Game
fails = []
def check(cond, what):
    print(('ok   ' if cond else 'FAIL ') + what)
    if not cond: fails.append(what)

# --- surge sounds: the same in two games, math.random restored, other calls untouched
SURGE = r'''
level = { get_start_time = function() return "start" end }
coop_event_news = nil
CT = {}; CT.__index = CT
function CT:diffSec(o) return self.sec end
surge_manager = { CSurgeManager = {} }
surge_manager.CSurgeManager.update = function(self)
  picks = picks or {}
  picks[#picks + 1] = math.random(1, 4)
  other = math.random(1, 100)
end
mgr = setmetatable({}, { __index = surge_manager.CSurgeManager })
'''
def surge_game(seed):
    g = Game('g%d' % seed, {}, None, seed)
    g.run(SURGE)
    g.load('coop_event_news')
    g.load('coop_surge_sound')
    g.run('coop_surge_sound.on_game_start()')
    return g
A, B = surge_game(11), surge_game(12)
for g in (A, B):
    g.run('mgr.started = true; mgr.inited_time = setmetatable({ sec = 987654 }, CT); for i = 1, 5 do mgr:update() end')
pa = list(A.lua.globals().picks.values()); pb = list(B.lua.globals().picks.values())
check(pa == pb and len(set(pa)) == 1, 'surge: the same sound roll in both games through the surge (%s / %s)' % (pa, pb))
check(A.lua.eval('math.random') is not None and A.lua.eval('type(math.random(1, 4))') == 'number', 'math.random is Anomaly\'s again after the update')
A.run('vals = {} for i = 1, 40 do vals[math.random(1, 4)] = true end n = 0 for _ in pairs(vals) do n = n + 1 end')
check(A.lua.eval('n') > 1, 'outside the surge update math.random(1, 4) is random again')
A.run('picks = {}; mgr.inited_time = setmetatable({ sec = 1234567 }, CT); mgr:update()')
B.run('picks = {}; mgr.inited_time = setmetatable({ sec = 1234567 }, CT); mgr:update()')
check(list(A.lua.globals().picks.values()) == list(B.lua.globals().picks.values()), 'another surge: again the same in both')
A.run('picks = {}; mgr.started = false; mgr:update()')

# --- crows: the authority spawns, shared, away from every player; the others don't
CROWS = r'''
level = { name = function() return "l01_escape" end }
spawned = {}
shared_depth = 0
coop.begin_shared = function() shared_depth = shared_depth + 1 end
coop.end_shared = function() shared_depth = shared_depth - 1 end
function alife_create(sec, pos) spawned[#spawned + 1] = { sec = sec, shared = shared_depth, x = pos.x } end
function patrol(name) local x = ({ p_near = 30, p_far = 500 })[name]
  return { point = function(self, i) return vector():set(x, 0, 0) end, level_vertex_id = function() return 1 end, game_vertex_id = function() return 2 end } end
sr_crow_spawner = { crowkiller = { check_for_spawn_new_crow = function(self) own = true end } }
db = { actor = { position = function() return vector():set(0, 0, 0) end } }
function make(paths) return setmetatable({ st = { path_table = paths }, spawn_points_idle = {} }, { __index = sr_crow_spawner.crowkiller }) end
'''
def crow_game(auth, peer_x):
    g = Game('c', {}, None, 5); g.run(CROWS)
    g.run('peer_list = { { name = "p", level = "l01_escape", position = vector():set(%d, 0, 0), age = 1 } }' % peer_x)
    g.load('coop_crows'); g.run('coop_crows.on_game_start()'); g.authority = auth
    return g
g = crow_game(False, 1000); g.run('k = make({ "p_far" }); r = k:check_for_spawn_new_crow()')
check(len(list(g.lua.globals().spawned.values())) == 0 and not g.lua.globals().own, 'crows: the non-authority spawns none')
g = crow_game(True, 1000); g.run('k = make({ "p_far" }); r = k:check_for_spawn_new_crow()')
sp = list(g.lua.globals().spawned.values())
check(len(sp) == 1 and sp[0].shared == 1 and sp[0].sec == 'm_crow', 'crows: the authority spawns one, shared')
g = crow_game(True, 480); g.run('k = make({ "p_far" }); r = k:check_for_spawn_new_crow()')
check(len(list(g.lua.globals().spawned.values())) == 0, 'crows: none 20 m from another player')
g = crow_game(True, 1000); g.run('k = make({ "p_near" }); r = k:check_for_spawn_new_crow()')
check(len(list(g.lua.globals().spawned.values())) == 0, 'crows: none 30 m from our own actor')

# --- offline squads' health: the host sends changes and the wounded each full round; the others take them
SQUADS = r'''
sent_events = {}
coop_sync = { send_event = function(name, payload) sent_events[#sent_events + 1] = name .. ":" .. payload end,
              on_event = function(name, f) handlers = handlers or {}; handlers[name] = f end }
local function member(id, hp) return { id = id, hp = hp } end
objects = { [10] = { online = true, m_game_vertex_id = 65535, members = { member(11, 1), member(12, 0.4) } } }
creatures = { [11] = 1, [12] = 0.4 }
function alife() return { object = function(self, id)
  if objects[id] then local s = objects[id]
    s.squad_members = function(self) local i = 0 return function() i = i + 1 return s.members[i] end end
    return s end
  if creatures[id] then return { alive = function() return creatures[id] > 0 end, health = function() return creatures[id] end } end
end } end
SIMBOARD = { squads = { [10] = true } }
taken = {}
coop.set_offline_health = function(id, h) taken[#taken + 1] = id .. "=" .. h; return true end
coop.squad_online_elsewhere = function() return false end
'''
H = Game('host', {}, None, 6); H.host = True
H.run(SQUADS); H.load('coop_squads'); H.run('coop_squads.on_game_start()')
H.run('fire("actor_on_update")')
ev = list(H.lua.globals().sent_events.values())
check(ev == ['squad_hp:12,400'], 'host: the first round sends the wounded one only (%s)' % ev)
H.run('sent_events = {}; now_ms = 6000; creatures[11] = 0.75; fire("actor_on_update")')
ev = list(H.lua.globals().sent_events.values())
check(ev == ['squad_hp:11,750'], 'host: a change goes out, the unchanged one not (%s)' % ev)
P = Game('friend', {}, None, 7)
P.run(SQUADS); P.load('coop_squads'); P.run('coop_squads.on_game_start()')
P.run('handlers.squad_hp("host", "11,750;12,400")')
check(list(P.lua.globals().taken.values()) == ['11=0.75', '12=0.4'], 'a player takes them onto its offline copies')
P.run('fire("actor_on_update")')
check(len(list(P.lua.globals().sent_events.values())) == 0, 'a player sends nothing')

# --- the Zone's events' clock
Z = Game('z', {}, None, 8)
Z.run('ini_sys.r_string_ex = function() return nil end')
Z.load('coop_zone_events')
Z.run('coop.server_time = function() return 1800000123.7 end')
check(Z.lua.eval('coop_zone_events.now()') == 1800000123, 'zone events: now() is the server\'s clock in co-op')
Z.run('coop.server_time = function() return 0 end')
check(abs(Z.lua.eval('coop_zone_events.now()') - Z.lua.eval('os.time()')) <= 1, 'zone events: os.time() without the server\'s')
print('FAILS:', len(fails)); sys.exit(1 if fails else 0)
