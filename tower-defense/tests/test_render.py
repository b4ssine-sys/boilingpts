import os
import re
import sys
import tempfile
import time
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pygame

import palette
from assets import Assets
from content import CONTENT
from mapart import bake_map
from layout import HUD_H, TRAY_H
from render import Renderer, screen_size, screen_to_tile, wrap
from sim import Game
from strings import Strings

ROOT = os.path.join(os.path.dirname(__file__), "..")


class PaletteTests(unittest.TestCase):
    def test_tokens_match_the_reference(self):
        self.assertEqual(palette.color("olive_drab"), (0x6B, 0x6B, 0x3A))
        self.assertEqual(palette.color("amber"), (0xF2, 0xB1, 0x4A))
        self.assertEqual(palette.color("night_tint"), (0x10, 0x16, 0x2A))

    def test_every_time_of_day_has_a_tint(self):
        from defs import TIMES_OF_DAY
        self.assertEqual(set(palette.TINTS), set(TIMES_OF_DAY))

    def test_no_rgb_literals_outside_palette(self):
        rgb = re.compile(r"\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)")
        for name in ("render.py", "mapart.py", "assets.py", "main.py", "sim.py"):
            with open(os.path.join(ROOT, name), encoding="utf-8") as f:
                self.assertIsNone(rgb.search(f.read()), f"{name} hard-codes a colour")


class AssetTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init()
        pygame.font.init()
        pygame.display.set_mode((100, 100))

    def tearDown(self):
        pygame.quit()

    def test_every_content_key_has_a_fallback_sprite(self):
        a = Assets()
        for t in CONTENT.towers:
            self.assertEqual(a.image(f"tower.{t}", 34).get_size(), (34, 34))
        for e in CONTENT.enemies:
            self.assertEqual(a.image(f"enemy.{e}", 28).get_size(), (28, 28))

    def test_unknown_key_does_not_crash(self):
        self.assertEqual(Assets().image("tower.nothing_here", 20).get_size(), (20, 20))

    def test_file_overrides_fallback_and_corrupt_file_falls_back(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "sprites"))
            red = pygame.Surface((8, 8))
            red.fill((255, 0, 0))
            pygame.image.save(red, os.path.join(root, "sprites", "tower.mg_nest.png"))
            with open(os.path.join(root, "sprites", "tower.mortar.png"), "wb") as f:
                f.write(b"not a png")
            a = Assets(root)
            self.assertEqual(a.image("tower.mg_nest", 10).get_at((5, 5))[:3], (255, 0, 0))
            self.assertEqual(a.image("tower.mortar", 10).get_size(), (10, 10))

    def test_rotation_is_cached_by_bucket(self):
        a = Assets()
        self.assertIs(a.rotated("tower.mg_nest", 34, 0.01), a.rotated("tower.mg_nest", 34, 0.02))

    def test_fonts_fall_back_when_no_file(self):
        self.assertIsNotNone(Assets().font("log", 15))
        self.assertIsNotNone(Assets().font("label", 15))


class BakeTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init()
        pygame.font.init()
        pygame.display.set_mode((100, 100))
        self.map = CONTENT.maps["firebase"]

    def tearDown(self):
        pygame.quit()

    def test_bake_is_right_size_fast_and_repeatable(self):
        s, a = Strings.load(), Assets()
        t = time.time()
        one = bake_map(self.map, s, a)
        self.assertLess(time.time() - t, 2.0)
        self.assertEqual(one.get_size(), self.map.world_size)
        two = bake_map(self.map, s, a)
        self.assertEqual(pygame.image.tobytes(one, "RGB"), pygame.image.tobytes(two, "RGB"))

    def test_trail_is_visibly_distinct_from_paper(self):
        surf = bake_map(self.map, Strings.load(), Assets())
        c, r = self.map.paths[0][0]
        on_trail = surf.get_at((int(c * 40 + 6), int(r * 40 + 20)))[:3]
        paper = surf.get_at((200, 560))[:3]
        self.assertNotEqual(on_trail, paper)


class RenderSmokeTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init()
        pygame.font.init()
        self.game = Game(CONTENT, "firebase")
        self.screen = pygame.display.set_mode(screen_size(self.game.map))
        self.renderer = Renderer(Strings.load(), Assets(), self.game.map)

    def tearDown(self):
        pygame.quit()

    def test_screen_and_tile_mapping(self):
        self.assertEqual(screen_size(self.game.map), (800, HUD_H + 600 + TRAY_H))
        self.assertEqual(screen_to_tile((85, HUD_H + 85), 40), (2, 2))

    def test_draws_a_full_run_with_every_tower_and_enemy(self):
        g = self.game
        g.supply = 5000
        for pos, key in [((8, 4), "mg_nest"), ((12, 7), "mortar"), ((13, 5), "claymore"),
                         ((16, 6), "flare"), ((9, 10), "mg_nest")]:
            self.assertTrue(g.try_build(*pos, key))
        for _ in range(len(g.map.waves)):
            g.start_wave()
            for i in range(60 * 40):
                g.update(1 / 60)
                self.renderer.update(1 / 60, g)
                if i % 6 == 0:   # drawing is the slow part; sampling still hits every state
                    self.renderer.draw(self.screen, g, g.map.towers[1], (330, 160))
                if not g.wave_active or g.state != "playing":
                    break
        for state in ("won", "lost"):
            g.state = state
            self.renderer.draw(self.screen, g, "mg_nest", (100, 100))

    def test_unseen_enemies_are_not_drawn_but_contacts_are(self):
        g = self.game
        g.time_of_day = "dark"
        g.start_wave()
        for _ in range(60 * 3):
            g.update(1 / 60)
        self.assertTrue(g.enemies)
        drawn = []
        real = self.renderer.assets.rotated
        self.renderer.assets.rotated = lambda key, *a, **k: (drawn.append(key), real(key, *a, **k))[1]
        for e in g.enemies:
            e.visible = False
        self.renderer.draw(self.screen, g, "mg_nest", (0, 0))
        self.assertFalse([k for k in drawn if k.startswith("enemy.")])
        for e in g.enemies:
            e.visible = True
        self.renderer.draw(self.screen, g, "mg_nest", (0, 0))
        self.assertTrue([k for k in drawn if k.startswith("enemy.")])

    def test_contact_marks_draw_without_error(self):
        from sim import Contact
        g = self.game
        g.contacts = [Contact(300, 200, 0.4, 1.0), Contact(500, 300, 0.6, 3.9)]
        self.renderer.draw(self.screen, g, "mg_nest", (0, 0))

    def test_hud_names_the_time_of_day(self):
        s = self.renderer.strings
        for tod in ("day", "dusk", "dark", "dawn"):
            self.assertTrue(s.get(f"time.{tod}"))

    def test_wrap_respects_width(self):
        f = self.renderer._ensure_hud(self.game).f_body
        for line in wrap(f, s := Strings.load().get("map.firebase.context"), 520):
            self.assertLessEqual(f.size(line)[0], 520)
        self.assertEqual(" ".join(wrap(f, s, 520)), s)


if __name__ == "__main__":
    unittest.main()
