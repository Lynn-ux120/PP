# -*- coding: utf-8 -*-
"""
motion.py —— 动作曲线库（角色 & 小宠物共用）
=========================================================
把"一段小动作"抽象成一条曲线：给定归一化进度 p ∈ [0, 1]，
返回一组变换量（位移 / 缩放 / 旋转）。谁用、用多大，由调用方决定。

为什么单独一个模块
  角色（260×300）和小宠物（140×132）体量不同，但"伸懒腰""打滚"
  这类动作的**节奏**是一样的 —— 曲线只管节奏，所以两边共用同一份，
  不必各写一遍。想同时调整两边的"手感"，改这里就够了。

【新增一种动作曲线】
  1. 写一个 fn(p) -> Pose 的函数（p 是 0 → 1 的进度）
  2. 注册进下面的 MOTION_LIB
  3. 在 config.py 的表里引用它的名字
     （PET_ANTICS 待机动作 / INTERACTIONS.motion 互动动作 /
       COMP_AI_TABLE 小宠物的行为）
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

TAU = math.tau


# ---------------------------------------------------------
#  小工具
# ---------------------------------------------------------
def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)


def smoothstep(x: float) -> float:
    x = clamp(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def envelop(p: float, rise: float = 0.3, fall: float = 0.3) -> float:
    """
    0 → 1 → 0 的平滑包络。
    动作的开始与结束都从 0 出发，避免"啪"地跳到位 / 跳回原位。
    """
    if p <= rise:
        return smoothstep(p / max(rise, 1e-6))
    if p >= 1.0 - fall:
        return smoothstep((1.0 - p) / max(fall, 1e-6))
    return 1.0


@dataclass
class Pose:
    """一帧的姿态变换量。多个 Pose 可以相加合成。"""

    dx: float = 0.0      # 水平位移（屏幕像素，右为正）
    dy: float = 0.0      # 垂直位移（屏幕像素，上为负）
    sx: float = 1.0      # 水平缩放
    sy: float = 1.0      # 垂直缩放
    rot: float = 0.0     # 旋转角度（度）

    def __add__(self, other: "Pose") -> "Pose":
        return Pose(self.dx + other.dx, self.dy + other.dy,
                    self.sx * other.sx, self.sy * other.sy,
                    self.rot + other.rot)


# ---------------------------------------------------------
#  动作曲线
#  —— 约定：dy 向上为负；返回的 Pose 在 p=0 与 p=1 时都应接近零姿态
# ---------------------------------------------------------
def c_stretch(p: float) -> Pose:
    """伸懒腰：整体拔高、收窄，再慢慢回弹。"""
    e = envelop(p, 0.42, 0.42)
    return Pose(dy=-10.0 * e, sx=1.0 - 0.10 * e, sy=1.0 + 0.22 * e)


def c_hop(p: float, n: float = 2.0) -> Pose:
    """
    原地蹦：跳两下，落地时压扁、腾空时拉长。
    包一层窄包络是为了让收尾回到 0 —— 否则 |cos| 在 p=1 处不等于 1，
    动作结束的瞬间会"啪"地弹一下。
    """
    a = p * n * math.pi
    e = envelop(p, 0.08, 0.22)
    h = abs(math.sin(a)) * 15.0 * e
    s = 1.0 - 0.070 * math.cos(a * 2.0) * e
    return Pose(dy=-h, sx=1.0 + (1.0 - s) * 0.75, sy=s)


def c_sway(p: float) -> Pose:
    """哼歌摇摆：左右晃得比较明显，身子跟着歪。"""
    a = p * TAU * 2.6
    e = envelop(p, 0.24, 0.24)
    return Pose(dx=math.sin(a) * 11.5 * e, rot=math.sin(a) * 6.0 * e,
                dy=-2.2 * e)


def c_tilt(p: float) -> Pose:
    """歪头张望：头往一边歪过去，停一会儿再回正。"""
    e = envelop(p, 0.3, 0.3)
    return Pose(rot=15.0 * e, dx=3.5 * e, dy=-1.5 * e)


def c_squat(p: float) -> Pose:
    """蹲下来歇会儿：整个矮一截。"""
    e = envelop(p, 0.3, 0.3)
    return Pose(sy=1.0 - 0.20 * e, sx=1.0 + 0.07 * e, dy=2.0 * e)


def c_twirl(p: float) -> Pose:
    """原地转一圈：整只旋转 360°，同时轻轻离地。"""
    e = smoothstep(p * 1.15)
    return Pose(rot=360.0 * e, dy=-8.0 * math.sin(p * math.pi))


def c_shiver(p: float) -> Pose:
    """打哆嗦 / 抽泣：高频小幅抖动。"""
    e = envelop(p, 0.14, 0.2)
    return Pose(dx=math.sin(p * TAU * 9.0) * 3.6 * e,
                rot=math.sin(p * TAU * 7.0) * 2.4 * e,
                dy=2.0 * e)


def c_shake(p: float) -> Pose:
    """甩头 / 抖水：幅度更大、频率稍低的一阵抖。"""
    e = envelop(p, 0.1, 0.22)
    a = p * TAU * 6.0
    return Pose(dx=math.sin(a) * 6.5 * e, rot=math.sin(a) * 9.0 * e,
                sx=1.0 + 0.06 * math.cos(a * 1.5) * e)


def c_sip(p: float) -> Pose:
    """仰头喝水。"""
    e = envelop(p, 0.3, 0.35)
    return Pose(rot=-12.0 * e, dy=-3.5 * e)


def c_squeeze(p: float) -> Pose:
    """被抱紧 → 一挤一松。"""
    e = envelop(p, 0.2, 0.25)
    a = p * TAU * 1.6
    s = 1.0 - 0.105 * e * (0.5 + 0.5 * math.cos(a))
    return Pose(sx=1.0 + (1.0 - s) * 0.85, sy=s, dy=(1.0 - s) * 26.0)


def c_roll(p: float) -> Pose:
    """
    打滚：侧着身子左右滚两下，滚完再爬起来。
    备注：一开始试过"翻整整一圈"，但二维平面里转到 180° 会变成头朝下，
    小动物看起来像倒挂着，很怪 —— 所以改成小幅侧滚。
    """
    e = envelop(p, 0.18, 0.22)
    a = p * TAU * 2.0
    return Pose(dx=math.sin(a) * 13.0 * e,
                rot=math.sin(a) * 27.0 * e,
                dy=-abs(math.sin(a)) * 3.5 * e,
                sy=1.0 - 0.08 * e)


def c_spin(p: float) -> Pose:
    """
    追尾巴：一边原地打转一边绕着小圈跑。
    二维旋转表达不了"绕竖轴转身"，所以用横向压缩 + 左右位移来模拟；
    压到 0 会变成一条线，所以留了 0.38 的底。
    """
    a = p * TAU * 2.4
    c = abs(math.cos(a))
    e = envelop(p, 0.10, 0.16)
    return Pose(dx=math.sin(a) * 10.0 * e,
                sx=1.0 - (1.0 - (0.38 + 0.62 * c)) * e,
                dy=-abs(math.sin(a)) * 2.4 * e,
                sy=1.0 + 0.05 * (1.0 - c) * e)


def c_groom(p: float) -> Pose:
    """低头舔毛：歪着身子一下一下地蹭。"""
    a = p * TAU * 2.5
    e = envelop(p, 0.2, 0.22)
    return Pose(dy=11.0 * e + abs(math.sin(a)) * 4.0 * e,
                rot=math.sin(a) * 6.5 * e, dx=-3.0 * e)


def c_dig(p: float) -> Pose:
    """刨地：前爪飞快地耸动。"""
    a = p * TAU * 4.0
    e = envelop(p, 0.18, 0.2)
    return Pose(dy=-abs(math.sin(a)) * 7.0 * e, dx=-4.5 * e,
                rot=math.sin(a) * 5.5 * e)


def c_nod(p: float) -> Pose:
    """点头 / 打瞌睡：一下一下地往前栽。"""
    a = p * TAU * 2.0
    e = envelop(p, 0.22, 0.25)
    n = 0.5 - 0.5 * math.cos(a)          # 0 → 1 → 0
    return Pose(dy=7.5 * n * e, rot=n * 7.0 * e)


# 名字 → 曲线。config 里引用的是这里的键名。
MOTION_LIB = {
    "stretch": c_stretch,
    "hop": c_hop,
    "sway": c_sway,
    "tilt": c_tilt,
    "squat": c_squat,
    "twirl": c_twirl,
    "shiver": c_shiver,
    "shake": c_shake,
    "sip": c_sip,
    "squeeze": c_squeeze,
    "roll": c_roll,
    "spin": c_spin,
    "groom": c_groom,
    "dig": c_dig,
    "nod": c_nod,
}


# ---------------------------------------------------------
#  播放器
# ---------------------------------------------------------
class MotionPlayer:
    """
    一次只播一个动作。行为很简单：
      play(名字, 时长) → 每帧 update(dt) → pose() 拿到当前姿态。
    播完自动归零，所以调用方不用管收尾。
    """

    def __init__(self, lib: dict | None = None):
        self.lib = lib if lib is not None else MOTION_LIB
        self.name: str | None = None
        self.t = 0.0
        self.duration = 0.0
        self.flip = 1
        self._pose = Pose()

    @property
    def playing(self) -> bool:
        return self.name is not None

    @property
    def progress(self) -> float:
        if not self.name or self.duration <= 0:
            return 0.0
        return clamp(self.t / self.duration, 0.0, 1.0)

    def play(self, name: str, duration: float = 1.5, flip: int = 1) -> bool:
        fn = self.lib.get(name)
        if fn is None:
            return False
        self.name = name
        self.t = 0.0
        self.duration = max(0.05, float(duration))
        self.flip = -1 if flip < 0 else 1
        self._pose = fn(0.0)
        return True

    def stop(self):
        self.name = None
        self.t = self.duration
        self._pose = Pose()

    def update(self, dt: float):
        if self.name is None:
            return
        self.t += dt
        if self.t >= self.duration:
            self.stop()
            return
        self._pose = self.lib[self.name](self.t / self.duration)

    def pose(self) -> Pose:
        p = self._pose
        if self.flip < 0:                    # 左右镜像（缩放不镜像）
            return Pose(-p.dx, p.dy, p.sx, p.sy, -p.rot)
        return p


# ---------------------------------------------------------
#  按权重随机
# ---------------------------------------------------------
def weighted_choice(items: list, key: str = "weight"):
    """从带 weight 字段的字典列表里按权重抽一个。"""
    if not items:
        return None
    total = sum(float(it.get(key, 1.0)) for it in items)
    if total <= 0.0:
        return random.choice(items)
    r = random.uniform(0.0, total)
    acc = 0.0
    for it in items:
        acc += float(it.get(key, 1.0))
        if r <= acc:
            return it
    return items[-1]
