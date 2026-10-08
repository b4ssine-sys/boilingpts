import math
import os
import sys
import unittest
from dataclasses import replace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from content import CONTENT
from defs import (Content, EnemyDef, MapDef, SpawnGroup, TimeRule, TowerDef, VisibilityRules,
                  WaveDef)
from sim import Enemy, Game, tile_center

DT = 1 / 60

GUN = TowerDef(key="gun", cost=1, range=120, cooldown=0.1, damage=5, sight_radius=100)
MORTAR = TowerDef(key="mortar", cost=1, range=300, min_range=60, cooldown=1.0, damage=10,
                  splash_radius=40, projectile_speed=300, sight_radius=50)
FLARE = TowerDef(key="flare", cost=1, range=0, cooldown=0, damage=0, kind="support",
                 light_radius=150)
WALKER = EnemyDef(key="walker", hp=1000, speed=10)
GHOST = EnemyDef(key="ghost", hp=1000, speed=10, visibility=0.5)


def rules(dark=(1.0, 0.5, 30), dusk=(2.0, 0.9, 10), dawn=(1.5, 0.8, 20), base_sight=0, ttl=4.0):
    return VisibilityRules(
        by_time=(("day", TimeRule(0, 1.0, 0)), ("dusk", TimeRule(*dusk)),
                 ("dark", TimeRule(*dark)), ("dawn", TimeRule(*dawn))),
        base_sight=base_sight, contact_ttl=ttl)


def make(tod="dark", towers=(GUN, MORTAR, FLARE), enemies=(WALKER, GHOST), vis=None, seed=0):
    """12x8 map, a trail along row 4, base at the far end, all content buildable."""
    m = MapDef(key="t", cols=12, rows=8, tile_size=40, paths=(((0, 4), (11, 4)),),
               waves=(WaveDef(groups=(), time_of_day=tod),), start_supply=999,
               start_integrity=5, resupply_bonus=0, towers=tuple(t.key for t in towers),
               base=(11, 4), visibility=vis or rules())
    c = Content(towers={t.key: t for t in towers}, enemies={e.key: e for e in enemies}, maps={"t": m})
    c.validate()
    g = Game(c, "t", seed=seed)
    g.start_wave()          # sets the time of day; the empty wave leaves the field clear
    g.groups = []
    return g


def put(g, col, row, key):
    """Build and fail loudly if the tile is illegal, so a bad test setup cannot pass silently."""
    assert g.try_build(col, row, key), f"cannot build {key} at {col},{row}"


def enemy_at(g, x, key="walker", y=None):
    e = Enemy(g.content.enemies[key], g.paths[0])
    e.x, e.y = x, tile_center(0, 4, 40)[1] if y is None else y
    e.target = 1
    g.enemies.append(e)
    return e


class TimeOfDayTests(unittest.TestCase):
    def test_follows_the_started_wave_and_resets(self):
        g = make("dusk")
        self.assertEqual(g.time_of_day, "dusk")
        g.reset()
        self.assertEqual(g.time_of_day, "day")

    def test_before_any_wave_it_is_day(self):
        m = make().map
        c = make().content
        self.assertEqual(Game(c, "t").time_of_day, "day")

    def test_daylight_sees_everything_and_aims_true(self):
        g = make("dark")
        g.time_of_day = "day"
        put(g, 5, 2, "gun")
        e = enemy_at(g, 20)
        g._update_visibility()
        self.assertTrue(e.visible)
        self.assertEqual(g.shot_quality(g.towers[(5, 2)]), (1.0, 0.0))


