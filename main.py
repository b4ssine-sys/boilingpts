"""Tower defense vertical slice (working title).

Pick a position from the tray (click it or press 1-4), then click a tile to
build it (costs Supply Points). Machine gun nests, mortar pits and flare towers
go on open ground; claymore lines go on the trail. Hold the firebase through
all waves.

Keys: 1-4 select position, SPACE call the next wave early, R restart, ESC quit.

Runs on the desktop (python main.py) and in the browser (built with pygbag, see
DEPLOY.md). The loop is async so the browser can breathe between frames.

Layout:
    defs.py      content dataclasses (TowerDef, EnemyDef, WaveDef, MapDef)
    content.py   the numbers designers tune
    strings.json every player-facing line, edited without touching code
    sim.py       simulation, no pygame
    palette.py   every colour token
    art.py       paints every sprite, foliage and firebase piece from code
    assets.py    sprites and fonts by key; files override the painting
    mapart.py    bakes the static jungle, roads and firebase once at load
    fx.py        rain, smoke, sparks, muzzle flashes, fading casualties
    lighting.py  darkness overlay and light glows
    ui.py        counters, radio log, build tray, banner, debrief card
    layout.py    screen layout constants
    audio.py     every sound goes through audio.play (silent stub for now)
    render.py    drawing, no state changes
"""
import asyncio
import sys

import pygame

import audio
import palette as P
from assets import Assets
from content import CONTENT
from render import FPS, Renderer, screen_size, screen_to_tile
from sim import Game
from strings import Strings

MAP_KEY = "firebase"
SELECT_KEYS = (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4)
WEB = sys.platform == "emscripten"      # running inside pygbag in a browser


def _loading_screen(screen, strings, assets):
    """Shown while the jungle is painted and the light sprites are built."""
    screen.fill(P.color("ink"))
    font = assets.font("label", 26)
    img = font.render(strings.get("load.text"), True, P.color("khaki"))
    screen.blit(img, img.get_rect(center=screen.get_rect().center))
    pygame.display.flip()


async def main(frames=None, web=WEB):
    """Run the game. `frames` stops after that many frames (used by tests)."""
    pygame.init()
    strings = Strings.load()
    game = Game(CONTENT, MAP_KEY)
    screen = pygame.display.set_mode(screen_size(game.map))
    pygame.display.set_caption("Tower Defense")
    assets = Assets()
    _loading_screen(screen, strings, assets)
    await asyncio.sleep(0)                     # let the browser paint it before the heavy work
    renderer = Renderer(strings, assets, game.map, game, quality="web" if web else "high")
    clock = pygame.time.Clock()
    build_key = game.map.towers[0]
    running, count = True, 0

    while running:
        dt = clock.tick(FPS) / 1000
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE and not web:   # a browser tab is closed by the browser
                    running = False
                elif event.key == pygame.K_SPACE:
                    game.start_wave()
                elif event.key == pygame.K_r:
                    game.reset()
                elif event.key in SELECT_KEYS:
                    i = SELECT_KEYS.index(event.key)
                    if i < len(game.map.towers):
                        build_key = game.map.towers[i]
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                hit = renderer.hit_test(event.pos, game)
                if hit is None:
                    col, row = screen_to_tile(event.pos, game.map.tile_size)
                    if game.try_build(col, row, build_key):
                        audio.play("build")
                elif hit[0] == "card":
                    build_key = hit[1]
                    audio.play("ui_click")
                elif hit[0] == "next_wave":
                    game.start_wave()
                    audio.play("ui_click")
                elif hit[0] == "restart":
                    game.reset()
        game.update(dt)
        renderer.update(dt, game)
        renderer.draw(screen, game, build_key, pygame.mouse.get_pos())
        pygame.display.flip()
        await asyncio.sleep(0)                 # yield to the browser every frame
        count += 1
        if frames is not None and count >= frames:
            break
    pygame.quit()


if __name__ == "__main__" or WEB:
    asyncio.run(main())
