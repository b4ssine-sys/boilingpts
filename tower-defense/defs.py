"""Content definitions. Plain data, no pygame, no game logic.

Designers tune numbers in content.py. Anything a player can read lives in
strings.json and is looked up by key (see strings.py), so these classes carry
ids, never display text.
"""
from dataclasses import dataclass, field
from typing import Optional, Tuple

PLACEMENTS = ("ground", "trail")
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

    def __post_init__(self):
        _check(self.placement, PLACEMENTS, f"{self.key}.placement")


@dataclass(frozen=True)
class EnemyDef:
    key: str
    hp: float
    speed: float                  # world units per second
    behavior: str = "follow_path"  # follow_path | seek_tower
    visibility: str = "standard"  # profile name, defined by the M3 visibility system
    kill_reward: int = 10

    def __post_init__(self):
        _check(self.behavior, BEHAVIORS, f"{self.key}.behavior")


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
    towers: Tuple[str, ...] = ()  # tower keys buildable on this map

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
