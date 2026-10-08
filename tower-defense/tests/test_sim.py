import os
import sys
import unittest
from dataclasses import replace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from content import CONTENT, TOWERS
from defs import Content, EnemyDef, MapDef, SpawnGroup, TowerDef, WaveDef
from sim import Enemy, Game, path_length, tile_center
from strings import Strings

DT = 1 / 60


def run(game, seconds):
    for _ in range(int(round(seconds / DT))):
        game.update(DT)


def fixture(towers=(), enemies=(), groups=(), paths=None, integrity=5, supply=1000):
    """A 12x6 map with one straight trail along row 2, east to the base."""
    towers = {t.key: t for t in towers}
    enemies = {e.key: e for e in enemies}
    m = MapDef(key="t", cols=12, rows=6, tile_size=40,
               paths=paths or (((0, 2), (11, 2)),),
               waves=(WaveDef(groups=tuple(groups)),),
               start_supply=supply, start_integrity=integrity, resupply_bonus=0,
               towers=tuple(towers), base=(11, 2))
    c = Content(towers=towers, enemies=enemies, maps={"t": m})
    c.validate()
    return Game(c, "t")


GUN = TowerDef(key="gun", cost=10, range=200, cooldown=0.1, damage=5)
WALKER = EnemyDef(key="walker", hp=20, speed=80, kill_reward=7)


class BasicTests(unittest.TestCase):
    def test_build_rules_ground_and_trail(self):
        mine = TowerDef(key="mine", cost=5, range=0, cooldown=0, damage=10, splash_radius=30,
                        placement="trail", single_use=True, kind="mine", trigger_radius=10)
        g = fixture(towers=(GUN, mine))
        self.assertFalse(g.try_build(3, 2, "gun"))        # ground tower on the trail
        self.assertTrue(g.try_build(3, 3, "gun"))
        self.assertFalse(g.try_build(3, 3, "gun"))        # occupied
        self.assertFalse(g.try_build(3, 3, "mine"))       # trail tower off the trail
        self.assertTrue(g.try_build(3, 2, "mine"))
        self.assertFalse(g.try_build(-1, 0, "gun"))       # off the map
        self.assertFalse(g.try_build(5, 5, "ghost"))      # unknown key

    def test_cannot_build_without_supply(self):
        g = fixture(towers=(GUN,), supply=9)
        self.assertFalse(g.try_build(3, 3, "gun"))
        self.assertTrue(g.placement_ok(3, 3, "gun"))      # location is fine, money is not

    def test_kill_pays_reward_and_clearing_last_wave_wins(self):
        g = fixture(towers=(GUN,), enemies=(WALKER,),
                    groups=(SpawnGroup("walker", 3, 0.5),))
        g.try_build(5, 3, "gun")
        g.start_wave()
        run(g, 20)
        self.assertEqual(g.supply, 1000 - 10 + 3 * 7)
        self.assertEqual(g.state, "won")

    def test_clearing_a_wave_pays_resupply_bonus(self):
        g = fixture(towers=(GUN,), enemies=(WALKER,), groups=(SpawnGroup("walker", 1, 0.5),))
        m = replace(g.map, resupply_bonus=11,
                    waves=g.map.waves + (WaveDef(groups=(SpawnGroup("walker", 1, 0.5),)),))
        g.map = m
        g.try_build(5, 3, "gun")
        g.start_wave()
        run(g, 20)
        self.assertEqual(g.state, "playing")
        self.assertEqual(g.supply, 1000 - 10 + 7 + 11)

    def test_leak_costs_integrity_and_loss_ends_game(self):
        g = fixture(enemies=(WALKER,), groups=(SpawnGroup("walker", 3, 0.2),), integrity=2)
        g.start_wave()
        run(g, 30)
        self.assertEqual(g.state, "lost")

    def test_events_do_not_replay_after_game_over(self):
        g = fixture(towers=(GUN,), enemies=(WALKER,), groups=(SpawnGroup("walker", 1, 0.5),))
        g.try_build(5, 3, "gun")
        g.start_wave()
        run(g, 20)
        self.assertEqual(g.state, "won")
        g.events = [("splash", 0, 0, 10)]
        g.update(DT)
        self.assertEqual(g.events, [])

    def test_reset(self):
        g = fixture(towers=(GUN,))
        g.try_build(3, 3, "gun")
        g.reset()
        self.assertEqual((g.supply, g.wave, len(g.towers), len(g.shells)), (1000, 0, 0, 0))


