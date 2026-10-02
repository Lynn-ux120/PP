# -*- coding: utf-8 -*-
"""
pet.py —— 宠物"高紫桐"的状态机 & 形象绘制
=========================================================
角色形象完全由代码绘制（不依赖外部图片）：
深色齐刘海 + 双马尾 + 白色蕾丝领衬衫 + 领口蝴蝶结 + 小花发饰，
参考工作区 ppphoto.jpg 的人物特征做了 Q 版卡通化处理。

结构分成四块，方便各自独立扩展：
  ① 数值逻辑  update() / interact()
  ② 表情状态机 emotion 属性 + 眨眼 / 互动 / 睡眠计时器
  ③ 衣装系统  outfit 属性 + set_outfit() / render_thumb()
  ④ 形象绘制  _render() 生成角色贴图（带缓存），draw() 负责动画与落位

【新增一种互动】不用写新方法，只要在 config.INTERACTIONS 里加一行，
  pet.interact("新id") 就能直接生效。
【新增一种表情】在 _draw_face() / _draw_blush() 里加分支，
  并在 emotion 属性里给出判定条件。
【新增一套衣装】只要在 config.OUTFITS 里加一行。绘制方面已经有四种版型
  （blouse / dress / sweater / overall）和六种发饰（flower / sakura /
  star / moon / ribbon / bear），配色与图案全部由那条字典驱动，
  通常不需要动本文件。
"""
from __future__ import annotations

import math
import random

import pygame

from config import *
from motion import MotionPlayer, Pose, weighted_choice
from utils import Pen, get_font, clamp, mix, sticker_outline, posed_blit

# 贴图四周留出的透明边（用于描边，避免被裁掉）
SPRITE_PAD = 6

# 说明：贴纸描边的实现已提到 utils.sticker_outline（小宠物也要用同一套）
_sticker_outline = sticker_outline

# ---------------------------------------------------------
#  角色内部坐标系（画布 260 × 300，脚底在 y≈280）
#  —— 想调整身材比例，改这里的常量即可
# ---------------------------------------------------------
HEAD_CX, HEAD_CY, HEAD_R = 130, 100, 70     # 头
EYE_LX, EYE_RX, EYE_Y = 104, 156, 128       # 双眼
BLUSH_Y = 146                               # 腮红
MOUTH_Y = 158                               # 嘴巴
CHIN_Y = 170                                # 下巴
BODY_TOP, BODY_BOT = 164, 246               # 身体上下沿
ARM_CX = (86, 174)                          # 手臂中心 x
HAND_Y = 226                                # 手的位置


def _arc_pts(cx, cy, rx, ry, a0, a1, n=26):
    """生成椭圆弧上的点，用于嘴巴 / 眉毛等曲线。"""
    pts = []
    for i in range(n + 1):
        a = math.radians(a0 + (a1 - a0) * i / n)
        pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
    return pts


