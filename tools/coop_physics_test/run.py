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
    return sum(1 for i in range(1, len(g.spawns) + 1) if g.spawns[i] is not None)

def shared_loot(w, n):
    g = w.G(n)
    return sum(1 for i in range(1, len(g.spawns) + 1) if g.spawns[i].shared)

def setup(names, authority):
    w = World(names)
    for n in names:
        w.lua(n, f'G.authority["l01_escape"] = {"true" if n == authority else "false"}')
        w.lua(n, 'math.randomseed(1); make_box(500, "esc_box_wood_0001")')
    return w

# 1. a player who isn't the authority breaks a box
w = setup(['A', 'B', 'C'], 'A')
w.lua('B', 'break_box(500)')
w.pump()
check('1: the breaker spawns no loot of its own', loot_made(w, 'B') == 0)
check('1: the authority made the loot, shared (0 or 2 items: the plain box chance)', loot_made(w, 'A') in (0, 2) and loot_made(w, 'A') == shared_loot(w, 'A'))
check('1: the others got the same items (as spawns)', (w.G('B').remote_spawns or 0) == loot_made(w, 'A') and (w.G('C').remote_spawns or 0) == loot_made(w, 'A'))
check('1: C broke its copy, with no loot', w.G('C').hits == 1 and loot_made(w, 'C') == 0)
check('1: the box is a fact on the server', w.server_facts.get('box:esc_box_wood_0001') in ('0', '1'))
w.tick(1000, 20)
check('1: nobody decides it again later', loot_made(w, 'B') == 0 and loot_made(w, 'C') == 0 and w.queue == [])

# 1b. force the loot on: chance 1 (ini), a drop for sure
w = setup(['A', 'B'], 'A')
w.lua('A', 'ini_sys.r_float_ex = function(s, k) if k == "plain_box_loot_chance" then return 1.01 end end')
w.lua('B', 'break_box(500)')
w.pump()
check('1b: chance 1 -> two shared items from the authority, two spawns at B', shared_loot(w, 'A') == 2 and w.G('B').remote_spawns == 2)

# 2. an explosion breaks it in two games at once (the authority and another)
w = setup(['A', 'B'], 'A')
w.lua('A', 'ini_sys.r_float_ex = function(s, k) if k == "plain_box_loot_chance" then return 1.01 end end')
w.lua('A', 'break_box(500)')
w.lua('B', 'break_box(500)')
w.pump()
w.tick(1000, 20)
check('2: one loot for the world', shared_loot(w, 'A') == 2 and loot_made(w, 'B') == 0 and w.G('B').remote_spawns == 2)

# 2b. two non-authority games break it at once
w = setup(['A', 'B', 'C'], 'A')
w.lua('A', 'ini_sys.r_float_ex = function(s, k) if k == "plain_box_loot_chance" then return 1.01 end end')
w.lua('B', 'break_box(500)')
w.lua('C', 'break_box(500)')
w.pump()
w.tick(1000, 20)
check('2b: one loot for the world', shared_loot(w, 'A') == 2 and loot_made(w, 'B') == 0 and loot_made(w, 'C') == 0)

# 3. the authority is gone: the breaker decides after confirm_s x confirm_tries
w = setup(['A', 'B'], 'A')
w.down.add('A')
w.lua('B', 'ini_sys.r_float_ex = function(s, k) if k == "plain_box_loot_chance" then return 1.01 end end')
w.lua('B', 'break_box(500)')
w.pump()
w.tick(1000, 4)
check('3: still waiting at 4 s', loot_made(w, 'B') == 0)
w.tick(1000, 8)
check('3: decided by the breaker itself after the tries', shared_loot(w, 'B') == 2)

# 4. single player: Anomaly's own
w = setup(['A'], 'A')
w.lua('A', 'G.connected = false; break_box(500)')
check('4: without co-op the box spawns its loot as Anomaly does', loot_made(w, 'A') == 2 and shared_loot(w, 'A') == 0)

# 5. doors
w = setup(['A', 'B', 'C'], 'A')
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

for n in 'ABC':
    if n in w.games:
        for line in list(w.G(n).log.values()):
            if line.startswith('!'):
                print(n, line)
print('FAILS:', fails)
sys.exit(1 if fails else 0)
