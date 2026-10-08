"""Bakes the static field-map background once at load.

Everything here is drawn a single time into one surface; per-frame code just
blits it. Output is deterministic for a given map, so screenshots and tests
are repeatable.
"""
import math
import random

import pygame

import palette as P


def _lerp_color(a, b, t):
    return P.mix(a, b, t)


def _paper(size, rng):
    w, h = size
    surf = pygame.Surface(size)
    surf.fill(P.color("paper"))
    for _ in range(w * h // 90):  # grain
        x, y = rng.randrange(w), rng.randrange(h)
        surf.fill(_lerp_color("paper", rng.choice(("paper_shadow", "khaki")), rng.uniform(0.1, 0.45)),
                  (x, y, rng.choice([1, 1, 2]), 1))
    return surf


def _dist_to_segment(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def _jungle(surf, game_map, centers, rng):
    ts = game_map.tile_size
    base = (game_map.base[0] * ts + ts / 2, game_map.base[1] * ts + ts / 2)
    for r in range(game_map.rows):
        for c in range(game_map.cols):
            mid = (c * ts + ts / 2, r * ts + ts / 2)
            near_trail = min(_dist_to_segment(mid, a, b)
                             for path in centers for a, b in zip(path, path[1:]))
            if near_trail < ts * 1.1 or math.dist(mid, base) < ts * 3.2:
                continue
            for _ in range(rng.choice((2, 3, 3, 4))):  # short hatch strokes
                x = c * ts + rng.uniform(4, ts - 4)
                y = r * ts + rng.uniform(4, ts - 4)
                L = rng.uniform(6, 11)
                col = P.color(rng.choice(("jungle_mid", "jungle_mid", "jungle_light", "jungle_dark")))
                pygame.draw.line(surf, col, (x, y), (x + L * 0.6, y - L), 1)


def _contours(surf, game_map, rng):
    ts = game_map.tile_size
    cx, cy = game_map.base[0] * ts + ts / 2, game_map.base[1] * ts + ts / 2
    col = P.mix("clay", "paper", 0.45)
    for radius in (2.3, 3.4, 4.5):
        pts = []
        wob = [rng.uniform(-0.18, 0.18) for _ in range(7)]
        for i in range(64):
            a = i / 64 * math.tau
            w = sum(wob[k] * math.sin((k + 1) * a + k) for k in range(7))
            rr = (radius + w) * ts
            pts.append((cx + rr * math.cos(a) * 1.15, cy + rr * math.sin(a)))
        pygame.draw.lines(surf, col, True, pts, 1)


def _trails(surf, centers, rng):
    edge, fill = P.mix("clay", "khaki", 0.35), P.color("khaki")
    for path in centers:
        for width, col in ((36, edge), (28, fill)):
            pygame.draw.lines(surf, col, False, path, width)
            for p in path:
                pygame.draw.circle(surf, col, p, width // 2)
        for a, b in zip(path, path[1:]):  # wear and ruts
            n = int(math.dist(a, b) / 6)
            for i in range(n):
                t = i / max(n, 1)
                x = a[0] + (b[0] - a[0]) * t + rng.uniform(-11, 11)
                y = a[1] + (b[1] - a[1]) * t + rng.uniform(-11, 11)
                pygame.draw.circle(surf, P.mix("khaki", "clay", rng.uniform(0.1, 0.5)), (x, y), rng.choice([1, 1, 2]))


def _route_marks(surf, centers):
    """Grease-pencil dashes and direction arrows down each trail."""
    col = P.mix("clay", "ink", 0.35)
    for path in centers:
        walked = 0.0
        next_arrow = 90.0
        for a, b in zip(path, path[1:]):
            L = math.dist(a, b)
            ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            d = 0.0
            while d < L:
                s, e = d, min(d + 9, L)
                pygame.draw.line(surf, col, (a[0] + ux * s, a[1] + uy * s),
                                 (a[0] + ux * e, a[1] + uy * e), 2)
                d += 17
                if walked + d >= next_arrow and d < L - 14:
                    x, y = a[0] + ux * d, a[1] + uy * d
                    for sgn in (-1, 1):
                        ang = math.atan2(uy, ux) + math.pi + sgn * 0.5
                        pygame.draw.line(surf, col, (x, y), (x + 9 * math.cos(ang), y + 9 * math.sin(ang)), 2)
                    next_arrow += 180
            walked += L


def _base_marker(surf, game_map):
    ts = game_map.tile_size
    cx, cy = game_map.base[0] * ts + ts / 2, game_map.base[1] * ts + ts / 2
    col = P.color("clay")
    r = pygame.Rect(0, 0, ts * 1.5, ts * 1.5)
    r.center = (cx, cy)
    pygame.draw.rect(surf, P.color("paper"), r)
    pygame.draw.rect(surf, col, r, 3)
    pygame.draw.line(surf, col, r.topleft, r.bottomright, 2)
    pygame.draw.line(surf, col, r.topright, r.bottomleft, 2)


def _stamp(surf, text, font, center, degrees):
    label = font.render(text, True, P.color("clay"))
    label.set_alpha(215)
    label = pygame.transform.rotate(label, degrees)
    surf.blit(label, label.get_rect(center=center))


def _folds(surf):
    w, h = surf.get_size()
    for x in (w // 2,):
        pygame.draw.line(surf, P.color("paper_shadow"), (x, 0), (x, h), 2)
        pygame.draw.line(surf, P.mix("paper", "amber_hot", 0.4), (x + 2, 0), (x + 2, h), 1)
    for y in (h // 2,):
        pygame.draw.line(surf, P.color("paper_shadow"), (0, y), (w, y), 2)
        pygame.draw.line(surf, P.mix("paper", "amber_hot", 0.4), (0, y + 2), (w, y + 2), 1)


def _vignette(surf):
    w, h = surf.get_size()
    small = pygame.Surface((16, 12))
    for y in range(12):
        for x in range(16):
            d = max(abs(x - 7.5) / 8, abs(y - 5.5) / 6)
            v = int(255 - 70 * max(0.0, d - 0.55) / 0.45)
            small.set_at((x, y), (v, v, v))
    surf.blit(pygame.transform.smoothscale(small, (w, h)), (0, 0), special_flags=pygame.BLEND_MULT)


def bake_map(game_map, strings, assets):
    ts = game_map.tile_size
    size = game_map.world_size
    rng = random.Random(game_map.key)
    surf = _paper(size, rng)
    centers = [[(c * ts + ts / 2, r * ts + ts / 2) for c, r in path] for path in game_map.paths]
    _jungle(surf, game_map, centers, rng)
    _contours(surf, game_map, rng)
    _trails(surf, centers, rng)
    _route_marks(surf, centers)
    _base_marker(surf, game_map)
    font = assets.font("label", 17)
    for key, col, row, degrees in game_map.labels:
        _stamp(surf, strings.get(key), font, (col * ts, row * ts), degrees)
    _folds(surf)
    _vignette(surf)
    return surf
