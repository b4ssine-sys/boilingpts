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
        rgb = re.compile(r"(?<![\w])\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*\)")
        for name in ("render.py", "mapart.py", "assets.py", "main.py", "sim.py", "art.py", "fx.py",
                     "lighting.py", "ui.py"):
            with open(os.path.join(ROOT, name), encoding="utf-8") as f:
                self.assertIsNone(rgb.search(f.read()), f"{name} hard-codes a colour")


class AssetTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init()
        pygame.font.init()
        pygame.display.set_mode((100, 100))

    def tearDown(self):
        pygame.quit()

    def test_every_content_key_has_painted_art(self):
        a = Assets()
        for key, t in CONTENT.towers.items():
            self.assertTrue(a.has(f"tower.{key}.base"), key)
            if t.kind == "turret":
                self.assertTrue(a.has(f"tower.{key}.gun"), key)
        for key in CONTENT.enemies:
            for frame in (0, 1):
                self.assertTrue(a.has(f"enemy.{key}.{frame}"), (key, frame))

    def test_painted_sprites_are_not_blank(self):
        a = Assets()
        for key in ("tower.mg_nest.base", "tower.mg_nest.gun", "tower.mortar.base", "tower.claymore.base",
                    "tower.flare.base", "enemy.scout.0", "enemy.infantry.1", "enemy.sapper.0"):
            r = a.sprite(key).get_bounding_rect()
            self.assertGreater(r.w * r.h, 150, key)

    def test_unknown_key_does_not_crash(self):
        self.assertFalse(Assets().has("tower.nothing_here"))
        self.assertGreater(Assets().sprite("tower.nothing_here").get_width(), 0)

    def test_file_overrides_painting_and_corrupt_file_falls_back(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "sprites"))
            red = pygame.Surface((8, 8))
            red.fill((255, 0, 0))
            pygame.image.save(red, os.path.join(root, "sprites", "tower.mg_nest.base.png"))
            with open(os.path.join(root, "sprites", "tower.mortar.base.png"), "wb") as f:
                f.write(b"not a png")
            a = Assets(root)
            self.assertEqual(a.sprite("tower.mg_nest.base").get_size(), (8, 8))
            self.assertEqual(a.sprite("tower.mg_nest.base").get_at((3, 3))[:3], (255, 0, 0))
            self.assertEqual(a.sprite("tower.mortar.base").get_size(), (60, 60))     # painted instead

    def test_rotation_is_cached_by_bucket(self):
        a = Assets()
        self.assertIs(a.rotated("tower.mg_nest.gun", 0.01), a.rotated("tower.mg_nest.gun", 0.02))
        self.assertIsNot(a.rotated("tower.mg_nest.gun", 0.0), a.rotated("tower.mg_nest.gun", 1.5))

    def test_flipping_mirrors_and_caches(self):
        a = Assets()
        k = "enemy.infantry.0"
        plain, mirrored = a.flipped(k, 1.0, False), a.flipped(k, 1.0, True)
        self.assertIs(a.flipped(k, 1.0, True), mirrored)
        self.assertEqual(plain.get_size(), mirrored.get_size())
        self.assertEqual(plain.get_at((10, 20)), mirrored.get_at((plain.get_width() - 11, 20)))

    def test_card_icons_fit_the_card(self):
        a = Assets()
        for key in CONTENT.towers:
            icon = a.icon(key, 40, 54)
            self.assertLessEqual(icon.get_height(), 40)
            self.assertLessEqual(icon.get_width(), 54, key)
            self.assertGreater(icon.get_height(), 20, key)

    def test_composed_tower_includes_gun_and_front_wall(self):
        a = Assets()
        plain = a.scaled("tower.mg_nest.base", 1.0)
        full = a.composed("mg_nest", 1.0)
        self.assertEqual(full.get_size(), plain.get_size())
        self.assertNotEqual(pygame.image.tobytes(full, "RGBA"), pygame.image.tobytes(plain, "RGBA"))

    def test_prewarm_builds_everything_the_renderer_will_ask_for(self):
        a = Assets()
        a.prewarm(1.25, 1.3)
        n = (len(a._scaled), len(a._rotated))
        a.flipped("enemy.scout.1", 1.3, True)
        a.rotated("tower.mortar.gun", 2.0, 1.25)
        a.scaled("tower.flare.base", 1.25)
        self.assertEqual((len(a._scaled), len(a._rotated)), n)

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
        self.assertLess(time.time() - t, 3.0)
        self.assertEqual(one.get_size(), self.map.world_size)
        two = bake_map(self.map, s, a)
        self.assertEqual(pygame.image.tobytes(one, "RGB"), pygame.image.tobytes(two, "RGB"))

    def test_trail_reads_as_mud_and_the_firebase_as_hard_ground(self):
        surf = bake_map(self.map, Strings.load(), Assets())

        def mean(rect):
            sub = surf.subsurface(rect)
            return tuple(sum(c) / (rect[2] * rect[3]) for c in zip(*[sub.get_at((x, y))[:3]
                         for x in range(rect[2]) for y in range(rect[3])]))
        trail = mean((60, 90, 40, 12))             # along the north trail
        jungle = mean((120, 300, 40, 12))          # deep jungle between the trails
        yard = mean((730, 255, 30, 10))            # gravel inside the firebase walls
        self.assertGreater(trail[0] - trail[1], 8)         # brown: red well above green
        self.assertGreater(jungle[1] - jungle[0], 8)       # green
        self.assertGreater(sum(yard), sum(jungle) + 90)    # the compound is a pale clearing

    def test_the_base_is_marked_by_a_bunker_and_nothing_green_grows_there(self):
        surf = bake_map(self.map, Strings.load(), Assets())
        gx, gy = self.map.base[0] * 40 + 20, self.map.base[1] * 40 + 20
        greys = sum(1 for dx in range(-30, 30, 3) for dy in range(-30, 30, 3)
                    if max(surf.get_at((gx + dx, gy + dy))[:3]) - min(surf.get_at((gx + dx, gy + dy))[:3]) < 22)
        self.assertGreater(greys, 150)             # mostly neutral concrete and gravel


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
        real = self.renderer.assets.flipped
        self.renderer.assets.flipped = lambda key, *a, **k: (drawn.append(key), real(key, *a, **k))[1]
        for e in g.enemies:
            e.visible = False
        self.renderer.draw(self.screen, g, "mg_nest", (0, 0))
        self.assertFalse([k for k in drawn if k.startswith("enemy.")])
        for e in g.enemies:
            e.visible = True
        self.renderer.draw(self.screen, g, "mg_nest", (0, 0))
        self.assertTrue([k for k in drawn if k.startswith("enemy.")])

    def test_illegal_tiles_show_a_red_ghost_and_legal_ones_do_not(self):
        import palette as P
        g = self.game
        ts = g.map.tile_size

        def red_pixels(col, row, key):
            self.screen.fill(P.color("ink"))
            self.renderer.draw(self.screen, g, key, (col * ts + 20, 40 + row * ts + 20))
            x, y = col * ts, 40 + row * ts
            return sum(self.screen.get_at((x + i, y + 1))[:3] == P.color("clay") for i in range(ts))
        self.assertGreater(red_pixels(0, 2, "mg_nest"), 20)       # ground tower on the trail
        self.assertGreater(red_pixels(5, 5, "claymore"), 20)      # trail tower off the trail
        self.assertEqual(red_pixels(5, 5, "mg_nest"), 0)          # legal and affordable: amber, not red

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
