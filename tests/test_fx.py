import math
import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pygame

import art
import palette as P
from assets import Assets
from content import CONTENT
from fx import Fx, Rain
from lighting import RAY_BUCKET, Light, Lighting
from render import Renderer, TOWER_SCALE, screen_size
from sim import Game, Shell
from strings import Strings

DT = 1 / 60


def settle(fx, seconds):
    for _ in range(int(seconds / DT)):
        fx.update(DT)


class FxTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init()
        pygame.display.set_mode((100, 100))
        self.screen = pygame.Surface((800, 700))

    def tearDown(self):
        pygame.quit()

    def test_muzzle_flash_sits_at_the_barrel_tip_and_is_brief(self):
        fx = Fx()
        fx.muzzle(100, 100, 0.0, 30)
        x, y, angle, age, ttl, size, v = fx.flashes[0]
        self.assertAlmostEqual(x, 130)
        self.assertAlmostEqual(y, 100)
        self.assertLess(ttl, 0.12)
        settle(fx, 0.2)
        self.assertEqual(fx.flashes, [])

    def test_muzzle_flash_follows_the_aim_angle(self):
        fx = Fx()
        fx.muzzle(50, 50, math.pi / 2, 20)
        self.assertAlmostEqual(fx.flashes[0][0], 50, delta=0.01)
        self.assertAlmostEqual(fx.flashes[0][1], 70, delta=0.01)

    def test_everything_expires(self):
        fx = Fx()
        fx.muzzle(10, 10, 0.5, 20)
        fx.mortar_fire(10, 10, 0.5, 15)
        fx.hit(20, 20, 1.0)
        fx.impact(30, 30, 45)
        fx.claymore(40, 40, 50)
        fx.tower_lost(50, 50)
        fx.ghost(pygame.Surface((10, 10), pygame.SRCALPHA), 5, 5)
        self.assertTrue(fx.smoke and fx.sparks and fx.flashes and fx.rings and fx.ghosts)
        settle(fx, 2.5)
        self.assertEqual((fx.smoke, fx.sparks, fx.flashes, fx.rings, fx.ghosts), ([], [], [], [], []))

    def test_smoke_rises_and_fades(self):
        fx = Fx()
        fx.puff(100, 100, 5, 4, rise=20, spread=0)
        y0 = sum(p[1] for p in fx.smoke) / 5
        settle(fx, 0.4)
        self.assertLess(sum(p[1] for p in fx.smoke) / 5, y0)

    def test_sparks_fall_under_gravity(self):
        fx = Fx()
        fx.sparks_at(100, 100, 10, -math.pi / 2, 1.0, spread=0.0)
        vy0 = [s[3] for s in fx.sparks]
        settle(fx, 0.1)
        self.assertTrue(all(s[3] > v for s, v in zip(fx.sparks, vy0)))

    def test_fallen_units_fade_in_grey_with_nothing_graphic(self):
        fx = Fx()
        colour = pygame.Surface((20, 20), pygame.SRCALPHA)
        colour.fill((*P.color("clay"), 255))
        fx.ghost(colour, 50, 50)
        grey = fx.ghosts[0][0].get_at((5, 5))
        self.assertAlmostEqual(grey[0], grey[1], delta=2)          # desaturated
        self.assertAlmostEqual(grey[1], grey[2], delta=2)
        screen = self.screen
        screen.fill(P.color("ink"))
        fx.draw_world(screen, 0)
        early = sum(screen.get_at((x, y))[0] for x in range(40, 60) for y in range(30, 50))
        settle(fx, 0.45)
        screen.fill(P.color("ink"))
        fx.draw_world(screen, 0)
        late = sum(screen.get_at((x, y))[0] for x in range(40, 60) for y in range(30, 50))
        self.assertLess(late, early)                                # it fades away

    def test_effect_randomness_is_separate_from_the_simulation(self):
        g = Game(CONTENT, "firebase", seed=3)
        before = g.rng.getstate()
        fx = Fx()
        fx.impact(10, 10, 40)
        settle(fx, 0.3)
        self.assertEqual(g.rng.getstate(), before)


