# Offline harness for coop_zone_ash.script's sky blend: the Lua under LuaJIT (lupa) with stubs, against the engine's
# blend ported in blend_sim.py (same frames, same clock).
import os, sys, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import blend_sim as B
from lupa import luajit21

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'gamedata', 'scripts', 'coop_zone_ash.script')
src = open(SRC, 'rb').read().decode('cp1251')
src += """
function __test(ze)
	ZE = ze
	return { update_weather = update_weather, rain_after = rain_after, world_rain = world_rain }
end
"""

L = luajit21.LuaRuntime(unpack_returned_tuples=True)
frames = {}

L.execute("""
CFG = {}
ini_sys = {
	r_string_ex = function(self, s, k) return CFG[k] end,
	r_float_ex = function(self, s, k) local v = CFG[k] return v and tonumber(v) end,
	r_bool_ex = function(self, s, k, d) return d end,
}
""")
g = L.globals()
state = L.table_from({'now': 1000000, 'gt': 12 * 3600 + 1234, 'tf': 6, 'weather': 'w_world', 'fact': ''})
cfg = g.CFG
for k, v in {'weather_blend_in_s': 180, 'weather_blend_out_s': 300, 'weather_rain_in_s': 30,
             'weather_rain_out_s': 120, 'weather_turn_s': 20, 'weather': 'w_zev_ash', 'slot': 'world'}.items():
    cfg[k] = v


def py_frames(file):
    f = frames.get(file)
    return f and L.table_from([L.table_from(list(x)) for x in f])


g.py_state = state
g.py_frames = py_frames
L.execute("""
py_calls = {}
level = {
	name = function() return "l08_yantar" end,
	get_weather = function() return py_state.weather end,
	set_weather = function(f, now) py_state.weather = f; table.insert(py_calls, { "set", f, now }) end,
	set_weather_blend = function(f, s, turn, rain) py_state.weather = f; table.insert(py_calls, { "blend", f, s, turn, rain }) end,
	get_time_factor = function() return py_state.tf end,
	rain_factor = function() return -1 end,
}
local wm = { weather_file = "w_world", select_weather = function(self, now) table.insert(py_calls, { "select", now }) end }
level_weathers = { get_weather_manager = function() return wm end }
game = { get_game_time = function()
	return { get = function()
		local t = math.floor(py_state.gt)
		return 2012, 1, 1, math.floor(t / 3600), math.floor(t % 3600 / 60), t % 60, 0
	end }
end }
coop = { connected = function() return true end, fact = function(k) return k == "weather" and py_state.fact or "" end }
function ini_file(path)
	local file = string.match(path, "([^\\\\]+)%.ltx$")
	local list = py_frames(file)
	if not list then return nil end
	return {
		section_for_each = function(self, fn)
			for i = 1, #list do fn(list[i][1]) end
		end,
		r_float_ex = function(self, section, key)
			for i = 1, #list do if list[i][1] == section then return list[i][2] end end
		end,
	}
end
""")
L.execute(src)
ZE = L.eval("""function(st)
	return {
		now = function() return st.now end,
		get = function(slot) return st.ev end,
		dbg = function() end,
		mark_of = function() return "" end,
	}
end""")(state)
T = g.__test(ZE)


def ev(stage, frm, till):
    return L.table_from({'id': 'ash', 'level': 'l08_yantar', 'stage': stage, 'from': frm, 'till': till})


def calls():
    out = [tuple(c[i] for i in range(1, len(c) + 1)) for c in g.py_calls.values()]
    L.execute("py_calls = {}")
    return out


fails = 0


def check(name, cond, info=''):
    global fails
    print(('ok   ' if cond else 'FAIL ') + name, info)
    fails += 0 if cond else 1


def reset():
    L.execute("py_calls = {}")
    # a fresh game: the module's own state as after a load
    L.execute(src)
    global T
    T = g.__test(ZE)


# 1 a game on the level when the front starts
reset()
e = ev('on', state['now'], state['now'] + 3 * 3600)
state['ev'] = e
check('before the blend the world weather (no state, front just began)', g.weather() is None)
T.update_weather(e)
c = calls()
check('blend in at the start', c == [('blend', 'w_zev_ash', 180, 20, 30)], c)
check('weather() now the ash', g.weather() == 'w_zev_ash')
T.update_weather(e)
check('no second blend', calls() == [])

