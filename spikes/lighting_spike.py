"""M3/G4 spike: what does the darkness overlay cost, and which build is cheapest?

Standalone. Nothing in the game imports this. Run:
    python spikes/lighting_spike.py            # benchmark table
    python spikes/lighting_spike.py --shot out.png   # also save a lit frame

Each strategy draws the same lights over the same scene and is timed for the
overlay work only (scene drawing is ~1 ms and identical across strategies).

Strategies
  full        darkness surface at screen size, lights punched out with
              BLEND_RGBA_SUB, then one alpha blit onto the screen.
  half        same at 1/2 width and height, smoothscaled up on the way out.
  half_fast   same as half but with a nearest-neighbour scale.
  quarter     same at 1/4 width and height, smoothscaled up.
  *_static    adds a cached layer holding every steady light (tower sight
              pools). Per frame: copy that layer, punch only the moving lights
              (flares, muzzle flashes). Rebuilt when a tower is built or lost.
Every strategy also does the additive amber glow pass (BLEND_RGB_ADD) at full
resolution, because the glow carries the look.
"""
import argparse
import math
import os
import random
import statistics
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pygame

import palette as P
from assets import Assets
from content import CONTENT
from render import HUD_H, Renderer, screen_size
from sim import Game
from strings import Strings

BUCKET = 8  # radii are rounded to this many pixels so the sprite cache stays small


class GradientCache:
    """Radial falloff sprites, built once per radius bucket (never per frame)."""

    def __init__(self):
        self._punch = {}
        self._glow = {}

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

    def punch(self, radius, scale=1.0):
        """Alpha-only sprite: subtracting it lets light through the darkness."""
        r = max(BUCKET, round(radius * scale / BUCKET) * BUCKET)
        if r not in self._punch:
            small = self._small(lambda f: (0, 0, 0, int(255 * f)))
            self._punch[r] = pygame.transform.smoothscale(small, (r * 2, r * 2))
        return self._punch[r]

    def glow(self, radius):
        """Warm additive sprite (RGB only is used)."""
        r = max(BUCKET, round(radius / BUCKET) * BUCKET)
        if r not in self._glow:
            amber = P.color("amber")
            small = self._small(lambda f: tuple(int(c * f * f * 0.30) for c in amber) + (255,))
            self._glow[r] = pygame.transform.smoothscale(small, (r * 2, r * 2)).convert()
        return self._glow[r]


class Overlay:
    def __init__(self, size, mode, tint):
        self.size = size
        self.static = mode.endswith("_static")
        base = mode.replace("_static", "")
        self.mode = base
        self.scale = {"full": 1.0, "half": 0.5, "half_fast": 0.5, "quarter": 0.25}[base]
        self._layer, self._sig = None, None
        self.w, self.h = int(size[0] * self.scale), int(size[1] * self.scale)
        self.dark = pygame.Surface((self.w, self.h), pygame.SRCALPHA)  # convert_alpha'd below
        self.dark = self.dark.convert_alpha()
        self.tint = (*P.color(tint[0]), tint[1])
        self.cache = GradientCache()
        self.phase = (0, 0, 0)
        self.out = pygame.Surface(size, pygame.SRCALPHA).convert_alpha()

    def _punch(self, surf, lights, origin_y):
        s = self.scale
        for x, y, r, strength, _, _ in lights:
            spr = self.cache.punch(r, s)
            if strength < 1.0:
                spr = spr.copy()
                spr.fill((0, 0, 0, int(255 * strength)), special_flags=pygame.BLEND_RGBA_MULT)
            surf.blit(spr, (x * s - spr.get_width() / 2, (y - origin_y) * s - spr.get_height() / 2),
                      special_flags=pygame.BLEND_RGBA_SUB)

    def render(self, screen, lights, origin_y):
        """lights: [(x, y, radius, strength 0-1, glows, steady)] in screen-space of the map area."""
        s = self.scale
        t0 = time.perf_counter()
        if self.static:
            steady = [l for l in lights if l[5]]
            moving = [l for l in lights if not l[5]]
            sig = tuple((round(x), round(y), r) for x, y, r, *_ in steady)
            if sig != self._sig:  # a tower was built or lost: rebuild the cached layer
                self._layer = pygame.Surface((self.w, self.h), pygame.SRCALPHA).convert_alpha()
                self._layer.fill(self.tint)
                self._punch(self._layer, steady, origin_y)
                self._sig = sig
            self.dark = self._layer.copy()
        else:
            moving = lights
            self.dark.fill(self.tint)
        self._punch(self.dark, moving, origin_y)
        t1 = time.perf_counter()
        if s == 1.0:
            layer = self.dark
        elif self.mode == "half_fast":
            layer = pygame.transform.scale(self.dark, self.size, self.out)
        else:
            layer = pygame.transform.smoothscale(self.dark, self.size, self.out)
        screen.blit(layer, (0, origin_y))
        t2 = time.perf_counter()
        for x, y, r, strength, glows, _ in lights:  # warm glow, additive, full resolution
            if glows:
                g = self.cache.glow(r)
                screen.blit(g, (x - g.get_width() / 2, y - g.get_height() / 2),
                            special_flags=pygame.BLEND_RGB_ADD)
        t3 = time.perf_counter()
        self.phase = (t1 - t0, t2 - t1, t3 - t2)


