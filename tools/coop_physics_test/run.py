# Offline check of coop_physics.script: up to three games (Lua states with stubs.lua) and a server between them.
# python run.py [path to coop_physics.script]   (needs lupa: pip install lupa)
import sys, os
from lupa import luajit21

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', '..', 'gamedata', 'scripts', 'coop_physics.script')
ECHOED = ('door:',)

class World:
    def __init__(self, names):
        self.queue = []
        self.server_facts = {}
        self.games = {}
        self.down = set()
        for n in names:
            L = luajit21.LuaRuntime(unpack_returned_tuples=True)
            L.globals().GAME_NAME = n
            L.globals().net_send = self.sender(n)
            L.execute(open(os.path.join(HERE, 'stubs.lua'), encoding='utf-8').read())
            src = open(SCRIPT, 'rb').read().decode('cp1251')
            mod = L.eval('function(src) local env = setmetatable({}, {__index = _G}); local f = assert(loadstring(src, "coop_physics")); setfenv(f, env); f(); return env end')(src)
            mod.on_game_start()
            L.globals().coop_physics_mod = mod
            self.games[n] = (L, mod)

    def sender(self, name):
        def send(kind, a, b):
            if name in self.down:
                return
            self.queue.append((name, kind, a, b))
        return send

    def G(self, n):
        return self.games[n][0].globals().G

    def lua(self, n, code):
        return self.games[n][0].execute(code)

    def pump(self):
        while self.queue:
            sender, kind, a, b = self.queue.pop(0)
            targets = [n for n in self.games if n != sender and n not in self.down]
            if kind == 'event':
                for n in targets:
                    self.games[n][0].globals().deliver_event(a, sender, b)
            elif kind == 'fact':
                if a.startswith('once:'):  # a claim: the first stays, the claimer is told whose it is
                    kept = self.server_facts.get(a, '')
                    if not kept and b:
                        self.server_facts[a] = b
                        for n in targets:
                            self.games[n][0].globals().deliver_fact(a, b)
                    self.games[sender][0].globals().deliver_fact(a, kept or b)
                    continue
                if self.server_facts.get(a, '') == b:
                    continue
                self.server_facts[a] = b
                if a.startswith(ECHOED):
                    targets.append(sender)
                for n in targets:
                    self.games[n][0].globals().deliver_fact(a, b)
            elif kind == 'spawn':
                for n in targets:
                    g = self.G(n)
                    g.remote_spawns = (g.remote_spawns or 0) + 1

    def tick(self, ms, times=1):
        for _ in range(times):
            for n in self.games:
                if n not in self.down:
                    self.games[n][0].globals().tick(ms)
            self.pump()

fails = 0
def check(what, ok):
    global fails
    print(('ok   ' if ok else 'FAIL ') + what)
    if not ok:
        fails += 1

def loot_made(w, n):
    g = w.G(n)
    return len(g.spawns)

def loot_list(w, n):
    g = w.G(n)
    return sorted(str(g.spawns[i].section) + ':' + str(g.spawns[i].ammo) for i in range(1, len(g.spawns) + 1))

def live(w, n):
    g = w.G(n)
    return sum(1 for i in range(1, len(g.spawns) + 1) if g.objects_se[g.spawns[i].id] is not None)

def shared_count(w, n):
    g = w.G(n)
    return sum(1 for _ in g.shared_ids.items())

def setup(names, seed='12345'):
    w = World(names)
    for n in names:
        w.lua(n, 'G.authority["l01_escape"] = ' + ('true' if n == names[0] else 'false'))
        w.lua(n, 'make_box(500, "esc_box_wood_0001"); make_box(501, "esc_box_wood_0002")')
        w.lua(n, 'ini_sys.r_float_ex = function(self, s, k) if k == "plain_box_loot_chance" then return 1.01 end end')
        if seed:
            w.lua(n, 'G.facts["once:seed:loot"] = "' + seed + '"')
            w.server_facts['once:seed:loot'] = seed
    return w

# 0. the roll is the world's: the same box, the same seed, the same loot in any game
w = setup(['A', 'B'])
la = list(w.lua('A', 'local t = {} for _, x in ipairs(coop_physics_mod.roll_loot("esc_box_wood_0001", "plain", false)) do t[#t+1] = x[1] .. ":" .. tostring(x[2]) end table.sort(t) return table.concat(t, ",")').split(','))
lb = list(w.lua('B', 'local t = {} for _, x in ipairs(coop_physics_mod.roll_loot("esc_box_wood_0001", "plain", false)) do t[#t+1] = x[1] .. ":" .. tostring(x[2]) end table.sort(t) return table.concat(t, ",")').split(','))
check(f'0: the same loot in two games ({len(la)} item(s))', la == lb and la != [''])
lo = w.lua('A', 'local n = 0 for i = 1, 20 do if #coop_physics_mod.roll_loot("box_" .. i, "plain", false) > 0 then n = n + 1 end end return n')
w.lua('A', 'ini_sys.r_float_ex = function() return nil end')
half = w.lua('A', 'local n = 0 for i = 1, 400 do if #coop_physics_mod.roll_loot("box_" .. i, "plain", false) > 0 then n = n + 1 end end return n')
check(f"0: Anomaly's 0.5 chance for a plain box ({half}/400 with loot)", 160 < half < 240)
w.lua('B', 'G.facts["once:seed:loot"] = "999"')
lc = w.lua('B', 'local t = {} for _, x in ipairs(coop_physics_mod.roll_loot("esc_box_wood_0001", "plain", false)) do t[#t+1] = x[1] .. ":" .. tostring(x[2]) end table.sort(t) return table.concat(t, ",")')
check('0: another world (seed), other loot', lc.split(',') != la)

