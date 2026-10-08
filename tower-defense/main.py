"""Minimal tower defense prototype.

Click a free grass tile to build a tower (costs gold). Towers shoot the
enemy closest to the end of the path. Survive all waves to win.
Press SPACE to start the next wave early, R to restart, ESC to quit.
"""
import math
import sys

import pygame

TILE = 40
COLS, ROWS = 20, 15
HUD_H = 40
WIDTH, HEIGHT = COLS * TILE, ROWS * TILE + HUD_H
FPS = 60

# Path as grid corners (col, row); enemies walk straight between them.
PATH_CORNERS = [(0, 2), (6, 2), (6, 10), (13, 10), (13, 4), (19, 4)]

TOWER_COST = 50
TOWER_RANGE = 120
TOWER_COOLDOWN = 0.5
TOWER_DAMAGE = 10
BULLET_SPEED = 400
START_GOLD = 150
START_LIVES = 10
KILL_REWARD = 10
WAVE_BONUS = 25
SPAWN_INTERVAL = 0.7
WAVES = [  # (enemy count, hp, speed px/s)
    (6, 30, 70),
    (10, 40, 80),
    (12, 60, 80),
    (15, 80, 90),
    (20, 100, 100),
]

GRASS = (74, 140, 70)
DIRT = (176, 140, 90)
WHITE = (240, 240, 240)
BLACK = (20, 20, 20)
RED = (200, 50, 50)
GREEN = (60, 200, 80)
BLUE = (70, 110, 220)
YELLOW = (240, 210, 60)


def build_path_tiles(corners):
    tiles = set()
    for (c0, r0), (c1, r1) in zip(corners, corners[1:]):
        dc = (c1 > c0) - (c1 < c0)
        dr = (r1 > r0) - (r1 < r0)
        c, r = c0, r0
        tiles.add((c, r))
        while (c, r) != (c1, r1):
            c, r = c + dc, r + dr
            tiles.add((c, r))
    return tiles


def tile_center(col, row):
    return (col * TILE + TILE / 2, row * TILE + TILE / 2 + HUD_H)


PATH_TILES = build_path_tiles(PATH_CORNERS)
WAYPOINTS = [tile_center(c, r) for c, r in PATH_CORNERS]


class Enemy:
    def __init__(self, hp, speed):
        self.x, self.y = WAYPOINTS[0]
        self.hp = self.max_hp = hp
        self.speed = speed
        self.target = 1
        self.progress = 0.0  # total distance walked, used for targeting
        self.reached_end = False

    @property
    def alive(self):
        return self.hp > 0 and not self.reached_end

    def update(self, dt):
        step = self.speed * dt
        self.progress += step
        while step > 0 and self.target < len(WAYPOINTS):
            tx, ty = WAYPOINTS[self.target]
            dist = math.hypot(tx - self.x, ty - self.y)
            if dist <= step:
                self.x, self.y = tx, ty
                step -= dist
                self.target += 1
            else:
                self.x += (tx - self.x) / dist * step
                self.y += (ty - self.y) / dist * step
                step = 0
        if self.target >= len(WAYPOINTS):
            self.reached_end = True


class Bullet:
    def __init__(self, x, y, enemy):
        self.x, self.y = x, y
        self.enemy = enemy
        self.done = False

    def update(self, dt):
        if not self.enemy.alive:
            self.done = True
            return
        dx, dy = self.enemy.x - self.x, self.enemy.y - self.y
        dist = math.hypot(dx, dy)
        step = BULLET_SPEED * dt
        if dist <= step:
            self.enemy.hp -= TOWER_DAMAGE
            self.done = True
        else:
            self.x += dx / dist * step
            self.y += dy / dist * step


class Tower:
    def __init__(self, col, row):
        self.col, self.row = col, row
        self.x, self.y = tile_center(col, row)
        self.cooldown = 0.0

    def update(self, dt, enemies, bullets):
        self.cooldown -= dt
        if self.cooldown > 0:
            return
        in_range = [e for e in enemies
                    if e.alive and math.hypot(e.x - self.x, e.y - self.y) <= TOWER_RANGE]
        if in_range:
            target = max(in_range, key=lambda e: e.progress)
            bullets.append(Bullet(self.x, self.y, target))
            self.cooldown = TOWER_COOLDOWN


