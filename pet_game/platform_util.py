# -*- coding: utf-8 -*-
"""
platform_util.py —— 桌面 / 安卓 双端适配层
=========================================================
这一层只干三件事，**游戏逻辑与绘制代码一行都不用改**：

1. DisplayManager
   把 640x800 的「逻辑画布」等比缩放、居中铺到任意手机屏幕上，
   多出来的「信箱区域」用游戏本身的背景渐变填充，不会出现黑边。
   桌面窗口尺寸刚好等于逻辑尺寸时 scale==1，self.logical 直接就是
   窗口本身 —— 零额外开销，表现与改造前完全一致。

2. 触摸 → 鼠标
   安卓没有鼠标。SDL2 通常会把触摸合成为鼠标事件；这里做兜底：
   只有当**整帧都没有鼠标事件**时，才用 FINGERDOWN/UP/MOTION 合成。
   这样不会出现「一次点击被处理两遍」。

3. 坐标换算 / 安卓返回键 / 屏幕常亮 / 沉浸式全屏

【改分辨率只改 config.WIDTH/HEIGHT，本文件自动适配】
【想关掉某个行为，改 config 里的 FULLSCREEN_MODE / MOBILE_SMOOTH_SCALE】
"""
from __future__ import annotations

import os
import sys

import pygame


# =========================================================
#  平台判定
# =========================================================
def is_android() -> bool:
    """python-for-android 启动时会往环境里塞这些变量。"""
    if sys.platform == "android":
        return True
    return any(k in os.environ for k in (
        "ANDROID_ARGUMENT", "ANDROID_BOOTLOGO",
        "ANDROID_PRIVATE", "P4A_BOOTSTRAP",
    ))


_AC_BACK = getattr(pygame, "K_AC_BACK", None)


def is_back_key(key) -> bool:
    """安卓手机的物理/手势返回键。"""
    return _AC_BACK is not None and key == _AC_BACK


# =========================================================
#  安卓原生小能力（拿不到就静默跳过，绝不让游戏崩）
# =========================================================
def android_screen_size():
    """真实屏幕像素尺寸；非安卓或取不到时返回 None。"""
    if not is_android():
        return None
    try:
        from jnius import autoclass  # type: ignore
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        metrics = autoclass("android.util.DisplayMetrics")()
        activity.getWindowManager().getDefaultDisplay().getRealMetrics(metrics)
        w, h = int(metrics.widthPixels), int(metrics.heightPixels)
        return (w, h) if w > 0 and h > 0 else None
    except Exception:
        return None


def keep_screen_on() -> bool:
    """玩游戏时别让屏幕自己黑掉。"""
    if not is_android():
        return False
    try:
        from jnius import autoclass  # type: ignore
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        lp = autoclass("android.view.WindowManager$LayoutParams")
        activity.getWindow().addFlags(lp.FLAG_KEEP_SCREEN_ON)
        return True
    except Exception:
        return False


def go_immersive() -> bool:
    """隐藏状态栏 / 导航栏，让画面铺满整屏。"""
    if not is_android():
        return False
    try:
        from jnius import autoclass  # type: ignore
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        view = autoclass("android.view.View")
        decor = activity.getWindow().getDecorView()
        flag = (view.SYSTEM_UI_FLAG_LAYOUT_STABLE
                | view.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                | view.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                | view.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                | view.SYSTEM_UI_FLAG_FULLSCREEN
                | view.SYSTEM_UI_FLAG_IMMERSIVE_STICKY)
        decor.setSystemUiVisibility(flag)
        return True
    except Exception:
        return False


def setup_android() -> dict:
    """进入游戏后调一次；返回各项是否成功，方便日志排查。"""
    return {
        "screen_on": keep_screen_on(),
        "immersive": go_immersive(),
    }


