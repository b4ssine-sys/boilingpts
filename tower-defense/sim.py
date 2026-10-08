"""Game simulation. No pygame, no drawing, no display strings.

Coordinates are world units (the map's top-left is 0,0). Presentation code
decides where the map sits on screen. The renderer reads this state and never
writes to it.
"""
import math
import random
from collections import namedtuple


# A hidden enemy's last known position, kept briefly so it can be marked and fired on.
Contact = namedtuple("Contact", "x y fraction age")


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


# ---- enemy behaviors: fn(enemy, dt, game) moves or acts ----

def _follow_path(enemy, dt, game=None):
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


def _nearest_tower(enemy, towers, within):
    best, best_d = None, within
    for t in towers:
        if t.defn.kind == "mine" or t.hp <= 0:
            continue
        d = math.hypot(t.x - enemy.x, t.y - enemy.y)
        if d <= best_d:
            best, best_d = t, d
    return best


def _seek_tower(enemy, dt, game):
    """Walk the trail until a tower comes within aggro range, then go and hit
    it. If every nearby tower falls, rejoin the trail from where it stands."""
    d = enemy.defn
    if enemy.tower_target is None or enemy.tower_target.hp <= 0:
        enemy.tower_target = _nearest_tower(enemy, game.towers.values(), d.aggro_range)
    tgt = enemy.tower_target
    if tgt is None:
        _follow_path(enemy, dt)
        return
    dx, dy = tgt.x - enemy.x, tgt.y - enemy.y
    dist = math.hypot(dx, dy)
    if dist > d.attack_range:
        step = min(enemy.speed * dt, dist - d.attack_range)
        enemy.x += dx / dist * step
        enemy.y += dy / dist * step
        return
    enemy.attack_cooldown -= dt
    if enemy.attack_cooldown <= 0:
        tgt.hp -= d.attack_damage
        enemy.attack_cooldown = d.attack_interval


BEHAVIORS = {"follow_path": _follow_path, "seek_tower": _seek_tower}


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
        self.tower_target = None
        self.attack_cooldown = 0.0
        self.visible = True      # can the defence see it right now (set each update)
        self.last_seen = None    # (x, y, fraction, clock) the last time it was visible

    @property
    def alive(self):
        return self.hp > 0 and not self.reached_end

    @property
    def fraction(self):
        """How far along its own path, 0..1. Comparable across paths."""
        return self.progress / self.path_length if self.path_length else 1.0

    def update(self, dt, game=None):
        BEHAVIORS[self.defn.behavior](self, dt, game)

    def predict(self, seconds):
        """Where this enemy will be after `seconds` if it keeps to its path."""
        if self.tower_target is not None:
            return self.x, self.y
        x, y, idx, step = self.x, self.y, self.target, self.speed * seconds
        wps = self.waypoints
        while step > 0 and idx < len(wps):
            tx, ty = wps[idx]
            dist = math.hypot(tx - x, ty - y)
            if dist <= step:
                x, y, step, idx = tx, ty, step - dist, idx + 1
            else:
                x += (tx - x) / dist * step
                y += (ty - y) / dist * step
                step = 0
        return x, y


class Bullet:
    def __init__(self, x, y, enemy, damage, speed, hits=True):
        self.x, self.y = x, y
        self.enemy = enemy
        self.damage = damage
        self.speed = speed
        self.hits = hits  # decided at the muzzle; a miss still flies to the target
        self.heading = 0.0
        self.done = False

    def update(self, dt, game=None):
        if not self.enemy.alive:
            self.done = True
            return
        dx, dy = self.enemy.x - self.x, self.enemy.y - self.y
        dist = math.hypot(dx, dy)
        self.heading = math.atan2(dy, dx)
        step = self.speed * dt
        if dist <= step:
            if self.hits:
                self.enemy.hp -= self.damage
            if game is not None:
                game.events.append(("hit" if self.hits else "miss", self.enemy.x, self.enemy.y, self.heading))
            self.done = True
        else:
            self.x += dx / dist * step
            self.y += dy / dist * step


# ---- targeting strategies: fn(tower, candidates) -> enemy ----

TARGETING = {
    "furthest": lambda tower, cands: max(cands, key=lambda e: e.fraction),
    "closest": lambda tower, cands: min(cands, key=lambda e: math.hypot(e.x - tower.x, e.y - tower.y)),
}


class Shell:
    """Mortar round. Flies to a fixed point and splashes whatever is there."""

    def __init__(self, x, y, tx, ty, damage, speed, radius):
        self.x, self.y = x, y
        self.tx, self.ty = tx, ty
        self.damage, self.speed, self.radius = damage, speed, radius
        self.sx, self.sy = x, y   # where it was fired from, for drawing the arc
        self.done = False

    def update(self, dt, game):
        dx, dy = self.tx - self.x, self.ty - self.y
        dist = math.hypot(dx, dy)
        step = self.speed * dt
        if dist <= step:
            game.splash(self.tx, self.ty, self.radius, self.damage)
            game.events.append(("splash", self.tx, self.ty, self.radius))
            self.done = True
        else:
            self.x += dx / dist * step
            self.y += dy / dist * step