# 1. a player breaks a box: its loot at once, then everyone's
w = setup(['A', 'B', 'C'])
w.lua('B', 'break_box(500)')
n = loot_made(w, 'B')
check(f'1: the breaker has its loot at once, before any answer ({n} item(s))', n > 0 and shared_count(w, 'B') == 0)
w.pump()
check('1: the server says ours: all of it goes to the others', shared_count(w, 'B') == n and w.G('A').remote_spawns == n and w.G('C').remote_spawns == n)
check('1: the others broke their copy, with no loot of their own', w.G('A').hits == 1 and w.G('C').hits == 1 and loot_made(w, 'A') == 0 and loot_made(w, 'C') == 0)
check("1: their release is the breaker's", w.G('A').theirs[500] and w.G('C').theirs[500])
check('1: the claim is on the server', w.server_facts.get('once:box:esc_box_wood_0001') == 'B')
w.tick(1000, 5)
check('1: nothing more later', w.queue == [] and loot_made(w, 'A') == 0)

# 2. two games break it at the same moment (an explosion)
w = setup(['A', 'B', 'C'])
w.lua('A', 'break_box(500)')
w.lua('B', 'break_box(500)')
check('2: both rolled the same loot', loot_list(w, 'A') == loot_list(w, 'B'))
w.pump()
na = loot_made(w, 'A')
check("2: the first claim (A) stays: A's loot shared, B's own gone, never sent", shared_count(w, 'A') == na and shared_count(w, 'B') == 0 and live(w, 'B') == 0 and w.G('B').released == na)
check('2: C got one loot only', w.G('C').remote_spawns == na)

# 3. a box the world has a claim for gives nothing
w = setup(['A', 'B'])
w.lua('B', 'G.facts["once:box:esc_box_wood_0002"] = "A"; break_box(501)')
check('3: broken again where the world had it broken: no loot', loot_made(w, 'B') == 0)

# 3b. no loot seed yet: the first game claims one
w = setup(['A', 'B'], seed='')
w.tick(100)
check('3b: a loot seed claimed, the same for both', w.server_facts.get('once:seed:loot') and w.lua('A', 'return coop.fact("once:seed:loot")') == w.lua('B', 'return coop.fact("once:seed:loot")'))

# 4. single player: Anomaly's own
w = setup(['A'])
w.lua('A', 'G.connected = false; break_box(500)')
check('4: without co-op the box spawns its loot as Anomaly does', loot_made(w, 'A') == 1 and shared_count(w, 'A') == 0)

# 5. doors
w = setup(['A', 'B', 'C'])
for n in ('A', 'B'):
    w.lua(n, 'make_door(700, "bar_door_1", "ph_door@close", true); door_online(700)')
