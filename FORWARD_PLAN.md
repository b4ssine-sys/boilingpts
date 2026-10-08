# Forward Plan: Firebase Defense (Vietnam War Theme)

**Owner:** Creative Director  **Audience:** Engineering  **Status:** Draft v1
**Related docs:** `CREATIVE_BRIEF.md`, `ENGINEERING_REFERENCE.md`

## 0. Theme lock

- **Setting:** The Vietnam War, 1960s to early 1970s.
- **Player role:** A US firebase commander. US soldiers defend a hilltop firebase.
- **Opposition:** Guerrilla forces attacking from jungle trails, mostly at night and at first light.
- **Gameplay genre:** Top-down tower defense. Build defensive positions, survive waves, resupply, repeat.
- **Tone:** Grounded and documentary. No gore. No caricature. No glorification (rules in section 9).

Everything below serves that theme. Every system, string, and asset should read as part of a defended firebase at night.

---

## 1. Current state (baseline)

`tower-defense/main.py` is a 288-line Pygame prototype. Key locations:

| Area | Where | What it does today |
|---|---|---|
| Constants | lines 12-46 | Grid (20x15, 40px tiles), one tower cost/range/damage, five waves as `(count, hp, speed)` |
| Path | line 19 `PATH_CORNERS` | One path, built into `PATH_TILES` and `WAYPOINTS` |
| `Enemy` | line 70 | Walks waypoints, tracks `progress` |
| `Bullet` | line 101 | Homing projectile, applies fixed `TOWER_DAMAGE` |
| `Tower` | line 122 | Fires at furthest-along enemy in range |
| `Game` | line 140 | State, `try_build`, `update`, and all drawing in `draw` |
| Input | `main()` line 256 | Click to build, SPACE next wave, R restart |

**Gaps against the theme:** one tower, one enemy, one path, no visibility, no time of day, no theme text, no art, no audio, and win/lose copy is "YOU WIN!" / "GAME OVER".

---

## 2. Target for the vertical slice

One complete, playable firebase map with:

- 4 defensive structures: machine gun nest, mortar pit, claymore line, flare tower
- 3 guerrilla unit types: scouts, infantry, sappers
- 6 waves across dusk, full dark, and first light, with visibility rules
- Radio-log narrative, resupply helicopter drops, documentary end screens
- Field-map art direction (placeholder quality, final quality swappable in place)
- Stubbed audio hooks
- 60 FPS on a mid laptop (integrated graphics), 800x736 window

Out of scope for the slice: special abilities (artillery, medevac, air support), more than one map, licensed music, web or mobile ports, campaign structure.

---

## 3. Architecture changes (do these first)

### 3.1 Target file layout

```
tower-defense/
  main.py              entry point and loop only
  game/
    __init__.py
    config.py          window size, tile size, FPS, tuning constants
    palette.py         all color tokens
    defs.py            TowerDef, EnemyDef, WaveDef, PhaseDef + the data tables
    maps.py            MapDef (paths, base area, LZ, blocked tiles) + firebase_01
    sim.py             Game state and update() with no pygame drawing calls
    entities.py        Tower, Enemy, Projectile, Shell, Effect
    visibility.py      light sources, sight checks
    render/
      __init__.py
      world.py         map bake, structures, units, effects
      lighting.py      darkness overlay, gradient cache
      ui.py            HUD, build tray, radio log, banners, end screens
      fonts.py         font loading with fallbacks
    assets.py          image loader with fallback shapes
    audio.py           play(key) stub
    strings.py         loads strings.json
  strings.json         all user-facing text
  assets/              sprites, tiles, ui, fx, fonts, audio (empty at start)
  ASSETS.md            source and license for every asset
  tests/
```

`sim.py` must not import pygame drawing. It may import `pygame.math` only if needed. This keeps simulation testable and ports cheap.

### 3.2 Data definitions

```python
@dataclass(frozen=True)
class TowerDef:
    key: str                # "mg", "mortar", "claymore", "flare"
    cost: int
    hp: int
    range: float            # px, attack range
    min_range: float        # px, 0 for none
    cooldown: float         # s
    damage: float
    splash_radius: float    # 0 for none
    sight: float            # px, light and spotting radius
    placement: str          # "ground" | "trail"
    single_use: bool
    projectile: str         # "bullet" | "shell" | "none"

@dataclass(frozen=True)
class EnemyDef:
    key: str                # "scout", "infantry", "sapper"
    hp: float
    speed: float            # px/s
    reward: int             # supply points
    base_damage: int        # integrity lost on reaching the base
    behavior: str           # "follow_path" | "seek_tower"
    radius: float           # drawn and hit radius

@dataclass(frozen=True)
class PhaseDef:
    key: str                # "dusk", "dark", "dawn"
    tint: tuple             # RGB
    darkness_alpha: int
    sight_mult: float

@dataclass(frozen=True)
class WaveDef:
    phase: str
    groups: list           # [(enemy_key, count, interval_s, path_index)]
    hp_mult: float
    # banner/start/clear text lives in strings.json, indexed by wave number
```

