"""Asset loading by key, with a drawn fallback so a missing file never crashes.

Sprites: assets/sprites/<key>.png, for example tower.mg_nest.png. Art faces
east (angle 0) so the renderer can rotate it toward a target. Fonts:
assets/fonts/<role>.ttf for the roles "log" (typewriter) and "label" (stencil).
When the concept artist delivers a file it is picked up by name with no code
change; until then the fallbacks below stand in.
"""
import os

import pygame

import palette as P

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# Rough match to the typewriter and stencil faces until licensed fonts are chosen.
_SYSFONTS = {"log": "couriernew,courier,dejavusansmono,monospace",
             "label": "impact,arialblack,dejavusans,arial"}


def _fb_mg_nest(s):
    surf = pygame.Surface((s, s), pygame.SRCALPHA)
    c = s / 2
    pygame.draw.circle(surf, P.color("khaki"), (c, c), s * 0.46)
    pygame.draw.circle(surf, P.color("ink"), (c, c), s * 0.46, max(1, s // 16))
    pygame.draw.circle(surf, P.color("olive_drab"), (c, c), s * 0.30)
    pygame.draw.rect(surf, P.color("ink"), (c, c - s * 0.06, s * 0.46, s * 0.12))
    return surf


def _fb_mortar(s):
    surf = pygame.Surface((s, s), pygame.SRCALPHA)
    c = s / 2
    pygame.draw.circle(surf, P.color("jungle_dark"), (c, c), s * 0.46)
    pygame.draw.circle(surf, P.color("khaki"), (c, c), s * 0.46, max(2, s // 12))
    pygame.draw.circle(surf, P.color("ink"), (c, c), s * 0.20)
    pygame.draw.rect(surf, P.color("olive_drab"), (c, c - s * 0.09, s * 0.30, s * 0.18))
    return surf


def _fb_claymore(s):
    surf = pygame.Surface((s, s), pygame.SRCALPHA)
    for i in (-1, 0, 1):
        r = pygame.Rect(0, 0, s * 0.18, s * 0.34)
        r.center = (s / 2, s / 2 + i * s * 0.26)
        pygame.draw.rect(surf, P.color("olive_drab"), r, border_radius=2)
        pygame.draw.rect(surf, P.color("ink"), r, 1, border_radius=2)
    return surf


def _fb_flare(s):
    surf = pygame.Surface((s, s), pygame.SRCALPHA)
    c = s / 2
    pygame.draw.circle(surf, P.color("olive_drab"), (c, c), s * 0.30)
    pygame.draw.circle(surf, P.color("ink"), (c, c), s * 0.30, 1)
    pygame.draw.circle(surf, P.color("amber"), (c, c), s * 0.16)
    pygame.draw.circle(surf, P.color("amber_hot"), (c, c), s * 0.07)
    return surf


def _fb_scout(s):
    surf = pygame.Surface((s, s), pygame.SRCALPHA)
    r = pygame.Rect(0, 0, s * 0.62, s * 0.30)
    r.center = (s / 2, s / 2)
    pygame.draw.ellipse(surf, P.color("clay"), r)
    pygame.draw.ellipse(surf, P.color("ink"), r, 1)
    return surf


def _fb_infantry(s):
    surf = pygame.Surface((s, s), pygame.SRCALPHA)
    pygame.draw.circle(surf, P.color("clay"), (s / 2, s / 2), s * 0.32)
    pygame.draw.circle(surf, P.color("ink"), (s / 2, s / 2), s * 0.32, 1)
    return surf


def _fb_sapper(s):
    surf = pygame.Surface((s, s), pygame.SRCALPHA)
    pack = pygame.Rect(0, 0, s * 0.30, s * 0.36)
    pack.center = (s * 0.30, s / 2)
    pygame.draw.rect(surf, P.color("jungle_dark"), pack, border_radius=2)
    pygame.draw.circle(surf, P.color("clay"), (s * 0.55, s / 2), s * 0.26)
    pygame.draw.circle(surf, P.color("ink"), (s * 0.55, s / 2), s * 0.26, 1)
    return surf


def _fb_unknown(s):
    surf = pygame.Surface((s, s), pygame.SRCALPHA)
    pygame.draw.rect(surf, P.color("clay"), (s * 0.2, s * 0.2, s * 0.6, s * 0.6), 2)
    pygame.draw.line(surf, P.color("clay"), (s * 0.2, s * 0.2), (s * 0.8, s * 0.8), 2)
    return surf


FALLBACKS = {
    "tower.mg_nest": _fb_mg_nest, "tower.mortar": _fb_mortar,
    "tower.claymore": _fb_claymore, "tower.flare": _fb_flare,
    "enemy.scout": _fb_scout, "enemy.infantry": _fb_infantry, "enemy.sapper": _fb_sapper,
}


class Assets:
    def __init__(self, root=ASSET_DIR):
        self.root = root
        self._images = {}
        self._rotated = {}
        self._fonts = {}

    def image(self, key, size):
        """Square sprite at `size` pixels, from file if present, else drawn."""
        ck = (key, size)
        if ck not in self._images:
            self._images[ck] = self._load(key, size)
        return self._images[ck]

    def _load(self, key, size):
        path = os.path.join(self.root, "sprites", f"{key}.png")
        if os.path.isfile(path):
            try:
                img = pygame.image.load(path)
                img = img.convert_alpha() if pygame.display.get_surface() else img
                return pygame.transform.smoothscale(img, (size, size))
            except pygame.error:
                pass  # a corrupt file falls back like a missing one
        # Draw at 2x and scale down for smoother edges.
        big = FALLBACKS.get(key, _fb_unknown)(size * 2)
        return pygame.transform.smoothscale(big, (size, size))

    def rotated(self, key, size, radians, bucket=12):
        """Sprite turned to `radians` (0 = east, y down), cached in `bucket`-degree steps."""
        deg = -radians * 180 / 3.14159265
        step = round(deg / bucket) * bucket % 360
        ck = (key, size, step)
        if ck not in self._rotated:
            self._rotated[ck] = pygame.transform.rotate(self.image(key, size), step)
        return self._rotated[ck]

    def font(self, role, size):
        ck = (role, size)
        if ck not in self._fonts:
            path = os.path.join(self.root, "fonts", f"{role}.ttf")
            if os.path.isfile(path):
                self._fonts[ck] = pygame.font.Font(path, size)
            else:
                self._fonts[ck] = pygame.font.SysFont(_SYSFONTS.get(role), size,
                                                      bold=(role == "label"))
        return self._fonts[ck]
