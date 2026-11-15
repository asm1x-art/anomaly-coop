import sys, os; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from game import Game
fails = []
def check(cond, what):
    print(('ok   ' if cond else 'FAIL ') + what)
    if not cond: fails.append(what)

STUB = r'''
hour = 10
set_weathers = {}
level = { get_time_hours = function() return hour end, is_wfx_playing = function() return false end,
          set_weather = function(f, now) set_weathers[#set_weathers + 1] = f end,
          set_weather_smooth = function(f) set_weathers[#set_weathers + 1] = f end, name = function() return "x" end }
weather = { is_paused = function() return false end }
coop_facts = { on_fact = function() end }
surge_manager = { CSurgeManager = {}, get_surge_manager = function() return nil end }
psi_storm_manager = { CPsiStormManager = {}, get_psi_storm_manager = function() return nil end }
db = { actor = {} }
-- level_weathers' select_weather, its atmosfear branch as vanilla's
WM = {}
WM.__index = WM
function WM:select_weather(now)
  if self.weatherType == "atmosfear" then
    local cycle
    if self.transition_period then cycle = "cloudy"; self.transition_period = false
    elseif self.pre_blowout_period then cycle = "pre_blowout"; self.pre_blowout_period = false
    else cycle = self.cycle or "clear" end
    if self.presets[cycle] then
      if not (self.preset and self.presets[cycle][self.preset]) then self.preset = random_key_table(self.presets[cycle]) end
      self.weather_file = self.preset
    elseif cycle == "pre_blowout" then
      self.weather_file = random_key_table(self.presets_pre_blowout)
    end
  else
    self.weather_file = self.weatherType
  end
  level.set_weather(self.weather_file, now)
end
function WM:change_period() end
level_weathers = { WeatherManager = WM }
function new_wm(kind)
  local wm = setmetatable({ weatherType = kind, cycle = "rain", preset = "w_cloudy3",
    presets = { cloudy = { w_cloudy1 = true, w_cloudy3 = true }, rain = { w_rain1 = true, w_rain2 = true } },
    presets_pre_blowout = { w_pre1 = true, w_pre2 = true } }, WM)
  return wm
end
level_weathers.get_weather_manager = function() return wm end
'''
facts = {}
M = Game('host', facts, None, 3); O = Game('friend', facts, None, 4)
for g in (M, O):
    g.run(STUB); g.load('coop_time')
    g.run('coop_time.on_game_start()')
M.authority = True
M.run('wm = new_wm("indoor")'); O.run('wm = new_wm("atmosfear"); wm.cycle = nil; wm.preset = nil')
def parse(v):
    return v.split('|')
# the master takes the world over at its first pick (coop_time take_state: the hour it came in is the world's)
M.run('hour = 9; wm:select_weather(false)')
f9 = parse(facts['weather'])[4]
O.run('hour = 9; wm:select_weather(false)')
# a change of cycle's hour, master underground
M.run('hour = 10; wm.transition_period = true; wm:select_weather(false)')
w = parse(facts['weather'])
check(w[3] == 't' and w[4] in ('w_cloudy1', 'w_cloudy3'), 'master underground, change of cycle: file published, a cloudy preset (%s)' % facts['weather'])
check(not M.lua.eval('wm.transition_period'), 'and the hour no longer stands in its manager')
check(w[5] == f9, 'underground: the weather before is the file published the hour before (%s, %s)' % (w[5], f9))
f10 = w[4]
O.run('hour = 10; wm:select_weather(false)')
check(O.lua.eval('wm.weather_file') == w[4], 'the other outdoors shows it (%s)' % O.lua.eval('wm.weather_file'))
# next hour, normal: the preset isn't rain's -> one of rain's, published with it
M.run('hour = 11; wm:select_weather(false)')
w = parse(facts['weather'])
check(w[3] == 'n' and w[4] in ('w_rain1', 'w_rain2') and w[2] == w[4], 'next hour: a rain preset, file = preset (%s)' % facts['weather'])
check(w[5] == f10, 'and the weather before is the previous hour file (%s)' % w[5])
O.run('hour = 11; wm:select_weather(false)')
check(O.lua.eval('wm.weather_file') == w[4], 'the other shows the same (%s)' % O.lua.eval('wm.weather_file'))
# a coming surge's hour: one of the surge's, the same through the hour's re-publishes
M.run('hour = 12; wm.pre_blowout_period = true; wm:select_weather(false)')
f1 = parse(facts['weather'])[4]
for i in range(20):
    M.run('now_ms = now_ms + 3000; fire("actor_on_update")')
f2 = parse(facts['weather'])[4]
check(f1 in ('w_pre1', 'w_pre2') and f1 == f2 and parse(facts['weather'])[3] == 'p', 'before a surge: a surge preset, kept through the hour (%s, %s)' % (f1, f2))
O.run('hour = 12; wm:select_weather(false)')
check(O.lua.eval('wm.weather_file') == f1, 'the other shows it (%s)' % O.lua.eval('wm.weather_file'))
# outdoors master unchanged
M.run('wm = new_wm("atmosfear"); hour = 13; wm:select_weather(false)')
check(parse(facts['weather'])[4] == M.lua.eval('wm.weather_file'), 'master outdoors: its own pick, as before (%s)' % facts['weather'])
print('FAILS:', len(fails)); sys.exit(1 if fails else 0)
