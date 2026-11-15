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
function V:distance_to_sqr(o) return (self.x - o.x) ^ 2 + (self.y - o.y) ^ 2 + (self.z - o.z) ^ 2 end
function V:distance_to(o) return math.sqrt(self:distance_to_sqr(o)) end
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
G.clock = 5000000   -- the world's clock, ms (coop.clock)
G.game_ms = 9000000 -- this game's game time, ms (game.get_game_time)
function coop.clock() return G.clock end
local T = {}
T.__index = T
function T:setHMSms(h, m, s, ms) self.ms = ((h * 60 + m) * 60 + s) * 1000 + ms end
function T:sub(o) self.ms = self.ms - o.ms end
game = { CTime = function() return setmetatable({ ms = 0 }, T) end,
	get_game_time = function() return setmetatable({ ms = G.game_ms }, T) end }
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
function level.get_time_factor() return 10 end
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
	if section == "" or section == nil then return false end
	local st = db.storage[obj:id()]
	if st.active_section == section then return false end
	st.active_section = section
	st.active_scheme = string.match(section, "^([^@]+)")
	G.switches = (G.switches or 0) + 1
	local per = G.section_logic and G.section_logic[obj:id()]
	if per and per[section] then
		st.ph_door = per[section]() -- xr_logic makes a section's storage and logic anew
	end
	return true
end

