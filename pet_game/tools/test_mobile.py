# -*- coding: utf-8 -*-
"""
tools/test_mobile.py —— 移动端适配层自测（开发辅助工具，不进 APK）
=========================================================
覆盖：
  1. 桌面：窗口尺寸 == 逻辑尺寸 → 不缩放、零开销、坐标直通
  2. 安卓：模拟 1080x2400 真机 → 缩放比 / 居中偏移 / 信箱填充
  3. 坐标换算：屏幕像素 → 640x800 逻辑坐标
  4. 触摸兜底：FINGER* 合成鼠标事件；有鼠标事件时不重复触发
  5. 端到端：用"手机屏幕坐标"点按钮，互动真的生效
  6. 安卓返回键：先关面板，再退出
  7. 缩放上屏不崩

用法：  python tools/test_mobile.py
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pygame  # noqa: E402
import platform_util as PU  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [OK]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}  {extra}")


def section(title: str):
    print(f"\n=== {title} ===")


# =========================================================
#  1. 桌面：完全不变
# =========================================================
section("1. 桌面（窗口尺寸 == 逻辑尺寸）")
dm = PU.DisplayManager((640, 800), "test")
check("不缩放 (scale == 1.0)", dm.scale == 1.0, f"scale={dm.scale}")
check("logical 就是窗口本身 → 零额外开销", dm.logical is dm.window)
check("坐标直通，不做任何换算", dm.to_logical((123, 456)) == (123, 456))
check("needs_transform 为 False", dm.needs_transform is False)
dm.present()
check("present() 不崩", True)

# =========================================================
#  2. 模拟真机 1080x2400（走真实的安卓分支代码）
# =========================================================
section("2. 安卓 1080x2400")
PU.is_android = lambda: True                      # 强制走安卓分支
PU.android_screen_size = lambda: (1080, 2400)

dm2 = PU.DisplayManager((640, 800), "test",
                        gradient=((214, 232, 245), (252, 238, 246)))
check("窗口取到真实屏幕尺寸", dm2.win_size == (1080, 2400), f"{dm2.win_size}")
check("logical 是独立画布（不是窗口）", dm2.logical is not dm2.window)
check("logical 尺寸仍是 640x800", dm2.logical.get_size() == (640, 800))
check("缩放比 = min(1080/640, 2400/800) = 1.6875",
      abs(dm2.scale - 1.6875) < 1e-9, f"scale={dm2.scale}")
check("等比缩放 → 1080x1350", dm2.dest.size == (1080, 1350), f"{dm2.dest.size}")
check("垂直居中 → 上下各留 525", dm2.dest.x == 0 and dm2.dest.y == 525,
      f"dest={tuple(dm2.dest)}")

# =========================================================
#  3. 坐标换算
# =========================================================
section("3. 屏幕像素坐标 → 逻辑坐标")
mid = dm2.to_logical((540, 1200))
check("屏幕正中心 → 逻辑正中心 (320,400)",
      abs(mid[0] - 320) < 1e-6 and abs(mid[1] - 400) < 1e-6, f"{mid}")
tl = dm2.to_logical((0, 525))
check("画布左上角映射正确 (0,0)",
      abs(tl[0]) < 1e-6 and abs(tl[1]) < 1e-6, f"{tl}")
br = dm2.to_logical((1080, 1875))
check("画布右下角映射正确 (640,800)",
      abs(br[0] - 640) < 1e-6 and abs(br[1] - 800) < 1e-6, f"{br}")
for wx, wy in [(137, 902), (864, 1780), (12, 640)]:
    lx, ly = dm2.to_logical((wx, wy))
    rx = lx * dm2.scale + dm2.dest.x
    ry = ly * dm2.scale + dm2.dest.y
    check(f"往返一致 ({wx},{wy})", abs(rx - wx) < 1e-6 and abs(ry - wy) < 1e-6)

# =========================================================
#  4. 触摸 → 鼠标
# =========================================================
section("4. 触摸事件兜底")
finger = pygame.event.Event(pygame.FINGERDOWN, {
    "x": 0.5, "y": 0.5, "finger_id": 0, "touch_id": 0, "pressure": 1.0})
out = dm2.prepare_events([finger])
check("只有 FINGERDOWN 时合成 MOUSEBUTTONDOWN",
      len(out) == 1 and out[0].type == pygame.MOUSEBUTTONDOWN,
      f"{[e.type for e in out]}")
check("归一化触摸坐标按窗口尺寸还原成 (540,1200)",
      abs(out[0].pos[0] - 540) < 1 and abs(out[0].pos[1] - 1200) < 1,
      f"{out[0].pos}")
tr = dm2.translate_event(out[0])
check("再换算后落在逻辑中心 (320,400)",
      abs(tr.pos[0] - 320) < 1e-6 and abs(tr.pos[1] - 400) < 1e-6, f"{tr.pos}")

mouse = pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": (7, 9), "button": 1})
out2 = dm2.prepare_events([finger, mouse])
check("同时有鼠标事件时丢弃触摸事件（避免一次点击算两次）",
      len(out2) == 1 and out2[0].pos == (7, 9), f"{[e.pos for e in out2]}")

up = pygame.event.Event(pygame.FINGERUP, {
    "x": 0.25, "y": 0.75, "finger_id": 0, "touch_id": 0, "pressure": 0.0})
out3 = dm2.prepare_events([up])
check("FINGERUP 合成 MOUSEBUTTONUP",
      len(out3) == 1 and out3[0].type == pygame.MOUSEBUTTONUP)

# =========================================================
#  5. 端到端：手机坐标点按钮，互动生效
# =========================================================
section("5. 端到端：手机上点击按钮触发互动")
import main as M  # noqa: E402

game = M.Game()
check("Game 启用缩放画布", game.screen is game.display.logical
      and game.display.scale > 1.0, game.display.describe())

KEYS = ("hunger", "happiness", "energy")


def stats():
    return {k: game.pet.get_stat(k) for k in KEYS}


def _screen(logical_pos):
    """把逻辑坐标换算成手机屏幕上真实的像素坐标。"""
    return (game.display.dest.x + logical_pos[0] * game.display.scale,
            game.display.dest.y + logical_pos[1] * game.display.scale)


def tap_mouse(logical_pos):
    """SDL 已把触摸合成鼠标事件的情形：按下 + 抬起。"""
    wx, wy = _screen(logical_pos)
    for t in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
        pygame.event.post(pygame.event.Event(t, {"pos": (wx, wy), "button": 1}))
    game.handle_events()


def tap_finger(logical_pos):
    """纯触摸兜底路径：只发 FINGER*，一个鼠标事件都不发。"""
    ww, wh = game.display.win_size
    wx, wy = _screen(logical_pos)
    for t in (pygame.FINGERDOWN, pygame.FINGERUP):
        pygame.event.post(pygame.event.Event(t, {
            "x": wx / ww, "y": wy / wh,
            "finger_id": 0, "touch_id": 0, "pressure": 1.0}))
    game.handle_events()


btn, spec = game.buttons[0]
label = spec.get("label", spec.get("id", "?"))

before = stats()
tap_mouse(btn.rect.center)
after = stats()
check(f"点「{label}」（鼠标合成路径）互动生效",
      before != after, f"before={before} after={after}")

# 等冷却结束，再用"纯触摸"走一遍同一条链路
game.update(12.0)
before = stats()
tap_finger(btn.rect.center)
after = stats()
check(f"点「{label}」（纯触摸兜底路径）互动生效",
      before != after, f"before={before} after={after}")

# 信箱区域（画面之外）的点击不该误触任何按钮
game.update(12.0)
before = stats()
tap_mouse((320, 40))           # 顶部信箱
tap_mouse((320, 798))          # 底部信箱
after = stats()
check("点在信箱区域不会误触按钮", before == after, f"{before} -> {after}")

# =========================================================
#  6. 安卓返回键
# =========================================================
section("6. 安卓返回键")
if PU._AC_BACK is None:
    print("  [SKIP] 当前 pygame 没有 K_AC_BACK")
else:
    game.wardrobe_open = True
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, {
        "key": pygame.K_AC_BACK, "mod": 0, "unicode": "", "scancode": 0}))
    game.handle_events()
    check("第一次按返回键 → 关掉衣橱面板", game.wardrobe_open is False)
    check("此时游戏没有退出", game.running is True)

    game.comp_panel_open = True
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, {
        "key": pygame.K_AC_BACK, "mod": 0, "unicode": "", "scancode": 0}))
    game.handle_events()
    check("面板打开时按返回键 → 关掉宠物面板", game.comp_panel_open is False)

    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, {
        "key": pygame.K_AC_BACK, "mod": 0, "unicode": "", "scancode": 0}))
    game.handle_events()
    check("没有面板时按返回键 → 退出游戏", game.running is False)

# =========================================================
#  7. 缩放上屏
# =========================================================
section("7. 缩放到真机分辨率并上屏")
game.draw()
check("draw() + present() 在缩放模式下不崩", True)
try:
    centre = game.window.get_at((540, 1200))
    edge = game.window.get_at((540, 8))
    check("画面中心已铺满内容", centre.a == 255)
    check("信箱区域是背景渐变而不是黑边",
          edge[:3] != (0, 0, 0), f"letterbox={edge}")
except Exception as e:
    check("读取窗口像素", False, repr(e))

pygame.quit()

# =========================================================
print("\n" + "=" * 52)
print(f"  移动端适配自测：{PASS} 通过 / {FAIL} 失败")
print("=" * 52)
sys.exit(1 if FAIL else 0)
