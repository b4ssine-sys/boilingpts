import os
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pygame

from content import CONTENT
from render import Renderer, screen_size
from sim import Game
from strings import Strings


class RenderSmokeTests(unittest.TestCase):
    def setUp(self):
        pygame.display.init()
        pygame.font.init()
        self.game = Game(CONTENT, "prototype")
        self.screen = pygame.display.set_mode(screen_size(self.game.map))
        self.font = pygame.font.SysFont(None, 26)
        self.renderer = Renderer(Strings.load(), self.font, pygame.font.SysFont(None, 72))

    def tearDown(self):
        pygame.quit()

    def test_draws_in_every_state(self):
        g = self.game
        g.try_build(5, 3, "mg_nest")
        g.start_wave()
        for _ in range(300):
            g.update(1 / 60)
            self.renderer.draw(self.screen, g, "mg_nest", (100, 100))
        for state in ("won", "lost"):
            g.state = state
            self.renderer.draw(self.screen, g, "mg_nest", (100, 100))

    def test_hud_line_fits_window(self):
        s = self.renderer.strings
        line = s.get("hud.status", supply=9999, integrity=10, wave=5, total=5,
                     tower=s.get("tower.mg_nest.name"), cost=50,
                     hint=s.get("hud.hint_next_wave"))
        self.assertLessEqual(self.font.size(line)[0] + 10, self.screen.get_width())


if __name__ == "__main__":
    unittest.main()
