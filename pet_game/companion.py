# -*- coding: utf-8 -*-
"""
companion.py —— 小宠物（陪伴动物）系统
=========================================================
主角"高紫桐"身边养着一只小动物：它有自己的数值、自己的 AI、
自己的形象，而且**完全由代码绘制**（不依赖任何外部图片）。

结构分成五块，方便各自独立扩展：
  ① 数值      bond(亲密) / belly(饱腹) / mood(心情)
  ② AI 状态机 行为表在 config.COMP_AI_TABLE，按权重随机挑下一个动作：
              walk(走动) / sit(坐下) / sleep(打盹) / chase(追蝴蝶) /
              nuzzle(跑去蹭主角) / groom(舔毛) / stretch(伸懒腰) /
              roll(打滚) / spin(追尾巴) / dig(刨地)
  ③ 动作系统  motion(MotionPlayer) —— 原地小动作的姿态曲线
  ④ 形象绘制  _render() 生成贴图（带缓存），draw() 负责动画与落位
  ⑤ 解锁      宠物种类按亲密度 / 互动次数 / 三值达成解锁

【新增一只小宠物】只需要在 config.COMPANIONS 里加一条字典，
  造型 kind 用现成的 cat / rabbit / shiba / bird 即可。
【新增一种宠物互动】在 config.COMPANION_ACTIONS 里加一行，
  companion.interact("新id") 就能直接生效。
【新增一个宠物动作】在 config.COMP_AI_TABLE 里加一行，并在下面的
  STATE_MOTION 里把它和 motion.py 的曲线对上。
"""
from __future__ import annotations

import math
import random

import pygame

from config import *
from motion import MotionPlayer, Pose, weighted_choice
from utils import Pen, get_font, clamp, mix, sticker_outline, posed_blit

SPRITE_PAD = 4

# ---------------------------------------------------------
#  宠物内部坐标系（画布 140 × 132，"脚底"在 y = 118）
#  —— 想调身材比例，改这里的常量即可
# ---------------------------------------------------------
COMP_BOX_W, COMP_BOX_H = 140, 132
GROUND_LOCAL = 118
BODY_CX = 70

# AI 状态
IDLE, WALK, SIT, SLEEP, CHASE, NUZZLE = (
    "idle", "walk", "sit", "sleep", "chase", "nuzzle")
# 原地小动作（本身不移动，纯粹的表演）
GROOM, STRETCH, ROLL, SPIN, DIG = (
    "groom", "stretch", "roll", "spin", "dig")

MOVE_STATES = (WALK, CHASE, NUZZLE)
ACT_STATES = (SIT, GROOM, STRETCH, ROLL, SPIN, DIG)

# 状态 → motion.py 里的动作曲线（没有的表示该状态不需要额外姿态）
STATE_MOTION = {
    GROOM: "groom",
    STRETCH: "stretch",
    ROLL: "roll",
    SPIN: "spin",
    DIG: "dig",
}
# 做了这些动作时顺手冒一点星光 / 说一句话
STATE_EFFECT = {ROLL: "sparkle", SPIN: "sparkle", STRETCH: "sparkle"}
STATE_SPEECH = {GROOM: "cgroom", STRETCH: "cstretch", ROLL: "croll",
                SPIN: "cspin", DIG: "cdig"}
STATE_SAY_CHANCE = 0.4


