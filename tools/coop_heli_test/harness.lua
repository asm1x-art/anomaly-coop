-- Offline check of gamedata/scripts/coop_heli.script with Anomaly's own bind_heli.script and heli_combat.script
-- loaded on stubs of the engine and of the co-op API (run.py loads the files and calls run()).
-- What runs: the puppet's update (no logic, health check only), the authority's update and hit callback with a
-- player's stand-in as the hitter (db.storage entry and db.heli_enemies only while the helicopter thinks), the
-- stand-in judged by heli_combat as our actor is, and errors inside the logic not leaving the stand-ins behind.

local results = {}
local function check(name, ok, detail)
	results[#results + 1] = { name = name, ok = not not ok, detail = detail or "" }
end

-- Lua classes as luabind makes them (enough for these scripts)
function class(name)
	local env = getfenv(2)
	local T = {}
	T.__index = T
	env[name] = T
	setmetatable(T, { __call = function(t, ...)
		local o = setmetatable({}, t)
		if t.__init then t.__init(o, ...) end
		return o
	end })
	return function(base)
		setmetatable(T, { __index = base, __call = getmetatable(T).__call })
	end
end

object_binder = { update = function() end, reinit = function() end, net_spawn = function() return true end,
                  net_destroy = function() end, reload = function() end, save = function() end, load = function() end }

local vec = {}
vec.__index = vec
function vector() return setmetatable({ x = 0, y = 0, z = 0 }, vec) end
function vec:set(a, b, c)
	if type(a) == "table" then self.x, self.y, self.z = a.x, a.y, a.z else self.x, self.y, self.z = a, b, c end
	return self
end
function vec:distance_to_sqr(o) return (self.x - o.x) ^ 2 + (self.y - o.y) ^ 2 + (self.z - o.z) ^ 2 end

AC_ID = 0
WARFARE = false
local now = 1000
function time_global() return now end
function printf() end
function IsStalker(o) return o and o.kind == "stalker" end
function IsMonster(o) return false end
function IsWounded(o) return false end
function IsSurvivalMode() return false end
function IsLauncher() return false end
function get_object_squad() return nil end
function character_community(o) return o.community end
local actor_vars = {}
function load_var(_, k, d) local v = actor_vars[k] if v == nil then return d end return v end
function save_var(_, k, v) actor_vars[k] = v end
local callbacks = {}
function SendScriptCallback(name, ...) callbacks[#callbacks + 1] = { name = name, args = { ... } } end
xr_combat_ignore = { ignore_enemy_by_overrides = function() return false end, safe_zone_npcs = {} }
local voices = {}
-- a theme's line as sound_theme picks it: math.random
xr_sound = { update = function() end,
	set_sound_play = function(id, snd) voices[#voices + 1] = id .. ":" .. snd .. "#" .. math.random(1, 1000) end }
local sent_events, event_handlers = {}, {}
coop_sync = {
	send_event = function(name, ...) sent_events[#sent_events + 1] = { name = name, args = { ... } } end,
	on_event = function(name, f) event_handlers[name] = f end,
}
function str_explode(s, sep)
	local t = {}
	for part in string.gmatch(s .. sep, "(.-)" .. sep) do t[#t + 1] = part end
	return t
end
ui_options = { get = function() return true end }
xr_logic = { initialized = 0, issued = 0 }
function xr_logic.initialize_obj() xr_logic.initialized = xr_logic.initialized + 1 end
function xr_logic.issue_event() xr_logic.issued = xr_logic.issued + 1 end
game_statistics = { increment_statistic = function() end, increment_npc_statistic = function() end }
mlr_utils = { death_heli = function() end }
ini_sys = { r_float_ex = function() return nil end, r_bool_ex = function(_, _, _, d) return d end,
            r_string_ex = function() return nil end }
level = { name = function() return "l01_escape" end, get_bounding_volume = function() return { max = { y = 100 } } end }
callback = { helicopter_on_hit = 1, helicopter_on_point = 2, key_press = 3, key_release = 4, key_hold = 5 }
db = { storage = {}, heli_enemies = {}, actor = {} }
function db.del_heli() end
modules = { stype_heli = 3 }
heli_fire = { get_heli_firer = function() return {} end }

-- the world: a helicopter of the army (500), a player's stand-in (900, peer 7), our actor (0)
local objects = {}
local function make_object(id, t)
	t.id_ = id
	t.id = function(self) return self.id_ end
	t.alive = function(self) return not self.dead end
	t.position = function(self) return vector():set(1, 2, 3) end
	t.set_callback = function(self, kind, f, owner) self.callbacks = self.callbacks or {} self.callbacks[kind] = { f, owner } end
	objects[id] = t
	return t
end
local heli_obj = {
	health = 1, dead_calls = 0, m_dead = false, cleared = 0,
	GetfHealth = function(self) return self.health end,
	SetfHealth = function(self, h) self.health = h end,
	Die = function(self) self.dead_calls = self.dead_calls + 1 self.m_dead = true end,
	ClearEnemy = function(self) self.cleared = self.cleared + 1 end,
	isVisible = function() return true end,
	GetRealAltitude = function() return 50 end,
	StartFlame = function(self) self.m_flame_started = true end,
	TurnEngineSound = function() end,
}
local heli = make_object(500, { kind = "heli", get_helicopter = function() return heli_obj end,
	section = function() return "helicopter" end, set_fastcall = function() end })
local stand_in = make_object(900, { kind = "stalker", community = "dolg" })
local se_heli = { id = 500, community = "army", player_id = "heli" }
function alife_object(id) if id == 500 then return se_heli end end
level.object_by_id = function(id) return objects[id] end

local puppet = false
local downed = {}
coop = {
	connected = function() return true end,
	heli_puppet = function(id) return id == 500 and puppet end,
	stand_in_peer = function(id) return id == 900 and 7 or 0 end,
	downed = function(peer) return downed[peer] or false end,
	peers = function() return { { id = 7, name = "Friend", level = "l01_escape", stand_in = 900 } } end,
	sent_states = {},
	send_object_state = function(id) coop.sent_states[#coop.sent_states + 1] = id return true end,
}
utils_stpk = { set_heli_data = function(data, se) se.heli_data = data end }

function run(load)
	bind_heli = load("bind_heli")
	heli_combat = load("heli_combat")
	heli_alife = { distance_2d_sqr = function() return 1 end }
	coop_heli = load("coop_heli")
	coop_heli.on_game_start()

	-- 0. a script's helicopter: its data set after the spawn went goes to the others
	local se_new = { id = 501 }
	utils_stpk.set_heli_data({ startup_animation = "idle" }, se_new)
	check("set_heli_data: data set and sent to the others", se_new.heli_data and coop.sent_states[1] == 501)

	local st = { heliObject = heli_obj }
	db.storage[500] = st
	st.combat = heli_combat.heli_combat(heli, heli_obj)
	st.combat.vis = 100
	local binder = setmetatable({ object = heli, st = st, heli_fire = {}, last_hit_snd_timeout = 0, snd_hit = "hit",
		snd_damage = "dmg", snd_down = "down", flame_start_health = 0.1, initialized = false }, bind_heli.heli_binder)

	-- 1. a puppet: no logic, the health check only (the death the authority sends brings it down)
	puppet = true
	heli_obj.health = 0.5
	binder:update(10)
	check("puppet: no xr_logic", xr_logic.initialized == 0 and xr_logic.issued == 0)
	heli_obj.health = 0
	binder:update(10)
	check("puppet: health 0 from the authority's death brings it down", heli_obj.dead_calls == 1)
	heli_obj.health, heli_obj.dead_calls, heli_obj.m_dead = 1, 0, false

	-- 2. the authority: its logic runs, the stand-ins are its enemies to look at, only while it thinks
	puppet = false
	local seen_inside
	heli_alife.update = function(obj, se, ho)
		seen_inside = { listed = false, storage = db.storage[900] ~= nil }
		for _, id in ipairs(db.heli_enemies) do if id == 900 then seen_inside.listed = true end end
		st.combat:find_valid_target()
	end
	binder:update(10)
	check("authority: xr_logic runs", xr_logic.initialized == 1)
	check("authority: callbacks set to coop_heli's", heli.callbacks and heli.callbacks[callback.helicopter_on_hit] and
		heli.callbacks[callback.helicopter_on_hit][1] == bind_heli.heli_binder.on_hit)
	check("thinking: stand-in in db.heli_enemies and db.storage", seen_inside and seen_inside.listed and seen_inside.storage)
	check("after: stand-in gone from db.heli_enemies", #db.heli_enemies == 0)
	check("after: stand-in not in db.storage", db.storage[900] == nil and rawget(db.storage, 900) == nil)
	check("not flagged, not always enemy: no target", st.enemy_id == nil, tostring(st.enemy_id))

	-- 3. the player hits it in their game: the hit comes from their stand-in here
	binder:on_hit(0.2, 0, 1, 900)
	check("hit: the firer takes the stand-in", binder.heli_fire.enemy == stand_in)
	check("hit: hitted_by is the stand-in", st.hitted_by == 900)
	local cb = callbacks[#callbacks]
	check("hit: heli_on_hit_callback with the stand-in (coop_tasks credit)", cb and cb.name == "heli_on_hit_callback" and cb.args[4] == stand_in)
	binder:update(10)
	check("hit: the helicopter turns on that player", st.enemy_id == 900, tostring(st.enemy_id))

	-- 4. is_enemy for a stand-in, as heli_combat judges our actor
	local combat = st.combat
	-- flagged by the hit (its entry kept between thinking)
	local flagged
	heli_alife.update = function() flagged = combat:is_enemy(stand_in) end
	binder:update(10)
	check("flagged player: enemy", flagged == true)
	downed[7] = true
	binder:update(10)
	check("lying wounded: left be", flagged == false)
	downed[7] = nil
	stand_in.community = "army"
	binder:update(10)
	check("player of the helicopter's faction: left be", flagged == false)
	stand_in.community = "dolg"
	-- the stand-in gone (the player left): its flag goes with it; a new one isn't flagged, actor_always_enemy makes it one
	objects[900] = nil
	binder:update(10)
	local stand_in2 = make_object(900, { kind = "stalker", community = "dolg" })
	heli_alife.update = function() flagged = combat:is_enemy(stand_in2) end
	binder:update(10)
	check("stand-in gone and back: flag forgotten", flagged == false)
	combat.actor_always_enemy = true
	heli_alife.update = function() flagged = combat:is_enemy(stand_in2) end
	binder:update(10)
	check("actor_always_enemy: every player", flagged == true)

	-- 5. an error inside the logic: the stand-ins don't stay behind
	heli_alife.update = function() error("boom") end
	local ok = pcall(binder.update, binder, 10)
	check("error passes on", not ok)
	check("error: db.heli_enemies clean", #db.heli_enemies == 0)
	check("error: db.storage clean", db.storage[900] == nil)

	-- 6. pilots' voice: the authority's goes to the others, a puppet says nothing of its own
	voices = {}
	xr_sound.set_sound_play(500, "heli_hit")
	local ev = sent_events[#sent_events]
	check("voice: the authority plays it and sends it", voices[1] and voices[1]:find("^500:heli_hit#") and ev
		and ev.name == "heli_voice" and ev.args[2] == 500 and ev.args[3] == "heli_hit" and ev.args[4])
	local authority_line = voices[1]
	puppet = true
	voices = {}
	xr_sound.set_sound_play(500, "heli_down")
	check("voice: a puppet's own is not played", #voices == 0)
	math.random(1, 1000) -- another game's randomness is elsewhere
	event_handlers["heli_voice"]("Friend", "l01_escape	500	heli_hit	" .. ev.args[4])
	check("voice: the authority's line is played on the puppet, the same one", voices[1] == authority_line,
		tostring(voices[1]) .. " vs " .. tostring(authority_line))
	xr_sound.set_sound_play(42, "some_npc")
	check("voice: an NPC's is not touched", voices[2] and voices[2]:find("^42:some_npc#"))
	puppet = false

	-- 7. combat altitude: the level's top once, not twice
	local c2 = heli_combat.heli_combat(heli, heli_obj)
	check("vanilla __init doubles it", c2.safe_altitude == c2.default_safe_altitude + c2.level_max_y)
	c2:initialize()
	check("altitude: section's over the level's top once", c2.safe_altitude == c2.default_safe_altitude,
		tostring(c2.safe_altitude))
	local ini = { r_bool_ex = function() return nil end, r_string_to_condlist = function() return nil end,
		r_string_ex = function() return nil end, r_float_ex = function(_, _, key) return nil end }
	c2:read_custom_data(ini, "logic")
	check("altitude: no logic value - the section's", c2.safe_altitude == c2.default_safe_altitude)
	ini.r_float_ex = function(_, _, key) if key == "combat_safe_altitude" then return 20 end end
	c2:read_custom_data(ini, "logic")
	check("altitude: the logic's over the level's top", c2.safe_altitude == 20 + c2.level_max_y)
	c2:initialize()
	check("altitude: the logic's kept on initialize", c2.safe_altitude == 20 + c2.level_max_y)

	-- 8. no co-op: as vanilla
	coop.connected = function() return false end
	heli_alife.update = function() seen_inside = db.storage[900] ~= nil end
	binder:update(10)
	check("no co-op: no stand-in entries", seen_inside == false)

	return results
end
