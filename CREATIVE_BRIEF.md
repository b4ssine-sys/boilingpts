# Creative Brief: Vietnam War Tower Defense

**To:** Creative Director
**Status:** Playable prototype exists (Python/Pygame). Theme reskin proposed below.

## 1. Pitch

A top-down tower defense game set during the Vietnam War. The player commands a besieged firebase and holds it through a series of night and dawn assaults, spending limited supplies on defensive positions and support. The core loop is already working: build, survive the wave, resupply, repeat.

The goal is a tense, grounded strategy game with a clear period identity, built with restraint toward its subject matter.

## 2. Where we are

- Prototype with one map, one tower type, one enemy type and five waves.
- Core systems in place: path-following enemies, tower placement, gold, lives, wave progression, win and lose states.
- All art is placeholder (colored shapes), so the theme can be set without rework.

## 3. Perspective (decision needed)

The choice of whose story we tell shapes every other decision.

| Option | Description | Notes |
|---|---|---|
| **A. Defending a firebase (recommended)** | Player is a US/allied base commander holding a hilltop or river outpost. | Fits tower defense naturally. Most common treatment in the genre, so the least differentiated. |
| **B. Defending a village** | Player organizes local defenses around a rural settlement. | Opens room for a human-scale story. Needs careful research and consultation. |
| **C. Campaign across both sides** | Alternating missions from different perspectives. | Strongest narrative, largest scope and sensitivity burden. |

Recommendation: ship Option A as the vertical slice, and revisit B or C after a sensitivity and research review.

## 4. Mechanics mapped to theme

| Current prototype | Themed version |
|---|---|
| Tower | Defensive positions: machine gun nest, mortar pit, claymore line, sandbagged bunker |
| Gold | Supply points |
| Wave bonus | Resupply helicopter drop |
| Lives | Base integrity or morale |
| Path | Jungle trail or river approach |
| Wave | Night probe, dawn assault, mortar barrage |
| Special ability (future) | Artillery strike, flare illumination, medevac, air support on cooldown |

Proposed first tower roster:

1. **Machine gun nest**: fast fire, low damage, short range.
2. **Mortar pit**: slow, splash damage, long range, cannot hit close targets.
3. **Claymore line**: placed on the trail itself, single use, high burst damage.
4. **Flare tower**: no damage, extends visibility and boosts nearby accuracy at night.

Proposed enemy roster: scouts (fast, fragile), infantry (baseline), sapper units (target towers directly), and later waves with mixed formations. Mechanics lean on fog of war and visibility at night to create tension without needing graphic content.

## 5. Art direction

- **Palette:** olive drab, khaki, faded red clay, jungle greens, warm amber for flares and muzzle light. Muted overall, with light used as the main accent.
- **View:** top-down 2D with a hand-drawn field-map look: grease-pencil marks, folded paper edges, stamped labels.
- **UI:** typewriter and stencil typography, radio-log style wave announcements ("Contact, north treeline").
- **Day/night cycle:** waves alternate between dusk, full dark and dawn, which changes visibility and gameplay.

## 6. Audio direction

- Layered jungle ambience (insects, rain, distant artillery), radio chatter, sparse and tense score.
- Period licensed music is a possible feature for menus or a supply-drop jingle. It needs a licensing budget, so it is optional for the slice.

## 7. Tone and responsible portrayal

This subject involves real people and real loss. Proposed guardrails:

- No gore. Casualties are communicated through UI and sound, not graphic imagery.
- Enemy units are not caricatured or dehumanized. Names, unit designations and radio language stay neutral and period-accurate.
- Avoid glorification. Win screens and mission text can carry a documentary tone, with short historical context for each map.
- Engage a historical consultant (ideally including Vietnamese and veteran voices) before locking narrative content.
- Review the title, marketing copy and store-page language through the same lens.

## 8. Open questions for you

1. Which perspective (A, B or C) do we commit to?
2. What age rating are we targeting? This affects how casualties are portrayed.
3. Is there a budget for a historical consultant and licensed music?
4. Do we want a narrative frame (letters home, radio log, commander's journal) or a pure systems-driven game?
5. Platform and distribution: desktop only, or browser and mobile later? This could mean porting off Pygame.

## 9. Proposed next steps

1. **Sign-off on perspective and tone** (this brief).
2. **Themed vertical slice:** reskin to placeholder themed art, add the four towers, three enemy types, day/night visibility, and a first firebase map.
3. **Art and audio pass** with a concept artist and sound designer.
4. **Playtest and sensitivity review**, then plan campaign scope.
