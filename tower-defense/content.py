"""Tunable game content. Edit numbers here; no logic lives in this file.

Distances are world units (one tile is 40). Times are seconds.
"""
from defs import Content, EnemyDef, MapDef, SpawnGroup, TowerDef, WaveDef

TOWERS = {
    t.key: t for t in (
        # Fast, light, short range. The reliable all-rounder.
        TowerDef(key="mg_nest", cost=50, range=110, cooldown=0.25, damage=4,
                 projectile_speed=500, hp=60),
        # Slow shells with splash. Cannot hit anything inside min_range.
        TowerDef(key="mortar", cost=100, range=230, min_range=80, cooldown=2.0,
                 damage=25, splash_radius=45, projectile_speed=220, hp=80),
        # Sits on the trail. One burst when an enemy walks into it, then gone.
        TowerDef(key="claymore", cost=30, range=0, cooldown=0, damage=60,
                 splash_radius=50, placement="trail", single_use=True,
                 kind="mine", trigger_radius=24, hp=1),
        # Deals no damage. Lights the area for the M3 visibility system, so
        # light_radius has no effect until then.
        TowerDef(key="flare", cost=40, range=0, cooldown=0, damage=0,
                 kind="support", light_radius=170, hp=40),
    )
}

ENEMIES = {
    e.key: e for e in (
        EnemyDef(key="scout", hp=30, speed=115, kill_reward=5),
        EnemyDef(key="infantry", hp=80, speed=65, kill_reward=6),
        EnemyDef(key="sapper", hp=60, speed=75, kill_reward=10, behavior="seek_tower",
                 aggro_range=130, attack_damage=20, attack_interval=1.0, attack_range=22),
    )
}


def _g(enemy, count, interval, path=0, delay=0.0):
    return SpawnGroup(enemy=enemy, count=count, interval=interval, path=path, delay=delay)


# Path 0 is the north trail, path 1 the south trail.
FIREBASE_WAVES = (
    WaveDef(time_of_day="dusk", log_key="log.firebase.w1", groups=(
        _g("infantry", 6, 1.4, path=0),)),
    WaveDef(time_of_day="dusk", log_key="log.firebase.w2", groups=(
        _g("infantry", 5, 1.4, path=0),
        _g("infantry", 5, 1.4, path=1, delay=2.0))),
    WaveDef(time_of_day="dark", log_key="log.firebase.w3", groups=(
        _g("scout", 8, 0.8, path=1),
        _g("infantry", 4, 1.5, path=0, delay=3.0))),
    WaveDef(time_of_day="dark", log_key="log.firebase.w4", groups=(
        _g("infantry", 8, 1.1, path=0),
        _g("sapper", 3, 2.0, path=1, delay=4.0))),
    WaveDef(time_of_day="dark", log_key="log.firebase.w5", groups=(
        _g("scout", 10, 0.6, path=0),
        _g("scout", 10, 0.6, path=1, delay=1.0),
        _g("infantry", 6, 1.2, path=1, delay=6.0))),
    WaveDef(time_of_day="dark", log_key="log.firebase.w6", groups=(
        _g("infantry", 14, 0.9, path=0),
        _g("sapper", 5, 1.6, path=0, delay=5.0),
        _g("infantry", 12, 0.9, path=1, delay=2.0))),
    WaveDef(time_of_day="dawn", log_key="log.firebase.w7", groups=(
        _g("scout", 16, 0.45, path=0),
        _g("sapper", 7, 1.3, path=1, delay=3.0),
        _g("infantry", 14, 0.8, path=1, delay=6.0))),
    WaveDef(time_of_day="dawn", log_key="log.firebase.w8", groups=(
        _g("infantry", 20, 0.7, path=0),
        _g("infantry", 20, 0.7, path=1, delay=1.0),
        _g("sapper", 8, 1.3, path=0, delay=8.0),
        _g("scout", 14, 0.45, path=1, delay=12.0))),
)

FIREBASE = MapDef(
    key="firebase",
    cols=20, rows=15, tile_size=40,
    paths=(
        # North trail, then the shared run in along row 7 to the wire.
        ((0, 2), (10, 2), (10, 5), (15, 5), (15, 7), (18, 7)),
        # South trail joins the same final stretch.
        ((0, 12), (8, 12), (8, 9), (14, 9), (14, 7), (18, 7)),
    ),
    waves=FIREBASE_WAVES,
    start_supply=200,
    start_integrity=10,
    resupply_bonus=30,
    towers=("mg_nest", "mortar", "claymore", "flare"),
    base=(18, 7),
    labels=(
        ("map.firebase.label.north_treeline", 3.0, 1.0, -4),
        ("map.firebase.label.south_approach", 3.0, 13.2, 3),
        ("map.firebase.label.wire", 16.5, 8.4, 0),
        ("map.firebase.label.base", 18.0, 5.6, 0),
    ),
)

CONTENT = Content(towers=TOWERS, enemies=ENEMIES, maps={FIREBASE.key: FIREBASE})
CONTENT.validate()
