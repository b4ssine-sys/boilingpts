import math
import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pygame

import art
import palette as P
from assets import Assets, REGISTRY
from content import CONTENT


def opaque_pixels(surf):
    return pygame.mask.from_surface(surf, 40).count()


def silhouette(surf):
    return pygame.mask.from_surface(surf, 40)


class ArtTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init()
        pygame.display.set_mode((100, 100))

    def tearDown(self):
        pygame.quit()

    # ---- towers ----
    def test_tower_layers_share_a_canvas_so_they_line_up(self):
        for key in ("mg_nest", "mortar"):
            base, front = art.BASE_BUILDERS[key](), art.FRONT_BUILDERS[key]()
            self.assertEqual(base.get_size(), front.get_size(), key)

    def test_front_wall_does_not_repeat_the_back_wall(self):
        for key in ("mg_nest", "mortar"):
            b = silhouette(art.FRONT_BUILDERS[key]())
            self.assertGreater(b.count(), 150, key)
            self.assertNotEqual(pygame.image.tobytes(art.BASE_BUILDERS[key](), "RGBA"),
                                pygame.image.tobytes(art.FRONT_BUILDERS[key](), "RGBA"), key)
        a, b = silhouette(art.BASE_BUILDERS["mg_nest"]()), silhouette(art.FRONT_BUILDERS["mg_nest"]())
        self.assertGreater(b.count() - a.overlap_area(b, (0, 0)), 100)       # the gun nest's low wall sits in front

    def test_sprites_stand_on_the_shared_ground_anchor(self):
        ax, ay = art.ANCHOR["tower"]
        for key, build in art.BASE_BUILDERS.items():
            s = build()
            r = s.get_bounding_rect()
            self.assertAlmostEqual(r.centerx / s.get_width(), ax, delta=0.12, msg=key)
            self.assertGreater(r.bottom / s.get_height(), ay, key)       # extends below the ground point
        eax, eay = art.ANCHOR["enemy"]
        for key, build in art.ENEMY_BUILDERS.items():
            s = build(0)
            r = s.get_bounding_rect()
            self.assertAlmostEqual(r.centerx / s.get_width(), eax, delta=0.2, msg=key)
            self.assertGreater(r.bottom / s.get_height(), eay - 0.02, key)

    def test_guns_are_drawn_pointing_east_around_their_centre(self):
        for key, build in art.GUN_BUILDERS.items():
            g = build()
            r = g.get_bounding_rect()
            self.assertGreater(r.right - g.get_width() / 2, g.get_width() / 2 - r.left, key)   # barrel to the right
            self.assertAlmostEqual((r.top + r.bottom) / 2, g.get_height() / 2, delta=3, msg=key)

    def test_gun_tip_matches_the_barrel_length(self):
        for key, build in art.GUN_BUILDERS.items():
            g = build()
            reach = g.get_bounding_rect().right - g.get_width() / 2
            self.assertAlmostEqual(art.GUN_TIP[key], reach, delta=4, msg=key)

    def test_the_flare_lamp_is_inside_the_canvas(self):
        s = art.BASE_BUILDERS["flare"]()
        top = s.get_bounding_rect().top
        self.assertGreaterEqual(top, 0)
        found = any(c[0] > 215 and c[1] > 150 and c[2] < 150
                    for c in (s.get_at((x, y)) for x in range(s.get_width()) for y in range(0, 24)))
        self.assertTrue(found, "no amber lamp near the top of the tower")

    # ---- enemies: human figures, one silhouette per type, same treatment as everything else ----
    def test_three_enemy_types_have_distinct_silhouettes(self):
        masks = {k: silhouette(art.ENEMY_BUILDERS[k](0)) for k in art.ENEMY_BUILDERS}
        keys = sorted(masks)
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                inter = masks[a].overlap_area(masks[b], (0, 0))
                union = masks[a].count() + masks[b].count() - inter
                self.assertLess(inter / union, 0.85, f"{a} and {b} are too alike to tell apart")

    def test_walk_frames_differ_but_stay_the_same_figure(self):
        for key, build in art.ENEMY_BUILDERS.items():
            a, b = build(0), build(1)
            self.assertNotEqual(pygame.image.tobytes(a, "RGBA"), pygame.image.tobytes(b, "RGBA"), key)
            ma, mb = silhouette(a), silhouette(b)
            self.assertGreater(ma.overlap_area(mb, (0, 0)) / max(ma.count(), mb.count()), 0.6, key)

    def test_enemies_are_inked_and_readable_against_the_jungle(self):
        ink = P.color("ink")
        jungle = P.color("jungle_dark")
        for key, build in art.ENEMY_BUILDERS.items():
            s = build(0)
            px = [s.get_at((x, y)) for x in range(s.get_width()) for y in range(s.get_height()) if s.get_at((x, y)).a > 200]
            near_ink = sum(1 for p in px if max(abs(p[i] - ink[i]) for i in range(3)) < 40)
            self.assertGreater(near_ink, 12, f"{key}: no dark outline")
            lum = lambda c: 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]
            bright = sum(1 for p in px if lum(p) > lum(jungle) + 25)
            self.assertGreater(bright / len(px), 0.25, f"{key}: disappears into the foliage")

    def test_enemy_and_tower_art_share_one_outline_style(self):
        ink = P.color("ink")
        for s in (art.ENEMY_BUILDERS["infantry"](0), art.BASE_BUILDERS["mg_nest"](), art.GUN_BUILDERS["mortar"]()):
            edge = [s.get_at((x, y)) for x in range(s.get_width()) for y in range(s.get_height())
                    if 0 < s.get_at((x, y)).a < 255 or s.get_at((x, y))[:3] == ink]
            self.assertGreater(len(edge), 40)

    # ---- toolkit ----
    def test_outline_adds_ink_around_a_shape(self):
        pen = art.Pen(20, 20)
        pen.circle(10, 10, 4, "khaki")
        plain, inked = pen.done(0), art.Pen(20, 20)
        inked.circle(10, 10, 4, "khaki")
        inked = inked.done(1.4)
        self.assertGreater(opaque_pixels(inked), opaque_pixels(plain))

    def test_foliage_is_deterministic_by_seed_and_varies_between_seeds(self):
        for kind, fn in art.FOLIAGE.items():
            a, b, c = fn(3), fn(3), fn(4)
            self.assertEqual(pygame.image.tobytes(a, "RGBA"), pygame.image.tobytes(b, "RGBA"), kind)
            if kind != "tuft":
                self.assertNotEqual(pygame.image.tobytes(a, "RGBA"), pygame.image.tobytes(c, "RGBA"), kind)

    def test_firebase_pieces_build(self):
        for s in (art.bunker(), art.sandbag_wall(100), art.sandbag_wall(60, True), art.wire_coil(40),
                  art.wire_stake(), art.barrel(), art.mud_puddle(1)):
            self.assertGreater(opaque_pixels(s), 40)

    def test_every_painted_key_builds(self):
        a = Assets()
        for key in REGISTRY:
            self.assertGreater(a.sprite(key).get_width(), 4, key)

    def test_shade_scales_brightness_and_clamps(self):
        self.assertEqual(P.shade((100, 100, 100), 0.5), (50, 50, 50))
        self.assertEqual(P.shade((200, 200, 200), 2.0), (255, 255, 255))

    def test_a_colour_for_every_token_art_uses(self):
        for t in ("mud", "mud_dark", "concrete", "concrete_dark", "sandbag", "steel", "wood", "wood_dark",
                  "leaf_deep", "leaf_bright", "rain", "cloth_brown", "cloth_green", "skin"):
            P.color(t)


class NoCaricatureTests(unittest.TestCase):
    """The enemy is a human opponent, drawn as one. See ASSETS.md and the content rules."""

    def test_enemy_art_is_registered_as_figures_with_walk_frames_and_nothing_else(self):
        for key in CONTENT.enemies:
            self.assertIn(f"enemy.{key}.0", REGISTRY)
            self.assertIn(f"enemy.{key}.1", REGISTRY)
        self.assertEqual({k for k in REGISTRY if k.startswith("enemy.")},
                         {f"enemy.{e}.{f}" for e in CONTENT.enemies for f in (0, 1)})

    def test_the_art_module_states_the_rule(self):
        self.assertIn("same treatment", art.__doc__)
        self.assertIn("human", art.__doc__)


if __name__ == "__main__":
    unittest.main()