class VisibilityTests(unittest.TestCase):
    def setUp(self):
        self.g = make("dark")
        put(self.g, 5, 2, "gun")           # centre (220, 100), sight 100
        self.t = self.g.towers[(5, 2)]

    def test_enemy_inside_sight_is_seen_outside_is_not(self):
        near = enemy_at(self.g, 220, y=self.t.y + 90)
        far = enemy_at(self.g, 20)
        self.g._update_visibility()
        self.assertTrue(near.visible)
        self.assertFalse(far.visible)

    def test_unseen_enemies_are_not_targeted(self):
        e = enemy_at(self.g, 220, y=self.t.y + 100.5)   # just outside sight, inside gun range
        self.g._update_visibility()
        self.assertFalse(e.visible)
        self.t.update(DT, self.g)
        self.assertEqual(self.g.bullets, [])
        e.y = self.t.y + 90
        self.g._update_visibility()
        self.t.update(DT, self.g)
        self.assertEqual(len(self.g.bullets), 1)

    def test_dusk_sees_further_than_dark(self):
        e = enemy_at(self.g, 220, y=self.t.y + 150)
        self.g._update_visibility()
        self.assertFalse(e.visible)
        self.g.time_of_day = "dusk"
        self.g._update_visibility()
        self.assertTrue(e.visible)       # sight scale 2.0

    def test_stealthy_enemy_needs_a_closer_light(self):
        normal = enemy_at(self.g, 220, "walker", y=self.t.y + 80)
        ghost = enemy_at(self.g, 220, "ghost", y=self.t.y + 80)
        self.g._update_visibility()
        self.assertTrue(normal.visible)
        self.assertFalse(ghost.visible)    # needs to be within 100 * 0.5

    def test_base_sees_its_own_surroundings(self):
        g = make("dark", vis=rules(base_sight=90))
        bx, by = tile_center(11, 4, 40)
        e = enemy_at(g, bx - 80)
        g._update_visibility()
        self.assertTrue(e.visible)

    def test_a_flare_lets_every_tower_see_into_its_pool(self):
        far = enemy_at(self.g, 20)                       # 200+ from the gun
        put(self.g, 1, 3, "flare")                  # centre (60, 140), light 150
        self.g._update_visibility()
        self.assertTrue(far.visible)
        far.x = 400                                       # outside both
        self.g._update_visibility()
        self.assertFalse(far.visible)

    def test_lost_tower_takes_its_sight_with_it(self):
        e = enemy_at(self.g, 220, y=self.t.y + 90)
        self.g._update_visibility()
        self.assertTrue(e.visible)
        self.t.hp = 0
        self.g.update(DT)
        self.assertNotIn((5, 2), self.g.towers)
        self.g._update_visibility()
        self.assertFalse(e.visible)

    def test_light_sources_lists_sight_and_light(self):
        put(self.g, 1, 3, "flare")
        kinds = sorted(k for *_, k in self.g.light_sources())
        self.assertEqual(kinds, ["light", "sight"])      # gun sight + flare light; base sight is 0 here


