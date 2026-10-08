"""Visual effects: muzzle flashes, smoke, sparks, impacts, rain, light shafts.

Presentation only. None of this touches the simulation, and its randomness
comes from its own generator so it can never change an outcome. Casualties are
shown as a quick desaturate-and-fade, never as anything graphic.
"""
import math
import random

import pygame

import palette as P


def _soft_disc(r, color, alpha):
    """A radial-falloff disc, used for smoke puffs and glints."""
    s = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
    for i in range(r, 0, -1):
        a = int(alpha * (1 - i / r) ** 1.3 + 4)
        pygame.draw.circle(s, (*color, min(255, a)), (r, r), i)
    return s


def _flash_sprite(size, rng):
    """A jagged muzzle-flash star pointing east."""
    s = pygame.Surface((size * 2, size * 2), pygame.SRCALPHA)
    c = size
    pts = []
    for i in range(14):
        a = math.tau * i / 14
        r = size * (1.0 if i % 2 == 0 else 0.38) * (0.75 + rng.random() * 0.25)
        if abs(math.sin(a)) > 0.85:
            r *= 0.5                       # keep it long and narrow, a flash not a ball
        pts.append((c + math.cos(a) * r, c + math.sin(a) * r * 0.62))
    pygame.draw.polygon(s, (*P.color("amber"), 235), pts)
    pygame.draw.polygon(s, (*P.color("amber_hot"), 255), [(c + (x - c) * 0.55, c + (y - c) * 0.55) for x, y in pts])
    return s


class Rain:
    """Slanted streaks plus ground ripples. Drawn before the darkness overlay,
    so the dark swallows them and the lit pools make them shimmer."""
    SLANT = 0.28

    def __init__(self, size, seed=11, drops=420):
        self.w, self.h = size
        self.rng = random.Random(seed)
        self.drops = [[self.rng.uniform(0, self.w), self.rng.uniform(0, self.h),
                       self.rng.uniform(520, 760), self.rng.uniform(7, 13)] for _ in range(drops)]
        self.ripples = []   # [x, y, age]
        self.intensity = 0.0

    def update(self, dt, intensity):
        self.intensity = intensity
        if intensity <= 0.02:
            return
        for d in self.drops[:int(len(self.drops) * intensity)]:
            d[1] += d[2] * dt
            d[0] += d[2] * dt * self.SLANT
            if d[1] > self.h + 10 or d[0] > self.w + 10:
                d[0], d[1] = self.rng.uniform(-80, self.w), self.rng.uniform(-40, -4)
        for rp in self.ripples:
            rp[2] += dt
        self.ripples = [r for r in self.ripples if r[2] < 0.45]
        if len(self.ripples) < 26 * intensity and self.rng.random() < 0.9:
            self.ripples.append([self.rng.uniform(0, self.w), self.rng.uniform(40, self.h), 0.0])

    def draw(self, screen, origin_y, backdrop_tone=0.45):
        if self.intensity <= 0.02:
            return
        col = P.mix("rain", "jungle_dark", backdrop_tone)
        n = int(len(self.drops) * self.intensity)
        for x, y, v, L in self.drops[:n]:
            pygame.draw.line(screen, col, (x, y + origin_y), (x - L * self.SLANT, y + origin_y - L))
        rcol = P.mix("rain", "jungle_mid", 0.5)
        for x, y, age in self.ripples:
            t = age / 0.45
            r = 2 + 7 * t
            rect = pygame.Rect(0, 0, r * 2, r * 0.9)
            rect.center = (x, y + origin_y)
            pygame.draw.ellipse(screen, P.mix(rcol, "jungle_mid", t), rect, 1)