# 2 a game that comes 60 s into the front
reset()
e = ev('on', state['now'] - 60, state['now'] + 3 * 3600)
state['ev'] = e
check('joiner in the blend: world weather first', g.weather() is None)
T.update_weather(e)
c = calls()
check('joiner takes the rest (120 s, rain already gone)', c and c[0][0] == 'blend' and c[0][2] == 120 and c[0][4] < 0.1, c)

# 3 a game that comes 10 min into the front
reset()
e = ev('on', state['now'] - 600, state['now'] + 3 * 3600)
state['ev'] = e
state['weather'] = 'w_zev_ash'
check('late joiner: the ash at once', g.weather() == 'w_zev_ash')
T.update_weather(e)
check('late joiner: nothing more', calls() == [])

# 4 the front ends with the game there
e_end = ev('end', state['now'] - 600, state['now'])
state['ev'] = e_end
T.update_weather(e_end)
c = calls()
check('blend out at the end, then the manager picks (deferred)', c == [('blend', 'w_world', 300, 20, 120), ('select', False)], c)
check('weather() the world again', g.weather() is None)

# 5 a game that comes 100 s after the end
reset()
state['weather'] = 'w_world'
e_end = ev('end', state['now'] - 1000, state['now'] - 100)
state['ev'] = e_end
check('joiner after the end: the ash first', g.weather() == 'w_zev_ash')
T.update_weather(e_end)
c = calls()
check('joiner after the end: the rest of the blend back', c and c[0][:3] == ('blend', 'w_world', 200) and abs(c[0][4] - 20) < 1e-6, c)

# 6 long after the end
reset()
e_end = ev('end', state['now'] - 5000, state['now'] - 1000)
state['ev'] = e_end
check('long after: no ash', g.weather() is None)
T.update_weather(e_end)
check('long after: nothing', calls() == [])

# 7 the master's rain model vs the engine's blend out of the ash
worst = 0
for seed in range(200):
    r = random.Random(seed)
    tf = r.choice([6, 10, 12])
    world = B.cycle(seed, rainy=True)
    ash = B.cycle(seed + 7, rainy=False)
    frames['w_world'] = [('%02d:00:00' % h, world[h].rain) for h in range(24)]
    reset()
    start = r.uniform(0, B.DAY)
    env = B.Env(ash, start, tf)
    env.select()
    env.frame(0)
    env.set_blend(world, 300 * tf, 20 * tf, 120 * tf)
    state['tf'] = tf
    state['fact'] = '%d|clear|w_world|n|w_world|w_world' % int(start // 3600)
    till = 2000000
    t_real = 0
    dt = 0.5
    e_end = ev('end', till - 5000, till)
    while t_real < 1500:
        _, rain = env.frame(dt)
        t_real += dt
        state['now'] = till + t_real
        state['gt'] = env.gt
        model = T.rain_after(e_end, T.world_rain())
        worst = max(worst, abs(model - rain))
check('the master\'s rain after the front = the engine\'s blend (worst gap %.3f)' % worst, worst < 0.02)
print('fails', fails)

# a sample: seed 3, both curves
r = random.Random(3); tf = r.choice([6, 10, 12]); world = B.cycle(3, rainy=True); ash = B.cycle(10, rainy=False)
frames['w_world'] = [('%02d:00:00' % h, world[h].rain) for h in range(24)]; reset()
start = r.uniform(0, B.DAY); env = B.Env(ash, start, tf); env.select(); env.frame(0)
env.set_blend(world, 300 * tf, 20 * tf, 120 * tf); state['tf'] = tf
state['fact'] = '%d|clear|w_world|n|w_world|w_world' % int(start // 3600)
e_end = ev('end', 0, 2000000); t = 0
while t < 1200:
    _, rain = env.frame(0.5); t += 0.5; state['now'] = 2000000 + t; state['gt'] = env.gt
    if t % 100 == 0: print(t, round(rain, 3), round(T.rain_after(e_end, T.world_rain()), 3))
