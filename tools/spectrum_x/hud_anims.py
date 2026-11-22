r"""Spectrum-X HUD animations as functions of time: where each hand is (a HUD-camera-space matrix of the hand bone)
and how far the left thumb is pressed, at t seconds. hud_rig.Rig puts the arms there with IK.

Motion is built from a few key poses (base, measuring, lowered, menu, sprint, bore) blended with easing curves,
damped springs for the settles (a little overshoot, weight), staggered starts between the hands, and periodic
layers for breathing and walking (whole cycles in a loop, so loops join). Camera space, Blender axes: x right,
y forward, z up; offsets are (dx, dy, dz metres, pitch, roll, yaw degrees) about a pivot carried by the hand
(the probe's grip, the tablet's centre)."""
import math
from mathutils import Matrix, Vector, Quaternion, Euler
import hud_rig as hr

FPS = 30
TAU = 2 * math.pi


# ---------------------------------------------------------------- curves
def c01(x): return 0.0 if x < 0 else 1.0 if x > 1 else x
def smooth(x): x = c01(x); return x * x * (3 - 2 * x)
def ease_io(x): x = c01(x); return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2
def ease_out(x): x = c01(x); return 1 - (1 - x) ** 3
def ease_in(x): x = c01(x); return x ** 3


def ease_out_back(x, s=1.2):
    x = c01(x); y = x - 1
    return 1 + (s + 1) * y ** 3 + s * y ** 2


def spring(t, w=14.0, z=0.7):
    """step response of a damped spring: 0 at t<=0, overshoots a little, settles to 1"""
    if t <= 0: return 0.0
    wd = w * math.sqrt(1 - z * z)
    return 1 - math.exp(-z * w * t) * (math.cos(wd * t) + z * w / wd * math.sin(wd * t))


def land(k, t, t_end, span=0.12):
    """make a curve exactly 1 by t_end (what is left of a spring's wobble fades out over span)"""
    return 1 + (k - 1) * (1 - smooth((t - (t_end - span)) / span))


# ---------------------------------------------------------------- rigid transforms
def rot_of(o):
    return Euler((math.radians(o[3]), math.radians(o[4]), math.radians(o[5])), "XYZ").to_matrix().to_4x4()


def moved(H, o, pv_local):
    """hand matrix H moved by offset o about the pivot carried by the hand"""
    pw = H @ Vector(pv_local)
    return Matrix.Translation(pw + Vector(o[:3])) @ rot_of(o) @ Matrix.Translation(-pw) @ H


def blend(Ha, Hb, k, pv_local):
    """from Ha to Hb (k may go past 0..1: a spring's overshoot), the pivot on a straight line, the turn about it"""
    pa, pb = Ha @ Vector(pv_local), Hb @ Vector(pv_local)
    qa, qb = Ha.to_quaternion(), Hb.to_quaternion()
    d = qb @ qa.inverted()
    if d.w < 0: d.negate()
    ang = d.angle
    q = Quaternion(d.axis, ang * k) @ qa if ang > 1e-9 else qa
    p = pa.lerp(pb, k)
    R3 = q.to_matrix()
    return Matrix.Translation(p - R3 @ Vector(pv_local)) @ R3.to_4x4()


# ---------------------------------------------------------------- the key poses
# where the tablet is held, HUD camera space (Blender axes: x right, y forward, z up): the screen's centre (m) and
# its turn from square-on (degrees): pitch < 0 = top away from the eye, yaw > 0 = screen turned toward the right,
# roll > 0 = turned clockwise as seen
HOLD = dict(centre=(-0.085, 0.47, -0.060), pitch=-30.0, yaw=15.0, roll=-5.0)     # one hand, the probe in the right
MENU = dict(centre=(0.0, 0.34, -0.022), pitch=-8.0, yaw=0.0, roll=0.0)          # both hands, raised for reading
PROBE_AWAY = (0.10, -0.12, -0.36, -70.0, 10.0, 25.0)   # the probe holstered out of view in the menu (offset as in moved())


