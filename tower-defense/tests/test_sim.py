import os
import sys
import unittest
from dataclasses import replace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from content import CONTENT, PROTOTYPE_MAP
from defs import Content, EnemyDef, MapDef, SpawnGroup, TowerDef, WaveDef
from sim import Enemy, Game, path_length, tile_center
from strings import Strings

DT = 1 / 60


def run(game, seconds):
    for _ in range(int(seconds / DT)):
        game.update(DT)


class SimTests(unittest.TestCase):
    def setUp(self):
        self.game = Game(CONTENT, "prototype")

    def test_start_values_come_from_map(self):
        self.assertEqual(self.game.supply, 150)
        self.assertEqual(self.game.integrity, 10)

    def test_build_rules(self):
        g = self.game
        self.assertFalse(g.try_build(0, 2, "mg_nest"))      # on the path
        self.assertFalse(g.try_build(-1, 0, "mg_nest"))     # off the map
        self.assertFalse(g.try_build(5, 3, "nope"))         # unknown tower
        self.assertTrue(g.try_build(5, 3, "mg_nest"))
        self.assertFalse(g.try_build(5, 3, "mg_nest"))      # occupied
        self.assertEqual(g.supply, 100)

    def test_cannot_build_without_supply(self):
        g = self.game
        g.supply = 49
        self.assertFalse(g.try_build(5, 3, "mg_nest"))

    def test_wave_clear_pays_resupply_bonus(self):
        g = self.game
        g.try_build(5, 3, "mg_nest")
        g.try_build(7, 3, "mg_nest")
        g.try_build(5, 8, "mg_nest")
        g.start_wave()
        run(g, 60)
        self.assertFalse(g.wave_active)
        self.assertEqual(g.supply, 150 - 150 + 25 + 6 * 10)

    def test_losing_ends_game(self):
        g = self.game
        g.integrity = 3
        g.start_wave()
        run(g, 120)
        self.assertEqual(g.state, "lost")
        self.assertFalse(g.try_build(5, 3, "mg_nest"))

    def test_reset(self):
        g = self.game
        g.try_build(5, 3, "mg_nest")
        g.start_wave()
        g.reset()
        self.assertEqual((g.supply, g.wave, len(g.towers), len(g.enemies)), (150, 0, 0, 0))

    def test_cannot_start_wave_mid_wave(self):
        g = self.game
        g.start_wave()
        g.start_wave()
        self.assertEqual(g.wave, 1)


class MultiPathTests(unittest.TestCase):
    def make(self):
        towers = {"t": TowerDef(key="t", cost=10, range=100, cooldown=1, damage=1)}
        enemies = {"e": EnemyDef(key="e", hp=10, speed=50)}
        m = MapDef(
            key="m", cols=10, rows=6, tile_size=40,
            paths=(((0, 1), (9, 1)), ((0, 4), (9, 4))),
            waves=(WaveDef(groups=(
                SpawnGroup("e", count=2, interval=1.0, path=0),
                SpawnGroup("e", count=2, interval=1.0, path=1, delay=0.5),
            )),),
            start_supply=0, start_integrity=5, resupply_bonus=0, towers=("t",),
        )
        c = Content(towers=towers, enemies=enemies, maps={"m": m})
        c.validate()
        return Game(c, "m")

    def test_groups_spawn_on_their_own_paths(self):
        g = self.make()
        self.assertEqual(len(g.paths), 2)
        self.assertTrue({(0, 1), (9, 1), (0, 4), (9, 4)} <= g.path_tiles)
        g.start_wave()
        g.update(DT)
        self.assertEqual([e.y for e in g.enemies], [tile_center(0, 1, 40)[1]])
        run(g, 0.6)
        ys = sorted({e.y for e in g.enemies})
        self.assertEqual(ys, [tile_center(0, 1, 40)[1], tile_center(0, 4, 40)[1]])

    def test_progress_fraction_compares_across_paths(self):
        short = Enemy(EnemyDef("e", 1, 1), [(0, 0), (100, 0)])
        long_ = Enemy(EnemyDef("e", 1, 1), [(0, 0), (400, 0)])
        short.progress, long_.progress = 50, 100
        self.assertGreater(short.fraction, long_.fraction)
        self.assertEqual(path_length([(0, 0), (3, 4)]), 5)