w.lua('C', 'make_door(700, "bar_door_1", "ph_door@close", false)')
w.tick(100)
w.lua('B', 'use_door(700)')
w.pump()
check('5: B opened it: A has it open', w.lua('A', 'return section_of(700)') == 'ph_door@open')
check('5: the fact is on the server', w.server_facts.get('door:bar_door_1', '').split('|')[0] == 'ph_door@open')
check('5: C has it offline: not touched yet', w.lua('C', 'return section_of(700)') == 'ph_door@close')
w.lua('C', 'door_online(700)')
w.tick(100)
check('5: C\'s door comes online open', w.lua('C', 'return section_of(700)') == 'ph_door@open')
# both at once, each from another state (B's door left closed by its own logic): open -> close in A, close -> open in B
w.lua('B', 'db.storage[700].active_section = "ph_door@close"')
w.lua('A', 'use_door(700)')
w.lua('B', 'use_door(700)')
w.pump()
w.tick(100)
sa, sb, sc = (w.lua(n, 'return section_of(700)') for n in 'ABC')
check(f'5: used at once by two: the same door everywhere ({sa}, {sb}, {sc})', sa == sb == sc == w.server_facts['door:bar_door_1'].split('|')[0])
# the world's clock: the fact says since when, and every game counts its timers from there
v = w.server_facts['door:bar_door_1']
sec, act = v.split('|')
check(f"6: the fact carries the moment on the world's clock ({v})", act.isdigit())
w.lua('C', 'G.clock = G.clock + 20000') # C's clock 20 s on (its fact applied late)
w.lua('C', 'db.storage[700].coop_act = nil; coop_physics_mod.set_activation(G.objects[700], ' + act + ')')
ago = w.lua('C', 'return G.game_ms - db.storage[700].activation_game_time.ms')
check(f"6: a game counts the timer from the world's moment ({ago} ms ago)", ago == 20000)
w.lua('C', 'G.clock = G.clock - 20000')
# rolls of a door's logic: the world's random, so a new authority rolls on as the last one would have
w.lua('A', 'G.rolls = {}; door_update(700)')
w.lua('B', 'G.rolls = {}; door_update(700)')
ra = w.G('A').rolls[1]
check('6: a non-authority runs no door logic of its own, rolls nothing', ra is not None and w.G('B').rolls[1] is None)
w.lua('A', 'G.authority["l01_escape"] = false')
w.lua('B', 'G.authority["l01_escape"] = true; door_update(700)')
rb = w.G('B').rolls[1]
check(f"6: a door's ~prob: the next authority rolls the same at the same moment ({ra}, {rb})", ra == rb)
w.lua('A', 'G.authority["l01_escape"] = true')
w.lua('B', 'G.authority["l01_escape"] = false')
# a section asking only infos and timers is the authority's too (players' groups know other infos)
before = w.lua('A', 'return section_of(700)')
other = 'ph_door@open' if before == 'ph_door@close' else 'ph_door@close'
w.lua('B', 'db.storage[700].ph_door.logic = { { name = "on_game_timer", condlist = { { "' + other + '", {} } } } }')
w.lua('B', 'xr_logic.switch_to_section(G.objects[700], db.storage[700].ini, "' + other + '")')
w.pump()
check('6: a timer switch off the authority is not told', w.lua('A', 'return section_of(700)') == before)
w.lua('B', 'xr_logic.switch_to_section(G.objects[700], db.storage[700].ini, "' + before + '")')
w.lua('A', 'db.storage[700].ph_door.logic = { { name = "on_game_timer", condlist = { { "ph_door@open", {} } } } }')
w.lua('A', 'xr_logic.switch_to_section(G.objects[700], db.storage[700].ini, "ph_door@open")')
w.pump()
check("6: the authority's timer switch reaches everyone", w.lua('B', 'return section_of(700)') == 'ph_door@open')
w.lua('A', 'db.storage[700].ph_door.logic = {}')
w.lua('B', 'db.storage[700].ph_door.logic = { { name = "on_info", condlist = { { "ph_door@close", { { "dist_to_actor_le", 3, {} } } } } } }')
w.lua('B', 'xr_logic.switch_to_section(G.objects[700], db.storage[700].ini, "ph_door@close")')
w.pump()
check('6: a switch asking about the player off the authority is not told', w.lua('A', 'return section_of(700)') == 'ph_door@open')
w.lua('B', 'xr_logic.switch_to_section(G.objects[700], db.storage[700].ini, "ph_door@open")') # back, as A has it
w.lua('B', 'db.storage[700].ph_door.logic = {}')

# a door just online: its own logic (from its save) isn't told before the world's word is put on it
w.lua('B', 'make_door(701, "bar_door_2", "ph_door@close", false); local o = G.objects[701]; o.online = true; o.binder.net_spawn(o.binder, {})')
w.lua('B', 'xr_logic.switch_to_section(G.objects[701], db.storage[701].ini, "ph_door@open")')
w.pump()
check("6: a door just online, before the world's word: its switch is not told", 'door:bar_door_2' not in w.server_facts)

# NPCs: the authority's only
w.lua('B', 'ph_door.try_to_open_door({}, {})')
w.lua('A', 'ph_door.try_to_open_door({}, {})')
check('5: an NPC opens doors in the authority\'s game only', not w.G('B').npc_door_calls and w.G('A').npc_door_calls == 1)
# a logic switch asking about the player in a non-authority game is its own; the authority's goes to all
w.pump()
before = w.lua('A', 'return section_of(700)')
w.lua('B', 'db.storage[700].ph_door.logic = { { name = "on_actor_dist_le", condlist = {} } }')
w.lua('B', 'xr_logic.switch_to_section(G.objects[700], db.storage[700].ini, "ph_door@close")')
w.pump()
check('5: a logic switch asking about the player off the authority is not sent', before == 'ph_door@open' and w.lua('A', 'return section_of(700)') == before)
w.lua('A', 'xr_logic.switch_to_section(G.objects[700], db.storage[700].ini, "ph_door@close")')
w.pump()
check('5: the authority\'s logic switch reaches everyone', all(w.lua(n, 'return section_of(700)') == 'ph_door@close' for n in 'ABC'))

check("5: a door with a motor is its logic's, not the engine's rests", all(w.G(n).by_logic[700] == True for n in 'ABC'))
w.lua('A', 'db.storage[700].ph_door = { no_force = true }; xr_logic.switch_to_section(G.objects[700], db.storage[700].ini, "ph_door@open")')
check("5: a door swinging free is the engine's rests", w.G('A').by_logic[700] == False)

