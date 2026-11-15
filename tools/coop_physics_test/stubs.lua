-- Stubs of the engine and Anomaly for coop_physics.script; one Lua state per game. The Python side (run.py) is
-- the network and the server: net_send(kind, a, b) puts out a message, deliver_* bring one in.
G = {
	name = GAME_NAME, level = "l01_escape", connected = true, authority = {}, facts = {}, fact_applying = false,
	shared = 0, spawns = {}, objects = {}, now = 0, updates = {}, events = {}, fact_handlers = {}, log = {},
	sp_spawns = 0,
}

function printf(fmt, ...)
	local ok, s = pcall(string.format, fmt, ...)
	G.log[#G.log + 1] = ok and s or fmt
end

function str_explode(s, sep)
	local t = {}
	for part in string.gmatch(s .. sep, "(.-)" .. sep) do
		t[#t + 1] = part
	end
	return t
end

function time_global() return G.now end
function get_console() return { get_integer = function() return 0 end } end
ini_sys = { r_float_ex = function() return nil end }

-- vectors
local V = {}
V.__index = V
function V:set(x, y, z)
	if type(x) == "table" then x, y, z = x.x, x.y, x.z end
	self.x, self.y, self.z = x or 0, y or 0, z or 0
	return self
end
function vector() return setmetatable({ x = 0, y = 0, z = 0 }, V) end

-- hits
hit = setmetatable({ fire_wound = 7, explosion = 4 }, { __call = function() return {} end })

-- the engine's co-op
coop = {}
function coop.connected() return G.connected end
function coop.is_authority(lvl) return G.authority[lvl] == true end
function coop.my_name() return G.name end
function coop.fact(key) return G.facts[key] or "" end
function coop.report_fact(key, value)
	if G.fact_applying or not G.connected or (G.facts[key] or "") == value then return end
	G.facts[key] = value
	net_send("fact", key, value)
end
function coop.begin_shared() G.shared = G.shared + 1 end
function coop.end_shared() if G.shared > 0 then G.shared = G.shared - 1 end end

coop_sync = {}
function coop_sync.on_event(name, h) G.events[name] = h end
function coop_sync.send_event(name, ...)
	local t = {}
	for i, v in ipairs({ ... }) do t[i] = tostring(v) end
	net_send("event", name, table.concat(t, "\t"))
end

coop_facts = {}
function coop_facts.on_fact(prefix, h) G.fact_handlers[prefix] = h end

function deliver_event(name, sender, payload)
	local h = G.events[name]
	if h then h(sender, payload) end
end

function deliver_fact(key, value)
	G.facts[key] = value
	G.fact_applying = true -- as coop_facts.cpp put_on
	for prefix, h in pairs(G.fact_handlers) do
		if string.sub(key, 1, #prefix) == prefix then
			h(key, value)
			break
		end
	end
	G.fact_applying = false
end

function RegisterScriptCallback(name, f) G.updates[#G.updates + 1] = f end
function tick(ms)
	G.now = G.now + ms
	for _, f in ipairs(G.updates) do f() end
end

-- world items
G.next_id = 1000
G.released = 0
G.shared_ids = {}
G.objects_se = {}
function alife_create_item(section, place, t)
	G.next_id = G.next_id + 1
	local id = G.next_id
	G.spawns[#G.spawns + 1] = { section = section, shared = G.shared > 0, id = id, ammo = t and t.ammo }
	local se = { id = id, section = section }
	G.objects_se[id] = se
	if G.shared > 0 then
		net_send("spawn", section, "")
	end
	if t and t.ammo then
		return { se } -- ammo comes as a list of boxes
	end
	return se
end
function alife_object(id) return G.objects_se[id] end
function alife_release_id(id) G.objects_se[id] = nil; G.released = G.released + 1 end
function coop.share(id)
	if not G.objects_se[id] or G.shared_ids[id] then return false end
	G.shared_ids[id] = true
	net_send("spawn", G.objects_se[id].section, "")
	return true
end
G.theirs = {}
function coop.release_theirs(id) G.theirs[id] = true end
G.by_logic = {}
function coop.prop_by_logic(id, on) G.by_logic[id] = on end
function IsItem(kind, section) return string.find(section, "^ammo") ~= nil end
ini_sys.section_exist = function(self, s) return true end
ini_sys.line_exist = function(self, s, k) return true end

game_achievements = { has_achievement = function() return false end }

-- Anomaly's xr_box: its lists in module locals, filled by the ph_item_box constructor; spawn_items reads them
xr_box = {}
local item_by_community = {}
local count_by_level = {}
xr_box.ph_item_box = setmetatable({
	spawn_items = function(self, obj)
		local _ = item_by_community, count_by_level
		local p = obj:position()
		alife_create_item("medkit", { p, obj:level_vertex_id(), obj:game_vertex_id() })
	end,
}, { __call = function()
	for _, c in ipairs({ "small_box_generic", "small_box_ussr", "small_box_nato", "small_box_army", "small_box_science" }) do
		item_by_community[c] = { medkit = 0.5, bandage = 0.7, ammo_9x18_fmj = 0.4, conserva = 0.6, vodka = 0.3 }
	end
	count_by_level.medkit = { 0, 2 }
	count_by_level.bandage = { 1, 3 }
	count_by_level.ammo_9x18_fmj = { 5, 20 }
	G.box_tables_made = (G.box_tables_made or 0) + 1
end })
local manager = { spawn_items = xr_box.ph_item_box.spawn_items }
function xr_box.get_box_manager() return manager end

-- level and objects
db = { storage = {}, level_doors = {}, actor = {} }
level = {}
function level.name() return G.level end
function level.object_by_id(id)
	local o = G.objects[id]
	return o and o.online and o or nil
end

local O = {}
O.__index = O
function O:id() return self._id end
function O:name() return self._name end
function O:position() return vector():set(self._pos) end
function O:level_vertex_id() return 100 end
function O:game_vertex_id() return 10 end
function O:spawn_ini() return nil end
function O:get_visual_name() return self._visual end
function O:hit(h)
	if self.dead then return end
	self.dead = true
	G.hits = (G.hits or 0) + 1
	local b = self.binder
	b.death_callback(b, self, h.draftsman)
end

-- Anomaly's generic_physics_binder: its death_callback as bind_physic_object's (box part)
bind_physic_object = { generic_physics_binder = {} }
local binder = bind_physic_object.generic_physics_binder
function binder.death_callback(self, victim, who)
	G.vanilla_deaths = (G.vanilla_deaths or 0) + 1
	if victim:get_visual_name() == [[dynamics\box\box_wood_01]] then
		xr_box.get_box_manager():spawn_items(victim, who)
	end
end
function binder.net_spawn(self, se) return true end

function make_box(id, name)
	local o = setmetatable({ _id = id, _name = name, _pos = vector():set(1, 2, 3), _visual = [[dynamics\box\box_wood_01]],
		online = true }, O)
	o.binder = setmetatable({ object = o, initialized = true }, { __index = binder })
	G.objects[id] = o
	return o
end

-- explosion / own shot: the engine's CDestroyablePhysicsObject::Destroy calls the death callback
function break_box(id)
	local o = G.objects[id]
	o:hit({ draftsman = { id = function() return 0 end } })
end

-- xr_logic and ph_door
xr_logic = {}
function xr_logic.switch_to_section(obj, ini, section)
	local st = db.storage[obj:id()]
	if st.active_section == section then return false end
	st.active_section = section
	st.active_scheme = string.match(section, "^([^@]+)")
	G.switches = (G.switches or 0) + 1
	return true
end

ph_door = { action_door = {} }
function ph_door.action_door.use_callback(self)
	local st = db.storage[self.object:id()]
	local to = st.active_section == "ph_door@open" and "ph_door@close" or "ph_door@open"
	xr_logic.switch_to_section(self.object, st.ini, to)
end
function ph_door.action_door.hit_callback(self) end
function ph_door.try_to_open_door(npc, opened)
	G.npc_door_calls = (G.npc_door_calls or 0) + 1
end
function ph_door.try_to_close_door(npc, opened) end

local INI = { section_exist = function(self, s) return s == "ph_door@open" or s == "ph_door@close" end }

function make_door(id, name, section, online)
	local o = setmetatable({ _id = id, _name = name, _pos = vector():set(0, 0, 0), _visual = "door", online = online }, O)
	o.binder = setmetatable({ object = o, initialized = false }, { __index = binder })
	G.objects[id] = o
	db.storage[id] = { ini = INI, active_section = section, active_scheme = "ph_door", ph_door = { no_force = false } }
	db.level_doors[id] = o._pos
	return o
end

function door_online(id)
	local o = G.objects[id]
	o.online = true
	o.binder.net_spawn(o.binder, {})
	o.binder.initialized = true -- its logic comes up on its first update
end

function use_door(id)
	local o = G.objects[id]
	ph_door.action_door.use_callback({ object = o })
end

function section_of(id) return db.storage[id].active_section end
