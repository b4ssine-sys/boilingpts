# Creative Direction Reference: Firebase Defense (working title)

**From:** Creative Director
**To:** Engineering
**Status:** Draft v1 for the vertical slice
**Companion doc:** `CREATIVE_BRIEF.md`

This reference maps the creative decisions to the existing prototype in `main.py` (288 lines, Pygame). It covers gameplay content, a full graphics overhaul, content rules, and milestones.

---

## 1. Decisions

| Question | Decision |
|---|---|
| Perspective | **Option A**, defending a firebase. B and C wait for the sensitivity review. |
| Narrative frame | **Radio log.** It fits the HUD, costs little, and carries tone. |
| Age rating target | **Teen (ESRB T / PEGI 12).** This sets the casualty rules in section 6. |
| Platform | **Desktop, Pygame, for the slice.** Keep simulation separate from rendering (3.1) so a later port is cheap. |
| Consultant and licensed music | **Consultant: yes, budget request going up.** Licensed music is cut from the slice. |

Open items: budget approval and the working title. Keep the title out of the window caption and store assets until it is locked.

---

## 2. Current prototype

- One path (`PATH_CORNERS`), one tower type (`TOWER_*` constants), one enemy type, five waves in the `WAVES` list.
- Towers always target the enemy furthest along the path (`max(..., key=progress)`).
- Gold, lives, win/lose states, and a flat `WAVE_BONUS` are in place.
- All visuals are solid-color shapes drawn inside `Game.draw`.

---

## 3. Gameplay engineering asks

### 3.1 Data-driven content
Move the module constants into definitions so designers can tune without touching logic.

- `TowerDef`: name, cost, range, min_range, cooldown, damage, splash_radius, placement rule (`ground` or `trail`), single_use flag.
- `EnemyDef`: name, hp, speed, behavior (`follow_path` or `seek_tower`), visibility profile.
- `WaveDef`: list of (enemy type, count, interval), time of day, radio-log text.

Keep `Game.update` free of pygame calls. Simulation and presentation must be separable.

### 3.2 Tower roster (four)

| Tower | Behavior | Engineering notes |
|---|---|---|
| Machine gun nest | Fast fire, low damage, short range | Closest to the current tower. Tune numbers. |
| Mortar pit | Slow, splash damage, long range, `min_range` blind zone | Needs splash on impact and a minimum-range check in targeting. |
| Claymore line | Placed on path tiles, single use, high burst | Inverts the "no building on the path" rule in `try_build`. Triggers on enemy contact, then is removed. |
| Flare tower | No damage. Extends visibility radius and boosts nearby tower accuracy at night | Depends on the visibility system (3.4). |

Targeting becomes a per-tower strategy rather than a fixed `max(progress)`.

### 3.3 Enemy roster (three for the slice)
- **Scout:** fast, fragile.
- **Infantry:** baseline.
- **Sapper:** diverts from the path to attack the nearest tower. Needs a new behavior state and tower HP.

Later waves mix formations, so `WaveDef` should allow multiple spawn groups.

### 3.4 Day/night and visibility
The main tension mechanic and the largest new system.

- Waves carry a time-of-day tag: dusk, dark, or dawn.
- At night each tower has a sight radius. Enemies outside every sight radius are hidden or shown only as faint contact marks. Flares enlarge the radius.
- Towers cannot target enemies they cannot see. Mortars may fire on last-known contact positions.
- Rendering is covered in 4.6.

### 3.5 Economy and flow
- Rename Gold to **Supply Points** and Lives to **Base Integrity** (display strings first).
- The wave bonus becomes a **resupply drop** event with an animation and a radio line.
- Waves are announced through a radio-log panel fed from `WaveDef`.
- Special abilities (artillery, on-demand flares, medevac, air support) are out of scope for the slice. Leave a hook for cooldown abilities and build nothing further.

### 3.6 Map
One firebase map: hilltop perimeter with two approach trails. The single `PATH_CORNERS` list becomes a list of paths per map.

---

## 4. Graphics overhaul

**Goal:** a game that is visually striking in a screenshot, a 15-second clip, and a store thumbnail. The look is a living field map: hand-drawn, tactile, warm light against a muted world. Light is the hero of every frame.

### 4.1 Visual pillars
1. **Muted world, glowing light.** Terrain stays desaturated. Flares, muzzle flashes, tracers, and lit windows of the radio tent carry the saturation and the eye.
2. **Tactile paper.** The map feels like a physical object: paper grain, fold creases, tape, stamped ink, grease-pencil annotations.
3. **Readable at a glance.** Every tower, enemy, and range ring is identifiable by silhouette first and color second. Check readability in grayscale.
4. **Motion with restraint.** Small, constant, quiet motion (foliage sway, rain, smoke, flickering light) keeps the screen alive without noise.

