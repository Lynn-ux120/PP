# -*- coding: utf-8 -*-
"""
utils.py —— 通用小工具
=========================================================
1. 数学：clamp / lerp / mix
2. 字体：自动寻找系统中文字体，避免中文变成方块
3. Pen：超采样画笔，用"逻辑坐标"作画、放大 k 倍渲染再缩小，
   这样即便是 pygame 的原始图元也能得到柔和的手绘感边缘。
"""
from __future__ import annotations

import math
import os

import pygame

# ---------------------------------------------------------
#  数学
# ---------------------------------------------------------
def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def mix(c1, c2, t: float):
    """按比例混合两个 RGB 颜色，t=0 得到 c1，t=1 得到 c2。"""
    t = clamp(t, 0.0, 1.0)
    return tuple(int(round(lerp(c1[i], c2[i], t))) for i in range(3))


def approach(cur: float, target: float, speed: float) -> float:
    """让 cur 以 speed 的节奏平滑逼近 target（帧率无关）。"""
    if cur < target:
        return min(target, cur + speed)
    return max(target, cur - speed)


# ---------------------------------------------------------
#  中文字体
# ---------------------------------------------------------
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",          # 微软雅黑
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\Deng.ttf",          # 等线
    r"C:\Windows\Fonts\simhei.ttf",        # 黑体
    r"C:\Windows\Fonts\simsun.ttc",        # 宋体
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]
_SYS_FONT_NAMES = [
    "microsoftyahei", "msyh", "simhei", "dengxian",
    "pingfangsc", "notosanscjksc", "wenquanyimicrohei", "arialunicodems",
]

# ---------------------------------------------------------
#  安卓：系统里一定有中文字体，但机型命名千奇百怪，所以按目录扫
# ---------------------------------------------------------
_ANDROID_FONT_DIRS = ("/system/fonts", "/system/fonts/opentype",
                      "/system/font", "/vendor/fonts")
_ANDROID_FONT_FILES = (
    "NotoSansCJK-Regular.ttc", "NotoSansCJKsc-Regular.otf",
    "NotoSansSC-Regular.otf", "NotoSansHans-Regular.otf",
    "NotoSansCJK-VF.otf.ttc", "DroidSansFallbackFull.ttf",
    "DroidSansFallback.ttf", "SourceHanSansSC-Regular.otf",
)
_ANDROID_FONT_KEYS = ("cjk", "notosanssc", "notosanshans", "notosanssc",
                      "droidsansfallback", "sourcehansans", "harmonyos",
                      "misans", "oplusos", "coloros")


def _android_font_candidates() -> list:
    out = []
    for d in _ANDROID_FONT_DIRS:
        if not os.path.isdir(d):
            continue
        for name in _ANDROID_FONT_FILES:
            p = os.path.join(d, name)
            if os.path.exists(p):
                out.append(p)
        try:
            for fn in sorted(os.listdir(d)):
                low = fn.lower()
                if low.endswith((".ttf", ".ttc", ".otf")) and \
                        any(k in low for k in _ANDROID_FONT_KEYS):
                    p = os.path.join(d, fn)
                    if p not in out:
                        out.append(p)
        except OSError:
            pass
    return out


_font_path: str | None = None
_font_cache: dict = {}


def _resolve_font_path() -> str:
    global _font_path
    if _font_path is None:
        _font_path = ""
        for p in list(_FONT_CANDIDATES) + _android_font_candidates():
            if os.path.exists(p):
                _font_path = p
                break
    return _font_path


def get_font(size: int, bold: bool = False) -> pygame.font.Font:
    """获取（并缓存）一个支持中文的字体对象。"""
    key = (size, bold)
    if key in _font_cache:
        return _font_cache[key]

    font = None
    path = _resolve_font_path()
    if path:
        try:
            font = pygame.font.Font(path, size)
            font.set_bold(bold)
        except Exception:
            font = None

    if font is None:
        try:
            font = pygame.font.SysFont(_SYS_FONT_NAMES, size, bold=bold)
        except Exception:
            font = pygame.font.Font(None, size)

    _font_cache[key] = font
    return font


