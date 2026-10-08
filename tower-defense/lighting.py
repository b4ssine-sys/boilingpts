"""Darkness overlay and light glows.

Built from the M3 spike (spikes/LIGHTING_SPIKE.md): the darkness layer is drawn
at half resolution, steady lights are punched into a cached layer once, only
moving lights are punched per frame, and gradient sprites are cached per radius
bucket. Cost is about 3 ms per frame and nearly flat in the number of lights.

Presentation only. The rules for what the defence can see live in sim.py; the
renderer feeds this module the same circles so the picture and the rules agree.
"""
import math
from collections import namedtuple

import pygame

import palette as P

BUCKET = 8            # radii round to this many pixels so the sprite cache stays small
TRANSITION_TAU = 1.0  # seconds; a tint change is ~95% done after three of these
MIN_ALPHA = 2         # below this the overlay is skipped entirely (daylight)
SIGHT_STRENGTH = 0.6  # tower and base sight pools leave a little dusk; flares clear it fully
GLOW_LEVELS = (0.25, 0.5, 1.0)  # faint at dusk and dawn, full at night

# strength: 1 clears the darkness fully, less leaves some. glow: add the amber
# bloom. steady: never moves or flickers, so it can live in the cached layer.
Light = namedtuple("Light", "x y radius strength glow steady")


RAY_BUCKET = 24       # shaft sprites are costly to build, so their radii step in coarser buckets
RAY_LEVELS = (0.45, 0.75, 1.0)
RAY_COUNT = 6


