"""Every colour in the game. Nothing else in the code base writes an RGB literal."""

_HEX = {
    "paper": "#D9CFAE",
    "paper_shadow": "#B9AE8A",
    "olive_drab": "#6B6B3A",
    "khaki": "#B5A67A",
    "clay": "#A4543A",
    "jungle_dark": "#2F4630",
    "jungle_mid": "#3F5B3A",
    "jungle_light": "#5E7A45",
    "ink": "#1E1B16",
    "amber": "#F2B14A",
    "amber_hot": "#FFE2A0",
    "night_tint": "#10162A",
}


def _rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


COLORS = {name: _rgb(h) for name, h in _HEX.items()}

# Darkness overlay per time of day: (token, alpha 0-255). Consumed by M3/G4.
TINTS = {
    "day": ("night_tint", 0),
    "dusk": ("night_tint", 90),
    "dark": ("night_tint", 178),
    "dawn": ("night_tint", 70),
}


def color(token):
    return COLORS[token]


def mix(a, b, t):
    """Blend two tokens (or RGB tuples); t=0 gives a, t=1 gives b."""
    ca = COLORS[a] if isinstance(a, str) else a
    cb = COLORS[b] if isinstance(b, str) else b
    return tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))
