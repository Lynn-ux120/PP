# -*- coding: utf-8 -*-
"""
effects.py —— 粒子特效系统
=========================================================
爱心 / 小饼干 / 水滴 / 泡泡 / 音符 / Zzz / 星光 / 飘字，
全部继承自 Particle 基类。

扩展方式：写一个新的粒子类，实现 update() 和 draw()，
然后在 ParticleSystem 里加一个 spawn_xxx() 方法即可。
"""
from __future__ import annotations

import math
import random

import pygame

from config import *
from utils import get_font, clamp


# ---------------------------------------------------------
#  基类
# ---------------------------------------------------------
class Particle:
    """粒子基类：世界坐标 + 生命期。update() 返回 False 表示该销毁。"""

    def __init__(self, x: float, y: float, life: float = 1.2):
        self.x = float(x)
        self.y = float(y)
        self.vx = 0.0
        self.vy = 0.0
        self.age = 0.0
        self.life = life

    # 归一化年龄 0→1
    @property
    def t(self) -> float:
        return clamp(self.age / self.life, 0.0, 1.0)

    def update(self, dt: float) -> bool:
        self.age += dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        return self.age < self.life

    def draw(self, surface):
        pass

    # ---------- 小图层工具 ----------
    # 半透明图形必须先在独立图层上作画再整体叠加，否则会破坏底图 alpha。
    # 但每次都分配整屏图层太贵，所以这里按图形的包围盒分配"刚好够用"的小图层。
    @staticmethod
    def _make_layer(points, extra=4):
        """按点集算出包围盒，返回 (layer, ox, oy)。"""
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        ox = int(min(xs)) - extra
        oy = int(min(ys)) - extra
        w = int(max(xs)) - ox + extra + 2
        h = int(max(ys)) - oy + extra + 2
        return pygame.Surface((max(1, w), max(1, h)), pygame.SRCALPHA), ox, oy

    @staticmethod
    def _shift(points, ox, oy):
        return [(p[0] - ox, p[1] - oy) for p in points]


# ---------------------------------------------------------
#  爱心
# ---------------------------------------------------------
class Heart(Particle):
    """飘起来的爱心 —— 抚摸宠物时出现。"""

    def __init__(self, x, y, scale=1.0, color=None):
        super().__init__(x, y, life=random.uniform(1.05, 1.75))
        self.vx = random.uniform(-30, 30)
        self.vy = random.uniform(-95, -58)
        self.size = random.uniform(9, 15) * scale
        self.color = color or random.choice([PINK, PINK_DEEP, (255, 198, 216), LILAC])
        self.wobble = random.uniform(0, math.tau)
        self.sway = random.uniform(14, 30)
        self.spin = random.uniform(-0.6, 0.6)

    def update(self, dt):
        self.wobble += dt * 4.5
        self.vx *= 0.985
        self.vy += 26 * dt          # 轻微减速上浮
        self.x += math.sin(self.wobble) * self.sway * dt
        return super().update(dt)

    def draw(self, surface):
        t = self.t
        fade_in = clamp(t / 0.15, 0.0, 1.0)
        fade_out = clamp((1 - t) / 0.35, 0.0, 1.0)
        alpha = int(255 * fade_in * fade_out)
        if alpha <= 2:
            return
        s = self.size * (0.55 + 0.65 * clamp(t / 0.25, 0, 1))
        # 参数方程心形
        pts = []
        n = 26
        for i in range(n):
            a = math.tau * i / n
            px = 16 * math.sin(a) ** 3
            py = (13 * math.cos(a) - 5 * math.cos(2 * a)
                  - 2 * math.cos(3 * a) - math.cos(4 * a))
            ang = math.atan2(py, px) + self.spin * self.age
            r = math.hypot(px, py) * s / 16.0
            pts.append((self.x + math.cos(ang) * r, self.y - math.sin(ang) * r))

        layer, ox, oy = self._make_layer(pts, extra=int(s * 0.5) + 6)
        pygame.draw.polygon(layer, (*self.color, alpha), self._shift(pts, ox, oy))
        # 高光
        hl = (int(self.x - s * 0.22) - ox, int(self.y - s * 0.42) - oy)
        pygame.draw.circle(layer, (255, 255, 255, int(alpha * 0.75)), hl,
                           max(1, int(s * 0.16)))
        surface.blit(layer, (ox, oy))


