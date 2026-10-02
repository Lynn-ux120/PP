# -*- coding: utf-8 -*-
"""
tools/actionsheet.py —— 把动作预览图拼成对比图（开发辅助工具）
=========================================================
动作是动态的，单看一张图很难判断"幅度够不够、会不会撞到别的动作"。
这个工具把 screenshot.py 生成的 `40_antic_*.png` / `42_pet_*.png`
按角色所在区域裁出来，横向排成一张总览图。

用法：
    python tools/screenshot.py      # 先渲染出各状态图
    python tools/actionsheet.py     # 再拼成总览图

输出：
    preview/50_antics.png      主角的动作总览（第一格是静止状态作对照）
    preview/51_pet_antics.png  小宠物的动作总览
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pygame  # noqa: E402

pygame.init()
pygame.display.set_mode((64, 64))          # dummy 驱动下也需要一个显示上下文

from utils import get_font  # noqa: E402

PREVIEW = os.path.join(ROOT, "preview")

# 裁剪区域：(x, y, w, h) —— 刚好框住角色 / 小宠物
CHAR_CROP = (170, 268, 300, 372)
PET_CROP = (46, 442, 208, 186)

LABEL_COLOR = (120, 102, 118)
GRID_COLOR = (246, 228, 236)

# (标签, 文件名)
CHAR_SHEET = [
    ("原地（静止）", "01_normal.png"),
    ("伸懒腰", "40_antic_stretch.png"),
    ("哼歌摇摆", "40_antic_sway.png"),
    ("原地蹦跳", "40_antic_hop.png"),
    ("歪头张望", "40_antic_tilt.png"),
    ("蹲下来", "40_antic_squat.png"),
    ("转个圈", "40_antic_twirl.png"),
]
PET_SHEET = [
    ("打滚", "42_pet_roll.png"),
    ("追尾巴", "42_pet_spin.png"),
    ("舔毛", "42_pet_groom.png"),
    ("伸懒腰", "42_pet_stretch.png"),
    ("刨地", "42_pet_dig.png"),
    ("坐下", "42_pet_sit.png"),
]


def sheet(items, crop, out_name):
    """把若干张截图的同一区域裁出来，横向拼成一张带标签的图。"""
    cw, ch = crop[2], crop[3]
    pad, lab_h = 10, 30
    surf = pygame.Surface((len(items) * (cw + pad) + pad, ch + lab_h + pad * 2),
                          pygame.SRCALPHA)
    surf.fill((255, 252, 253, 255))
    font = get_font(17, True)

    for i, (label, fname) in enumerate(items):
        path = os.path.join(PREVIEW, fname)
        if not os.path.exists(path):
            print("  ! 缺少", fname, "（先跑 tools/screenshot.py）")
            continue
        img = pygame.image.load(path).convert_alpha()
        sub = img.subsurface(pygame.Rect(*crop)).copy()
        x = pad + i * (cw + pad)
        surf.blit(sub, (x, pad))
        pygame.draw.rect(surf, GRID_COLOR, pygame.Rect(x, pad, cw, ch), 2)
        lab = font.render(label, True, LABEL_COLOR)
        surf.blit(lab, lab.get_rect(center=(x + cw // 2, pad + ch + lab_h // 2)))

    out = os.path.join(PREVIEW, out_name)
    pygame.image.save(surf, out)
    print("  ->", out_name, surf.get_size())


def main():
    print("[动作总览]")
    sheet(CHAR_SHEET, CHAR_CROP, "50_antics.png")
    sheet(PET_SHEET, PET_CROP, "51_pet_antics.png")
    print("完成，输出目录：", PREVIEW)


if __name__ == "__main__":
    main()
