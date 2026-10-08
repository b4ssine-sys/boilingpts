import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "spikes"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pygame

import palette as P
import lighting_spike as L


class OverlayTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init()
        pygame.display.set_mode((800, 640))
        self.screen = pygame.Surface((800, 640))
        self.screen.fill((200, 200, 200))

    def tearDown(self):
        pygame.quit()

    def darkness_at(self, mode, lights, point):
        ov = L.Overlay((800, 600), mode, P.TINTS["dark"])
        self.screen.fill((200, 200, 200))
        ov.render(self.screen, lights, 40)
        return 200 - self.screen.get_at(point)[0]  # how much the pixel was darkened

    def test_every_mode_lights_the_centre_and_darkens_the_corner(self):
        light = [(400, 340, 120, 1.0, False, False)]
        for mode in ("full", "half", "half_fast", "quarter", "half_static", "quarter_static"):
            lit = self.darkness_at(mode, light, (400, 340))
            dark = self.darkness_at(mode, light, (20, 620))
            self.assertLess(lit, 12, mode)       # light pool: nearly untouched
            self.assertGreater(dark, 80, mode)   # far from any light: clearly darkened

    def test_modes_agree_on_the_picture(self):
        light = [(300, 300, 150, 1.0, False, False), (560, 420, 100, 0.8, False, True)]
        ref = self.darkness_at("full", light, (330, 320))
        for mode in ("half", "quarter", "half_static", "quarter_static"):
            self.assertAlmostEqual(self.darkness_at(mode, light, (330, 320)), ref, delta=14, msg=mode)

    def test_static_layer_is_rebuilt_only_when_steady_lights_change(self):
        ov = L.Overlay((800, 600), "half_static", P.TINTS["dark"])
        steady = [(200, 200, 105, 0.8, False, True)]
        flare = lambda r: [(500, 300, r, 1.0, True, False)]
        ov.render(self.screen, steady + flare(170), 40)
        built = ov._layer
        ov.render(self.screen, steady + flare(178), 40)   # a flare flickered
        self.assertIs(ov._layer, built)
        ov.render(self.screen, steady + [(300, 300, 105, 0.8, False, True)], 40)  # tower built
        self.assertIsNot(ov._layer, built)

    def test_flicker_keeps_the_sprite_cache_small(self):
        c = L.GradientCache()
        for i in range(200):
            c.punch(170 + 10 * (i % 7 - 3) / 3)
        self.assertLessEqual(len(c._punch), 4)

    def test_every_time_of_day_gives_a_valid_tint(self):
        for tod, tint in P.TINTS.items():
            ov = L.Overlay((800, 600), "half_static", tint)
            ov.render(self.screen, [], 40)


if __name__ == "__main__":
    unittest.main()