class RainTests(unittest.TestCase):
    def test_no_rain_by_day_and_more_rain_in_the_dark(self):
        light, heavy = Rain((800, 600)), Rain((800, 600))
        dry = pygame.Surface((800, 600))
        dry.fill(P.color("jungle_dark"))
        ref = pygame.image.tobytes(dry, "RGB")
        light.update(DT, 0.0)
        light.draw(dry, 0)
        self.assertEqual(pygame.image.tobytes(dry, "RGB"), ref)
        counts = {}
        for name, r, k in (("drizzle", light, 0.3), ("downpour", heavy, 1.0)):
            for _ in range(30):
                r.update(DT, k)
            s = pygame.Surface((800, 600))
            s.fill(P.color("jungle_dark"))
            r.draw(s, 0)
            data = pygame.image.tobytes(s, "RGB")
            dry_px = bytes(P.color("jungle_dark"))
            counts[name] = sum(1 for i in range(0, len(data), 3) if data[i:i + 3] != dry_px)
        self.assertGreater(counts["downpour"], counts["drizzle"])

    def test_drops_stay_on_the_map_and_ripples_are_bounded(self):
        r = Rain((800, 600))
        for _ in range(600):
            r.update(DT, 1.0)
        self.assertTrue(all(-100 <= d[0] <= 810 and -50 <= d[1] <= 620 for d in r.drops))
        self.assertLessEqual(len(r.ripples), 27)


class ShaftTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init()
        pygame.display.set_mode((800, 700))
        self.light = Lighting((800, 600))

    def tearDown(self):
        pygame.quit()

    def settle(self, tod):
        self.light.set_time_of_day(tod, 1.0)
        for _ in range(600):
            self.light.update(DT)

    def test_shafts_brighten_the_lit_area_at_night_only(self):
        screen = pygame.Surface((800, 700))
        for tod, expect in (("day", False), ("dark", True)):
            l = Lighting((800, 600))
            l.set_time_of_day(tod, 1.0)
            for _ in range(600):
                l.update(DT)
            screen.fill(P.color("jungle_dark"))
            l.render_shafts(screen, [(400, 300, 170)], 1.0)
            lit = sum(screen.get_at((x, y))[0] for x in range(400, 560, 4) for y in range(260, 340, 4))
            base = P.color("jungle_dark")[0] * 40 * 20
            self.assertEqual(lit > base + 50, expect, tod)

    def test_shaft_sprites_fade_toward_their_tips_and_dim_by_level(self):
        c = self.light.cache
        bright, dim = c.rays(170, 0, 2), c.rays(170, 0, 0)
        w = bright.get_width()
        near = max(bright.get_at((w // 2 + dx, w // 2 + dy))[0] for dx in range(-30, 30) for dy in range(-30, 30))
        far = max(bright.get_at((w - 8, w // 2 + dy))[0] for dy in range(-20, 20))
        self.assertGreater(near, far)
        self.assertGreater(bright.get_at((w // 2 + 20, w // 2))[0] + bright.get_at((w // 2, w // 2 + 20))[0],
                           dim.get_at((w // 2 + 20, w // 2))[0] + dim.get_at((w // 2, w // 2 + 20))[0])

    def test_the_two_phases_are_different_pictures(self):
        c = self.light.cache
        self.assertNotEqual(pygame.image.tobytes(c.rays(170, 0, 2), "RGB"), pygame.image.tobytes(c.rays(170, 1, 2), "RGB"))

    def test_shaft_cache_survives_flicker_after_prewarm(self):
        self.light.prewarm()
        n = {k[:2] for k in self.light.cache._rays}
        self.settle("dark")
        screen = pygame.Surface((800, 700))
        for r in range(150, 372, 3):
            self.light.render_shafts(screen, [(400, 300, r)], r * 0.1)
        self.assertEqual({k[:2] for k in self.light.cache._rays}, n)   # no new sizes; dim levels may appear


class RendererEffectTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init()
        pygame.font.init()
        self.game = Game(CONTENT, "firebase", seed=2)
        self.screen = pygame.display.set_mode(screen_size(self.game.map))
        self.r = Renderer(Strings.load(), Assets(), self.game.map, self.game)

    def tearDown(self):
        pygame.quit()

    def feed(self, *events):
        self.game.events = list(events)
        self.r.update(DT, self.game)

    def test_gun_fire_makes_a_flash_a_recoil_and_a_light(self):
        self.feed(("muzzle", 300.0, 200.0, 0.3))
        self.assertTrue(self.r.fx.flashes)
        self.assertIn((300.0, 200.0), self.r._recoil)
        self.assertTrue(self.r.flashes)
        for _ in range(30):
            self.feed()
        self.assertEqual((self.r.fx.flashes, self.r._recoil, self.r.flashes), ([], {}, []))

    def test_mortar_fire_is_bigger_than_gun_fire(self):
        self.feed(("mortar_fire", 300.0, 200.0, 0.0))
        self.assertGreater(self.r.fx.flashes[0][5], 1.5)
        self.assertGreater(len(self.r.fx.smoke), 3)

    def test_impacts_claymores_and_hits_each_have_a_look(self):
        self.feed(("splash", 100.0, 100.0, 45), ("claymore", 200.0, 200.0, 50), ("hit", 300.0, 300.0, 0.5))
        kinds = {r[5] for r in self.r.fx.rings}
        self.assertEqual(kinds, {"khaki", "amber"})
        self.assertTrue(self.r.fx.sparks)

    def test_losing_a_tower_leaves_smoke_and_a_fading_ghost(self):
        self.game.supply = 999
        self.game.try_build(14, 6, "mg_nest")
        t = self.game.towers[(14, 6)]
        self.r.draw(self.screen, self.game, "mg_nest", (0, 0))          # the renderer notes the tower
        self.feed(("tower_lost", t.x, t.y, 0))
        self.assertTrue(self.r.fx.ghosts)
        self.assertTrue(self.r.fx.smoke)

    def test_an_enemy_that_vanishes_fades_out(self):
        g = self.game
        g.start_wave()
        g.time_of_day = "day"                     # everyone visible, so everyone is drawn
        for _ in range(60 * 4):
            g.update(DT)
            self.r.update(DT, g)
        self.assertTrue(any(e.visible for e in g.enemies))
        before = len(self.r.fx.ghosts)
        g.enemies.remove(g.enemies[0])
        self.r.update(DT, g)
        self.assertEqual(len(self.r.fx.ghosts), before + 1)

    def test_an_enemy_lost_in_the_dark_is_not_shown_fading(self):
        g = self.game
        g.start_wave()
        g.time_of_day = "dark"                    # no towers, so only the base lights anything
        for _ in range(60 * 3):
            g.update(DT)
            self.r.update(DT, g)
        hidden = [e for e in g.enemies if not e.visible]
        self.assertTrue(hidden)
        before = len(self.r.fx.ghosts)
        g.enemies.remove(hidden[0])
        self.r.update(DT, g)
        self.r.update(DT, g)
        self.assertEqual(len(self.r.fx.ghosts), before)    # it was never drawn, so nothing fades

    def test_shell_arc_is_zero_at_both_ends_and_highest_midway(self):
        sh = Shell(100, 100, 300, 100, 25, 200, 45)
        heights = []
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            sh.x = 100 + 200 * frac
            heights.append(self.r._arc(sh))
        self.assertAlmostEqual(heights[0], 0, delta=0.01)
        self.assertAlmostEqual(heights[4], 0, delta=0.01)
        self.assertEqual(max(heights), heights[2])
        self.assertLessEqual(heights[2], 70 * 1.001 * 1)

    def test_full_scene_draws_with_every_effect_and_each_time_of_day(self):
        g = self.game
        g.supply = 5000
        for pos, key in [((14, 6), "mg_nest"), ((12, 4), "mortar"), ((13, 8), "flare"), ((15, 6), "claymore")]:
            self.assertTrue(g.try_build(*pos, key))
        for tod in ("day", "dusk", "dark", "dawn"):
            g.time_of_day = tod
            g.wave = 0
            g.start_wave()
            for i in range(60 * 12):
                g.update(DT)
                self.r.update(DT, g)
                if i % 10 == 0:
                    self.r.draw(self.screen, g, "mortar", (400, 300))
            g.reset()
            g.supply = 5000
            for pos, key in [((14, 6), "mg_nest"), ((12, 4), "mortar"), ((13, 8), "flare"), ((15, 6), "claymore")]:
                g.try_build(*pos, key)

    def test_tower_scale_keeps_the_gun_on_the_mount(self):
        a = self.r.assets
        ax, ay = art.ANCHOR["tower"]
        base = a.scaled("tower.mg_nest.base", TOWER_SCALE)
        self.assertAlmostEqual(base.get_width(), 60 * TOWER_SCALE, delta=1)
        gun = a.rotated("tower.mg_nest.gun", 0.0, TOWER_SCALE)
        self.assertAlmostEqual(gun.get_width(), 44 * TOWER_SCALE, delta=2)


if __name__ == "__main__":
    unittest.main()
