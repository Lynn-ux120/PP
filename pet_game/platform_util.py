# -*- coding: utf-8 -*-
"""
platform_util.py —— 桌面 / 安卓 双端适配层
=========================================================
这一层只干三件事，**游戏逻辑与绘制代码一行都不用改**：

1. DisplayManager
   把 640x800 的「逻辑画布」等比缩放、居中铺到任意手机屏幕上。
   三种模式自动切换（见类文档）：
     - "scaled"  手机上优先：交给 GPU（pygame.SCALED）缩放，CPU 不参与，
                 画面之外的区域用天空色 / 草地色填平，不会出现黑边。
     - "manual"  兜底：窗口按屏幕分辨率开，CPU 缩放 + 纯色补边。
     - "direct"  桌面窗口尺寸刚好等于设计尺寸 → 零额外开销，
                 表现与改造前完全一致。

2. 触摸 → 鼠标
   安卓没有鼠标。SDL2 通常会把触摸合成为鼠标事件；这里做兜底：
   只有当**整帧都没有鼠标事件**时，才用 FINGERDOWN/UP/MOTION 合成。
   这样不会出现「一次点击被处理两遍」。

3. 坐标换算 / 安卓返回键 / 屏幕常亮 / 沉浸式全屏

【改分辨率只改 config.WIDTH/HEIGHT，本文件自动适配】
【想关掉某个行为，改 config 里的 FULLSCREEN_MODE / MOBILE_SMOOTH_SCALE /
  MOBILE_USE_SCALED】
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
                                      band_colors=(BG_TOP, GROUND_DEEP))
        self.screen = self.display.logical     # ← 之后所有绘制都画在它上面
        ...
        # 事件循环：
        for e in self.display.prepare_events(pygame.event.get()):
            e = self.display.translate_event(e)   # 屏幕坐标 → 逻辑坐标
            ...
        # 每帧末尾：
        self.display.present()

    两种工作模式（自动选，见 mode 属性）
    ---------------------------------------------------------
    "scaled"  ★ 手机首选
        用 pygame.SCALED 让 **GPU** 把逻辑画布缩放到整屏，CPU 完全不参与缩放。
        逻辑画布做成和屏幕同比例，游戏画面居中画在中间，上下多出来的部分
        用天空色 / 草地色填平 —— 看上去就是一整屏。
        代价：只有一次 640x1422 的纹理上传。

    "manual"  兜底（SCALED 不可用时 / 桌面调试）
        真实窗口按屏幕分辨率开，逻辑画布 640x800 由 CPU 缩放贴上去，
        四周用纯色 fill 补边。比 scaled 慢，但哪儿都能跑。

    "direct"  桌面窗口尺寸刚好等于设计尺寸 → 不需要任何缩放。
    """

    def __init__(self, logical_size, caption: str = "", fullscreen=None,
                 smooth: bool = True, band_colors=(None, None),
                 use_scaled: bool | None = None):
        self.design_size = (int(logical_size[0]), int(logical_size[1]))
        self.android = is_android()
        self.smooth = bool(smooth)
        self.band_colors = band_colors

        if caption:
            pygame.display.set_caption(caption)

        if fullscreen is None:
            fullscreen = self.android
        self.fullscreen = bool(fullscreen)

        if use_scaled is None:
            # 本模块刻意不 import config（保持"纯适配层"），
            # 所以默认值用延迟导入取；取不到就按 True 试一次。
            try:
                from config import MOBILE_USE_SCALED as use_scaled
            except Exception:
                use_scaled = True
        self.use_scaled = bool(use_scaled)

        # 先试 GPU 缩放路径；失败就安静地退回 CPU 缩放
        self.mode = "manual"
        self.win_size = self.design_size
        if self.android and self.use_scaled and self._setup_scaled():
            return
        self._setup_manual()

    # ---------------- 模式一：GPU 缩放（pygame.SCALED） ----------------
    def _setup_scaled(self) -> bool:
        real = android_screen_size()
        if not real:
            return False
        sw, sh = real
        lw, lh = self.design_size
        if sw <= 0 or sh <= 0:
            return False

        # 逻辑画布做成和屏幕同比例，这样 SDL 不需要额外加黑边
        aspect = sw / float(sh)
        if aspect < lw / float(lh):          # 屏幕比游戏更瘦长 → 画布加高
            kw, kh = lw, int(round(lw / aspect))
        else:                                # 屏幕更宽 → 画布加宽
            kw, kh = int(round(lh * aspect)), lh
        kh = max(kh, lh)
        kw = max(kw, lw)

        try:
            surf = pygame.display.set_mode((kw, kh),
                                           pygame.FULLSCREEN | pygame.SCALED)
            win = tuple(pygame.display.get_window_size())
        except Exception:
            return False

        if win == (kw, kh):
            # SCALED 没被采纳（窗口就是逻辑尺寸）→ 说明没有可用的渲染器，回退
            return False

        self.mode = "scaled"
        self.window = surf
        self.canvas = surf
        self.win_size = win
        self.scale = 1.0
        self.dest = pygame.Rect((kw - lw) // 2, (kh - lh) // 2, lw, lh)
        self.logical = surf.subsurface(self.dest)
        self._dest_surf = None
        self._bars = []
        sky, ground = self.band_colors
        if self.dest.top > 0:
            self._bars.append((pygame.Rect(0, 0, kw, self.dest.top), sky))
        if self.dest.bottom < kh:
            self._bars.append((pygame.Rect(0, self.dest.bottom, kw,
                                           kh - self.dest.bottom), ground))
        if self.dest.left > 0:
            self._bars.append((pygame.Rect(0, 0, self.dest.left, kh), sky))
        if self.dest.right < kw:
            self._bars.append((pygame.Rect(self.dest.right, 0,
                                           kw - self.dest.right, kh), sky))
        return True

    # ---------------- 模式二：CPU 缩放（兜底） ----------------
    def _setup_manual(self):
        self.mode = "manual"
        flags = pygame.FULLSCREEN if self.fullscreen else 0

        # 安卓：直接按真实屏幕分辨率开全屏窗口，最稳
        want = self.design_size
        if self.android:
            real = android_screen_size()
            if real:
                want = real

        try:
            self.window = pygame.display.set_mode(want, flags)
        except Exception:
            self.window = pygame.display.set_mode(self.design_size)

        self._relayout()

    # ---------------- 布局（manual 模式） ----------------
    def _relayout(self):
        lw, lh = self.design_size
        ww, wh = self.window.get_size()
        self.win_size = (ww, wh)

        if (ww, wh) == (lw, lh):
            # 尺寸刚好吻合 → 不需要缩放：逻辑画布 == 窗口，零开销
            self.mode = "direct"
            self.logical = self.window
            self.canvas = self.window
            self.scale = 1.0
            self.dest = pygame.Rect(0, 0, lw, lh)
            self._bars = []
            self._dest_surf = None
            return

        self.mode = "manual"
        self.scale = min(ww / lw, wh / lh)
        dw = max(1, int(round(lw * self.scale)))
        dh = max(1, int(round(lh * self.scale)))
        self.dest = pygame.Rect((ww - dw) // 2, (wh - dh) // 2, dw, dh)
        self.logical = pygame.Surface((lw, lh)).convert()
        self.canvas = self.logical
        # 缩放的目标区域：缓存成 subsurface，省掉每帧一次对象分配
        self._dest_surf = self.window.subsurface(self.dest)

        # 信箱区域（游戏画面之外的边）★ 性能点 ★
        # 早先是每帧把整块 1080x2400 的背景 blit 一遍（2.6 M 像素）。
        # 只填游戏画面**四周的边条**，而且用纯色 fill（内存 memset，
        # 比贴图快好几倍）。竖屏手机上就是上下两条，正好接着天空和草地。
        sky, ground = self.band_colors
        self._bars = []
        d = self.dest
        if d.top > 0:
            self._bars.append((pygame.Rect(0, 0, ww, d.top), sky))
        if d.bottom < wh:
            self._bars.append((pygame.Rect(0, d.bottom, ww, wh - d.bottom), ground))
        if d.left > 0:
            self._bars.append((pygame.Rect(0, 0, d.left, wh), sky))
        if d.right < ww:
            self._bars.append((pygame.Rect(d.right, 0, ww - d.right, wh), sky))

    # ---------------- 坐标 ----------------
    @property
    def needs_transform(self) -> bool:
        return self.mode == "scaled" or self.scale != 1.0

    def to_logical(self, pos):
        """（窗口/画布）像素坐标 → 640x800 游戏逻辑坐标。"""
        if self.mode == "scaled":
            # SCALED 模式下 SDL/pygame 已经把坐标换到逻辑画布空间了，
            # 只要再减掉游戏画面在画布里的偏移
            return (pos[0] - self.dest.x, pos[1] - self.dest.y)
        if self.scale == 1.0:
            return pos
        return ((pos[0] - self.dest.x) / self.scale,
                (pos[1] - self.dest.y) / self.scale)

    def translate_event(self, event):
        """把带 pos 的事件（鼠标/触摸）就地换算成逻辑坐标。"""
        if self.needs_transform and hasattr(event, "pos"):
            try:
                event.pos = self.to_logical(event.pos)
            except Exception:
                pass
        return event

    # ---------------- 触摸兜底 ----------------
    def _finger_pos(self, e):
        """归一化手指坐标 (0~1) → 当前模式的像素坐标。"""
        if self.mode == "scaled":
            return (e.x * self.canvas.get_width(),
                    e.y * self.canvas.get_height())
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
        """把逻辑画布送到屏幕上。"""
        if self.mode == "scaled":
            # 逻辑画布（含天空/草地边条）直接交给 GPU 缩放整屏 ——
            # 这里只填边条，缩放和上屏全由 SDL 的渲染器做。
            for r, col in self._bars:
                self.canvas.fill(col, r)
        elif self.mode == "manual":
            # 1) 只填游戏画面四周的边条（纯色 fill，不是贴图）
            for r, col in self._bars:
                self.window.fill(col, r)
            # 2) 逻辑画布 → 目标区域（CPU 缩放）
            #    smooth=True 更细腻，但 640x800 → 1080x1350 在手机 CPU 上
            #    要 20~40 ms；False（最近邻）快 3~6 倍，粉彩画面几乎看不出差别。
            #    开关在 config.MOBILE_SMOOTH_SCALE。
            if self.smooth:
                pygame.transform.smoothscale(self.logical, self.dest.size,
                                             self._dest_surf)
            else:
                pygame.transform.scale(self.logical, self.dest.size,
                                       self._dest_surf)
        pygame.display.flip()

    # ---------------- 调试 ----------------
    def describe(self) -> str:
        return (f"display: {'android' if self.android else sys.platform} "
                f"mode={self.mode} window={self.win_size} "
                f"canvas={self.canvas.get_size()} design={self.design_size} "
                f"scale={self.scale:.4f} dest={tuple(self.dest)} "
                f"smooth={self.smooth}")