class Fx:
    def __init__(self, seed=5):
        self.rng = random.Random(seed)
        self.smoke = []     # [x, y, vx, vy, age, ttl, r]
        self.sparks = []    # [x, y, vx, vy, age, ttl]
        self.flashes = []   # [x, y, angle, age, ttl, size, variant]
        self.rings = []     # [x, y, radius, age, ttl, tone]
        self.ghosts = []    # [surface, x, y, age]
        self._puffs = {}
        self._flash_variants = [_flash_sprite(16, random.Random(i)) for i in range(3)]

    # ---- spawning ----
    def muzzle(self, x, y, angle, tip, size=1.0):
        self.flashes.append([x + math.cos(angle) * tip, y + math.sin(angle) * tip, angle,
                             0.0, 0.07, size, self.rng.randrange(3)])
        self.sparks_at(x + math.cos(angle) * tip, y + math.sin(angle) * tip, 2, angle, 0.9)
        self.puff(x + math.cos(angle) * tip, y + math.sin(angle) * tip, 1, 3.0, rise=14)

    def mortar_fire(self, x, y, angle, tip):
        px, py = x + math.cos(angle) * tip, y + math.sin(angle) * tip
        self.flashes.append([px, py, angle, 0.0, 0.1, 1.9, self.rng.randrange(3)])
        self.puff(px, py, 6, 6.0, rise=26)
        self.sparks_at(px, py, 6, angle, 1.4)

    def hit(self, x, y, angle):
        self.sparks_at(x, y - 8, 5, angle + math.pi, 1.0, spread=1.6)

    def impact(self, x, y, radius):
        self.rings.append([x, y, radius, 0.0, 0.45, "khaki"])
        self.puff(x, y, 8, radius * 0.22, rise=22, spread=radius * 0.5, tone="mud")
        self.sparks_at(x, y - 4, 8, -math.pi / 2, 1.5, spread=3.0)

    def claymore(self, x, y, radius):
        self.rings.append([x, y, radius, 0.0, 0.35, "amber"])
        self.flashes.append([x, y - 4, 0.0, 0.0, 0.14, 4.0, 0])
        self.puff(x, y, 10, radius * 0.2, rise=18, spread=radius * 0.6)
        self.sparks_at(x, y - 4, 14, -math.pi / 2, 2.0, spread=3.1)

    def tower_lost(self, x, y):
        self.puff(x, y - 4, 7, 6.0, rise=20, spread=16, tone="mud")
        self.sparks_at(x, y - 6, 8, -math.pi / 2, 1.2, spread=2.6)

    def ghost(self, surface, x, y):
        """A fallen unit or position, shown as a desaturated shape that fades out."""
        gray = pygame.transform.grayscale(surface)
        self.ghosts.append([gray, x, y, 0.0])

    def puff(self, x, y, n, r, rise=16, spread=4.0, tone="concrete"):
        for _ in range(n):
            self.smoke.append([x + self.rng.uniform(-spread, spread), y + self.rng.uniform(-spread, spread) * 0.6,
                               self.rng.uniform(-8, 8), -self.rng.uniform(rise * 0.5, rise),
                               0.0, self.rng.uniform(0.6, 1.1), r * self.rng.uniform(0.8, 1.4), tone])

    def sparks_at(self, x, y, n, angle, speed, spread=0.7):
        for _ in range(n):
            a = angle + self.rng.uniform(-spread, spread)
            v = self.rng.uniform(40, 130) * speed
            self.sparks.append([x, y, math.cos(a) * v, math.sin(a) * v, 0.0, self.rng.uniform(0.18, 0.4)])

    # ---- simulation ----
    def update(self, dt):
        for p in self.smoke:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[3] *= 0.97
            p[4] += dt
            p[6] += dt * 8
        self.smoke = [p for p in self.smoke if p[4] < p[5]]
        for s in self.sparks:
            s[0] += s[2] * dt
            s[1] += s[3] * dt
            s[3] += 260 * dt            # gravity
            s[4] += dt
        self.sparks = [s for s in self.sparks if s[4] < s[5]]
        for f in self.flashes:
            f[3] += dt
        self.flashes = [f for f in self.flashes if f[3] < f[4]]
        for r in self.rings:
            r[3] += dt
        self.rings = [r for r in self.rings if r[3] < r[4]]
        for g in self.ghosts:
            g[3] += dt
        self.ghosts = [g for g in self.ghosts if g[3] < 0.55]

    # ---- drawing: smoke and ghosts sit in the world, flashes and sparks are self-lit ----
    def _puff_sprite(self, r, tone):
        key = (max(3, int(r) // 2 * 2), tone)
        if key not in self._puffs:
            col = P.mix("concrete", "mud", 0.4) if tone == "mud" else P.mix("concrete", "paper", 0.2)
            self._puffs[key] = _soft_disc(key[0], col, 170)
        return self._puffs[key]

    def draw_world(self, screen, origin_y):
        for surf, x, y, age in self.ghosts:
            t = age / 0.55
            img = surf.copy()
            img.set_alpha(int(190 * (1 - t)))
            screen.blit(img, img.get_rect(midbottom=(x, y + origin_y - 2 * t * 8)))
        for x, y, vx, vy, age, ttl, r, tone in self.smoke:
            spr = self._puff_sprite(r, tone)
            spr.set_alpha(int(255 * (1 - age / ttl) ** 1.2))
            screen.blit(spr, spr.get_rect(center=(x, y + origin_y)))
        for x, y, radius, age, ttl, tone in self.rings:
            if tone == "khaki":
                t = age / ttl
                rr = max(2, int(radius * (0.3 + 0.7 * t)))
                rect = pygame.Rect(0, 0, rr * 2, rr * 1.3)
                rect.center = (x, y + origin_y)
                pygame.draw.ellipse(screen, P.mix("khaki", "mud", t), rect, 2)

    def draw_lit(self, screen, origin_y):
        for x, y, radius, age, ttl, tone in self.rings:
            if tone == "amber":
                t = age / ttl
                rr = max(2, int(radius * (0.3 + 0.7 * t)))
                rect = pygame.Rect(0, 0, rr * 2, rr * 1.3)
                rect.center = (x, y + origin_y)
                pygame.draw.ellipse(screen, P.mix("amber_hot", "amber", t), rect, 3)
        for x, y, angle, age, ttl, size, v in self.flashes:
            spr = self._flash_variants[v]
            k = size * (1.15 - 0.4 * age / ttl)
            img = pygame.transform.rotozoom(spr, -math.degrees(angle), k)
            screen.blit(img, img.get_rect(center=(x, y + origin_y)))
        for x, y, vx, vy, age, ttl in self.sparks:
            t = age / ttl
            col = P.mix("amber_hot", "clay", t)
            pygame.draw.line(screen, col, (x, y + origin_y), (x - vx * 0.012, y - vy * 0.012 + origin_y), 2)