# ---------------------------------------------------------
#  小饼干 / 食物碎屑
# ---------------------------------------------------------
class Crumb(Particle):
    """喂食时飞向嘴边的小饼干。"""

    def __init__(self, x, y, target):
        super().__init__(x, y, life=random.uniform(0.65, 0.95))
        self.target = target
        self.size = random.uniform(5, 9)
        self.color = random.choice([BUTTER, BUTTER_DEEP, (255, 236, 196)])
        self.arc = random.uniform(-70, -30)

    def update(self, dt):
        self.age += dt
        t = self.t
        e = t * t * (3 - 2 * t)                       # smoothstep 插值
        self.x = lerp_simple(self.x, self.target[0], 0.22)
        self.y = lerp_simple(self.y, self.target[1], 0.22)
        self.y += self.arc * dt * (1 - t) * 0.5
        return self.age < self.life

    def draw(self, surface):
        alpha = int(255 * clamp((1 - self.t) / 0.3, 0, 1))
        if alpha <= 2:
            return
        r = self.size
        pad = int(r) + 4
        layer = pygame.Surface((pad * 2, pad * 2), pygame.SRCALPHA)
        cx = cy = pad
        pygame.draw.circle(layer, (*self.color, alpha), (cx, cy), int(r))
        pygame.draw.circle(layer, (150, 110, 70, int(alpha * 0.55)),
                           (int(cx - r * 0.3), int(cy - r * 0.2)), max(1, int(r * 0.22)))
        pygame.draw.circle(layer, (150, 110, 70, int(alpha * 0.55)),
                           (int(cx + r * 0.35), int(cy + r * 0.3)), max(1, int(r * 0.18)))
        surface.blit(layer, (int(self.x) - pad, int(self.y) - pad))


def lerp_simple(a, b, t):
    return a + (b - a) * t


# ---------------------------------------------------------
#  水滴（喝水）
# ---------------------------------------------------------
class Drop(Particle):
    """飞向嘴边的小水滴。"""

    def __init__(self, x, y, target):
        super().__init__(x, y, life=random.uniform(0.60, 0.90))
        self.target = target
        self.size = random.uniform(5.0, 8.0)
        self.color = random.choice([SKY, (176, 220, 246), (150, 205, 244)])

    def update(self, dt):
        self.age += dt
        self.x += (self.target[0] - self.x) * 0.21
        self.y += (self.target[1] - self.y) * 0.21
        self.y -= 16 * dt
        return self.age < self.life

    def draw(self, surface):
        alpha = int(255 * clamp((1 - self.t) / 0.30, 0, 1))
        if alpha <= 3:
            return
        s = self.size
        layer, ox, oy = self._make_layer(
            [(self.x - s, self.y - s * 2), (self.x + s, self.y + s * 1.4)], extra=3)
        cx, cy = int(self.x) - ox, int(self.y) - oy
        # 圆底 + 上方尖角 = 水滴
        pygame.draw.circle(layer, (*self.color, alpha), (cx, cy), int(s))
        pygame.draw.polygon(layer, (*self.color, alpha), [
            (cx, cy - int(s * 1.7)),
            (cx - int(s * 0.76), cy - int(s * 0.40)),
            (cx + int(s * 0.76), cy - int(s * 0.40)),
        ])
        pygame.draw.circle(layer, (255, 255, 255, alpha),
                           (cx - int(s * 0.30), cy + int(s * 0.10)),
                           max(1, int(s * 0.26)))
        surface.blit(layer, (ox, oy))