Acceptance: swapping a number in `defs.py` changes behavior with no other edits, and no gameplay constants remain in `sim.py`.

### 3.3 Fixed timestep
Run the simulation at a fixed 1/60 s step with an accumulator, and render at display rate. This makes tests deterministic and keeps frame hitches from changing outcomes.

### 3.4 Determinism
All randomness goes through one seeded `random.Random` held by `Game`. Visual-only randomness (rain, sparks) uses a separate RNG so it never affects simulation.

---

## 4. Workstreams and tasks

Estimates are in engineer-days for one engineer already familiar with the repo. IDs are for ticketing.

### WS1: Refactor and data (blocks everything)

| ID | Task | Detail | Accept when | Est |
|---|---|---|---|---|
| E1.1 | Split module layout | Create package per 3.1, move code without behavior change | Game plays identically to current `main.py` | 1 |
| E1.2 | Defs and tables | Implement dataclasses and move all constants to `defs.py` and `config.py` | No magic numbers left in `sim.py` | 1 |
| E1.3 | Multi-path maps | `MapDef` with a list of paths, base tile set, LZ tile, blocked tiles. Enemies carry their own path | Two paths load and enemies follow the right one | 1 |
| E1.4 | Fixed timestep | Accumulator loop in `main.py` | Same seed gives same result across runs | 0.5 |
| E1.5 | Strings table | `strings.json` loader. Every user-facing string goes through `strings.get(key)` | Grep finds no hard-coded UI text in `render/` or `sim.py` | 0.5 |
| E1.6 | Test harness | pytest setup, headless pygame (`SDL_VIDEODRIVER=dummy`) | `pytest` runs green in CI | 0.5 |

### WS2: Towers and combat

| ID | Task | Detail | Accept when | Est |
|---|---|---|---|---|
| E2.1 | Per-tower targeting | Strategy per tower: `first` (max progress), `cluster` (most neighbors within splash) | Unit tests per strategy | 1 |
| E2.2 | Machine gun nest | cooldown 0.18 s, damage 4, range 110, sight 120, hp 60. Tracer projectile | Fires continuously, rotates toward target with easing | 0.5 |
| E2.3 | Mortar pit | cooldown 2.2 s, damage 28, splash radius 48, range 230, min range 80, sight 70, hp 50. Shell with flight time 0.6 to 1.4 s, lead on target velocity | Cannot target inside min range, splash hits all in radius | 1.5 |
| E2.4 | Claymore line | Placement on trail tiles only, excluding base area and spawn column. Triggers when an enemy is within 28 px. Burst deals 50 damage within 60 px, then the tower is removed | Single use, removed after trigger, damage verified in test | 1 |
| E2.5 | Flare tower | No attack. Sight 190. Towers inside its light radius at night get a 1.35x damage multiplier | Multiplier applies only in `dark` and `dusk` phases and only within radius | 1 |
| E2.6 | Tower hit points | All structures have hp. Destroyed at hp <= 0, tile freed, radio line fires | Tile can be rebuilt after loss | 0.5 |
| E2.7 | Build tray state | Selected structure type (keys 1-4 and click), cost check, validity rules per placement type | Invalid placement shows red ghost and does nothing | 1 |

Initial tuning (all adjustable in `defs.py`):

| Structure | Cost | HP | Range | Cooldown | Damage | Notes |
|---|---|---|---|---|---|---|
| MG nest | 40 | 60 | 110 | 0.18 | 4 | min_range 0 |
| Mortar pit | 90 | 50 | 230 | 2.2 | 28 | splash 48, min_range 80 |
| Claymore | 25 | 1 | n/a | n/a | 50 | burst radius 60, trigger 28 |
| Flare | 60 | 40 | n/a | n/a | 0 | sight 190, accuracy x1.35 |

### WS3: Guerrilla units and waves

