# M3/G4 lighting spike: findings

Question: can the darkness overlay hold 60 FPS at 800x640, and what is the
cheapest way to build it? Code: `lighting_spike.py` (standalone, not imported by
the game). Run `python spikes/lighting_spike.py`; add `--shot out.png` to save a
lit frame.

## Method
Real baked map and real towers, wave 8 running, dark tint (alpha 178). Lights
are flares (radius 170, flickering), tower sight pools (105) and muzzle flashes
on bullets (38). Each strategy is timed for the overlay only, 400 frames after a
60-frame warm-up. Two runs, means below are from run 2 (run 1 within ~10%).

## Results (mean ms per frame; p99 in brackets)

| Strategy | 6 lights | 14 lights | 25 lights |
|---|---|---|---|
| full resolution | 3.0 (4.7) | 6.1 (12.9) | **9.0 (16.5)** |
| half | 2.5 (4.5) | 3.6 (8.0) | 4.3 (7.6) |
| half, nearest upscale | 1.5 (3.9) | 2.4 (5.3) | 3.4 (5.8) |
| quarter | 1.9 (3.5) | 2.6 (3.9) | 2.9 (4.7) |
| **half + static layer** | 2.3 (3.6) | 2.5 (4.0) | **2.7 (4.2)** |
| quarter + static layer | 1.8 (3.2) | 1.9 (2.9) | 2.2 (4.4) |

Other costs: warm glow pass 0.2-0.7 ms; the visibility rule ("an enemy is seen
if any light source reaches it") 0.06-0.09 ms for 60 enemies and up to 25
sources.

## What the numbers say
- **Full resolution does not fit.** Cost grows with lit area (8 ms of punching
  at 25 lights) and p99 reaches 16 ms, which is the whole frame budget.
- **Half resolution is the fix.** Punching cost falls about 4x.
- **A cached layer for steady lights flattens the curve.** Tower sight pools do
  not move, so they are punched once and the layer is copied each frame. Only
  flares and muzzle flashes are punched per frame. Cost stops depending on how
  many towers the player builds.
- **What is left is the upscale and blit**, about 1.7 ms. Nearest-neighbour
  scaling saves ~0.8 ms but is blocky. Quarter resolution is the next step down
  and still looks clean, since light falloff is already soft.
- Gradient sprites are cached per 8 px radius bucket. Flicker stays within 3-4
  sprites, so the cache never grows.

## Recommendation
Build the real lighting system on **half resolution + static layer + smooth
upscale**: about 3 ms flat. Keep quarter resolution as the switch to flip if a
target machine misses 60 FPS. No shader backend is needed.

## Look
- Pools read clearly and the dark region has the right muted blue-grey.
- Additive glow must stay opt-in (flares, muzzle flashes) and weak. Applied to
  every light it blew the scene out to white (first attempt).
- Overlapping pools saturate to fully lit, which is fine for sight but means
  flare light and sight need separate strengths to feel different. Sight pools
  use strength 0.8.

## Not measured
- Display present cost. The spike ran on SDL's dummy driver, so the final flip
  to a real window is excluded.
- Hardware. Timings come from a shared cloud container, not a mid-range laptop
  with integrated graphics. Treat them as relative, and re-run the script there.
- Time-of-day transitions (tint lerp is a single fill colour change, no extra
  cost expected) and rain/mist layers, which G6 adds on top.
- Gameplay rules: hiding enemies outside light, contact marks, mortars firing
  on last-known positions. Only the cost of the visibility test was measured.

## Status: promoted
Built as `lighting.py` (M3/G4). All four steps below are done, plus two changes the real
thing forced: the glow became an alpha-blended amber wash in three fixed strength levels
(additive glow blew the scene out at dusk, and mixing surface alpha with per-pixel alpha was
3-4x slower), and every gradient sprite is built at load (about 0.5 s) because radii sweep
through many buckets during a tint transition and creating sprites mid-frame caused hitches.
Measured in the real game over a full eight-wave run: whole frame (sim, update, draw) mean
3.95 ms, p99 7.4 ms, max 11.9 ms.

## Next steps to promote this (all done)
1. Move `GradientCache` and `Overlay` into a `lighting.py` used by `render.py`,
   driven by `WaveDef.time_of_day` and `palette.TINTS`.
2. Add `visible(enemy)` to the simulation, sharing light radii with the
   renderer so the picture and the rules agree. Towers skip unseen enemies.
3. Add last-known contact tracking for mortars, and faint contact marks.
4. Tint lerp over ~3 s on wave start, timed with the radio line.
