# =============================================================================
#  Decentralised Swarm Intelligence — SAR City Visualiser  |  Ursina 8.x
# =============================================================================
#  Controls
#    Right-click + drag  : orbit / tilt
#    Scroll wheel        : zoom
#    Middle-drag / WASD  : pan
#    SPACE               : dispatch drone mission
#
#  API hook: replace the `elif key == 'space'` line with
#            invoke(execute_mission, delay=0)  from FastAPI / MCP / LLM
# =============================================================================

from ursina import *

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

GRID_CELLS   = 26
GRID_SPACING =  2

BX, BZ       =  0,  0       # glass target building centre
NUM_FLOORS   =  4
FLOOR_H      =  3.0
FLOOR_W, FLOOR_D =  8,  8
FLOOR_T      =  0.20
SURV_HOVER   =  0.55

DRONE_START  = Vec3(13, 1, 13)
T_FLY_F2, T_PAUSE, T_FLY_F4 = 3.0, 1.5, 3.0

def slab_y(n): return (n - 1) * FLOOR_H
def surv_y(n): return slab_y(n) + FLOOR_T / 2 + SURV_HOVER

# ─────────────────────────────────────────────────────────────────────────────
#  ENGINE
#  base.setBackgroundColor() sets the Panda3D clear colour — more reliable
#  than window.color in Ursina 8.x and cannot be overridden by a sky entity.
# ─────────────────────────────────────────────────────────────────────────────

app = Ursina(title='SAR City Visualiser')
base.setBackgroundColor(0.05, 0.05, 0.09, 1)   # dark navy — never appears white

W = 'white_cube'   # every solid entity needs this so Ursina's colour pipeline
                   # tints correctly; without it the renderer falls back to white.

span     = GRID_CELLS * GRID_SPACING
half     = span / 2
total_h  = NUM_FLOORS * FLOOR_H

# ─────────────────────────────────────────────────────────────────────────────
#  GROUND — asphalt base
# ─────────────────────────────────────────────────────────────────────────────

Entity(model='plane', scale=(span, 1, span),
       color=color.rgb32(36, 36, 40), texture=W, texture_scale=(26, 26))

# ─────────────────────────────────────────────────────────────────────────────
#  ROADS + MARKINGS
# ─────────────────────────────────────────────────────────────────────────────

ROAD = color.rgb32(48, 48, 54)
LINE = color.rgb32(215, 205, 165)

Entity(model='cube', position=(0,0.02,0), scale=(span,0.01,5),    color=ROAD, texture=W)  # E–W
Entity(model='cube', position=(0,0.02,0), scale=(5,0.01,span),    color=ROAD, texture=W)  # N–S
Entity(model='cube', position=(0,0.03,0), scale=(span,0.01,0.14), color=LINE, texture=W)  # E–W centre line
Entity(model='cube', position=(0,0.03,0), scale=(0.14,0.01,span), color=LINE, texture=W)  # N–S centre line

# ─────────────────────────────────────────────────────────────────────────────
#  PARKS — green ground patches
# ─────────────────────────────────────────────────────────────────────────────

for px, pz, pw, pd in [(-7, 7, 9, 9), (11, -11, 7, 7), (-16, -6, 6, 6)]:
    Entity(model='cube', position=Vec3(px, 0.02, pz), scale=(pw, 0.01, pd),
           color=color.rgb32(40, 108, 52), texture=W)

# ─────────────────────────────────────────────────────────────────────────────
#  GRID OVERLAY — subtle city-block grid on the ground
# ─────────────────────────────────────────────────────────────────────────────

for i in range(GRID_CELLS + 1):
    p     = -half + i * GRID_SPACING
    major = (i % 5 == 0)
    tone  = color.rgb32(58, 62, 68) if major else color.rgb32(42, 44, 50)
    th    = 0.06 if major else 0.025
    Entity(model='cube', position=(0, 0.01, p),  scale=(span, 0.01, th),   color=tone, texture=W)
    Entity(model='cube', position=(p, 0.01, 0),  scale=(th,   0.01, span), color=tone, texture=W)

