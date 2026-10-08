# Asset register

Every file under `assets/` gets a row here: source, author, license. Nothing
ships without one.

## Current state

The only bundled files are the two fonts below. Every sprite is painted at load by `art.py`,
the map by `mapart.py`, effects by `fx.py`, and every colour comes from
`palette.py`. The painting needs no license. The painting is placeholder-grade
art that stands in until the concept artist delivers; real files replace it by
name with no code change.

## How the enemy is depicted (content rule, not a style choice)

Enemy units are **human figures**, drawn faceless in muted field gear, with one
silhouette per type: a slim running scout, an infantryman with pack and rifle, a
crouched sapper carrying a satchel charge. They get exactly the same inked,
shaded treatment as every tower and structure, and the same desaturate-and-fade
when they fall. No gore.

They are never drawn as animals, monsters or caricatures, and no replacement art
may do so. This follows the project's content rules (no caricature, no
dehumanisation, the same treatment for both sides) and is guarded by
`tests/test_art.py::NoCaricatureTests`. A concept-art brief or reference image
that proposes otherwise needs the Creative Director and the consultant, not a
code change.

## Sprite replacement

Drop `assets/sprites/<key>.png` to replace a painting. Art faces east and stands
on the ground point `art.ANCHOR` (towers 50%/64% of the canvas, enemies
50%/84%). Authoring size is the canvas below; the renderer scales towers by
1.25 and enemies by 1.3.

| Key | Canvas | Notes |
|---|---|---|
| `tower.<t>.base` | 60x60 | Static layer. Back wall, floor, crates. |
| `tower.<t>.front` | 60x60 | mg_nest and mortar only. Near wall, drawn over the gun. |
| `tower.<t>.gun` | 44x44 | mg_nest and mortar only. Pivots on its centre; mount offsets in `art.MOUNT`. |
| `enemy.<e>.0`, `enemy.<e>.1` | 48x48 | Two walk frames; the renderer mirrors them for westward travel. |

`<t>` is `mg_nest`, `mortar`, `claymore` or `flare`; `<e>` is `scout`, `infantry`
or `sapper`. A missing or corrupt file falls back to the painting.

## Fonts

Two fonts are bundled so the browser build, which has no system fonts, looks the same
as the desktop one:

| Role | File | Face | Used for |
|---|---|---|---|
| `log` | `assets/fonts/log.ttf` | DejaVu Sans Mono | radio log, body text (typewriter stand-in) |
| `label` | `assets/fonts/label.ttf` | DejaVu Sans Bold | labels, counters, stamps (stencil stand-in) |

They are stand-ins. The brief asks for a true typewriter face and a stencil face; pick
those (confirm each license, SIL OFL is a good fit) and drop them over these two
files. Without the files, `assets.py` falls back to system fonts.

## Register

| File | Source | Author | License |
|---|---|---|---|
| `assets/fonts/log.ttf` | DejaVu Sans Mono, from the Debian `fonts-dejavu-core` package | Bitstream, Inc. and the DejaVu authors | Bitstream Vera license: free to use and redistribute with the notice, which ships as `assets/fonts/LICENSE-DejaVu.txt` |
| `assets/fonts/label.ttf` | DejaVu Sans Bold, same package | same | same |
