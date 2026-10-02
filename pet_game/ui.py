# -*- coding: utf-8 -*-
"""
ui.py —— 界面组件
=========================================================
- Button   : 圆角按钮，带悬停 / 按下动画与手绘小图标
- StatBar  : 平滑滚动的数值条，低值时自动变红并呼吸闪烁
- make_icon: 超采样绘制的小图标工厂（结果做了缓存）
"""
from __future__ import annotations

import math

import pygame

from config import *
from utils import Pen, get_font, text_at, clamp, approach, mix

# ---------------------------------------------------------
#  图标工厂
# ---------------------------------------------------------
_icon_cache: dict = {}


def _heart_pts(cx, cy, scale, n=28):
    """参数方程心形（供 heart / hug 图标复用）。"""
    pts = []
    for i in range(n):
        a = math.tau * i / n
        x = 16 * math.sin(a) ** 3
        y = 13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a)
        pts.append((cx + x * scale, cy - y * scale))
    return pts


def make_icon(kind: str, size: int = 30, color=(120, 102, 118), accent=None) -> pygame.Surface:
    """
    生成小图标。内部用 4 倍超采样绘制再缩小，得到平滑边缘。

    已有种类：
      bowl(饭碗) heart(爱心) hand(手) star(星)
      drop(水滴) hug(拥抱) ball(小球) note(音符)
      bubble(泡泡) moon(月亮·睡觉) sun(太阳·叫醒)
      hanger(衣架·衣橱) lock(小锁·未解锁)
      paw(爪印·宠物) cookie(小饼干) yarn(毛线球)
    """
    key = (kind, size, color, accent)
    if key in _icon_cache:
        return _icon_cache[key]

    k = 4
    S = size
    surf = pygame.Surface((S * k, S * k), pygame.SRCALPHA)
    p = Pen(surf, k)
    c = (S / 2, S / 2)
    accent = accent or color

    if kind == "bowl":
        # 碗身
        p.arc(color, (c[0], c[1] - S * 0.10), S * 0.36, S * 0.30, 0, 180, S * 0.11)
        # 碗口
        p.ellipse(color, (c[0] - S * 0.38, c[1] - S * 0.19, S * 0.76, S * 0.14))
        # 冒出来的饭粒
        for dx, dy in ((-0.16, -0.34), (0.02, -0.40), (0.19, -0.32)):
            p.circle(accent, (c[0] + S * dx, c[1] + S * dy), S * 0.075)

    elif kind == "heart":
        p.polygon(color, _heart_pts(c[0], c[1], S * 0.030))

    elif kind == "hand":
        # 手掌
        p.ellipse(color, (c[0] - S * 0.30, c[1] - S * 0.10, S * 0.60, S * 0.58))
        # 四根手指
        for i, dx in enumerate((-0.20, -0.06, 0.08, 0.21)):
            h = S * (0.34 if i in (1, 2) else 0.26)
            p.rect(color, (c[0] + S * dx - S * 0.055, c[1] - S * 0.10 - h,
                           S * 0.11, h + S * 0.12), radius=S * 0.055)
        # 拇指
        p.ellipse(color, (c[0] - S * 0.42, c[1] + S * 0.02, S * 0.22, S * 0.30))

    elif kind == "star":
        pts = []
        for i in range(10):
            a = -math.pi / 2 + i * math.pi / 5
            r = S * (0.44 if i % 2 == 0 else 0.19)
            pts.append((c[0] + math.cos(a) * r, c[1] + math.sin(a) * r))
        p.polygon(color, pts)

    # ---------- 以下为新增互动的图标 ----------
    elif kind == "drop":
        # 水滴：圆底 + 上方尖角
        cy0 = c[1] + S * 0.14
        r = S * 0.26
        p.circle(color, (c[0], cy0), r)
        p.polygon(color, [
            (c[0], c[1] - S * 0.42),
            (c[0] - r * 0.92, cy0 - r * 0.34),
            (c[0] + r * 0.92, cy0 - r * 0.34),
        ])
        p.circle((255, 255, 255), (c[0] - r * 0.34, cy0 + r * 0.06), r * 0.26)

    elif kind == "hug":
        # 拥抱：一颗心 + 下方环抱的双臂
        p.polygon(color, _heart_pts(c[0], c[1] - S * 0.07, S * 0.023))
        p.arc(color, (c[0], c[1] + S * 0.20), S * 0.40, S * 0.24, 205, 335, S * 0.10)
        p.circle(color, (c[0] - S * 0.39, c[1] + S * 0.06), S * 0.055)
        p.circle(color, (c[0] + S * 0.39, c[1] + S * 0.06), S * 0.055)

    elif kind == "ball":
        # 小球（玩耍）：球体 + 一条装饰弧
        p.circle(accent, c, S * 0.36)
        p.arc(color, (c[0] - S * 0.06, c[1]), S * 0.30, S * 0.36, 40, 150, S * 0.085)
        p.circle((255, 255, 255), (c[0] - S * 0.14, c[1] - S * 0.15), S * 0.075)

    elif kind == "note":
        # 音符 ♪
        hx, hy = c[0] - S * 0.10, c[1] + S * 0.25
        hr = S * 0.16
        top_y = c[1] - S * 0.32
        stem_x = hx + hr * 0.62
        p.rect(color, (stem_x, top_y, S * 0.075, hy - top_y), radius=S * 0.038)
        p.polygon(color, [
            (stem_x + S * 0.05, top_y),
            (stem_x + S * 0.32, top_y + S * 0.11),
            (stem_x + S * 0.24, top_y + S * 0.26),
            (stem_x + S * 0.05, top_y + S * 0.17),
        ])
        p.circle(color, (hx, hy), hr)

    elif kind == "bubble":
        # 泡泡：空心圆 + 两处高光
        p.circle(color, (c[0], c[1] + S * 0.02), S * 0.30, S * 0.10)
        p.circle(color, (c[0] - S * 0.11, c[1] - S * 0.11), S * 0.075)
        p.circle(color, (c[0] + S * 0.13, c[1] + S * 0.13), S * 0.05)

    elif kind == "moon":
        # 月亮：先画满月，再用 BLEND_RGBA_SUB 挖出弯月
        R = S * 0.38
        p.circle(color, c, R)
        hole = pygame.Surface(p.surf.get_size(), pygame.SRCALPHA)
        pygame.draw.circle(hole, (255, 255, 255, 255),
                           (int((c[0] + R * 0.44) * k), int((c[1] - R * 0.10) * k)),
                           int(R * 0.94 * k))
        p.surf.blit(hole, (0, 0), special_flags=pygame.BLEND_RGBA_SUB)

    elif kind == "sun":
        # 太阳（睡觉按钮变成"叫醒"时使用）
        p.circle(color, c, S * 0.21)
        for i in range(12):
            a = math.tau * i / 12
            p.line(color,
                   (c[0] + math.cos(a) * S * 0.30, c[1] + math.sin(a) * S * 0.30),
                   (c[0] + math.cos(a) * S * 0.43, c[1] + math.sin(a) * S * 0.43),
                   S * 0.075)

    # ---------- 衣装系统相关 ----------
    elif kind == "hanger":
        # 衣架：顶部挂钩 + 三角形架身 + 底横杆
        w = S * 0.085
        p.arc(color, (c[0], c[1] - S * 0.27), S * 0.095, S * 0.105, 170, 360, w)
        p.line(color, (c[0] - S * 0.09, c[1] - S * 0.22), (c[0], c[1] - S * 0.11), w)
        p.line(color, (c[0], c[1] - S * 0.11), (c[0] - S * 0.40, c[1] + S * 0.22), w)
        p.line(color, (c[0], c[1] - S * 0.11), (c[0] + S * 0.40, c[1] + S * 0.22), w)
        p.line(color, (c[0] - S * 0.40, c[1] + S * 0.22),
               (c[0] + S * 0.40, c[1] + S * 0.22), w)

    elif kind == "lock":
        # 小锁：上方锁梁 + 下方锁体
        p.arc(color, (c[0], c[1] - S * 0.06), S * 0.19, S * 0.21, 180, 360, S * 0.10)
        p.rect(color, (c[0] - S * 0.29, c[1] - S * 0.04, S * 0.58, S * 0.42),
               radius=S * 0.11)
        p.circle(mix(color, (255, 255, 255), 0.55), (c[0], c[1] + S * 0.14), S * 0.055)

    # ---------- 宠物系统相关 ----------
    elif kind == "paw":
        # 爪印：一个掌心 + 四个脚趾
        p.ellipse(color, (c[0] - S * 0.24, c[1] - S * 0.02, S * 0.48, S * 0.42))
        for dx, dy, r in ((-0.26, -0.22, 0.105), (-0.08, -0.32, 0.112),
                          (0.10, -0.31, 0.110), (0.27, -0.18, 0.098)):
            p.circle(color, (c[0] + S * dx, c[1] + S * dy), S * r)

    elif kind == "cookie":
        # 小饼干：圆饼 + 几粒巧克力豆
        p.circle(color, c, S * 0.38)
        for dx, dy in ((-0.14, -0.10), (0.13, -0.06), (-0.02, 0.14), (0.17, 0.16)):
            p.circle(mix(color, (120, 84, 56), 0.55),
                     (c[0] + S * dx, c[1] + S * dy), S * 0.062)

    elif kind == "yarn":
        # 毛线球：球体 + 几道缠绕的弧线 + 线头
        p.circle(color, c, S * 0.36)
        for i, (rx, ry, a0, a1) in enumerate((
                (S * 0.34, S * 0.16, 200, 340),
                (S * 0.16, S * 0.34, 110, 250),
                (S * 0.30, S * 0.30, 20, 160))):
            p.arc(mix(color, (255, 255, 255), 0.45), c, rx, ry, a0, a1, S * 0.045)
        p.line(color, (c[0] + S * 0.30, c[1] + S * 0.26),
               (c[0] + S * 0.44, c[1] + S * 0.42), S * 0.05)

    icon = pygame.transform.smoothscale(surf, (S, S))
    _icon_cache[key] = icon
    return icon


