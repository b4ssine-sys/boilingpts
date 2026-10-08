"""Tower defense vertical slice (working title).

Click a tile to build the selected position (costs Supply Points). Machine gun
nests, mortar pits and flare towers go on open ground; claymore lines go on the
trail. Hold the firebase through all waves.

Keys: 1-4 select position, SPACE call the next wave early, R restart, ESC quit.

Layout:
    defs.py      content dataclasses (TowerDef, EnemyDef, WaveDef, MapDef)
    content.py   the numbers designers tune
    strings.json every player-facing line, edited without touching code
    sim.py       simulation, no pygame
    palette.py   every colour token
    assets.py    sprites and fonts by key, with drawn fallbacks
    mapart.py    bakes the static field-map background
    lighting.py  darkness overlay and light glows
    render.py    drawing, no state changes
"""
import sys

import pygame

from assets import Assets
from content import CONTENT
from render import FPS, Renderer, screen_size, screen_to_tile
from sim import Game
from strings import Strings

MAP_KEY = "firebase"
SELECT_KEYS = (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4)


def main():
    pygame.init()
    game = Game(CONTENT, MAP_KEY)
    screen = pygame.display.set_mode(screen_size(game.map))
    pygame.display.set_caption("Tower Defense")
    clock = pygame.time.Clock()
    renderer = Renderer(Strings.load(), Assets(), game.map)
    build_key = game.map.towers[0]

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
                elif event.key in SELECT_KEYS:
                    i = SELECT_KEYS.index(event.key)
                    if i < len(game.map.towers):
                        build_key = game.map.towers[i]
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                col, row = screen_to_tile(event.pos, game.map.tile_size)
                game.try_build(col, row, build_key)
        game.update(dt)
        renderer.update(dt, game)
        renderer.draw(screen, game, build_key, pygame.mouse.get_pos())
        pygame.display.flip()


if __name__ == "__main__":
    main()
