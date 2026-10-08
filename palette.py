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
    # Painted-world additions. Same muted family as the tokens above; used by
    # art.py and mapart.py so no colour literal lives outside this file.
    "mud": "#6B5640",
    "mud_dark": "#46382A",
    "concrete": "#8F9189",
    "concrete_dark": "#5E625C",
    "sandbag": "#B09A6A",
    "steel": "#4B4F4E",
    "wood": "#7A5C3A",
    "wood_dark": "#4A3722",
    "leaf_deep": "#1F3320",
    "leaf_bright": "#7FA14F",
    "rain": "#B8C6D0",
    "cloth_brown": "#6E5A3C",
    "cloth_green": "#4E5A3A",
    "skin": "#A88660",
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


def shade(c, f):
    """Scale a token or RGB tuple's brightness. f < 1 darkens, f > 1 lightens (clamped)."""
    rgb = COLORS[c] if isinstance(c, str) else c
    return tuple(max(0, min(255, round(v * f))) for v in rgb)


def mix(a, b, t):
    """Blend two tokens (or RGB tuples); t=0 gives a, t=1 gives b."""
    ca = COLORS[a] if isinstance(a, str) else a
    cb = COLORS[b] if isinstance(b, str) else b
    return tuple(round(x + (y - x) * t) for x, y in zip(ca, cb))
