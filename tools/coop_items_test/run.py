# Offline checks (lupa, LuaJIT) of coop_items.script's item state for the world (Notion audit, item 10) and of the item
# Lua data in coop_sync.script, on stub games: things a script set up after making them (ItemProcessor), WPO parts
# rolled the same in every game, live NPCs' weapon wear from the level's authority. python run.py
import os, sys
import lupa.luajit21 as L

SCRIPTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'gamedata', 'scripts') + os.sep

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
console = { get_integer = function(self, k) return 1 end }
function get_console() return console end
ini_values = {}
ini_sys = { r_float_ex = function(self, s, k) return ini_values[s .. "." .. k] end,
            r_bool_ex = function(self, s, k) return ini_values[s .. "." .. k] end }
now_ms = 0
function time_global() return now_ms end
-- time events: fired by run_events() once due
events = {}
function CreateTimeEvent(ev, act, delay, f, ...) events[ev .. "/" .. act] = { at = now_ms + delay * 1000, f = f, args = {...} } end
function run_events()
  for k, e in pairs(events) do
    if now_ms >= e.at and e.f(unpack(e.args)) then events[k] = nil end
  end
end
function str_explode(s, sep) local t = {} for p in string.gmatch(s, "([^" .. sep .. "]+)") do t[#t+1] = p end return t end
function random_key_table(t) local n = {} for k in pairs(t) do n[#n+1] = k end table.sort(n) return #n > 0 and n[math.random(#n)] or nil end
-- objects: online ones in level.object_by_id, server ones in alife_object
objects, se_objects = {}, {}
level = { object_by_id = function(id) return objects[id] end, name = function() return "l01_escape" end }
function alife_object(id) return se_objects[id] end
multiuse = {}
function IsItem(kind, sec) return kind == "multiuse" and multiuse[sec] or false end
function IsWeapon(obj) return obj.weapon end
se_vars = {}
function se_load_var(id, name, key) return se_vars[id .. "." .. key] end
function se_save_var(id, name, key, v) se_vars[id .. "." .. key] = v end
db = { OnlineStalkers = {} }
death_manager = { decide_items_to_keep = function() end }
coop_sync = { on_event = function() end, send_event = function() end }
'''

ITEM = r'''
function item(id, sec, cond, extra)
  local o = { _id = id, _sec = sec, _cond = cond, _uses = extra and extra.uses, weapon = extra and extra.weapon,
              _ammo_type = 0, _scope = false }
  function o:id() return self._id end
  function o:section() return self._sec end
  function o:condition() return self._cond end
  function o:set_condition(c) self._cond = c end
  function o:get_remaining_uses() return self._uses end
  function o:set_remaining_uses(u) self._uses = u end
  function o:get_ammo_type() return self._ammo_type end
  function o:weapon_is_scope() return self._scope end
  function o:weapon_is_grenadelauncher() return false end
  function o:weapon_is_silencer() return false end
  objects[id] = o
  se_objects[id] = { id = id, parent_id = 65535, section_name = function() return sec end }
  return o
end
function npc(id, slots)
  local o = { _id = id, _slots = slots, _alive = true }
  function o:id() return self._id end
  function o:alive() return self._alive end
  function o:item_in_slot(s) return self._slots[s] end
  function o:active_item() return self._slots[2] end
  objects[id] = o
  table.insert(db.OnlineStalkers, id)
  return o
end
-- ItemProcessor, as itms_manager has it: a condition (uses) set on the game object a frame after the thing was made
local IP = {}
IP.__index = IP
function IP.update(self)
  for id, c in pairs(self.Cond) do local o = level.object_by_id(id) if o then o:set_condition(c); self.Cond[id] = nil end end
  for id, u in pairs(self.Uses) do local o = level.object_by_id(id) if o then o:set_remaining_uses(u); self.Uses[id] = nil end end
end
itms_manager = { ItemProcessor = IP }
processor = setmetatable({ Cond = {}, Uses = {}, Ammo = {}, Remove = {} }, IP)
'''

class Game:
    def __init__(self, name, seed=1):
        self.lua = L.LuaRuntime(unpack_returned_tuples=True)
        self.log = []
        g = self.lua.globals()
        g.log_line = lambda s: self.log.append(s)
        self.lua.execute(PRELUDE)
        self.lua.execute(ITEM)
        self.lua.execute('math.randomseed(%d)' % seed)
        self.sent = []
        self.connected = True
        self.authority = True
        game = self
        coop = self.lua.table_from({})
        coop['connected'] = lambda: game.connected
        coop['is_authority'] = lambda lvl: game.authority
        coop['my_name'] = lambda: name
        def send_item_state(id):
            game.sent.append(int(id))
            return True
        coop['send_item_state'] = send_item_state
        g.coop = coop

    def run(self, code):
        return self.lua.execute(code)

    def load(self, name):
        src = open(SCRIPTS + name + '.script', 'rb').read().decode('cp1251')
        return self.lua.globals().load_module(name, src)

    def items(self):
        m = self.load('coop_items')
        m.on_game_start()
        self.run('fire("actor_on_first_update")')
        return m

    def at(self, ms):
        self.run('now_ms = %d; run_events(); fire("actor_on_update")' % ms)

failed = 0
def check(what, ok):
    global failed
    print(('ok   ' if ok else 'FAIL ') + what)
    if not ok:
        failed += 1

# 1. a stash's thing: made with condition 1, ItemProcessor sets 0.45 a frame later; its state goes out made_delay_s on
g = Game('a')
g.run('ini_values["coop_items.made_delay_s"] = 1')
g.items()
g.run('item(100, "medkit", 1); processor.Cond[100] = 0.45; item(101, "bandage", 1); item(102, "conserva", 1, {uses = 3}); processor.Uses[102] = 2')
g.run('processor:update()')
check('the condition is set by the processor', g.run('return objects[100]:condition()') == 0.45)
check('nothing goes out at once', g.sent == [])
g.at(500)
check('nor before made_delay_s', g.sent == [])
g.at(1000)
check('then the state of both things it set up (not of one it never touched)', sorted(g.sent) == [100, 102])
g.sent.clear()
g.at(3000)
check('once', g.sent == [])
# one another player took meanwhile is theirs to tell
g.run('item(103, "medkit", 1); processor.Cond[103] = 0.5; processor:update(); se_objects[200] = { section_name = function() return "coop_shadow_box" end }; se_objects[103].parent_id = 200')
g.at(5000)
check("not of a thing another player took meanwhile", g.sent == [])
# single player: nothing
g.connected = False
g.run('item(104, "medkit", 1); processor.Cond[104] = 0.5; processor:update()')
g.connected = True
g.at(8000)
check('nothing without co-op', g.sent == [])

# 2. WPO parts: rolled the same in every game, by id, section and condition; math.random is the game's again after
PARTS = r'''
item_parts = {}
function item_parts.evaluate_parts(obj)
  local t = {}
  for _, p in ipairs({ "barrel", "trigger", "spring", "bolt" }) do t[p] = math.random(50, 100) end
  t.pick = random_key_table({ a = 1, b = 2, c = 3, d = 4 })
  t.f = math.random()
  se_save_var(obj:id(), nil, "parts", t)
end
'''
def parts_of(seed, cond, id=300):
    g = Game('p%d' % seed, seed)
    g.run(PARTS)
    g.items()
    g.run('item(%d, "wpn_ak74", %r, {weapon = true})' % (id, cond))
    g.run('before = math.random')
    g.run('item_parts.evaluate_parts(objects[%d])' % id)
    restored = g.run('return math.random == before')
    p = g.run('local t = se_vars["%d.parts"] local o = {} for k, v in pairs(t) do o[#o+1] = k .. "=" .. tostring(v) end table.sort(o) return table.concat(o, ",")' % id)
    return p, restored, g

p1, r1, g1 = parts_of(1, 0.6)
p2, r2, _ = parts_of(987654, 0.6)
check('the same parts in two games with other random states', p1 == p2)
check("math.random is the game's own again", r1 and r2)
p3, _, _ = parts_of(1, 0.35)
check('another condition rolls other parts', p3 != p1)
p4, _, _ = parts_of(1, 0.6, 301)
check('another thing rolls other parts', p4 != p1)
g = Game('sp', 5)
g.run(PARTS)
g.items()
g.connected = False
g.run('item(300, "wpn_ak74", 0.6, {weapon = true}); item_parts.evaluate_parts(objects[300])')
g.connected = True
check('single player: its own roll', g.run('return se_vars["300.parts"].f') != g1.run('return se_vars["300.parts"].f'))
# the three forms of math.random keep their ranges
g = Game('r')
g.items()
ok = g.run(r'''
local rnd = coop_items.seeded_random(12345)
for i = 1, 2000 do
  local a, b, c = rnd(), rnd(6), rnd(-3, 3)
  if a < 0 or a >= 1 or b < 1 or b > 6 or b ~= math.floor(b) or c < -3 or c > 3 or c ~= math.floor(c) then return false end
end
return true
''')
check('seeded math.random: [0,1), [1,m], [m,n], whole numbers', ok)
check('an error inside is passed through and math.random put back', g.run(r'''
local before = math.random
local ok = pcall(coop_items.seeded, 1, "x", 50, function() error("boom") end)
return not ok and math.random == before
'''))

# 3. live NPCs' weapons: the authority tells the others their wear
g = Game('auth')
g.run('ini_values["coop_items.npc_weapons_look_s"] = 5; ini_values["coop_items.npc_weapon_step"] = 0.02')
g.items()
g.run('w1 = item(500, "wpn_ak74", 0.9, {weapon = true}); w2 = item(501, "wpn_pm", 0.8, {weapon = true}); n = npc(400, { [2] = w1, [3] = w2 })')
g.at(5000)
check('first look: nothing (the others have it as it is)', g.sent == [])
g.run('w1:set_condition(0.89)')
g.at(10000)
check('a little wear: not yet', g.sent == [])
g.run('w1:set_condition(0.875)')
g.at(15000)
check('npc_weapon_step of wear: its state goes', g.sent == [500])
g.sent.clear()
g.at(20000)
check('once', g.sent == [])
g.run('w2._ammo_type = 1')
g.at(25000)
check('another ammo type goes at once', g.sent == [501])
g.sent.clear()
g.run('w1:set_condition(0.87)')
g.at(30000)
g.run('fire("npc_on_net_destroy", n)')
check('the NPC goes offline here: the rest of the wear goes with it', g.sent == [500])
g.sent.clear()
g.run('n2 = npc(401, { [2] = item(502, "wpn_ak74", 0.7, {weapon = true}) })')
g.at(35000)
g.run('objects[502]:set_condition(0.69); n2._alive = false')
g.at(40000)
check('its NPC died: the last of the wear goes (the body\'s loot is the authority\'s from then)', g.sent == [502])
g.sent.clear()
g.run('n3 = npc(402, { [2] = item(503, "wpn_ak74", 0.7, {weapon = true}) })')
g.at(45000)
g.run('objects[503]:set_condition(0.695)')
g.at(50000)
g.run('fire("on_before_level_changing")')
check('leaving the level: the rest of the wear goes', g.sent == [503])
g.sent.clear()
g.authority = False
g.run('objects[503]:set_condition(0.5)')
g.at(55000)
check('not the authority: nothing', g.sent == [])
g.authority = True
g.at(60000)
check('the authority again: a fresh first look, nothing', g.sent == [])
g.connected = False
g.run('objects[503]:set_condition(0.1)')
g.at(65000)
check('without co-op: nothing', g.sent == [])

# 4. coop_sync's item Lua data: an online item's uses and condition as it has them now; uses taken onto one online here
SYNC = r'''
alife_storage_manager = { get_state = function() return m_data end }
m_data = { item_condition = {}, item_remaining_uses = {}, device_condition = {}, se_object = {} }
'''
g = Game('lua')
g.run(SYNC)
sync = g.load('coop_sync')
g.run('ini_values["medkit.use_condition"] = true; multiuse["conserva"] = true')
g.run('item(600, "medkit", 0.4); m_data.item_condition[600] = 1; item(601, "conserva", 1, {uses = 1}); m_data.item_remaining_uses[601] = 3')
text = sync.item_lua(600)
check("the condition as the item has it, not the binder's last one", g.lua.eval('function(t) return coop_sync.deserialize(t).item_condition end')(text) == 0.4)
text = sync.item_lua(601)
check("the uses as the item has them", g.lua.eval('function(t) return coop_sync.deserialize(t).item_remaining_uses end')(text) == 1)
g.run('m_data.item_remaining_uses[700] = 2')
check('an item not online here: the table\'s', g.lua.eval('function(t) return coop_sync.deserialize(t).item_remaining_uses end')(sync.item_lua(700)) == 2)
g2 = Game('lua2')
g2.run(SYNC)
sync2 = g2.load('coop_sync')
g2.run('multiuse["conserva"] = true; item(601, "conserva", 1, {uses = 3})')
sync2.take_item_lua(601, text)
check('taken: the uses are set on the item online here too', g2.run('return objects[601]:get_remaining_uses()') == 1)
check('and kept for the binder', g2.run('return m_data.item_remaining_uses[601]') == 1)

print('all passed' if failed == 0 else '%d check(s) failed' % failed)
sys.exit(1 if failed else 0)