class MultiPathTests(unittest.TestCase):
    def test_groups_spawn_on_their_own_paths(self):
        g = fixture(enemies=(WALKER,),
                    paths=(((0, 1), (11, 1)), ((0, 4), (11, 4))),
                    groups=(SpawnGroup("walker", 2, 1.0, path=0),
                            SpawnGroup("walker", 2, 1.0, path=1, delay=0.5)))
        g.start_wave()
        g.update(DT)
        self.assertEqual([e.y for e in g.enemies], [tile_center(0, 1, 40)[1]])
        run(g, 0.6)
        self.assertEqual(sorted({e.y for e in g.enemies}),
                         [tile_center(0, 1, 40)[1], tile_center(0, 4, 40)[1]])

    def test_progress_fraction_compares_across_paths(self):
        short = Enemy(EnemyDef("e", 1, 1), [(0, 0), (100, 0)])
        long_ = Enemy(EnemyDef("e", 1, 1), [(0, 0), (400, 0)])
        short.progress, long_.progress = 50, 100
        self.assertGreater(short.fraction, long_.fraction)
        self.assertEqual(path_length([(0, 0), (3, 4)]), 5)


class TowerBehaviorTests(unittest.TestCase):
    def test_min_range_blind_zone(self):
        mortar = TowerDef(key="m", cost=1, range=300, min_range=100, cooldown=1, damage=10,
                          splash_radius=30, projectile_speed=200)
        g = fixture(towers=(mortar,), enemies=(WALKER,))
        g.try_build(5, 3, "m")
        t = g.towers[(5, 3)]
        e = Enemy(WALKER, g.paths[0])
        e.x, e.y = t.x + 60, t.y
        g.enemies = [e]
        t.update(DT, g)
        self.assertEqual(g.shells, [])
        e.x = t.x + 150
        t.update(DT, g)
        self.assertEqual(len(g.shells), 1)

    def test_mortar_leads_a_moving_target(self):
        mortar = TowerDef(key="m", cost=1, range=400, cooldown=99, damage=10,
                          splash_radius=40, projectile_speed=200)
        tank = EnemyDef(key="tank", hp=1000, speed=80)
        g = fixture(towers=(mortar,), enemies=(tank,), groups=(SpawnGroup("tank", 1, 1.0),))
        g.try_build(5, 4, "m")
        g.start_wave()
        run(g, 1.0)                       # enemy is now walking within range
        run(g, 2.0)                       # shell flies for about a second
        e = g.enemies[0]
        self.assertLess(e.hp, 1000)       # aimed at where it would be, so it was hit

    def test_splash_damages_only_inside_radius(self):
        g = fixture(enemies=(WALKER,))
        a, b = Enemy(WALKER, g.paths[0]), Enemy(WALKER, g.paths[0])
        a.x, a.y, b.x, b.y = 100, 100, 100, 160
        g.enemies = [a, b]
        g.splash(100, 100, 30, 8)
        self.assertEqual((a.hp, b.hp), (12, 20))

    def test_claymore_bursts_once_and_is_removed(self):
        mine = TowerDef(key="mine", cost=1, range=0, cooldown=0, damage=100, splash_radius=60,
                        placement="trail", single_use=True, kind="mine", trigger_radius=20)
        g = fixture(towers=(mine,), enemies=(WALKER,),
                    groups=(SpawnGroup("walker", 3, 0.2),))
        g.try_build(5, 2, "mine")
        g.start_wave()
        seen = []
        for _ in range(60 * 5):
            g.update(DT)
            seen += [ev[0] for ev in g.events]
        self.assertEqual(g.towers, {})
        self.assertEqual(seen.count("claymore"), 1)           # bursts exactly once
        self.assertEqual(g.supply, 1000 - 1 + 3 * 7)          # all three walked into the blast

    def test_claymore_ignores_enemies_out_of_trigger_range(self):
        mine = TowerDef(key="mine", cost=1, range=0, cooldown=0, damage=100, splash_radius=60,
                        placement="trail", single_use=True, kind="mine", trigger_radius=20)
        g = fixture(towers=(mine,), enemies=(WALKER,))
        g.try_build(5, 2, "mine")
        e = Enemy(WALKER, g.paths[0])
        e.x, e.y = g.towers[(5, 2)].x - 60, g.towers[(5, 2)].y
        g.enemies = [e]
        g.towers[(5, 2)].update(DT, g)
        self.assertFalse(g.towers[(5, 2)].spent)

    def test_support_tower_never_fires(self):
        flare = TowerDef(key="f", cost=1, range=0, cooldown=0, damage=0, kind="support",
                         light_radius=100)
        g = fixture(towers=(flare,), enemies=(WALKER,))
        g.try_build(3, 3, "f")
        e = Enemy(WALKER, g.paths[0])
        e.x, e.y = g.towers[(3, 3)].x + 10, g.towers[(3, 3)].y
        g.enemies = [e]
        run(g, 1)
        self.assertEqual((g.bullets, g.shells), ([], []))

    def test_closest_strategy(self):
        near_gun = replace(GUN, targeting="closest")
        g = fixture(towers=(near_gun,), enemies=(WALKER,))
        g.try_build(5, 3, "gun")
        t = g.towers[(5, 3)]
        far, near = Enemy(WALKER, g.paths[0]), Enemy(WALKER, g.paths[0])
        far.x, far.y, far.progress = t.x + 90, t.y, 500
        near.x, near.y, near.progress = t.x + 20, t.y, 10
        g.enemies = [far, near]
        t.update(DT, g)
        self.assertIs(g.bullets[0].enemy, near)

    def test_predict_follows_path(self):
        e = Enemy(WALKER, [(0, 0), (100, 0), (100, 100)])
        self.assertEqual(e.predict(0.5), (40, 0))
        x, y = e.predict(2.0)                      # 160 units: 100 east, 60 south
        self.assertAlmostEqual(x, 100)
        self.assertAlmostEqual(y, 60)
        self.assertEqual(e.predict(100), (100, 100))   # clamps at the end