# ─────────────────────────────────────────────────────────────────────────────
#  TREES — trunk (thin cube) + canopy (sphere)
#  Note: Ursina 8.x has no built-in 'cylinder' model; use scaled cube instead.
# ─────────────────────────────────────────────────────────────────────────────

TRUNK = color.rgb32(95, 65, 38)
LEAF  = color.rgb32(38, 118, 50)

TREE_XZ = [
    (-4,5),(-5,8),(-8,5),(-7,9),(-9,8),(-5,6),          # park 1
    (9,-9),(12,-13),(13,-10),(10,-13),                    # park 2
    (-14,-4),(-17,-8),(-15,-8),                          # park 3
    (4,3),(4,-3),(-4,3),(-4,-3),                         # street trees
    (10,3),(10,-3),(-10,3),(-10,-3),(16,3),(16,-3),
]
for tx, tz in TREE_XZ:
    Entity(model='cube',   position=Vec3(tx, 0.65, tz), scale=(0.18,1.3,0.18), color=TRUNK, texture=W)
    Entity(model='sphere', position=Vec3(tx, 1.7,  tz), scale=0.9,             color=LEAF,  texture=W)

# ─────────────────────────────────────────────────────────────────────────────
#  CITY BUILDINGS — body + lighter roof cap
#  cols: cx  cz   w   d    h   body-R  G   B   roof-R  G   B
# ─────────────────────────────────────────────────────────────────────────────

CITY = [
    (-14,-12, 8, 8,20,  70, 98,145,  90,118,165),   # blue glass tower    NW
    ( 14,-10, 7, 9,14, 188,165,128, 205,182,145),   # warm concrete       NE
    (-16, 10, 9, 7, 9, 198,182,150, 212,198,168),   # beige block         SW
    ( 16, 14, 7, 8,24,  48, 62, 82,  68, 82,102),   # charcoal tower      SE
    (  0,-20,14, 6, 7, 178,175,165, 192,190,180),   # flat white block    N
    (-22,  2, 7, 7,16,  82,118,158, 102,138,178),   # steel-blue          W
    ( 20,  0, 9, 8,12, 168,108, 72, 185,128, 90),   # terracotta          E
    (  0, 22,10, 9,15,  70, 85, 98,  90,105,118),   # slate               S
    (  8,-15, 5, 5,22,  52, 72,110,  72, 92,130),   # cobalt slim
    ( -8, 17, 8, 6,10, 190,175,145, 208,192,162),   # limestone
    (-10, -8, 4, 4,30,  38, 54, 88,  56, 72,108),   # ultra-slim skyscraper
    ( 10,  8, 6, 6,11, 152,118, 90, 168,135,108),   # brick-orange
    ( -6,-18, 6, 6,18,  55, 78,118,  75, 98,138),   # cobalt tower
    ( 18, -6, 5, 8,16, 118,138,152, 138,158,172),   # silver steel
    (-18, -4, 8, 5, 8, 205,190,160, 218,205,175),   # sandstone
    (  5,-10, 4, 4,12,  88,130, 80, 108,150,100),   # green glass
    (-12, 14, 6, 5,14, 148, 72, 62, 165, 90, 78),   # brick-red
    ( 15,  5, 5, 7,19,  60, 80,112,  80,100,132),   # dusk blue
    (-20, 18, 6, 6,10,  98,142,115, 118,162,135),   # jade
    (  6, 18, 7, 5, 8, 178,148,110, 195,165,128),   # caramel
]

for cx, cz, w, d, h, wr, wg, wb, rr, rg, rb in CITY:
    Entity(model='cube', position=Vec3(cx, h/2,    cz), scale=(w, h,    d),
           color=color.rgb32(wr, wg, wb), texture=W)
    Entity(model='cube', position=Vec3(cx, h+0.08, cz), scale=(w, 0.16, d),
           color=color.rgb32(rr, rg, rb), texture=W)

