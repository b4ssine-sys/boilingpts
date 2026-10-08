"""Procedural sprite painter. Draws every unit and structure from code so the
game has real art before the concept artist delivers; drop a PNG named after
the key into assets/sprites/ and it replaces the drawing (see assets.py).

Conventions
  * Sprites face east (angle 0) and stand on a ground point given by ANCHOR.
  * Towers are two layers: a static BASE (sandbags, crates) and a rotating GUN
    drawn at the base's mount point, so the sandbags never spin.
  * Everything is drawn at SS times its final size and smoothscaled down for
    clean edges, with a dark outline for a hand-inked look.
  * Enemies are human figures: faceless, in muted field gear, one silhouette per
    type. They get exactly the same treatment as every other unit. See
    ASSETS.md; this is a content rule, not a style choice.
"""
import math
import random

import pygame

import palette as P

SS = 3  # supersampling factor

# Ground contact point of each sprite as a fraction of its canvas.
ANCHOR = {"tower": (0.5, 0.64), "enemy": (0.5, 0.84)}
# Where the rotating gun sits relative to the ground point, in final pixels.
MOUNT = {"mg_nest": (0, -7), "mortar": (0, -2)}
GUN_TIP = {"mg_nest": 24, "mortar": 17}   # distance from mount to muzzle, final pixels


def _c(c):
    return P.color(c) if isinstance(c, str) else c