class Poses:
    def __init__(self, rig, aim_point=(0.045, 0.58, 0.0)):
        R = rig; B = R.base; O = hr.OURS
        self.rig = R
        self.R0 = O @ B["r_hand"]
        self.L0 = self.tablet_hand(**HOLD)
        # pivots in the hands' own frames: the probe's grip, the tablet's centre (in the base pose)
        self.pvR = tuple(B["r_hand"].inverted() @ (R.item_arm(B) @ R.grip_item))
        self.pvL = tuple(B["l_hand"].inverted() @ (R.tab_arm(B) @ Vector((0.0, 0.0, 0.013))))
        # measuring (RMB): the lens ahead, a bit right of centre and low, pointing forward
        iw = O @ R.item_arm(B)
        lens = iw @ R.lens_item; fwd = (iw.to_3x3() @ Vector((0, 1, 0))).normalized()
        rot = fwd.rotation_difference(Vector((0, 1, 0)))
        T = Matrix.Translation(Vector(aim_point)) @ rot.to_matrix().to_4x4() @ Matrix.Translation(-lens)
        self.R_aim = T @ self.R0
        self.L_aim = moved(self.L0, (-0.012, 0.0, -0.014, 5, 0, 4), self.pvL)
        # probe lowered out of the way, tablet up for reading in both hands
        self.R_low = moved(self.R0, (0.07, -0.05, -0.23, -48, 10, 18), self.pvR)
        self.L_menu = self.tablet_hand(**MENU)
        # sprint: both held low and turned in
        self.R_spr = moved(self.R0, (0.03, -0.05, -0.11, -32, 14, 10), self.pvR)
        self.L_spr = moved(self.L0, (-0.02, -0.04, -0.08, -24, -10, -8), self.pvL)
        # bore: the tablet up and tilted toward the eyes
        self.L_bore = moved(self.L0, (0.04, -0.07, 0.05, 20, 0, -10), self.pvL)
        self.R_bore = moved(self.R0, (0.01, -0.01, -0.02, 0, 22, -14), self.pvR)

    def tablet_cam(self, centre, pitch, yaw, roll):
        """the tablet's own coords -> HUD camera space, for a wanted screen centre and turn"""
        M = Matrix(((0, 1, 0), (0, 0, -1), (-1, 0, 0)))        # columns: x (down) -> -z, y (right) -> +x, z (out) -> -y
        Rm = (Matrix.Rotation(math.radians(yaw), 3, "Z") @ Matrix.Rotation(math.radians(pitch), 3, "X")
              @ Matrix.Rotation(math.radians(-roll), 3, "Y") @ M).to_4x4()
        x0, x1, y0, y1, z = hr.SCREEN
        c = Rm @ Vector(((x0 + x1) / 2, (y0 + y1) / 2, z))
        return Matrix.Translation(Vector(centre) - c) @ Rm

    def tablet_hand(self, centre, pitch, yaw, roll):
        """the left hand (camera space) that puts the tablet there: tablet = hand @ L2T @ A_tab"""
        R = self.rig
        return self.tablet_cam(centre, pitch, yaw, roll) @ R.A_tab.inverted() @ R.L2T.inverted()

    def menu_hand(self, dist):
        return self.tablet_hand(**dict(MENU, centre=(MENU["centre"][0], dist, MENU["centre"][2])))


