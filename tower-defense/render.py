"""Presentation. Reads simulation state, draws it, never mutates it."""
import math

import pygame

import palette as P
from lighting import SIGHT_STRENGTH, Light, Lighting
from mapart import bake_map

HUD_H = 40
FPS = 60
TOWER_PX = 34
ENEMY_PX = 28
EFFECT_TTL = 0.45
# Short-lived lights: kind -> (radius, seconds). Muzzle flashes and claymore bursts.
FLASHES = {"muzzle": (46, 0.12), "claymore": (120, 0.35)}


def screen_size(game_map):
    w, h = game_map.world_size
    return w, h + HUD_H


def world_to_screen(x, y):
    return x, y + HUD_H


def screen_to_tile(pos, tile_size):
    x, y = pos
    return int(x // tile_size), int((y - HUD_H) // tile_size)


def wrap(font, text, width):
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if font.size(trial)[0] <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + [cur] if cur else lines


class Renderer:
    def __init__(self, strings, assets, game_map):
        self.strings = strings
        self.assets = assets
        self.map = game_map
        self.background = bake_map(game_map, strings, assets)  # static, drawn once
        self.f_hud = assets.font("label", 15)
        self.f_hud2 = assets.font("log", 15)
        self.f_title = assets.font("label", 54)
        self.f_body = assets.font("log", 18)
        self.effects = []     # [kind, x, y, radius, age]
        self.flashes = []     # [x, y, radius, ttl, age]
        self._heading = {}    # id(enemy) -> last angle
        w, h = game_map.world_size
        self.lighting = Lighting((w, h))
        self.lighting.prewarm()
        self.time = 0.0       # drives flare flicker; presentation only

    # ---- per-frame bookkeeping ----
    def update(self, dt, game):
        self.time += dt
        self.lighting.set_time_of_day(game.time_of_day, game.time_rule.sight_scale)
        self.lighting.update(dt)
        for kind, x, y, radius in game.events:
            if kind in FLASHES:
                r, ttl = FLASHES[kind]
                self.flashes.append([x, y, r, ttl, 0.0])
            if kind != "muzzle":
                self.effects.append([kind, x, y, radius, 0.0])
        for fx in self.effects:
            fx[4] += dt
        self.effects = [fx for fx in self.effects if fx[4] < EFFECT_TTL]
        for fl in self.flashes:
            fl[4] += dt
        self.flashes = [fl for fl in self.flashes if fl[4] < fl[3]]

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

    def draw(self, screen, game, build_key, mouse_pos):
        m = game.map
        ts = m.tile_size
        width, height = screen_size(m)
        tdef = game.content.towers[build_key]

        screen.fill(P.color("ink"))
        screen.blit(self.background, (0, HUD_H))
        self._draw_towers(screen, game)
        self._draw_enemies(screen, game)
        for b in game.bullets:
            pygame.draw.circle(screen, P.color("amber_hot"), world_to_screen(b.x, b.y), 3)
        for sh in game.shells:
            x, y = world_to_screen(sh.x, sh.y)
            pygame.draw.circle(screen, P.color("ink"), (x, y), 4)
            pygame.draw.circle(screen, P.color("amber"), (x, y), 4, 1)
        self._draw_effects(screen)
        self.lighting.render(screen, self._lights(game), HUD_H)
        self._draw_contacts(screen, game)
        self._draw_hover(screen, game, tdef, mouse_pos)
        self._draw_hud(screen, game, tdef, width)
        if game.state != "playing":
            self._draw_end_card(screen, game, width, height)

    # ---- layers ----
    def _draw_hover(self, screen, game, tdef, mouse_pos):
        ts = game.map.tile_size
        hc, hr = screen_to_tile(mouse_pos, ts)
        if not game.placement_ok(hc, hr, tdef.key):
            return
        ok = game.supply >= tdef.cost
        col = P.color("amber") if ok else P.color("clay")
        cx, cy = world_to_screen(hc * ts + ts / 2, hr * ts + ts / 2)
        pygame.draw.rect(screen, col, (hc * ts, hr * ts + HUD_H, ts, ts), 2)
        if tdef.range:
            pygame.draw.circle(screen, col, (cx, cy), tdef.range, 1)
        if tdef.min_range:  # blind zone
            pygame.draw.circle(screen, P.color("clay"), (cx, cy), tdef.min_range, 1)
        if tdef.light_radius:
            pygame.draw.circle(screen, P.color("amber_hot"), (cx, cy),
                               tdef.light_radius * self.lighting.sight_scale, 1)

    def _draw_towers(self, screen, game):
        for t in game.towers.values():
            x, y = world_to_screen(t.x, t.y)
            key = f"tower.{t.defn.key}"
            if t.defn.kind == "turret":
                img = self.assets.rotated(key, TOWER_PX, t.aim)
            else:
                img = self.assets.image(key, TOWER_PX)
            screen.blit(img, img.get_rect(center=(x, y)))
            if t.hp < t.max_hp:
                self._bar(screen, x, y - 24, 26, t.hp / t.max_hp)

    def _draw_enemies(self, screen, game):
        seen = set()
        for e in game.enemies:
            seen.add(id(e))
            if not e.visible:
                continue  # in the dark; only a contact mark may show where it was
            x, y = world_to_screen(e.x, e.y)
            tgt = e.tower_target or None
            if tgt is not None:
                ang = math.atan2(tgt.y - e.y, tgt.x - e.x)
            else:
                ang = self._path_heading(e)
            self._heading[id(e)] = ang
            shadow = pygame.Rect(0, 0, 20, 10)
            shadow.center = (x + 2, y + 6)
            pygame.draw.ellipse(screen, P.mix("paper", "ink", 0.35), shadow)
            img = self.assets.rotated(f"enemy.{e.defn.key}", ENEMY_PX, ang)
            screen.blit(img, img.get_rect(center=(x, y)))
            if e.hp < e.max_hp:
                self._bar(screen, x, y - 20, 24, max(e.hp, 0) / e.max_hp)
        for k in [k for k in self._heading if k not in seen]:
            del self._heading[k]

    def _path_heading(self, e):
        if e.target < len(e.waypoints):
            tx, ty = e.waypoints[e.target]
            return math.atan2(ty - e.y, tx - e.x)
        return self._heading.get(id(e), 0.0)

    def _bar(self, screen, x, y, w, frac):
        pygame.draw.rect(screen, P.color("ink"), (x - w / 2 - 1, y - 1, w + 2, 5))
        pygame.draw.rect(screen, P.color("jungle_light"), (x - w / 2, y, w * frac, 3))

    def _draw_effects(self, screen):
        for kind, x, y, radius, age in self.effects:
            t = age / EFFECT_TTL
            r = max(2, int(radius * (0.35 + 0.65 * t)))
            alpha = int(200 * (1 - t))
            surf = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
            tone = {"splash": "khaki", "claymore": "amber", "tower_lost": "clay"}.get(kind, "khaki")
            if kind != "tower_lost":
                pygame.draw.circle(surf, (*P.color(tone), alpha // 3), (r + 2, r + 2), r)
            pygame.draw.circle(surf, (*P.color("amber_hot" if kind == "claymore" else tone), alpha),
                               (r + 2, r + 2), r, 3)
            sx, sy = world_to_screen(x, y)
            screen.blit(surf, (sx - r - 2, sy - r - 2))

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

    def _draw_hud(self, screen, game, tdef, width):
        s = self.strings
        pygame.draw.rect(screen, P.color("ink"), (0, 0, width, HUD_H))
        pygame.draw.line(screen, P.color("clay"), (0, HUD_H - 1), (width, HUD_H - 1))
        can_call = not game.wave_active and game.state == "playing"
        line1 = s.get("hud.line1", supply=game.supply, integrity=game.integrity,
                      wave=game.wave, total=len(game.map.waves),
                      tod=s.get(f"time.{game.time_of_day}"))
        idx = game.map.towers.index(tdef.key) + 1
        line2 = s.get("hud.line2", n=idx, tower=s.get(f"tower.{tdef.key}.name"), cost=tdef.cost,
                      hint=s.get("hud.hint_next_wave" if can_call else "hud.hint_busy"))
        screen.blit(self.f_hud.render(line1, True, P.color("paper")), (10, 4))
        screen.blit(self.f_hud2.render(line2, True, P.color("khaki")), (10, 22))

    def _draw_end_card(self, screen, game, width, height):
        s = self.strings
        outcome = "won" if game.state == "won" else "lost"
        card = pygame.Rect(0, 0, 560, 270)
        card.center = (width / 2, height / 2)
        shadow = card.move(5, 6)
        pygame.draw.rect(screen, P.mix("paper", "ink", 0.6), shadow)
        pygame.draw.rect(screen, P.color("paper"), card)
        pygame.draw.rect(screen, P.color("ink"), card, 2)
        title = self.f_title.render(s.get(f"end.{outcome}.title").upper(), True, P.color("clay"))
        screen.blit(title, title.get_rect(midtop=(card.centerx, card.top + 18)))
        y = card.top + 90
        body = s.get(f"end.{outcome}.body")
        ctx_key = f"map.{game.map.key}.context"
        lines = wrap(self.f_body, body, card.w - 40) + [""] + wrap(self.f_body, s.get(ctx_key), card.w - 40)
        for ln in lines:
            if ln:
                img = self.f_body.render(ln, True, P.color("ink"))
                screen.blit(img, img.get_rect(midtop=(card.centerx, y)))
            y += 22
        sub = self.f_body.render(s.get("end.restart"), True, P.color("olive_drab"))
        screen.blit(sub, sub.get_rect(midbottom=(card.centerx, card.bottom - 12)))