class GradientCache:
    """Radial falloff sprites, built once per bucket and never per frame."""

    def __init__(self):
        self._punch = {}
        self._glow = {}
        self._rays = {}
        self._fall = {}

    @staticmethod
    def _falloff(d):
        t = max(0.0, 1.0 - d)
        return t * t * (3 - 2 * t)  # smoothstep

    def _small(self, fn):
        n = 32
        s = pygame.Surface((n, n), pygame.SRCALPHA)
        for y in range(n):
            for x in range(n):
                d = math.hypot(x - (n - 1) / 2, y - (n - 1) / 2) / (n / 2)
                s.set_at((x, y), fn(self._falloff(d)))
        return s

    def punch(self, radius, strength=1.0, scale=1.0):
        """Alpha-only sprite. Subtracting it from the darkness lets light through."""
        r = max(BUCKET, round(radius * scale / BUCKET) * BUCKET)
        q = round(strength * 10)
        key = (r, q)
        if key not in self._punch:
            k = q / 10
            small = self._small(lambda f: (0, 0, 0, int(255 * f * k)))
            self._punch[key] = pygame.transform.smoothscale(small, (r * 2, r * 2))
        return self._punch[key]

    def glow(self, radius, level=1.0):
        """Warm amber wash: a plain per-pixel alpha blend, so it tints but never
        blows out. Strength comes in a few fixed levels because blending with a
        surface alpha as well is several times slower."""
        r = max(BUCKET, round(radius / BUCKET) * BUCKET)
        key = (r, level)
        if key not in self._glow:
            if level == 1.0:
                amber = P.color("amber")
                small = self._small(lambda f: (*amber, int(255 * f * f * 0.40)))
                self._glow[key] = pygame.transform.smoothscale(small, (r * 2, r * 2)).convert_alpha()
            else:  # dimmer levels are the full one with its alpha scaled down
                dim = self.glow(r, 1.0).copy()
                dim.fill((255, 255, 255, int(255 * level)), special_flags=pygame.BLEND_RGBA_MULT)
                self._glow[key] = dim
        return self._glow[key]


    def rays(self, radius, phase, level):
        """Additive light shafts fanning out from a lamp, faded toward their tips.
        Two phases are offset by half a ray so alternating them makes the beams shimmer.
        Dimmer levels are the brightest one scaled down, which is far cheaper to build."""
        r = max(RAY_BUCKET, round(radius / RAY_BUCKET) * RAY_BUCKET)
        key = (r, phase, level)
        if key not in self._rays:
            if level == len(RAY_LEVELS) - 1:
                if r not in self._fall:
                    fall = self._small(lambda f: (int(255 * f),) * 3 + (255,))
                    self._fall[r] = pygame.transform.smoothscale(fall, (r * 2, r * 2)).convert()
                # Drawn at half size and scaled up: the blur turns hard-edged wedges into soft beams.
                half_r = r // 2
                small = pygame.Surface((half_r * 2, half_r * 2))
                dim = P.shade("amber", 0.24)
                for i in range(RAY_COUNT):
                    a = math.tau * (i + 0.5 * phase) / RAY_COUNT + 0.3
                    half = 0.11 + 0.035 * ((i * 5) % 3)
                    pts = [(half_r, half_r), (half_r + math.cos(a - half) * half_r, half_r + math.sin(a - half) * half_r),
                           (half_r + math.cos(a + half) * half_r, half_r + math.sin(a + half) * half_r)]
                    pygame.draw.polygon(small, dim, pts)
                surf = pygame.transform.smoothscale(small, (r * 2, r * 2))
                surf = pygame.transform.smoothscale(pygame.transform.smoothscale(surf, (r // 2, r // 2)), (r * 2, r * 2))
                surf.blit(self._fall[r], (0, 0), special_flags=pygame.BLEND_RGB_MULT)
                self._rays[key] = surf
            else:
                surf = self.rays(r, phase, len(RAY_LEVELS) - 1).copy()
                v = int(255 * RAY_LEVELS[level])
                surf.fill((v, v, v), special_flags=pygame.BLEND_RGB_MULT)
                self._rays[key] = surf
        return self._rays[key]


class Lighting:
    def __init__(self, size, scale=0.5):
        """size: pixel size of the map area the overlay covers. scale 0.5 is the
        default; 0.25 is the fallback if a target machine misses 60 FPS."""
        self.size = size
        self.scale = scale
        self.w, self.h = max(1, int(size[0] * scale)), max(1, int(size[1] * scale))
        self.cache = GradientCache()
        self._out = pygame.Surface(size, pygame.SRCALPHA)
        self._layer = pygame.Surface((self.w, self.h), pygame.SRCALPHA)  # reused, never reallocated
        self._sig = None
        color, alpha = P.TINTS["day"]
        self.rgb = tuple(float(c) for c in P.color(color))
        self.alpha = float(alpha)
        self._target = (self.rgb, self.alpha)
        self.sight_scale = 1.0       # smoothed radius multiplier the renderer applies
        self._sight_target = 1.0

    def prewarm(self, sight_max=240, light_max=380):
        """Build every gradient sprite a session can ask for, at load time.
        Radii sweep through many buckets during a tint transition, and creating
        sprites mid-frame causes visible hitches. Steady sight pools use
        strength SIGHT_STRENGTH and stay small; flares and flashes use 1.0 and go larger."""
        for r in range(BUCKET, int(light_max) + BUCKET, BUCKET):
            self.cache.punch(r, 1.0, self.scale)
            if r <= sight_max:
                self.cache.punch(r, SIGHT_STRENGTH, self.scale)
            for level in GLOW_LEVELS:
                self.cache.glow(r, level)
        for r in range(6 * RAY_BUCKET, int(light_max) + RAY_BUCKET, RAY_BUCKET):   # flares only reach 150 and up
            for phase in (0, 1):
                for level in range(len(RAY_LEVELS)):
                    self.cache.rays(r, phase, level)

    # ---- time of day ----
    def set_time_of_day(self, tod, sight_scale):
        """sight_scale 0 means unlimited (daylight); the picture then keeps scale 1."""
        color, alpha = P.TINTS[tod]
        self._target = (tuple(float(c) for c in P.color(color)), float(alpha))
        self._sight_target = sight_scale or 1.0

    def update(self, dt):
        k = 1 - math.exp(-dt / TRANSITION_TAU)
        rgb, alpha = self._target
        self.rgb = tuple(c + (t - c) * k for c, t in zip(self.rgb, rgb))
        self.alpha += (alpha - self.alpha) * k
        self.sight_scale += (self._sight_target - self.sight_scale) * k

    @property
    def active(self):
        return self.alpha >= MIN_ALPHA

    # ---- drawing ----
    def _tint(self):
        # Quantised so the cached layer is not rebuilt for sub-pixel changes.
        return (*(int(round(c)) for c in self.rgb), int(round(self.alpha / 2) * 2))

    def _punch(self, surf, lights, origin_y):
        s = self.scale
        for lt in lights:
            spr = self.cache.punch(lt.radius, lt.strength, s)
            surf.blit(spr, (lt.x * s - spr.get_width() / 2, (lt.y - origin_y) * s - spr.get_height() / 2),
                      special_flags=pygame.BLEND_RGBA_SUB)

    def render(self, screen, lights, origin_y):
        """Draw darkness and glows over the map area. lights use screen coordinates."""
        if not self.active:
            return
        tint = self._tint()
        steady = [l for l in lights if l.steady]
        moving = [l for l in lights if not l.steady]
        sig = (tint, tuple((round(l.x), round(l.y), round(l.radius), l.strength) for l in steady))
        if sig != self._sig:  # tower built or lost, or the tint moved: rebuild the cached layer
            self._layer.fill(tint)
            self._punch(self._layer, steady, origin_y)
            self._sig = sig
        dark = self._layer.copy()
        self._punch(dark, moving, origin_y)
        pygame.transform.smoothscale(dark, self.size, self._out)
        screen.blit(self._out, (0, origin_y))
        gain = (self.alpha - 40) / 138
        level = next((lv for lv in GLOW_LEVELS if gain <= lv + 0.12), GLOW_LEVELS[-1]) if gain > 0.1 else 0
        if level:
            for lt in lights:
                if lt.glow:
                    g = self.cache.glow(lt.radius, level)
                    screen.blit(g, (lt.x - g.get_width() / 2, lt.y - g.get_height() / 2))

    def render_shafts(self, screen, shafts, time):
        """Volumetric light shafts, drawn additively after the darkness so they glow.
        shafts: [(x, y, radius)] for each lamp. Faint at dusk and dawn, full at night."""
        gain = (self.alpha - 40) / 138
        if gain <= 0.1:
            return
        base = 2 if gain > 0.75 else 1 if gain > 0.35 else 0
        for i, (x, y, radius) in enumerate(shafts):
            flick = math.sin(time * 6.0 + i * 1.7) + 0.6 * math.sin(time * 15.0 + i)
            level = max(0, min(len(RAY_LEVELS) - 1, base + (1 if flick > 1.0 else 0) - (1 if flick < -1.0 else 0)))
            phase = int(time * 2.2 + i) % 2
            spr = self.cache.rays(radius, phase, level)
            screen.blit(spr, (x - spr.get_width() / 2, y - spr.get_height() / 2), special_flags=pygame.BLEND_RGB_ADD)
