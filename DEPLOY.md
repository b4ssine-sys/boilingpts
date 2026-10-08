# Deploying to Vercel

Vercel hosts static sites and serverless functions, so it cannot run a desktop
Pygame window. The game is compiled for the browser instead with
[pygbag](https://pygame-web.github.io/) (Pygame to WebAssembly), and the result is
served as a static site. Vercel does the build on every deploy; nothing generated is
committed.

## Deploy

1. Push this repository to GitHub.
2. In Vercel choose **Add New, Project**, import the repository and press **Deploy**.
   No settings need changing: `vercel.json` already sets everything.

What `vercel.json` does:

| Setting | Value | Why |
|---|---|---|
| `framework` | `null` | Stops Vercel treating `main.py` as a Python web app. |
| `installCommand` | `pip install -r requirements-web.txt` | Installs pygbag (pinned) for the build only. |
| `buildCommand` | `python3 scripts/build_web.py` | Stages the game and runs pygbag. |
| `outputDirectory` | `public` | Where the script writes the finished site. |

## What the build does

`scripts/build_web.py` follows the real imports from `main.py` and copies only what
the game needs (19 files: the modules, `strings.json`, the bundled fonts) into
`build/stage/tower-defense/`. Tests, spikes, scripts and docs stay out of the
download. It then runs `pygbag --build` and copies `build/web/` to `public/`.

Check the staging without the network: `python scripts/build_web.py --stage`.

## Run it locally in a browser

    pip install -r requirements-web.txt
    python scripts/build_web.py
    python -m http.server --directory public 8000      # then open http://localhost:8000

The page loads the Python and Pygame runtime from `pygame-web.github.io`, so it needs
internet access (the build does too).

## Not tested

The browser build could not be run in the environment this was written in, because
its network blocks the pygbag runtime host. Verified: the staging step, that the
staged folder runs on its own in web mode on the desktop, and every test. **Not
tested:** `pygbag --build` itself, the Vercel build, and the game running in a
browser, including its frame rate. Treat the first deploy as the real test and check:

- The Vercel build log shows pygbag finishing and `wrote public/`. If `pip install`
  complains about an externally managed environment, the install command already sets
  `PIP_BREAK_SYSTEM_PACKAGES=1`; if Python is missing from the build image, say so and
  the build can move to a GitHub Action that uploads `public/`.
- The page shows "Ready to start! Please click/touch page", then the LOADING screen,
  then the game. Loading is slower than on the desktop.
- Frame rate. WebAssembly is several times slower than native Python-with-C-Pygame, and
  the game costs about 5 ms a frame natively. The browser build already uses the
  lighter setting (`Renderer(..., quality="web")`): the darkness layer at quarter
  resolution, no light shafts, less rain. If it still drops frames, the next cuts are
  fewer rain drops, no ripples, and a lower resolution map bake.

## Known differences in the browser

- ESC does not quit (the tab is closed by the browser).
- No sound yet; `audio.py` is a silent stub. When real sound arrives, pygbag's click to
  start page is what unlocks browser audio.
- Fonts are bundled DejaVu (see `ASSETS.md`), not system fonts.
- The page title is the generic "Tower Defense" until the working title is locked.
