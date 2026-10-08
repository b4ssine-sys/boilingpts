import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pygame

import audio
import ui
from assets import Assets
from content import CONTENT
from layout import HUD_H, TRAY_H, screen_size
from render import Renderer
from sim import Game
from strings import Strings

DT = 1 / 60


def run(game, seconds):
    for _ in range(int(round(seconds / DT))):
        game.update(DT)


class SimHookTests(unittest.TestCase):
    def test_wave_start_event_reaches_the_next_update(self):
        g = Game(CONTENT, "firebase")
        g.start_wave()                       # called outside update, like a key press
        g.update(DT)
        self.assertIn(("wave_start", 0, 0, 1), g.events)
        g.update(DT)
        self.assertNotIn(("wave_start", 0, 0, 1), g.events)   # delivered once

    def test_clearing_a_wave_emits_clear_and_resupply(self):
        g = Game(CONTENT, "firebase")
        g.supply = 9999
        for pos in [(14, 6), (16, 6), (15, 8), (13, 6)]:
            g.try_build(*pos, "mg_nest")
        g.start_wave()
        seen = []
        for _ in range(60 * 60):
            g.update(DT)
            seen += [(e[0], e[3]) for e in g.events]
            if not g.wave_active:
                break
        self.assertIn(("wave_clear", 1), seen)
        self.assertIn(("resupply", g.map.resupply_bonus), seen)

    def test_stats_track_the_fight(self):
        g = Game(CONTENT, "firebase")
        g.supply = 9999
        for pos in [(14, 6), (16, 6), (15, 8), (13, 6)]:
            g.try_build(*pos, "mg_nest")
        self.assertEqual(g.stats["built"], 4)
        g.start_wave()
        for _ in range(60 * 60):
            g.update(DT)
            if not g.wave_active:
                break
        st = g.stats
        self.assertEqual(st["waves_cleared"], 1)
        self.assertEqual(st["stopped"] + st["leaked"], 6)    # wave 1 sends six
        g.reset()
        self.assertEqual(sum(g.stats.values()), 0)


class CounterTests(unittest.TestCase):
    def test_counts_toward_the_target_without_overshoot(self):
        c = ui.Counter(100)
        c.update(DT, 40)
        prev = c.shown
        self.assertEqual(c.sign, -1)
        self.assertGreater(c.pulse, 0.95)
        for _ in range(90):
            c.update(DT, 40)
            self.assertLessEqual(c.shown, prev)
            self.assertGreaterEqual(c.shown, 40)
            prev = c.shown
        self.assertEqual(c.text, "40")

    def test_pulse_fades_and_gain_has_positive_sign(self):
        c = ui.Counter(10)
        c.update(DT, 20)
        self.assertEqual(c.sign, 1)
        for _ in range(60):
            c.update(DT, 20)
        self.assertEqual(c.pulse, 0.0)

    def test_steady_value_does_not_pulse(self):
        c = ui.Counter(5)
        for _ in range(30):
            c.update(DT, 5)
        self.assertEqual((c.pulse, c.text), (0.0, "5"))


class RadioLogTests(unittest.TestCase):
    def setUp(self):
        pygame.font.init()
        self.font = pygame.font.SysFont(None, 18)
        audio.history.clear()

    def test_types_at_a_steady_pace_and_finishes(self):
        log = ui.RadioLog()
        text = "x" * 92
        log.push(text)
        for _ in range(60):
            log.update(DT)
        self.assertAlmostEqual(log.typing[1], ui.RadioLog.CPS, delta=2)
        for _ in range(120):
            log.update(DT)
        self.assertIsNone(log.typing)
        self.assertEqual(log.lines, [text])

    def test_clicks_follow_the_typing_and_skip_spaces(self):
        log = ui.RadioLog()
        log.push("abc def ghi jkl")
        for _ in range(60):
            log.update(DT)
        clicks = audio.history.count("radio_key")
        self.assertTrue(3 <= clicks <= 5, clicks)

    def test_lines_type_one_at_a_time_in_order(self):
        log = ui.RadioLog()
        log.push("first line")
        log.push("second line")
        log.update(DT)
        self.assertEqual(log.typing[0], "first line")
        for _ in range(300):
            log.update(DT)
        self.assertEqual(log.lines, ["first line", "second line"])

    def test_stacked_lines_type_faster_to_catch_up(self):
        a, b = ui.RadioLog(), ui.RadioLog()
        for t in ("x" * 200, "y" * 10, "z" * 10):
            a.push(t)
        b.push("x" * 200)
        a.update(0.5)
        b.update(0.5)
        self.assertGreater(a.typing[1], b.typing[1] * 2)

    def test_display_reveals_a_prefix_without_reflow(self):
        log = ui.RadioLog()
        text = "Dark. Fast movement on the south trail. Second element, north."
        log.push(text)
        full = ui.wrap(self.font, text, 200)
        for _ in range(25):
            log.update(DT)
        shown = [ln for ln, _ in log.display(self.font, 200, 6)]
        self.assertEqual(len(shown), len(full))                  # layout fixed from the first frame
        self.assertTrue("".join(shown).startswith(full[0][:3]))
        self.assertLess(sum(len(s) for s in shown), len(text))

    def test_older_lines_fade_and_newest_is_strongest(self):
        log = ui.RadioLog()
        log.lines = ["one", "two", "three", "four"]
        fades = [f for _, f in log.display(self.font, 300, 4)]
        self.assertEqual(fades, sorted(fades))
        self.assertEqual(fades[-1], 1.0)

    def test_clear_empties_everything(self):
        log = ui.RadioLog()
        log.push("a")
        log.update(DT)
        log.clear()
        self.assertEqual((log.lines, log.queue, log.typing), ([], [], None))