# ---------------------------------------------------------
#  超采样画笔
# ---------------------------------------------------------
class Pen:
    """
    用逻辑坐标作画的画笔。

        surf = pygame.Surface((W * k, H * k), pygame.SRCALPHA)
        pen  = Pen(surf, k)
        pen.circle((255, 0, 0), (50, 50), 20)     # 坐标/半径都按逻辑值给
        char = pygame.transform.smoothscale(surf, (W, H))   # 缩回 1x → 平滑

    所有 width 参数也是逻辑值。

    offset
        画笔的"图层原点"（**表面像素**）。soft() 会在一个只够装下图形的小
        图层上作画，然后整体贴回主画布 —— 这时就靠 offset 把逻辑坐标
        换算到那个小图层的局部坐标里。
    """

    __slots__ = ("surf", "k", "ox", "oy")

    def __init__(self, surface: pygame.Surface, k: int = 1, offset=(0, 0)):
        self.surf = surface
        self.k = k
        self.ox, self.oy = offset

    # ---------- 坐标换算 ----------
    def _pt(self, x, y):
        k = self.k
        return int(x * k - self.ox), int(y * k - self.oy)

    # ---------- 基础图元 ----------
    def _rect(self, rect):
        x, y, w, h = rect
        k = self.k
        return pygame.Rect(
            *self._pt(x, y),
            max(1, int(w * k)), max(1, int(h * k)),
        )

    def _w(self, width: float) -> int:
        return max(1, int(width * self.k)) if width else 0

    def line(self, color, p0, p1, width=2):
        """带圆头的粗线（比 pygame.draw.line 更柔和）。"""
        k = self.k
        brush = max(1, int(width * k / 2))
        dist = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) * k
        steps = max(2, int(dist / max(1.0, brush * 0.6)))
        for i in range(steps + 1):
            t = i / steps
            x = (p0[0] + (p1[0] - p0[0]) * t) * k
            y = (p0[1] + (p1[1] - p0[1]) * t) * k
            pygame.draw.circle(self.surf, color,
                               (int(x - self.ox), int(y - self.oy)), brush)

    def arc(self, color, center, rx, ry, a0, a1, width=3, steps=None):
        """
        角度制椭圆弧，0° = 正右，顺时针为正（屏幕坐标 y 轴向下）。
        - 上半弧 180°→360° 画出来是 "⌒"
        - 下半弧   0°→180° 画出来是 "⌣"
        """
        if steps is None:
            steps = max(10, int(abs(a1 - a0) / 180.0 * 26) + 8)
        k = self.k
        brush = max(1, int(width * k / 2))
        for i in range(steps + 1):
            a = math.radians(a0 + (a1 - a0) * i / steps)
            x = (center[0] + rx * math.cos(a)) * k
            y = (center[1] + ry * math.sin(a)) * k
            pygame.draw.circle(self.surf, color,
                               (int(x - self.ox), int(y - self.oy)), brush)

    def circle(self, color, center, r, width=0):
        k = self.k
        pygame.draw.circle(
            self.surf, color,
            self._pt(center[0], center[1]),
            max(1, int(r * k)), self._w(width),
        )

    def ellipse(self, color, rect, width=0):
        pygame.draw.ellipse(self.surf, color, self._rect(rect), self._w(width))

    def rect(self, color, rect, width=0, radius=0):
        pygame.draw.rect(
            self.surf, color, self._rect(rect), self._w(width),
            border_radius=int(radius * self.k),
        )

    def polygon(self, color, points, width=0):
        pts = [self._pt(p[0], p[1]) for p in points]
        pygame.draw.polygon(self.surf, color, pts, self._w(width))

    def rounded_polygon(self, color, points, radius):
        """多边形 + 每个顶点补一个圆 → 近似圆角多边形。"""
        self.polygon(color, points)
        for p in points:
            self.circle(color, p, radius)

    # ---------- 半透明图元 ----------
    def soft(self, rgba, shape: str, **kw):
        """
        绘制半透明图元。原理：先在独立透明图层上作画，再整体 blit 叠加，
        这样不会破坏底图已有像素的 alpha 通道。

        ⚠️ 性能：这里**只分配刚好裹住图形的小图层**。
        早期版本每次都分配一整张画布（780x900），角色一次重绘要调 16 次
        soft()，光分配+叠加就要 24 ms（桌面），手机上直接卡到动不了 ——
        换成包围盒之后同样一次重绘降到 3 ms 出头。
        """
        box = self._shape_box(shape, kw)
        if box is None:
            return
        bx, by, bw, bh = box

        # 裁到画布范围内（超出部分 pygame 本来也会裁掉，这里只是别白分配）
        sw, sh = self.surf.get_size()
        x0 = max(0, bx)
        y0 = max(0, by)
        w = min(bw - (x0 - bx), sw - x0)
        h = min(bh - (y0 - by), sh - y0)
        if w <= 0 or h <= 0:
            return

        layer = pygame.Surface((w, h), pygame.SRCALPHA)
        Pen(layer, self.k, offset=(x0, y0))._shape(rgba, shape, kw)
        self.surf.blit(layer, (x0, y0))

    def _shape_box(self, shape: str, kw):
        """图形的包围盒（表面像素）：(x, y, w, h)。"""
        k = self.k
        m = 3                                    # 抗锯齿余量
        if shape == "ellipse" or shape == "rect":
            x, y, w, h = kw["rect"]
        elif shape == "circle":
            cx, cy = kw["center"]
            r = max(0.5, float(kw["r"]))
            x, y, w, h = cx - r, cy - r, r * 2, r * 2
        elif shape == "polygon":
            pts = kw["points"]
            if not pts:
                return None
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            x, y = min(xs), min(ys)
            w, h = max(xs) - x, max(ys) - y
        else:
            return None
        return (int(x * k) - m, int(y * k) - m,
                int(w * k) + m * 2 + 2, int(h * k) + m * 2 + 2)

    def _shape(self, rgba, shape: str, kw):
        if shape == "ellipse":
            self.ellipse(rgba, kw["rect"])
        elif shape == "circle":
            self.circle(rgba, kw["center"], kw["r"])
        elif shape == "polygon":
            self.polygon(rgba, kw["points"])
        elif shape == "rect":
            self.rect(rgba, kw["rect"], radius=kw.get("radius", 0))


