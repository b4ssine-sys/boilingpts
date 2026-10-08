"""Presentation. Reads simulation state, draws it, never mutates it."""
import pygame

HUD_H = 40
FPS = 60

GRASS = (74, 140, 70)
DIRT = (176, 140, 90)
WHITE = (240, 240, 240)
BLACK = (20, 20, 20)
RED = (200, 50, 50)
GREEN = (60, 200, 80)
BLUE = (70, 110, 220)
YELLOW = (240, 210, 60)


def screen_size(game_map):
    w, h = game_map.world_size
    return w, h + HUD_H


def world_to_screen(x, y):
    return x, y + HUD_H


def screen_to_tile(pos, tile_size):
    x, y = pos
    return int(x // tile_size), int((y - HUD_H) // tile_size)


class Renderer:
    def __init__(self, strings, font, big_font):
        self.strings = strings
        self.font = font
        self.big_font = big_font

    def draw(self, screen, game, build_key, mouse_pos):
        m = game.map
        ts = m.tile_size
        width, height = screen_size(m)
        tdef = game.content.towers[build_key]

        screen.fill(BLACK)
        for r in range(m.rows):
            for c in range(m.cols):
                color = DIRT if (c, r) in game.path_tiles else GRASS
                pygame.draw.rect(screen, color, (c * ts, r * ts + HUD_H, ts, ts))
                pygame.draw.rect(screen, (0, 0, 0, 30), (c * ts, r * ts + HUD_H, ts, ts), 1)

        hc, hr = screen_to_tile(mouse_pos, ts)
        if (0 <= hc < m.cols and 0 <= hr < m.rows and (hc, hr) not in game.path_tiles
                and (hc, hr) not in game.towers):
            cx, cy = world_to_screen(hc * ts + ts / 2, hr * ts + ts / 2)
            ok = game.supply >= tdef.cost
            pygame.draw.circle(screen, WHITE if ok else RED, (cx, cy), tdef.range, 1)

        for t in game.towers.values():
            x, y = world_to_screen(t.x, t.y)
            pygame.draw.rect(screen, BLUE, (x - 14, y - 14, 28, 28), border_radius=4)
            pygame.draw.circle(screen, WHITE, (x, y), 6)
        for e in game.enemies:
            x, y = world_to_screen(e.x, e.y)
            pygame.draw.circle(screen, RED, (x, y), 11)
            w = 24
            pygame.draw.rect(screen, BLACK, (x - w / 2, y - 18, w, 4))
            pygame.draw.rect(screen, GREEN, (x - w / 2, y - 18, w * max(e.hp, 0) / e.max_hp, 4))
        for b in game.bullets:
            pygame.draw.circle(screen, YELLOW, world_to_screen(b.x, b.y), 3)

        self._draw_hud(screen, game, tdef, width)
        if game.state != "playing":
            self._draw_end_card(screen, game.state, width, height)

    def _draw_hud(self, screen, game, tdef, width):
        s = self.strings
        pygame.draw.rect(screen, (30, 30, 40), (0, 0, width, HUD_H))
        can_call = not game.wave_active and game.state == "playing"
        info = s.get(
            "hud.status",
            supply=game.supply, integrity=game.integrity,
            wave=game.wave, total=len(game.map.waves),
            tower=s.get(f"tower.{tdef.key}.name"), cost=tdef.cost,
            hint=s.get("hud.hint_next_wave") if can_call else "",
        )
        screen.blit(self.font.render(info, True, WHITE), (10, 10))

    def _draw_end_card(self, screen, state, width, height):
        s = self.strings
        outcome = "won" if state == "won" else "lost"
        title = self.big_font.render(s.get(f"end.{outcome}.title"), True, YELLOW)
        body = self.font.render(s.get(f"end.{outcome}.body"), True, WHITE)
        sub = self.font.render(s.get("end.restart"), True, WHITE)
        screen.blit(title, title.get_rect(center=(width / 2, height / 2 - 30)))
        screen.blit(body, body.get_rect(center=(width / 2, height / 2 + 10)))
        screen.blit(sub, sub.get_rect(center=(width / 2, height / 2 + 40)))