class AccuracyTests(unittest.TestCase):
    def test_flare_restores_accuracy_only_inside_its_pool(self):
        g = make("dark")
        put(g, 5, 2, "gun")        # (220, 100)
        put(g, 5, 6, "gun")        # (220, 260)
        put(g, 5, 3, "flare")      # (220, 140) light 150 covers both guns
        put(g, 0, 0, "gun")        # (20, 20) well outside
        self.assertEqual(g.shot_quality(g.towers[(5, 2)]), (1.0, 0.0))
        self.assertEqual(g.shot_quality(g.towers[(5, 6)]), (1.0, 0.0))
        self.assertEqual(g.shot_quality(g.towers[(0, 0)]), (0.5, 30))

    def test_hit_chance_zero_misses_and_one_hits(self):
        for chance, expect_hit in ((0.0, False), (1.0, True)):
            g = make("dark", vis=rules(dark=(1.0, chance, 0)))
            put(g, 5, 2, "gun")
            e = enemy_at(g, 220, y=g.towers[(5, 2)].y + 60)
            g._update_visibility()
            g.towers[(5, 2)].update(DT, g)
            for _ in range(60):
                g.bullets[0].update(DT) if g.bullets and not g.bullets[0].done else None
            self.assertEqual(e.hp < e.max_hp, expect_hit, chance)

    def test_a_miss_still_flies_to_the_target(self):
        g = make("dark", vis=rules(dark=(1.0, 0.0, 0)))
        put(g, 5, 2, "gun")
        enemy_at(g, 220, y=g.towers[(5, 2)].y + 60)
        g._update_visibility()
        g.towers[(5, 2)].update(DT, g)
        self.assertFalse(g.bullets[0].hits)
        self.assertEqual(len(g.bullets), 1)

    def test_same_seed_repeats_and_hit_rate_matches_chance(self):
        def volley(seed):
            g = make("dark", vis=rules(dark=(1.0, 0.65, 0)), seed=seed)
            put(g, 5, 2, "gun")
            enemy_at(g, 220, y=g.towers[(5, 2)].y + 60)
            g._update_visibility()
            out = []
            for _ in range(400):
                g.towers[(5, 2)].cooldown = 0
                g.towers[(5, 2)].update(DT, g)
                out.append(g.bullets[-1].hits)
            return out
        a, b, c = volley(1), volley(1), volley(2)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertAlmostEqual(sum(a) / len(a), 0.65, delta=0.08)

    def test_mortar_scatter_is_bounded_and_flare_removes_it(self):
        g = make("dark", vis=rules(dark=(1.0, 1.0, 40)))
        put(g, 5, 2, "mortar")
        m = g.towers[(5, 2)]
        spots = []
        for _ in range(60):
            g.shells.clear()
            m._lob(g, 400, 160, 40)
            spots.append((g.shells[0].tx, g.shells[0].ty))
        self.assertLessEqual(max(math.hypot(x - 400, y - 160) for x, y in spots), 40.001)
        self.assertGreater(max(math.hypot(x - 400, y - 160) for x, y in spots), 10)   # it does scatter
        put(g, 5, 3, "flare")
        self.assertEqual(g.shot_quality(m), (1.0, 0.0))


class ContactTests(unittest.TestCase):
    def test_a_lost_enemy_leaves_a_contact_that_expires(self):
        g = make("dark", vis=rules(ttl=2.0))
        put(g, 5, 2, "gun")
        e = enemy_at(g, 220, y=g.towers[(5, 2)].y + 90)
        g._update_visibility()
        self.assertEqual(g.contacts, [])
        seen_at = (e.x, e.y)
        e.y += 80                              # walks out of the light
        g.clock += 0.5
        g._update_visibility()
        self.assertEqual(len(g.contacts), 1)
        c = g.contacts[0]
        self.assertEqual((c.x, c.y), seen_at)  # where it WAS, not where it is
        self.assertAlmostEqual(c.age, 0.5)
        g.clock += 2.0
        g._update_visibility()
        self.assertEqual(g.contacts, [])

    def test_an_enemy_never_seen_leaves_no_contact(self):
        g = make("dark")
        enemy_at(g, 20)
        g._update_visibility()
        self.assertEqual(g.contacts, [])

    def test_a_dead_enemy_leaves_no_contact(self):
        g = make("dark")
        put(g, 5, 2, "gun")
        e = enemy_at(g, 220, y=g.towers[(5, 2)].y + 90)
        g._update_visibility()
        e.hp = 0
        g._update_visibility()
        self.assertEqual(g.contacts, [])


