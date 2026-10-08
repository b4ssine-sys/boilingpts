"""Tunable game content. Edit numbers here; no logic lives in this file.

M1 holds only the prototype's content, re-expressed as definitions. The
four-tower roster, three-enemy roster and firebase map arrive in M2.
"""
from defs import Content, EnemyDef, MapDef, SpawnGroup, TowerDef, WaveDef

TOWERS = {
    t.key: t for t in (
        TowerDef(key="mg_nest", cost=50, range=120, cooldown=0.5, damage=10,
                 projectile_speed=400),
    )
}

ENEMIES = {
    e.key: e for e in (
        EnemyDef(key="infantry", hp=30, speed=70, kill_reward=10),
    )
}


def _wave(count, hp, speed):
    return WaveDef(groups=(
        SpawnGroup(enemy="infantry", count=count, interval=0.7, hp=hp, speed=speed),
    ))


PROTOTYPE_MAP = MapDef(
    key="prototype",
    cols=20, rows=15, tile_size=40,
    paths=(
        ((0, 2), (6, 2), (6, 10), (13, 10), (13, 4), (19, 4)),
    ),
    waves=(
        _wave(6, 30, 70),
        _wave(10, 40, 80),
        _wave(12, 60, 80),
        _wave(15, 80, 90),
        _wave(20, 100, 100),
    ),
    start_supply=150,
    start_integrity=10,
    resupply_bonus=25,
    towers=("mg_nest",),
)

CONTENT = Content(towers=TOWERS, enemies=ENEMIES, maps={PROTOTYPE_MAP.key: PROTOTYPE_MAP})
CONTENT.validate()