### 4.2 Palette and tokens
Define all colors in one `palette.py` (or JSON) and never hard-code RGB elsewhere.

| Token | Hex | Use |
|---|---|---|
| `paper` | `#D9CFAE` | Map base, UI panels |
| `paper_shadow` | `#B9AE8A` | Folds, panel edges |
| `olive_drab` | `#6B6B3A` | Friendly structures, UI accents |
| `khaki` | `#B5A67A` | Sandbags, trails (day) |
| `clay` | `#A4543A` | Dirt, trail wear, stamped red labels |
| `jungle_dark` | `#2F4630` | Dense canopy, night base |
| `jungle_mid` | `#3F5B3A` | Foliage |
| `jungle_light` | `#5E7A45` | Foliage highlights |
| `ink` | `#1E1B16` | Text, outlines |
| `amber` | `#F2B14A` | Flares, muzzle light, resupply glow |
| `amber_hot` | `#FFE2A0` | Flare core, tracer heads |
| `night_tint` | `#10162A` at ~70% | Darkness overlay |

Keep a day, dusk, night, and dawn tint set per map so the time-of-day tag in `WaveDef` drives the whole grade.

### 4.3 Map and terrain rendering
- **Base layer:** paper texture tiled and lightly vignetted, with subtle fold lines (one horizontal, one vertical) and a darker edge.
- **Terrain layer:** replace flat tile squares with hand-drawn style terrain. Contour lines for the hill, hatching for jungle, scribbled marsh patches, a drawn river with a light edge.
- **Trails:** a worn dirt band with irregular edges, plus grease-pencil arrows and dashed route marks laid over the top.
- **Placement tiles:** a faint pencil grid appears only while the player is placing a structure, and valid tiles get a soft amber outline.
- **Pre-render:** bake the static map into one cached surface at load. Only dynamic layers redraw per frame.
- **Annotations:** stamped labels ("NORTH TREELINE", "LZ", "WIRE") in stencil type, slightly rotated, with ink-bleed texture.

### 4.4 Structures and units
Top-down sprites with strong silhouettes, drawn at 2x and downscaled for crispness.

- **Machine gun nest:** sandbag ring, barrel pointing at target, small muzzle flash.
- **Mortar pit:** circular pit with tube angled up and a crew marker. Smoke puff on fire.
- **Claymore line:** a dashed row of small curved plates on the trail, with a pulse of amber when armed.
- **Flare tower:** pole with an amber lamp that flickers, casting the largest visible light pool.
- **Enemies:** small, readable markers with distinct silhouettes per type (scout slim and quick, infantry round, sapper with a pack-like outline). Each has a subtle shadow and a movement bob. All enemies use the same neutral treatment as friendly units (see section 6).
- **Health:** thin ink-line bars that appear on hit and fade, so the screen stays clean.
- **Rotation:** structures rotate toward their target with easing.

### 4.5 Effects (the "wow" layer)
| Effect | Implementation notes |
|---|---|
| Muzzle flash | 2-3 frame additive sprite plus a short-lived radial light on the light layer |
| Tracers | Fading streak with an `amber_hot` head, additive blend |
| Mortar shell | Arc with growing and shrinking shadow, impact ring and dust cloud |
| Claymore burst | Fan-shaped flash with a short screen shake (2-3 px, 120 ms) |
| Flare launch | Rising spark trail, then a swinging, flickering light pool that decays over several seconds |
| Resupply drop | Helicopter shadow crossing the map, crate parachute, amber smoke marker, supply counter ticking up |
| Rain | Sparse streaks at an angle, plus ripple dots on the paper (night waves) |
| Ambient | Drifting mist, swaying foliage (sine offset on foliage sprites), floating embers near flares |
| Hit feedback | Small ink-splat style marker and a damage tick on the UI, with no gore (section 6) |

Casualty feedback uses a quick desaturate-and-fade on the unit plus an audio cue. Nothing graphic is drawn.

### 4.6 Lighting and day/night
Render order: terrain, structures, units, effects, **darkness overlay**, light glows, UI.

- Build one `darkness` surface per frame, filled with `night_tint` at the current time-of-day alpha.
- For each light source (flare, muzzle flash, lamp), draw a precomputed radial gradient with `BLEND_RGBA_SUB` to punch light into the darkness, then a second additive pass in `amber` for the warm glow.
- Cache gradient sprites per radius bucket. Never compute gradients per frame.
- Transitions between dusk, dark, and dawn lerp the tint alpha and color over about 3 seconds, timed with a radio line.
- Visibility from 3.4 shares the same light radii, so the picture and the rules agree.

Performance target: 60 FPS at 800x640 on a mid laptop with no discrete GPU. If the overlay costs too much, render the darkness at half resolution and upscale.