class BannerTests(unittest.TestCase):
    def test_banner_text_is_the_first_two_sentences_in_capitals(self):
        self.assertEqual(ui.banner_text("Dusk. Contact, north treeline. One element on the trail."),
                         "DUSK. CONTACT, NORTH TREELINE.")
        self.assertEqual(ui.banner_text("Single."), "SINGLE.")

    def test_timeline_slides_in_holds_then_fades(self):
        b = ui.Banner("X")
        dx0, o0 = b.pose()
        self.assertLess(dx0, -300)
        self.assertEqual(o0, 0)
        b.age = ui.BANNER_IN
        self.assertEqual(b.pose(), (0, 1.0))
        b.age = ui.BANNER_IN + ui.BANNER_HOLD / 2
        self.assertEqual(b.pose(), (0, 1.0))
        b.age = ui.BANNER_IN + ui.BANNER_HOLD + ui.BANNER_OUT / 2
        self.assertAlmostEqual(b.pose()[1], 0.5)
        b.age = ui.BANNER_IN + ui.BANNER_HOLD + ui.BANNER_OUT
        self.assertTrue(b.done)

    def test_easing_is_monotonic_and_bounded(self):
        vals = [ui.ease_out(i / 20) for i in range(21)]
        self.assertEqual((vals[0], vals[-1]), (0, 1))
        self.assertEqual(vals, sorted(vals))
        self.assertEqual((ui.ease_out(-1), ui.ease_out(2)), (0, 1))


class HudTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init()
        pygame.font.init()
        self.game = Game(CONTENT, "firebase")
        self.screen = pygame.display.set_mode(screen_size(self.game.map))
        self.strings = Strings.load()
        self.hud = ui.Hud(self.strings, Assets(), self.game)
        audio.history.clear()

    def tearDown(self):
        pygame.quit()

    def step(self, seconds=DT):
        for _ in range(max(1, int(round(seconds / DT)))):
            self.game.update(DT)
            self.hud.update(DT, self.game)

    def test_opens_with_a_radio_check(self):
        self.hud.log.update(DT)
        self.assertEqual(self.hud.log.typing[0], self.strings.get("log.start"))

    def test_calling_a_wave_posts_its_radio_line_and_a_banner(self):
        self.game.start_wave()
        self.step()
        line = self.strings.get(self.game.map.waves[0].log_key)
        self.assertIn(line, self.hud.log.queue + [self.hud.log.typing and self.hud.log.typing[0]]
                      + self.hud.log.lines)
        self.assertEqual(self.hud.banner.text, ui.banner_text(line))
        self.assertIn("radio_wave", audio.history)

    def test_resupply_posts_a_line_and_sting_and_pulses_supply(self):
        self.hud.update(DT, self.game)
        self.game.events = [("resupply", 0, 0, 30)]
        self.game.supply += 30
        self.hud.update(DT, self.game)
        self.assertIn(self.strings.get("log.resupply"), self.hud.log.queue)
        self.assertIn("resupply", audio.history)
        self.assertEqual(self.hud.supply.sign, 1)
        self.assertGreater(self.hud.supply.pulse, 0)

    def lost_lines(self):
        """How many 'position overrun' lines exist anywhere in the log pipeline."""
        text = self.strings.get("log.tower_lost")
        log = self.hud.log
        return (log.queue.count(text) + log.lines.count(text)
                + (1 if log.typing and log.typing[0] == text else 0))

    def test_tower_lost_lines_are_rate_limited(self):
        self.game.events = [("tower_lost", 0, 0, 0)] * 3
        self.hud.update(DT, self.game)
        self.assertEqual(self.lost_lines(), 1)
        self.game.events = [("tower_lost", 0, 0, 0)]
        self.hud.update(DT, self.game)
        self.assertEqual(self.lost_lines(), 1)               # still cooling down
        self.hud.update(ui.TOWER_LOST_COOLDOWN + 0.1, self.game)
        self.game.events = [("tower_lost", 0, 0, 0)]
        self.hud.update(DT, self.game)
        self.assertEqual(self.lost_lines(), 2)

    def test_restart_resets_the_log_and_counters(self):
        self.game.start_wave()
        self.step(2.0)
        self.assertTrue(self.hud.log.lines or self.hud.log.typing)
        self.game.reset()
        self.hud.update(DT, self.game)
        self.assertIsNone(self.hud.banner)
        self.assertEqual(self.hud.log.lines, [])
        self.assertEqual(self.hud.supply.value, self.game.map.start_supply)

    def test_cards_lift_under_the_cursor_and_settle_back(self):
        rects = self.hud.card_rects(self.game)
        key = "mortar"
        self.hud.mouse = rects[key].center
        for _ in range(20):
            self.hud.update(DT, self.game)
        self.assertGreater(self.hud.lift[key], 0.9)
        self.assertLess(self.hud.lift["mg_nest"], 0.05)
        self.hud.mouse = (5, 5)
        for _ in range(30):
            self.hud.update(DT, self.game)
        self.assertLess(self.hud.lift[key], 0.05)

    # ---- clicks ----
    def test_clicking_a_card_selects_it(self):
        for key, rect in self.hud.card_rects(self.game).items():
            self.assertEqual(self.hud.hit_test(rect.center, self.game), ("card", key))

    def test_clicks_on_the_map_pass_through(self):
        self.assertIsNone(self.hud.hit_test((300, 300), self.game))
        gap = (self.hud.card_rects(self.game)["mg_nest"].right + 2, self.hud.tray_y + 30)
        self.assertIsNone(self.hud.hit_test(gap, self.game))

    def test_call_wave_button_only_works_between_waves(self):
        pos = self.hud.button_rect.center
        self.assertEqual(self.hud.hit_test(pos, self.game), ("next_wave", None))
        self.game.start_wave()
        self.assertIsNone(self.hud.hit_test(pos, self.game))

    def test_button_is_dead_after_the_last_wave_is_called(self):
        self.game.wave = len(self.game.map.waves)
        self.assertFalse(ui.Hud.can_call(self.game))

    def test_restart_stamp_is_clickable_only_on_the_end_card(self):
        self.assertIsNone(self.hud.hit_test((10, 10), self.game))
        self.game.state = "lost"
        self.hud.draw(self.screen, self.game, "mg_nest")
        self.assertEqual(self.hud.hit_test(self.hud.restart_rect.center, self.game), ("restart", None))
        self.assertIsNone(self.hud.hit_test(self.hud.card_rects(self.game)["mortar"].center, self.game))

    # ---- fit ----
    def test_tower_names_fit_their_cards(self):
        for key in self.game.map.towers:
            lines = ui.wrap(self.hud.f_small, self.strings.get(f"tower.{key}.name"), ui.CARD_W - 28)
            self.assertLessEqual(len(lines), 2, key)
            for ln in lines:
                self.assertLessEqual(self.hud.f_small.size(ln)[0], ui.CARD_W - 28, ln)

    def test_top_strip_blocks_do_not_collide(self):
        h = self.hud
        s = self.strings
        self.assertLess(12 + max(h.f_small.size(s.get("hud.supply"))[0], h.f_num.size("99999")[0]), 214 - 10)
        self.assertLess(214 + max(h.f_small.size(s.get("hud.integrity"))[0], h.f_num.size("99")[0]), 420 - 10)
        wave = h.f_num.size(s.get("hud.wave_value", wave=8, total=8))[0]
        tod = max(h.f_label.size(s.get(f"time.{t}").upper())[0] for t in ("day", "dusk", "dark", "dawn"))
        self.assertLess(420 + wave + 10 + tod, h.button_rect.left - 8)

    def test_button_text_fits_its_tag(self):
        h = self.hud
        s = self.strings
        key = h.f_small.size(s.get("hud.next_wave_key"))[0]
        self.assertLess(10 + h.f_label.size(s.get("hud.next_wave"))[0] + 8 + key + 8, h.button_rect.w)
        self.assertLess(10 + h.f_label.size(s.get("hud.next_wave_busy"))[0] + 8, h.button_rect.w)

    def test_every_radio_line_and_banner_fits(self):
        h = self.hud
        width = ui.LOG_W - 20
        for w in self.game.map.waves:
            line = self.strings.get(w.log_key)
            self.assertLessEqual(len(ui.wrap(h.f_log, line, width)), 4, line)
            text = ui.banner_text(line)
            self.assertLessEqual(h.banner_font(text).size(text)[0] + 36,
                                 self.game.map.world_size[0] - 40, line)
        for key in ("log.start", "log.wave_clear", "log.tower_lost", "log.resupply"):
            self.assertLessEqual(len(ui.wrap(h.f_log, self.strings.get(key), width)), 4)

    def test_tooltips_fit_four_lines(self):
        for key in self.game.map.towers:
            self.assertLessEqual(len(ui.wrap(self.hud.f_tip, self.strings.get(f"tower.{key}.role"), 230)), 4)

    def test_debrief_fits_its_card(self):
        h = self.hud
        for outcome in ("won", "lost"):
            self.assertLess(h.f_body.size(self.strings.get(f"end.{outcome}.body"))[0], 560)
            self.assertLess(h.f_title.size(self.strings.get(f"end.{outcome}.title").upper())[0], 580)
        ctx = ui.wrap(h.f_stat, self.strings.get("map.firebase.context"), 560)
        self.assertLessEqual(len(ctx), 3)

    # ---- drawing ----
    def test_draws_every_state_with_big_numbers(self):
        g = self.game
        g.supply = 99999
        g.stats.update(waves_cleared=8, stopped=9999, leaked=99, built=99, lost=99)
        for state in ("playing", "won", "lost"):
            g.state = state
            for mouse in ((0, 0), self.hud.card_rects(g)["flare"].center, self.hud.button_rect.center):
                self.hud.mouse = mouse
                self.hud.update(DT, g)
                self.hud.draw(self.screen, g, "flare")

    def test_banner_and_end_card_do_not_draw_together(self):
        self.game.start_wave()
        self.step(0.5)
        self.assertIsNotNone(self.hud.banner)
        self.game.state = "won"
        self.hud.draw(self.screen, self.game, "mg_nest")     # must not raise; banner skipped


