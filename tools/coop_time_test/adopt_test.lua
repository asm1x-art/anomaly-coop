-- Offline test of coop_time.script (tools/coop_time_test/run.py): a game that becomes the sim master - the host
-- started again from an old save, a player's game taking the world over - takes the world's weather, cycle period
-- and surge/psi storm timetables from the server's facts at once, before it decides or publishes anything; the
-- admin's weather right after that is the world's; a word of the master of a moment ago is taken, not overwritten.
local SCRIPT = ...

-- CTime on os.time (local zone, consistent within the test)
local CTime = {}
CTime.__index = CTime
local function ctime_of(t) return setmetatable({ t = t }, CTime) end
function CTime:set(Y, M, D, h, m, s, ms)
	self.t = os.time({ year = Y, month = M, day = D, hour = h, min = m, sec = s })
end
function CTime:get()
	local d = os.date("*t", self.t)
	return d.year, d.month, d.day, d.hour, d.min, d.sec, 0
end
function CTime:diffSec(o) return self.t - o.t end
local function at(Y, M, D, h, m, s) return os.time({ year = Y, month = M, day = D, hour = h, min = m or 0, sec = s or 0 }) end

local now_t = at(2012, 5, 3, 9, 10) -- the save's clock
local world_t = at(2012, 5, 3, 14, 20) -- the world's
local tg, frame = 0, 0
local master = true
local live = false -- coop_facts.cpp g_live: reports go out only once the world runs (after the first update)
local applying = false -- coop_facts.cpp g_applying: no reports from inside a fact's handler
local WORLD_WEATHER = "14|rain|w_rain2|n|w_rain2|w_rain1"
local facts = {
	weather = WORLD_WEATHER,
	weather_period = "2012,5,3,11,0,0,0|clear,rain",
	surge = "2012,5,3,12,0,0,0|30000",
	psi = "2012,5,3,13,0,0,0|40000",
}
local sent = {} -- what went to the server
local callbacks = {}
local fact_handlers = {}