# 7. a door whose logic asks about the player: the level's authority runs it, for all the level's players
def place(w, pos, ages=None, levels=None):
    # pos: game -> (x, y, z) of its player; each game has its own actor there and the others as peers
    for n in w.games:
        x, y, z = pos[n]
        peers = []
        for m, (px, py, pz) in pos.items():
            if m == n:
                continue
            age = (ages or {}).get(m, 0)
            lvl = (levels or {}).get(m, 'l01_escape')
            peers.append(f'{{ id = {ord(m)}, name = "{m}", level = "{lvl}", position = {{ x = {px}, y = {py}, z = {pz} }}, age = {age} }}')
        w.lua(n, f'G.actor_pos = {{ x = {x}, y = {y}, z = {z} }}; G.peers = {{ {", ".join(peers)} }}; G.now = G.now + 1')

def sec(w, n, door):
    return w.lua(n, f'return section_of({door})')

def fx(w, n):
    g = w.G(n)
    return [g.fx[i] for i in range(1, len(g.fx) + 1)]

def clear_fx(w):
    for n in w.games:
        w.lua(n, 'G.fx = {}; G.door_hits = 0')

KNOCK = '''{
    ["ph_door@horror_knock"] = { { "on_info", "{=dist_to_actor_le(8)} ph_door@horror_wait %=hit_npc(warlab_point_knock_1:door:0:1500) =play_particle_on_path(hit_fx:warlab_knock_points_1:70) =play_sound(trader_door_close_stop) =spawn_thing(x)%, ph_door@horror_silence" } },
    ["ph_door@horror_wait"] = { { "on_timer", 5000, "ph_door@horror_knock" } },
    ["ph_door@horror_silence"] = { { "on_timer", 5000, "ph_door@horror_knock" } },
}'''

w = setup(['A', 'B', 'C'])
for n in 'ABC':
    w.lua(n, f'make_logic_door(710, "warlab_door_1", "ph_door@horror_knock", {KNOCK})')
w.tick(100)
place(w, {'A': (100, 0, 0), 'B': (5, 0, 0), 'C': (60, 0, 0)})
for n in 'BC':
    w.lua(n, 'door_update(710)')
w.pump()
check('7: B (its player 5 m from the door) and C run no such logic of their own',
      sec(w, 'B', 710) == sec(w, 'C', 710) == 'ph_door@horror_knock' and not w.G('B').evaluated and not w.G('C').evaluated
      and 'door:warlab_door_1' not in w.server_facts)
w.lua('A', 'door_update(710)')
check("7: the authority (its own player 100 m away) takes B's 5 m: the door knocks", sec(w, 'A', 710) == 'ph_door@horror_wait')
check('7: the knock plays at the authority as Anomaly has it', fx(w, 'A') == ['hit_npc:warlab_door_1', 'play_particle_on_path:warlab_door_1', 'play_sound:warlab_door_1', 'spawn_thing:warlab_door_1'] and w.G('A').door_hits == 1)
w.pump()
check('7: every game has the door as the authority told', sec(w, 'B', 710) == sec(w, 'C', 710) == 'ph_door@horror_wait'
      and w.server_facts['door:warlab_door_1'].split('|')[0] == 'ph_door@horror_wait')
check('7: the others play the knock too (sound, particles, the hit), not what changes the world',
      fx(w, 'B') == fx(w, 'C') == ['hit_npc:warlab_door_1', 'play_particle_on_path:warlab_door_1', 'play_sound:warlab_door_1'])
check("7: the knock played there is no hit of theirs (the door's hit callback isn't run)", not w.G('B').door_hits and not w.G('C').door_hits)
fact_before = w.server_facts['door:warlab_door_1']
for _ in range(5):
    for n in 'ABC':
        w.lua(n, 'door_update(710)')
    w.pump()
    w.tick(100)
check('7: no back and forth: rounds of every game later, one door, one fact',
      sec(w, 'A', 710) == sec(w, 'B', 710) == sec(w, 'C', 710) == 'ph_door@horror_wait' and w.server_facts['door:warlab_door_1'] == fact_before)

# the nearest of all, whoever he is
def knock_again(w, decider='A'):
    w.lua(decider, 'xr_logic.switch_to_section(G.objects[710], db.storage[710].ini, "ph_door@horror_knock")')
    w.pump()
    clear_fx(w)

knock_again(w)
place(w, {'A': (6, 0, 0), 'B': (100, 0, 0), 'C': (60, 0, 0)})
w.lua('A', 'door_update(710)')
w.pump()
check("7: the authority's own player near: the same knock", all(sec(w, n, 710) == 'ph_door@horror_wait' for n in 'ABC'))
knock_again(w)
place(w, {'A': (50, 0, 0), 'B': (30, 0, 0), 'C': (9, 0, 0)})
for n in 'BCA':
    w.lua(n, 'door_update(710)')
