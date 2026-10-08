"""Bakes the static painted map once at load: ground, jungle, mud roads, firebase.

Everything here is drawn a single time into one surface; per-frame code just
blits it. Output is deterministic for a given map, so screenshots and tests
are repeatable. Sprites come from art.py, and every colour from palette.py.
"""
import math
import random

import pygame

import art
import palette as P

TRAIL_W = 34          # drawn width of the mud road; the tile grid stays the rule


def _span(gen, lo, hi):
    """Re-scale a generator's 0..1 progress into lo..hi, passing its return value through."""
    try:
        while True:
            yield lo + (hi - lo) * next(gen)
    except StopIteration as done:
        return done.value


def _dist_to_segment(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L))
    return math.hypot(p[0] - (ax + t * dx), p[1] - (ay + t * dy))


def _trail_distance(p, centers):
    return min(_dist_to_segment(p, a, b) for path in centers for a, b in zip(path, path[1:]))


def _soft_noise(size, cell, tones, rng):
    """Low-resolution random colours scaled up smoothly: cheap soft mottling."""
    w, h = size
    small = pygame.Surface((w // cell + 2, h // cell + 2))
    for y in range(small.get_height()):
        for x in range(small.get_width()):
            small.set_at((x, y), rng.choice(tones))
    return pygame.transform.smoothscale(small, (w + cell * 2, h + cell * 2))


def _ground(size, rng):
    """Mottled green ground with grass flecks. A generator: yields a fraction (0..1) now and
    then so loading can repaint; returns the surface."""
    greens = [P.shade("jungle_mid", f) for f in (0.7, 0.85, 1.0, 1.1)] + [P.color("jungle_light")]
    surf = _soft_noise(size, 64, greens, rng).subsurface((0, 0, *size)).copy()
    yield 0.2
    fine = _soft_noise(size, 14, greens + [P.shade("leaf_deep", 1.2)], rng).subsurface((0, 0, *size)).copy()
    fine.set_alpha(120)
    surf.blit(fine, (0, 0))
    yield 0.3
    w, h = size
    flecks = w * h // 45
    for n in range(flecks):                           # grass flecks, light and dark
        x, y = rng.randrange(w), rng.randrange(h)
        tone = rng.choice(("leaf_deep", "jungle_dark", "jungle_light", "leaf_bright", "jungle_light"))
        pygame.draw.line(surf, P.shade(tone, 0.85 + rng.random() * 0.3), (x, y), (x + rng.choice((-1, 0, 1)), y - rng.randint(2, 4)))
        if n % 1800 == 1799:
            yield 0.3 + 0.7 * (n + 1) / flecks
    return surf


def _scatter(game_map, centers, rng, detail=1.0):
    """Foliage positions: thick in the deep jungle, none on or beside the trails or in the firebase."""
    ts = game_map.tile_size
    w, h = game_map.world_size
    bx, by = game_map.base[0] * ts + ts / 2, game_map.base[1] * ts + ts / 2
    items = []

    def ok(x, y, clear):
        return (_trail_distance((x, y), centers) > clear and math.hypot(x - bx, (y - by) * 0.8) > 118
                and math.hypot(x - bx, y - by) > 112)

    for _ in range(int(900 * detail)):                             # big canopy trees, well off the trails
        x, y = rng.uniform(-10, w + 10), rng.uniform(-4, h + 20)
        if ok(x, y, 62) and all(math.hypot(x - ix, (y - iy)) > 66 for k, ix, iy, _ in items if k == "tree"):
            items.append(("tree", x, y, rng.randrange(4)))
    for _ in range(int(1400 * detail)):                            # palms and ferns, closer in
        x, y = rng.uniform(0, w), rng.uniform(0, h + 10)
        if ok(x, y, 40) and all(math.hypot(x - ix, y - iy) > 30 for k, ix, iy, _ in items if k in ("palm", "fern")):
            items.append((rng.choice(("palm", "palm", "fern")), x, y, rng.randrange(4)))
    for _ in range(int(500 * detail)):                             # bushes and grass everywhere legal
        x, y = rng.uniform(0, w), rng.uniform(0, h + 6)
        if ok(x, y, 27):
            items.append((rng.choice(("bush", "tuft", "tuft", "tuft")), x, y, rng.randrange(3)))
    items.sort(key=lambda it: it[2])                               # back to front
    return items


def _paste(surf, sprite, x, y, flip=False, scale=1.0, cache=None):
    """Blit a sprite standing on (x, y). `cache` holds scaled copies for one bake only:
    keyed by object id, it must never outlive the sprites it describes."""
    if scale != 1.0:
        key = (id(sprite), scale)
        if cache is None or key not in cache:
            scaled = pygame.transform.smoothscale(
                sprite, (round(sprite.get_width() * scale), round(sprite.get_height() * scale)))
            if cache is None:
                sprite = scaled
            else:
                cache[key] = scaled
        if cache is not None:
            sprite = cache[key]
    if flip:
        sprite = pygame.transform.flip(sprite, True, False)
    surf.blit(sprite, (x - sprite.get_width() / 2, y - sprite.get_height() * 0.78))


def _trails(surf, centers, rng):
    edge, mud = P.shade("mud", 0.78), P.color("mud")
    rut, hi = P.mix("mud", "mud_dark", 0.55), P.shade("mud", 1.25)
    for path in centers:
        for width, col in ((TRAIL_W + 7, edge), (TRAIL_W, mud)):
            pygame.draw.lines(surf, col, False, path, width)
            for p in path:
                pygame.draw.circle(surf, col, p, width // 2)
        for a, b in zip(path, path[1:]):
            L = math.dist(a, b)
            ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            nx, ny = -uy, ux
            for off in (-7.5, 7.5):                                # the two wheel ruts
                a2 = (a[0] + nx * off, a[1] + ny * off)
                b2 = (b[0] + nx * off, b[1] + ny * off)
                pygame.draw.line(surf, rut, a2, b2, 4)
                pygame.draw.line(surf, hi, (a2[0] + nx * 3.2, a2[1] + ny * 3.2), (b2[0] + nx * 3.2, b2[1] + ny * 3.2), 1)
                d = 6.0
                while d < L - 4:                                   # tread marks across the rut
                    x, y = a2[0] + ux * d, a2[1] + uy * d
                    pygame.draw.line(surf, P.mix("mud", "mud_dark", 0.8), (x - nx * 2.4 - ux * 1.5, y - ny * 2.6 - uy * 1.5),
                                     (x + nx * 2.6 + ux * 1.5, y + ny * 2.6 + uy * 1.5), 1)
                    d += 8.5
            for _ in range(int(L / 5)):                            # mud speckle, stones
                t = rng.random()
                x = a[0] + (b[0] - a[0]) * t + nx * rng.uniform(-15, 15)
                y = a[1] + (b[1] - a[1]) * t + ny * rng.uniform(-15, 15)
                pygame.draw.circle(surf, P.mix("mud", rng.choice(("mud_dark", "khaki", "concrete")), rng.uniform(0.15, 0.5)),
                                   (x, y), rng.choice([1, 1, 2]))
    for i, path in enumerate(centers):                             # puddles on the long straights
        for a, b in zip(path, path[1:]):
            if math.dist(a, b) > 150 and rng.random() < 0.9:
                t = rng.uniform(0.3, 0.7)
                x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t + rng.uniform(-6, 6)
                p = art.mud_puddle(rng.randrange(1000))
                surf.blit(p, (x - p.get_width() / 2, y - p.get_height() / 2))


def _route_marks(surf, centers):
    """Faint grease-pencil dashes and direction arrows down each trail."""
    col = (*P.color("ink"), 110)
    layer = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
    for path in centers:
        walked, next_arrow = 0.0, 90.0
        for a, b in zip(path, path[1:]):
            L = math.dist(a, b)
            ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            d = 0.0
            while d < L:
                e = min(d + 9, L)
                pygame.draw.line(layer, col, (a[0] + ux * d, a[1] + uy * d), (a[0] + ux * e, a[1] + uy * e), 2)
                d += 17
                if walked + d >= next_arrow and d < L - 14:
                    x, y = a[0] + ux * d, a[1] + uy * d
                    for sgn in (-1, 1):
                        ang = math.atan2(uy, ux) + math.pi + sgn * 0.5
                        pygame.draw.line(layer, col, (x, y), (x + 9 * math.cos(ang), y + 9 * math.sin(ang)), 2)
                    next_arrow += 180
            walked += L
    surf.blit(layer, (0, 0))


def _firebase(surf, game_map, rng):
    """Gravel apron, sandbag walls, concrete bunker, crates and razor wire around the base tile."""
    ts = game_map.tile_size
    bx, by = game_map.base[0] * ts + ts / 2, game_map.base[1] * ts + ts / 2
    apron = pygame.Surface((260, 230), pygame.SRCALPHA)
    pygame.draw.ellipse(apron, (*P.mix("concrete", "khaki", 0.35), 235), apron.get_rect().inflate(-6, -6))
    pygame.draw.ellipse(apron, (*P.mix("concrete", "mud", 0.3), 255), apron.get_rect().inflate(-30, -28))
    for _ in range(420):
        x, y = rng.randrange(40, 220), rng.randrange(36, 196)
        if apron.get_at((x, y)).a > 200:
            pygame.draw.circle(apron, P.mix("concrete", rng.choice(("khaki", "mud_dark", "paper")), rng.uniform(0.1, 0.5)),
                               (x, y), rng.choice([1, 1, 2]))
    surf.blit(apron, (bx - 130 + 14, by - 115))
    top, bottom, left = by - 70, by + 74, bx - 52
    parts = []
    parts.append((top, art.sandbag_wall(120), bx - 4, top))                       # back wall
    parts.append((bottom, art.sandbag_wall(120), bx - 4, bottom))                 # front wall
    parts.append((top + 40, art.sandbag_wall(48, True), left, top + 44))          # left wall, gap for the road
    parts.append((bottom - 20, art.sandbag_wall(48, True), left, bottom - 6))
    parts.append((by - 4, art.bunker(), bx + 22, by + 26))                         # command bunker
    parts.append((by + 40, art.barrel(), bx - 30, by + 44))
    parts.append((by - 36, art.barrel(), bx - 22, by - 36))
    for _, spr, x, y in sorted(parts, key=lambda p: p[3]):
        _paste(surf, spr, x, y)
    # razor wire across the approaches, a gap left where each trail comes in
    wx = left - 36
    for y0, y1 in ((top - 14, by - 34), (by + 34, bottom + 14)):
        n = max(1, int((y1 - y0) / 40))
        for i in range(n + 1):
            y = y0 + (y1 - y0) * i / n
            _paste(surf, art.wire_stake(), wx, y + 10)
        for i in range(n):
            y = y0 + (y1 - y0) * (i + 0.5) / n
            coil = pygame.transform.rotate(art.wire_coil(40), 90)
            surf.blit(coil, (wx - coil.get_width() / 2 + 2, y - coil.get_height() / 2))
    for x0 in range(int(left - 36), int(bx + 60), 52):                             # front line of wire
        _paste(surf, art.wire_coil(46), x0 + 24, bottom + 36)
        _paste(surf, art.wire_stake(), x0 + 1, bottom + 38)


def _stamp(surf, text, font, center, degrees):
    ink = font.render(text, True, P.color("ink"))
    face = font.render(text, True, P.shade("paper", 0.92))
    box = pygame.Surface((face.get_width() + 4, face.get_height() + 4), pygame.SRCALPHA)
    for dx, dy in ((0, 0), (4, 0), (0, 4), (4, 4), (2, 0), (0, 2), (4, 2), (2, 4)):
        box.blit(ink, (dx, dy))
    box.blit(face, (2, 2))
    box.set_alpha(225)
    box = pygame.transform.rotate(box, degrees)
    surf.blit(box, box.get_rect(center=center))


def _vignette(surf):
    w, h = surf.get_size()
    small = pygame.Surface((16, 12))
    for y in range(12):
        for x in range(16):
            d = max(abs(x - 7.5) / 8, abs(y - 5.5) / 6)
            v = int(255 - 95 * max(0.0, d - 0.5) / 0.5)
            small.set_at((x, y), (v, v, v))
    surf.blit(pygame.transform.smoothscale(small, (w, h)), (0, 0), special_flags=pygame.BLEND_MULT)


CHUNK = 70   # sprites pasted between progress reports


def bake_steps(game_map, strings, assets, detail=1.0):
    """Generator behind bake_map. Yields a progress fraction (0..1) between phases so a
    caller can repaint a loading bar and give the browser a turn; returns the surface.
    `detail` below 1 thins the foliage for slower targets (the browser build)."""
    ts = game_map.tile_size
    size = game_map.world_size
    rng = random.Random(game_map.key)
    surf = yield from _span(_ground(size, rng), 0.0, 0.08)
    centers = [[(c * ts + ts / 2, r * ts + ts / 2) for c, r in path] for path in game_map.paths]
    variants = {k: [fn(i * 17 + 3) for i in range(4 if k in ("tree", "palm") else 3)] for k, fn in art.FOLIAGE.items()}
    yield 0.14
    items = _scatter(game_map, centers, rng, detail)
    scaled_cache = {}
    yield 0.24
    for i, (kind, x, y, v) in enumerate(items):                    # jungle behind the roads
        scale = rng.choice((0.75, 0.9, 1.0, 1.15)) if kind in ("tree", "palm") else rng.choice((0.9, 1.0, 1.15))
        _paste(surf, variants[kind][v % len(variants[kind])], x, y, rng.random() < 0.5, scale, scaled_cache)
        if i % CHUNK == CHUNK - 1:
            yield 0.24 + 0.46 * (i + 1) / len(items)
    _trails(surf, centers, rng)
    yield 0.74
    _route_marks(surf, centers)
    yield 0.78
    segments = [(p[i], p[i + 1]) for p in centers for i in range(len(p) - 1)]
    fringe = int(sum(len(p) for p in centers) * 5 * detail)
    for n in range(fringe):                                        # ferns and grass fringing the road edges
        a, b = rng.choice(segments)
        t = rng.random()
        L = math.dist(a, b)
        nx, ny = -(b[1] - a[1]) / L, (b[0] - a[0]) / L
        side = rng.choice((-1, 1))
        x = a[0] + (b[0] - a[0]) * t + nx * side * (TRAIL_W / 2 + rng.uniform(4, 12))
        y = a[1] + (b[1] - a[1]) * t + ny * side * (TRAIL_W / 2 + rng.uniform(4, 12))
        if _trail_distance((x, y), centers) > TRAIL_W / 2 + 2:
            kind = rng.choice(("tuft", "tuft", "fern", "bush"))
            _paste(surf, variants[kind][rng.randrange(3)], x, y + 6, rng.random() < 0.5)
        if n % 40 == 39:
            yield 0.78 + 0.12 * (n + 1) / max(1, fringe)
    _firebase(surf, game_map, rng)
    yield 0.94
    font = assets.font("label", 18)
    for key, col, row, degrees in game_map.labels:
        _stamp(surf, strings.get(key), font, (col * ts, row * ts), degrees)
    _vignette(surf)
    yield 1.0
    return surf


def bake_map(game_map, strings, assets, detail=1.0):
    """The finished map surface. See bake_steps for the incremental form."""
    gen = bake_steps(game_map, strings, assets, detail)
    try:
        while True:
            next(gen)
    except StopIteration as done:
        return done.value