class SapperTests(unittest.TestCase):
    SAPPER = EnemyDef(key="sap", hp=30, speed=80, behavior="seek_tower", aggro_range=150,
                      attack_damage=15, attack_interval=0.5, attack_range=20)
    POST = TowerDef(key="post", cost=1, range=0, cooldown=0, damage=0, kind="support", hp=40)

    def make(self, sapper=None):
        return fixture(towers=(self.POST,), enemies=(sapper or self.SAPPER,),
                       groups=(SpawnGroup("sap", 1, 1.0),))

    def test_diverts_to_tower_and_destroys_it(self):
        g = self.make()
        g.try_build(4, 3, "post")      # just off the trail, within aggro range
        g.start_wave()
        run(g, 1.0)
        self.assertIsNotNone(g.enemies[0].tower_target)
        run(g, 6.0)
        self.assertEqual(g.towers, {})

    def test_tower_loss_is_reported(self):
        g = self.make()
        g.try_build(4, 3, "post")
        g.start_wave()
        seen = []
        for _ in range(60 * 8):
            g.update(DT)
            seen += [ev[0] for ev in g.events]
        self.assertIn("tower_lost", seen)

    def test_ignores_tower_beyond_aggro_range(self):
        g = self.make(replace(self.SAPPER, aggro_range=60))
        g.try_build(4, 5, "post")      # 120 units off the trail
        g.start_wave()
        run(g, 3)
        self.assertIsNone(g.enemies[0].tower_target)

    def test_rejoins_trail_when_target_is_gone(self):
        g = self.make()
        g.try_build(4, 3, "post")
        g.start_wave()
        for _ in range(60 * 8):
            g.update(DT)
            if not g.towers:
                break
        e = g.enemies[0]
        self.assertEqual(g.towers, {})
        x0 = e.x
        run(g, 1)
        self.assertGreater(e.x, x0)    # heading for the base again

    def test_does_not_target_mines(self):
        mine = TowerDef(key="mine", cost=1, range=0, cooldown=0, damage=1, splash_radius=1,
                        placement="trail", single_use=True, kind="mine", trigger_radius=1)
        g = fixture(towers=(mine,), enemies=(self.SAPPER,),
                    groups=(SpawnGroup("sap", 1, 1.0),))
        g.try_build(6, 2, "mine")
        g.start_wave()
        run(g, 0.5)
        self.assertIsNone(g.enemies[0].tower_target)