| ID | Task | Detail | Accept when | Est |
|---|---|---|---|---|
| E3.1 | Scout | hp 18, speed 110, reward 6, base damage 1 | Visible spawn and behavior in test wave | 0.5 |
| E3.2 | Infantry | hp 40, speed 70, reward 10, base damage 1 | Baseline unit | 0.25 |
| E3.3 | Sapper | hp 35, speed 60, reward 14, base damage 2. Within 90 px of a tower it diverts toward the nearest tower, deals 40 damage on contact and is removed. If the tower dies first it resumes the path from its current position | State machine test: divert, detonate, resume | 1.5 |
| E3.4 | Wave scheduler | Expand each `WaveDef` group into a timeline of `(t, enemy, path)`, merged and sorted. `hp_mult = 1 + 0.1 * wave_index` | Mixed groups spawn concurrently on separate paths | 1 |
| E3.5 | Six waves | Content table below | All six reachable in playtest | 0.5 |

Wave table (draft, tune in playtest):

| Wave | Phase | Groups (unit x count, interval s, path) |
|---|---|---|
| 1 | dusk | infantry x6, 0.9, N |
| 2 | dark | scouts x8, 0.6, S + infantry x4, 1.0, N |
| 3 | dark | infantry x8, 0.8, N + infantry x8, 0.8, S + sappers x2, 3.0, S |
| 4 | dawn | scouts x10, 0.5, N + infantry x10, 0.7, S + sappers x3, 2.5, N |
| 5 | dark | sappers x4, 2.2, N + sappers x4, 2.2, S + scouts x12, 0.45, S + infantry x8, 0.9, N |
| 6 | dawn | infantry x14, 0.6, N + infantry x14, 0.6, S + scouts x10, 0.5, S + sappers x5, 2.0, N |

### WS4: Visibility and day/night (highest risk)

| ID | Task | Detail | Accept when | Est |
|---|---|---|---|---|
| E4.1 | Phase model | `PhaseDef` table. Phase set at wave start. Tint color, darkness alpha, and sight multiplier lerp over 3 s | Transition is smooth, no pop | 1 |
| E4.2 | Light sources | Every structure contributes `sight * sight_mult`. The firebase lamp adds a base radius around the compound. Temporary lights from muzzle flashes, bursts, and impacts affect rendering only | Light list rebuilt per frame without allocation spikes | 1 |
| E4.3 | Visibility rule | Enemy is visible if within any light radius. Hidden enemies cannot be targeted. Enemies within 45 px outside a radius draw as a faint contact mark | Hidden enemy never targeted, verified in test | 1 |
| E4.4 | Spotting for mortars | Mortars may fire at any enemy visible to any light source, not only their own | Mortar fires at enemy lit by a distant flare | 0.5 |
| E4.5 | Darkness overlay | Per-frame RGBA overlay filled with tint, light gradients punched out with `BLEND_RGBA_SUB`, warm additive glow pass on top | Matches visibility rule; no enemy visible outside a lit zone | 2 |
| E4.6 | Gradient cache | Pre-render alpha and glow gradient sprites by radius bucket (round to 4 px) | No gradient math in the frame loop | 0.5 |
| E4.7 | Perf budget | Profile at wave 6 with all structures built | Frame time under 16 ms; if over, render the overlay at half resolution and upscale | 1 |

Recommendation: start E4.5 as a standalone spike in week 1 and report frame cost before the rest of WS4 is built.

### WS5: Economy, flow, and narrative

| ID | Task | Detail | Accept when | Est |
|---|---|---|---|---|
| E5.1 | Resource rename | Gold becomes Supply Points, Lives becomes Base Integrity (20 start) in code and UI | Grep finds no `gold` or `lives` identifiers | 0.5 |
| E5.2 | Resupply drop | After each cleared wave, a helicopter crosses the map, drops a crate at the LZ, and +30 supply applies when the crate lands | Supply increases at landing, not at wave end | 1.5 |
| E5.3 | Radio log | Scrolling queue of the last 4 lines, newest typed out at ~45 chars/s, older lines fade | Wave start and clear lines pulled from `strings.json` | 1 |
| E5.4 | Wave banner | Stamped banner slides in for 0.4 s, holds 2.2 s, fades | Shows `banner` string and phase name | 0.5 |
| E5.5 | End screens | Debrief card: title, subtitle, context paragraph, wave stats, restart prompt | Win/lose copy comes only from `strings.json` | 1 |
| E5.6 | Wave call hint | HUD shows the next wave's phase so the player can prepare | Phase named before SPACE is pressed | 0.25 |

### WS6: Graphics overhaul

