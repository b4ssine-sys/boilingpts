import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pygame

import palette as P
from lighting import GLOW_LEVELS, MIN_ALPHA, SIGHT_STRENGTH, Light, Lighting

GREY = (200, 200, 200)


class LightingTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init()
        pygame.display.set_mode((800, 640))
        self.screen = pygame.Surface((800, 640))
        self.screen.fill(GREY)

    def tearDown(self):
        pygame.quit()

    def settle(self, light, tod):
        light.set_time_of_day(tod, 1.0)
        for _ in range(600):
            light.update(1 / 60)

    def darkness(self, light, lights, point):
        self.screen.fill(GREY)
        light.render(self.screen, lights, 40)
        return GREY[0] - self.screen.get_at(point)[0]

    def test_daylight_draws_nothing(self):
        light = Lighting((800, 600))
        self.assertFalse(light.active)
        self.screen.fill(GREY)
        light.render(self.screen, [Light(400, 340, 100, 1.0, True, True)], 40)
        self.assertEqual(self.screen.get_at((400, 340))[:3], GREY)

    def test_night_darkens_the_field_and_a_light_clears_a_pool(self):
        light = Lighting((800, 600))
        self.settle(light, "dark")
        lights = [Light(400, 340, 120, 1.0, False, False)]
        self.assertGreater(self.darkness(light, lights, (20, 620)), 80)
        self.assertLess(self.darkness(light, lights, (400, 340)), 12)

    def test_steady_and_moving_lights_draw_identically(self):
        a, b = Lighting((800, 600)), Lighting((800, 600))
        self.settle(a, "dark")
        self.settle(b, "dark")
        steady = self.darkness(a, [Light(300, 300, 150, SIGHT_STRENGTH, False, True)], (330, 320))
        moving = self.darkness(b, [Light(300, 300, 150, SIGHT_STRENGTH, False, False)], (330, 320))
        self.assertEqual(steady, moving)

    def test_strength_below_one_leaves_some_darkness(self):
        light = Lighting((800, 600))
        self.settle(light, "dark")
        full = self.darkness(light, [Light(400, 340, 120, 1.0, False, False)], (400, 340))
        part = self.darkness(light, [Light(400, 340, 120, 0.6, False, False)], (400, 340))
        self.assertEqual(full, 0)           # a flare clears the dark completely
        self.assertGreater(part, 10)        # a sight pool leaves a little behind

    def test_every_time_of_day_renders(self):
        for tod in P.TINTS:
            light = Lighting((800, 600))
            self.settle(light, tod)
            light.render(self.screen, [Light(300, 300, 100, 1.0, True, True)], 40)

    def test_darker_times_darken_more(self):
        results = {}
        for tod in ("dusk", "dawn", "dark"):
            light = Lighting((800, 600))
            self.settle(light, tod)
            results[tod] = self.darkness(light, [], (20, 620))
        self.assertLess(results["dawn"], results["dusk"])
        self.assertLess(results["dusk"], results["dark"])

    def test_transition_takes_about_three_seconds_and_never_jumps(self):
        light = Lighting((800, 600))
        light.set_time_of_day("dark", 1.0)
        target = P.TINTS["dark"][1]
        prev, steps = 0.0, []
        for i in range(60 * 6):
            light.update(1 / 60)
            self.assertLessEqual(light.alpha - prev, target * 0.03)   # smooth, no jump
            prev = light.alpha
            steps.append(prev)
        self.assertLess(steps[60 * 1 - 1], target * 0.7)              # not instant
        self.assertGreater(steps[60 * 3 - 1], target * 0.9)           # mostly there in 3 s
        self.assertGreater(steps[-1], target * 0.99)

    def test_sight_scale_is_smoothed_and_daylight_keeps_it_at_one(self):
        light = Lighting((800, 600))
        light.set_time_of_day("dusk", 2.0)
        light.update(1 / 60)
        self.assertTrue(1.0 < light.sight_scale < 1.1)
        for _ in range(600):
            light.update(1 / 60)
        self.assertAlmostEqual(light.sight_scale, 2.0, places=1)
        light.set_time_of_day("day", 0)
        for _ in range(600):
            light.update(1 / 60)
        self.assertAlmostEqual(light.sight_scale, 1.0, places=1)
        self.assertLess(light.alpha, MIN_ALPHA)

    def test_cached_layer_survives_flicker_and_rebuilds_on_change(self):
        light = Lighting((800, 600))
        self.settle(light, "dark")
        steady = [Light(200, 200, 105, SIGHT_STRENGTH, False, True)]
        light.render(self.screen, steady + [Light(500, 300, 170, 1.0, True, False)], 40)
        sig = light._sig
        light.render(self.screen, steady + [Light(500, 300, 181, 1.0, True, False)], 40)  # flicker
        self.assertEqual(light._sig, sig)
        light.render(self.screen, steady + [Light(300, 300, 105, SIGHT_STRENGTH, False, True)], 40)  # tower built
        self.assertNotEqual(light._sig, sig)

    def test_prewarm_covers_a_full_session_of_radii(self):
        light = Lighting((800, 600))
        light.prewarm()
        n_punch, n_glow = len(light.cache._punch), len(light.cache._glow)
        self.settle(light, "dark")
        for r in range(40, 372, 3):                   # sweep radii the way a transition does
            light.render(self.screen, [Light(300, 300, r, 1.0, True, False),
                                       Light(500, 300, min(r, 230), SIGHT_STRENGTH, False, True)], 40)
        self.assertEqual((len(light.cache._punch), len(light.cache._glow)), (n_punch, n_glow))

    def test_glow_levels_are_ordered_and_only_tint(self):
        light = Lighting((800, 600))
        c = light.cache
        centres = [c.glow(160, lv).get_at((160, 160)) for lv in GLOW_LEVELS]
        alphas = [p.a for p in centres]
        self.assertEqual(alphas, sorted(alphas))
        self.assertLess(alphas[-1], 160)            # a wash, never opaque
        self.assertEqual(centres[-1][:3], P.color("amber"))


if __name__ == "__main__":
    unittest.main()
