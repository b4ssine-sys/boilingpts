"""Game simulation. No pygame, no drawing, no display strings.

Coordinates are world units (the map's top-left is 0,0). Presentation code
decides where the map sits on screen. The renderer reads this state and never
writes to it.
"""
import math


def build_path_tiles(corners):
    tiles = set()
    for (c0, r0), (c1, r1) in zip(corners, corners[1:]):
        dc = (c1 > c0) - (c1 < c0)
        dr = (r1 > r0) - (r1 < r0)
        c, r = c0, r0
        tiles.add((c, r))
        while (c, r) != (c1, r1):
            c, r = c + dc, r + dr
            tiles.add((c, r))
    return tiles


def tile_center(col, row, tile_size):
    return (col * tile_size + tile_size / 2, row * tile_size + tile_size / 2)


def path_length(waypoints):
    return sum(math.dist(a, b) for a, b in zip(waypoints, waypoints[1:]))


# ---- enemy behaviors: fn(enemy, dt) moves the enemy ----

def _follow_path(enemy, dt):
    step = enemy.speed * dt
    enemy.progress += step
    wps = enemy.waypoints
    while step > 0 and enemy.target < len(wps):
        tx, ty = wps[enemy.target]
        dist = math.hypot(tx - enemy.x, ty - enemy.y)
        if dist <= step:
            enemy.x, enemy.y = tx, ty
            step -= dist
            enemy.target += 1
        else:
            enemy.x += (tx - enemy.x) / dist * step
            enemy.y += (ty - enemy.y) / dist * step
            step = 0
    if enemy.target >= len(wps):
        enemy.reached_end = True


BEHAVIORS = {"follow_path": _follow_path}


class Enemy:
    def __init__(self, edef, waypoints, hp=None, speed=None):
        self.defn = edef
        self.waypoints = waypoints
        self.x, self.y = waypoints[0]
        self.hp = self.max_hp = edef.hp if hp is None else hp
        self.speed = edef.speed if speed is None else speed
        self.target = 1
        self.progress = 0.0  # distance walked along its path
        self.path_length = path_length(waypoints)
        self.reached_end = False

    @property
    def alive(self):
        return self.hp > 0 and not self.reached_end

    @property
    def fraction(self):
        """How far along its own path, 0..1. Comparable across paths."""
        return self.progress / self.path_length if self.path_length else 1.0

    def update(self, dt):
        BEHAVIORS[self.defn.behavior](self, dt)


class Bullet:
    def __init__(self, x, y, enemy, damage, speed):
        self.x, self.y = x, y
        self.enemy = enemy
        self.damage = damage
        self.speed = speed
        self.done = False

    def update(self, dt):
        if not self.enemy.alive:
            self.done = True
            return
        dx, dy = self.enemy.x - self.x, self.enemy.y - self.y
        dist = math.hypot(dx, dy)
        step = self.speed * dt
        if dist <= step:
            self.enemy.hp -= self.damage
            self.done = True
        else:
            self.x += dx / dist * step
            self.y += dy / dist * step


# ---- targeting strategies: fn(tower, candidates) -> enemy ----

TARGETING = {
    "furthest": lambda tower, cands: max(cands, key=lambda e: e.fraction),
    "closest": lambda tower, cands: min(cands, key=lambda e: math.hypot(e.x - tower.x, e.y - tower.y)),
}


class Tower:
    def __init__(self, tdef, col, row, tile_size):
        self.defn = tdef
        self.col, self.row = col, row
        self.x, self.y = tile_center(col, row, tile_size)
        self.cooldown = 0.0

    def update(self, dt, enemies, bullets):
        self.cooldown -= dt
        if self.cooldown > 0:
            return
        d = self.defn
        cands = []
        for e in enemies:
            if not e.alive:
                continue
            dist = math.hypot(e.x - self.x, e.y - self.y)
            if d.min_range <= dist <= d.range:
                cands.append(e)
        if cands:
            target = TARGETING[d.targeting](self, cands)
            bullets.append(Bullet(self.x, self.y, target, d.damage, d.projectile_speed))
            self.cooldown = d.cooldown