# ---------------------------------------------------------
#  贴纸描边
# ---------------------------------------------------------
_OUTLINE_SPOKES = 12          # 描边的"辐条"数量（越多越圆，也越慢）


def sticker_outline(canvas: pygame.Surface, width=3,
                    color=(255, 253, 255, 255)) -> pygame.Surface:
    """
    给任意带 alpha 的贴图加一圈柔和描边（贴纸效果），
    让主体从粉彩背景里"跳"出来。

    做法：提取 alpha 蒙版 → 沿一圈辐条平移叠加成粗轮廓 → 把原图盖回去。
    角色和角色养的小宠物共用这一个函数。

    ⚠️ 性能：平移次数 = 辐条数。早期版本遍历了整个 (2w+1)² 方形区域
    （width=3 时是 29 次全图 alpha 叠加），改成 12 根辐条后同样的观感、
    但快了 2.4 倍。贴图只在缓存未命中时才重画，所以这已经够用了。
    """
    mask = pygame.mask.from_surface(canvas, 120)
    silhouette = mask.to_surface(setcolor=color, unsetcolor=(0, 0, 0, 0))
    out = pygame.Surface(canvas.get_size(), pygame.SRCALPHA)
    for i in range(_OUTLINE_SPOKES):
        a = math.tau * i / _OUTLINE_SPOKES
        dx = int(round(math.cos(a) * width))
        dy = int(round(math.sin(a) * width))
        if dx or dy:
            out.blit(silhouette, (dx, dy), special_flags=pygame.BLEND_RGBA_MAX)
    out.blit(canvas, (0, 0))
    return out


