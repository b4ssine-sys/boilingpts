"""Interface: counters, radio log, build tray, wave banner, call-wave button, debrief card.

Presentation only. It reads game state and sim events and never changes the
game. Everything the player reads comes from the strings table, every colour
from the palette, every sound goes through audio.play.
"""
import math

import pygame

import audio
import palette as P
from layout import HUD_H, TRAY_H

PAD = 8
CARD_W, CARD_H, CARD_GAP = 100, 66, 6
LOG_W, LOG_H = 352, 68
BANNER_IN, BANNER_HOLD, BANNER_OUT = 0.4, 2.2, 0.5
TOWER_LOST_COOLDOWN = 4.0   # seconds between "position overrun" lines


def ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def wrap(font, text, width):
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if font.size(trial)[0] <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + [cur] if cur else lines


def banner_text(line):
    """The stamped banner is the radio line's first two sentences, in capitals."""
    parts = [p.strip() for p in line.split(".") if p.strip()]
    return (". ".join(parts[:2]) + ".").upper()


class Counter:
    """A number that counts toward its target and pulses when it changes."""

    def __init__(self, value):
        self.value = value
        self.shown = float(value)
        self.pulse = 0.0
        self.sign = 0

    def update(self, dt, value):
        if value != self.value:
            self.sign = 1 if value > self.value else -1
            self.pulse = 1.0
            self.value = value
        diff = self.value - self.shown
        if abs(diff) < 0.5:
            self.shown = float(self.value)
        else:
            self.shown += diff * (1 - math.exp(-dt / 0.12))
        self.pulse = max(0.0, self.pulse - dt / 0.6)

    @property
    def text(self):
        return str(int(round(self.shown)))


class RadioLog:
    """Lines type out one at a time with a key click every few characters."""
    CPS = 46            # characters per second
    CLICK_EVERY = 3     # characters per key click

    def __init__(self):
        self.lines = []       # finished lines, oldest first
        self.queue = []
        self.typing = None    # [text, characters shown as float]

    def push(self, text):
        self.queue.append(text)

    def clear(self):
        self.lines, self.queue, self.typing = [], [], None

    def update(self, dt):
        if self.typing is None and self.queue:
            self.typing = [self.queue.pop(0), 0.0]
        if self.typing is None:
            return
        text, shown = self.typing
        speed = self.CPS * (3 if len(self.queue) > 1 else 1)   # catch up when waves stack lines
        new = min(len(text), shown + speed * dt)
        for i in range(int(shown), int(new)):
            if i % self.CLICK_EVERY == 0 and text[i] != " ":
                audio.play("radio_key")
        if new >= len(text):
            self.lines.append(text)
            self.lines = self.lines[-40:]
            self.typing = None
        else:
            self.typing[1] = new

    def display(self, font, width, max_lines):
        """(text, fade 0..1) for the lines to show, oldest first, newest last.
        A line being typed is laid out in full first, so words never reflow."""
        out = []
        for text in self.lines[-8:]:
            out += wrap(font, text, width)
        if self.typing:
            text, shown = self.typing
            left = int(shown)
            for ln in wrap(font, text, width):
                out.append(ln[:left])
                left = max(0, left - len(ln) - 1)
        out = out[-max_lines:]
        n = len(out)
        return [(ln, 0.5 + 0.5 * ((i + 1) / n) ** 1.5) for i, ln in enumerate(out)]


class Banner:
    def __init__(self, text):
        self.text = text
        self.age = 0.0

    @property
    def done(self):
        return self.age >= BANNER_IN + BANNER_HOLD + BANNER_OUT

    def pose(self):
        """(x offset, opacity 0..1)."""
        if self.age < BANNER_IN:
            t = ease_out(self.age / BANNER_IN)
            return -(1 - t) * 320, t
        out_start = BANNER_IN + BANNER_HOLD
        if self.age > out_start:
            return 0, max(0.0, 1 - (self.age - out_start) / BANNER_OUT)
        return 0, 1.0


