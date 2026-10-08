"""Asset loading by key, with painted fallbacks so a missing file never crashes.

Sprites: assets/sprites/<key>.png replaces the drawing in art.py. Keys:
    tower.<tower>.base          static layer (sandbags, crates, structure)
    tower.<tower>.gun           rotating layer (mg_nest and mortar only)
    enemy.<enemy>.0 / .1        two walk frames, facing east
Art faces east (angle 0). Towers and enemies stand on the ground point given by
art.ANCHOR, so a replacement PNG must keep its feet or foundation there.
Fonts: assets/fonts/<role>.ttf for the roles "log" (typewriter) and "label"
(stencil); system fonts stand in until licensed ones are chosen.
"""
import math
import os

import pygame

import art

ASSET_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

# Rough match to the typewriter and stencil faces until licensed fonts are chosen.
_SYSFONTS = {"log": "couriernew,courier,dejavusansmono,monospace",
             "label": "impact,arialblack,dejavusans,arial"}


def _registry():
    reg = {}
    for k, fn in art.BASE_BUILDERS.items():
        reg[f"tower.{k}.base"] = fn
    for k, fn in art.GUN_BUILDERS.items():
        reg[f"tower.{k}.gun"] = fn
    for k, fn in art.FRONT_BUILDERS.items():
        reg[f"tower.{k}.front"] = fn
    for k, fn in art.ENEMY_BUILDERS.items():
        for frame in (0, 1):
            reg[f"enemy.{k}.{frame}"] = (lambda fn=fn, frame=frame: fn(frame))
    return reg


REGISTRY = _registry()


def _unknown():
    pen = art.Pen(24, 24)
    pen.rect(5, 5, 14, 14, "clay", width=1.4)
    pen.line((5, 5), (19, 19), "clay", 1.4)
    return pen.done(0)


class Assets:
    def __init__(self, root=ASSET_DIR):
        self.root = root
        self._sprites = {}
        self._scaled = {}
        self._rotated = {}
        self._icons = {}
        self._fonts = {}

    def has(self, key):
        return key in REGISTRY or os.path.isfile(os.path.join(self.root, "sprites", f"{key}.png"))

    def sprite(self, key):
        """The sprite at its native size, from file if present, else painted."""
        if key not in self._sprites:
            self._sprites[key] = self._load(key)
        return self._sprites[key]

    def _load(self, key):
        path = os.path.join(self.root, "sprites", f"{key}.png")
        if os.path.isfile(path):
            try:
                img = pygame.image.load(path)
                return img.convert_alpha() if pygame.display.get_surface() else img
            except pygame.error:
                pass  # a corrupt file falls back like a missing one
        build = REGISTRY.get(key, _unknown)
        return build()

    def scaled(self, key, scale):
        if scale == 1.0:
            return self.sprite(key)
        ck = (key, scale)
        if ck not in self._scaled:
            s = self.sprite(key)
            self._scaled[ck] = pygame.transform.smoothscale(
                s, (max(1, round(s.get_width() * scale)), max(1, round(s.get_height() * scale))))
        return self._scaled[ck]

    def flipped(self, key, scale=1.0, flip=False):
        """Scaled sprite, mirrored left to right when `flip` (units that walk west)."""
        if not flip:
            return self.scaled(key, scale)
        ck = (key, scale, "flip")
        if ck not in self._scaled:
            self._scaled[ck] = pygame.transform.flip(self.scaled(key, scale), True, False)
        return self._scaled[ck]

    def rotated(self, key, radians, scale=1.0, bucket=10):
        """Sprite turned to `radians` (0 = east, y down), cached in `bucket`-degree steps."""
        step = round((-radians * 180 / math.pi) / bucket) * bucket % 360
        ck = (key, scale, step)
        if ck not in self._rotated:
            self._rotated[ck] = pygame.transform.rotate(self.scaled(key, scale), step)
        return self._rotated[ck]

    def composed(self, tower_key, scale, aim=0.0):
        """Base, gun and front wall flattened into one picture (cards and the placement preview)."""
        base = self.scaled(f"tower.{tower_key}.base", scale).copy()
        gun_key = f"tower.{tower_key}.gun"
        ax, ay = art.ANCHOR["tower"]
        if self.has(gun_key):
            gun = self.rotated(gun_key, aim, scale)
            mx, my = art.MOUNT[tower_key]
            base.blit(gun, gun.get_rect(center=(base.get_width() * ax + mx * scale,
                                                base.get_height() * ay + my * scale)))
        front_key = f"tower.{tower_key}.front"
        if self.has(front_key):
            base.blit(self.scaled(front_key, scale), (0, 0))
        return base

    def icon(self, tower_key, height, max_width=None):
        """A tower as a card illustration: base and gun together, scaled to fit
        `height` and, if given, `max_width`."""
        ck = (tower_key, height, max_width)
        if ck not in self._icons:
            base = self.composed(tower_key, 1.0)
            rect = base.get_bounding_rect()
            base = base.subsurface(rect).copy()
            k = height / base.get_height()
            if max_width:
                k = min(k, max_width / base.get_width())
            height = max(1, round(base.get_height() * k))
            self._icons[ck] = pygame.transform.smoothscale(
                base, (max(1, round(base.get_width() * k)), height))
        return self._icons[ck]

    def prewarm(self, tower_scale, enemy_scale):
        """Build every scaled, mirrored and rotated variant a session can ask for,
        so nothing is created mid-frame."""
        for key in REGISTRY:
            if key.startswith("enemy."):
                self.flipped(key, enemy_scale, False)
                self.flipped(key, enemy_scale, True)
            elif key.endswith(".base") or key.endswith(".front"):
                self.scaled(key, tower_scale)
            elif key.endswith(".gun"):
                for deg in range(0, 360, 10):
                    self.rotated(key, -math.radians(deg), tower_scale)

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
