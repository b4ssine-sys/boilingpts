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
import time
import traceback

import pygame

import art
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
SLOW_AFTER = 8.0                        # seconds before the loading screen admits it is slow


def _centered(screen, font, text, color, dy=0):
    img = font.render(text, True, color)
    screen.blit(img, img.get_rect(center=(screen.get_width() // 2, screen.get_height() // 2 + dy)))


def _loading_screen(screen, strings, assets, frac, elapsed=0.0):
    """Title, a progress bar, and a note if it is taking long."""
    screen.fill(P.color("ink"))
    _centered(screen, assets.font("label", 26), strings.get("load.progress", pct=int(frac * 100)), P.color("khaki"), -14)
    bar = pygame.Rect(0, 0, 360, 12)
    bar.center = (screen.get_width() // 2, screen.get_height() // 2 + 20)
    pygame.draw.rect(screen, P.color("jungle_dark"), bar)
    pygame.draw.rect(screen, P.color("amber"), (bar.x, bar.y, int(bar.w * frac), bar.h))
    pygame.draw.rect(screen, P.color("khaki"), bar, 1)
    if elapsed > SLOW_AFTER:
        _centered(screen, assets.font("log", 14), strings.get("load.slow"), P.color("paper_shadow"), 52)
    pygame.display.flip()


async def _load(screen, strings, assets, game, web):
    """Finish building the renderer a little at a time, repainting the bar and handing
    control back to the browser after every step, so the page never looks frozen."""
    renderer = Renderer(strings, assets, game.map, game, quality="web" if web else "high", lazy=True)
    start, shown = time.monotonic(), -1
    for frac in renderer.load_steps():
        _loading_screen(screen, strings, assets, frac, time.monotonic() - start)
        if int(frac * 10) != shown:                       # a line per tenth, for the browser console
            shown = int(frac * 10)
            print(f"loading {shown * 10}% ({time.monotonic() - start:.1f}s)", flush=True)
        pygame.event.pump()
        await asyncio.sleep(0)
    return renderer


async def _show_error(screen, strings, assets, exc, frames):
    """Put a startup or runtime failure on screen. It is already in the console."""
    screen.fill(P.color("ink"))
    _centered(screen, assets.font("label", 26), strings.get("load.error"), P.color("clay"), -30)
    _centered(screen, assets.font("log", 15), f"{type(exc).__name__}: {str(exc)[:80]}", P.color("khaki"), 4)
    _centered(screen, assets.font("log", 14), strings.get("load.error_hint"), P.color("paper_shadow"), 34)
    pygame.display.flip()
    count = 0
    while True:                                           # stay up, answering the window, until closed
        if any(e.type == pygame.QUIT for e in pygame.event.get()):
            return
        await asyncio.sleep(0.1)
        count += 1
        if frames is not None and count >= frames:
            return


async def main(frames=None, web=WEB):
    """Run the game. `frames` stops after that many frames (used by tests)."""
    pygame.init()
    strings = Strings.load()
    game = Game(CONTENT, MAP_KEY)
    screen = pygame.display.set_mode(screen_size(game.map))
    pygame.display.set_caption("Tower Defense")
    assets = Assets()
    supersample = art.SS
    if web:
        art.SS = 2                                        # fewer pixels per sprite: faster to paint
    try:
        _loading_screen(screen, strings, assets, 0.0)
        await asyncio.sleep(0)                            # let the browser paint it before any heavy work
        renderer = await _load(screen, strings, assets, game, web)
        await _play(screen, game, renderer, web, frames)
    except Exception as exc:                              # noqa: BLE001 - show it, do not die silently
        traceback.print_exc()
        await _show_error(screen, strings, assets, exc, frames)
    finally:
        art.SS = supersample
    pygame.quit()


async def _play(screen, game, renderer, web, frames):
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
        await asyncio.sleep(0)                            # yield to the browser every frame
        count += 1
        if frames is not None and count >= frames:
            break


if __name__ == "__main__" or WEB:
    asyncio.run(main())
