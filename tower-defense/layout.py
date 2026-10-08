"""Screen layout constants shared by the renderer and the UI."""
HUD_H = 40    # resource strip across the top
TRAY_H = 80   # build tray and radio log along the bottom


def screen_size(game_map):
    w, h = game_map.world_size
    return w, HUD_H + h + TRAY_H