w.pump()
check('7: nobody within 8 m (nearest 9 m): silence everywhere', all(sec(w, n, 710) == 'ph_door@horror_silence' for n in 'ABC'))

# the authority moves to B: the same answer from the same players
knock_again(w)
for n in 'ABC':
    w.lua(n, 'G.authority["l01_escape"] = ' + ('true' if n == 'B' else 'false'))
place(w, {'A': (7, 0, 0), 'B': (100, 0, 0), 'C': (60, 0, 0)})
w.lua('A', 'door_update(710)')
w.pump()
check('7: A is no authority any more: its near player is for B to tell', all(sec(w, n, 710) == 'ph_door@horror_knock' for n in 'ABC'))
w.lua('B', 'door_update(710)')
w.pump()
check("7: the new authority (B, 100 m away) tells it by A's 7 m", all(sec(w, n, 710) == 'ph_door@horror_wait' for n in 'ABC'))

# a stale player or one on another level is no player here
knock_again(w, 'B')
place(w, {'A': (5, 0, 0), 'B': (100, 0, 0), 'C': (4, 0, 0)}, ages={'A': 20000}, levels={'C': 'l02_garbage'})
w.lua('B', 'door_update(710)')
check('7: a player not heard from for 20 s or on another level counts for nothing', sec(w, 'B', 710) == 'ph_door@horror_silence')

# xr_logic's own distance conditions (on_actor_dist_le_nvis): the nearest player too
w = setup(['A', 'B'])
for n in 'AB':
    w.lua(n, '''make_logic_door(740, "dist_door", "ph_door@close", {
        ["ph_door@close"] = { { "on_actor_dist_le_nvis", 4, "ph_door@open" } },
        ["ph_door@open"] = { { "on_actor_dist_ge_nvis", 10, "ph_door@close" } } })''')
w.tick(100)
place(w, {'A': (50, 0, 0), 'B': (3, 0, 0)})
w.lua('A', 'door_update(740)')
w.pump()
check('7: on_actor_dist_le_nvis: the nearest player (B at 3 m)', sec(w, 'A', 740) == sec(w, 'B', 740) == 'ph_door@open')
w.lua('A', 'door_update(740)')
check('7: on_actor_dist_ge_nvis: closes only when every player is farther (B still at 3 m)', sec(w, 'A', 740) == 'ph_door@open')
place(w, {'A': (50, 0, 0), 'B': (30, 0, 0)})
w.lua('A', 'door_update(740)')
check('7: ... and closes once all are', sec(w, 'A', 740) == 'ph_door@close')

# 8. zones: any player in it is "in", none in it is "out"
w = setup(['A', 'B', 'C'])
for n in 'ABC':
    w.lua(n, '''make_zone("trader_into", 0, 0, 0, 3); make_zone("red_forester_restr", 200, 0, 0, 10); make_zone("jup_zone", -200, 0, 0, 10)
    make_logic_door(720, "esc_trader_door", "ph_door@close", {
        ["ph_door@close"] = { { "on_actor_in_zone", "trader_into", "ph_door@near" } },
        ["ph_door@near"] = {},
        ["ph_door@open"] = { { "on_actor_not_in_zone", "trader_into", "ph_door@close" } } })
    make_logic_door(721, "red_forester_door", "ph_door@open", {
        ["ph_door@open"] = { { "on_info", "{=actor_out_zone(red_forester_restr)} ph_door@close" } },
        ["ph_door@close"] = {} })
    make_logic_door(722, "jup_b1_door", "ph_door@locked", {
        ["ph_door@locked"] = { { "on_info", "{=actor_in_zone(jup_zone)} ph_door@close" } },
        ["ph_door@close"] = { { "on_info", "{!actor_in_zone(jup_zone)} ph_door@locked" } } })''')
w.tick(100)
place(w, {'A': (50, 0, 0), 'B': (1, 0, 0), 'C': (40, 0, 0)})
w.lua('B', 'db.actor_inside_zones["trader_into"] = db.zone_by_name["trader_into"]') # the restrictor told B's game
w.lua('B', 'door_update(720)')
w.lua('A', 'door_update(720)')
w.pump()
check('8: on_actor_in_zone: B in the zone, the authority outside: near, everywhere', all(sec(w, n, 720) == 'ph_door@near' for n in 'ABC'))
w.lua('A', 'xr_logic.switch_to_section(G.objects[720], db.storage[720].ini, "ph_door@open")')
w.pump()
w.lua('A', 'door_update(720)')
check('8: on_actor_not_in_zone: B still in it, the door stays open', sec(w, 'A', 720) == 'ph_door@open')
place(w, {'A': (50, 0, 0), 'B': (20, 0, 0), 'C': (40, 0, 0)})
w.lua('A', 'door_update(720)')
w.pump()
check('8: ... closes once nobody is in it', all(sec(w, n, 720) == 'ph_door@close' for n in 'ABC'))
place(w, {'A': (50, 0, 0), 'B': (20, 0, 0), 'C': (40, 0, 0)})
w.lua('A', 'db.actor_inside_zones["trader_into"] = db.zone_by_name["trader_into"]') # the authority's own player, as its restrictor tells
w.lua('A', 'door_update(720)')
check("8: the authority's own player in the zone counts as its restrictor tells", sec(w, 'A', 720) == 'ph_door@near')