Follow `ENGINEERING_REFERENCE.md` section 4 for the full spec. Task breakdown:

| ID | Task | Detail | Accept when | Est |
|---|---|---|---|---|
| G6.1 | Palette module | All color tokens from the reference in `palette.py` | No raw RGB tuples outside `palette.py` | 0.5 |
| G6.2 | Asset loader | Load by key, return a fallback shape if missing | Deleting any asset never crashes the game | 1 |
| G6.3 | Baked map | Paper texture, speckle, fold lines, vignette, jungle hatching, hill contours, trails with irregular edges, grease-pencil route dashes and chevrons, stamped labels (NORTH TREELINE, SOUTH TRAIL, FIREBASE, LZ) | Map builds once at load, then is blitted | 3 |
| G6.4 | Firebase compound | Sandbag perimeter, tents, radio tent with a lit window, drawn into the baked map | Reads as a base at a glance | 1 |
| G6.5 | Structure sprites | MG nest (sandbag ring, barrel, rotates), mortar pit (earth pit, tube), claymore (curved plate, armed pulse), flare tower (pole, flickering lamp) | Distinct by silhouette in grayscale | 3 |
| G6.6 | Unit sprites | Scout (slim), infantry (round), sapper (pack outline). Neutral treatment, movement bob, shadow | Distinct by silhouette in grayscale | 2 |
| G6.7 | Effects | Muzzle flash, tracers, mortar arc with growing shadow and dust, claymore fan burst, flare light, helicopter and crate, rain, mist, embers | Each effect has a duration, a pool cap, and is additive where noted | 4 |
| G6.8 | Casualty feedback | Units desaturate and fade out. No blood, bodies, or ragdolls | Verified against section 9 checklist | 0.5 |
| G6.9 | UI rebuild | Paper panels, stamped HUD strip, build tray cards with icon, cost, key hint, range ring on hover (mortar shows min-range ring), animated counters | Matches reference section 4.7 | 3 |
| G6.10 | Typography | Typewriter face for log and body, stencil face for labels. Licenses recorded in `ASSETS.md` | All fonts load, with system fallbacks | 0.5 |
| G6.11 | Screen shake | Claymore and mortar impacts, 2-3 px, 120 ms, with a settings toggle | Toggle disables it fully | 0.5 |
| G6.12 | Title screen | Animated map with slow drift, rain, distant flare | Start, quit, and settings entries | 1.5 |

### WS7: Audio hooks

| ID | Task | Detail | Accept when | Est |
|---|---|---|---|---|
| A7.1 | `audio.play(key)` | Single entry point, silent stub when a file is missing | No audio calls outside `audio.py` | 0.5 |
| A7.2 | Event wiring | Keys: `mg_fire`, `mortar_fire`, `mortar_impact`, `claymore`, `flare_launch`, `heli`, `crate_land`, `radio_open`, `wave_start`, `base_hit`, `structure_lost`, ambience loop by phase | Events fire at the right moments (verify with logging) | 1 |
| A7.3 | Mixer settings | Master, effects, ambience, radio volumes; mute toggle | Settings persist between runs | 1 |

### WS8: QA, tuning, and review

| ID | Task | Detail | Accept when | Est |
|---|---|---|---|---|
| Q8.1 | Unit tests | Targeting, min range, splash, claymore trigger, sapper state machine, visibility, wave scheduler, economy | Coverage on `sim.py` above 80% | 2 |
| Q8.2 | Replay test | Seeded scripted run (build order plus wave calls) must end in a known state | Fails if sim behavior changes unexpectedly | 1 |
| Q8.3 | Balance bot | Headless bot with 2-3 build strategies run across seeds, win rate reported | Target 40-70% win rate for a reasonable build | 2 |
| Q8.4 | Perf test | Frame-time capture at wave 6 | Budget in E4.7 met | 0.5 |
| Q8.5 | Content audit | Script scans `strings.json` and sprites for banned terms and graphic assets | Passes against checklist in section 9 | 0.5 |

---

## 5. Milestones and sequencing

