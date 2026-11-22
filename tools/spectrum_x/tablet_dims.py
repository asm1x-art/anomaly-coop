"""Spectrum-X landscape tablet: its dimensions (m), shared by make_tablet.py (Blender) and tablet_prints.py (PIL).
The tablet's own coords: x down the screen, y to the screen's right, z out of the glass, z = 0 at the back."""
HW, HH = 0.089, 0.059          # rubber frame half width (y) / half height (x): 178 x 118 mm
FRONT = 0.023                  # bezel front (the body's thickness)
BEZ_L, BEZ_R, BEZ_T, BEZ_B = 0.036, 0.036, 0.015, 0.017     # bezel widths: left, right, top, bottom
GLASS_Z = FRONT - 0.0035       # glass surface, 3.5 mm under the bezel front
WIN_R = 0.003                  # window corner radius
WIN = (-HH + BEZ_T, HH - BEZ_B, -HW + BEZ_L, HW - BEZ_R)    # x0, x1, y0, y1
BTN_Y = 0.064                  # button column, |y|: the bezel's inner half, where the thumb lies
BTN_HX, BTN_HY = 0.0058, 0.0048  # button half sizes (x along the column)
BTN_X = (0.031, 0.0455)        # P1, P2 (left) and +, - (right): the thumbs' rows, where the thumbs lie when the
                               # hands hold the lower corners (hud_rig.LEFT_GRIP / TAB_GRIP)
PWR_X = -0.002
BTN_TOP = FRONT + 0.0016
SOCK = (HH, 0.0, FRONT / 2)       # cable socket in the bottom edge's middle (the hands hold the lower corners): x of the edge, y, z
SOCK_LEN, SOCK_R = 0.0075, 0.0058
BUMPER = 0.012                 # corner bumper half size (square, rounded)
SEG = 12                       # segments per rounded corner

BUTTONS = {"p1": (BTN_X[0], -BTN_Y, BTN_TOP), "p2": (BTN_X[1], -BTN_Y, BTN_TOP),
           "plus": (BTN_X[0], BTN_Y, BTN_TOP), "minus": (BTN_X[1], BTN_Y, BTN_TOP), "power": (PWR_X, BTN_Y, BTN_TOP)}
BOX = (-0.070, 0.070, -0.100, 0.100)      # x0, x1, y0, y1 covered by the print images (front and back)
PPM = 20000                                # print pixels per metre (20 px/mm)
