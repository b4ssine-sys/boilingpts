"""Every sound goes through play(key). No sound plays yet: until the sound
designer delivers, this is a silent stub that records what was asked for, so
the call sites, the keys and the timing are already in place and testable.

To add real audio later, load files in _load() and play them in play().
Nothing else in the code base needs to change.
"""

KEYS = (
    "radio_key",       # one typewriter click while a radio line types out
    "radio_wave",      # radio chatter one-shot at wave start
    "resupply",        # supply-drop sting
    "ui_click",
    "build",
    "fire_mg_nest", "fire_mortar", "claymore", "flare",   # distinct per tower (wired in G3)
)

history = []          # what was requested, newest last (kept short; for tests and debugging)
_MAX_HISTORY = 200


def play(key):
    if key not in KEYS:
        raise KeyError(f"unknown sound {key!r}; add it to audio.KEYS")
    history.append(key)
    del history[:-_MAX_HISTORY]