# ---------------------------------------------------------
#  常用绘制封装
# ---------------------------------------------------------
def draw_panel(surface, rect, radius=24, color=None, edge=None,
               shadow=(232, 214, 224, 90), shadow_offset=5):
    """画一个带柔和投影的圆角面板。"""
    from config import PANEL, PANEL_EDGE
    color = color or PANEL
    edge = edge or PANEL_EDGE
    x, y, w, h = rect
    if shadow:
        layer = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        pygame.draw.rect(layer, shadow,
                         pygame.Rect(x, y + shadow_offset, w, h),
                         border_radius=radius)
        surface.blit(layer, (0, 0))
    pygame.draw.rect(surface, color, pygame.Rect(x, y, w, h), border_radius=radius)
    pygame.draw.rect(surface, edge, pygame.Rect(x, y, w, h), 2, border_radius=radius)


# ---------------------------------------------------------
#  姿态摆放（角色 / 小宠物共用）
# ---------------------------------------------------------
def posed_blit(surface, sprite, foot_x: float, foot_y: float, pose):
    """
    按 pose 把贴图"缩放 → 旋转"后摆到 (foot_x, foot_y)。

    锚点约定：foot_x/foot_y 是**贴图底边的中心**（也就是角色脚底）。
    为了不让角色在转圈时绕着脚底画大圈，旋转是以"静止时的贴图中心"
    为轴做的 —— 视觉上就是原地翻跟头。

    返回 (rect, 旋转前的高度)。后者用于换算头顶点位（旋转会让
    rect 变大，直接用它算比例会漂）。
    """
    img = sprite
    if abs(pose.sx - 1.0) > 1e-3 or abs(pose.sy - 1.0) > 1e-3:
        img = pygame.transform.smoothscale(
            img, (max(1, int(round(img.get_width() * pose.sx))),
                  max(1, int(round(img.get_height() * pose.sy)))))

    pre_h = img.get_height()
    if abs(pose.rot) > 0.05:
        img = pygame.transform.rotate(img, pose.rot)

    cx = int(round(foot_x))
    cy = int(round(foot_y - pre_h / 2.0))
    rect = img.get_rect(center=(cx, cy))
    surface.blit(img, rect)
    return rect, pre_h


# ---------------------------------------------------------
#  文字渲染缓存
# ---------------------------------------------------------
# 界面上的文字绝大多数是**每帧都一样**的（按钮名、数值条标签、提示语…），
# 一帧要渲染三十多次。缓存下来之后这些渲染基本就免费了。
# 键里带 text，所以会变的数值（0~100）最多撑到上限然后整体清空，不会失控。
_TEXT_CACHE: dict = {}
_TEXT_CACHE_MAX = 512
_TEXT_SIZE_CACHE: dict = {}


def render_text(text: str, size: int, bold: bool, color) -> pygame.Surface:
    """渲染一行文字（带缓存）。返回的 Surface 不要就地修改。"""
    key = (text, size, bold, color)
    img = _TEXT_CACHE.get(key)
    if img is None:
        if len(_TEXT_CACHE) >= _TEXT_CACHE_MAX:
            _TEXT_CACHE.clear()
        img = get_font(size, bold).render(text, True, color)
        _TEXT_CACHE[key] = img
    return img


def text_size(text: str, size: int, bold: bool = False):
    """量一行文字的宽高（带缓存 —— 按钮每帧都要量）。"""
    key = (text, size, bold)
    r = _TEXT_SIZE_CACHE.get(key)
    if r is None:
        if len(_TEXT_SIZE_CACHE) >= _TEXT_CACHE_MAX:
            _TEXT_SIZE_CACHE.clear()
        r = get_font(size, bold).size(text)
        _TEXT_SIZE_CACHE[key] = r
    return r


def text_at(surface, text, pos, size=18, color=(120, 102, 118),
            bold=False, center=False, shadow=None):
    """绘制一行文字，返回它的 rect。"""
    img = render_text(text, size, bold, color)
    rect = img.get_rect()
    if center:
        rect.center = pos
    else:
        rect.topleft = pos
    if shadow:
        sh = render_text(text, size, bold, shadow)
        surface.blit(sh, (rect.x + 1, rect.y + 2))
    surface.blit(img, rect)
    return rect
