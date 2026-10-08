import asyncio
import contextlib
import io
import os
import sys
import time
import unittest
from unittest import mock

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import pygame

import art
import main
import palette as P
import render
from assets import Assets
from content import CONTENT
from render import Renderer, screen_size
from sim import Game
from strings import Strings


def fresh():
    pygame.display.init()
    pygame.font.init()
    g = Game(CONTENT, "firebase")
    return g, pygame.display.set_mode(screen_size(g.map))


class IncrementalLoadTests(unittest.TestCase):
    def tearDown(self):
        pygame.quit()

    def test_a_lazy_renderer_returns_at_once_and_loads_in_many_small_steps(self):
        g, screen = fresh()
        t = time.perf_counter()
        r = Renderer(Strings.load(), Assets(), g.map, g, quality="web", lazy=True)
        self.assertLess(time.perf_counter() - t, 0.05)            # the constructor does not do the heavy work
        self.assertFalse(r.ready)
        steps, last = [], time.perf_counter()
        for frac in r.load_steps():
            now = time.perf_counter()
            steps.append((frac, now - last))
            last = now
        fracs = [f for f, _ in steps]
        self.assertGreater(len(steps), 60, "loading is too coarse to show progress")
        self.assertEqual(fracs, sorted(fracs))                    # progress never goes backwards
        self.assertEqual((fracs[0], fracs[-1]), (0.0, 1.0))
        total = sum(d for _, d in steps)
        self.assertLess(max(d for _, d in steps), 0.35 * total, "one step dominates the load")
        self.assertTrue(r.ready)
        r.update(1 / 60, g)
        r.draw(screen, g, "mg_nest", (0, 0))

    def test_the_default_constructor_still_finishes_everything(self):
        g, screen = fresh()
        r = Renderer(Strings.load(), Assets(), g.map, g)
        self.assertTrue(r.ready)
        r.draw(screen, g, "mg_nest", (0, 0))

    def test_every_loading_phase_is_incremental(self):
        g, _ = fresh()
        a = Assets()
        from lighting import Lighting
        from mapart import bake_steps, bake_map
        self.assertGreater(sum(1 for _ in bake_steps(g.map, Strings.load(), a)), 15)
        self.assertGreater(sum(1 for _ in Lighting((800, 600)).prewarm_steps()), 20)
        self.assertGreater(sum(1 for _ in Assets().prewarm_steps(1.25, 1.3)), 10)
        surf = bake_map(g.map, Strings.load(), a)                  # the one-shot wrapper still returns the surface
        self.assertEqual(surf.get_size(), g.map.world_size)

    def test_thinner_foliage_for_the_browser_loads_faster(self):
        g, _ = fresh()
        from mapart import _scatter
        import random
        centers = [[(c * 40 + 20, r * 40 + 20) for c, r in p] for p in g.map.paths]
        full = len(_scatter(g.map, centers, random.Random(1), 1.0))
        thin = len(_scatter(g.map, centers, random.Random(1), 0.6))
        self.assertLess(thin, full * 0.85)


class LoadingScreenTests(unittest.TestCase):
    def setUp(self):
        self.g, self.screen = fresh()
        self.strings, self.assets = Strings.load(), Assets()

    def tearDown(self):
        pygame.quit()

    def bar_fill(self):
        y = self.screen.get_height() // 2 + 20
        x0 = self.screen.get_width() // 2 - 180
        amber = P.color("amber")
        return sum(1 for x in range(x0, x0 + 360) if self.screen.get_at((x, y))[:3] == amber)

    def test_the_bar_grows_with_progress(self):
        widths = []
        for frac in (0.0, 0.25, 0.5, 1.0):
            main._loading_screen(self.screen, self.strings, self.assets, frac)
            widths.append(self.bar_fill())
        self.assertEqual(widths, sorted(widths))
        self.assertAlmostEqual(widths[1], 90, delta=3)
        self.assertAlmostEqual(widths[3], 360, delta=3)

    def test_it_says_so_when_loading_is_slow(self):
        main._loading_screen(self.screen, self.strings, self.assets, 0.5, elapsed=1.0)
        quick = pygame.image.tobytes(self.screen, "RGB")
        main._loading_screen(self.screen, self.strings, self.assets, 0.5, elapsed=main.SLOW_AFTER + 1)
        self.assertNotEqual(pygame.image.tobytes(self.screen, "RGB"), quick)

    def test_loading_text_is_in_the_strings_table(self):
        for key in ("load.progress", "load.slow", "load.error", "load.error_hint"):
            self.assertTrue(self.strings.get(key, pct=5) if key == "load.progress" else self.strings.get(key))

    def test_loading_hands_control_back_to_the_browser_often_and_reports_to_the_console(self):
        yields = []
        real = asyncio.sleep

        async def counting(delay, *a, **k):
            yields.append(delay)
            return await real(delay, *a, **k)
        out = io.StringIO()
        with mock.patch.object(main.asyncio, "sleep", counting), contextlib.redirect_stdout(out):
            renderer = asyncio.run(main._load(self.screen, self.strings, self.assets, self.g, True))
        self.assertTrue(renderer.ready)
        self.assertGreater(len(yields), 60)
        self.assertIn("loading 0%", out.getvalue())
        self.assertIn("loading 100%", out.getvalue())


class FailureVisibleTests(unittest.TestCase):
    def tearDown(self):
        pygame.quit()

    def test_a_startup_failure_is_shown_and_logged_not_swallowed(self):
        err = io.StringIO()
        with mock.patch.object(render, "bake_steps", side_effect=RuntimeError("boom")), \
                contextlib.redirect_stderr(err):
            asyncio.run(main.main(frames=3, web=True))              # returns; it does not hang or crash
        self.assertIn("RuntimeError", err.getvalue())
        self.assertIn("boom", err.getvalue())

    def test_the_error_screen_names_the_problem(self):
        g, screen = fresh()
        strings, assets = Strings.load(), Assets()
        asyncio.run(main._show_error(screen, strings, assets, ValueError("bad thing"), frames=2))
        clay = P.color("clay")
        found = any(screen.get_at((x, y))[:3] == clay for x in range(250, 550) for y in range(300, 350))
        self.assertTrue(found, "no error heading on screen")
        ink = P.color("ink")
        detail = any(screen.get_at((x, y))[:3] != ink for x in range(200, 600) for y in range(354, 374))
        self.assertTrue(detail, "the detail line is missing")

    def test_a_failure_in_the_middle_of_play_is_also_shown(self):
        err = io.StringIO()
        with mock.patch.object(Renderer, "update", side_effect=KeyError("late")), contextlib.redirect_stderr(err):
            asyncio.run(main.main(frames=3, web=False))
        self.assertIn("KeyError", err.getvalue())

    def test_the_supersampling_setting_is_restored_even_after_a_failure(self):
        before = art.SS
        with mock.patch.object(render, "bake_steps", side_effect=RuntimeError("x")), \
                contextlib.redirect_stderr(io.StringIO()):
            asyncio.run(main.main(frames=2, web=True))
        self.assertEqual(art.SS, before)

    def test_web_mode_paints_sprites_at_lower_supersampling_while_loading(self):
        seen = []
        real = Renderer.load_steps

        def spy(self):
            seen.append(art.SS)
            return real(self)
        with mock.patch.object(Renderer, "load_steps", spy):
            asyncio.run(main.main(frames=5, web=True))
            asyncio.run(main.main(frames=5, web=False))
        self.assertEqual(seen, [2, 3])


if __name__ == "__main__":
    unittest.main()
