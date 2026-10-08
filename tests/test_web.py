import ast
import asyncio
import inspect
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import pygame

import build_web
import main
from assets import Assets
from content import CONTENT
from lighting import GradientCache, Lighting
from render import Renderer, screen_size
from sim import Game
from strings import Strings

RUNTIME_MODULES = {"main.py", "art.py", "assets.py", "audio.py", "content.py", "defs.py", "fx.py", "layout.py",
                   "lighting.py", "mapart.py", "palette.py", "render.py", "sim.py", "strings.py", "ui.py"}


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


class StagingTests(unittest.TestCase):
    def test_import_closure_is_exactly_the_runtime_modules(self):
        self.assertEqual(build_web.local_imports(), RUNTIME_MODULES)

    def test_every_top_level_module_is_either_shipped_or_deliberately_left_out(self):
        on_disk = {f for f in os.listdir(ROOT) if f.endswith(".py")}
        self.assertEqual(on_disk - RUNTIME_MODULES, set(), "a module is not reachable from main.py")

    def test_stage_ships_the_game_and_leaves_out_everything_else(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = build_web.stage(os.path.join(tmp, "game"))
        names = set(files)
        self.assertLessEqual(RUNTIME_MODULES | {"strings.json"}, names)
        for font in ("assets/fonts/log.ttf", "assets/fonts/label.ttf", "assets/fonts/LICENSE-DejaVu.txt"):
            self.assertIn(font, names)
        for f in names:
            self.assertFalse(f.startswith(("tests/", "spikes/", "scripts/", "build/", "public/")), f)
            self.assertFalse(f.endswith((".md", ".pyc", ".gitkeep")), f)
            self.assertNotIn("__pycache__", f)

    def test_staging_is_repeatable_and_clears_old_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "game")
            build_web.stage(dest)
            open(os.path.join(dest, "stale.py"), "w").close()
            files = build_web.stage(dest)
            self.assertNotIn("stale.py", files)

    def test_the_staged_copy_runs_on_its_own_in_web_mode(self):
        """Nothing from the repo may leak in: run the staged folder alone in a fresh interpreter."""
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "game")
            build_web.stage(dest)
            code = ("import asyncio, main; asyncio.run(main.main(frames=45, web=True)); print('ok')")
            r = subprocess.run([sys.executable, "-c", code], cwd=dest, capture_output=True, text=True, timeout=120,
                               env={**os.environ, "PYTHONPATH": ""})
        self.assertIn("ok", r.stdout, r.stderr[-800:])

    def test_runtime_code_never_exits_the_interpreter_or_blocks_on_input(self):
        for name in RUNTIME_MODULES:
            tree = ast.parse(read(name))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    f = node.func
                    dotted = f"{getattr(getattr(f, 'value', None), 'id', '')}.{getattr(f, 'attr', '')}"
                    self.assertNotIn(dotted, ("sys.exit",), f"{name} exits the interpreter")
                    self.assertNotEqual(getattr(f, "id", ""), "input", f"{name} blocks on input")


class DeployConfigTests(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads(read("vercel.json"))

    def test_vercel_serves_the_static_build_not_a_python_app(self):
        self.assertIsNone(self.cfg["framework"])
        self.assertEqual(self.cfg["outputDirectory"], "public")
        self.assertEqual(self.cfg["outputDirectory"], os.path.basename(build_web.OUT_DIR))

    def test_build_and_install_commands_point_at_files_that_exist(self):
        self.assertIn("scripts/build_web.py", self.cfg["buildCommand"])
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "scripts", "build_web.py")))
        self.assertIn("requirements-web.txt", self.cfg["installCommand"])
        self.assertTrue(os.path.isfile(os.path.join(ROOT, "requirements-web.txt")))

    def test_the_build_tool_is_pinned(self):
        self.assertRegex(read("requirements-web.txt"), r"(?m)^pygbag==\d+\.\d+\.\d+$")

    def test_build_output_is_not_committed_and_tests_are_not_uploaded(self):
        ignore = read(".gitignore").split()
        self.assertIn("build/", ignore)
        self.assertIn("public/", ignore)
        self.assertIn("tests/", read(".vercelignore").split())

    def test_the_page_title_matches_the_desktop_window(self):
        self.assertEqual(build_web.TITLE, "Tower Defense")        # no working title is locked yet

    def test_a_deploy_guide_exists_and_states_what_is_unverified(self):
        text = read("DEPLOY.md")
        self.assertIn("vercel", text.lower())
        self.assertIn("not tested", text.lower())


class BrowserModeTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init()
        pygame.font.init()

    def tearDown(self):
        pygame.quit()

    def test_main_is_async_and_importing_it_does_not_start_the_game(self):
        self.assertTrue(inspect.iscoroutinefunction(main.main))
        self.assertFalse(main.WEB)

    def test_the_game_loop_runs_headless_in_both_modes(self):
        for web in (False, True):
            asyncio.run(main.main(frames=30, web=web))
            pygame.display.init()
            pygame.font.init()

    def test_web_quality_is_lighter_and_drops_the_shafts(self):
        g = Game(CONTENT, "firebase")
        pygame.display.set_mode(screen_size(g.map))
        hi = Renderer(Strings.load(), Assets(), g.map, g, quality="high")
        web = Renderer(Strings.load(), Assets(), g.map, g, quality="web")
        self.assertEqual((hi.lighting.scale, hi.lighting.shafts, len(hi.rain.drops)), (0.5, True, 420))
        self.assertEqual((web.lighting.scale, web.lighting.shafts, len(web.rain.drops)), (0.25, False, 180))
        self.assertEqual(len(web.lighting.cache._rays), 0)          # shaft sprites are never built
        self.assertGreater(len(hi.lighting.cache._rays), 0)

    def test_light_sprite_caches_stay_small_enough_for_a_browser_tab(self):
        pygame.display.set_mode((800, 720))
        light = Lighting((800, 600))
        light.prewarm()
        c = light.cache
        total = sum(s.get_width() * s.get_height() * 4 for d in (c._punch, c._glow, c._rays, c._fall) for s in d.values())
        self.assertLess(total / 1e6, 70, "light caches are too big")

    def test_dim_glow_levels_are_built_on_demand_not_at_load(self):
        pygame.display.set_mode((800, 720))
        light = Lighting((800, 600))
        light.prewarm()
        self.assertTrue(all(level == 1.0 for _, level in light.cache._glow))
        light.cache.glow(170, 0.5)
        self.assertIn((light.cache.glow_bucket(170), 0.5), light.cache._glow)

    def test_glow_never_undersizes_its_light(self):
        for r in range(8, 400, 7):
            self.assertGreaterEqual(GradientCache.glow_bucket(r), r - 4)

    def test_fonts_are_bundled_so_the_browser_needs_no_system_fonts(self):
        root = os.path.join(ROOT, "assets", "fonts")
        for name in ("log.ttf", "label.ttf", "LICENSE-DejaVu.txt"):
            self.assertTrue(os.path.isfile(os.path.join(root, name)), name)
        a = Assets()
        for role in ("log", "label"):
            self.assertGreater(a.font(role, 16).size("Machine gun nest")[0], 40)
        with tempfile.TemporaryDirectory() as empty:                  # and the fallback still works without them
            self.assertGreater(Assets(empty).font("log", 16).size("abc")[0], 5)

    def test_loading_text_comes_from_the_strings_table(self):
        self.assertTrue(Strings.load().get("load.text"))


if __name__ == "__main__":
    unittest.main()