# =========================================================
#  显示管理器
# =========================================================
class DisplayManager:
    """
    用法（main.Game.__init__ 里）：

        self.display = DisplayManager((WIDTH, HEIGHT), TITLE,
                                      fullscreen=FULLSCREEN_MODE,
                                      smooth=MOBILE_SMOOTH_SCALE,
                                      gradient=(BG_TOP, BG_BOTTOM))
        self.screen = self.display.logical     # ← 之后所有绘制都画在它上面
        ...
        # 事件循环：
        for e in self.display.prepare_events(pygame.event.get()):
            e = self.display.translate_event(e)   # 屏幕坐标 → 逻辑坐标
            ...
        # 每帧末尾：
        self.display.present()
    """

    def __init__(self, logical_size, caption: str = "", fullscreen=None,
                 smooth: bool = True, gradient=(None, None)):
        self.logical_size = (int(logical_size[0]), int(logical_size[1]))
        self.android = is_android()
        self.smooth = bool(smooth)
        self._grad_colors = gradient

        if caption:
            pygame.display.set_caption(caption)

        if fullscreen is None:
            fullscreen = self.android
        self.fullscreen = bool(fullscreen)

        flags = pygame.FULLSCREEN if self.fullscreen else 0

        # 安卓：直接按真实屏幕分辨率开全屏窗口，最稳
        want = self.logical_size
        if self.android:
            real = android_screen_size()
            if real:
                want = real

        try:
            self.window = pygame.display.set_mode(want, flags)
        except Exception:
            self.window = pygame.display.set_mode(self.logical_size)

        self._relayout()

    # ---------------- 布局 ----------------
    def _relayout(self):
        lw, lh = self.logical_size
        ww, wh = self.window.get_size()
        self.win_size = (ww, wh)

        if (ww, wh) == (lw, lh):
            # 尺寸刚好吻合 → 不需要缩放：逻辑画布 == 窗口，零开销
            self.logical = self.window
            self.scale = 1.0
            self.dest = pygame.Rect(0, 0, lw, lh)
            self._backdrop = None
            return

        self.scale = min(ww / lw, wh / lh)
        dw = max(1, int(round(lw * self.scale)))
        dh = max(1, int(round(lh * self.scale)))
        self.dest = pygame.Rect((ww - dw) // 2, (wh - dh) // 2, dw, dh)
        self.logical = pygame.Surface((lw, lh)).convert()
        self._backdrop = self._make_backdrop(ww, wh)

    def _make_backdrop(self, w: int, h: int):
        """信箱区域填充色：用游戏自身的背景渐变延伸出去，视觉上像一整屏。"""
        top, bottom = self._grad_colors
        if top is None or bottom is None:
            return None
        strip = pygame.Surface((1, h))
        for y in range(h):
            t = y / max(1, h - 1)
            strip.set_at((0, y), tuple(
                int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
        return pygame.transform.scale(strip, (w, h)).convert()

    # ---------------- 坐标 ----------------
    @property
    def needs_transform(self) -> bool:
        return self.scale != 1.0

    def to_logical(self, pos):
        """屏幕像素坐标 → 640x800 逻辑坐标。"""
        if self.scale == 1.0:
            return pos
        return ((pos[0] - self.dest.x) / self.scale,
                (pos[1] - self.dest.y) / self.scale)

    def translate_event(self, event):
        """把带 pos 的事件（鼠标/触摸）就地换算成逻辑坐标。"""
        if self.scale != 1.0 and hasattr(event, "pos"):
            try:
                event.pos = self.to_logical(event.pos)
            except Exception:
                pass
        return event

    # ---------------- 触摸兜底 ----------------
    def _finger_pos(self, e):
        ww, wh = self.win_size
        return (e.x * ww, e.y * wh)          # pygame2 的 x/y 是 0~1 归一化值

    def prepare_events(self, raw):
        """
        统一事件流：
        - 整帧出现过鼠标事件 → 丢掉 FINGER*（SDL 已经帮我们合成了，别重复处理）
        - 整帧没有鼠标事件   → 用 FINGER* 合成鼠标事件（老设备/特殊后端兜底）
        """
        f_down = getattr(pygame, "FINGERDOWN", None)
        f_up = getattr(pygame, "FINGERUP", None)
        f_move = getattr(pygame, "FINGERMOTION", None)

        if f_down is None:
            return list(raw)

        has_mouse = any(e.type in (pygame.MOUSEBUTTONDOWN,
                                   pygame.MOUSEBUTTONUP,
                                   pygame.MOUSEMOTION) for e in raw)

        out = []
        for e in raw:
            if e.type in (f_down, f_up, f_move):
                if has_mouse:
                    continue
                pos = self._finger_pos(e)
                if e.type == f_down:
                    out.append(pygame.event.Event(
                        pygame.MOUSEBUTTONDOWN, {"pos": pos, "button": 1}))
                elif e.type == f_up:
                    out.append(pygame.event.Event(
                        pygame.MOUSEBUTTONUP, {"pos": pos, "button": 1}))
                else:
                    out.append(pygame.event.Event(
                        pygame.MOUSEMOTION,
                        {"pos": pos, "rel": (0, 0), "buttons": (0, 0, 0)}))
            else:
                out.append(e)
        return out

    # ---------------- 出图 ----------------
    def present(self):
        """把逻辑画布缩放贴到窗口并翻页。桌面 scale==1 时等价于原来的 flip()。"""
        if self.scale != 1.0:
            if self._backdrop is not None:
                self.window.blit(self._backdrop, (0, 0))
            else:
                self.window.fill((0, 0, 0))
            dst = self.window.subsurface(self.dest)
            if self.smooth:
                pygame.transform.smoothscale(self.logical, self.dest.size, dst)
            else:
                pygame.transform.scale(self.logical, self.dest.size, dst)
        pygame.display.flip()

    # ---------------- 调试 ----------------
    def describe(self) -> str:
        return (f"display: {'android' if self.android else sys.platform} "
                f"window={self.win_size} logical={self.logical_size} "
                f"scale={self.scale:.4f} dest={tuple(self.dest)} "
                f"smooth={self.smooth}")