# ---------------------------------------------------------
#  按钮
# ---------------------------------------------------------
class Button:
    """圆角按钮：支持悬停放大、按下回弹、快捷键提示、禁用态。"""

    def __init__(self, rect, label, base, hover, edge, text_color=TEXT,
                 icon=None, icon_color=None, hotkey="", radius=18):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.base = base
        self.hover_color = hover
        self.edge = edge
        self.text_color = text_color
        self.icon_kind = icon
        self.icon_color = icon_color or text_color
        self.hotkey = hotkey
        self.radius = radius

        self.hover = False
        self.pressed = False
        self.anim = 0.0          # 0 → 1 的按下进度
        self.enabled = True
        self.flash = 0.0         # 点击后的高光反馈

    # 按钮尺寸自适应：矮按钮用小图标 / 小字号
    @property
    def _compact(self) -> bool:
        return self.rect.h < 72

    # ---------- 交互 ----------
    def handle_event(self, event) -> bool:
        """返回 True 表示本次事件构成了一次"点击"。"""
        if not self.enabled:
            return False
        if event.type == pygame.MOUSEMOTION:
            self.hover = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.pressed = True
                self.hover = True
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            was = self.pressed
            self.pressed = False
            if was and self.rect.collidepoint(event.pos):
                self.flash = 1.0
                return True
        return False

    def set_hover(self, pos):
        self.hover = self.rect.collidepoint(pos) and self.enabled

    def update(self, dt):
        target = 1.0 if self.pressed else 0.0
        self.anim = approach(self.anim, target, dt * 7.0)
        self.flash = max(0.0, self.flash - dt * 3.2)

    # ---------- 绘制 ----------
    def draw(self, surface):
        compact = self._compact
        radius = self.radius if compact else 26
        off = 3 if compact else 6

        r = self.rect.copy()
        # 悬停时轻微放大（向外扩几像素）
        if self.hover and self.enabled:
            grow = 4 if compact else 6
            r.inflate_ip(grow, grow)

        body = mix(self.base, self.hover_color, 0.55 if (self.hover and self.enabled) else 0.0)
        if not self.enabled:
            body = mix(body, (240, 234, 240), 0.55)

        # 投影：只在按钮大小的小图层上作画（避免每帧分配整屏 surface）
        sh = pygame.Surface((r.w + 4, r.h + off + 4), pygame.SRCALPHA)
        pygame.draw.rect(sh, (206, 184, 198, 80), pygame.Rect(0, 0, r.w, r.h),
                         border_radius=radius)
        surface.blit(sh, (r.x - 2, r.y + off - 2))

        # 按下时向下压
        r.y += int(self.anim * off)

        # 主体
        pygame.draw.rect(surface, body, r, border_radius=radius)

        # 顶部高光
        hl = pygame.Rect(r.x + 5, r.y + 4, r.w - 10, int(r.h * 0.36))
        hi = pygame.Surface(hl.size, pygame.SRCALPHA)
        pygame.draw.rect(hi, (255, 255, 255, 92), pygame.Rect(0, 0, hl.w, hl.h),
                         border_radius=radius // 2)
        surface.blit(hi, hl.topleft)

        # 描边
        pygame.draw.rect(surface, self.edge, r, 2 if compact else 3, border_radius=radius)

        # 内容：图标 + 文字
        icon_size = 24 if compact else 34
        font_size = 17 if compact else 28
        gap = 7 if compact else 12

        font = get_font(font_size, True)
        label_w = font.size(self.label)[0]
        total_w = label_w + (icon_size + gap if self.icon_kind else 0)
        cx = r.centerx - total_w // 2
        cy = r.centery

        if self.icon_kind:
            icon = make_icon(self.icon_kind, icon_size, self.icon_color)
            surface.blit(icon, icon.get_rect(midleft=(cx, cy)))
            cx += icon_size + gap

        text_at(surface, self.label, (cx + label_w // 2, cy), size=font_size,
                color=self.text_color, bold=True, center=True)

        # 快捷键角标
        if self.hotkey:
            bw, bh = (18, 16) if compact else (20, 18)
            inset = 6 if compact else 10
            badge_font = get_font(11 if compact else 13, True)
            bx = r.right - bw - inset
            by = r.top + inset
            pygame.draw.rect(surface, self.edge, pygame.Rect(bx, by, bw, bh),
                             border_radius=5)
            img = badge_font.render(self.hotkey, True, (255, 255, 255))
            surface.blit(img, img.get_rect(center=(bx + bw // 2, by + bh // 2)))

        # 点击闪光
        if self.flash > 0.01:
            fr = r.inflate(6, 6)
            fl = pygame.Surface(fr.size, pygame.SRCALPHA)
            pygame.draw.rect(fl, (255, 255, 255, int(120 * self.flash)),
                             pygame.Rect(0, 0, fr.w, fr.h), border_radius=radius, width=5)
            surface.blit(fl, fr.topleft)


# ---------------------------------------------------------
#  数值条
# ---------------------------------------------------------
class StatBar:
    """
    带平滑滚动的数值条。
    display 会缓慢追上真实值，产生"掉血/回血"的过渡观感。
    """

    def __init__(self, y, label, icon_kind, fg, bg, icon_color):
        self.y = y
        self.label = label
        self.icon_kind = icon_kind
        self.fg = fg
        self.bg = bg
        self.icon_color = icon_color
        self.display = 0.0
        self.pulse = 0.0
        self.warn = False

    def update(self, dt, value, max_value):
        target = clamp(value / max_value, 0.0, 1.0)
        # 下降稍快、上升更柔和
        speed = dt * (1.5 if target > self.display else 0.9)
        self.display = approach(self.display, target, speed)
        self.warn = target < (LOW_THRESHOLD / STAT_MAX)
        self.pulse = (self.pulse + dt * 3.6) % (math.tau) if self.warn else 0.0

    def draw(self, surface, value):
        bar = pygame.Rect(STAT_BAR_X, self.y, STAT_BAR_W, STAT_BAR_H)

        # 图标 + 名称
        icon = make_icon(self.icon_kind, 26, self.icon_color)
        surface.blit(icon, icon.get_rect(center=(STAT_ICON_X, bar.centery)))
        text_at(surface, self.label, (STAT_LABEL_X, bar.centery - 1), size=19,
                color=TEXT, bold=True, center=False)

        # 轨道
        pygame.draw.rect(surface, self.bg, bar, border_radius=bar.h // 2)
        pygame.draw.rect(surface, (255, 255, 255), bar, 2, border_radius=bar.h // 2)

        # 填充
        fill_w = int((bar.w - 6) * clamp(self.display, 0, 1))
        if fill_w > 2:
            fg = self.fg
            if self.warn:
                k = 0.5 + 0.5 * math.sin(self.pulse)
                fg = mix(self.fg, BAR_LOW_FG, 0.45 + 0.45 * k)
            fr = pygame.Rect(bar.x + 3, bar.y + 3, fill_w, bar.h - 6)
            pygame.draw.rect(surface, fg, fr, border_radius=(bar.h - 6) // 2)
            # 顶部高光条（小图层，避免整屏分配）
            hw, hh = max(1, fr.w - 10), max(1, (bar.h - 6) // 3)
            hi = pygame.Surface((hw, hh), pygame.SRCALPHA)
            pygame.draw.rect(hi, (255, 255, 255, 110),
                             pygame.Rect(0, 0, hw, hh), border_radius=hh // 2)
            surface.blit(hi, (fr.x + 4, fr.y + 2))

        # 数值
        vx = bar.right + 14
        text_at(surface, f"{int(round(value))}", (vx, bar.centery - 1), size=20,
                color=BAR_LOW_FG if self.warn else TEXT_LIGHT, bold=True, center=False)
