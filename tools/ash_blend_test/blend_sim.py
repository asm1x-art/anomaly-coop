# Offline model of CEnvironment's weather selection + the co-op blend (Environment.cpp), ported line by line, to check
# that the shown look (a scalar per frame: "look" and "rain") has no step, whatever the moment the blend begins.
import random, bisect

DAY = 86400.0


def norm(t):
    return t + DAY if t < 0 else (t - DAY if t > DAY else t)


def tdiff(prev, cur):
    return (DAY - prev) + cur if prev > cur else cur - prev


def tweight(val, a, b):
    length = tdiff(a, b)
    w = 0.0
    if abs(length) > 1e-6:
        if a > b:
            if val >= a or val <= b:
                w = tdiff(a, val) / length
        else:
            if a <= val <= b:
                w = tdiff(a, val) / length
        w = min(1.0, max(0.0, w))
    return w


class D:
    def __init__(self, t, look, rain):
        self.exec_time, self.look, self.rain = t, look, rain


def cycle(seed, rainy):
    r = random.Random(seed)
    return [D(h * 3600.0, r.uniform(0, 1), (r.uniform(0.2, 1) if rainy else 0.0)) for h in range(24)]


def select_env(envs, gt):
    times = [e.exec_time for e in envs]
    i = bisect.bisect_left(times, gt)
    return envs[0] if i == len(envs) else envs[i]


def select_envs2(envs, gt):
    times = [e.exec_time for e in envs]
    i = bisect.bisect_left(times, gt)
    if i == len(envs):
        return envs[-1], envs[0]
    return (envs[-1] if i == 0 else envs[i - 1]), envs[i]


class Env:
    def __init__(self, weather, gt, tf):
        self.W = weather
        self.gt, self.tf = gt, tf
        self.C = [None, None]
        self.blend = False
        self.weight = 0
        self.rain = 0

    # SelectEnvs(float)
    def select(self):
        if self.C[0] is None and self.C[1] is None:
            self.C = list(select_envs2(self.W, self.gt))
        else:
            c0, c1 = self.C
            if c0.exec_time > c1.exec_time:
                sel = self.gt > c1.exec_time and self.gt < c0.exec_time
            else:
                sel = self.gt > c1.exec_time
            if sel:
                self.C[0] = self.C[1]
                self.C[1] = select_env(self.W, self.gt)

    def set_weather(self, w, forced):
        if self.blend:
            forced = False
        if forced:
            self.C = [None, None]
            self.blend = False
        self.W = w
        if forced:
            self.select()

    def set_blend(self, w, time, turn, rain_t):
        if self.C[0] is None or time <= 0:
            self.blend = False
            return self.set_weather(w, True)
        time = min(max(time, 1), DAY / 2)
        wt = self.weight if self.blend else tweight(self.gt, self.C[0].exec_time, self.C[1].exec_time)
        back = wt < 0.5
        self.f0 = self.C[1] if back else self.C[0]
        self.f1 = self.C[0] if back else self.C[1]
        self.w0 = 1 - wt if back else wt
        self.turn = max(0, min(turn * 2 * (1 - self.w0), time / 3))
        self.rain0 = self.rain
        self.rain_t = min(max(rain_t, 0), time)
        self.W = w
        te = norm(self.gt + time)
        e0, e1 = select_envs2(w, te)
        self.to = e0 if tweight(te, e0.exec_time, e1.exec_time) < 0.5 else e1
        self.nxt = e1
        self.start, self.end = self.gt, time
        self.next_tm = time + tdiff(te, e1.exec_time)
        self.el = 0
        self.blend = True

    def blend_select(self):
        e = tdiff(self.start, self.gt)
        if e > DAY - 3600:
            e = 0
        self.el = e
        if e < self.turn:
            self.C = [self.f0, self.f1]
            return True, self.w0 + (1 - self.w0) * e / self.turn
        if e < self.end:
            self.C = [self.f1, self.to]
            return True, (e - self.turn) / (self.end - self.turn)
        if e < self.next_tm:
            self.C = [self.to, self.nxt]
            return True, (e - self.end) / (self.next_tm - self.end)
        self.blend = False
        if e - self.next_tm < 600:
            self.C = [self.nxt, select_env(self.W, self.gt)]
        else:
            self.C = [None, None]
        return False, 0

    def frame(self, dt_real):
        self.gt = norm(self.gt + dt_real * self.tf)
        ok = False
        if self.blend:
            ok, w = self.blend_select()
        if not ok:
            self.select()
            w = tweight(self.gt, self.C[0].exec_time, self.C[1].exec_time)
        a, b = self.C
        self.weight = w
        look = (1 - w) * a.look + w * b.look
        rain = (1 - w) * a.rain + w * b.rain
        if self.blend and self.rain_t > 0 and self.el < self.end:
            rain = self.rain0 + (self.to.rain - self.rain0) * min(1, self.el / self.rain_t)
        self.rain = rain
        return look, rain


def run(seed):
    r = random.Random(seed)
    tf = r.choice([6, 10, 12])
    world = cycle(seed, rainy=True)
    world2 = cycle(seed + 1000, rainy=True)
    ash = cycle(seed + 2000, rainy=False)
    gt = r.uniform(0, DAY)
    env = Env(world, gt, tf)
    env.select()
    dt = 1 / 30
    prev = None
    worst = 0  # the biggest per-frame step of the look, against the steepest normal hourly change per frame
    steps = []
    t_real = 0
    start_in = r.uniform(5, 200)
    start_out = start_in + r.uniform(100, 900)
    retarget = r.uniform(0, 2000)
    rain_after_in = None
    events = []
    while t_real < start_out + 1500:
        if prev is not None and t_real - dt < start_in <= t_real:
            env.set_blend(ash, 180 * tf, 20 * tf, 30 * tf)
        if t_real - dt < start_out <= t_real:
            env.set_blend(world, 300 * tf, 20 * tf, 120 * tf)
        if t_real - dt < retarget <= t_real:
            env.set_weather(world2 if env.W is world else env.W, r.random() < 0.5)  # an hourly pick / forced pick
        look, rain = env.frame(dt)
        if prev is not None:
            steps.append((abs(look - prev[0]), abs(rain - prev[1]), t_real))
        if start_in + 30 <= t_real < start_out and rain > 1e-6 and t_real > start_in + 31:
            events.append(('rain under the ash', t_real, rain))
        prev = (look, rain)
        t_real += dt
    # normal speed: one frame change of up to 1 over an hour of game time
    normal = dt * tf / 3600.0
    big = max(s[0] for s in steps)
    bigr = max(s[1] for s in steps)
    return big / normal, bigr / normal, events[:1], tf


if __name__ == '__main__':
    worst_look = worst_rain = 0
    bad = 0
    for seed in range(300):
        l, rr, ev, tf = run(seed)
        worst_look = max(worst_look, l)
        worst_rain = max(worst_rain, rr)
        if ev:
            bad += 1
            if bad < 4:
                print('seed', seed, ev)
    print('worst step of the look: %.1fx the normal hourly rate per frame' % worst_look)
    print('worst step of the rain: %.1fx' % worst_rain)
    print('runs with rain left under the ash after 30 s:', bad)