### 4.7 UI and typography
- **Panels:** paper cards with taped corners and drop shadows. Resource counters sit on a stamped strip across the top.
- **Type:** a typewriter face for the radio log and body text, a stencil face for labels and buttons. Use freely licensed fonts and record each license in `ASSETS.md`.
- **Radio log:** lines type out character by character with a soft key click, newest line at the bottom, older lines fading.
- **Build menu:** a bottom tray of four tower cards (icon, cost, one-line role). Hover shows the range ring and, for the mortar, the blind-zone ring.
- **Wave banner:** a stamped "DUSK. CONTACT, NORTH TREELINE" slide-in at wave start.
- **Counters:** supply and base-integrity numbers animate on change (count tween, brief amber pulse on gain, muted ink pulse on loss).
- **End screens:** a debrief card with a short historical-context paragraph, wave stats, and a restart stamp. Documentary tone throughout.
- **Menus:** the title screen shows the animated map with a slow camera drift, rain, and a distant flare.

### 4.8 Motion and polish
- Ease all UI transitions (150-250 ms, ease-out).
- Subtle parallax on foliage and mist layers when the camera is stationary (slow drift).
- Soft screen shake only for claymore and mortar impacts, with an accessibility toggle.
- Hover and click feedback on every interactive element.

### 4.9 Asset pipeline
- Folder layout: `assets/{sprites,tiles,ui,fx,fonts,audio}`.
- `assets.py` loads images by key and returns a colored-shape fallback if a file is missing, so the game never breaks mid-art-handoff.
- Sprite sheets with a JSON atlas for animations. Authoring size is 2x, runtime scales to the display.
- Use `convert_alpha()` once at load, never per frame.
- `ASSETS.md` tracks source, author, and license for every asset.

### 4.10 Graphics milestones
| Step | Deliverable |
|---|---|
| G1 | Palette module, asset loader with fallbacks, baked paper-map background |
| G2 | Four structure sprites and three enemy sprites in placeholder style, rotation and shadows |
| G3 | Effects pass: muzzle flash, tracers, mortar arc, claymore burst, flare |
| G4 | Lighting system and day/night grading |
| G5 | UI rebuild: paper panels, radio log typing, build tray, wave banner, end cards |
| G6 | Ambient layer, menus, final polish and performance pass |

The concept artist replaces placeholder sprites in place as finals arrive. No code changes should be needed beyond new atlas entries.

---

## 5. Audio handoff

- Ambience loop (insects, rain, distant artillery), radio chatter one-shots keyed to wave start, supply-drop sting, and distinct fire sounds per tower.
- Silent stubs are fine until the sound designer is on board. Route all audio through one `audio.play(key)` call.
- Licensed period music is out of scope for the slice.

---

## 6. Content rules (apply to code, text, and assets)

1. **No gore.** Casualties show through UI changes, desaturate-and-fade, and sound. No blood, bodies, or ragdolls, for any side.
2. **No caricature.** Enemy units get neutral, period-accurate designations in the UI and log (for example "Contact, north treeline"). No slurs, slang, or mocking language anywhere, including placeholder strings and debug text.
3. **No glorification.** Win and lose screens use a documentary register with a short historical-context card per map. Replace "YOU WIN!" and "GAME OVER" accordingly.
4. **All narrative strings live in one table** (`strings.json` or similar) so the consultant can review and edit without touching code.
5. **Nothing historical is final until the consultant reviews it.** Mark all narrative text as draft in the strings table.
6. **Marketing visuals follow the same rules.** Thumbnails, trailers, and store screenshots use the field-map look and light effects, with no graphic imagery.

---

## 7. Milestones

| Milestone | Scope |
|---|---|
| M1 | Data-driven refactor (3.1), renamed resources (3.5), multi-path maps (3.6). Gameplay output unchanged. |
| G1 | Palette, asset loader, baked map (can run in parallel with M1) |
| M2 | Four towers, three enemies, firebase map, wave definitions |
| G2-G3 | Placeholder sprites and effects pass |
| M3 | Visibility and day/night rules, built with G4 lighting as one workstream |
| G5 | UI rebuild with radio log and build tray |
| M4 / G6 | Ambient layer, audio stubs, polish, performance pass |
| M5 | Playtest build for sensitivity and design review |

Flag anything in M3/G4 that threatens 60 FPS. The darkness overlay is the likely cost.

---

## 8. Questions back to engineering

- Effort estimates for M1 and M3/G4, and whether the lighting system should start as a standalone spike.
- Any objection to Pygame for the slice, given the web and mobile question is still open.
- Preferred format for the strings table (JSON, YAML, or CSV).
- Whether a shader-capable backend (for example `pygame-ce` with `moderngl`) is worth evaluating for the lighting pass.