class Tower:
    def __init__(self, tdef, col, row, tile_size):
        self.defn = tdef
        self.col, self.row = col, row
        self.x, self.y = tile_center(col, row, tile_size)
        self.cooldown = 0.0
        self.hp = self.max_hp = tdef.hp
        self.aim = 0.0      # radians, last direction fired
        self.spent = False  # mines: already burst

    def update(self, dt, game):
        k = self.defn.kind
        if k == "turret":
            self._fire(dt, game)
        elif k == "mine":
            self._trigger(game)

    def _fire(self, dt, game):
        self.cooldown -= dt
        if self.cooldown > 0:
            return
        d = self.defn
        cands = []
        for e in game.enemies:
            if not (e.alive and e.visible):
                continue
            dist = math.hypot(e.x - self.x, e.y - self.y)
            if d.min_range <= dist <= d.range:
                cands.append(e)
        hit_chance, scatter = game.shot_quality(self)
        if cands:
            target = TARGETING[d.targeting](self, cands)
            if d.splash_radius:
                # Lead the target: flight time depends on where it will be.
                tx, ty = target.x, target.y
                for _ in range(2):
                    tx, ty = target.predict(math.hypot(tx - self.x, ty - self.y) / d.projectile_speed)
                self._lob(game, tx, ty, scatter)
            else:
                hits = game.rng.random() < hit_chance
                game.bullets.append(Bullet(self.x, self.y, target, d.damage, d.projectile_speed, hits))
                self.aim = math.atan2(target.y - self.y, target.x - self.x)
        elif d.splash_radius:
            # Nothing in sight: fire blind on the freshest contact in reach.
            reach = [c for c in game.contacts
                     if d.min_range <= math.hypot(c.x - self.x, c.y - self.y) <= d.range]
            if not reach:
                return
            c = max(reach, key=lambda c: c.fraction)
            self._lob(game, c.x, c.y, scatter)
        else:
            return
        # radius carries the aim angle so the renderer can place the flash at the barrel tip
        game.events.append(("mortar_fire" if d.splash_radius else "muzzle", self.x, self.y, self.aim))
        self.cooldown = d.cooldown

    def _lob(self, game, tx, ty, scatter):
        d = self.defn
        if scatter:
            ang = game.rng.uniform(0, math.tau)
            off = scatter * math.sqrt(game.rng.random())
            tx, ty = tx + math.cos(ang) * off, ty + math.sin(ang) * off
        game.shells.append(Shell(self.x, self.y, tx, ty, d.damage, d.projectile_speed, d.splash_radius))
        self.aim = math.atan2(ty - self.y, tx - self.x)

    def _trigger(self, game):
        d = self.defn
        for e in game.enemies:
            if e.alive and math.hypot(e.x - self.x, e.y - self.y) <= d.trigger_radius:
                game.splash(self.x, self.y, d.splash_radius, d.damage)
                game.events.append(("claymore", self.x, self.y, d.splash_radius))
                self.spent = True
                return