class Pen:
    """Draws in final-pixel coordinates onto a supersampled canvas."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.s = pygame.Surface((w * SS, h * SS), pygame.SRCALPHA)
        self.under = pygame.Surface((w * SS, h * SS), pygame.SRCALPHA)

    def _p(self, pt):
        return pt[0] * SS, pt[1] * SS

    def poly(self, pts, color):
        pygame.draw.polygon(self.s, _c(color), [self._p(p) for p in pts])

    def line(self, a, b, color, width=1.0):
        pygame.draw.line(self.s, _c(color), self._p(a), self._p(b), max(1, round(width * SS)))

    def lines(self, pts, color, width=1.0):
        pygame.draw.lines(self.s, _c(color), False, [self._p(p) for p in pts], max(1, round(width * SS)))

    def circle(self, cx, cy, r, color, width=0):
        pygame.draw.circle(self.s, _c(color), self._p((cx, cy)), max(1, r * SS), round(width * SS))

    def ellipse(self, cx, cy, rx, ry, color, width=0):
        r = pygame.Rect(0, 0, rx * 2 * SS, ry * 2 * SS)
        r.center = self._p((cx, cy))
        pygame.draw.ellipse(self.s, _c(color), r, round(width * SS))

    def rect(self, x, y, w, h, color, radius=0, width=0):
        pygame.draw.rect(self.s, _c(color), (x * SS, y * SS, w * SS, h * SS), round(width * SS),
                         border_radius=round(radius * SS))

    def shadow(self, cx, cy, rx, ry, alpha=90):
        r = pygame.Rect(0, 0, rx * 2 * SS, ry * 2 * SS)
        r.center = self._p((cx, cy))
        pygame.draw.ellipse(self.under, (*P.color("ink"), alpha), r)

    def done(self, outline=1.4, outline_color="ink"):
        """Outline the drawn shapes, add the ground shadow beneath, scale down."""
        out = pygame.Surface(self.s.get_size(), pygame.SRCALPHA)
        out.blit(self.under, (0, 0))
        if outline:
            mask = pygame.mask.from_surface(self.s, 20)
            ink = mask.to_surface(setcolor=(*_c(outline_color), 255), unsetcolor=(0, 0, 0, 0))
            k = max(1, round(outline * SS))
            for dx in range(-k, k + 1):
                for dy in range(-k, k + 1):
                    if dx * dx + dy * dy <= k * k + 1:
                        out.blit(ink, (dx, dy))
        out.blit(self.s, (0, 0))
        return pygame.transform.smoothscale(out, (self.w, self.h))


def _bag(pen, x, y, w, h, tone=1.0, rng=None):
    """One sandbag: a stuffed rounded lozenge with a lit top and a seam."""
    base = P.shade("sandbag", tone)
    pen.rect(x, y, w, h, base, radius=h * 0.45)
    pen.rect(x + 1, y + 0.6, w - 2, h * 0.38, P.shade("sandbag", tone * 1.18), radius=h * 0.3)
    pen.line((x + w * 0.5, y + h * 0.2), (x + w * 0.5, y + h * 0.8), P.shade("sandbag", tone * 0.72), 0.6)
    pen.line((x + 1.5, y + h - 0.8), (x + w - 1.5, y + h - 0.8), P.shade("sandbag", tone * 0.7), 0.8)


def _crate(pen, x, y, w, h, lid="olive_drab"):
    pen.rect(x, y + h * 0.3, w, h * 0.7, P.shade(lid, 0.72))
    pen.rect(x, y, w, h * 0.38, P.shade(lid, 1.15))
    pen.line((x + 1, y + h * 0.66), (x + w - 1, y + h * 0.66), P.shade(lid, 0.5), 0.7)
    pen.rect(x + w * 0.2, y + h * 0.46, w * 0.34, h * 0.14, P.shade("khaki", 0.9))   # stencil


# ---------------------------------------------------------------- towers
def tower_base_mg_nest(layer="back"):
    """Back half of the ring, floor and crates; layer="front" is the low front wall,
    drawn over the gun so the gun sits inside the sandbags."""
    w = h = 60
    pen = Pen(w, h)
    gx, gy = w * ANCHOR["tower"][0], h * ANCHOR["tower"][1]
    rng = random.Random(3)
    if layer == "back":
        pen.shadow(gx, gy + 6, 25, 9)
        for i in range(6):
            a = math.pi * (1.12 + i * 0.15)
            _bag(pen, gx + math.cos(a) * 17 - 5, gy - 3 + math.sin(a) * 8 - 3, 10, 6.2, 0.82 + rng.random() * 0.1)
        pen.ellipse(gx, gy - 1, 14, 6.5, P.shade("mud_dark", 0.8))          # trampled floor inside
        _crate(pen, gx + 15, gy - 5, 11, 9)
        _crate(pen, gx + 17, gy - 12, 9, 8, "olive_drab")
        return pen.done()
    for i in range(7):                                                 # front row, low curve
        a = math.pi * (0.04 + i * 0.152)
        _bag(pen, gx + math.cos(a) * 20 - 5.5, gy + 3 + math.sin(a) * 8.5, 11, 6.6, 0.95 + rng.random() * 0.12)
    for i in range(5):                                                 # second, stacked row
        a = math.pi * (0.11 + i * 0.195)
        _bag(pen, gx + math.cos(a) * 15 - 5, gy - 1.5 + math.sin(a) * 7, 10, 6, 1.08 + rng.random() * 0.1)
    return pen.done()


def tower_gun_mg_nest():
    """Twin-barrel pintle gun with a shield, pointing east around its own centre."""
    w = h = 44
    pen = Pen(w, h)
    cx = cy = 22
    steel, dark = "steel", P.shade("steel", 0.6)
    pen.rect(cx - 4, cy + 3, 6, 5, "wood_dark", radius=1)                 # ammo box
    pen.rect(cx - 6, cy - 5, 14, 9, steel, radius=2)                      # receiver
    pen.rect(cx - 5, cy - 4.4, 12, 3, P.shade(steel, 1.5), radius=1.2)
    for off in (-2.6, 2.6):                                               # twin barrels
        pen.rect(cx + 6, cy + off - 1.1, 17, 2.6, dark, radius=1)
        pen.rect(cx + 6, cy + off - 1.1, 17, 1.0, P.shade(steel, 1.7), radius=0.6)
        pen.rect(cx + 21, cy + off - 1.7, 3.4, 3.6, P.shade(steel, 0.45), radius=0.8)   # muzzle brake
        for k in range(3):
            pen.line((cx + 9 + k * 3.5, cy + off - 1.1), (cx + 9 + k * 3.5, cy + off + 1.5), P.shade(steel, 0.4), 0.6)
    pen.rect(cx + 3, cy - 8.5, 3.2, 17, P.shade(steel, 0.8), radius=1)    # gun shield plate
    pen.rect(cx + 3.4, cy - 8, 1.2, 16, P.shade(steel, 1.6))
    pen.rect(cx - 10, cy - 3, 5, 2, P.shade(steel, 0.7))                  # grips
    pen.rect(cx - 10, cy + 1, 5, 2, P.shade(steel, 0.7))
    return pen.done(1.1)


def tower_base_mortar(layer="back"):
    """The pit, back half of the rim, shells and crate; layer="front" is the near rim."""
    w = h = 60
    pen = Pen(w, h)
    gx, gy = w * ANCHOR["tower"][0], h * ANCHOR["tower"][1]
    rng = random.Random(5)
    if layer == "back":
        pen.shadow(gx, gy + 6, 26, 9)
        pen.ellipse(gx, gy, 24, 11.5, "mud_dark")                        # the pit
        pen.ellipse(gx, gy - 0.5, 20, 9, P.shade("mud_dark", 0.6))
        pen.ellipse(gx, gy + 0.5, 12, 5.5, P.shade("mud_dark", 0.4))
    for i in range(10):                                                  # rim of sandbags
        a = math.tau * i / 10 + 0.2
        tone = 0.78 if math.sin(a) < 0 else 1.0
        bag_tone = tone + rng.random() * 0.1                             # drawn for both layers to keep the rng in step
        if (math.sin(a) < 0) == (layer == "back"):
            _bag(pen, gx + math.cos(a) * 23 - 5, gy + math.sin(a) * 11 - 3, 10, 6, bag_tone)
    if layer == "back":
        for i in range(4):                                               # stacked shells, left
            pen.rect(gx - 29 + i * 3.2, gy + 1, 3, 9, P.shade("steel", 0.8), radius=1.2)
            pen.rect(gx - 29 + i * 3.2, gy + 1, 3, 2.6, "khaki", radius=1)
        _crate(pen, gx + 19, gy + 1, 11, 9)
    return pen.done()


def tower_gun_mortar():
    w = h = 44
    pen = Pen(w, h)
    cx = cy = 22
    pen.ellipse(cx - 5, cy + 1, 7.5, 4.2, P.shade("steel", 0.55))         # base plate
    pen.rect(cx - 6, cy - 3.2, 22, 6.4, "steel", radius=3)                # tube
    pen.rect(cx - 5, cy - 2.6, 20, 2.2, P.shade("steel", 1.6), radius=1.1)
    pen.rect(cx + 12.5, cy - 3.8, 4.6, 7.6, P.shade("steel", 0.5), radius=1.4)   # muzzle collar
    pen.ellipse(cx + 17, cy, 1.5, 2.8, P.shade("steel", 0.25))                   # bore
    pen.line((cx + 4, cy + 2), (cx - 1, cy + 8), P.shade("steel", 0.7), 1.6)      # bipod
    pen.line((cx + 4, cy - 2), (cx - 1, cy - 8), P.shade("steel", 0.7), 1.6)
    pen.rect(cx + 3, cy - 4.4, 3, 2.2, "khaki", radius=0.8)                       # elevation band
    return pen.done(1.1)


def tower_base_claymore():
    w = h = 60
    pen = Pen(w, h)
    gx, gy = w * ANCHOR["tower"][0], h * ANCHOR["tower"][1]
    pen.shadow(gx, gy + 5, 17, 5.5, 80)
    for dx in (-7.5, 7.5):                                               # folded scissor legs
        pen.line((gx + dx, gy - 4), (gx + dx * 1.7, gy + 6), "steel", 1.6)
    # the curved olive-drab body: lit top plate, darker face, rim and a tiny fuse well
    pen.poly([(gx - 14, gy - 12), (gx + 14, gy - 12), (gx + 12, gy - 1), (gx - 12, gy - 1)], P.shade("olive_drab", 0.7))
    pen.poly([(gx - 14, gy - 12), (gx + 14, gy - 12), (gx + 13, gy - 8), (gx - 13, gy - 8)], P.shade("olive_drab", 1.25))
    pen.lines([(gx - 12, gy - 6), (gx - 6, gy - 5), (gx, gy - 4.4), (gx + 6, gy - 5), (gx + 12, gy - 6)],
              P.shade("olive_drab", 0.45), 0.9)
    pen.rect(gx - 5, gy - 9.6, 10, 3.6, "khaki", radius=0.8)             # stencilled panel
    pen.line((gx - 3, gy - 7.8), (gx + 3, gy - 7.8), P.shade("ink", 1.0), 0.6)
    pen.circle(gx + 9, gy - 13.2, 1.5, "clay")                           # detonator cap
    pen.lines([(gx + 9, gy - 13.5), (gx + 15, gy - 17), (gx + 21, gy - 14)], "ink", 0.7)   # trip wire
    return pen.done(1.2)


def tower_base_flare():
    w = h = 60
    pen = Pen(w, h)
    gx, gy = w * ANCHOR["tower"][0], h * ANCHOR["tower"][1]
    pen.shadow(gx + 4, gy + 5, 18, 6)
    wood, dark = "wood", "wood_dark"
    top = gy - 21
    for dx in (-9, 9):                                                   # four legs, two shown front/back
        pen.line((gx + dx, gy + 4), (gx + dx * 0.55, top + 6), dark, 2.2)
        pen.line((gx + dx * 0.8, gy - 1), (gx + dx * 0.45, top + 8), wood, 1.0)
    pen.line((gx - 9, gy + 4), (gx + 5, top + 14), dark, 1.3)            # cross braces
    pen.line((gx + 9, gy + 4), (gx - 5, top + 14), dark, 1.3)
    pen.line((gx - 7, gy - 8), (gx + 7, gy - 8), dark, 1.5)
    for i in range(5):                                                   # ladder rungs
        pen.line((gx - 2, gy + 2 - i * 5.5), (gx + 2, gy + 2 - i * 5.5), wood, 1.0)
    pen.rect(gx - 9, top + 2, 18, 5.5, wood, radius=1)                   # platform
    pen.rect(gx - 9, top + 2, 18, 1.8, P.shade(wood, 1.3), radius=1)
    pen.rect(gx - 8, top - 5, 2, 8, dark)                                # rail posts
    pen.rect(gx + 6, top - 5, 2, 8, dark)
    pen.line((gx - 8, top - 4), (gx + 8, top - 4), dark, 1.0)
    pen.rect(gx - 4, top - 11, 8, 8, "steel", radius=1.5)                # flare launcher drum
    pen.rect(gx - 3, top - 10, 6, 2, P.shade("steel", 1.6))
    pen.circle(gx, top - 12, 4.2, "amber")                               # the lamp
    pen.circle(gx, top - 12, 2.3, "amber_hot")
    return pen.done()


def blank(w=2, h=2):
    return pygame.Surface((w, h), pygame.SRCALPHA)


BASE_BUILDERS = {
    "mg_nest": tower_base_mg_nest, "mortar": tower_base_mortar,
    "claymore": tower_base_claymore, "flare": tower_base_flare,
}
GUN_BUILDERS = {"mg_nest": tower_gun_mg_nest, "mortar": tower_gun_mortar}
# Towers whose near wall is drawn after the gun.
FRONT_BUILDERS = {"mg_nest": lambda: tower_base_mg_nest("front"), "mortar": lambda: tower_base_mortar("front")}


# --------------------------------------------------------------- enemies
# Human figures in muted field gear. Faceless on purpose: no features that
# could read as a caricature, and the same inked, shaded treatment as every
# other unit. Each type has its own silhouette; each has two walk frames.
def _legs(pen, gx, gy, frame, stride, color, boot="ink"):
    a = stride if frame == 0 else -stride
    for side, off in ((-1, a), (1, -a)):
        hip = (gx + side * 1.8, gy - 8.5)
        foot = (gx + side * 2.4 + off, gy - 0.5 - (1.2 if side * off > 0 else 0))
        pen.line(hip, foot, color, 3.0)
        pen.rect(foot[0] - 2, foot[1] - 1, 4.6, 2.4, boot, radius=1)


def _head(pen, x, y, hat, hat_tone=1.0):
    pen.circle(x, y, 3.3, "skin")
    pen.ellipse(x, y - 1.6, 5.2, 2.8, P.shade(hat, hat_tone))            # soft bush hat brim
    pen.rect(x - 3.1, y - 4.9, 6.2, 3.7, P.shade(hat, hat_tone * 1.12), radius=1.6)


def enemy_infantry(frame):
    w = h = 48
    pen = Pen(w, h)
    gx, gy = w * ANCHOR["enemy"][0], h * ANCHOR["enemy"][1]
    pen.shadow(gx, gy + 1, 10, 3.2)
    bob = 0.7 if frame == 0 else 0
    _legs(pen, gx, gy, frame, 2.8, P.shade("cloth_green", 1.25))
    pen.rect(gx - 8.2, gy - 21 - bob, 5.6, 10, P.shade("cloth_brown", 1.1), radius=1.4)  # field pack
    pen.rect(gx - 8.2, gy - 21 - bob, 5.6, 3, P.shade("cloth_brown", 1.5), radius=1.2)
    pen.poly([(gx - 4, gy - 21 - bob), (gx + 4.4, gy - 21 - bob), (gx + 4, gy - 8.5), (gx - 3.6, gy - 8.5)], "cloth_green")
    pen.poly([(gx - 4, gy - 21 - bob), (gx + 4.4, gy - 21 - bob), (gx + 3.8, gy - 17), (gx - 3.8, gy - 17)],
             P.shade("cloth_green", 1.3))
    pen.rect(gx - 4, gy - 11.5, 8.2, 1.7, P.shade("cloth_brown", 0.7))   # belt
    _head(pen, gx + 0.6, gy - 25 - bob, "olive_drab", 1.2)
    pen.line((gx - 1, gy - 15), (gx + 9.5, gy - 17.5), "skin", 2.0)      # arm out to the rifle
    pen.line((gx - 5, gy - 14), (gx + 20, gy - 21.5), "wood_dark", 2.1)  # rifle: stock to muzzle
    pen.line((gx + 6, gy - 18.7), (gx + 20, gy - 22.5), P.shade("steel", 0.7), 1.3)
    return pen.done()


def enemy_scout(frame):
    w = h = 48
    pen = Pen(w, h)
    gx, gy = w * ANCHOR["enemy"][0], h * ANCHOR["enemy"][1]
    pen.shadow(gx, gy + 1, 10, 3, 80)
    bob = 1.0 if frame == 0 else -0.2
    _legs(pen, gx, gy, frame, 4.6, "cloth_brown")                        # long running stride
    lean = 2.4
    pen.poly([(gx - 2.6 + lean, gy - 21 - bob), (gx + 3 + lean, gy - 21 - bob), (gx + 2.4, gy - 8.5), (gx - 2.4, gy - 8.5)],
             "khaki")
    pen.poly([(gx - 2.6 + lean, gy - 21 - bob), (gx + 3 + lean, gy - 21 - bob), (gx + 3 + lean * 0.8, gy - 18), (gx - 2.4 + lean, gy - 18)],
             P.shade("khaki", 1.2))
    pen.line((gx + lean * 0.8, gy - 21.5 - bob), (gx - 3.5, gy - 12), "clay", 1.8)   # cloth sash
    pen.circle(gx + 0.6 + lean, gy - 24.4 - bob, 3.0, "skin")
    pen.rect(gx - 2.6 + lean, gy - 28.4 - bob, 6.4, 3.4, P.shade("cloth_brown", 1.05), radius=1.6)   # cap
    pen.line((gx + lean, gy - 18), (gx - 6, gy - 15.5 + (1 if frame else -1)), "skin", 1.8)           # arms pumping
    pen.line((gx + lean, gy - 18), (gx + 7, gy - 14.5 - (1 if frame else -1)), "skin", 1.8)
    pen.line((gx - 2, gy - 10), (gx + 6.5, gy - 21), "wood_dark", 1.6)   # carbine slung across the back
    return pen.done()


def enemy_sapper(frame):
    w = h = 48
    pen = Pen(w, h)
    gx, gy = w * ANCHOR["enemy"][0], h * ANCHOR["enemy"][1]
    pen.shadow(gx, gy + 1, 11, 3.4)
    bob = 0.5 if frame == 0 else 0
    _legs(pen, gx, gy + 0.8, frame, 2.2, P.shade("cloth_green", 0.8))
    pen.poly([(gx - 4.5, gy - 18 - bob), (gx + 5, gy - 18 - bob), (gx + 4, gy - 7.5), (gx - 3.6, gy - 7.5)],
             P.shade("cloth_green", 0.85))                                # crouched, shorter torso
    pen.poly([(gx - 4.5, gy - 18 - bob), (gx + 5, gy - 18 - bob), (gx + 4.6, gy - 15), (gx - 4.2, gy - 15)],
             P.shade("cloth_green", 1.15))
    pen.rect(gx - 12.5, gy - 22 - bob, 9.5, 12.5, "clay", radius=2.4)    # satchel charge on the back
    pen.rect(gx - 12.5, gy - 22 - bob, 9.5, 3.6, P.shade("clay", 1.3), radius=2)
    pen.line((gx - 11, gy - 17), (gx - 4, gy - 17), P.shade("clay", 0.55), 0.9)
    pen.line((gx - 3, gy - 23), (gx + 3, gy - 18), "wood_dark", 1.3)     # strap
    pen.line((gx - 9, gy - 22.5 - bob), (gx - 13, gy - 26), "khaki", 0.9)   # fuse
    pen.circle(gx - 13.2, gy - 26.4, 1.0, "amber")
    _head(pen, gx + 1.2, gy - 21.5 - bob, "cloth_green", 0.9)
    pen.line((gx + 1, gy - 14), (gx + 8.5, gy - 12 + (0.5 if frame else -0.5)), "skin", 2.0)   # carrying a coil
    pen.circle(gx + 10.5, gy - 11.5, 2.8, "steel", 1.0)
    return pen.done()


ENEMY_BUILDERS = {"scout": enemy_scout, "infantry": enemy_infantry, "sapper": enemy_sapper}


# -------------------------------------------------------------- foliage
# Variants are generated once and reused with flips, so a dense jungle costs a
# handful of drawings, not hundreds.
LEAF = ("jungle_dark", "jungle_mid", "jungle_light", "leaf_bright")


def _leaf_tone(rng, lift=0.0):
    i = min(3, max(0, int(rng.random() * 3 + lift)))
    return P.shade(LEAF[i], 0.78 + rng.random() * 0.25)


def foliage_tree(seed):
    """A broad canopy seen from above and a little to the side."""
    rng = random.Random(seed)
    w, h = 92, 84
    pen = Pen(w, h)
    cx, cy = w / 2, h * 0.52
    pen.shadow(cx + 4, cy + 22, 36, 11, 70)
    blobs = [(cx + rng.uniform(-22, 22), cy + rng.uniform(-14, 12), rng.uniform(13, 21)) for _ in range(9)]
    for bx, by, br in blobs:                                          # deep underside
        pen.circle(bx + 2, by + 4, br, "leaf_deep")
    for bx, by, br in blobs:                                          # body
        pen.circle(bx, by, br * 0.95, _leaf_tone(rng))
    for bx, by, br in blobs:                                          # lit crowns, up and to the left
        pen.circle(bx - br * 0.2, by - br * 0.28, br * 0.62, _leaf_tone(rng, 0.8))
    for _ in range(46):                                               # leaf strokes and wet glints
        a, d = rng.uniform(0, math.tau), rng.uniform(0, 30)
        x, y = cx + math.cos(a) * d, cy + math.sin(a) * d * 0.7 - 3
        pen.line((x, y), (x + rng.uniform(-3, 3), y - rng.uniform(2, 5)), _leaf_tone(rng, 1.1), 1.0)
    for _ in range(9):
        pen.circle(cx + rng.uniform(-24, 18), cy + rng.uniform(-22, 6), 0.9, "rain")
    return pen.done(1.3, "leaf_deep")


def _frond(pen, rng, ox, oy, ang, length, droop, leaflet, tone_lift=0.0):
    pts = []
    for i in range(11):
        t = i / 10
        pts.append((ox + math.cos(ang) * length * t,
                    oy + math.sin(ang) * length * t * 0.62 + droop * t * t))
    pen.lines(pts, P.shade("jungle_dark", 0.9), 1.5)
    for i in range(1, 11):
        x, y = pts[i]
        nx, ny = pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]
        n = math.hypot(nx, ny) or 1
        px, py = -ny / n, nx / n
        size = leaflet * (1 - abs(i - 5) / 8)
        for side in (-1, 1):
            tip = (x + px * side * size + nx / n * 2.2, y + py * side * size + ny / n * 2.2 + size * 0.35)
            pen.line((x, y), tip, _leaf_tone(random.Random(int(x * 7 + y * 3 + side)), 0.9 + tone_lift), 1.6)


def foliage_palm(seed):
    rng = random.Random(seed)
    w, h = 76, 64
    pen = Pen(w, h)
    cx, cy = w / 2, h * 0.62
    pen.shadow(cx, cy + 6, 26, 7, 60)
    n = rng.randint(8, 10)
    for i in range(n):
        ang = math.tau * i / n + rng.uniform(-0.2, 0.2)
        _frond(pen, rng, cx, cy, ang, rng.uniform(22, 32), rng.uniform(6, 14), rng.uniform(5, 8))
    pen.circle(cx, cy, 3.2, "wood_dark")
    return pen.done(1.0, "leaf_deep")


def foliage_fern(seed):
    rng = random.Random(seed)
    w, h = 44, 34
    pen = Pen(w, h)
    cx, cy = w / 2, h * 0.7
    pen.shadow(cx, cy + 3, 15, 4, 50)
    for i in range(7):
        ang = math.pi * (1.1 + i * 0.13) + rng.uniform(-0.1, 0.1) if i % 2 == 0 else math.pi * (0.0 - i * 0.02) - rng.uniform(0, 0.4)
        _frond(pen, rng, cx, cy, ang if i % 2 == 0 else -ang, rng.uniform(12, 18), rng.uniform(3, 8), rng.uniform(3, 4.5), 0.3)
    return pen.done(0.8, "leaf_deep")


def foliage_bush(seed):
    rng = random.Random(seed)
    w, h = 40, 30
    pen = Pen(w, h)
    cx, cy = w / 2, h * 0.62
    pen.shadow(cx + 1, cy + 6, 15, 4.5, 55)
    blobs = [(cx + rng.uniform(-9, 9), cy + rng.uniform(-5, 3), rng.uniform(6, 9)) for _ in range(5)]
    for bx, by, br in blobs:
        pen.circle(bx, by + 1.5, br, "leaf_deep")
    for bx, by, br in blobs:
        pen.circle(bx, by, br * 0.92, _leaf_tone(rng))
        pen.circle(bx - 1.5, by - 2, br * 0.55, _leaf_tone(rng, 0.9))
    return pen.done(1.0, "leaf_deep")


def foliage_tuft(seed):
    rng = random.Random(seed)
    w, h = 20, 16
    pen = Pen(w, h)
    cx, cy = w / 2, h - 3
    for i in range(7):
        a = -math.pi / 2 + (i - 3) * 0.34 + rng.uniform(-0.12, 0.12)
        L = rng.uniform(6, 11)
        pen.line((cx + (i - 3) * 0.7, cy), (cx + math.cos(a) * L, cy + math.sin(a) * L), _leaf_tone(rng, 0.9), 1.2)
    return pen.done(0.5, "leaf_deep")


FOLIAGE = {"tree": foliage_tree, "palm": foliage_palm, "fern": foliage_fern,
           "bush": foliage_bush, "tuft": foliage_tuft}


# ------------------------------------------------------------- firebase
def sandbag_wall(length, vertical=False):
    """Two rows of stacked bags along a line, with a lit top and a dark base."""
    rng = random.Random(length * 7 + (1 if vertical else 0))
    bw, bh = 12, 7.5
    n = max(2, int(length / (bw - 1.5)))
    if not vertical:
        w, h = n * (bw - 1.5) + 8, 22
        pen = Pen(int(w), h)
        pen.shadow(w / 2, h - 5, w / 2 - 3, 4, 70)
        for row, (y, tone, shift) in enumerate(((10.5, 0.88, 0), (4.6, 1.08, 5))):
            for i in range(n):
                _bag(pen, 3 + i * (bw - 1.5) + shift * (row % 2) - 2, y, bw, bh, tone + rng.random() * 0.1)
        return pen.done(1.2)
    w, h = 24, n * (bh - 1.5) + 12
    pen = Pen(w, int(h))
    pen.shadow(w / 2, h - 4, 9, 4, 70)
    for i in range(n):
        for col, (x, tone) in enumerate(((3.5, 0.9), (9, 1.08))):
            _bag(pen, x + (3 if i % 2 else 0) * (col == 1) - 1, 3 + i * (bh - 1.5), bw - 2, bh, tone + rng.random() * 0.1)
    return pen.done(1.2)


def bunker():
    """Concrete command bunker: lit roof slab, shaded front, firing slit, sandbagged top."""
    w, h = 104, 78
    pen = Pen(w, h)
    pen.shadow(w / 2, h - 8, 46, 8, 80)
    pen.poly([(8, 28), (96, 28), (101, 58), (3, 58)], "concrete_dark")                 # front face
    pen.poly([(8, 28), (96, 28), (98, 36), (6, 36)], P.shade("concrete_dark", 1.25))
    pen.poly([(16, 10), (88, 10), (96, 28), (8, 28)], "concrete")                       # roof slab
    pen.poly([(16, 10), (88, 10), (90, 14), (14, 14)], P.shade("concrete", 1.22))
    pen.rect(22, 38, 60, 8, "ink", radius=2)                                           # firing slit
    pen.rect(24, 39, 56, 2.2, P.shade("steel", 0.7))
    pen.rect(46, 47, 12, 11, P.shade("steel", 0.7))                                    # steel door
    pen.rect(48, 49, 8, 8, P.shade("steel", 0.9))
    for i in range(5):                                                                 # sandbags along the roof edge
        _bag(pen, 20 + i * 13, 5, 13, 7.5, 0.95 + 0.05 * (i % 2))
    for x in (12, 86):                                                                 # weathering streaks
        pen.line((x, 30), (x + 1, 56), P.shade("concrete_dark", 0.7), 1.4)
    pen.line((82, 10), (86, -0), "steel", 0.9)                                         # radio whip
    return pen.done(1.4)


def wire_coil(length=46):
    """Concertina razor wire: overlapping loops with sharp barbs and glints."""
    rng = random.Random(length)
    w, h = length + 10, 26
    pen = Pen(w, h)
    pen.shadow(w / 2, h - 4, w / 2 - 4, 3.5, 60)
    steel = P.shade("steel", 1.9)
    n = int(length / 6)
    for i in range(n + 1):
        x = 6 + i * 6
        pen.ellipse(x, 12, 7.2, 8.8, steel, 1.0)
        pen.ellipse(x + 3, 12.4, 6.4, 8.0, P.shade("steel", 1.2), 0.8)
        pen.line((x - 3, 5), (x - 5.2, 2.6), steel, 0.8)                                # barbs
        pen.line((x + 4, 18), (x + 6, 20.6), steel, 0.8)
        if rng.random() < 0.5:
            pen.circle(x + 2, 4.6, 0.8, "rain")
    return pen.done(0.7)


def wire_stake():
    pen = Pen(10, 24)
    pen.shadow(5, 21, 4, 2, 70)
    pen.line((2, 3), (8, 21), "wood_dark", 2.2)
    pen.line((8, 3), (2, 21), "wood", 2.2)
    return pen.done(0.8)


def barrel():
    pen = Pen(16, 20)
    pen.shadow(8, 17, 7, 2.6, 70)
    pen.rect(2, 3, 12, 14, P.shade("olive_drab", 0.8), radius=2.4)
    pen.rect(2.6, 3.4, 4, 13, P.shade("olive_drab", 1.2), radius=1.5)
    for y in (6, 11):
        pen.line((2, y), (14, y), P.shade("olive_drab", 0.5), 0.9)
    pen.ellipse(8, 3.4, 6, 2.2, P.shade("olive_drab", 1.35))
    return pen.done(1.0)


def mud_puddle(seed):
    rng = random.Random(seed)
    w, h = 44, 18
    pen = Pen(w, h)
    pen.ellipse(w / 2, h / 2, 19 + rng.random() * 3, 6.4, "mud_dark")
    pen.ellipse(w / 2 - 1, h / 2 - 0.4, 17, 5.0, P.mix("mud_dark", "rain", 0.35))
    pen.ellipse(w / 2 - 5, h / 2 - 1.6, 7, 1.7, P.mix("mud_dark", "rain", 0.7))
    return pen.done(0, "ink")