class DefinitionTests(unittest.TestCase):
    def test_bad_values_rejected(self):
        with self.assertRaises(ValueError):
            TowerDef(key="x", cost=1, range=1, cooldown=1, damage=1, placement="sky")
        with self.assertRaises(ValueError):
            TowerDef(key="x", cost=1, range=1, cooldown=1, damage=1, kind="trap")
        with self.assertRaises(ValueError):   # a mine must be single use on the trail
            TowerDef(key="x", cost=1, range=0, cooldown=0, damage=1, kind="mine")
        with self.assertRaises(ValueError):   # a turret needs reach and damage
            TowerDef(key="x", cost=1, range=0, cooldown=1, damage=1)
        with self.assertRaises(ValueError):
            EnemyDef(key="x", hp=1, speed=1, behavior="teleport")
        with self.assertRaises(ValueError):   # sapper needs something to seek with
            EnemyDef(key="x", hp=1, speed=1, behavior="seek_tower")
        with self.assertRaises(ValueError):
            WaveDef(groups=(), time_of_day="noon")

    def test_dangling_keys_fail_validation(self):
        m = CONTENT.maps["firebase"]
        with self.assertRaises(ValueError):
            Content(towers=TOWERS, enemies=CONTENT.enemies,
                    maps={"x": replace(m, towers=("ghost",))}).validate()
        bad_wave = WaveDef(groups=(SpawnGroup("ghost", 1, 1),))
        with self.assertRaises(ValueError):
            Content(towers=TOWERS, enemies=CONTENT.enemies,
                    maps={"x": replace(m, waves=(bad_wave,))}).validate()
        bad_path = WaveDef(groups=(SpawnGroup("scout", 1, 1, path=5),))
        with self.assertRaises(ValueError):
            Content(towers=TOWERS, enemies=CONTENT.enemies,
                    maps={"x": replace(m, waves=(bad_path,))}).validate()


class FirebaseContentTests(unittest.TestCase):
    def test_roster_and_map_shape(self):
        m = CONTENT.maps["firebase"]
        self.assertEqual(set(m.towers), {"mg_nest", "mortar", "claymore", "flare"})
        self.assertEqual(set(CONTENT.enemies), {"scout", "infantry", "sapper"})
        self.assertEqual(len(m.paths), 2)
        self.assertEqual(len(m.waves), 8)
        self.assertEqual({p[-1] for p in m.paths}, {m.base})
        used = {g.path for w in m.waves for g in w.groups}
        self.assertEqual(used, {0, 1})                        # both trails see traffic
        self.assertTrue({w.time_of_day for w in m.waves} >= {"dusk", "dark", "dawn"})
        for w in m.waves:
            self.assertTrue(w.log_key)

    def test_no_build_loses_and_mixed_defence_wins(self):
        """Guards against content edits that make the slice unwinnable or trivial."""
        def play(plan):
            g = Game(CONTENT, "firebase")
            i = 0
            for _ in g.map.waves:
                while i < len(plan) and g.try_build(*plan[i]):
                    i += 1
                g.start_wave()
                ticks = 0
                while g.wave_active and g.state == "playing" and ticks < 36000:
                    g.update(DT)
                    ticks += 1
                    if ticks % 30 == 0:
                        while i < len(plan) and g.try_build(*plan[i]):
                            i += 1
                if g.state != "playing":
                    break
            return g
        self.assertEqual(play([]).state, "lost")
        mixed = [(14, 6, "mg_nest"), (16, 6, "mg_nest"), (15, 8, "mg_nest"), (13, 7, "mortar"),
                 (9, 3, "mg_nest"), (11, 4, "mg_nest"), (9, 10, "mg_nest"), (12, 10, "mg_nest"),
                 (12, 8, "mortar"), (11, 3, "mortar"), (15, 6, "claymore"), (14, 9, "claymore"),
                 (10, 4, "claymore"), (16, 8, "mg_nest"), (13, 6, "mg_nest"), (7, 10, "mg_nest"),
                 (16, 5, "mg_nest"), (9, 11, "mortar"), (12, 4, "mg_nest"), (17, 8, "mg_nest"),
                 (17, 6, "mg_nest")]
        self.assertEqual(play(mixed).state, "won")


class StringsTests(unittest.TestCase):
    def setUp(self):
        self.strings = Strings.load()

    def test_narrative_is_draft(self):
        for key in self.strings.keys():
            e = self.strings.entry(key)
            if e["kind"] == "narrative":
                self.assertEqual(e["status"], "draft", key)

    def test_content_references_resolve(self):
        s = self.strings
        for t in CONTENT.towers:
            s.get(f"tower.{t}.name")
            s.get(f"tower.{t}.role")
        for e in CONTENT.enemies:
            s.get(f"enemy.{e}.name")
        for m in CONTENT.maps.values():
            s.get(f"map.{m.key}.name")
            s.get(f"map.{m.key}.context")
            for key, *_ in m.labels:
                s.get(key)
            for w in m.waves:
                s.get(w.log_key)

    def test_old_terms_gone(self):
        text = " ".join(self.strings.entry(k)["text"] for k in self.strings.keys())
        for old in ("Gold", "Lives", "YOU WIN", "GAME OVER"):
            self.assertNotIn(old, text)

    def test_missing_key_raises(self):
        with self.assertRaises(KeyError):
            self.strings.get("does.not.exist")


if __name__ == "__main__":
    unittest.main()