class Companion:
    """小宠物本体。"""

    NORMAL, HAPPY, SAD, SLEEPING = "normal", "happy", "sad", "sleeping"

    def __init__(self, species_id: str = COMPANION_START, x: float | None = None):
        self.species_id = species_id
        # 默认站在主角左手边（不要站到她自己身上去）
        self.x = float(PET_CENTER[0] - 172 if x is None else x)
        self.y = ground_top(self.x) + 6

        # ---------- 数值 ----------
        self.bond = COMP_INIT["bond"]        # 亲密度（不衰减：感情不会变淡）
        self.belly = COMP_INIT["belly"]      # 饱腹
        self.mood = COMP_INIT["mood"]        # 心情

        # ---------- 状态机 ----------
        self.state = IDLE
        self.state_t = random.uniform(0.6, 1.8)
        self.target_x = self.x
        self.facing = 1
        self._butterfly = None
        self._bob = random.uniform(0, math.tau)

        # ---------- 动作 ----------
        self.motion = MotionPlayer()
        self.pending_effects: list = []    # 待播特效，由 main.py 取走

        # ---------- 计时器 ----------
        self.anim_time = random.uniform(0.0, 5.0)
        self.reaction_timer = 0.0
        self._cooldowns: dict = {}
        self._last_mood = "ok"
        self._idle_timer = random.uniform(9.0, 16.0)

        # ---------- 解锁 ----------
        self.action_count = 0
        self._max_seen = {k: self.get_stat(k) for k in COMP_STAT_KEYS}
        self.unlocked = {c["id"] for c in COMPANIONS if not c["unlock"]}
        self.pending_unlocks: list = []
        self._thumb_cache: dict = {}

        # ---------- 说话 & 绘制 ----------
        self.say_text = ""
        self._say_timer = 0.0
        self._sprite_cache: dict = {}
        self.rect = pygame.Rect(0, 0, COMP_BOX_W, COMP_BOX_H)

    # =====================================================
    #  ① 数值
    # =====================================================
    def get_stat(self, key: str) -> float:
        return float(getattr(self, key, 0.0))

    def set_stat(self, key: str, value: float):
        setattr(self, key, clamp(value, 0.0, COMP_MAX))

    @property
    def min_stat(self) -> float:
        return min(self.belly, self.mood)

    @property
    def thriving(self) -> bool:
        """三项都不错 —— 用来给主角加一点心情加成。"""
        return self.min_stat > 70.0

    # =====================================================
    #  ② 每帧推进
    # =====================================================
    def update(self, dt: float, host=None, particles=None):
        self.anim_time += dt
        self.motion.update(dt)

        # 峰值记录（解锁条件用）
        for k in COMP_STAT_KEYS:
            v = self.get_stat(k)
            if v > self._max_seen[k]:
                self._max_seen[k] = v
        self._refresh_unlocks()

        # 数值衰减（睡着时几乎不动）
        if self.state != SLEEP:
            self.belly = clamp(self.belly - COMP_BELLY_DECAY * dt, 0.0, COMP_MAX)
            self.mood = clamp(self.mood - COMP_MOOD_DECAY * dt, 0.0, COMP_MAX)

        # 计时器
        self.reaction_timer = max(0.0, self.reaction_timer - dt)
        self._say_timer = max(0.0, self._say_timer - dt)
        for k in self._cooldowns:
            self._cooldowns[k] = max(0.0, self._cooldowns[k] - dt)

        self._ai(dt, host, particles)

        # 状态变差时出声
        mood = self._mood_key()
        if mood != self._last_mood:
            self._last_mood = mood
            if mood in ("hungry", "lonely") and self._say_timer <= 0:
                self.say(random.choice(SPEECH["chungry" if mood == "hungry"
                                        else "clonely"]), 2.4)
                self._idle_timer = random.uniform(9.0, 16.0)

        # 待机碎碎念
        self._idle_timer -= dt
        if self._idle_timer <= 0:
            self._idle_timer = random.uniform(13.0, 24.0)
            if self._say_timer <= 0 and self.state != SLEEP and self.min_stat > COMP_LOW:
                self.say(random.choice(SPEECH["idle"]), 2.0)

        # 落位：脚底始终贴着草地
        self.y = ground_top(self.x) + 6

    def _mood_key(self) -> str:
        if self.state == SLEEP:
            return "sleep"
        if self.belly < COMP_LOW:
            return "hungry"
        if self.mood < COMP_LOW:
            return "lonely"
        return "ok"

    # ---------- AI ----------
    def _enter(self, state: str, duration: float):
        self.state = state
        self.state_t = duration
        if state != CHASE:
            self._butterfly = None

        # 挂上对应的动作曲线；走动/坐下这类用不着曲线的状态就收起姿态
        mname = STATE_MOTION.get(state)
        if mname:
            self.motion.play(mname, duration)
        else:
            self.motion.stop()

        # 自娱自乐时顺手冒点星光、偶尔哼一声
        eff = STATE_EFFECT.get(state)
        if eff:
            self.pending_effects.append(eff)
        key = STATE_SPEECH.get(state)
        if key and self._say_timer <= 0 and random.random() < STATE_SAY_CHANCE:
            self.say(random.choice(SPEECH[key]), 1.6)

    def _choose_next(self, host):
        """
        挑一个"接下来干什么"。
        行为池与权重都在 config.COMP_AI_TABLE —— 想改它的性格改那里就行。
        """
        base = host.x if host is not None else WIDTH / 2
        # 主角的贴图很宽，小宠物站得太中间会被"压在"她身上 →
        # 目标点始终避开主角正中间这条带子，各自待在左右两侧。
        span = 150.0

        spec = weighted_choice(COMP_AI_TABLE)
        if spec is None:
            self._enter(IDLE, random.uniform(1.0, 2.4))
            return
        kind = spec["id"]
        dur = random.uniform(*spec.get("dur", (2.0, 4.0)))

        if kind == "walk_near":            # 在主角附近溜达（固定在她左右侧）
            side = 1 if random.random() < 0.5 else -1
            self.target_x = clamp(base + side * random.uniform(span, span + 82),
                                  82, WIDTH - 82)
            self._enter(WALK, dur)
        elif kind == "walk_far":           # 自己去远处逛
            self.target_x = random.uniform(82, WIDTH - 82)
            if abs(self.target_x - base) < span:
                self.target_x = clamp(base + math.copysign(span + 14,
                                                           self.target_x - base),
                                      82, WIDTH - 82)
            self._enter(WALK, dur)
        elif kind == "chase":              # 追蝴蝶
            self._butterfly = clamp(self.x + random.uniform(-90, 90), 82, WIDTH - 82)
            self.target_x = self._butterfly
            self._enter(CHASE, dur)
        else:                              # 原地小动作：舔毛 / 伸懒腰 / 打滚…
            self._enter(kind, dur)

    def _ai(self, dt: float, host, particles):
        # 主角睡觉 → 陪在旁边一起睡
        if host is not None and host.sleeping:
            if self.state != SLEEP:
                self.x = clamp(host.x + 158, 90, WIDTH - 90)
                self._enter(SLEEP, 6.0)
            return
        if self.state == SLEEP:            # 主角醒了，跟着醒
            self._enter(IDLE, 0.9)
            return

        # 饿了 → 跑去主角身边讨食
        if (self.belly < COMP_SEEK_BELLY and host is not None
                and self.state != NUZZLE and random.random() < 0.55 * dt):
            self.target_x = clamp(host.x + (156 if self.x < host.x else -156),
                                  90, WIDTH - 90)
            self._enter(NUZZLE, 5.0)
            if particles is not None:
                particles.spawn_hearts((self.x, self.y - 96), n=3, spread=30, scale=0.8)

        if self.state in MOVE_STATES:
            dx = self.target_x - self.x
            speed = 34.0 if self.state == WALK else (56.0 if self.state == CHASE else 46.0)
            if abs(dx) <= 3.5:
                if self.state == CHASE and particles is not None:
                    particles.spawn_sparkles((self.x, self.y - 96), n=4, spread=38)
                self._enter(IDLE, random.uniform(1.2, 3.4))
            else:
                self.x += math.copysign(1.0, dx) * speed * dt
                self.facing = 1 if dx > 0 else -1
                self._bob += dt * (11.0 if self.state != CHASE else 15.0)
                # 追蝴蝶：蝴蝶会自己乱飞，追到手就换一只
                if self.state == CHASE:
                    if self._butterfly is None or abs(self.x - self._butterfly) < 14:
                        self._butterfly = clamp(self.x + random.uniform(-95, 95),
                                                82, WIDTH - 82)
                    self.target_x = self._butterfly
        else:
            # 站在原地时，如果正好站到主角身上去了，就挪到她身边
            if (host is not None and self.state in (IDLE, SIT)
                    and abs(self.x - host.x) < 140):
                side = 1 if self.x >= host.x else -1
                self.target_x = clamp(host.x + side * random.uniform(158, 214),
                                      82, WIDTH - 82)
                self._enter(WALK, 6.0)
                return
            # 原地站着：到点换下一个动作
            self.state_t -= dt
            if self.state_t <= 0:
                self._choose_next(host)

    # =====================================================
    #  互动（表驱动：逻辑来自 config.COMPANION_ACTIONS）
    # =====================================================
    def cooldown(self, action_id: str) -> float:
        return self._cooldowns.get(action_id, 0.0)

    def can_interact(self, action_id: str) -> bool:
        return action_id in COMPANION_ACTION_MAP and self.cooldown(action_id) <= 0

    def interact(self, action_id: str):
        """执行一次宠物互动，返回 dict(action, gained, effect)；不可执行返回 None。"""
        spec = COMPANION_ACTION_MAP.get(action_id)
        if spec is None or self.cooldown(action_id) > 0:
            return None

        gained = {}
        for key, delta in spec.get("gain", {}).items():
            before = self.get_stat(key)
            self.set_stat(key, before + delta)
            gained[key] = self.get_stat(key) - before

        self._cooldowns[action_id] = spec.get("cooldown", 0.4)
        self.action_count += 1
        self.reaction_timer = 1.7
        self._enter(IDLE, 1.4)              # 被照顾的时候乖乖站好
        mo = spec.get("motion")             # 互动自带的动作（低头吃 / 扑过去…）
        if mo:
            self.motion.play(mo[0], mo[1])
        self.say(random.choice(SPEECH[spec["speech"]]), 1.9)
        return dict(action=action_id, gained=gained, effect=spec["effect"])

    def pet(self):
        """直接点草地上的小宠物 = 摸摸它。"""
        if self.cooldown("touch") > 0:
            return None
        self._cooldowns["touch"] = 0.45
        self.action_count += 1
        self.reaction_timer = 1.5
        self._enter(IDLE, 1.2)
        self.motion.play("sway", 1.1)       # 被摸到 → 舒服地晃一晃
        gained = {}
        for key, delta in (("bond", 5.0), ("mood", 6.0)):
            before = self.get_stat(key)
            self.set_stat(key, before + delta)
            gained[key] = self.get_stat(key) - before
        return dict(action="touch", gained=gained, effect="ctouch")

    # =====================================================
    #  ③ 宠物种类
    # =====================================================
    @property
    def species(self) -> dict:
        return COMPANION_MAP.get(self.species_id, COMPANIONS[0])

    @property
    def name(self) -> str:
        return self.species["name"]

    def species_unlocked(self, sid: str) -> bool:
        spec = COMPANION_MAP.get(sid)
        if spec is None:
            return False
        cond = spec.get("unlock")
        if not cond:
            return True
        if "bond" in cond:
            return self._max_seen.get("bond", 0.0) >= cond["bond"]
        if "actions" in cond:
            return self.action_count >= cond["actions"]
        if "all" in cond:
            return all(v >= cond["all"] for v in self._max_seen.values())
        return False

    def available_species(self) -> list:
        return [c["id"] for c in COMPANIONS if self.species_unlocked(c["id"])]

    def set_species(self, sid: str, force: bool = False) -> bool:
        if sid not in COMPANION_MAP or sid == self.species_id:
            return False
        if not force and not self.species_unlocked(sid):
            return False
        self.species_id = sid
        return True

    def _refresh_unlocks(self):
        for spec in COMPANIONS:
            sid = spec["id"]
            if sid in self.unlocked:
                continue
            if self.species_unlocked(sid):
                self.unlocked.add(sid)
                self.pending_unlocks.append(sid)

    def render_thumb(self, sid: str, size=None) -> pygame.Surface:
        """宠物面板卡片用的小图（实时渲染 + 缓存）。"""
        size = size or COMP_THUMB_SIZE
        key = (sid, size)
        if key in self._thumb_cache:
            return self._thumb_cache[key]
        sprite = self._render(sid=sid, emo=self.NORMAL, state=IDLE)
        s = COMP_SCALE
        # 正方形裁切 → 缩略图不会被拉伸变形
        crop = pygame.Rect(int(18 * s), int(3 * s),
                           int(116 * s), int(116 * s)).clip(sprite.get_rect())
        thumb = pygame.transform.smoothscale(sprite.subsurface(crop).copy(), size)
        self._thumb_cache[key] = thumb
        return thumb

    # ---------- 说话 ----------
    def say(self, text: str, duration: float = 2.0):
        self.say_text = text
        self._say_timer = duration

    def take_effects(self) -> list:
        """取走积累的特效请求（main.py 每帧调一次）。"""
        out = self.pending_effects
        self.pending_effects = []
        return out

    # =====================================================
    #  ④ 表情 & 形象绘制
    # =====================================================
    @property
    def emotion(self) -> str:
        if self.state == SLEEP:
            return self.SLEEPING
        if self.reaction_timer > 0:
            return self.HAPPY
        if self.min_stat < COMP_LOW:
            return self.SAD
        return self.NORMAL

    def _render(self, sid: str | None = None, emo: str | None = None,
                state: str | None = None, facing: int | None = None) -> pygame.Surface:
        """生成小宠物贴图（超采样 + 贴纸描边），结果带缓存。"""
        sid = sid or self.species_id
        o = COMPANION_MAP.get(sid, COMPANIONS[0])
        emo = emo or self.emotion
        state = self.state if state is None else state
        facing = self.facing if facing is None else facing

        tail_frame = 0 if state == SLEEP else int(self.anim_time * 3.4) % 4
        key = (sid, emo, tail_frame, facing)
        if key in self._sprite_cache:
            return self._sprite_cache[key]

        k = CHAR_SUPERSAMPLE
        W, H = COMP_BOX_W, COMP_BOX_H
        canvas = pygame.Surface((W * k, H * k), pygame.SRCALPHA)
        p = Pen(canvas, k)

        self._draw_shadow(p)
        self._draw_tail(p, o, tail_frame, state)
        self._draw_body(p, o)
        self._draw_paws(p, o)
        self._draw_ears(p, o, emo)
        self._draw_head(p, o)
        self._draw_markings(p, o, emo)
        self._draw_face(p, o, emo)
        self._draw_cheeks(p, o, emo)

        sprite = pygame.transform.smoothscale(canvas, (W, H))
        padded = pygame.Surface((W + SPRITE_PAD * 2, H + SPRITE_PAD * 2), pygame.SRCALPHA)
        padded.blit(sprite, (SPRITE_PAD, SPRITE_PAD))
        sprite = sticker_outline(padded, width=2)

        # 整体放大到设定身量（内部坐标系保持不变，改 COMP_SCALE 即可）
        if abs(COMP_SCALE - 1.0) > 1e-3:
            sprite = pygame.transform.smoothscale(
                sprite, (max(1, int(sprite.get_width() * COMP_SCALE)),
                         max(1, int(sprite.get_height() * COMP_SCALE))))
        if facing < 0:
            sprite = pygame.transform.flip(sprite, True, False)

        if len(self._sprite_cache) > 90:
            self._sprite_cache.clear()
        self._sprite_cache[key] = sprite
        return sprite

    # ---------- 各部件 ----------
    def _draw_shadow(self, p: Pen):
        p.soft((196, 176, 200, 55), "ellipse", rect=(28, 108, 84, 16))

    def _draw_tail(self, p: Pen, o: dict, frame: int, state: str):
        kind, tail = o["kind"], o["tail"]
        swing = (frame - 1.5) * 5.0          # -7.5 → +7.5 一摆一摆

        if kind == "cat":                    # 长长的弯尾巴
            p.arc(tail, (100 + swing * 0.5, 88), 26, 32, 275, 80, 9)
            p.arc(mix(tail, (255, 255, 255), 0.45), (100 + swing * 0.5, 88),
                  26, 32, 295, 50, 2.6)
        elif kind == "rabbit":               # 圆球尾
            p.circle(tail, (104, 90), 12)
            p.circle(mix(tail, (255, 255, 255), 0.5), (100, 86), 4.6)
        elif kind == "shiba":                # 卷起来的柴犬尾
            p.arc(tail, (102, 86), 21, 21, 196 + swing * 1.6, 344 + swing * 1.6, 10)
            p.circle(tail, (108, 66 + swing * 0.25), 7.5)
        else:                                # 小鸟：扇形尾羽
            for off in (-11, 0, 11):
                p.polygon(tail, [
                    (94, 92),
                    (128 + off * 0.6, 82 + off * 0.5 + swing * 0.4),
                    (124 + off * 0.6, 98 + off * 0.5 + swing * 0.4),
                ])

    def _draw_body(self, p: Pen, o: dict):
        kind, body, patch, tummy = o["kind"], o["body"], o["patch"], o["tummy"]
        # 一圈略深的描边 —— 否则"白兔 + 白脸"会糊成一团认不出来
        edge = mix(body, (146, 136, 158), 0.18)

        if kind == "bird":
            p.ellipse(edge, (32, 56, 76, 62))
            p.ellipse(body, (34, 58, 72, 58))
            p.ellipse(tummy, (49, 78, 42, 32))
            for sx in (-1, 1):               # 两侧小翅膀
                p.ellipse(patch, (70 + sx * 35 - 12, 66, 24, 33))
            p.soft((255, 255, 255, 75), "ellipse", rect=(56, 62, 24, 11))
            return

        p.ellipse(edge, (31, 50, 78, 66))
        p.ellipse(body, (33, 52, 74, 62))
        p.ellipse(tummy, (54, 86, 32, 26))
        if kind == "shiba":                  # 胸口的浅色弧
            p.arc(patch, (70, 86), 26, 22, 192, 348, 3)
        p.soft((255, 255, 255, 70), "ellipse", rect=(46, 58, 30, 12))

    def _draw_paws(self, p: Pen, o: dict):
        if o["kind"] == "bird":              # 细爪
            for sx in (-1, 1):
                x = 70 + sx * 15
                p.line(o["nose"], (x, 108), (x, 118), 4)
                p.line(o["nose"], (x, 118), (x - sx * 8, 119), 3)
            return
        paw = mix(o["body"], (214, 204, 210), 0.22)
        for cx in (56, 84):
            p.ellipse(paw, (cx - 13, 96, 26, 20))
            p.soft((255, 255, 255, 110), "ellipse", rect=(cx - 8, 100, 12, 6))

    def _draw_head(self, p: Pen, o: dict):
        edge = mix(o["body"], (146, 136, 158), 0.18)
        p.circle(edge, (BODY_CX, 44), 35)
        p.circle(o["body"], (BODY_CX, 44), 33)
        p.soft((255, 255, 255, 85), "ellipse", rect=(50, 20, 34, 20))

    def _draw_ears(self, p: Pen, o: dict, emo: str):
        kind, ear, inner = o["kind"], o["ear"], o["inner"]
        droop = 9.0 if emo == self.SAD else 0.0    # 蔫掉时耳朵往下垂

        if kind == "cat":
            p.rounded_polygon(ear, [(43, 33), (48, 3), (69, 23)], 3.5)
            p.rounded_polygon(inner, [(50, 29), (51, 13), (63, 24)], 2.4)
            p.rounded_polygon(ear, [(97, 33), (92, 3), (71, 23)], 3.5)
            p.rounded_polygon(inner, [(90, 29), (89, 13), (77, 24)], 2.4)
        elif kind == "rabbit":
            for sx in (-1, 1):
                bx = 70 + sx * 20
                p.ellipse(ear, (bx - 10, 0 + droop * 1.5, 20, 48))
                p.ellipse(inner, (bx - 5, 8 + droop * 1.5, 10, 32))
        elif kind == "shiba":
            p.rounded_polygon(ear, [(43, 34), (47, 5), (70, 25)], 5)
            p.rounded_polygon(mix(inner, (255, 255, 255), 0.55),
                              [(51, 30), (52, 16), (64, 25)], 3)
            p.rounded_polygon(ear, [(97, 34), (93, 5), (70, 25)], 5)
            p.rounded_polygon(mix(inner, (255, 255, 255), 0.55),
                              [(89, 30), (88, 16), (76, 25)], 3)
        else:                                # 小鸟：头顶的小呆毛
            for sx in (-1, 1):
                p.arc(mix(o["body"], (255, 255, 255), 0.3),
                      (70 + sx * 14, 18), 9, 11, 200, 340, 4)

    def _draw_markings(self, p: Pen, o: dict, emo: str):
        """
        头上的花纹 + 鼻子（或鸟喙）。
        必须画在 _draw_head / _draw_ears 之后，否则会被头盖住看不见。
        """
        kind, nose = o["kind"], o["nose"]

        if kind == "cat":                    # 三花：头顶一块橘斑 + 右耳根一小块
            p.ellipse(o["patch"], (58, 14, 28, 18))
            p.circle(o["patch"], (100, 34), 7.5)
        elif kind == "shiba":                # 柴犬标志性的白色口鼻
            p.ellipse(o["tummy"], (53, 50, 34, 24))

        if kind == "bird":
            p.polygon(nose, [(64, 54), (76, 54), (70, 66)])
            p.line(mix(nose, (200, 140, 60), 0.4), (64, 60), (76, 60), 1.6)
        else:
            p.polygon(nose, [(64, 55), (76, 55), (70, 62)])
            p.soft((255, 255, 255, 150), "ellipse", rect=(67.5, 56, 5, 3))

    def _draw_face(self, p: Pen, o: dict, emo: str):
        ex_l, ex_r, ey = 56, 84, 46

        if emo == self.SLEEPING:
            for cx in (ex_l, ex_r):
                p.arc(C_EYE, (cx, ey + 2), 9, 6, 22, 158, 3.4)
        elif emo == self.HAPPY:
            for cx in (ex_l, ex_r):          # "⌒⌒" 眯眼笑
                p.arc(C_EYE, (cx, ey + 3), 9, 7.5, 180, 360, 4)
        elif emo == self.SAD:
            for cx in (ex_l, ex_r):
                p.ellipse(C_EYE, (cx - 6, ey - 4, 12, 9))     # 无精打采
                p.circle((255, 255, 255), (cx - 2, ey - 1), 1.8)
            for cx in (ex_l, ex_r):
                p.arc(C_EYE, (cx, ey - 5), 8, 4.5, 22, 158, 2.4)   # 垂眉
        else:
            for cx in (ex_l, ex_r):
                p.circle(C_EYE, (cx, ey), 7)
                p.circle((255, 255, 255), (cx - 2.4, ey - 2.6), 3.2)
                p.circle((255, 255, 255), (cx + 2.6, ey + 2.4), 1.4)

        # 嘴巴
        if emo == self.HAPPY:
            p.arc(C_MOUTH, (70, 63), 11, 8, 18, 162, 3)
        elif emo == self.SAD:
            p.arc(C_MOUTH, (70, 70), 8, 5, 202, 338, 2.6)
        elif emo == self.SLEEPING:
            p.arc(C_MOUTH, (70, 64), 5.5, 4, 25, 155, 2.2)
            p.circle(mix(C_MOUTH, (255, 255, 255), 0.5), (70, 68), 2.4)   # 小鼻泡
        else:                                # ω 形猫嘴
            p.arc(C_MOUTH, (63.5, 61), 5.4, 4.6, 15, 165, 2.2)
            p.arc(C_MOUTH, (76.5, 61), 5.4, 4.6, 15, 165, 2.2)

        # 胡须（小鸟没有）
        if o["kind"] != "bird":
            whisker = mix(C_HAIR, (255, 255, 255), 0.42)
            for dy in (-4, 0, 4):
                p.line(whisker, (46, 59 + dy), (24, 55 + dy), 1.7)
                p.line(whisker, (94, 59 + dy), (116, 55 + dy), 1.7)
        else:                                # 小鸟的腮红点
            p.circle(o["accent"], (46, 62), 4.5)
            p.circle(o["accent"], (94, 62), 4.5)

    def _draw_cheeks(self, p: Pen, o: dict, emo: str):
        alpha = 155 if emo == self.HAPPY else 95
        for cx in (44, 96):
            p.soft((C_BLUSH[0], C_BLUSH[1], C_BLUSH[2], alpha),
                   "ellipse", rect=(cx - 9, 60, 18, 9))

    # -----------------------------------------------------
    #  对外绘制入口
    # -----------------------------------------------------
    def draw(self, surface: pygame.Surface):
        sprite = self._render()
        t = self.anim_time

        # 走动时一颠一颠；睡觉时缓慢起伏；原地小动作交给动作曲线
        if self.state in MOVE_STATES:
            hop = abs(math.sin(self._bob)) * 4.5
            squash = 1.0 + 0.05 * math.sin(self._bob * 2.0)
        elif self.state == SLEEP:
            hop = 0.0
            squash = 1.0 + 0.03 * math.sin(t * 1.6)
        elif self.state == SIT:
            # 坐下：整体矮一截（0.97 时几乎看不出来，压到 0.90 才明显）
            hop = 0.0
            squash = 0.90
        elif self.state in ACT_STATES:
            hop = 0.0
            squash = 1.0
        else:
            hop = math.sin(t * 1.9) * 1.4
            squash = 1.0 + 0.022 * math.sin(t * 2.0)

        # 基础姿态 + 动作曲线
        pose = Pose(dy=-hop, sx=1.0 / squash, sy=squash) + self.motion.pose()

        # 让"脚底"（画布 y = GROUND_LOCAL 处）落在草地上
        foot_drop = (COMP_BOX_H + 2 * SPRITE_PAD
                     - SPRITE_PAD - GROUND_LOCAL) * COMP_SCALE
        rect, _ = posed_blit(surface, sprite, int(self.x + pose.dx),
                             int(self.y + foot_drop) + pose.dy, pose)
        self.rect = rect

        if self._say_timer > 0 and self.say_text:
            self._draw_bubble(surface, self.say_text, rect)

    def _draw_bubble(self, surface, text: str, sprite_rect: pygame.Rect):
        font = get_font(14)
        img = font.render(text, True, TEXT)
        pad_x, pad_y = 12, 7
        w = img.get_width() + pad_x * 2
        h = img.get_height() + pad_y * 2

        alpha = int(255 * clamp(self._say_timer / 0.3, 0, 1))
        bx = int(clamp(sprite_rect.centerx - w / 2, 8, WIDTH - w - 8))
        by = sprite_rect.top - h - 6 + int(math.sin(self.anim_time * 2.8) * 2)

        layer = pygame.Surface((w, h + 9), pygame.SRCALPHA)
        pygame.draw.rect(layer, (255, 255, 255, int(alpha * 0.95)),
                         pygame.Rect(0, 0, w, h), border_radius=12)
        pygame.draw.rect(layer, (*PANEL_EDGE, alpha),
                         pygame.Rect(0, 0, w, h), 2, border_radius=12)
        pygame.draw.polygon(layer, (255, 255, 255, int(alpha * 0.95)), [
            (w // 2 - 7, h - 2), (w // 2 + 7, h - 2), (w // 2, h + 8)])
        img.set_alpha(alpha)
        layer.blit(img, (pad_x, pad_y))
        surface.blit(layer, (bx, by))