class BlindFireTests(unittest.TestCase):
    def setUp(self):
        self.g = make("dark", vis=rules(dark=(1.0, 1.0, 0)))
        put(self.g, 5, 6, "mortar")                   # (220, 260), sight 50
        self.m = self.g.towers[(5, 6)]

    def hidden_contact(self, x, y):
        e = enemy_at(self.g, x, y=y)
        e.last_seen = (x, y, 0.5, self.g.clock)
        e.y += 500                                          # now far from anything, but remembered
        self.g._update_visibility()
        return e

    def test_mortar_fires_on_a_last_known_position_in_reach(self):
        self.hidden_contact(220, 100)                       # 160 away: inside 60..300
        self.assertEqual(len(self.g.contacts), 1)
        self.m.update(DT, self.g)
        self.assertEqual(len(self.g.shells), 1)
        s = self.g.shells[0]
        self.assertEqual((s.tx, s.ty), (220, 100))          # the stale position, not the live one
        self.assertIn("muzzle", [ev[0] for ev in self.g.events])

    def test_contacts_outside_min_or_max_range_are_ignored(self):
        self.hidden_contact(220, 240)                       # 20 away: inside the blind zone
        self.m.update(DT, self.g)
        self.assertEqual(self.g.shells, [])
        self.g.contacts.clear()
        self.hidden_contact(220 + 10, 260 - 400 + 0)         # too far
        self.m.cooldown = 0
        self.m.update(DT, self.g)
        self.assertEqual(self.g.shells, [])

    def test_guns_do_not_fire_on_contacts(self):
        put(self.g, 5, 2, "gun")
        gun = self.g.towers[(5, 2)]
        e = enemy_at(self.g, 220, y=gun.y + 90)
        self.g._update_visibility()
        e.y += 500
        self.g.clock += 0.5
        self.g._update_visibility()
        self.assertEqual(len(self.g.contacts), 1)
        gun.update(DT, self.g)
        self.assertEqual(self.g.bullets, [])

    def test_visible_targets_take_priority_over_contacts(self):
        self.hidden_contact(220, 100)
        near = enemy_at(self.g, 220, y=self.m.y - 40 - 40)    # 80 away, mortar sight is only 50
        put(self.g, 5, 5, "flare")                        # light reveals it
        self.g._update_visibility()
        self.assertTrue(near.visible)
        self.m.update(DT, self.g)
        s = self.g.shells[0]
        self.assertLess(math.hypot(s.tx - near.x, s.ty - near.y), 40)   # aimed at the live target


class EventTests(unittest.TestCase):
    def test_firing_emits_a_muzzle_event(self):
        g = make("day")
        put(g, 5, 2, "gun")
        enemy_at(g, 220, y=g.towers[(5, 2)].y + 60)
        g.update(DT)
        self.assertIn("muzzle", [ev[0] for ev in g.events])


class BalanceTests(unittest.TestCase):
    """Guards the slice's difficulty: night hurts, flares are worth building."""

    CORE = [(14, 6, "mg_nest"), (16, 6, "mg_nest"), (15, 8, "mg_nest"), (13, 7, "mortar"),
            (9, 3, "mg_nest"), (11, 4, "mg_nest"), (9, 10, "mg_nest"), (12, 10, "mg_nest"),
            (12, 8, "mortar"), (11, 3, "mortar"), (15, 6, "claymore"), (14, 9, "claymore"),
            (10, 4, "claymore"), (16, 8, "mg_nest"), (13, 6, "mg_nest"), (7, 10, "mg_nest"),
            (16, 5, "mg_nest"), (9, 11, "mortar"), (12, 4, "mg_nest"), (17, 8, "mg_nest"),
            (17, 6, "mg_nest")]
    FLARES = [(13, 8, "flare"), (11, 6, "flare")]

    def play(self, flares, seed):
        plan = [(0, *t) for t in self.CORE[:4]] + [(2, *f) for f in self.FLARES[:flares]] \
               + [(0, *t) for t in self.CORE[4:]]
        g = Game(CONTENT, "firebase", seed=seed)
        for _, c, r, k in plan:
            self.assertTrue(g.placement_ok(c, r, k), (c, r, k))
        pending = list(plan)

        def spend(w):
            while pending and pending[0][0] <= w and g.try_build(*pending[0][1:]):
                pending.pop(0)
        for w in range(len(g.map.waves)):
            spend(w)
            g.start_wave()
            ticks = 0
            while g.wave_active and g.state == "playing" and ticks < 36000:
                g.update(DT)
                ticks += 1
                if ticks % 30 == 0:
                    spend(w)
            if g.state != "playing":
                break
            spend(w + 1)
        return g.state, g.integrity

    def test_flares_are_worth_building(self):
        seeds = range(3)
        with_flares = [self.play(1, s) for s in seeds]
        without = [self.play(0, s) for s in seeds]
        self.assertTrue(all(st == "won" for st, _ in with_flares), with_flares)
        self.assertGreater(sum(i for _, i in with_flares), sum(i for _, i in without) + 3,
                           (with_flares, without))


if __name__ == "__main__":
    unittest.main()