def build_scene():
    pygame.init()
    game = Game(CONTENT, "firebase")
    screen = pygame.display.set_mode(screen_size(game.map))
    renderer = Renderer(Strings.load(), Assets(), game.map)
    return game, screen, renderer


def populate(game, n_towers):
    spots = [(14, 6), (16, 6), (15, 8), (13, 7), (9, 3), (11, 4), (9, 10), (12, 10), (12, 8), (11, 3),
             (16, 8), (13, 6), (7, 10), (16, 5), (12, 4), (17, 8), (17, 6), (8, 4), (6, 7), (11, 11),
             (14, 11), (10, 6), (7, 3), (5, 11), (13, 3)]
    game.supply = 99999
    kinds = ["mg_nest", "flare", "mortar", "mg_nest", "flare"]
    for i, (c, r) in enumerate(spots[:n_towers]):
        game.try_build(c, r, kinds[i % len(kinds)])


def lights_for(game, frame, rng):
    """Flares lit and flickering, towers with a sight pool, muzzle flashes on the bullets."""
    out = []
    for t in game.towers.values():
        x, y = t.x, t.y + HUD_H
        if t.defn.kind == "support":
            flick = 1 + 0.06 * math.sin(frame * 0.35 + t.col) + rng.uniform(-0.03, 0.03)
            out.append((x, y, t.defn.light_radius * flick, 1.0, True, False))
        else:
            out.append((x, y, 105, 0.8, False, True))
    for b in game.bullets:
        out.append((b.x, b.y + HUD_H, 38, 1.0, True, False))
    return out


def bench(mode, n_towers, frames=240):
    game, screen, renderer = build_scene()
    populate(game, n_towers)
    game.wave = 7
    game.start_wave()
    ov = Overlay(screen.get_size(), mode, P.TINTS["dark"])
    rng = random.Random(1)
    times, counts, phases = [], [], []
    for f in range(frames + 60):
        game.update(1 / 60)
        renderer.update(1 / 60, game)
        renderer.draw(screen, game, "mg_nest", (0, 0))
        lights = lights_for(game, f, rng)
        t = time.perf_counter()
        ov.render(screen, lights, HUD_H)
        dt = time.perf_counter() - t
        if f >= 60:  # skip warm-up while caches fill
            times.append(dt * 1000)
            counts.append(len(lights))
            phases.append(ov.phase)
    pygame.quit()
    times.sort()
    ph = [statistics.mean(p[i] for p in phases) * 1000 for i in range(3)]
    return (statistics.mean(times), times[int(len(times) * 0.99)], max(times),
            statistics.mean(counts), len(ov.cache._punch), ph)


def visibility_cost(n_towers, n_enemies=60, reps=200):
    """Cost of the rule 'enemy is visible if any light source reaches it'."""
    rng = random.Random(2)
    srcs = [(rng.uniform(0, 800), rng.uniform(0, 600), rng.choice([105, 170])) for _ in range(n_towers)]
    enemies = [(rng.uniform(0, 800), rng.uniform(0, 600)) for _ in range(n_enemies)]
    t = time.perf_counter()
    for _ in range(reps):
        for ex, ey in enemies:
            any(math.hypot(ex - sx, ey - sy) <= r for sx, sy, r in srcs)
    return (time.perf_counter() - t) / reps * 1000


def save_shot(path, mode="half_static"):
    game, screen, renderer = build_scene()
    populate(game, 14)
    game.wave = 5
    game.start_wave()
    ov = Overlay(screen.get_size(), mode, P.TINTS["dark"])
    rng = random.Random(1)
    for f in range(60 * 14):
        game.update(1 / 60)
        renderer.update(1 / 60, game)
    renderer.draw(screen, game, "mg_nest", (0, 0))
    ov.render(screen, lights_for(game, 840, rng), HUD_H)
    pygame.image.save(screen, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot")
    ap.add_argument("--shot-mode", default="half_static")
    ap.add_argument("--frames", type=int, default=240)
    args = ap.parse_args()
    if args.shot:
        save_shot(args.shot, args.shot_mode)
        print("saved", args.shot)
    print(f"Overlay cost per frame in ms (budget 16.7 for the whole frame). pygame {pygame.version.ver}")
    print(f"{'mode':10s} {'towers':>6s} {'lights':>6s} {'mean':>7s} {'p99':>7s} {'max':>7s}   punch  scale+blit  glow")
    for mode in ("full", "half", "half_fast", "quarter", "half_static", "quarter_static"):
        for n in (6, 14, 25):
            mean, p99, mx, lights, sprites, ph = bench(mode, n, args.frames)
            print(f"{mode:10s} {n:6d} {lights:6.1f} {mean:7.2f} {p99:7.2f} {mx:7.2f}  {ph[0]:6.2f}  {ph[1]:9.2f}  {ph[2]:5.2f}")
    for n in (6, 14, 25):
        print(f"visibility check, {n} sources x 60 enemies: {visibility_cost(n):.3f} ms")


if __name__ == "__main__":
    main()