place(w, {'A': (50, 0, 0), 'B': (201, 0, 0), 'C': (40, 0, 0)})
w.lua('A', 'door_update(721)')
check('8: =actor_out_zone: B is in the forester\'s zone, the door stays open', sec(w, 'A', 721) == 'ph_door@open')
place(w, {'A': (50, 0, 0), 'B': (220, 0, 0), 'C': (40, 0, 0)})
w.lua('A', 'door_update(721)')
w.pump()
check('8: ... closes when nobody is', all(sec(w, n, 721) == 'ph_door@close' for n in 'ABC'))

place(w, {'A': (50, 0, 0), 'B': (20, 0, 0), 'C': (-205, 0, 0)})
w.lua('A', 'door_update(722)')
w.pump()
check('8: =actor_in_zone: C in the zone opens the lock for all', all(sec(w, n, 722) == 'ph_door@close' for n in 'ABC'))
w.lua('A', 'door_update(722)')
check('8: !actor_in_zone: locks again only when nobody is in it (C still is)', sec(w, 'A', 722) == 'ph_door@close')
place(w, {'A': (50, 0, 0), 'B': (20, 0, 0), 'C': (-150, 0, 0)})
w.lua('A', 'door_update(722)')
check('8: ... C out: locked', sec(w, 'A', 722) == 'ph_door@locked')

# 9. keys: each game tells what its player carries of what doors ask about; a key counts for its holder at the door
w = setup(['A', 'B', 'C'])
for n in 'ABC':
    w.lua(n, '''make_logic_door(730, "warlab_pod_room_door", "ph_door@locked", {
        ["ph_door@locked"] = { { "on_info", "{=actor_has_item(decoder)} ph_door@coded" } },
        ["ph_door@coded"] = { { "on_info", "{!actor_has_item(decoder)} ph_door@locked" },
            { "on_use", "ph_door@decoding %+warlab_access_decoding =play_sound(warlab_decoder)%" } },
        ["ph_door@decoding"] = {} })
    make_logic_door(731, "lab_door", "ph_door@closed", {
        ["ph_door@closed"] = { { "on_info", "{=actor_has_item(lab_key)} ph_door@open" } },
        ["ph_door@open"] = {} })
    make_logic_door(732, "lx8_transformer_door", "ph_door@no_key", {
        ["ph_door@no_key"] = { { "on_info", "{=actor_has_item(lx8_key)} ph_door@closed" } },
        ["ph_door@closed"] = { { "on_info", "{!actor_has_item(lx8_key)} ph_door@no_key" },
            { "on_use", "ph_door@open %=remove_item(lx8_key)%" } },
        ["ph_door@open"] = {} })''')
w.tick(100)
place(w, {'A': (50, 0, 0), 'B': (500, 0, 0), 'C': (40, 0, 0)})
w.lua('B', 'G.inv.decoder = {}')
w.tick(1000)
check('9: B tells it carries a decoder (carry_items)', w.server_facts.get('carry:B') == 'decoder' and w.lua('A', 'return coop.fact("carry:B")') == 'decoder')
w.lua('A', 'door_update(730)')
w.pump()
check('9: B has the decoder but is elsewhere on the level: the door stays locked', all(sec(w, n, 730) == 'ph_door@locked' for n in 'ABC'))
place(w, {'A': (50, 0, 0), 'B': (3, 0, 0), 'C': (40, 0, 0)})
w.lua('A', 'door_update(730)')
w.pump()
check('9: B with the decoder at the door (within key_reach_m): coded for everyone', all(sec(w, n, 730) == 'ph_door@coded' for n in 'ABC'))
w.lua('A', 'door_update(730)')
check('9: !actor_has_item: it stays coded while B is there with it', sec(w, 'A', 730) == 'ph_door@coded')
place(w, {'A': (50, 0, 0), 'B': (3, 0, 0), 'C': (1, 0, 0)})
w.lua('C', 'use_door(730)')
w.pump()
check("9: C, at the door without the decoder, can't use it (B is right there)",
      all(sec(w, n, 730) == 'ph_door@coded' for n in 'ABC') and w.G('C').uses == 1 and not w.G('C').given)
clear_fx(w)
w.lua('B', 'use_door(730)')
w.pump()
check("9: the sound of B's use (the decoder's) plays for the others too",
      all(fx(w, n) == ['play_sound:warlab_pod_room_door'] for n in 'ABC'))