# Horizontal glass-band accent at each floor level on tall buildings
for cx, cz, w, d, h, *_ in CITY:
    if h >= 14:
        for fi in range(1, int(h // FLOOR_H)):
            band = Entity(model='cube', position=Vec3(cx, fi * FLOOR_H, cz),
                          scale=(w * 0.92, 0.28, d * 0.92),
                          color=color.rgb32(170, 210, 240), texture=W)
            band.alpha = 0.45

# ─────────────────────────────────────────────────────────────────────────────
#  TARGET BUILDING — glass curtain-wall tower (survivors visible inside)
# ─────────────────────────────────────────────────────────────────────────────

hw, hd = FLOOR_W / 2, FLOOR_D / 2

# Concrete floor slabs (solid)
for n in range(NUM_FLOORS + 1):
    Entity(model='cube', position=Vec3(BX, n * FLOOR_H, BZ),
           scale=(FLOOR_W, FLOOR_T, FLOOR_D),
           color=color.rgb32(148, 162, 175), texture=W)

# Glass walls (semi-transparent)
GLASS = color.rgb32(125, 188, 225)
for pos, scl in [
    ((BX,      total_h/2, BZ - hd), (FLOOR_W, total_h, 0.12)),
    ((BX,      total_h/2, BZ + hd), (FLOOR_W, total_h, 0.12)),
    ((BX - hw, total_h/2, BZ),      (0.12, total_h, FLOOR_D)),
    ((BX + hw, total_h/2, BZ),      (0.12, total_h, FLOOR_D)),
]:
    g = Entity(model='cube', position=pos, scale=scl, color=GLASS, texture=W)
    g.alpha = 0.25

# ─────────────────────────────────────────────────────────────────────────────
#  SURVIVORS  (red thermal spheres)  +  DRONE
# ─────────────────────────────────────────────────────────────────────────────

survivor_f2 = Entity(model='sphere', color=color.red, scale=0.65, texture=W,
                     position=Vec3(BX - 1.5, surv_y(2), BZ + 1.0))
survivor_f4 = Entity(model='sphere', color=color.red, scale=0.65, texture=W,
                     position=Vec3(BX + 1.5, surv_y(4), BZ - 1.0))
drone = Entity(model='cube', color=color.cyan, scale=0.6, texture=W,
               position=DRONE_START)

# ─────────────────────────────────────────────────────────────────────────────
#  CAMERA — EditorCamera with a drone-eye starting angle
#
#  EditorCamera gives you out-of-the-box:
#    right-click drag → orbit/tilt
#    scroll wheel     → zoom
#    middle drag      → pan
#
#  We then set the initial rotation and zoom so it opens at a natural
#  drone-eye view (looking down at ~50°) instead of the default flat angle.
# ─────────────────────────────────────────────────────────────────────────────

ec = EditorCamera()
ec.rotation_x = 50     # tilt down ~50° (drone view; 90 = straight down)
ec.rotation_y = 30     # initial compass bearing
camera.z      = -55    # distance from pivot — controls zoom level

# ─────────────────────────────────────────────────────────────────────────────
#  MISSION EXECUTOR  ◄── replace spacebar trigger with API / MCP / LLM call
# ─────────────────────────────────────────────────────────────────────────────

def execute_mission():
    """
    Dispatch drone on a two-target SAR flight.
    External trigger:  invoke(execute_mission, delay=0)
    """
    print("[DRONE] Mission dispatched.")

    leg1 = Vec3(survivor_f2.x, survivor_f2.y, survivor_f2.z - 1.5)
    drone.animate_position(leg1, duration=T_FLY_F2, curve=curve.in_out_quad)
    invoke(drone.animate_color, color.green, duration=0.3, delay=T_FLY_F2)
    print("[DRONE] Floor 2 — survivor confirmed.")

    t2 = T_FLY_F2 + T_PAUSE
    invoke(drone.animate_color, color.cyan, duration=0.3, delay=t2 - 0.3)

    leg2 = Vec3(survivor_f4.x, survivor_f4.y, survivor_f4.z - 1.5)
    invoke(drone.animate_position, leg2,
           duration=T_FLY_F4, curve=curve.in_out_quad, delay=t2)
    invoke(drone.animate_color, color.green, duration=0.3, delay=t2 + T_FLY_F4)
    print("[DRONE] Floor 4 — survivor confirmed. Mission complete.")


def input(key):
    # ← swap this for invoke(execute_mission, delay=0) from your API/MCP
    if key == 'space':
        execute_mission()


print("Right-click+drag: orbit | Scroll: zoom | Middle-drag: pan | SPACE: dispatch")
app.run()