class Pet:
    """宠物本体。"""

    NORMAL, HAPPY, SAD, MEH = "normal", "happy", "sad", "meh"
    SLEEPING, TIRED = "sleeping", "tired"

    def __init__(self, name: str = PET_NAME, center=None):
        self.name = name
        self.x, self.y = center or PET_CENTER      # y 为角色画布中心

        # ---------- 数值 ----------
        self.hunger = INIT_HUNGER         # 饱腹值
        self.happiness = INIT_HAPPINESS   # 快乐值
        self.energy = INIT_ENERGY         # 精力值

        # ---------- 计时器 ----------
        self.anim_time = 0.0
        self.reaction_timer = 0.0
        self.reaction_kind = None
        self._cooldowns: dict = {}        # {互动id: 剩余冷却秒数}

        self._blink_timer = random.uniform(1.8, 4.5)
        self._blinking = 0.0
        self._chew = 0.0
        self._play_bounce = 0.0           # 玩耍时的额外弹跳

        # ---------- 睡眠 ----------
        self.sleeping = False
        self._sleep_timer = 0.0

        self.say_text = ""
        self._say_timer = 0.0
        self._idle_talk_timer = random.uniform(9.0, 16.0)
        self._last_mood = "ok"

        # ---------- 动作 ----------
        self.motion = MotionPlayer()
        self._antic_timer = random.uniform(*ANTIC_FIRST_GAP)
        self.pending_effects: list = []    # 待播特效，由 main.py 取走

        # ---------- 衣装 ----------
        self.outfit_id = OUTFITS[0]["id"]          # 当前穿的衣服（见 config.OUTFITS）
        self._max_seen = {k: self.get_stat(k) for k in STAT_KEYS}
        self.interaction_count = 0                 # 累计互动次数（解锁条件用）
        self.unlocked = {o["id"] for o in OUTFITS if not o["unlock"]}
        self.pending_unlocks: list = []            # 刚解锁、还没播过提示的衣服
        self._thumb_cache: dict = {}

        # ---------- 缓存 ----------
        self._sprite_cache: dict = {}

        # 屏幕坐标（draw() 时刷新）
        self.head_pos = (self.x, self.y - 70)
        self.mouth_pos = (self.x, self.y + 6)
        self.box_rect = pygame.Rect(0, 0, PET_BOX_W, PET_BOX_H)

        self.say(f"我是{self.name}，请多关照～♪", 3.2)

    # =====================================================
    #  ① 数值逻辑
    # =====================================================
    @property
    def min_stat(self) -> float:
        """三条数值里最低的那条（不含精力，精力单独判定犯困）。"""
        return min(self.hunger, self.happiness)

    def get_stat(self, key: str) -> float:
        return float(getattr(self, key, 0.0))

    def set_stat(self, key: str, value: float):
        setattr(self, key, clamp(value, 0.0, STAT_MAX))

    def update(self, dt: float, particles=None, happiness_mul: float = 1.0):
        """
        推进一帧。

        particles     预留钩子，方便以后把特效交给宠物自行触发
                      （当前特效统一由 main.py 管理，所以通常传 None）
        happiness_mul 快乐值衰减的额外倍率 —— 小宠物过得好会让她更省心
                      （<1 衰减更慢），宠物饿着则会让她更操心（>1）。
        """
        self.anim_time += dt
        self.motion.update(dt)

        # --- 记录数值历史峰值 + 刷新衣装解锁（衣橱的解锁条件就靠它）---
        for k in STAT_KEYS:
            v = self.get_stat(k)
            if v > self._max_seen[k]:
                self._max_seen[k] = v
        self._refresh_unlocks()

        # --- 睡眠：快速回精力，其余数值几乎停滞 ---
        if self.sleeping:
            self._sleep_timer -= dt
            self.energy = clamp(self.energy + SLEEP_ENERGY_RATE * dt, 0.0, STAT_MAX)
            decay_mul = SLEEP_DECAY_MUL
            if self._sleep_timer <= 0:
                self.wake_up()
        else:
            decay_mul = 1.0
            self.energy = clamp(self.energy - ENERGY_DECAY * dt, 0.0, STAT_MAX)

        # --- 数值自然衰减 ---
        self.hunger = clamp(
            self.hunger - HUNGER_DECAY * decay_mul * dt, 0.0, STAT_MAX)
        self.happiness = clamp(
            self.happiness - HAPPINESS_DECAY * decay_mul * happiness_mul * dt,
            0.0, STAT_MAX)

        # --- 计时器 ---
        self.reaction_timer = max(0.0, self.reaction_timer - dt)
        self._say_timer = max(0.0, self._say_timer - dt)
        self._chew = max(0.0, self._chew - dt)
        self._play_bounce = max(0.0, self._play_bounce - dt * 0.9)
        for key in self._cooldowns:
            self._cooldowns[key] = max(0.0, self._cooldowns[key] - dt)

        # --- 眨眼（睡觉时不眨） ---
        if self.sleeping:
            self._blinking = 0.0
        else:
            self._blink_timer -= dt
            if self._blinking > 0:
                self._blinking -= dt
            elif self._blink_timer <= 0:
                self._blinking = 0.13
                self._blink_timer = random.uniform(2.0, 5.5)

        if self.sleeping:
            return

        # --- 状态变差时立刻出声 ---
        mood = self._mood_key()
        if mood != self._last_mood:
            self._last_mood = mood
            if mood in ("hungry", "unhappy", "sleepy", "critical") and self._say_timer <= 0:
                self._say(*self._pick_idle_line())
                self._idle_talk_timer = random.uniform(9.0, 16.0)

        # --- 待机闲聊 ---
        self._idle_talk_timer -= dt
        if self._idle_talk_timer <= 0:
            self._idle_talk_timer = random.uniform(11.0, 20.0)
            if self._say_timer <= 0:
                self._say(*self._pick_idle_line())

        # --- 待机小动作（闲着无聊时自己动一动，而不是只有呼吸）---
        if self.reaction_timer > 0:
            # 刚互动完，先让她把互动动作做完
            self._antic_timer = max(self._antic_timer, 1.4)
        else:
            self._antic_timer -= dt
            if self._antic_timer <= 0 and not self.motion.playing:
                self._play_antic()

    # ---------- 待机小动作 ----------
    def _play_antic(self):
        """按当前心情挑一个小动作播。表和权重都在 config.PET_ANTICS。"""
        ids = PET_MOOD_ANTICS.get(self.emotion)
        if ids:
            pool = [PET_ANTIC_MAP[i] for i in ids if i in PET_ANTIC_MAP]
        else:
            pool = PET_ANTICS
        spec = weighted_choice(pool)
        if not spec:
            self._antic_timer = random.uniform(*ANTIC_FIRST_GAP)
            return

        self._antic_timer = random.uniform(*spec.get("next", (7.0, 12.0)))
        self.motion.play(spec["motion"], random.uniform(*spec.get("dur", (1.5, 1.9))),
                         flip=random.choice((-1, 1)))      # 有时往左歪，有时往右歪

        if spec.get("effect"):
            self.pending_effects.append(spec["effect"])
        if spec.get("speech") and self._say_timer <= 0:
            self.say(random.choice(SPEECH[spec["speech"]]), 1.7)

    def take_effects(self) -> list:
        """取走积累的特效请求（main.py 每帧调一次）。"""
        out = self.pending_effects
        self.pending_effects = []
        return out

    # ---------- 心情分类 ----------
    def _mood_key(self) -> str:
        if self.sleeping:
            return "sleep"
        if self.min_stat < 12.0:
            return "critical"
        if self.min_stat < LOW_THRESHOLD:
            return "hungry" if self.hunger <= self.happiness else "unhappy"
        if self.energy < 18.0:
            return "sleepy"
        if self.hunger < MID_THRESHOLD:
            return "hungry"
        if self.happiness < MID_THRESHOLD:
            return "unhappy"
        return "ok"

    def _pick_idle_line(self):
        mood = self._mood_key()
        pool = SPEECH["critical"] if mood == "critical" else SPEECH.get(mood, SPEECH["idle"])
        return random.choice(pool), 2.6

    # =====================================================
    #  互动（表驱动：逻辑来自 config.INTERACTIONS）
    # =====================================================
    def cooldown(self, action_id: str) -> float:
        return self._cooldowns.get(action_id, 0.0)

    def can_interact(self, action_id: str) -> bool:
        """按钮是否可点（睡着时除"睡觉/叫醒"外全部不可用）。"""
        spec = INTERACTION_MAP.get(action_id)
        if spec is None:
            return False
        if action_id == "sleep":
            return True                       # 睡着时变成"叫醒"，始终可点
        if self.sleeping:
            return False
        if self.cooldown(action_id) > 0:
            return False
        for key, need in spec.get("require", {}).items():
            if self.get_stat(key) < need:
                return False
        return True

    def interact(self, action_id: str):
        """
        执行一次互动。
        返回 dict(action, gained, effect, woke, sleeping)，不可执行时返回 None。
        gained 是"实际"增减量（可能因上限而被截断）。
        """
        spec = INTERACTION_MAP.get(action_id)
        if spec is None:
            return None

        # ---------- 睡觉：开始 / 叫醒 ----------
        if action_id == "sleep":
            if self.sleeping:
                self.wake_up()
                return dict(action="sleep", gained={}, effect="wake",
                            woke=True, sleeping=False)
            if self.cooldown("sleep") > 0:
                return None
            self._start_sleep()
            return dict(action="sleep", gained={}, effect="sleep",
                        woke=False, sleeping=True)

        # ---------- 其他互动：如果她睡着，先被吵醒再继续 ----------
        woke = self.sleeping
        if woke:
            self.wake_up()

        if self.cooldown(action_id) > 0:
            return None
        for key, need in spec.get("require", {}).items():
            if self.get_stat(key) < need:
                return None

        gained = {}
        for key, delta in spec.get("gain", {}).items():
            before = self.get_stat(key)
            self.set_stat(key, before + delta)
            gained[key] = self.get_stat(key) - before

        self._cooldowns[action_id] = spec.get("cooldown", 0.3)
        self.interaction_count += 1

        react_time = spec.get("react_time", REACTION_TIME)
        if react_time > 0:
            self._react(self.HAPPY, react_time, action_id)

        if action_id == "feed":
            self._chew = 1.1
        elif action_id == "play":
            self._play_bounce = 1.0

        # 互动自带的动作（喂食点头 / 喝水仰头 / 拥抱挤压 / 唱歌摇摆…）
        mo = spec.get("motion")
        if mo:
            self.motion.play(mo[0], mo[1], flip=random.choice((-1, 1)))
            self._antic_timer = max(self._antic_timer, mo[1] + 2.5)

        self.say(random.choice(SPEECH[spec["speech"]]), 1.9)
        return dict(action=action_id, gained=gained, effect=spec["effect"],
                    woke=woke, sleeping=False)

    # ---------- 兼容旧接口 ----------
    def can_feed(self) -> bool:
        return self.can_interact("feed")

    def can_pet(self) -> bool:
        return self.can_interact("pet")

    def feed(self) -> float:
        res = self.interact("feed")
        return res["gained"].get("hunger", 0.0) if res else 0.0

    def pet_action(self) -> float:
        res = self.interact("pet")
        return res["gained"].get("happiness", 0.0) if res else 0.0

    # =====================================================
    #  衣装
    # =====================================================
    @property
    def outfit(self) -> dict:
        """当前衣装的配置字典。"""
        return OUTFIT_MAP.get(self.outfit_id, OUTFITS[0])

    def outfit_unlocked(self, outfit_id: str) -> bool:
        """判断某套衣服是否已达解锁条件（不做缓存，随时可查）。"""
        spec = OUTFIT_MAP.get(outfit_id)
        if spec is None:
            return False
        cond = spec.get("unlock")
        if not cond:
            return True
        if "stat" in cond:
            return self._max_seen.get(cond["stat"], 0.0) >= cond["gte"]
        if "stat_all" in cond:
            return all(v >= cond["stat_all"] for v in self._max_seen.values())
        if "interactions" in cond:
            return self.interaction_count >= cond["interactions"]
        return False

    def available_outfits(self) -> list:
        """当前已解锁的衣服 id 列表（顺序同 config.OUTFITS）。"""
        return [o["id"] for o in OUTFITS if self.outfit_unlocked(o["id"])]

    def set_outfit(self, outfit_id: str, force: bool = False) -> bool:
        """换衣服。未解锁时会失败并返回 False（force=True 可跳过检查）。"""
        if outfit_id not in OUTFIT_MAP:
            return False
        if outfit_id == self.outfit_id:
            return False
        if not force and not self.outfit_unlocked(outfit_id):
            return False
        self.outfit_id = outfit_id
        return True

    def _refresh_unlocks(self):
        """把新达成的解锁条件收进来，并排进待提示队列。"""
        for spec in OUTFITS:
            oid = spec["id"]
            if oid in self.unlocked:
                continue
            if self.outfit_unlocked(oid):
                self.unlocked.add(oid)
                self.pending_unlocks.append(oid)

    def render_thumb(self, outfit_id: str, size=None) -> pygame.Surface:
        """
        衣橱卡片用的小图：把角色整只渲染出来，裁掉多余留白再缩到 size。
        结果带缓存 —— 卡片每帧都在画，不能每帧重新缩一次。
        """
        size = size or CARD_THUMB_SIZE
        key = (outfit_id, size)
        if key in self._thumb_cache:
            return self._thumb_cache[key]

        sprite = self._render(outfit_id=outfit_id, emo=self.NORMAL, blink=False)
        pad = SPRITE_PAD
        crop = pygame.Rect(26 + pad, 10 + pad, 208, 280).clip(sprite.get_rect())
        thumb = pygame.transform.smoothscale(sprite.subsurface(crop).copy(), size)
        self._thumb_cache[key] = thumb
        return thumb

    # ---------- 睡眠 ----------
    def _start_sleep(self):
        self.sleeping = True
        self._sleep_timer = SLEEP_DURATION
        self.reaction_timer = 0.0
        self._play_bounce = 0.0
        self.motion.stop()                 # 睡着就别再乱动了
        self.say(random.choice(SPEECH["sleep"]), 1.6)

    def wake_up(self):
        was = self.sleeping
        self.sleeping = False
        self._sleep_timer = 0.0
        if was:
            self._cooldowns["sleep"] = 0.8
            self._react(self.HAPPY, 1.8, "wake")
            self.say(random.choice(SPEECH["wake"]), 2.0)

    def _react(self, emotion: str, duration: float, kind: str):
        self.reaction_timer = duration
        self.reaction_kind = kind

    def say(self, text: str, duration: float = 2.0):
        self.say_text = text
        self._say_timer = duration

    _say = say

    # =====================================================
    #  ② 表情状态机
    # =====================================================
    @property
    def emotion(self) -> str:
        if self.sleeping:                 # 睡觉优先
            return self.SLEEPING
        if self.reaction_timer > 0:       # 互动中优先显示开心
            return self.HAPPY
        if self.min_stat < LOW_THRESHOLD:
            return self.SAD
        if self.energy < LOW_THRESHOLD:   # 精力见底 → 犯困
            return self.TIRED
        if self.min_stat < MID_THRESHOLD:
            return self.MEH
        return self.NORMAL

    @property
    def _blink_on(self) -> bool:
        return self._blinking > 0 and self.emotion in (self.NORMAL, self.MEH)

    def _tear_drip(self) -> float:
        """泪珠下落的循环进度 0→1。"""
        return (self.anim_time * 1.6) % 1.0

    # =====================================================
    #  ③ 形象绘制
    # =====================================================
    def _render(self, outfit_id: str | None = None,
                emo: str | None = None,
                blink: bool | None = None) -> pygame.Surface:
        """
        生成角色贴图（超采样抗锯齿 + 白色描边），结果带缓存。

        outfit_id / emo / blink 是可选覆盖参数 —— 衣橱里的缩略图就是靠它们
        在同一只宠物上渲染出"别的衣服 / 别的表情"的。
        """
        oid = outfit_id or self.outfit_id
        o = OUTFIT_MAP.get(oid, OUTFITS[0])
        emo = emo or self.emotion
        blink = self._blink_on if blink is None else blink

        eat_frame = int(self._chew * 5) % 2 if self._chew > 0 else -1
        # ⚠️ 角上的泪珠**不进缓存键**（它每帧都在往下滴，进键就等于每秒
        # 重画 8 次角色；一次重画在手机上是几百毫秒 → 直接卡住）。
        # 泪珠改成 draw() 里单独叠一层小图，见 _draw_tear_overlay()。
        key = (oid, emo, blink, eat_frame)
        if key in self._sprite_cache:
            return self._sprite_cache[key]

        k = CHAR_SUPERSAMPLE
        W, H = PET_BOX_W, PET_BOX_H
        canvas = pygame.Surface((W * k, H * k), pygame.SRCALPHA)
        p = Pen(canvas, k)

        self._draw_shadow(p)
        self._draw_hair_back(p)
        self._draw_twintails(p)      # 落在身体后面
        self._draw_body(p, o)
        self._draw_shoes(p, o)
        self._draw_skirt(p, o)       # 裙摆压在鞋子之上
        self._draw_pattern(p, o)     # 图案必须画在裙摆之后，否则会被盖住
        self._draw_arms(p, o)
        self._draw_neck(p)
        self._draw_head(p)
        self._draw_bangs(p)
        self._draw_headwear(p, o)
        self._draw_hair_ties(p, o)
        self._draw_collar(p, o)
        self._draw_sidelocks(p)
        self._draw_blush(p, emo)
        self._draw_face(p, emo, eat_frame)

        # 缩回 1x → 平滑
        sprite = pygame.transform.smoothscale(canvas, (W, H))
        # 加白色描边
        padded = pygame.Surface((W + SPRITE_PAD * 2, H + SPRITE_PAD * 2), pygame.SRCALPHA)
        padded.blit(sprite, (SPRITE_PAD, SPRITE_PAD))
        sprite = _sticker_outline(padded, width=3)

        if len(self._sprite_cache) > 80:
            self._sprite_cache.clear()
        self._sprite_cache[key] = sprite
        return sprite

    # -----------------------------------------------------
    #  身体各部件
    # -----------------------------------------------------
    def _draw_shadow(self, p: Pen):
        breathe = 1.0 + 0.03 * math.sin(self.anim_time * 2.0)
        w = 172 * breathe
        p.soft((196, 176, 200, 60), "ellipse", rect=((260 - w) / 2, 266, w, 26))

    def _draw_hair_back(self, p: Pen):
        p.circle(C_HAIR, (HEAD_CX, HEAD_CY), 82)

    def _draw_twintails(self, p: Pen):
        """双马尾：画在身体之前，所以只从肩后探出来。"""
        for cx in (48, 212):
            p.ellipse(C_HAIR_DARK, (cx - 23, 116, 46, 134))
            p.ellipse(C_HAIR, (cx - 18, 122, 36, 122))
            p.soft((124, 110, 136, 95), "ellipse", rect=(cx - 11, 138, 11, 66))

    # ---------- 衣服：主色 / 版型 / 图案 ----------
    def _draw_body(self, p: Pen, o: dict):
        """上身。四种版型差别就在这里。"""
        style = o["style"]
        cloth, shad = o["cloth"], o["shad"]

        if style == "blouse":                       # 衬衫：直筒下摆
            p.rounded_polygon(cloth, [(104, BODY_TOP), (156, BODY_TOP),
                                      (170, 250), (90, 250)], 9)
            p.soft((shad[0], shad[1], shad[2], 85), "ellipse", rect=(98, 226, 66, 28))
            p.arc(shad, (130, 200), 20, 26, 62, 118, 2.2)
            p.arc(shad, (130, 200), 34, 32, 66, 114, 2.2)

        elif style == "dress":                      # 连衣裙：收腰 + 腰带
            p.rounded_polygon(cloth, [(106, BODY_TOP - 2), (154, BODY_TOP - 2),
                                      (158, 198), (102, 198)], 9)
            p.soft((shad[0], shad[1], shad[2], 70), "ellipse", rect=(104, 176, 52, 24))
            p.rect(o["trim"], (100, 190, 62, 13), radius=6)

        elif style == "sweater":                    # 毛衣：宽松 + 罗纹下摆
            p.rounded_polygon(cloth, [(98, BODY_TOP - 6), (162, BODY_TOP - 6),
                                      (172, 238), (88, 238)], 15)
            for i in range(7):
                x = 99 + i * 12
                p.line(shad, (x, 222), (x, 240), 2.4)
            p.soft((shad[0], shad[1], shad[2], 70), "ellipse", rect=(96, 216, 70, 22))

        elif style == "overall":                    # 背带裙：白 T + 两条背带
            p.rounded_polygon(o["inner"], [(104, BODY_TOP), (156, BODY_TOP),
                                           (168, 240), (92, 240)], 10)
            ish = mix(o["inner"], (206, 208, 218), 0.35)
            p.soft((ish[0], ish[1], ish[2], 90), "ellipse", rect=(100, 224, 62, 24))
            p.rect(cloth, (108, 156, 13, 46), radius=6)
            p.rect(cloth, (139, 156, 13, 46), radius=6)
            p.rounded_polygon(cloth, [(104, 186), (156, 186), (160, 218), (100, 218)], 8)
            p.soft((shad[0], shad[1], shad[2], 62), "ellipse", rect=(106, 196, 48, 18))

    def _draw_skirt(self, p: Pen, o: dict):
        """裙摆。单独一个函数是为了能画在鞋子之上（不会被脚"穿"出来）。"""
        style = o["style"]
        cloth, shad = o["cloth"], o["shad"]

        if style == "dress":                        # 散开的裙摆 + 荷叶边
            p.rounded_polygon(cloth, [(104, 188), (156, 188), (184, 251), (76, 251)], 12)
            for i in range(3):                      # 裙褶（避开两侧的袖子）
                p.arc(shad, (108 + i * 22, 244), 12, 34, 204, 336, 2.2)
            for i in range(7):
                t = i / 6
                p.circle(o["trim"], (79 + t * 102, 247 + math.sin(t * math.pi) * 4), 6)

        elif style == "overall":                    # 背带裙裙摆 + 小口袋
            p.rounded_polygon(cloth, [(98, 208), (162, 208), (178, 250), (82, 250)], 12)
            p.soft((shad[0], shad[1], shad[2], 70), "ellipse", rect=(88, 232, 84, 18))
            p.rounded_polygon(mix(cloth, (255, 255, 255), 0.35),
                              [(118, 214), (142, 214), (144, 234), (116, 234)], 5)
            p.circle(o["accent"], (114, 195), 3.4)
            p.circle(o["accent"], (146, 195), 3.4)

    def _draw_pattern(self, p: Pen, o: dict):
        """衣服上的小图案，纯装饰，用来拉开几套衣服的辨识度。"""
        kind = o["pattern"]
        if kind == "none":
            return
        acc = o["accent"]
        # 各版型"能露出图案"的区间不一样，这里整体上下挪一挪
        dy = {"dress": 12, "overall": 6}.get(o["style"], 0)

        if kind == "star":
            for cx, cy, r in ((113, 200, 9), (147, 212, 7), (126, 226, 6)):
                cy += dy
                pts = []
                for i in range(10):
                    a = -math.pi / 2 + i * math.pi / 5
                    rr = r * (1.0 if i % 2 == 0 else 0.44)
                    pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
                p.polygon(acc, pts)

        elif kind == "flower":
            for cx, cy, r in ((115, 202, 8), (146, 214, 6), (126, 228, 5)):
                cy += dy
                for i in range(5):
                    a = -math.pi / 2 + i * math.tau / 5
                    p.circle(acc, (cx + math.cos(a) * r, cy + math.sin(a) * r), r * 0.62)
                p.circle(mix(acc, (255, 255, 255), 0.45), (cx, cy), r * 0.34)

        elif kind == "bear":
            cx, cy = 130, 212 + dy
            for dx in (-14, 14):
                p.circle(acc, (cx + dx, cy - 15), 7.5)
                p.circle(mix(acc, (255, 255, 255), 0.5), (cx + dx, cy - 15), 3.8)
            p.circle(acc, (cx, cy), 21)
            p.circle(mix(acc, (255, 255, 255), 0.55), (cx, cy + 5), 13)
            p.circle((72, 58, 48), (cx - 5.5, cy), 2.4)
            p.circle((72, 58, 48), (cx + 5.5, cy), 2.4)
            p.ellipse((72, 58, 48), (cx - 3.6, cy + 5, 7.2, 5.2))

    def _draw_shoes(self, p: Pen, o: dict):
        shoe = o["shoe"]
        sole = mix(shoe, (128, 116, 136), 0.34)
        for cx in (111, 149):
            p.ellipse(shoe, (cx - 22, 254, 44, 26))
            p.soft((255, 255, 255, 130), "ellipse", rect=(cx - 15, 258, 18, 8))
            p.arc(sole, (cx, 258), 20, 8, 15, 165, 2.2)

    def _draw_arms(self, p: Pen, o: dict):
        """袖子跟着衣服走；背带裙的袖子是里面那件白 T。"""
        if o["style"] == "overall":
            sleeve = o["inner"]
            shad = mix(o["inner"], (202, 206, 218), 0.30)
        else:
            sleeve, shad = o["cloth"], o["shad"]
        for cx in ARM_CX:
            p.ellipse(sleeve, (cx - 13, 168, 26, 60))
            p.ellipse(shad, (cx - 13, 208, 26, 20))
            p.circle(C_SKIN, (cx, HAND_Y), 10.5)
            p.soft((238, 200, 188, 120), "circle", center=(cx, HAND_Y + 4), r=5)

    def _draw_neck(self, p: Pen):
        p.rect(C_SKIN, (117, 138, 26, 34), radius=9)
        p.soft((236, 198, 186, 130), "rect", rect=(117, 138, 26, 14), radius=7)

    def _draw_head(self, p: Pen):
        p.circle(C_SKIN, (HEAD_CX, HEAD_CY), HEAD_R)
        p.circle(C_SKIN, (62, 112), 11)     # 耳朵
        p.circle(C_SKIN, (198, 112), 11)
        p.soft((240, 208, 196, 90), "ellipse", rect=(82, 130, 96, 38))

    def _draw_bangs(self, p: Pen):
        # 主刘海
        p.ellipse(C_HAIR, (58, 20, 144, 88))
        # 碎发：一排下垂的圆润发绺
        for i in range(6):
            cx = 76 + i * 21.6
            drop = 34 + (5 if i % 2 == 0 else 0)
            p.ellipse(C_HAIR, (cx - 14, 78, 28, drop))
        # 头顶高光
        p.soft((130, 116, 142, 115), "ellipse", rect=(86, 36, 88, 18))
        p.soft((130, 116, 142, 70), "ellipse", rect=(150, 50, 40, 13))
        # 呆毛
        p.line(C_HAIR, (128, 22), (120, 8), 5)
        p.line(C_HAIR, (120, 8), (132, 1), 4)

    def _draw_headwear(self, p: Pen, o: dict):
        """发饰 / 头饰。六种造型，靠 o["pin"] 切换。"""
        pin = o["pin"]
        main, acc = o["pin_main"], o["pin_accent"]

        if pin == "bear":                            # 连体服的兜帽熊耳
            for cx in (98, 162):
                p.circle(mix(main, (152, 112, 82), 0.40), (cx, 37), 22)
                p.circle(main, (cx, 38), 19)
                p.circle(mix(main, (255, 255, 255), 0.62), (cx, 40), 10)
            return

        if pin in ("flower", "sakura"):
            cx, cy = 184, 56
            if pin == "sakura":
                # 樱花：花瓣尖端带个小缺口 → 一眼和小雏菊区分开
                r = 10.5
                for i in range(5):
                    a = -math.pi / 2 + i * math.tau / 5
                    p.circle(main, (cx + math.cos(a) * r, cy + math.sin(a) * r), r * 0.74)
                    p.circle(C_HAIR, (cx + math.cos(a) * r * 1.50,
                                      cy + math.sin(a) * r * 1.50), r * 0.25)
                p.circle(acc, (cx, cy), 3.8)
                for i in range(5):
                    a = -math.pi / 2 + (i + 0.5) * math.tau / 5
                    p.circle(mix(acc, (255, 226, 140), 0.65),
                             (cx + math.cos(a) * 4.2, cy + math.sin(a) * 4.2), 1.5)
            else:
                r = 9
                for i in range(5):
                    a = -math.pi / 2 + i * math.tau / 5
                    p.circle(main, (cx + math.cos(a) * r, cy + math.sin(a) * r), r * 0.78)
                p.circle(acc, (cx, cy), 4.8)
                p.circle(mix(acc, (255, 255, 255), 0.6), (cx - 1.4, cy - 1.4), 1.9)

        elif pin == "star":                          # 星星
            cx, cy = 186, 54
            pts = []
            for i in range(10):
                a = -math.pi / 2 + i * math.pi / 5
                rr = 12 if i % 2 == 0 else 5
                pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
            p.polygon(main, pts)
            p.circle(acc, (cx, cy), 3)

        elif pin == "moon":                          # 弯月（用发色"挖"出缺口）
            cx, cy, r = 186, 54, 11
            p.circle(main, (cx, cy), r)
            p.circle(C_HAIR, (cx + r * 0.56, cy - r * 0.16), r * 0.86)
            p.circle(acc, (cx - 3.6, cy + 3.2), 2.4)

        elif pin == "ribbon":                        # 小蝴蝶结发夹
            cx, cy = 186, 56
            p.ellipse(main, (cx - 16, cy - 8, 16, 16))
            p.ellipse(main, (cx, cy - 8, 16, 16))
            p.circle(acc, (cx, cy), 4.2)

    def _draw_hair_ties(self, p: Pen, o: dict):
        tie = o["tie"]
        deep = mix(tie, (60, 40, 60), 0.24)
        for cx in (54, 206):
            p.circle(tie, (cx, 126), 10.5)
            p.circle(deep, (cx, 126), 10.5, 3)
            p.circle(mix(tie, (255, 255, 255), 0.55), (cx - 3.4, 122.6), 3.1)

    def _draw_collar(self, p: Pen, o: dict):
        """领口。四种版型各有一套：蕾丝领 / 圆领 / 高领 / 白 T 领。"""
        style = o["style"]
        bow = o["bow"]

        if style == "blouse":                        # 蕾丝领 + 领口蝴蝶结
            base = mix(o["trim"], (255, 255, 255), 0.42)
            p.rounded_polygon(base, [(110, 170), (150, 170), (164, 202), (96, 202)], 8)
            for i in range(9):
                t = i / 8
                p.circle((255, 255, 255), (96 + t * 68, 198 + math.sin(t * math.pi) * 7), 7)
            for i in range(8):
                t = (i + 0.5) / 8
                p.circle(base, (100 + t * 60, 184 + math.sin(t * math.pi) * 4), 2.3)
            p.arc(o["trim"], (130, 176), 24, 15, 24, 156, 2.2)

        elif style == "dress":                       # 圆领
            p.ellipse(o["trim"], (103, 170, 54, 22))
            p.ellipse(mix(o["trim"], (255, 255, 255), 0.55), (110, 174, 40, 14))

        elif style == "sweater":                     # 高领罗纹
            p.ellipse(o["trim"], (104, 170, 52, 26))
            p.ellipse(o["cloth"], (111, 175, 38, 18))

        elif style == "overall":                     # 白 T 的领口弧
            p.arc(mix(o["inner"], (196, 200, 212), 0.5), (130, 172), 21, 13, 196, 344, 3)

        if bow:                                      # 领口蝴蝶结（背带裙没有）
            deep = mix(bow, (60, 40, 60), 0.18)
            light = mix(bow, (255, 255, 255), 0.6)
            p.ellipse(bow, (113, 172, 18, 16))
            p.ellipse(bow, (130, 172, 18, 16))
            p.circle(deep, (130.5, 180), 5.4)
            p.circle(light, (128.8, 178.4), 1.9)

    def _draw_sidelocks(self, p: Pen):
        """垂在脸颊两侧的长发。"""
        for cx in (72, 188):
            p.ellipse(C_HAIR, (cx - 15, 88, 30, 98))
            p.soft((124, 110, 136, 85), "ellipse", rect=(cx - 9, 110, 9, 48))

    def _draw_blush(self, p: Pen, emo: str):
        alpha = {self.HAPPY: 168, self.NORMAL: 105, self.MEH: 85, self.SAD: 132,
                 self.SLEEPING: 118, self.TIRED: 96}.get(emo, 105)
        rx = 16 if emo == self.HAPPY else 14
        for cx in (88, 172):
            p.soft((C_BLUSH[0], C_BLUSH[1], C_BLUSH[2], alpha),
                   "ellipse", rect=(cx - rx, BLUSH_Y, rx * 2, 14))
        if emo in (self.HAPPY, self.SAD):
            p.soft((C_BLUSH[0], C_BLUSH[1], C_BLUSH[2], 80),
                   "ellipse", rect=(123, BLUSH_Y + 6, 14, 8))

    # -----------------------------------------------------
    #  五官
    # -----------------------------------------------------
    def _draw_face(self, p: Pen, emo: str, eat_frame: int):
        lx, rx, ey = EYE_LX, EYE_RX, EYE_Y

        # ---- 眼睛 ----
        if emo == self.SLEEPING:                                   # 闭眼（安睡）
            for cx in (lx, rx):
                p.arc(C_EYE, (cx, ey - 2), 13, 9, 22, 158, 4.6)
        elif self._blink_on:
            for cx in (lx, rx):
                p.arc(C_EYE, (cx, ey), 14, 7.5, 180, 360, 5)
        elif emo == self.HAPPY:
            for cx in (lx, rx):                                   # "⌒⌒" 笑眼
                p.arc(C_EYE, (cx, ey + 3), 15, 11, 180, 360, 6)
            p.arc(C_EYE, (lx, ey + 14), 8, 4.5, 190, 350, 2.4)    # 笑纹
            p.arc(C_EYE, (rx, ey + 14), 8, 4.5, 190, 350, 2.4)
        elif emo == self.TIRED:                                    # 眼皮耷拉
            w, h, dy = 12.5, 14.0, 3.0
            for cx in (lx, rx):
                p.ellipse(C_EYE, (cx - w, ey - h + dy, w * 2, h * 2))
                p.circle((255, 255, 255), (cx - w * 0.32, ey + h * 0.24 + dy), w * 0.25)
                p.circle((255, 255, 255), (cx + w * 0.30, ey + h * 0.54 + dy), w * 0.12)
            # 同色"上眼皮"压住瞳孔上半截 → 一眼看出半睁的困倦眼
            for cx in (lx, rx):
                p.rect(C_EYE, (cx - w - 1.4, ey - h + dy - 0.8,
                               w * 2 + 2.8, h * 0.56 + 0.8), radius=2.6)
            # 眼角一道下垂的困纹
            p.arc(C_HAIR, (lx - 3, ey + 9), 10, 5.5, 200, 340, 2.6)
            p.arc(C_HAIR, (rx + 3, ey + 9), 10, 5.5, 200, 340, 2.6)
        else:
            if emo == self.MEH:
                w, h, dy = 12.5, 14.5, 1
            elif emo == self.SAD:
                w, h, dy = 11.5, 11.5, 5        # 眼睛变小并下垂 → 无精打采
            else:
                w, h, dy = 13, 15.5, 0
            for cx in (lx, rx):
                p.ellipse(C_EYE, (cx - w, ey - h + dy, w * 2, h * 2))
                p.circle((255, 255, 255), (cx - w * 0.34, ey - h * 0.46 + dy), w * 0.33)
                p.circle((255, 255, 255), (cx + w * 0.34, ey + h * 0.30 + dy), w * 0.15)
                if emo == self.SAD:         # 眼眶里打转的泪光
                    p.soft((176, 218, 245, 140), "ellipse",
                           rect=(cx - w + 1, ey + h + dy - 4, w * 2 - 2, 6))
            p.arc(C_EYE, (lx, ey + 7), w + 3, h + 2, 40, 140, 2)   # 下睫毛
            p.arc(C_EYE, (rx, ey + 7), w + 3, h + 2, 40, 140, 2)

        # ---- 眉毛 ----
        if emo == self.SAD:                                        # 八字眉
            p.line(C_HAIR, (82, 119), (119, 103), 6)
            p.line(C_HAIR, (178, 119), (141, 103), 6)
        elif emo == self.HAPPY:
            p.arc(C_HAIR, (lx, 116), 14, 7.5, 200, 340, 3)
            p.arc(C_HAIR, (rx, 116), 14, 7.5, 200, 340, 3)

        # ---- 嘴巴 ----
        if emo == self.SLEEPING:                                   # 安睡的小嘴
            p.arc(C_MOUTH, (130, MOUTH_Y - 1), 8, 5.5, 25, 155, 3.2)
        elif eat_frame >= 0:                                       # 咀嚼
            rr = 8.5 if eat_frame == 0 else 4.5
            p.ellipse(C_MOUTH, (130 - rr, MOUTH_Y - rr * 0.7, rr * 2, rr * 1.5))
            p.soft((C_TONGUE[0], C_TONGUE[1], C_TONGUE[2], 220),
                   "ellipse", rect=(130 - rr * 0.6, MOUTH_Y + 2, rr * 1.2, rr * 0.8))
        elif emo == self.HAPPY:                                    # 张嘴笑
            pts = _arc_pts(130, MOUTH_Y - 6, 17, 13, 8, 172, 26)
            pts += [(130 - 17, MOUTH_Y - 6), (130 + 17, MOUTH_Y - 6)]
            p.polygon(C_MOUTH, pts)
            p.soft((C_TONGUE[0], C_TONGUE[1], C_TONGUE[2], 235),
                   "ellipse", rect=(120, MOUTH_Y - 3, 20, 10))
            p.arc(C_MOUTH, (130, MOUTH_Y - 2), 19, 15, 190, 350, 2.2)
        elif emo == self.SAD:                                      # 撇嘴
            p.arc(C_MOUTH, (130, MOUTH_Y + 11), 15, 7.5, 205, 335, 4)
        elif emo == self.TIRED:                                    # 打哈欠的小圆嘴
            p.ellipse(C_MOUTH, (124, MOUTH_Y + 1, 12, 9))
            p.soft((C_TONGUE[0], C_TONGUE[1], C_TONGUE[2], 200),
                   "ellipse", rect=(126.5, MOUTH_Y + 5, 7, 5))
        elif emo == self.MEH:
            p.line(C_MOUTH, (121, MOUTH_Y + 8), (139, MOUTH_Y + 8), 3.6)
        else:                                                      # 微笑
            p.arc(C_MOUTH, (130, MOUTH_Y + 2), 12, 9, 22, 158, 4)

    def _draw_tear_overlay(self, surface, cx, sx, scale, stable_top):
        """
        眼角往下滴的泪珠 —— 单独叠一层，**不进角色贴图缓存**。

        (cx, sx, scale, stable_top) 是 draw() 里算出来的同一套映射参数，
        所以泪珠会跟着角色的缩放/位移走（难过时角色不旋转，忽略旋转没问题）。
        """
        drip = self._tear_drip()
        fade = int(215 * (1 - drip))
        if fade <= 8:
            return
        lx = cx + (150 - PET_BOX_W / 2) * sx
        ly = stable_top + (152 + drip * 26 + SPRITE_PAD) * scale
        w = max(2, int(11 * sx))
        h = max(2, int(15 * scale))
        layer = pygame.Surface((w + 4, h + 4), pygame.SRCALPHA)
        pygame.draw.ellipse(layer, (*C_TEAR, fade), pygame.Rect(2, 2, w, h))
        pygame.draw.ellipse(layer, (255, 255, 255, fade // 2),
                            pygame.Rect(2 + max(1, int(w * 0.25)),
                                        2 + max(1, int(h * 0.25)),
                                        max(1, int(w * 0.33)),
                                        max(1, int(h * 0.23))))
        surface.blit(layer, (int(lx), int(ly)))

    # -----------------------------------------------------
    #  对外绘制入口
    # -----------------------------------------------------
    def draw(self, surface: pygame.Surface):
        sprite = self._render()
        full_h = PET_BOX_H + SPRITE_PAD * 2

        t = self.anim_time
        emo = self.emotion

        # 呼吸 / 跳跃动画
        if emo == self.HAPPY:
            jump = abs(math.sin(t * 6.2)) * 11
            squash = 1.0 + 0.045 * math.sin(t * 12.4)
        elif emo == self.SLEEPING:
            jump = 0.0
            squash = 1.0 + 0.022 * math.sin(t * 1.5)      # 缓慢平稳的呼吸
        elif emo == self.TIRED:
            jump = 1.0 + math.sin(t * 1.3) * 3.0          # 一点点打盹点头
            squash = 0.992
        elif emo == self.SAD:
            jump = 2.0 + math.sin(t * 1.6) * 2.0
            squash = 0.985
        else:
            jump = math.sin(t * 2.0) * 3.5
            squash = 1.0

        jump += (self._play_bounce ** 2) * 15             # 玩耍时的额外弹跳

        base = Pose(dy=-jump, sx=1.0 / squash, sy=squash)

        # ---- 叠加动作曲线（伸懒腰 / 蹦跳 / 转圈…），两者相加 ----
        pose = base + self.motion.pose()

        # 让"角色脚底"稳稳落在地面线上（画布 y=300 为基准）
        foot_y = int(self.y + PET_BOX_H / 2) + SPRITE_PAD + pose.dy
        rect, pre_h = posed_blit(surface, sprite,
                                 self.x + pose.dx, foot_y, pose)
        self.box_rect = rect

        # 记录头顶 / 嘴巴的屏幕坐标，供特效使用。
        # 用"缩放后、旋转前"的盒子换算 —— 转圈时不至于把气泡甩出去。
        scale = pre_h / full_h
        stable_top = foot_y - pre_h
        sx = rect.width / float(PET_BOX_W + SPRITE_PAD * 2)

        def sy(local_y):
            return stable_top + (local_y + SPRITE_PAD) * scale

        self.head_pos = (int(self.x + pose.dx), sy(26))
        self.mouth_pos = (int(self.x + pose.dx), sy(MOUTH_Y))

        # 难过时眼角滴的泪 —— 单独叠加，不参与贴图缓存
        if emo == self.SAD:
            self._draw_tear_overlay(surface, self.x + pose.dx, sx, scale,
                                    stable_top)

        if self._say_timer > 0 and self.say_text:
            self._draw_bubble(surface, self.say_text, rect)

    def _draw_bubble(self, surface, text: str, char_rect: pygame.Rect):
        font = get_font(17)
        img = font.render(text, True, TEXT)
        pad_x, pad_y = 16, 10
        w = img.get_width() + pad_x * 2
        h = img.get_height() + pad_y * 2

        alpha = int(255 * clamp(self._say_timer / 0.3, 0, 1))
        bx = int(clamp(char_rect.centerx - w / 2, 10, WIDTH - w - 10))
        by = char_rect.top - h - 10 + int(math.sin(self.anim_time * 2.6) * 3)

        layer = pygame.Surface((w, h + 12), pygame.SRCALPHA)
        pygame.draw.rect(layer, (255, 255, 255, int(alpha * 0.96)),
                         pygame.Rect(0, 0, w, h), border_radius=16)
        pygame.draw.rect(layer, (*PANEL_EDGE, alpha),
                         pygame.Rect(0, 0, w, h), 2, border_radius=16)
        pygame.draw.polygon(layer, (255, 255, 255, int(alpha * 0.96)), [
            (w // 2 - 9, h - 2), (w // 2 + 9, h - 2), (w // 2, h + 11)])
        img.set_alpha(alpha)
        layer.blit(img, (pad_x, pad_y))
        surface.blit(layer, (bx, by))