check("9: B uses it: decoding for everyone, the use's info is B's (his game gives it)",
      all(sec(w, n, 730) == 'ph_door@decoding' for n in 'ABC') and w.G('B').given == '+warlab_access_decoding'
      and not w.G('A').given and not w.G('C').given)
w.lua('A', 'xr_logic.switch_to_section(G.objects[730], db.storage[730].ini, "ph_door@coded")')
w.pump()
place(w, {'A': (50, 0, 0), 'B': (30, 0, 0), 'C': (1, 0, 0)})
w.lua('A', 'door_update(730)')
w.pump()
check('9: B walks away with the decoder (C still at the door): locked again', all(sec(w, n, 730) == 'ph_door@locked' for n in 'ABC'))
place(w, {'A': (50, 0, 0), 'B': (3, 0, 0), 'C': (40, 0, 0)})
w.lua('A', 'door_update(730)')
w.lua('B', 'G.inv.decoder = nil')
w.tick(1000)
w.lua('A', 'door_update(730)')
w.pump()
check('9: B drops it at the door: locked again', w.server_facts.get('carry:B', 'x') == '' and all(sec(w, n, 730) == 'ph_door@locked' for n in 'ABC'))
place(w, {'A': (2, 0, 0), 'B': (30, 0, 0), 'C': (40, 0, 0)})
w.lua('A', 'G.inv.decoder = {}')
w.lua('A', 'door_update(730)')
check("9: the authority's own player at the door: its decoder counts from its inventory", sec(w, 'A', 730) == 'ph_door@coded')
w.lua('A', 'G.inv.decoder = nil; xr_logic.switch_to_section(G.objects[730], db.storage[730].ini, "ph_door@locked")')
w.lua('C', 'G.inv.decoder = {}')
w.tick(1000)
place(w, {'A': (50, 0, 0), 'B': (500, 0, 0), 'C': (1, 0, 0)}, levels={'C': 'l02_garbage'})
w.lua('A', 'door_update(730)')
check('9: a decoder on another level opens nothing here', sec(w, 'A', 730) == 'ph_door@locked')
w.lua('C', 'G.inv.decoder = nil')
w.tick(1000)
# the key used: the door takes it from its holder's game, nobody else's
w.pump()
place(w, {'A': (50, 0, 0), 'B': (2, 0, 0), 'C': (1, 0, 0)})
w.lua('B', 'G.inv.lx8_key = {}')
w.lua('B', 'door_update(732)') # B's game hasn't the door's logic yet: lx8_key isn't in carry_items
w.tick(1000)
w.lua('A', 'door_update(732)')
w.pump()
check('9: an item no list has: B tells it once a door online in B asks about it, the door is usable', w.server_facts.get('carry:B') == 'lx8_key'
      and all(sec(w, n, 732) == 'ph_door@closed' for n in 'ABC'))
w.lua('C', 'G.inv.lx8_key = nil; use_door(732)')
w.pump()
check("9: C without the key can't open it", all(sec(w, n, 732) == 'ph_door@closed' for n in 'ABC'))
w.lua('B', 'use_door(732)')
w.pump()
check("9: B opens it with his key, the key goes from B's game", all(sec(w, n, 732) == 'ph_door@open' for n in 'ABC')
      and w.lua('B', 'return G.inv.lx8_key') is None and 'remove_item:lx8_key' in fx(w, 'B') and 'remove_item:lx8_key' not in fx(w, 'A') + fx(w, 'C'))
# the headless host has no player: its own actor counts for nothing, and it tells nothing it carries
place(w, {'A': (1, 0, 0), 'B': (500, 0, 0), 'C': (40, 0, 0)})
w.lua('A', 'coop.is_host = function() return true end; G.inv.decoder = {}; G.now = G.now + 1')
w.lua('A', 'door_update(730)')
w.tick(1000)
check('9: the headless host: its own actor is no player', sec(w, 'A', 730) == 'ph_door@locked' and w.server_facts.get('carry:A', '') == '')

# 11. infos a switch the authority made gives: to the player it was for, his game gives them (coop_story takes them
# along his group); taking a door's flag away: from every player of the level who has it
w = setup(['A', 'B', 'C'])
for n in 'ABC':
    w.lua(n, '''make_zone("b303_rest", 0, 0, 0, 3)
    make_logic_door(750, "pri_b303_one_side_door", "ph_door@closed_out", {
        ["ph_door@closed_out"] = { { "on_info", "{=actor_in_zone(b303_rest)} ph_door@closed_in %+pri_b303_door_is_open%" } },
        ["ph_door@closed_in"] = {} })
    make_logic_door(751, "pri_a16_ph_door", "ph_door@close", {
        ["ph_door@close"] = { { "on_use", "ph_door@open %+pri_a16_door_open%" },
            { "on_info", "{+pri_a16_door_open !is_door_blocked_by_npc} ph_door@open" } },
        ["ph_door@open"] = { { "on_use", "ph_door@close %-pri_a16_door_open%" },
            { "on_info", "{-pri_a16_door_open !is_door_blocked_by_npc} ph_door@close" },
            { "on_info", "{+shut_now} ph_door@close %-pri_a16_door_open%" } } })
    make_logic_door(752, "warlab_door_1", "ph_door@horror_knock", {
        ["ph_door@horror_knock"] = { { "on_info", "{+warlab_main_polter_dead} ph_door@open %+warlab_open_door_1 =play_sound(trader_door_unlock)%" } },
        ["ph_door@open"] = {} })''')