class Game:
    def __init__(self):
        self.reset()

    def reset(self):
        self.gold = START_GOLD
        self.lives = START_LIVES
        self.wave = 0  # number of waves started
        self.towers = {}
        self.enemies = []
        self.bullets = []
        self.to_spawn = 0
        self.spawn_timer = 0.0
        self.wave_hp = 0
        self.wave_speed = 0
        self.state = "playing"  # playing | won | lost

    @property
    def wave_active(self):
        return self.to_spawn > 0 or any(e.alive for e in self.enemies)

    def start_wave(self):
        if self.state != "playing" or self.wave_active or self.wave >= len(WAVES):
            return
        count, hp, speed = WAVES[self.wave]
        self.wave += 1
        self.to_spawn, self.wave_hp, self.wave_speed = count, hp, speed
        self.spawn_timer = 0.0

    def try_build(self, col, row):
        if self.state != "playing":
            return False
        if not (0 <= col < COLS and 0 <= row < ROWS):
            return False
        if (col, row) in PATH_TILES or (col, row) in self.towers:
            return False
        if self.gold < TOWER_COST:
            return False
        self.gold -= TOWER_COST
        self.towers[(col, row)] = Tower(col, row)
        return True

    def update(self, dt):
        if self.state != "playing":
            return
        was_active = self.wave_active
        if self.to_spawn > 0:
            self.spawn_timer -= dt
            if self.spawn_timer <= 0:
                self.enemies.append(Enemy(self.wave_hp, self.wave_speed))
                self.to_spawn -= 1
                self.spawn_timer = SPAWN_INTERVAL
        for e in self.enemies:
            e.update(dt)
        for t in self.towers.values():
            t.update(dt, self.enemies, self.bullets)
        for b in self.bullets:
            b.update(dt)
        for e in self.enemies:
            if e.hp <= 0:
                self.gold += KILL_REWARD
            elif e.reached_end:
                self.lives -= 1
        self.enemies = [e for e in self.enemies if e.alive]
        self.bullets = [b for b in self.bullets if not b.done]

        if self.lives <= 0:
            self.state = "lost"
        elif was_active and not self.wave_active:
            if self.wave >= len(WAVES):
                self.state = "won"
            else:
                self.gold += WAVE_BONUS

    # ---- rendering ----
    def draw(self, screen, font, big_font):
        screen.fill(BLACK)
        for r in range(ROWS):
            for c in range(COLS):
                color = DIRT if (c, r) in PATH_TILES else GRASS
                pygame.draw.rect(screen, color, (c * TILE, r * TILE + HUD_H, TILE, TILE))
                pygame.draw.rect(screen, (0, 0, 0, 30), (c * TILE, r * TILE + HUD_H, TILE, TILE), 1)

        mx, my = pygame.mouse.get_pos()
        hc, hr = mx // TILE, (my - HUD_H) // TILE
        if (0 <= hc < COLS and 0 <= hr < ROWS and (hc, hr) not in PATH_TILES
                and (hc, hr) not in self.towers):
            cx, cy = tile_center(hc, hr)
            ok = self.gold >= TOWER_COST
            pygame.draw.circle(screen, WHITE if ok else RED, (cx, cy), TOWER_RANGE, 1)

        for t in self.towers.values():
            pygame.draw.rect(screen, BLUE, (t.x - 14, t.y - 14, 28, 28), border_radius=4)
            pygame.draw.circle(screen, WHITE, (t.x, t.y), 6)
        for e in self.enemies:
            pygame.draw.circle(screen, RED, (e.x, e.y), 11)
            w = 24
            pygame.draw.rect(screen, BLACK, (e.x - w / 2, e.y - 18, w, 4))
            pygame.draw.rect(screen, GREEN, (e.x - w / 2, e.y - 18, w * max(e.hp, 0) / e.max_hp, 4))
        for b in self.bullets:
            pygame.draw.circle(screen, YELLOW, (b.x, b.y), 3)

        pygame.draw.rect(screen, (30, 30, 40), (0, 0, WIDTH, HUD_H))
        wave_txt = f"Wave {self.wave}/{len(WAVES)}"
        hint = "" if self.wave_active or self.state != "playing" else "  [SPACE: next wave]"
        info = f"Gold {self.gold}   Lives {self.lives}   {wave_txt}   Tower {TOWER_COST}g{hint}"
        screen.blit(font.render(info, True, WHITE), (10, 10))

        if self.state != "playing":
            msg = "YOU WIN!" if self.state == "won" else "GAME OVER"
            label = big_font.render(msg, True, YELLOW)
            sub = font.render("Press R to restart", True, WHITE)
            screen.blit(label, label.get_rect(center=(WIDTH / 2, HEIGHT / 2 - 10)))
            screen.blit(sub, sub.get_rect(center=(WIDTH / 2, HEIGHT / 2 + 30)))


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("Tower Defense")
    clock = pygame.time.Clock()
    font = pygame.font.SysFont(None, 26)
    big_font = pygame.font.SysFont(None, 72)
    game = Game()

    while True:
        dt = clock.tick(FPS) / 1000
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    sys.exit()
                elif event.key == pygame.K_SPACE:
                    game.start_wave()
                elif event.key == pygame.K_r:
                    game.reset()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                x, y = event.pos
                game.try_build(x // TILE, (y - HUD_H) // TILE)
        game.update(dt)
        game.draw(screen, font, big_font)
        pygame.display.flip()


if __name__ == "__main__":
    main()