coop = {
	connected = function() return true end,
	is_sim_master = function() return master end,
	report_fact = function(k, v)
		if not live or applying or facts[k] == v then
			return
		end
		facts[k] = v
		sent[#sent + 1] = k .. "=" .. v
	end,
	fact = function(k) return facts[k] or "" end,
	-- the script compares h*3600+m*60+s with (world/1000) % 86400
	clock = function() local d = os.date("*t", world_t); return ((d.hour * 3600 + d.min * 60 + d.sec) + 86400 * 100) * 1000 end,
	is_authority = function() return true end,
}
local function from_another(k, v) -- a fact another game sent
	facts[k] = v
	applying = true
	for prefix, fn in pairs(fact_handlers) do
		if string.sub(k, 1, #prefix) == prefix then
			fn(k, v)
			break
		end
	end
	applying = false
end

function get_console() return { get_integer = function() return 0 end } end
function printf(fmt, ...) print(string.format(fmt, ...)) end
function time_global() return tg end
function device() return { frame = frame } end
function ini_file() return nil end
ini_sys = { r_float_ex = function() return nil end }
weather = { is_paused = function() return false end }
level = {
	get_time_hours = function() return os.date("*t", now_t).hour end,
	is_wfx_playing = function() return false end,
	set_weather = function() end,
	set_weather_smooth = function() end,
	get_time_factor = function() return 6 end,
	name = function() return "fake_start" end,
}
game = { get_game_time = function() return ctime_of(now_t) end, CTime = function() return ctime_of(0) end }
db = { actor = {} }
function RegisterScriptCallback(name, fn) callbacks[name] = fn end
coop_facts = { on_fact = function(name, fn) fact_handlers[name] = fn end }

-- the weather manager as level_weathers has it (only what coop_time touches)
local change_periods = 0
local WM = {}
WM.__index = WM
function WM:select_weather(now) self.weather_file = self.preset end
function WM:change_period() change_periods = change_periods + 1; self.cycle = "foggy"; self.preset = "w_foggy1" end
function WM:forced_weather_change() self.forced_weather_change_on_time_change = true end
function WM:load_state() -- the save's
	self.cycle, self.preset, self.weather_file, self.last_hour = "clear", "w_clear1", "w_clear1", 9
	self.last_period_change_date, self.weather_storage = ctime_of(at(2012, 5, 3, 3)), { "foggy" }
end
local wm = setmetatable({ weatherType = "atmosfear" }, WM)
level_weathers = { WeatherManager = WM, get_weather_manager = function() return wm end }
-- WeatherManager:update's hour turn
local function hour_turn()
	if wm.last_hour ~= level.get_time_hours() then
		wm.last_hour = level.get_time_hours()
		wm:change_period()
		wm:select_weather(false)
	end
end

local function storm_class()
	local C = { updates = 0 }
	C.__index = C
	function C:update() C.updates = C.updates + 1 end
	function C:kill_objects_at_pos() end
	function C:end_surge() self.ended = true end
	function C:finish() self.ended = true end
	return C
end
local SC, PC = storm_class(), storm_class()
local sm = setmetatable({}, SC)
local pm = setmetatable({}, PC)
surge_manager = { CSurgeManager = SC, get_surge_manager = function() return sm end,
	load_state = function() -- the save's
		sm._state_loaded, sm.started, sm.last_surge_time, sm._delta, sm.surge_time = true, false,
			ctime_of(at(2012, 5, 2, 20)), 99999, 222
	end }
psi_storm_manager = { CPsiStormManager = PC, get_psi_storm_manager = function() return pm end,
	load_state = function() -- the save's: one runs in it
		pm._state_loaded, pm.started, pm.inited_time, pm.last_psi_storm_time, pm._delta, pm.psi_storm_duration =
			true, true, ctime_of(at(2012, 5, 3, 9)), ctime_of(at(2012, 5, 2, 21)), 12345, 254
	end }

local f = assert(loadstring(SCRIPT))
local env = setmetatable({}, { __index = _G, __newindex = _G })
setfenv(f, env)
f()
env.on_game_start()

local function check(cond, what)
	print((cond and "PASS " or "FAIL ") .. what)
	if not cond then FAILED = true end
end
local function stamp(t) local Y, M, D, h, m, s = t:get(); return string.format("%d,%d,%d,%d,%d,%d,0", Y, M, D, h, m, s) end
local function tick(n)
	for _ = 1, n or 1 do
		tg = tg + 1100; frame = frame + 1
		callbacks.actor_on_update()
		sm:update(); pm:update() -- surge_manager's main_loop
	end
end

-- 1. the host loads its old save (it runs the world alone: the master while loading); net_spawn's reset picks
wm:load_state(); surge_manager.load_state(); psi_storm_manager.load_state()
wm:select_weather(true)
check(wm.cycle == "rain" and wm.preset == "w_rain2" and wm.weather_file == "w_rain2",
	"at the first pick, before any frame: the world's weather (" .. wm.cycle .. "/" .. wm.weather_file .. ")")
check(stamp(wm.last_period_change_date) == "2012,5,3,11,0,0,0" and table.concat(wm.weather_storage, ",") == "clear,rain",
	"the world's weather period")
check(stamp(sm.last_surge_time) == "2012,5,3,12,0,0,0" and sm._delta == 30000, "the world's surge timetable")
check(stamp(sm.inited_time) == "2012,5,3,20,20,0,0", "surge inited_time on the world's next one, not skipped as missed")
check(pm.ended and pm.started == false, "the save's psi storm, not the world's, ended quietly")
check(stamp(pm.last_psi_storm_time) == "2012,5,3,13,0,0,0" and pm._delta == 40000, "the world's psi timetable")

-- 2. the world runs: the first update, frames on the save's clock (the world's comes in the frame's end)
live = true
callbacks.actor_on_first_update()
from_another("weather", facts.weather) -- facts_ready: every fact put on again
tick(3)
check(#sent == 0, "nothing sent while our clock is the save's (" .. table.concat(sent, "; ") .. ")")

-- 3. the world's clock: the hour turns from the save's to the world's, the world had decided it
now_t = world_t
_G.coop_on_time_jump(world_t - at(2012, 5, 3, 9, 10))
hour_turn()
tick(3)
check(change_periods == 0, "no change of cycle in the hour the world had decided")
check(facts.weather == WORLD_WEATHER, "the world's weather fact stays: " .. facts.weather)
check(facts.surge == "2012,5,3,12,0,0,0|30000" and facts.psi == "2012,5,3,13,0,0,0|40000" and
	facts.weather_period == "2012,5,3,11,0,0,0|clear,rain", "timetables and period unchanged on the server")
check(#sent == 0, "nothing changed on the server (" .. table.concat(sent, "; ") .. ")")
check(SC.updates > 0 and PC.updates > 0, "surge/psi updates ran, no waiting")

-- 4. the admin's weather now (coop_world_events.run on the master): it is the world's, and the next hour is ours
env.take_world()
env.weather_now()
wm.cycle, wm.preset = "storm", "w_storm1" -- coop_world_events.weather
wm:forced_weather_change()
wm:select_weather(true)
check(string.match(facts.weather, "^14|storm|w_storm1|") ~= nil, "the admin's weather published: " .. facts.weather)
now_t = at(2012, 5, 3, 15, 0); world_t = now_t
hour_turn()
tick(2)
check(change_periods == 1, "the next hour's change of cycle is ours again")

-- 5. a word of the game that was the master a moment ago (an admin's event reached it before the roles moved)
from_another("weather", "15|cloudy|w_cloudy3|n|w_cloudy3|w_storm1")
tick(2)
check(wm.cycle == "cloudy" and wm.preset == "w_cloudy3", "its weather is taken, not overwritten: " .. wm.cycle)
check(facts.weather == "15|cloudy|w_cloudy3|n|w_cloudy3|w_storm1", "the server keeps it: " .. facts.weather)
from_another("surge", "2012,5,3,15,0,0,0|900")
tick(2)
check(stamp(sm.last_surge_time) == "2012,5,3,15,0,0,0" and sm._delta == 900, "its surge (the admin's) is taken")
pm.started = true -- ours runs: it stays
from_another("psi", "2012,5,3,15,0,0,0|5")
tick(1)
check(pm._delta == 40000 and not pm.ended_again, "a psi storm of ours that runs isn't cut by its word")
pm.started = false
tick(1)
check(pm._delta == 5, "its psi timetable is taken once ours doesn't run")

-- 6. weather_period from another game: nothing picked
local picks = 0
local sel = WM.select_weather
WM.select_weather = function(...) picks = picks + 1; return sel(...) end
from_another("weather_period", "2012,5,3,15,0,0,0|cloudy")
check(picks == 0, "weather_period doesn't make a pick")

-- 7. the roles move away and back: taken anew
master = false
tick(1)
facts.surge = "2012,5,3,16,0,0,0|20000"
master = true
tick(1)
check(stamp(sm.last_surge_time) == "2012,5,3,16,0,0,0" and sm._delta == 20000, "taken again on becoming the master again")

print(FAILED and "SOME FAILED" or "ALL PASSED")