w.tick(100)
place(w, {'A': (50, 0, 0), 'B': (1, 0, 0), 'C': (40, 0, 0)})
w.lua('A', 'door_update(750)')
w.pump()
check("11: B in the zone: the door goes, its info goes to B's game, not the authority's",
      all(sec(w, n, 750) == 'ph_door@closed_in' for n in 'ABC') and w.G('B').given == '+pri_b303_door_is_open'
      and not w.G('A').given and not w.G('C').given)
w.lua('A', 'xr_logic.switch_to_section(G.objects[750], db.storage[750].ini, "ph_door@closed_out")')
w.pump()
w.lua('B', 'G.given = nil; G.infos = {}')
place(w, {'A': (1, 0, 0), 'B': (30, 0, 0), 'C': (40, 0, 0)})
w.lua('A', 'db.actor_inside_zones["b303_rest"] = db.zone_by_name["b303_rest"]; door_update(750)')
w.pump()
check("11: the authority's own player in the zone: its own game gives it", w.G('A').given == '+pri_b303_door_is_open' and not w.G('B').given)
# a door's own flag: B (not the authority) opens it; the authority reads B's flag and leaves it open
place(w, {'A': (50, 0, 0), 'B': (1, 0, 0), 'C': (40, 0, 0)})
w.lua('B', 'use_door(751)')
w.pump()
w.lua('A', 'door_update(751)')
w.pump()
check("11: B opens a door that keeps its flag in an info: B has the flag, the authority sees it and leaves the door open",
      all(sec(w, n, 751) == 'ph_door@open' for n in 'ABC') and w.server_facts.get('knows:B') == 'pri_a16_door_open')
w.lua('C', 'G.infos.pri_a16_door_open = true; door_update(751)')
w.tick(1000)
w.lua('A', 'G.infos.shut_now = true; door_update(751)')
w.pump()
w.tick(1000)
check('11: the authority shuts it by its logic: the flag goes from every player of the level holding it (B, C)',
      all(sec(w, n, 751) == 'ph_door@close' for n in 'ABC') and not w.lua('B', 'return G.infos.pri_a16_door_open')
      and not w.lua('C', 'return G.infos.pri_a16_door_open') and w.server_facts.get('knows:B') == '' and w.server_facts.get('knows:C') == '')
w.lua('A', 'G.infos.shut_now = nil; door_update(751)')
w.pump()
check('11: ... and it stays shut (no player keeps the flag)', all(sec(w, n, 751) == 'ph_door@close' for n in 'ABC'))
# a section asking only infos: the authority asks all the players; the info its way out gives goes to the one it was for
place(w, {'A': (50, 0, 0), 'B': (30, 0, 0), 'C': (2, 0, 0)})
for n in 'ABC':
    w.lua(n, 'G.given = nil')
w.lua('B', 'G.infos.warlab_main_polter_dead = true; door_update(752)')
w.tick(1000)
w.lua('C', 'door_update(752)')
w.lua('A', 'door_update(752)')
check("11: B's group killed the poltergeist, the authority's didn't: the door opens by B's info",
      w.server_facts.get('knows:B') and 'warlab_main_polter_dead' in w.server_facts['knows:B'] and sec(w, 'A', 752) == 'ph_door@open')
clear_fx(w)
w.pump()
check("11: its info goes to B (the one who knew), the others play its sound",
      w.G('B').given == '+warlab_open_door_1' and not w.G('A').given and not w.G('C').given
      and all(sec(w, n, 752) == 'ph_door@open' for n in 'BC') and fx(w, 'B') == fx(w, 'C') == ['play_sound:warlab_door_1'])


# 10. single player: Anomaly's own, its own actor only
w = setup(['A'])
w.lua('A', f'G.connected = false; make_logic_door(710, "warlab_door_1", "ph_door@horror_knock", {KNOCK})')
place(w, {'A': (100, 0, 0)})
w.lua('A', 'G.peers = { { id = 66, name = "B", level = "l01_escape", position = { x = 1, y = 0, z = 0 }, age = 0 } }')
w.lua('A', 'door_update(710)')
check('10: without co-op the door asks about our actor alone', sec(w, 'A', 710) == 'ph_door@horror_silence' and w.G('A').door_hits in (None, 0))

for n in 'ABC':
    if n in w.games:
        for line in list(w.G(n).log.values()):
            if line.startswith('!'):
                print(n, line)
print('FAILS:', fails)
sys.exit(1 if fails else 0)