# ---------------------------------------------------------------- the animations
class Anims:
    def __init__(self, P):
        self.P = P
        # name: (duration s, loop, function)
        self.table = {
            "draw": (0.80, False, self.draw), "holster": (0.60, False, self.holster),
            "idle": (4.0, True, self.idle), "idle_moving": (0.93, True, self.walk),
            "idle_sprint": (0.70, True, self.sprint), "idle_crouch": (1.40, True, self.crouch),
            "aim_start": (0.35, False, self.aim_start), "aim": (2.0, True, self.aim), "aim_end": (0.30, False, self.aim_end),
            "bore": (3.6, False, self.bore),
            "menu_open": (0.75, False, self.menu_open), "menu_idle": (3.0, True, self.menu_idle),
            "menu_close": (0.65, False, self.menu_close), "switch": (0.50, False, self.switch),
        }

    def frames(self, name):
        D, loop, f = self.table[name]
        n = int(round(D * FPS)) + 1
        return [f(D * i / (n - 1), D) for i in range(n)]     # the last frame exactly at the end

    # breathing: a slow cycle, the right hand a little behind the left
    def breath(self, t, D, amp=1.0, cycles=1):
        P = self.P
        b = math.sin(TAU * cycles * t / D); b2 = math.sin(TAU * 2 * cycles * t / D + 1.0)
        br = math.sin(TAU * cycles * t / D - 0.5); b2r = math.sin(TAU * 2 * cycles * t / D + 0.4)
        lo = (0.0008 * b2 * amp, 0.0, 0.0022 * b * amp, 0.5 * b * amp, 0.25 * b2 * amp, 0.0)
        ro = (0.0006 * b2r * amp, 0.0, 0.0018 * br * amp, 0.4 * br * amp, 0.0, 0.3 * b2r * amp)
        return ro, lo

    def draw(self, t, D):
        P = self.P
        out = []
        for H0, pv, dl, start in ((P.R0, P.pvR, 0.07, (0.05, -0.06, -0.30, -42, 12, -14)),
                                  (P.L0, P.pvL, 0.0, (-0.06, -0.06, -0.28, -38, -14, 16))):
            Hs = moved(H0, start, pv)
            u = t - dl
            k = land(spring(u, w=13.0, z=0.68), t, D)
            out.append(blend(Hs, H0, k, pv))
        return out[0], out[1], 0.0

    def holster(self, t, D):
        P = self.P
        out = []
        for H0, pv, dl, end in ((P.R0, P.pvR, 0.0, (0.05, -0.05, -0.32, -46, 14, -12)),
                                (P.L0, P.pvL, 0.06, (-0.06, -0.05, -0.30, -40, -16, 14))):
            u = c01((t - dl) / (D - 0.06))
            # a small lift first (the weight is taken), then down, faster and faster
            k = ease_in(u) * 1.04 - 0.04 * math.sin(math.pi * min(u * 2.5, 1.0))
            out.append(blend(H0, moved(H0, end, pv), k, pv))
        return out[0], out[1], 0.0

    def idle(self, t, D):
        P = self.P
        ro, lo = self.breath(t, D)
        return moved(P.R0, ro, P.pvR), moved(P.L0, lo, P.pvL), 0.0

    def gait(self, t, T, R0, L0, A, Bx, roll, pitch):
        P = self.P; ph = TAU * t / T
        out = []
        for H0, pv, lag, side in ((R0, P.pvR, 0.28, 1), (L0, P.pvL, 0.0, -1)):
            p = ph - lag
            o = (Bx * math.sin(p), 0.0025 * math.cos(2 * p), -A * 0.5 * (1 + math.cos(2 * p - 0.5)),
                 pitch * math.cos(2 * p - 0.5), roll * math.sin(p - 0.3), 0.8 * math.sin(p) * side)
            out.append(moved(H0, o, pv))
        return out[0], out[1], 0.0

    def walk(self, t, D):
        return self.gait(t, D, self.P.R0, self.P.L0, 0.006, 0.007, 1.5, 0.9)

    def sprint(self, t, D):
        return self.gait(t, D, self.P.R_spr, self.P.L_spr, 0.013, 0.014, 3.0, 2.0)

    def crouch(self, t, D):
        return self.gait(t, D, self.P.R0, self.P.L0, 0.004, 0.005, 1.0, 0.6)

    def aim_start(self, t, D):
        P = self.P
        kr = ease_out_back(t / D, 1.1)
        kl = ease_io((t - 0.05) / (D - 0.05))
        return blend(P.R0, P.R_aim, kr, P.pvR), blend(P.L0, P.L_aim, kl, P.pvL), 0.0

    def aim(self, t, D):
        P = self.P
        a = TAU * t / D
        ro = (0.0005 * math.sin(2 * a), 0.0, 0.0008 * math.sin(a), 0.25 * math.sin(a + 1.0), 0.0, 0.2 * math.sin(3 * a))
        _, lo = self.breath(t, D, 0.8)
        return moved(P.R_aim, ro, P.pvR), moved(P.L_aim, lo, P.pvL), 0.0

    def aim_end(self, t, D):
        P = self.P
        kr = land(spring(t, w=16.0, z=0.8), t, D, 0.08)
        kl = ease_io(t / (D - 0.03))
        return blend(P.R_aim, P.R0, kr, P.pvR), blend(P.L_aim, P.L0, kl, P.pvL), 0.0

    def press(self, t, t0, down=0.14, hold=0.07, up=0.18):
        """the thumb's press: 0 -> 1 -> 0 starting at t0"""
        if t < t0: return 0.0
        if t < t0 + down: return ease_io((t - t0) / down)
        if t < t0 + down + hold: return 1.0
        return 1.0 - ease_io((t - t0 - down - hold) / up)

    def bore(self, t, D):
        P = self.P
        kl = ease_io(t / 0.7) if t < 2.6 else 1 - ease_io((t - 2.6) / 0.95)
        look = (0.0, 0.0, 0.004 * math.sin(TAU * t / 1.8), 2.0 * math.sin(TAU * t / 2.4), 0.0, 3.0 * math.sin(TAU * t / 3.6))
        L = moved(blend(P.L0, P.L_bore, kl, P.pvL), tuple(x * kl for x in look), P.pvL)
        kr = smooth((t - 1.8) / 0.45) if t < 2.5 else 1 - ease_io((t - 2.5) / 0.75)
        R = blend(P.R0, P.R_bore, kr, P.pvR)
        ro, lo = self.breath(t, D, 0.6)
        return moved(R, ro, P.pvR), L, self.press(t, 1.25)

    def menu_open(self, t, D):
        P = self.P
        kr = ease_io(t / 0.45)
        kl = land(spring(t - 0.08, w=11.0, z=0.82), t, D)
        return blend(P.R0, P.R_low, kr, P.pvR), blend(P.L0, P.L_menu, kl, P.pvL), 0.0

    def menu_idle(self, t, D):
        P = self.P
        ro, lo = self.breath(t, D, 0.35)
        return moved(P.R_low, ro, P.pvR), moved(P.L_menu, lo, P.pvL), 0.0

    def menu_close(self, t, D):
        P = self.P
        kl = ease_io(t / 0.5)
        kr = land(spring(t - 0.12, w=13.0, z=0.72), t, D)
        return blend(P.R_low, P.R0, kr, P.pvR), blend(P.L_menu, P.L0, kl, P.pvL), 0.0

    def switch(self, t, D):
        P = self.P
        w = self.press(t, 0.05, 0.13, 0.07, 0.2)
        lo = (0.0, 0.0, -0.0015 * w, 1.2 * w, 0.0, 0.6 * w)
        return P.R0, moved(P.L0, lo, P.pvL), w