class AudioTests(unittest.TestCase):
    def test_unknown_keys_are_rejected(self):
        with self.assertRaises(KeyError):
            audio.play("not_a_sound")

    def test_history_is_bounded(self):
        for _ in range(500):
            audio.play("ui_click")
        self.assertLessEqual(len(audio.history), 200)

    def test_every_key_plays(self):
        for k in audio.KEYS:
            audio.play(k)


class EndToEndTests(unittest.TestCase):
    def test_play_a_wave_through_the_ui(self):
        pygame.display.init()
        pygame.font.init()
        g = Game(CONTENT, "firebase")
        screen = pygame.display.set_mode(screen_size(g.map))
        r = Renderer(Strings.load(), Assets(), g.map)
        audio.history.clear()
        r.update(DT, g)
        r.draw(screen, g, "mg_nest", (0, 0))
        # click a card, then a map tile, then the call-wave button
        card = r.hit_test(r.hud.card_rects(g)["mg_nest"].center, g)
        self.assertEqual(card, ("card", "mg_nest"))
        self.assertIsNone(r.hit_test((14 * 40 + 20, HUD_H + 6 * 40 + 20), g))
        self.assertTrue(g.try_build(14, 6, "mg_nest"))
        self.assertEqual(r.hit_test(r.hud.button_rect.center, g), ("next_wave", None))
        g.start_wave()
        for _ in range(60 * 90):
            g.update(DT)
            r.update(DT, g)
            r.draw(screen, g, "mg_nest", (0, 0)) if _ % 30 == 0 else None
            if not g.wave_active:
                break
        for _ in range(60 * 8):                 # let the clear and resupply lines type out
            g.update(DT)
            r.update(DT, g)
        text = " ".join(r.hud.log.lines)
        self.assertIn(Strings.load().get("log.firebase.w1"), text)
        self.assertIn(Strings.load().get("log.resupply"), text)
        self.assertIn("radio_key", audio.history)
        pygame.quit()


if __name__ == "__main__":
    unittest.main()