# ---------------------------------------------------------
#  泡泡（洗澡）
# ---------------------------------------------------------
class Bubble(Particle):
    """向上飘的肥皂泡。"""

    def __init__(self, x, y):
        super().__init__(x, y, life=random.uniform(1.30, 2.10))
        self.r = random.uniform(5.0, 12.0)
        self.vx = random.uniform(-16, 16)
        self.vy = random.uniform(-74, -38)
        self.wob = random.uniform(0, math.tau)
        self.color = random.choice([(196, 232, 250), (214, 240, 252),
                                    (206, 226, 250), (255, 255, 255)])

    def update(self, dt):
        self.wob += dt * 3.0
        self.x += math.sin(self.wob) * 18 * dt
        self.vy *= 0.995
        return super().update(dt)

    def draw(self, surface):
        t = self.t
        alpha = int(195 * clamp(t / 0.12, 0, 1) * clamp((1 - t) / 0.30, 0, 1))
        if alpha <= 3:
            return
        r = max(2, int(self.r))
        pad = r + 4
        layer = pygame.Surface((pad * 2, pad * 2), pygame.SRCALPHA)
        pygame.draw.circle(layer, (*self.color, alpha // 3), (pad, pad), r)
        pygame.draw.circle(layer, (*self.color, alpha), (pad, pad), r, max(1, r // 5))
        pygame.draw.circle(layer, (255, 255, 255, min(255, alpha)),
                           (int(pad - r * 0.35), int(pad - r * 0.38)),
                           max(1, int(r * 0.22)))
        surface.blit(layer, (int(self.x) - pad, int(self.y) - pad))


# ---------------------------------------------------------
#  音符（唱歌）
# ---------------------------------------------------------
class Note(Particle):
    """飘起来的音符 ♪。"""

    def __init__(self, x, y):
        super().__init__(x, y, life=random.uniform(1.10, 1.70))
        self.vx = random.uniform(-26, 26)
        self.vy = random.uniform(-80, -46)
        self.size = random.uniform(9.0, 15.0)
        self.color = random.choice([LILAC, LILAC_DEEP, PINK, (255, 255, 255), SKY])
        self.wob = random.uniform(0, math.tau)
        self.spin = random.uniform(-0.9, 0.9)

    def update(self, dt):
        self.wob += dt * 3.4
        self.vx *= 0.98
        self.vy += 18 * dt
        self.x += math.sin(self.wob) * 22 * dt
        return super().update(dt)

    def draw(self, surface):
        alpha = int(255 * clamp((1 - self.t) / 0.40, 0, 1) * clamp(self.t / 0.10, 0, 1))
        if alpha <= 3:
            return
        s = self.size * (1.0 - 0.20 * self.t)

        # 符头（椭圆）
        hx, hy = self.x - s * 0.40, self.y + s * 0.50
        # 符干 / 符尾的基准点
        sx = hx + s * 0.30
        sy1 = self.y - s * 0.72

        layer, ox, oy = self._make_layer(
            [(hx - s * 0.40, sy1 - s * 0.10), (sx + s * 0.62, hy + s * 0.32)], extra=3)

        head = [(hx + math.cos(i * math.tau / 16) * s * 0.36 - ox,
                 hy + math.sin(i * math.tau / 16) * s * 0.27 - oy) for i in range(16)]
        pygame.draw.polygon(layer, (*self.color, alpha), head)

        pygame.draw.line(layer, (*self.color, alpha),
                         (sx - ox, sy1 - oy), (sx - ox, hy - oy),
                         max(1, int(s * 0.16)))

        pygame.draw.polygon(layer, (*self.color, alpha), [
            (sx - ox, sy1 - oy),
            (sx + s * 0.58 - ox, sy1 + s * 0.20 - oy),
            (sx + s * 0.38 - ox, sy1 + s * 0.54 - oy),
            (sx - ox, sy1 + s * 0.42 - oy),
        ])
        surface.blit(layer, (ox, oy))


# ---------------------------------------------------------
#  Zzz（睡觉）
# ---------------------------------------------------------
class Zzz(Particle):
    """睡觉时头顶飘出的 Z。"""

    def __init__(self, x, y):
        super().__init__(x, y, life=random.uniform(1.40, 1.95))
        self.vx = random.uniform(14, 40)
        self.vy = random.uniform(-42, -22)
        self.size = random.uniform(15.0, 21.0)

    def update(self, dt):
        self.vy += 10 * dt
        return super().update(dt)

    def draw(self, surface):
        alpha = int(235 * clamp((1 - self.t) / 0.50, 0, 1) * clamp(self.t / 0.12, 0, 1))
        if alpha <= 4:
            return
        size = int(self.size * (0.70 + 0.60 * self.t))
        font = get_font(size, True)
        img = font.render("Z", True, (150, 148, 205))
        img.set_alpha(alpha)
        surface.blit(img, img.get_rect(center=(self.x, self.y)))


# ---------------------------------------------------------
#  星光
# ---------------------------------------------------------
class Sparkle(Particle):
    """四角星光 —— 数值恢复/互动成功时的小点缀。"""

    def __init__(self, x, y):
        super().__init__(x, y, life=random.uniform(0.5, 0.95))
        self.vx = random.uniform(-45, 45)
        self.vy = random.uniform(-70, -20)
        self.size = random.uniform(4, 9)
        self.color = random.choice([(255, 255, 255), PINK_SOFT, (255, 244, 214), (216, 236, 255)])
        self.rot = random.uniform(0, math.pi)

    def update(self, dt):
        self.vy += 55 * dt
        self.rot += dt * 2.2
        return super().update(dt)

    def draw(self, surface):
        alpha = int(255 * clamp((1 - self.t) / 0.5, 0, 1) * clamp(self.t / 0.12, 0, 1))
        if alpha <= 2:
            return
        s = self.size * (1.0 - 0.35 * self.t)
        quads = []
        for i in range(4):
            a = self.rot + i * math.pi / 2
            ex = self.x + math.cos(a) * s * 1.9
            ey = self.y + math.sin(a) * s * 1.9
            quads.append([
                (self.x, self.y),
                (self.x + math.cos(a + 0.45) * s * 0.42, self.y + math.sin(a + 0.45) * s * 0.42),
                (ex, ey),
                (self.x + math.cos(a - 0.45) * s * 0.42, self.y + math.sin(a - 0.45) * s * 0.42),
            ])
        all_pts = [p for q in quads for p in q]
        layer, ox, oy = self._make_layer(all_pts, extra=3)
        for q in quads:
            pygame.draw.polygon(layer, (*self.color, alpha), self._shift(q, ox, oy))
        surface.blit(layer, (ox, oy))


# ---------------------------------------------------------
#  飘字（+26 之类）
# ---------------------------------------------------------
class FloatingText(Particle):
    def __init__(self, x, y, text, color=TEXT, size=22):
        super().__init__(x, y, life=1.05)
        self.text = text
        self.color = color
        self.size = size
        self.vx = random.uniform(-10, 10)

    def update(self, dt):
        self.vy = -58 * (1 - self.t)
        return super().update(dt)

    def draw(self, surface):
        alpha = int(255 * clamp((1 - self.t) / 0.45, 0, 1))
        if alpha <= 3:
            return
        font = get_font(self.size, True)
        img = font.render(self.text, True, self.color)
        img.set_alpha(alpha)
        surface.blit(img, img.get_rect(center=(self.x, self.y)))


# ---------------------------------------------------------
#  粒子系统
# ---------------------------------------------------------
class ParticleSystem:
    def __init__(self):
        self.items: list[Particle] = []

    def add(self, p: Particle):
        self.items.append(p)
        return p

    # ---------- 便捷生成接口 ----------
    def spawn_hearts(self, pos, n=6, spread=46, scale=1.0):
        """宠物头顶冒爱心。"""
        for _ in range(n):
            self.add(Heart(
                pos[0] + random.uniform(-spread, spread),
                pos[1] + random.uniform(-12, 18),
                scale=scale,
            ))

    def spawn_food(self, pos, target, n=6):
        """小饼干飞向嘴边。"""
        for _ in range(n):
            self.add(Crumb(
                pos[0] + random.uniform(-70, 70),
                pos[1] + random.uniform(-40, 20),
                target,
            ))

    def spawn_drops(self, pos, target, n=6):
        """小水滴飞向嘴边。"""
        for _ in range(n):
            self.add(Drop(
                pos[0] + random.uniform(-70, 70),
                pos[1] + random.uniform(-40, 20),
                target,
            ))

    def spawn_bubbles(self, pos, n=12, spread=60):
        """洗澡时的泡泡。"""
        for _ in range(n):
            self.add(Bubble(
                pos[0] + random.uniform(-spread, spread),
                pos[1] + random.uniform(-10, 34),
            ))

    def spawn_notes(self, pos, n=6, spread=56):
        """唱歌时飘出的音符。"""
        for _ in range(n):
            self.add(Note(
                pos[0] + random.uniform(-spread, spread),
                pos[1] + random.uniform(-14, 24),
            ))

    def spawn_zzz(self, pos):
        """睡觉时头顶的 Z。"""
        self.add(Zzz(
            pos[0] + random.uniform(8, 28),
            pos[1] + random.uniform(-4, 12),
        ))

    def spawn_sparkles(self, pos, n=8, spread=60):
        for _ in range(n):
            self.add(Sparkle(
                pos[0] + random.uniform(-spread, spread),
                pos[1] + random.uniform(-30, 30),
            ))

    def spawn_text(self, pos, text, color=TEXT, size=22):
        self.add(FloatingText(pos[0], pos[1], text, color, size))

    def clear(self):
        self.items.clear()

    # ---------- 生命周期 ----------
    def update(self, dt):
        alive = []
        for p in self.items:
            if p.update(dt):
                alive.append(p)
        self.items = alive

    def draw(self, surface):
        for p in self.items:
            p.draw(surface)