class Hud:
    def __init__(self, strings, assets, game):
        self.s = strings
        self.assets = assets
        self.f_small = assets.font("label", 11)
        self.f_label = assets.font("label", 13)
        self.f_num = assets.font("log", 20)
        self.f_log = assets.font("log", 13)
        self.f_tip = assets.font("log", 13)
        self.banner_sizes = (28, 24, 20, 16)   # longest that fits the window wins
        self.f_title = assets.font("label", 50)
        self.f_body = assets.font("log", 18)
        self.f_stat = assets.font("log", 15)
        self.map_h = game.map.world_size[1]
        self.width = game.map.world_size[0]
        self.tray_y = HUD_H + self.map_h
        self.mouse = (-1, -1)
        self.clock = -1.0
        self._tape = self._make_tape()
        self._reset(game)

    def _reset(self, game):
        self.supply = Counter(game.supply)
        self.integrity = Counter(game.integrity)
        self.log = RadioLog()
        self.log.push(self.s.get("log.start"))
        self.banner = None
        self.lift = {}                 # tower key -> hover raise, 0..1
        self.button_hover = 0.0
        self.tower_lost_cooldown = 0.0
        self.restart_rect = pygame.Rect(0, 0, 0, 0)

    # ---- geometry ----
    def card_rects(self, game):
        return {key: pygame.Rect(PAD + i * (CARD_W + CARD_GAP), self.tray_y + 7, CARD_W, CARD_H)
                for i, key in enumerate(game.map.towers)}

    @property
    def button_rect(self):
        return pygame.Rect(self.width - 218, 6, 210, 28)

    @property
    def log_rect(self):
        return pygame.Rect(self.width - LOG_W - PAD, self.tray_y + 6, LOG_W, LOG_H)

    def hit_test(self, pos, game):
        """What did a click at `pos` land on? ("card", key) | ("next_wave", None)
        | ("restart", None) | None."""
        if game.state != "playing":
            return ("restart", None) if self.restart_rect.collidepoint(pos) else None
        for key, rect in self.card_rects(game).items():
            if rect.collidepoint(pos):
                return ("card", key)
        if self.button_rect.collidepoint(pos) and self.can_call(game):
            return ("next_wave", None)
        return None

    @classmethod
    def next_wave_time(cls, game):
        """Time of day of the wave SPACE would call, or None if none can be called."""
        return game.map.waves[game.wave].time_of_day if cls.can_call(game) else None

    @staticmethod
    def can_call(game):
        return (game.state == "playing" and not game.wave_active
                and game.wave < len(game.map.waves))

    # ---- per-frame state ----
    def update(self, dt, game):
        if game.clock < self.clock:        # the game was restarted
            self._reset(game)
        self.clock = game.clock
        self.supply.update(dt, game.supply)
        self.integrity.update(dt, game.integrity)
        self.tower_lost_cooldown = max(0.0, self.tower_lost_cooldown - dt)
        for kind, _, _, n in game.events:
            if kind == "wave_start":
                self._wave_started(game, n)
            elif kind == "wave_clear":
                self.log.push(self.s.get("log.wave_clear"))
            elif kind == "resupply":
                self.log.push(self.s.get("log.resupply"))
                audio.play("resupply")
            elif kind == "tower_lost" and self.tower_lost_cooldown == 0:
                self.log.push(self.s.get("log.tower_lost"))
                self.tower_lost_cooldown = TOWER_LOST_COOLDOWN
        self.log.update(dt)
        if self.banner:
            self.banner.age += dt
            if self.banner.done:
                self.banner = None
        k = 1 - math.exp(-dt / 0.07)       # ~200 ms ease for hover
        mx, my = self.mouse
        for key, rect in self.card_rects(game).items():
            target = 1.0 if rect.collidepoint(mx, my) and game.state == "playing" else 0.0
            self.lift[key] = self.lift.get(key, 0.0) + (target - self.lift.get(key, 0.0)) * k
        hot = self.button_rect.collidepoint(mx, my) and self.can_call(game)
        self.button_hover += ((1.0 if hot else 0.0) - self.button_hover) * k

    def _wave_started(self, game, n):
        wave = game.map.waves[n - 1]
        audio.play("radio_wave")
        if wave.log_key:
            line = self.s.get(wave.log_key)
            self.log.push(line)
            self.banner = Banner(banner_text(line))

    # ---- drawing helpers ----
    @staticmethod
    def _make_tape():
        tape = pygame.Surface((34, 14), pygame.SRCALPHA)
        pygame.draw.rect(tape, (*P.color("khaki"), 200), (0, 0, 34, 14))
        pygame.draw.rect(tape, (*P.color("paper_shadow"), 230), (0, 0, 34, 14), 1)
        return pygame.transform.rotate(tape, 12)

    def panel(self, screen, rect, tape=True, fill="paper"):
        pygame.draw.rect(screen, P.mix("paper", "ink", 0.55), rect.move(3, 4))
        pygame.draw.rect(screen, P.color(fill), rect)
        pygame.draw.rect(screen, P.color("ink"), rect, 1)
        if tape:
            for x in (rect.left, rect.right):
                screen.blit(self._tape, self._tape.get_rect(center=(x, rect.top + 2)))

    def _text(self, screen, font, text, color, pos, anchor="topleft"):
        img = font.render(text, True, color)
        screen.blit(img, img.get_rect(**{anchor: pos}))
        return img

    # ---- drawing ----
    def draw(self, screen, game, build_key):
        self._draw_top(screen, game)
        self._draw_tray(screen, game, build_key)
        self._draw_log(screen)
        if game.state == "playing":
            self._draw_banner(screen)
            self._draw_tooltip(screen, game)
        else:
            self._draw_end(screen, game)

    def _counter(self, screen, x, w, label, counter, good_up=True):
        if counter.pulse > 0:
            gain = (counter.sign > 0) == good_up
            tone = P.color("amber") if gain else P.color("clay")
            glow = pygame.Surface((w - 6, HUD_H - 6), pygame.SRCALPHA)
            glow.fill((*tone, int(110 * counter.pulse)))
            screen.blit(glow, (x - 3, 3))
        self._text(screen, self.f_small, label, P.color("khaki"), (x, 3))
        color = P.color("paper")
        if counter.pulse > 0.3:
            color = P.color("amber_hot") if (counter.sign > 0) == good_up else P.mix("clay", "paper", 0.5)
        self._text(screen, self.f_num, counter.text, color, (x, 15))

    def _draw_top(self, screen, game):
        s = self.s
        pygame.draw.rect(screen, P.color("ink"), (0, 0, self.width, HUD_H))
        pygame.draw.line(screen, P.color("clay"), (0, HUD_H - 1), (self.width, HUD_H - 1))
        self._counter(screen, 12, 190, s.get("hud.supply"), self.supply)
        self._counter(screen, 214, 190, s.get("hud.integrity"), self.integrity)
        self._text(screen, self.f_small, s.get("hud.wave"), P.color("khaki"), (420, 3))
        val = s.get("hud.wave_value", wave=game.wave, total=len(game.map.waves))
        img = self._text(screen, self.f_num, val, P.color("paper"), (420, 15))
        # Between waves, name the next wave's time of day so the player can prepare for it.
        nxt = self.next_wave_time(game)
        tod = s.get("hud.next_phase", tod=s.get(f"time.{nxt}").upper()) if nxt else \
            s.get(f"time.{game.time_of_day}").upper()
        self._text(screen, self.f_label, tod, P.color("amber"), (420 + img.get_width() + 10, 20))
        # call-wave button: a paper tag that lifts a little under the cursor
        r = self.button_rect
        on = self.can_call(game)
        rect = r.move(0, -int(2 * self.button_hover))
        if on:
            fill = P.mix("paper", "amber_hot", 0.55 * self.button_hover)
            pygame.draw.rect(screen, fill, rect)
            pygame.draw.rect(screen, P.color("clay"), rect, 2)
            ink = P.color("ink")
        else:
            pygame.draw.rect(screen, P.mix("ink", "khaki", 0.12), rect)
            pygame.draw.rect(screen, P.mix("ink", "khaki", 0.3), rect, 1)
            ink = P.mix("ink", "khaki", 0.5)
        busy = game.state == "playing" and not on
        label = s.get("hud.next_wave_busy" if busy else "hud.next_wave")
        self._text(screen, self.f_label, label, ink, (rect.left + 10, rect.centery), "midleft")
        if on:
            self._text(screen, self.f_small, s.get("hud.next_wave_key"), P.color("clay"),
                       (rect.right - 8, rect.centery), "midright")

    def _draw_tray(self, screen, game, build_key):
        s = self.s
        pygame.draw.rect(screen, P.color("ink"), (0, self.tray_y, self.width, TRAY_H))
        pygame.draw.line(screen, P.color("clay"), (0, self.tray_y), (self.width, self.tray_y))
        for i, (key, base) in enumerate(self.card_rects(game).items()):
            tdef = game.content.towers[key]
            lift = self.lift.get(key, 0.0)
            rect = base.move(0, -int(5 * ease_out(lift)))
            affordable = game.supply >= tdef.cost
            selected = key == build_key
            pygame.draw.rect(screen, P.mix("paper", "ink", 0.55), rect.move(2, 3))
            pygame.draw.rect(screen, P.color("paper") if affordable else P.mix("paper", "ink", 0.3), rect)
            border = P.color("amber") if selected else (P.color("khaki") if lift > 0.3 else P.color("ink"))
            pygame.draw.rect(screen, border, rect, 3 if selected else 1)
            # key badge
            badge = pygame.Rect(rect.left + 4, rect.top + 4, 14, 14)
            pygame.draw.rect(screen, P.color("ink"), badge)
            self._text(screen, self.f_small, str(i + 1), P.color("paper"), badge.center, "center")
            # name, up to two lines
            name = s.get(f"tower.{key}.name")
            for j, ln in enumerate(wrap(self.f_small, name, CARD_W - 28)[:2]):
                self._text(screen, self.f_small, ln, P.color("ink"), (rect.left + 22, rect.top + 4 + 12 * j))
            icon = self.assets.image(f"tower.{key}", 30)
            screen.blit(icon, icon.get_rect(midleft=(rect.left + 6, rect.bottom - 20)))
            cost_color = P.color("ink") if affordable else P.color("clay")
            self._text(screen, self.f_num, s.get("tray.cost", cost=tdef.cost), cost_color,
                       (rect.right - 8, rect.bottom - 6), "bottomright")

    def _draw_log(self, screen):
        r = self.log_rect
        self.panel(screen, r)
        lines = self.log.display(self.f_log, r.w - 20, 4)
        y = r.top + 10
        for text, fade in lines:
            self._text(screen, self.f_log, text, P.mix("paper", "ink", fade), (r.left + 10, y))
            y += 14
        if self.log.typing and (int(self.clock * 3) % 2 == 0):   # blinking cursor while typing
            pygame.draw.rect(screen, P.color("ink"), (r.left + 10, r.bottom - 10, 7, 2))

    def banner_font(self, text):
        """Largest stencil size whose stamped box still fits inside the window."""
        for size in self.banner_sizes:
            font = self.assets.font("label", size)
            if font.size(text)[0] + 36 <= self.width - 40:
                return font
        return self.assets.font("label", self.banner_sizes[-1])

    def _draw_banner(self, screen):
        if not self.banner:
            return
        dx, opacity = self.banner.pose()
        text = self.banner_font(self.banner.text).render(self.banner.text, True, P.color("clay"))
        box = pygame.Surface((text.get_width() + 36, text.get_height() + 18), pygame.SRCALPHA)
        pygame.draw.rect(box, (*P.color("paper"), 235), box.get_rect())
        pygame.draw.rect(box, P.color("clay"), box.get_rect(), 3)
        box.blit(text, (18, 9))
        box = pygame.transform.rotate(box, -2)
        box.set_alpha(int(255 * opacity))
        screen.blit(box, box.get_rect(center=(self.width / 2 + dx, HUD_H + 56)))

    def _draw_tooltip(self, screen, game):
        if game.state != "playing":
            return
        for key, rect in self.card_rects(game).items():
            if rect.collidepoint(self.mouse) and self.lift.get(key, 0) > 0.5:
                role = self.s.get(f"tower.{key}.role")
                lines = wrap(self.f_tip, role, 230)
                h = 14 * len(lines) + 16
                tip = pygame.Rect(0, 0, 250, h)
                tip.bottomleft = (min(rect.left, self.width - 258), self.tray_y - 8)
                self.panel(screen, tip, tape=False)
                for i, ln in enumerate(lines):
                    self._text(screen, self.f_tip, ln, P.color("ink"), (tip.left + 10, tip.top + 8 + 14 * i))

    def _draw_end(self, screen, game):
        s = self.s
        won = game.state == "won"
        outcome = "won" if won else "lost"
        card = pygame.Rect(0, 0, 620, 360)
        card.center = (self.width / 2, HUD_H + self.map_h / 2)
        self.panel(screen, card)
        title = s.get(f"end.{outcome}.title").upper()
        self._text(screen, self.f_title, title, P.color("clay"), (card.centerx, card.top + 20), "midtop")
        y = card.top + 84
        self._text(screen, self.f_body, s.get(f"end.{outcome}.body"), P.color("ink"),
                   (card.centerx, y), "midtop")
        y += 34
        for ln in wrap(self.f_stat, s.get(f"map.{game.map.key}.context"), card.w - 60):
            self._text(screen, self.f_stat, ln, P.color("olive_drab"), (card.centerx, y), "midtop")
            y += 18
        y += 8
        pygame.draw.line(screen, P.color("paper_shadow"), (card.left + 30, y), (card.right - 30, y), 2)
        y += 10
        self._text(screen, self.f_label, s.get("end.stats.title"), P.color("clay"), (card.left + 34, y))
        st = game.stats
        rows = [s.get("end.stats.waves", n=st["waves_cleared"], total=len(game.map.waves)),
                s.get("end.stats.stopped", n=st["stopped"]),
                s.get("end.stats.leaked", n=st["leaked"]),
                s.get("end.stats.built", n=st["built"]),
                s.get("end.stats.lost", n=st["lost"])]
        for i, row in enumerate(rows):
            self._text(screen, self.f_stat, row, P.color("ink"), (card.left + 34, y + 20 + 18 * i))
        # restart stamp
        stamp = self.f_label.render(s.get("end.restart_stamp"), True, P.color("clay"))
        box = pygame.Surface((stamp.get_width() + 28, stamp.get_height() + 16), pygame.SRCALPHA)
        pygame.draw.rect(box, P.color("clay"), box.get_rect(), 3)
        box.blit(stamp, (14, 8))
        box = pygame.transform.rotate(box, 4)
        hot = self.restart_rect.collidepoint(self.mouse)
        if hot:
            box.set_alpha(255)
        else:
            box.set_alpha(215)
        self.restart_rect = box.get_rect(bottomright=(card.right - 28, card.bottom - 22))
        screen.blit(box, self.restart_rect)
