"""Content definitions. Plain data, no pygame, no game logic.

Designers tune numbers in content.py. Anything a player can read lives in
strings.json and is looked up by key (see strings.py), so these classes carry
ids, never display text.
"""
from dataclasses import dataclass, field
from typing import Optional, Tuple

PLACEMENTS = ("ground", "trail")
KINDS = ("turret", "mine", "support")
BEHAVIORS = ("follow_path", "seek_tower")
TIMES_OF_DAY = ("day", "dusk", "dark", "dawn")


def _check(value, allowed, what):
    if value not in allowed:
        raise ValueError(f"{what} must be one of {allowed}, got {value!r}")


@dataclass(frozen=True)
class TowerDef:
    key: str
    cost: int
    range: float
    cooldown: float
    damage: float
    projectile_speed: float = 400
    min_range: float = 0          # targets closer than this are ignored
    splash_radius: float = 0      # 0 = single target
    placement: str = "ground"     # ground | trail
    single_use: bool = False
    targeting: str = "furthest"   # key into sim.TARGETING
    kind: str = "turret"          # turret fires, mine bursts on contact, support does neither
    hp: float = 60                # what sappers wear down
    trigger_radius: float = 0     # mines: an enemy this close sets it off
    sight_radius: float = 0       # at night this tower sees enemies this close
    light_radius: float = 0       # flares: lit area that also steadies nearby fire at night

    def __post_init__(self):
        _check(self.placement, PLACEMENTS, f"{self.key}.placement")
        _check(self.kind, KINDS, f"{self.key}.kind")
        if self.kind == "mine" and not (self.single_use and self.placement == "trail"
                                        and self.trigger_radius > 0 and self.splash_radius > 0):
            raise ValueError(f"{self.key}: a mine needs single_use, trail placement, "
                             "trigger_radius and splash_radius")
        if self.kind == "turret" and not (self.range > 0 and self.damage > 0):
            raise ValueError(f"{self.key}: a turret needs range and damage")


@dataclass(frozen=True)
class TimeRule:
    """How a time of day changes the fight."""
    sight_scale: float   # multiplies every sight and light radius; 0 means no limit (full daylight)
    hit_chance: float    # chance a gun round hits when the shooter is not lit by a flare
    scatter: float       # mortar aim error, in world units, when the shooter is not lit


# Chosen so dusk and dawn are easier than the dark, and day is unrestricted.
DEFAULT_TIME_RULES = (
    ("day", TimeRule(sight_scale=0, hit_chance=1.0, scatter=0)),
    ("dusk", TimeRule(sight_scale=2.0, hit_chance=0.90, scatter=12)),
    ("dark", TimeRule(sight_scale=1.2, hit_chance=0.65, scatter=35)),
    ("dawn", TimeRule(sight_scale=1.7, hit_chance=0.85, scatter=20)),
)


@dataclass(frozen=True)
class VisibilityRules:
    by_time: Tuple[Tuple[str, TimeRule], ...] = DEFAULT_TIME_RULES
    base_sight: float = 110       # the base itself always sees this far
    contact_ttl: float = 4.0      # seconds a lost contact stays on the map and can be fired on

    def __post_init__(self):
        if {t for t, _ in self.by_time} != set(TIMES_OF_DAY):
            raise ValueError(f"by_time must cover exactly {TIMES_OF_DAY}")

    def rule(self, time_of_day):
        return dict(self.by_time)[time_of_day]


@dataclass(frozen=True)
class EnemyDef:
    key: str
    hp: float
    speed: float                  # world units per second
    behavior: str = "follow_path"  # follow_path | seek_tower
    kill_reward: int = 10
    visibility: float = 1.0       # 1 = normal; below 1 a light must be closer to reveal it
    # seek_tower only: leave the trail for any tower within aggro_range, then
    # hit it every attack_interval seconds from within attack_range.
    aggro_range: float = 0
    attack_damage: float = 0
    attack_interval: float = 1.0
    attack_range: float = 20

    def __post_init__(self):
        _check(self.behavior, BEHAVIORS, f"{self.key}.behavior")
        if not 0 < self.visibility <= 1.5:
            raise ValueError(f"{self.key}: visibility must be in (0, 1.5]")
        if self.behavior == "seek_tower" and not (self.aggro_range > 0 and self.attack_damage > 0):
            raise ValueError(f"{self.key}: seek_tower needs aggro_range and attack_damage")


@dataclass(frozen=True)
class SpawnGroup:
    """One stream of enemies inside a wave. A wave may hold several."""
    enemy: str
    count: int
    interval: float
    path: int = 0                 # index into MapDef.paths
    delay: float = 0.0            # seconds after wave start before the first spawn
    # Per-group overrides of the EnemyDef numbers, so a wave can ramp one enemy
    # type without a new def per wave.
    hp: Optional[float] = None
    speed: Optional[float] = None


@dataclass(frozen=True)
class WaveDef:
    groups: Tuple[SpawnGroup, ...]
    time_of_day: str = "day"
    log_key: Optional[str] = None   # strings.json key for the radio-log line

    def __post_init__(self):
        _check(self.time_of_day, TIMES_OF_DAY, "time_of_day")


@dataclass(frozen=True)
class MapDef:
    key: str
    cols: int
    rows: int
    tile_size: int
    paths: Tuple[Tuple[Tuple[int, int], ...], ...]  # each path is a list of (col, row) corners
    waves: Tuple[WaveDef, ...]
    start_supply: int
    start_integrity: int
    resupply_bonus: int           # paid when a wave is cleared
    towers: Tuple[str, ...] = ()  # tower keys buildable on this map, in menu order
    base: Tuple[int, int] = (0, 0)  # tile where the trails end
    visibility: VisibilityRules = VisibilityRules()
    # (strings key, col, row, degrees) stamped on the map art
    labels: Tuple[Tuple[str, float, float, float], ...] = ()

    @property
    def world_size(self):
        return self.cols * self.tile_size, self.rows * self.tile_size


@dataclass(frozen=True)
class Content:
    """Everything the simulation needs, resolved by key."""
    towers: dict = field(default_factory=dict)
    enemies: dict = field(default_factory=dict)
    maps: dict = field(default_factory=dict)

    def validate(self):
        """Fail loudly on dangling keys so a bad edit never reaches a playtest."""
        for m in self.maps.values():
            for t in m.towers:
                if t not in self.towers:
                    raise ValueError(f"map {m.key}: unknown tower {t!r}")
            for i, wave in enumerate(m.waves):
                for g in wave.groups:
                    if g.enemy not in self.enemies:
                        raise ValueError(f"map {m.key} wave {i}: unknown enemy {g.enemy!r}")
                    if not 0 <= g.path < len(m.paths):
                        raise ValueError(f"map {m.key} wave {i}: bad path index {g.path}")