class Game:
    def __init__(self, content, map_key):
        self.content = content
        self.map = content.maps[map_key]
        self._check_supported()
        ts = self.map.tile_size
        self.path_tiles = set()
        self.paths = []  # world-space waypoints, one list per path
        for corners in self.map.paths:
            self.path_tiles |= build_path_tiles(corners)
            self.paths.append([tile_center(c, r, ts) for c, r in corners])
        self.reset()

    def _check_supported(self):
        """Defs may describe features that land in later milestones. Refuse
        them here so they cannot silently behave like the basic version."""
        for key in self.map.towers:
            t = self.content.towers[key]
            if t.single_use or t.splash_radius or t.placement != "ground":
                raise NotImplementedError(f"tower {key!r} needs M2 mechanics")
            if t.targeting not in TARGETING:
                raise ValueError(f"tower {key!r}: unknown targeting {t.targeting!r}")
        for wave in self.map.waves:
            for g in wave.groups:
                if self.content.enemies[g.enemy].behavior not in BEHAVIORS:
                    raise NotImplementedError(f"enemy {g.enemy!r} needs M2 behavior")

    def reset(self):
        self.supply = self.map.start_supply
        self.integrity = self.map.start_integrity
        self.wave = 0  # number of waves started
        self.towers = {}
        self.enemies = []
        self.bullets = []
        self.groups = []  # live spawn state: [SpawnGroup, remaining, timer]
        self.state = "playing"  # playing | won | lost

    @property
    def wave_active(self):
        return any(g[1] > 0 for g in self.groups) or any(e.alive for e in self.enemies)

    @property
    def current_wave(self):
        """The WaveDef most recently started, or None before the first."""
        return self.map.waves[self.wave - 1] if self.wave else None

    def start_wave(self):
        if self.state != "playing" or self.wave_active or self.wave >= len(self.map.waves):
            return
        wave = self.map.waves[self.wave]
        self.wave += 1
        self.groups = [[g, g.count, g.delay] for g in wave.groups]

    def try_build(self, col, row, tower_key):
        if self.state != "playing":
            return False
        if not (0 <= col < self.map.cols and 0 <= row < self.map.rows):
            return False
        if tower_key not in self.map.towers:
            return False
        tdef = self.content.towers[tower_key]
        if (col, row) in self.path_tiles or (col, row) in self.towers:
            return False
        if self.supply < tdef.cost:
            return False
        self.supply -= tdef.cost
        self.towers[(col, row)] = Tower(tdef, col, row, self.map.tile_size)
        return True

    def _spawn(self, dt):
        for state in self.groups:
            g, remaining, _ = state
            if remaining <= 0:
                continue
            state[2] -= dt
            if state[2] <= 0:
                edef = self.content.enemies[g.enemy]
                self.enemies.append(Enemy(edef, self.paths[g.path], g.hp, g.speed))
                state[1] -= 1
                state[2] = g.interval

    def update(self, dt):
        if self.state != "playing":
            return
        was_active = self.wave_active
        self._spawn(dt)
        for e in self.enemies:
            e.update(dt)
        for t in self.towers.values():
            t.update(dt, self.enemies, self.bullets)
        for b in self.bullets:
            b.update(dt)
        for e in self.enemies:
            if e.hp <= 0:
                self.supply += e.defn.kill_reward
            elif e.reached_end:
                self.integrity -= 1
        self.enemies = [e for e in self.enemies if e.alive]
        self.bullets = [b for b in self.bullets if not b.done]

        if self.integrity <= 0:
            self.state = "lost"
        elif was_active and not self.wave_active:
            if self.wave >= len(self.map.waves):
                self.state = "won"
            else:
                self.supply += self.map.resupply_bonus