| Milestone | Contains | Depends on | Exit criteria |
|---|---|---|---|
| **M0: Spike** (week 1) | E4.5 lighting spike, E4.7 profile | none | Frame cost known; go/no-go on overlay approach |
| **M1: Foundation** | WS1, G6.1, G6.2, E5.1 | none | Game plays as before, from data tables, with themed names |
| **M2: Content** | WS2, WS3, E5.2 | M1 | All 4 structures, 3 units, 6 waves playable, with placeholder shapes |
| **M3: Night** | WS4 | M0, M2 | Visibility and day/night rules working end to end |
| **M4: Look** | G6.3 to G6.12, E5.3 to E5.6 | M2 (G6.3 and G6.4 can start after M1) | Full art pass in placeholder quality, UI rebuilt, radio log live |
| **M5: Sound and polish** | WS7, tuning from Q8.3 | M3, M4 | Hooks wired, balance in target range, perf budget met |
| **M6: Review build** | Q8.1 to Q8.5, bug fixes | M5 | Build handed to sensitivity review and internal playtest |

Rough total: about 45 engineer-days. With two engineers, expect 5 to 6 weeks including review loops. Parallel tracks after M1: one engineer on gameplay (WS2, WS3, WS4), one on graphics and UI (WS6, E5.3 to E5.6).

---

## 6. Definition of done (per task)

1. Code merged with passing tests and lint.
2. No new hard-coded UI text or magic numbers.
3. Works at 60 FPS in the wave 6 scenario.
4. If the task changes visuals, a screenshot is attached to the ticket and checked against section 9.
5. If the task changes tuning, the balance bot is rerun and the result noted.

---

## 7. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Darkness overlay too slow in Pygame | Misses 60 FPS | M0 spike, half-resolution overlay, cached gradients, fallback to tile-based light mask |
| Visibility makes the game feel unfair | Frustration | Faint contact marks, radio hints, generous dusk and dawn multipliers, tune in Q8.3 |
| Sapper behavior bugs (stuck, oscillation) | Broken waves | Explicit state machine, tests, re-acquire rules |
| Scope creep into abilities and extra maps | Slice slips | Hooks only; log new ideas in a backlog file |
| Placeholder art ships by accident | Quality | `ASSETS.md` tracks status per asset; build script flags placeholders |
| Pygame limits web and mobile later | Rework | Keep sim separate from render (3.1), evaluate `pygame-ce` and shader options in a later spike |
| Sensitive content slips through in text or art | Reputation | Single strings table, content audit script, consultant review before locking narrative |

---

## 8. Open questions for engineering

1. Estimates for E4.5 and E2.3, and whether M0 can be done this week.
2. Is `pygame-ce` acceptable? It is largely compatible and may help the lighting pass.
3. Preferred format for map definitions: Python module or JSON/Tiled export.
4. Do we want a replay or recording system for balance testing (Q8.2 starts it)?
5. Any CI platform constraints for headless pygame?

Decisions needed from me: working title, budget confirmation for the consultant, and sign-off on the six-wave table after the first balance run.

---

## 9. Content rules and review checklist

Apply to code, strings, assets, screenshots, and marketing.

1. **No gore.** Casualties are shown through UI changes, desaturate-and-fade, and sound. No blood, bodies, or ragdolls on any side.
2. **No caricature.** Guerrilla units use neutral, period-accurate designations ("contact", "element", "formation"). No slurs, slang, jokes, or mocking language, including in placeholders and debug strings.
3. **No glorification.** End screens use a documentary tone with a short historical context card. Replace "YOU WIN!" and "GAME OVER" with "PERIMETER HELD" and "POSITION LOST" or consultant-approved equivalents.
4. **One strings table.** All narrative text lives in `strings.json`, flagged DRAFT until the consultant approves it.
5. **Human cost stays visible.** Base Integrity represents people. Tooltips and radio lines refer to positions and perimeter, and never treat losses as a score to celebrate.
6. **Marketing follows the same rules.** Thumbnails and trailers use the field-map look and light effects, with no graphic imagery.

Review checklist for each milestone build:

- [ ] Screenshots of every unit and effect reviewed against rules 1 and 2
- [ ] `strings.json` diffed and scanned
- [ ] End screens read in sequence for tone
- [ ] Window title, menu text, and file names contain no placeholder jokes
- [ ] Consultant notes triaged and tracked

---

## 10. Handoffs

| From | To | What | When |
|---|---|---|---|
| Creative Director | Engineering | This plan, tuning tables, palette | Now |
| Engineering | Creative Director | M0 spike result and estimates | End of week 1 |
| Engineering | Concept artist | Sprite size specs, atlas format, `ASSETS.md` | M4 start |
| Concept artist | Engineering | Final sprites and UI kit | After M4, drop-in replacement |
| Engineering | Sound designer | Event key list from A7.2 | M5 start |
| Engineering | Consultant (via Creative Director) | `strings.json`, screenshots, review build | M6 |