class TargetingTests(unittest.TestCase):
    def test_min_range_blind_zone(self):
        content = replace(CONTENT, towers={
            "mg_nest": replace(CONTENT.towers["mg_nest"], min_range=60)})
        g = Game(content, "prototype")
        g.try_build(5, 3, "mg_nest")
        tower = g.towers[(5, 3)]
        near = Enemy(CONTENT.enemies["infantry"], g.paths[0])
        near.x, near.y = tower.x + 30, tower.y
        bullets = []
        tower.update(DT, [near], bullets)
        self.assertEqual(bullets, [])
        near.x = tower.x + 80
        tower.update(DT, [near], bullets)
        self.assertEqual(len(bullets), 1)

    def test_closest_strategy(self):
        content = replace(CONTENT, towers={
            "mg_nest": replace(CONTENT.towers["mg_nest"], targeting="closest")})
        g = Game(content, "prototype")
        g.try_build(5, 3, "mg_nest")
        tower = g.towers[(5, 3)]
        far, near = (Enemy(CONTENT.enemies["infantry"], g.paths[0]) for _ in range(2))
        far.x, far.y, far.progress = tower.x + 90, tower.y, 500
        near.x, near.y, near.progress = tower.x + 20, tower.y, 10
        bullets = []
        tower.update(DT, [far, near], bullets)
        self.assertIs(bullets[0].enemy, near)


class GuardTests(unittest.TestCase):
    def test_unbuilt_features_are_refused(self):
        for tower in (replace(CONTENT.towers["mg_nest"], single_use=True),
                      replace(CONTENT.towers["mg_nest"], splash_radius=30),
                      replace(CONTENT.towers["mg_nest"], placement="trail")):
            with self.assertRaises(NotImplementedError):
                Game(replace(CONTENT, towers={"mg_nest": tower}), "prototype")

    def test_dangling_keys_fail_validation(self):
        bad = replace(PROTOTYPE_MAP, towers=("ghost",))
        with self.assertRaises(ValueError):
            Content(towers=CONTENT.towers, enemies=CONTENT.enemies, maps={"x": bad}).validate()

    def test_bad_enum_values_rejected(self):
        with self.assertRaises(ValueError):
            TowerDef(key="x", cost=1, range=1, cooldown=1, damage=1, placement="sky")
        with self.assertRaises(ValueError):
            EnemyDef(key="x", hp=1, speed=1, behavior="teleport")
        with self.assertRaises(ValueError):
            WaveDef(groups=(), time_of_day="noon")


class StringsTests(unittest.TestCase):
    def setUp(self):
        self.strings = Strings.load()

    def test_every_entry_valid_and_narrative_is_draft(self):
        for key in self.strings.keys():
            e = self.strings.entry(key)
            if e["kind"] == "narrative":
                self.assertEqual(e["status"], "draft", key)

    def test_content_references_resolve(self):
        for t in CONTENT.towers:
            self.strings.get(f"tower.{t}.name")
        for m in CONTENT.maps.values():
            for w in m.waves:
                if w.log_key:
                    self.strings.get(w.log_key)

    def test_renamed_hud_terms(self):
        line = self.strings.get("hud.status", supply=1, integrity=2, wave=3, total=4,
                                tower="T", cost=5, hint="")
        self.assertIn("Supply Points 1", line)
        self.assertIn("Base Integrity 2", line)
        for old in ("Gold", "Lives", "YOU WIN", "GAME OVER"):
            self.assertNotIn(old, "".join(self.strings.entry(k)["text"] for k in self.strings.keys()))

    def test_missing_key_raises(self):
        with self.assertRaises(KeyError):
            self.strings.get("does.not.exist")


if __name__ == "__main__":
    unittest.main()
