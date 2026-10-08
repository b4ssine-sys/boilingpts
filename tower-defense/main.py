"""Tower defense vertical slice (working title).

Click a free tile to build a defensive position (costs Supply Points).
Towers fire on enemies approaching along the trail. Hold the position through
all waves. Press SPACE to call the next wave early, R to restart, ESC to quit.

Layout:
    defs.py      content dataclasses (TowerDef, EnemyDef, WaveDef, MapDef)
    content.py   the numbers designers tune
    strings.json every player-facing line, edited without touching code
    sim.py       simulation, no pygame
    render.py    drawing, no state changes
"""
import sys

import pygame

from content import CONTENT
from render import FPS, Renderer, screen_size, screen_to_tile
from sim import Game
from strings import Strings

MAP_KEY = "prototype"


def main():
    pygame.init()
    game = Game(CONTENT, MAP_KEY)
    screen = pygame.display.set_mode(screen_size(game.map))
    pygame.display.set_caption("Tower Defense")
    clock = pygame.time.Clock()
    renderer = Renderer(Strings.load(), pygame.font.SysFont(None, 26),
                        pygame.font.SysFont(None, 72))
    build_key = game.map.towers[0]  # tower picker arrives with the M2 roster

    while True:
        dt = clock.tick(FPS) / 1000
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    sys.exit()
                elif event.key == pygame.K_SPACE:
                    game.start_wave()
                elif event.key == pygame.K_r:
                    game.reset()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                col, row = screen_to_tile(event.pos, game.map.tile_size)
                game.try_build(col, row, build_key)
        game.update(dt)
        renderer.draw(screen, game, build_key, pygame.mouse.get_pos())
        pygame.display.flip()


if __name__ == "__main__":
    main()
