# -*- coding: utf-8 -*-
"""
tools/make_icon.py —— 生成安卓应用图标与启动图
=========================================================
直接复用游戏里绘制的高紫桐贴图，输出到仓库根目录：

    icon.png       512x512  应用图标
    presplash.png  512x1024 启动时的过场图

用法：  python tools/make_icon.py
"""
from __future__ import annotations

import math
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = os.path.join(ROOT, "pet_game")
sys.path.insert(0, GAME)

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((64, 64))

from config import (BG_TOP, BG_BOTTOM, GROUND, GROUND_DEEP,  # noqa: E402
                    PINK_DEEP, SKY_DEEP, PET_NAME)
from pet import Pet  # noqa: E402
from utils import sticker_outline, mix  # noqa: E402


def gradient(size, top, bottom):
    w, h = size
    strip = pygame.Surface((1, h))
    for y in range(h):
        strip.set_at((0, y), mix(top, bottom, y / max(1, h - 1)))
    return pygame.transform.smoothscale(strip, size)


def glow(surface, center, radius, color, alpha=120, rings=26):
    """柔和径向光晕（同心圆叠出渐变，不破坏底图 alpha）。"""
    layer = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    step = max(1, radius // rings)
    for r in range(radius, 0, -step):
        a = int(alpha * (1 - r / radius) ** 1.6)
        pygame.draw.circle(layer, (*color, a), center, r)
    surface.blit(layer, (0, 0))


def ground(surface, cx, cy, rx, ry, color, alpha=150):
    """地面椭圆（半透明，别抢角色的视觉重心）。"""
    layer = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    pygame.draw.ellipse(layer, (*color, alpha),
                        pygame.Rect(cx - rx, cy - ry, rx * 2, ry * 2))
    surface.blit(layer, (0, 0))


def character(pet, height):
    """取出主角贴图，裁掉透明留白并加一圈贴纸描边。"""
    sprite = pet._render(outfit_id="classic", emo=pet.NORMAL, blink=False)
    rect = sprite.get_bounding_rect(min_alpha=10)
    char = sprite.subsurface(rect).copy()
    scale = height / char.get_height()
    char = pygame.transform.smoothscale(
        char, (max(1, int(char.get_width() * scale)), int(height)))
    return sticker_outline(char, width=5)


def main():
    pet = Pet(PET_NAME)

    # ---------------- 应用图标 512x512 ----------------
    # 注意：安卓自适应图标会裁成圆形，主体必须留在中间 ~66% 的安全区里
    S = 512
    icon = gradient((S, S), BG_TOP, BG_BOTTOM)
    glow(icon, (S // 2, int(S * 0.46)), int(S * 0.42), PINK_DEEP, alpha=95)
    glow(icon, (S // 2, int(S * 0.62)), int(S * 0.30), SKY_DEEP, alpha=70)

    # 角色放在中下部，去掉贴纸白描边带来的"糊边"
    char = character(pet, int(S * 0.66))
    icon.blit(char, char.get_rect(center=(S // 2, int(S * 0.53))))

    p_icon = os.path.join(ROOT, "icon.png")
    pygame.image.save(icon, p_icon)
    print("  ->", p_icon)

    # ---------------- 启动图 512x1024 ----------------
    W, H = 512, 1024
    splash = gradient((W, H), BG_TOP, BG_BOTTOM)
    glow(splash, (W // 2, int(H * 0.42)), int(W * 0.62), (255, 255, 255), alpha=150)

    # 几颗小光点
    for cx, cy, r, a in [(96, 190, 26, 70), (420, 250, 34, 60),
                         (140, 700, 30, 55), (400, 660, 22, 65)]:
        layer = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
        pygame.draw.circle(layer, (255, 255, 255, a), (r, r), r)
        splash.blit(layer, (cx - r, cy - r))

    char = character(pet, int(H * 0.42))
    splash.blit(char, char.get_rect(center=(W // 2, int(H * 0.44))))

    # 草地：和游戏里同一条地面色，半透明地接住角色
    ground(splash, W // 2, int(H * 0.68), int(W * 0.40), 34, GROUND_DEEP, 90)
    ground(splash, W // 2, int(H * 0.665), int(W * 0.40), 30, GROUND, 130)

    p_splash = os.path.join(ROOT, "presplash.png")
    pygame.image.save(splash, p_splash)
    print("  ->", p_splash)

    pygame.quit()


if __name__ == "__main__":
    main()
