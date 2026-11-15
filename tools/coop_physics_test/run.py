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
check('5: the fact is on the server', w.server_facts.get('door:bar_door_1') == 'ph_door@open')
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
check(f'5: used at once by two: the same door everywhere ({sa}, {sb}, {sc})', sa == sb == sc == w.server_facts['door:bar_door_1'])
# NPCs: the authority's only
w.lua('B', 'ph_door.try_to_open_door({}, {})')
w.lua('A', 'ph_door.try_to_open_door({}, {})')
check('5: an NPC opens doors in the authority\'s game only', not w.G('B').npc_door_calls and w.G('A').npc_door_calls == 1)
# a logic switch in a non-authority game is its own; the authority's goes to all
w.lua('B', 'xr_logic.switch_to_section(G.objects[700], db.storage[700].ini, "ph_door@close")')
w.pump()
check('5: a logic switch off the authority is not sent', w.lua('A', 'return section_of(700)') == sa)
w.lua('A', 'xr_logic.switch_to_section(G.objects[700], db.storage[700].ini, "ph_door@close")')
w.pump()
check('5: the authority\'s logic switch reaches everyone', all(w.lua(n, 'return section_of(700)') == 'ph_door@close' for n in 'ABC'))

check("5: a door with a motor is its logic's, not the engine's rests", all(w.G(n).by_logic[700] == True for n in 'ABC'))
w.lua('A', 'db.storage[700].ph_door = { no_force = true }; xr_logic.switch_to_section(G.objects[700], db.storage[700].ini, "ph_door@open")')
check("5: a door swinging free is the engine's rests", w.G('A').by_logic[700] == False)

for n in 'ABC':
    if n in w.games:
        for line in list(w.G(n).log.values()):
            if line.startswith('!'):
                print(n, line)
print('FAILS:', fails)
sys.exit(1 if fails else 0)
