"""Presentation. Reads simulation state, draws it, never mutates it.

Draw order, back to front: baked map, ground decals, towers and enemies sorted
by depth, smoke and fallen units, rain, the darkness overlay, then everything
that glows (light shafts, sparkles, muzzle flashes, tracers, sparks), then
contacts, the placement hover and the interface.
"""
import math
import random

import pygame

import art
import palette as P
from fx import Fx, Rain
from layout import HUD_H, TRAY_H, screen_size
from lighting import SIGHT_STRENGTH, Light, Lighting
from mapart import _span, bake_steps
from ui import Hud
from ui import wrap  # noqa: F401  (re-exported)

FPS = 60
ENEMY_SCALE = 1.3
TOWER_SCALE = 1.25
LAMP_LIFT = 41          # how far above a flare tower's base its lamp sits
RECOIL_PX, RECOIL_TIME = 2.6, 0.09
# Short-lived lights: event kind -> (radius, seconds).
FLASH_LIGHTS = {"muzzle": (46, 0.12), "mortar_fire": (84, 0.2), "claymore": (120, 0.35), "splash": (66, 0.18)}


def world_to_screen(x, y):
    return x, y + HUD_H


def screen_to_tile(pos, tile_size):
    x, y = pos
    return int(x // tile_size), int((y - HUD_H) // tile_size)


class Renderer:
    def __init__(self, strings, assets, game_map, game=None, quality="high", lazy=False):
        """quality "web" is for the browser build: a quarter-resolution darkness layer,
        no light shafts, thinner foliage and lighter rain, trading some polish for load
        time, frame rate and memory.

        The heavy setup (painting the map, building light sprites) runs in small steps.
        By default the constructor runs them all. With lazy=True it returns at once and
        the caller iterates load_steps(), repainting a progress bar between steps, so a
        slow machine or a browser never looks frozen. The renderer is usable once the
        iteration finishes (`ready`)."""
        self.quality = quality
        self.strings = strings
        self.assets = assets
        self.map = game_map
        self.hud = None       # built on first use, once there is a game to read
        self.flashes = []     # [x, y, radius, ttl, age]: short-lived lights
        self._heading = {}    # id(enemy) -> last angle
        self.time = 0.0       # drives animation and flicker; presentation only
        self._recoil = {}     # (x, y) of a gun -> seconds of kick left
        self._last_enemies = {}   # id -> (image, x, y) for fading out the fallen
        self._last_towers = {}    # (x, y) -> (tower key, aim) for fading out lost positions
        self._sparkle_rng = random.Random(9)
        self.ready = False
        self._loader = self._load(game)
        if not lazy:
            for _ in self._loader:
                pass

    def load_steps(self):
        """Iterate to finish loading; yields a progress fraction from 0 to 1."""
        return self._loader

    def _load(self, game):
        web = self.quality == "web"
        w, h = self.map.world_size
        yield 0.0
        self.background = yield from _span(
            bake_steps(self.map, self.strings, self.assets, detail=0.6 if web else 1.0), 0.0, 0.70)
        self.lighting = Lighting((w, h), scale=0.25 if web else 0.5, shafts=not web)
        yield from _span(self.lighting.prewarm_steps(), 0.70, 0.90)
        yield from _span(self.assets.prewarm_steps(TOWER_SCALE, ENEMY_SCALE), 0.90, 0.97)
        self.fx = Fx()
        self.rain = Rain((w, h), drops=180 if web else 420)
        yield 0.98
        if game is not None:
            self._ensure_hud(game)   # build the interface textures now, not on the first frame
        self.ready = True
        yield 1.0

    # ---- per-frame bookkeeping ----
    def _ensure_hud(self, game):
        if self.hud is None:
            self.hud = Hud(self.strings, self.assets, game)
        return self.hud

    def update(self, dt, game):
        self._ensure_hud(game).update(dt, game)
        self.time += dt
        self.lighting.set_time_of_day(game.time_of_day, game.time_rule.sight_scale)
        self.lighting.update(dt)
        self.rain.update(dt, min(1.0, self.lighting.alpha / 150))
        self._enemy_ghosts(game)
        for kind, x, y, extra in game.events:
            self._on_event(game, kind, x, y, extra)
        for sh in game.shells:                                    # a thin smoke trail behind each shell
            if self.fx.rng.random() < 0.5:
                self.fx.puff(sh.x, sh.y - self._arc(sh), 1, 2.2, rise=4, spread=1)
        self.fx.update(dt)
        for fl in self.flashes:
            fl[4] += dt
        self.flashes = [fl for fl in self.flashes if fl[4] < fl[3]]
        self._recoil = {k: v - dt for k, v in self._recoil.items() if v > dt}

    def _on_event(self, game, kind, x, y, extra):
        if kind in FLASH_LIGHTS:
            r, ttl = FLASH_LIGHTS[kind]
            self.flashes.append([x, y, r, ttl, 0.0])
        if kind == "muzzle":
            self.fx.muzzle(x, y, extra, art.GUN_TIP["mg_nest"] * TOWER_SCALE)
            self._recoil[(x, y)] = RECOIL_TIME
        elif kind == "mortar_fire":
            self.fx.mortar_fire(x, y, extra, art.GUN_TIP["mortar"] * TOWER_SCALE)
            self._recoil[(x, y)] = RECOIL_TIME * 1.6
        elif kind == "hit":
            self.fx.hit(x, y, extra)
        elif kind == "splash":
            self.fx.impact(x, y, extra)
        elif kind == "claymore":
            self.fx.claymore(x, y, extra)
        elif kind == "tower_lost":
            self.fx.tower_lost(x, y)
            old = self._last_towers.get((x, y))
            if old:
                self.fx.ghost(self.assets.scaled(f"tower.{old[0]}.base", TOWER_SCALE), x, y + 24)

    def _enemy_image(self, e):
        """(sprite, heading) for an enemy right now: walk frame, mirrored when heading west."""
        tgt = e.tower_target
        ang = math.atan2(tgt.y - e.y, tgt.x - e.x) if tgt is not None else self._path_heading(e)
        self._heading[id(e)] = ang
        frame = int(self.time * (e.speed / 9.0) + (id(e) % 7)) % 2
        img = self.assets.flipped(f"enemy.{e.defn.key}.{frame}", ENEMY_SCALE, math.cos(ang) < 0)
        return img, ang

    def _enemy_ghosts(self, game):
        """Anyone who vanished since last update, seen or not, fades out as a grey shape."""
        now = {}
        for e in game.enemies:
            if e.visible:
                img, _ = self._enemy_image(e)
                now[id(e)] = (img, e.x, e.y)
        for k, (img, x, y) in self._last_enemies.items():
            if k not in now and not any(id(e) == k for e in game.enemies):
                self.fx.ghost(img, x, y + 6)
        self._last_enemies = now

    def _lights(self, game):
        """The same circles the simulation sees by, plus short-lived flashes."""
        k = self.lighting.sight_scale
        out = []
        for x, y, r, kind in game.light_sources():
            if kind == "sight":
                out.append(Light(x, y + HUD_H, r * k, SIGHT_STRENGTH, False, True))
            else:  # flare: flickers, so it is punched every frame
                flick = 1 + 0.05 * math.sin(self.time * 5.1 + x * 0.013) + 0.03 * math.sin(self.time * 13.0 + y)
                out.append(Light(x, y + HUD_H, r * k * flick, 1.0, True, False))
        for x, y, r, ttl, age in self.flashes:
            out.append(Light(x, y + HUD_H, r * (1 - 0.5 * age / ttl), 1.0, True, False))
        return out

    def hit_test(self, pos, game):
        """Route a click to the UI first; None means it was meant for the map."""
        return self._ensure_hud(game).hit_test(pos, game)

    def draw(self, screen, game, build_key, mouse_pos):
        tdef = game.content.towers[build_key]
        screen.fill(P.color("ink"))
        screen.blit(self.background, (0, HUD_H))
        self._draw_units(screen, game)
        self._draw_shells(screen, game)
        self.fx.draw_world(screen, HUD_H)
        self.rain.draw(screen, HUD_H)
        self.lighting.render(screen, self._lights(game), HUD_H)
        self._draw_shafts(screen, game)
        self._draw_tracers(screen, game)
        self.fx.draw_lit(screen, HUD_H)
        self._draw_contacts(screen, game)
        self._draw_hover(screen, game, tdef, mouse_pos)
        hud = self._ensure_hud(game)
        hud.mouse = mouse_pos
        hud.draw(screen, game, build_key)

    # ---- layers ----
    def _draw_hover(self, screen, game, tdef, mouse_pos):
        ts = game.map.tile_size
        hc, hr = screen_to_tile(mouse_pos, ts)
        if game.state != "playing" or not (0 <= hc < game.map.cols and 0 <= hr < game.map.rows):
            return
        cx, cy = world_to_screen(hc * ts + ts / 2, hr * ts + ts / 2)
        rect = (hc * ts, hr * ts + HUD_H, ts, ts)
        if not game.placement_ok(hc, hr, tdef.key):
            # Illegal tile: a red ghost with a cross, and clicking does nothing.
            red = P.color("clay")
            pygame.draw.rect(screen, red, rect, 2)
            pygame.draw.line(screen, red, (rect[0] + 8, rect[1] + 8), (rect[0] + ts - 8, rect[1] + ts - 8), 2)
            pygame.draw.line(screen, red, (rect[0] + ts - 8, rect[1] + 8), (rect[0] + 8, rect[1] + ts - 8), 2)
            return
        ok = game.supply >= tdef.cost
        col = P.color("amber") if ok else P.color("clay")
        self._draw_preview(screen, tdef, cx, cy, ok)
        pygame.draw.rect(screen, col, rect, 2)
        if tdef.range:
            pygame.draw.circle(screen, col, (cx, cy), tdef.range, 1)
        if tdef.min_range:  # blind zone
            pygame.draw.circle(screen, P.color("clay"), (cx, cy), tdef.min_range, 1)
        if tdef.light_radius:
            pygame.draw.circle(screen, P.color("amber_hot"), (cx, cy),
                               tdef.light_radius * self.lighting.sight_scale, 1)

    def _draw_preview(self, screen, tdef, cx, cy, ok):
        """The position about to be built, drawn translucent where it would stand."""
        ax, ay = art.ANCHOR["tower"]
        base = self.assets.composed(tdef.key, TOWER_SCALE)
        base.set_alpha(150 if ok else 80)
        screen.blit(base, (cx - base.get_width() * ax, cy - base.get_height() * ay))

    def _draw_units(self, screen, game):
        """Towers and enemies together, sorted by how far down the map they stand."""
        ax, ay = art.ANCHOR["tower"]
        drawables = []
        for t in game.towers.values():
            self._last_towers[(t.x, t.y)] = (t.defn.key, t.aim)
            drawables.append((t.y - (100 if t.defn.kind == "mine" else 0), 0, t))
        for e in game.enemies:
            if e.visible:
                drawables.append((e.y, 1, e))
        for _, kind, obj in sorted(drawables, key=lambda d: d[0]):
            (self._draw_tower if kind == 0 else self._draw_enemy)(screen, obj)
        for _, kind, obj in drawables:                                 # health bars sit on top of everything
            if kind == 0 and obj.hp < obj.max_hp and obj.defn.kind != "mine":
                x, y = world_to_screen(obj.x, obj.y)
                self._bar(screen, x, y - 44, 30, obj.hp / obj.max_hp)
            elif kind == 1 and obj.hp < obj.max_hp:
                x, y = world_to_screen(obj.x, obj.y)
                self._bar(screen, x, y - 55, 28, max(obj.hp, 0) / obj.max_hp)
        live = {id(e) for e in game.enemies}
        for k in [k for k in self._heading if k not in live]:
            del self._heading[k]

    def _draw_tower(self, screen, t):
        ax, ay = art.ANCHOR["tower"]
        x, y = world_to_screen(t.x, t.y)
        base = self.assets.scaled(f"tower.{t.defn.key}.base", TOWER_SCALE)
        screen.blit(base, (x - base.get_width() * ax, y - base.get_height() * ay))
        gun_key = f"tower.{t.defn.key}.gun"
        if t.defn.kind == "turret" and self.assets.has(gun_key):
            mx, my = art.MOUNT[t.defn.key]
            kick = max(0.0, self._recoil.get((t.x, t.y), 0.0)) / RECOIL_TIME
            gun = self.assets.rotated(gun_key, t.aim, TOWER_SCALE)
            px = x + mx * TOWER_SCALE - math.cos(t.aim) * RECOIL_PX * kick
            py = y + my * TOWER_SCALE - math.sin(t.aim) * RECOIL_PX * kick
            screen.blit(gun, gun.get_rect(center=(px, py)))
        front_key = f"tower.{t.defn.key}.front"
        if self.assets.has(front_key):                                 # the near wall overlaps the gun
            front = self.assets.scaled(front_key, TOWER_SCALE)
            screen.blit(front, (x - front.get_width() * ax, y - front.get_height() * ay))

    def _draw_enemy(self, screen, e):
        img, ang = self._enemy_image(e)
        ax, ay = art.ANCHOR["enemy"]
        x, y = world_to_screen(e.x, e.y)
        bob = abs(math.sin(self.time * e.speed / 9.0 * math.pi + id(e) % 7)) * 1.6
        screen.blit(img, (x - img.get_width() * ax, y - img.get_height() * ay - bob))

    def _path_heading(self, e):
        if e.target < len(e.waypoints):
            tx, ty = e.waypoints[e.target]
            return math.atan2(ty - e.y, tx - e.x)
        return self._heading.get(id(e), 0.0)

    def _bar(self, screen, x, y, w, frac):
        tone = "jungle_light" if frac > 0.5 else "amber" if frac > 0.25 else "clay"
        pygame.draw.rect(screen, P.color("ink"), (x - w / 2 - 1.5, y - 1.5, w + 3, 6), border_radius=2)
        pygame.draw.rect(screen, P.shade(tone, 0.55), (x - w / 2, y, w, 3))
        pygame.draw.rect(screen, P.color(tone), (x - w / 2, y, max(1, w * frac), 3))

    @staticmethod
    def _arc(shell):
        """Height of a mortar round above the ground: a parabola over its flight."""
        total = math.hypot(shell.tx - shell.sx, shell.ty - shell.sy)
        if total < 1:
            return 0.0
        p = 1 - math.hypot(shell.tx - shell.x, shell.ty - shell.y) / total
        return 4 * min(70.0, total * 0.45) * p * (1 - p)

    def _draw_shells(self, screen, game):
        for sh in game.shells:
            gx, gy = world_to_screen(sh.x, sh.y)
            lift = self._arc(sh)
            shadow = pygame.Rect(0, 0, 9 - min(4, lift / 14), 4)
            shadow.center = (gx, gy)
            pygame.draw.ellipse(screen, P.mix("jungle_dark", "ink", 0.7), shadow)
            pygame.draw.circle(screen, P.color("steel"), (gx, gy - lift), 3.4)
            pygame.draw.circle(screen, P.color("khaki"), (gx, gy - lift - 1), 1.6)

    def _draw_tracers(self, screen, game):
        for b in game.bullets:
            x, y = world_to_screen(b.x, b.y - 8)
            dx, dy = math.cos(b.heading), math.sin(b.heading)
            pygame.draw.line(screen, P.color("amber"), (x - dx * 12, y - dy * 12), (x, y), 2)
            pygame.draw.line(screen, P.color("amber_hot"), (x - dx * 5, y - dy * 5), (x, y), 2)

    def _draw_shafts(self, screen, game):
        """Gold light shafts around each lit flare lamp, and glints on the wet ground."""
        k = self.lighting.sight_scale
        shafts, lamps = [], []
        for x, y, r, kind in game.light_sources():
            if kind == "light":
                sx, sy = world_to_screen(x, y - LAMP_LIFT)
                shafts.append((sx, sy, r * k * 0.95))
                lamps.append((x, y, r * k))
        self.lighting.render_shafts(screen, shafts, self.time)
        if self.lighting.alpha < 40:
            return
        rng = random.Random(int(self.time / 0.14) * 31 + 7)          # glints re-roll a few times a second
        for x, y, r in lamps:
            for _ in range(11):
                a, d = rng.uniform(0, math.tau), r * math.sqrt(rng.random()) * 0.85
                px, py = world_to_screen(x + math.cos(a) * d, y + math.sin(a) * d * 0.8)
                if rng.random() < 0.6:
                    pygame.draw.circle(screen, P.mix("amber_hot", "amber", rng.random()), (px, py), 1)

    def _draw_contacts(self, screen, game):
        """Faint rings where a hidden enemy was last seen. They fade as the contact goes stale."""
        ttl = game.map.visibility.contact_ttl
        for c in game.contacts:
            fade = max(0.0, 1 - c.age / ttl)
            surf = pygame.Surface((22, 22), pygame.SRCALPHA)
            col = (*P.color("paper"), int(150 * fade))
            pygame.draw.circle(surf, col, (11, 11), 9, 2)
            pygame.draw.circle(surf, col, (11, 11), 2)
            screen.blit(surf, (c.x - 11, c.y + HUD_H - 11))
