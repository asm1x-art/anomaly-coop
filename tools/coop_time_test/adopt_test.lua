-- Offline test of coop_time.script: a host that starts again from an old save takes the world's weather,
-- cycle period and surge/psi timetables from the facts before it publishes anything.
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
local facts = {
	weather = "14|rain|w_rain2|n|w_rain2|w_rain1",
	weather_period = "2012,5,3,11,0,0,0|clear,rain",
	surge = "2012,5,3,12,0,0,0|30000",
	psi = "2012,5,3,13,0,0,0|40000",
}
local reported = {}
local callbacks = {}
local fact_handlers = {}

coop = {
	connected = function() return true end,
	is_sim_master = function() return master end,
	report_fact = function(k, v) reported[#reported + 1] = k .. "=" .. v; facts[k] = v end,
	fact = function(k) return facts[k] or "" end,
	clock = function() return (world_t - at(2012, 1, 1, 0)) * 1000 + 0 end,
	is_authority = function() return true end,
}
-- coop.clock(): the script compares h*3600+m*60+s with (world/1000) % 86400, so give it seconds of the day
coop.clock = function() local d = os.date("*t", world_t); return ((d.hour * 3600 + d.min * 60 + d.sec) + 86400 * 100) * 1000 end

function get_console() return { get_integer = function() return 1 end } end
function printf(fmt, ...) print(string.format(fmt, ...)) end
function time_global() return tg end
function device() return { frame = frame } end
function ini_file() return nil end
ini_sys = { r_float_ex = function() return nil end }
weather = { is_paused = function() return false end }
local shown = {}
level = {
	get_time_hours = function() return os.date("*t", now_t).hour end,
	is_wfx_playing = function() return false end,
	set_weather = function(f, now) shown[#shown + 1] = "set " .. f .. (now and " now" or "") end,
	set_weather_smooth = function(f) shown[#shown + 1] = "smooth " .. f end,
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
function WM:select_weather(now)
	self.weather_file = self.preset
	level.set_weather(self.weather_file, now)
end
function WM:change_period() change_periods = change_periods + 1; self.cycle = "storm"; self.preset = "w_storm1" end
function WM:forced_weather_change() self.forced_weather_change_on_time_change = true end
local wm = setmetatable({ weatherType = "atmosfear", cycle = "clear", preset = "w_clear1", weather_file = "w_clear1",
	last_hour = 9, last_period_change_date = ctime_of(at(2012, 5, 3, 3)), weather_storage = { "foggy" } }, WM)
level_weathers = { WeatherManager = WM, get_weather_manager = function() return wm end }

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
local sm = setmetatable({ _state_loaded = true, started = false, last_surge_time = ctime_of(at(2012, 5, 2, 20)),
	_delta = 99999, surge_time = 222 }, SC)
local pm = setmetatable({ _state_loaded = true, started = true, inited_time = ctime_of(at(2012, 5, 3, 9)),
	last_psi_storm_time = ctime_of(at(2012, 5, 2, 21)), _delta = 12345, psi_storm_duration = 254 }, PC)
surge_manager = { CSurgeManager = SC, get_surge_manager = function() return sm end }
psi_storm_manager = { CPsiStormManager = PC, get_psi_storm_manager = function() return pm end }

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

-- 1. the host loads its old save: net_spawn's reset picks the weather
wm:select_weather(true)
callbacks.actor_on_first_update()
tick(3)
check(#reported == 0, "nothing published while the clock is the save's (" .. table.concat(reported, "; ") .. ")")
check(SC.updates == 0 and PC.updates == 0, "surge/psi updates held before the world's state is taken")
check(wm.cycle == "rain" and wm.preset == "w_rain2", "follows the world's weather meanwhile: " .. wm.cycle .. "/" .. wm.preset)

-- an hour turns on the save's clock meanwhile: the cycle is not changed from the save's period
change_periods = 0; wm.cycle = "rain"; wm.preset = "w_rain2"
wm:change_period()
check(change_periods == 0, "change_period skipped before the world's state is taken")

-- 2. the engine sets the world's clock
now_t = world_t
_G.coop_on_time_jump(world_t - at(2012, 5, 3, 9, 10))
tick(3)
check(stamp(sm.last_surge_time) == "2012,5,3,12,0,0,0" and sm._delta == 30000, "surge timetable is the world's: " ..
	stamp(sm.last_surge_time) .. "|" .. sm._delta)
check(stamp(sm.inited_time) == "2012,5,3,20,20,0,0", "surge inited_time at the world's next one: " .. stamp(sm.inited_time))
check(pm.ended and pm.started == false, "psi storm of the save (not the world's) ended quietly")
check(stamp(pm.last_psi_storm_time) == "2012,5,3,13,0,0,0" and pm._delta == 40000, "psi timetable is the world's")
check(stamp(wm.last_period_change_date) == "2012,5,3,11,0,0,0" and table.concat(wm.weather_storage, ",") == "clear,rain",
	"weather period is the world's")
check(wm.weather_file == "w_rain2" and wm.cycle == "rain", "weather is the world's: " .. tostring(wm.weather_file))
check(SC.updates > 0 and PC.updates > 0, "surge/psi updates run after adoption")
local bad = {}
for _, r in ipairs(reported) do
	local k, v = string.match(r, "^([^=]+)=(.*)$")
	if k ~= "weather" and k ~= "weather_period" and k ~= "surge" and k ~= "psi" then bad[#bad + 1] = r end
end
check(#bad == 0, "only the four facts published")
check(facts.surge == "2012,5,3,12,0,0,0|30000" and facts.psi == "2012,5,3,13,0,0,0|40000", "timetables unchanged on the server")
check(facts.weather_period == "2012,5,3,11,0,0,0|clear,rain", "period unchanged on the server")
check(string.match(facts.weather, "^14|rain|w_rain2|") ~= nil, "weather fact still the world's: " .. facts.weather)

-- 3. leading now: the next hour's turn changes the cycle in our game
change_periods = 0
wm:change_period()
check(change_periods == 1, "change_period runs once leading")

-- 4. another game takes over (the host left): ours follows again, and leads after taking the state anew
master = false
tick(1)
reported = {}
facts.surge = "2012,5,3,15,0,0,0|20000"
sm.started = false
master = true
tick(2)
check(stamp(sm.last_surge_time) == "2012,5,3,15,0,0,0" and sm._delta == 20000, "taken again on becoming master again")

print(FAILED and "SOME FAILED" or "ALL PASSED")
