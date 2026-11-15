# Offline checks of the co-op scripts of batch G (python run.py; needs lupa). A stub "game": a LuaRuntime with Anomaly-ish globals, co-op facts shared through a Python dict.
import lupa.luajit21 as L

import os
REPO = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'gamedata', 'scripts') + os.sep

PRELUDE = r'''
callbacks = {}
function RegisterScriptCallback(name, f) callbacks[name] = callbacks[name] or {}; table.insert(callbacks[name], f) end
function fire(name, ...) for _, f in ipairs(callbacks[name] or {}) do f(...) end end
function printf(fmt, ...) log_line(string.format(fmt, ...)) end
function load_module(name, src)
  local f, err = loadstring(src, name)
  if not f then error(err) end
  local env = setmetatable({}, {__index = _G})
  _G[name] = env
  setfenv(f, env)
  f()
  return env
end
-- vectors
local V = {}
V.__index = V
function V:set(x, y, z) if type(x) == "table" then self.x, self.y, self.z = x.x, x.y, x.z else self.x, self.y, self.z = x, y, z end return self end
function V:distance_to_sqr(o) local dx, dy, dz = self.x-o.x, self.y-o.y, self.z-o.z return dx*dx+dy*dy+dz*dz end
function vector() return setmetatable({x=0,y=0,z=0}, V) end
function distance_2d(a, b) local dx, dz = a.x-b.x, a.z-b.z return math.sqrt(dx*dx+dz*dz) end
console = { get_integer = function(self, k) return 1 end }
function get_console() return console end
ini_values = {}
ini_sys = { r_float_ex = function(self, s, k) return ini_values[s .. "." .. k] end,
            r_string_ex = function(self, s, k) return ini_values[s .. "." .. k] end }
now_ms = 0
function time_global() return now_ms end
function random_key_table(t) local keys = {} for k in pairs(t) do keys[#keys+1] = k end table.sort(keys) return keys[math.random(#keys)] end
'''

class Game:
    def __init__(self, name, facts, peers_of, seed=1):
        self.name = name
        self.facts = facts
        self.lua = L.LuaRuntime(unpack_returned_tuples=True)
        self.log = []
        g = self.lua.globals()
        g.log_line = lambda s: self.log.append(s)
        self.lua.execute(PRELUDE)
        self.lua.execute('math.randomseed(%d)' % seed)
        self.authority = False
        self.host = False
        self.events = []
        self.clock = 0.0
        game = self
        coop = self.lua.table_from({})
        coop['connected'] = lambda: True
        coop['fact'] = lambda k: facts.get(k, '')
        def report(k, v):
            facts[k] = v
            game.reported.append((k, v))
        self.reported = []
        coop['report_fact'] = report
        coop['is_authority'] = lambda lvl: game.authority
        coop['is_sim_master'] = lambda: game.authority
        coop['is_host'] = lambda: game.host
        coop['my_name'] = lambda: name
        coop['clock'] = lambda: game.clock
        g.coop = coop
        self.lua.execute('peer_list = {}; coop.peers = function() return peer_list end')

    def run(self, code):
        return self.lua.execute(code)

    def load(self, name, path=None):
        src = open(path or (REPO + name + '.script'), 'rb').read().decode('cp1251')
        return self.lua.globals().load_module(name, src)