class Game:
    def __init__(self, content, map_key, seed=0):
        self.content = content
        self.seed = seed
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
            if t.targeting not in TARGETING:
                raise ValueError(f"tower {key!r}: unknown targeting {t.targeting!r}")
        for wave in self.map.waves:
            for g in wave.groups:
                if self.content.enemies[g.enemy].behavior not in BEHAVIORS:
                    raise ValueError(f"enemy {g.enemy!r}: no behavior {self.content.enemies[g.enemy].behavior!r}")

    def reset(self):
        self.supply = self.map.start_supply
        self.integrity = self.map.start_integrity
        self.wave = 0  # number of waves started
        self.towers = {}
        self.enemies = []
        self.bullets = []
        self.shells = []
        self.events = []  # (kind, x, y, radius) for the presentation layer, rebuilt each update
        self._queued = []  # events raised between updates, such as a wave being called
        # Totals for the debrief card.
        self.stats = {"waves_cleared": 0, "stopped": 0, "leaked": 0, "built": 0, "lost": 0}
        self.groups = []  # live spawn state: [SpawnGroup, remaining, timer]
        self.state = "playing"  # playing | won | lost
        self.time_of_day = "day"  # follows the most recently started wave
        self.clock = 0.0
        self.contacts = []  # Contact tuples for hidden enemies seen a moment ago
        self.rng = random.Random(self.seed)  # shot accuracy; seeded so runs repeat

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
        self.time_of_day = wave.time_of_day
        self._queued.append(("wave_start", 0, 0, self.wave))
        self.groups = [[g, g.count, g.delay] for g in wave.groups]

    def placement_ok(self, col, row, tower_key):
        """Is this tile a legal site for the tower, ignoring cost?"""
        if not (0 <= col < self.map.cols and 0 <= row < self.map.rows):
            return False
        if tower_key not in self.map.towers or (col, row) in self.towers:
            return False
        on_trail = (col, row) in self.path_tiles
        return on_trail == (self.content.towers[tower_key].placement == "trail")

    def try_build(self, col, row, tower_key):
        if self.state != "playing" or not self.placement_ok(col, row, tower_key):
            return False
        tdef = self.content.towers[tower_key]
        if self.supply < tdef.cost:
            return False
        self.supply -= tdef.cost
        self.towers[(col, row)] = Tower(tdef, col, row, self.map.tile_size)
        self.stats["built"] += 1
        return True

    # ---- light and visibility ----
    @property
    def time_rule(self):
        return self.map.visibility.rule(self.time_of_day)

    def light_sources(self):
        """Every circle the defence sees by, unscaled: (x, y, radius, kind).
        kind is "sight" (towers and the base) or "light" (flares)."""
        ts = self.map.tile_size
        out = []
        bx, by = tile_center(*self.map.base, ts)
        if self.map.visibility.base_sight:
            out.append((bx, by, self.map.visibility.base_sight, "sight"))
        for t in self.towers.values():
            if t.defn.sight_radius:
                out.append((t.x, t.y, t.defn.sight_radius, "sight"))
            if t.defn.light_radius:
                out.append((t.x, t.y, t.defn.light_radius, "light"))
        return out

    def is_lit(self, x, y):
        """Standing in a flare's light (always true in daylight)."""
        scale = self.time_rule.sight_scale
        if scale == 0:
            return True
        return any(math.hypot(x - sx, y - sy) <= r * scale
                   for sx, sy, r, kind in self.light_sources() if kind == "light")

    def shot_quality(self, tower):
        """(hit chance, mortar scatter) for a shooter, given the time of day and flares."""
        rule = self.time_rule
        if rule.sight_scale == 0 or self.is_lit(tower.x, tower.y):
            return 1.0, 0.0
        return rule.hit_chance, rule.scatter

    def _update_visibility(self):
        scale = self.time_rule.sight_scale
        ttl = self.map.visibility.contact_ttl
        sources = self.light_sources()
        contacts = []
        for e in self.enemies:
            if not e.alive:
                continue
            if scale == 0:
                e.visible = True
            else:
                k = scale * e.defn.visibility
                e.visible = any(math.hypot(e.x - sx, e.y - sy) <= r * k for sx, sy, r, _ in sources)
            if e.visible:
                e.last_seen = (e.x, e.y, e.fraction, self.clock)
            elif e.last_seen and self.clock - e.last_seen[3] <= ttl:
                x, y, frac, t = e.last_seen
                contacts.append(Contact(x, y, frac, self.clock - t))
        self.contacts = contacts

    def splash(self, x, y, radius, damage):
        for e in self.enemies:
            if e.alive and math.hypot(e.x - x, e.y - y) <= radius:
                e.hp -= damage

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
        # Cleared first so a finished game never replays old events. Anything raised
        # since the last update (a wave called by key press) is delivered now.
        self.events, self._queued = self._queued, []
        if self.state != "playing":
            return
        was_active = self.wave_active
        self.clock += dt
        self._spawn(dt)
        for e in self.enemies:
            e.update(dt, self)
        self._update_visibility()
        for t in self.towers.values():
            t.update(dt, self)
        for b in self.bullets:
            b.update(dt, self)
        for sh in self.shells:
            sh.update(dt, self)
        for e in self.enemies:
            if e.hp <= 0:
                self.supply += e.defn.kill_reward
                self.stats["stopped"] += 1
            elif e.reached_end:
                self.integrity -= 1
                self.stats["leaked"] += 1
        self.enemies = [e for e in self.enemies if e.alive]
        self.bullets = [b for b in self.bullets if not b.done]
        self.shells = [sh for sh in self.shells if not sh.done]
        for pos, t in list(self.towers.items()):
            if t.spent:
                del self.towers[pos]
            elif t.hp <= 0:
                del self.towers[pos]
                self.stats["lost"] += 1
                self.events.append(("tower_lost", t.x, t.y, 0))

        if self.integrity <= 0:
            self.state = "lost"
        elif was_active and not self.wave_active:
            self.stats["waves_cleared"] += 1
            self.events.append(("wave_clear", 0, 0, self.wave))
            if self.wave >= len(self.map.waves):
                self.state = "won"
            else:
                self.supply += self.map.resupply_bonus
                self.events.append(("resupply", 0, 0, self.map.resupply_bonus))