-- the door's logic as xr_logic runs it each update: rolls math.random(100) (a ~prob of its condlist), then the
-- switch conditions doors use, as vanilla's try_switch_to_another_section
function xr_logic.try_switch_to_another_section(npc, st, actor)
	G.rolls = G.rolls or {}
	G.rolls[#G.rolls + 1] = math.random(100)
	if not actor then return end
	G.evaluated = (G.evaluated or 0) + 1
	local switched = false
	for _, c in pairs(st.logic or {}) do
		local go
		if c.name == "on_info" then go = true
		elseif c.name == "on_actor_dist_le_nvis" then go = distance_between(actor, npc) <= c.v1
		elseif c.name == "on_actor_dist_ge_nvis" then go = distance_between(actor, npc) > c.v1
		elseif c.name == "on_actor_in_zone" then go = db.actor_inside_zones[c.v1]
		elseif c.name == "on_actor_not_in_zone" then go = not db.actor_inside_zones[c.v1]
		end
		if go then
			switched = xr_logic.switch_to_section(npc, st.ini, xr_logic.pick_section_from_condlist(actor, npc, c.condlist))
		end
		if switched == true then break end
	end
	return switched
end

-- vanilla's pick_section_from_condlist, the parts doors use (infos as G.infos)
function xr_logic.pick_section_from_condlist(actor, npc, condlist)
	for i = 1, #condlist do
		local cond, met = condlist[i], true
		for _, infop in ipairs(cond[2] or {}) do
			if infop[2] == 1 then if not db.actor:has_info(infop[1]) then met = false break end
			elseif infop[2] == 2 then if db.actor:has_info(infop[1]) then met = false break end
			elseif infop[2] == 3 then if not xr_conditions[infop[1]](actor, npc, infop[3]) then met = false break end
			elseif infop[2] == 4 then if xr_conditions[infop[1]](actor, npc, infop[3]) then met = false break end
			elseif infop[2] == 5 then if infop[3] and infop[3] < math.random(100) then met = false break end
			end
		end
		if met then
			for _, e in ipairs(cond[3] or {}) do
				if e[2] == 1 then if not db.actor:has_info(e[1]) then db.actor:give_info_portion(e[1]) end
				elseif e[2] == 2 then if db.actor:has_info(e[1]) then db.actor:disable_info_portion(e[1]) end
				elseif e[2] == 3 or e[2] == 4 then xr_effects[e[1]](actor, npc, e[3]) end
			end
			return cond[1] or ""
		end
	end
end

-- vanilla's parse_condlist / extract_conditions
local function extract_conditions(c, lst, n, index)
	for sign, infop in c:gmatch("([=%-%+!~]+)([^=%-%+!~%s]+)") do
		lst[n][index] = lst[n][index] or {}
		if sign == "+" then table.insert(lst[n][index], { infop, 1 })
		elseif sign == "-" then table.insert(lst[n][index], { infop, 2 })
		elseif sign == "=" or sign == "!" then
			local a = string.find(infop, "(", 1, true)
			if a then
				local b = string.find(infop, ")", 1, true)
				local params = infop:sub(a + 1, b - 1)
				infop = infop:sub(1, a - 1)
				local t
				for p in params:gmatch("%s*([^:]+)%s*") do
					t = t or {}
					table.insert(t, tonumber(p) or p)
				end
				table.insert(lst[n][index], { infop, sign == "=" and 3 or 4, t })
			else
				table.insert(lst[n][index], { infop, sign == "=" and 3 or 4 })
			end
		elseif sign == "~" then table.insert(lst[n][index], { infop, 5, tonumber(infop) })
		end
	end
end
function parse_condlist(src)
	local lst, n = {}, 0
	for fld in src:gmatch("%s*([^,]+)%s*") do
		n = n + 1
		lst[n] = {}
		local a, b, c = string.find(fld, "{%s*(.*)%s*}")
		if c then fld = string.sub(fld, 1, a - 1) .. string.sub(fld, b + 1); extract_conditions(c, lst, n, 2) end
		a, b, c = string.find(fld, "%%%s*(.*)%s*%%")
		if c then fld = string.sub(fld, 1, a - 1) .. string.sub(fld, b + 1); extract_conditions(c, lst, n, 3) end
		lst[n][1] = fld:match("^%s*(.-)%s*$")
	end
	return lst
end

ph_door = { action_door = {} }
function ph_door.action_door.use_callback(self)
	local st = db.storage[self.object:id()]
	if self.st and self.st.has_use then -- a door with its sections' logic: vanilla's try_switch on on_use
		G.uses = (G.uses or 0) + 1
		if self.st.on_use then
			xr_logic.switch_to_section(self.object, st.ini,
				xr_logic.pick_section_from_condlist(db.actor, self.object, self.st.on_use.condlist))
		end
		return
	end
	local to = st.active_section == "ph_door@open" and "ph_door@close" or "ph_door@open"
	xr_logic.switch_to_section(self.object, st.ini, to)
end
function ph_door.action_door.hit_callback(self) G.door_hits = (G.door_hits or 0) + 1 end
function ph_door.try_to_open_door(npc, opened)
	G.npc_door_calls = (G.npc_door_calls or 0) + 1
end
function ph_door.try_to_close_door(npc, opened) end

local INI = { section_exist = function(self, s) return s == "ph_door@open" or s == "ph_door@close" end }

function make_door(id, name, section, online)
	local o = setmetatable({ _id = id, _name = name, _pos = vector():set(0, 0, 0), _visual = "door", online = online }, O)
	o.binder = setmetatable({ object = o, initialized = false }, { __index = binder })
	G.objects[id] = o
	db.storage[id] = { ini = INI, active_section = section, active_scheme = "ph_door", ph_door = { no_force = false, logic = {} } }
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
	ph_door.action_door.use_callback({ object = o, st = db.storage[id].ph_door })
end

function section_of(id) return db.storage[id].active_section end

-- the level's players, zones, the actor's conditions and the effects doors play (as vanilla's xr_conditions,
-- xr_effects, _g, utils_obj)
G.section_logic = {}
G.infos = {}
G.peers = {}
G.actor_pos = { x = 0, y = 0, z = 0 }
G.inv = {}
G.fx = {}
db.actor = {
	id = function() return 0 end,
	position = function() return vector():set(G.actor_pos) end,
	object = function(self, sec) return G.inv[sec] end,
	has_info = function(self, info) return G.infos[info] == true end,
	give_info_portion = function(self, info) G.infos[info] = true; G.given = (G.given or "") .. "+" .. info end,
	disable_info_portion = function(self, info) G.infos[info] = nil; G.given = (G.given or "") .. "-" .. info end,
}
db.zone_by_name = {}
db.actor_inside_zones = {}
function coop.peers() return G.peers end

function distance_between(a, b) return a:position():distance_to(b:position()) end
utils_obj = {}
function utils_obj.npc_in_zone(npc, zone)
	zone = type(zone) == "string" and db.zone_by_name[zone] or zone
	return npc and zone and zone.inside and zone:inside(npc:position())
end
xr_conditions = {}
function xr_conditions.dist_to_actor_le(actor, npc, p)
	return p[1] and npc:position():distance_to_sqr(actor:position()) <= tonumber(p[1]) ^ 2
end
function xr_conditions.dist_to_actor_ge(actor, npc, p)
	return p[1] and npc:position():distance_to_sqr(actor:position()) >= tonumber(p[1]) ^ 2
end
function xr_conditions.actor_in_zone(actor, npc, p)
	for i = 1, #p do
		local zone = db.zone_by_name[p[i]]
		if zone and zone:inside(db.actor:position()) then return true end
	end
	return false
end
function xr_conditions.actor_out_zone(actor, npc, p) return not utils_obj.npc_in_zone(db.actor, p[1]) end
function xr_conditions.actor_has_item(actor, npc, p) return p[1] ~= nil and db.actor:object(p[1]) ~= nil end
function xr_conditions.is_door_blocked_by_npc(actor, npc, p) return G.blocked == true end

xr_effects = {}
for _, name in ipairs({ "play_sound", "play_particle_on_path", "spawn_thing" }) do
	xr_effects[name] = function(actor, obj, p) G.fx[#G.fx + 1] = name .. ":" .. obj:name() end
end
function xr_effects.remove_item(actor, obj, p)
	G.fx[#G.fx + 1] = "remove_item:" .. p[1]
	G.inv[p[1]] = nil
end
function xr_effects.hit_npc(actor, obj, p)
	G.fx[#G.fx + 1] = "hit_npc:" .. obj:name()
	ph_door.action_door.hit_callback({ object = obj }) -- the engine's hit callback of the door
end

-- a zone: a sphere
function make_zone(name, x, y, z, r)
	db.zone_by_name[name] = { name = function() return name end,
		inside = function(self, pos) return vector():set(x, y, z):distance_to_sqr(pos) <= r * r end }
end

-- a door with its sections' logic, online: sections = { section = { { condition, "condlist" }
-- or { condition, v1, "condlist" }... } }
function make_logic_door(id, name, section, sections)
	make_door(id, name, section, false)
	db.storage[id].ini = { section_exist = function(self, s) return sections[s] ~= nil end }
	local per = {}
	for sec, list in pairs(sections) do
		per[sec] = function()
			local logic, on_use = {}, nil
			for _, c in ipairs(list) do
				if c[1] == "on_use" then
					on_use = { condlist = parse_condlist(c[2]) }
				elseif c[3] then
					logic[#logic + 1] = { name = c[1], v1 = c[2], condlist = parse_condlist(c[3]) }
				else
					logic[#logic + 1] = { name = c[1], condlist = parse_condlist(c[2]) }
				end
			end
			return { no_force = false, logic = logic, on_use = on_use, has_use = true }
		end
	end
	G.section_logic[id] = per
	db.storage[id].ph_door = per[section]()
	door_online(id)
end

-- the door's update: its logic, as ph_door's update runs it
function door_update(id)
	return xr_logic.try_switch_to_another_section(G.objects[id], db.storage[id].ph_door, db.actor)
end
