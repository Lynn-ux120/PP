# -*- coding: utf-8 -*-
"""
main.py —— 游戏主循环 & 场景组装
=========================================================
运行：  python main.py

结构：
  build_background()  预渲染静态背景（渐变天空 / 草地 / 装饰 / 面板）
  build_buttons()     按 config.INTERACTIONS 自动生成按钮网格
  Cloud               飘动的云
  Game                事件 → 逻辑 → 绘制 的主循环
                      ＋ 衣橱（模态面板，见 open_wardrobe / _draw_wardrobe）
                      ＋ 小宠物（companion.Companion，面板见 open_comp_panel）

【加互动只需要改 config.INTERACTIONS】
按钮会自动生成、快捷键会自动绑定；只有新特效才需要动本文件的
_spawn_effect()。

【加衣装只需要改 config.OUTFITS】
卡片、缩略图、解锁判断都会自动生成。

【加小宠物只需要改 config.COMPANIONS / COMPANION_ACTIONS】
卡片、按钮、解锁判断、快捷键都会自动生成。
"""
from __future__ import annotations

import math
import random
import sys

import pygame

from config import *
from utils import get_font, text_at, clamp, mix, draw_panel
from effects import ParticleSystem
from ui import Button, StatBar, make_icon
from pet import Pet
from companion import Companion
from platform_util import DisplayManager, is_back_key, setup_android


# =========================================================
#  背景
# =========================================================
def _ground_top(x: float) -> float:
    """草地起伏的顶边曲线（背景、角色、小宠物共用同一条地面）。"""
    return ground_top(x)


def _glow_circle(layer, color, center, r, alpha, rings=14):
    """用同心圆叠加做出柔和的光晕（越靠中心越亮）。"""
    step = max(1, int(r / rings))
    for rr in range(int(r), 0, -step):
        pygame.draw.circle(layer, (*color, max(1, alpha // rings)), center, rr)


def build_background() -> pygame.Surface:
    surf = pygame.Surface((WIDTH, HEIGHT))

    # ---------- 渐变天空 ----------
    span = GROUND_Y + 12
    for y in range(span):
        surf.fill(mix(BG_TOP, BG_BOTTOM, y / span), pygame.Rect(0, y, WIDTH, 1))

    # ---------- 背景柔光斑 ----------
    layer = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    for cx, cy, r, col, a in [
        (92, 262, 84, BOKEH_1, 120), (548, 232, 96, BOKEH_2, 110),
        (206, 392, 64, BOKEH_3, 130), (462, 442, 58, BOKEH_1, 120),
        (104, 486, 50, BOKEH_2, 110), (598, 528, 70, BOKEH_3, 120),
    ]:
        _glow_circle(layer, col, (cx, cy), r, a)
    surf.blit(layer, (0, 0))

    # ---------- 草地 ----------
    top_pts = [(x, _ground_top(x)) for x in range(0, WIDTH + 1, 6)]
    pygame.draw.polygon(surf, GROUND, top_pts + [(WIDTH, HEIGHT), (0, HEIGHT)])
    deep_pts = [(x, _ground_top(x) + 18) for x in range(0, WIDTH + 1, 6)]
    pygame.draw.polygon(surf, GROUND_DEEP, deep_pts + [(WIDTH, HEIGHT), (0, HEIGHT)])
    # 草地边缘
    pygame.draw.lines(surf, GRASS_LINE, False, top_pts, 3)

    # ---------- 草地装饰（固定随机种子，保证每次一致） ----------
    rng = random.Random(20261002)

    def _ground_y(x):
        return _ground_top(x)

    # 草丛
    for _ in range(26):
        x = rng.uniform(8, WIDTH - 8)
        y = _ground_y(x) + rng.uniform(4, 34)
        h = rng.uniform(7, 13)
        for d in (-1, 0, 1):
            pygame.draw.line(surf, GRASS_LINE, (x + d * 4, y), (x + d * 6, y - h), 2)

    # 小石子
    for _ in range(7):
        x = rng.uniform(20, WIDTH - 20)
        y = _ground_y(x) + rng.uniform(14, 42)
        pygame.draw.ellipse(surf, (232, 230, 240),
                            pygame.Rect(x, y, rng.uniform(7, 12), rng.uniform(4, 6)))

    # 小花
    for _ in range(11):
        x = rng.uniform(24, WIDTH - 24)
        y = _ground_y(x) + rng.uniform(6, 30)
        col = rng.choice([PINK, (255, 255, 255), LILAC, PINK_SOFT, (255, 236, 200)])
        pygame.draw.line(surf, GRASS_LINE, (x, y + 8), (x, y), 2)
        for i in range(5):
            a = -math.pi / 2 + i * math.tau / 5
            pygame.draw.circle(surf, col, (int(x + math.cos(a) * 4), int(y + math.sin(a) * 4)), 3)
        pygame.draw.circle(surf, BUTTER, (int(x), int(y)), 2)

    # ---------- 标题 ----------
    text_at(surf, "高紫桐的小屋", (WIDTH // 2, 44), size=33, color=TEXT,
            bold=True, center=True, shadow=(255, 255, 255))
    text_at(surf, "喂饱她 · 陪她玩 · 别让她累着～", (WIDTH // 2, 74),
            size=15, color=TEXT_LIGHT, center=True)
    for dx, col in ((-172, PINK), (172, LILAC)):
        ic = make_icon("heart", 16, col)
        surf.blit(ic, ic.get_rect(center=(WIDTH // 2 + dx, 42)))

    # ---------- 面板 ----------
    draw_panel(surf, STAT_PANEL_RECT, radius=28)
    draw_panel(surf, BTN_PANEL_RECT, radius=30)
    return surf


# =========================================================
#  按钮网格
# =========================================================
def build_buttons():
    """按 config.INTERACTIONS 自动排布按钮，返回 [(Button, spec), ...]。"""
    buttons = []
    for i, spec in enumerate(INTERACTIONS):
        col = i % BTN_COLS
        row = i // BTN_COLS
        x = BTN_GRID_LEFT + col * (BTN_W + BTN_GAP_X)
        y = BTN_GRID_TOP + row * (BTN_H + BTN_GAP_Y)
        base, hover, edge, text_c, icon_c = spec["btn"]
        buttons.append((
            Button((x, y, BTN_W, BTN_H), spec["label"], base, hover, edge, text_c,
                   icon=spec["icon"], icon_color=icon_c,
                   hotkey=spec["hotkey"], radius=18),
            spec,
        ))
    return buttons


# =========================================================
#  飘云
# =========================================================
class Cloud:
    def __init__(self, x, y, scale, speed, alpha):
        self.x, self.y = x, y
        self.scale = scale
        self.speed = speed
        self.alpha = alpha

    def update(self, dt):
        self.x += self.speed * dt
        if self.x - 200 * self.scale > WIDTH:
            self.x = -200 * self.scale

    def draw(self, surface):
        s = self.scale
        w, h = 130 * s, 44 * s
        pad = 30 * s
        layer = pygame.Surface((int(w + pad * 2), int(h + pad * 2)), pygame.SRCALPHA)
        ox, oy = pad, pad
        col = (255, 255, 255, self.alpha)
        pygame.draw.ellipse(layer, col, pygame.Rect(ox, oy + h * 0.42, w, h * 0.72))
        pygame.draw.circle(layer, col, (int(ox + w * 0.28), int(oy + h * 0.52)), int(h * 0.70))
        pygame.draw.circle(layer, col, (int(ox + w * 0.55), int(oy + h * 0.34)), int(h * 0.92))
        pygame.draw.circle(layer, col, (int(ox + w * 0.80), int(oy + h * 0.56)), int(h * 0.62))
        surface.blit(layer, (self.x - pad, self.y - pad))


# =========================================================
#  游戏
# =========================================================
class Game:
    def __init__(self):
        pygame.init()

        # ---------- 显示：逻辑画布始终是 640x800，桌面窗口 / 手机全屏自动适配 ----------
        # 桌面窗口尺寸刚好等于逻辑尺寸时 scale==1，表现和改造前完全一致；
        # 手机上则等比放大铺满屏幕，信箱区域用背景渐变补上。
        self.display = DisplayManager(
            (WIDTH, HEIGHT), TITLE,
            fullscreen=FULLSCREEN_MODE,
            smooth=MOBILE_SMOOTH_SCALE,
            gradient=(BG_TOP, BG_BOTTOM))
        self.window = self.display.window       # 真实窗口（手机上比逻辑画布大）
        self.screen = self.display.logical      # ← 所有绘制都画在它上面
        self.android_status = setup_android()   # 屏幕常亮 + 沉浸式（桌面返回 False）

        self.clock = pygame.time.Clock()
        self.running = True
        self.time = 0.0

        # 场景
        self.bg = build_background()
        self.clouds = [
            Cloud(-60, 232, 1.00, 11, 200),
            Cloud(300, 286, 0.72, 16, 165),
            Cloud(560, 212, 0.86, 8, 185),
        ]

        # 角色 & 特效
        self.pet = Pet(PET_NAME)
        self.particles = ParticleSystem()
        self._zzz_timer = 0.0
        self._czzz_timer = 0.0

        # 数值条（顺序对应 STAT_KEYS）
        self.bars = {
            "hunger": StatBar(STAT_ROWS[0], "饱腹值", "bowl",
                              BAR_HUNGER_FG, BAR_HUNGER_BG, BUTTER_DEEP),
            "happiness": StatBar(STAT_ROWS[1], "快乐值", "heart",
                                 BAR_HAPPY_FG, BAR_HAPPY_BG, PINK_DEEP),
            "energy": StatBar(STAT_ROWS[2], "精力值", "drop",
                              BAR_ENERGY_FG, BAR_ENERGY_BG, SKY_DEEP),
        }

        # 按钮（自动生成）
        self.buttons = build_buttons()

        # ---------- 衣橱 ----------
        self.wardrobe_btn = Button(
            WARDROBE_BTN_RECT, "衣装", (255, 240, 246), (255, 250, 252),
            (242, 194, 218), (150, 98, 128),
            icon="hanger", icon_color=(238, 150, 190), radius=13)
        self.wardrobe_open = False
        self.wardrobe_hover = None
        self.wardrobe_msg = ""
        self.wardrobe_msg_t = 0.0
        self._wear_flash = 0.0            # 换装瞬间全屏柔光

        # 卡片矩形（按 config.OUTFITS 自动排布）
        self.cards = []
        gw = CARD_COLS * CARD_W + (CARD_COLS - 1) * CARD_GAP_X
        gx = WARDROBE_PANEL[0] + (WARDROBE_PANEL[2] - gw) // 2
        for i, spec in enumerate(OUTFITS):
            rr, cc = divmod(i, CARD_COLS)
            self.cards.append((
                pygame.Rect(gx + cc * (CARD_W + CARD_GAP_X),
                            WARDROBE_GRID_TOP + rr * (CARD_H + CARD_GAP_Y),
                            CARD_W, CARD_H),
                spec["id"],
            ))

        # ---------- 小宠物 ----------
        self.companion = Companion(COMPANION_START)
        self.comp_panel_open = False
        self.comp_hover = None
        self.comp_msg = ""
        self.comp_msg_t = 0.0
        self._comp_flash = 0.0
        self.comp_btn = Button(
            COMPANION_BTN_RECT, "宠物", (255, 245, 238), (255, 251, 246),
            (240, 208, 188), (150, 104, 82),
            icon="paw", icon_color=(242, 168, 122), radius=13)

        # 宠物种类卡片（按 config.COMPANIONS 自动排布）
        self.comp_cards = []
        cgw = len(COMPANIONS) * COMP_CARD_W + (len(COMPANIONS) - 1) * COMP_CARD_GAP
        cgx = COMPANION_PANEL[0] + (COMPANION_PANEL[2] - cgw) // 2
        for i, spec in enumerate(COMPANIONS):
            self.comp_cards.append((
                pygame.Rect(cgx + i * (COMP_CARD_W + COMP_CARD_GAP),
                            COMPANION_PANEL[1] + COMP_CARD_TOP,
                            COMP_CARD_W, COMP_CARD_H),
                spec["id"],
            ))

        # 宠物操作按钮（投喂 / 逗它 / 抱抱）
        self.comp_actions = []
        caw = (len(COMPANION_ACTIONS) * COMP_ACT_W
               + (len(COMPANION_ACTIONS) - 1) * COMP_ACT_GAP)
        cax = COMPANION_PANEL[0] + (COMPANION_PANEL[2] - caw) // 2
        for i, spec in enumerate(COMPANION_ACTIONS):
            base, hover, edge, text_c, icon_c = spec["btn"]
            self.comp_actions.append((
                Button((cax + i * (COMP_ACT_W + COMP_ACT_GAP),
                        COMPANION_PANEL[1] + COMP_ACT_TOP, COMP_ACT_W, COMP_ACT_H),
                       spec["label"], base, hover, edge, text_c,
                       icon=spec["icon"], icon_color=icon_c,
                       hotkey=spec["hotkey"], radius=16),
                spec,
            ))

        # 宠物快捷键映射（1 / 2 / 3）
        self.comp_key_map = {}
        for spec in COMPANION_ACTIONS:
            key = getattr(pygame, "K_" + spec["hotkey"], None)
            if key is not None:
                self.comp_key_map[key] = spec["id"]

        # 快捷键映射：从配置里自动生成
        self.key_map = {}
        for spec in INTERACTIONS:
            hk = spec.get("hotkey")
            if hk:
                key = getattr(pygame, "K_" + hk.lower(), None)
                if key is not None:
                    self.key_map[key] = spec["id"]

    # ---------------- 互动 ----------------
    def do_action(self, action_id: str):
        res = self.pet.interact(action_id)
        if not res:
            return
        self._spawn_effect(res["effect"])
        self._spawn_gain_text(res["gained"])

    def _spawn_effect(self, effect):
        """把互动结果翻译成粒子表现。新增特效只需要在这里加一个分支。"""
        pet = self.pet
        hp, mp = pet.head_pos, pet.mouth_pos
        spawn_pos = (pet.x, pet.y - 70)

        if effect == "food":
            self.particles.spawn_food(spawn_pos, mp, n=7)
            self.particles.spawn_sparkles(hp, n=4, spread=74)
        elif effect == "water":
            self.particles.spawn_drops((pet.x, pet.y - 60), mp, n=7)
            self.particles.spawn_sparkles(hp, n=3, spread=62)
        elif effect == "heart":
            self.particles.spawn_hearts(hp, n=7, spread=54)
            self.particles.spawn_sparkles(hp, n=3, spread=86)
        elif effect == "hug":
            self.particles.spawn_hearts(hp, n=9, spread=82, scale=1.45)
            self.particles.spawn_sparkles(hp, n=4, spread=94)
        elif effect == "play":
            self.particles.spawn_sparkles(hp, n=13, spread=100)
            self.particles.spawn_hearts(hp, n=3, spread=70, scale=0.85)
        elif effect == "music":
            self.particles.spawn_notes(hp, n=7, spread=56)
            self.particles.spawn_sparkles(hp, n=4, spread=80)
        elif effect == "bubble":
            self.particles.spawn_bubbles(hp, n=14, spread=64)
        elif effect == "sleep":
            self.particles.spawn_zzz(hp)
            self.particles.spawn_hearts(hp, n=3, spread=44, scale=0.8)
        elif effect == "wake":
            self.particles.spawn_sparkles(hp, n=8, spread=76)
        elif effect == "sparkle":                  # 待机小动作的星光点缀
            self.particles.spawn_sparkles(hp, n=7, spread=78)

    def _spawn_gain_text(self, gained):
        """把数值增减显示成角色旁边的飘字（最多两条）。"""
        entries = [(k, v) for k, v in gained.items() if abs(v) >= 0.5]
        if not entries:
            return
        entries.sort(key=lambda kv: -abs(kv[1]))
        for i, (key, val) in enumerate(entries[:2]):
            col = STAT_TEXT_COLOR.get(key, TEXT)
            sign = "+" if val > 0 else "-"
            self.particles.spawn_text(
                (self.pet.x + 142, self.pet.head_pos[1] + 48 + i * 26),
                f"{sign}{int(round(abs(val)))}", col, 22)

    def restart(self):
        worn = self.pet.outfit_id                  # 重开也保留当前衣装
        sid = self.companion.species_id            # 以及当前的小宠物
        self.pet = Pet(PET_NAME)
        self.pet.set_outfit(worn, force=True)
        self.companion = Companion(sid)
        self.particles.clear()
        self._zzz_timer = 0.0
        self.wardrobe_open = False
        self.comp_panel_open = False

    # ---------------- 衣橱 ----------------
    def open_wardrobe(self):
        self.wardrobe_open = True
        self.wardrobe_hover = None
        self.wardrobe_msg = ""
        self.wardrobe_msg_t = 0.0
        for b, _ in self.buttons:
            b.hover = False
        self.wardrobe_btn.hover = False

    def try_wear(self, outfit_id: str):
        """点击卡片：能穿就换，没解锁就给出条件提示。"""
        spec = OUTFIT_MAP.get(outfit_id)
        if spec is None:
            return
        if not self.pet.outfit_unlocked(outfit_id):
            self.wardrobe_msg = f"这件还锁着哦 —— {unlock_text(spec['unlock'])}"
            self.wardrobe_msg_t = 2.6
            return
        if outfit_id == self.pet.outfit_id:
            return
        self.pet.set_outfit(outfit_id, force=True)
        self._wear_flash = 1.0
        self.wardrobe_open = False
        hp = self.pet.head_pos
        self.particles.spawn_sparkles(hp, n=18, spread=112)
        self.particles.spawn_hearts(hp, n=5, spread=74, scale=1.15)
        self.pet.say(f"换上「{spec['name']}」啦～", 2.6)

    def cycle_outfit(self, step: int):
        """← / → 在"已解锁"的衣服之间循环。"""
        ids = self.pet.available_outfits()
        if not ids:
            return
        cur = ids.index(self.pet.outfit_id) if self.pet.outfit_id in ids else 0
        nxt = ids[(cur + step) % len(ids)]
        if nxt == self.pet.outfit_id:
            return
        self.pet.set_outfit(nxt, force=True)
        self._wear_flash = 0.75
        self.particles.spawn_sparkles(self.pet.head_pos, n=10, spread=88)
        self.pet.say(f"「{OUTFIT_MAP[nxt]['name']}」", 1.7)

    def _handle_wardrobe_event(self, event):
        """衣橱打开时，事件只走这里（底层按钮一律不响应）。"""
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_c):
                self.wardrobe_open = False
            elif event.key == pygame.K_LEFT:
                self.cycle_outfit(-1)
            elif event.key == pygame.K_RIGHT:
                self.cycle_outfit(1)
        elif event.type == pygame.MOUSEMOTION:
            self.wardrobe_hover = None
            for rect, oid in self.cards:
                if rect.collidepoint(event.pos):
                    self.wardrobe_hover = oid
                    break
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for rect, oid in self.cards:
                if rect.collidepoint(event.pos):
                    self.try_wear(oid)
                    return
            # 点空白处 = 关掉
            if not pygame.Rect(WARDROBE_PANEL).collidepoint(event.pos):
                self.wardrobe_open = False

    # ---------------- 小宠物 ----------------
    def do_comp_action(self, action_id: str):
        """照顾小宠物。她心情好，主角也会跟着开心一点（host_gain）。"""
        res = self.companion.interact(action_id)
        if not res:
            return
        self._spawn_comp_effect(res["effect"])
        self._spawn_comp_gain(res["gained"])

        spec = COMPANION_ACTION_MAP[action_id]
        host_gain = spec.get("host_gain", {})
        if host_gain:
            hp = self.pet.head_pos
            for key, delta in host_gain.items():
                self.pet.set_stat(key, self.pet.get_stat(key) + delta)
            self.particles.spawn_hearts((hp[0] - 40, hp[1] + 60), n=3,
                                        spread=40, scale=0.8)
            entries = [(k, v) for k, v in host_gain.items() if abs(v) >= 0.5]
            for i, (key, val) in enumerate(entries[:1]):
                self.particles.spawn_text(
                    (self.pet.x + 142, self.pet.head_pos[1] + 48),
                    f"+{int(round(val))}", STAT_TEXT_COLOR.get(key, TEXT), 20)

    def do_comp_pet(self):
        """直接点草地上的小宠物。"""
        res = self.companion.pet()
        if not res:
            return
        self._spawn_comp_effect(res["effect"])
        self._spawn_comp_gain(res["gained"])
        self._glance_at_companion()

    def _glance_at_companion(self):
        """主角朝小宠物那边歪个头（不打断她正在做的别的事）。"""
        if self.pet.sleeping or self.pet.motion.playing:
            return
        self.pet.motion.play("tilt", 1.7)

    def _comp_focus(self):
        """小宠物当前在屏幕上的大致位置（胸口高度，用作特效锚点）。"""
        c = self.companion
        return (c.x, c.y - 96)

    def _spawn_comp_effect(self, effect):
        c = self.companion
        cp = self._comp_focus()
        if effect == "cfood":
            self.particles.spawn_food((c.x, c.y - 14), (c.x, c.y - 92), n=6)
            self.particles.spawn_sparkles(cp, n=3, spread=44)
        elif effect == "ctoy":
            self.particles.spawn_sparkles(cp, n=10, spread=62)
            self.particles.spawn_hearts(cp, n=3, spread=40, scale=0.75)
        elif effect == "chug":
            self.particles.spawn_hearts(cp, n=9, spread=56, scale=1.05)
            self.particles.spawn_sparkles(cp, n=3, spread=56)
        elif effect == "ctouch":
            self.particles.spawn_hearts(cp, n=5, spread=44, scale=0.85)
            self.particles.spawn_sparkles(cp, n=2, spread=48)
        elif effect == "sparkle":                  # 它自己玩得高兴时的星光
            self.particles.spawn_sparkles(cp, n=5, spread=50)

    def _spawn_comp_gain(self, gained):
        """小宠物的数值飘字 —— 往它"外侧"飘，避开主角和头顶气泡。"""
        entries = [(k, v) for k, v in gained.items() if abs(v) >= 0.5]
        if not entries:
            return
        side = -1 if self.companion.x < self.pet.x else 1
        entries.sort(key=lambda kv: -abs(kv[1]))
        for i, (key, val) in enumerate(entries[:2]):
            col = COMP_STAT_COLOR.get(key, TEXT)
            sign = "+" if val > 0 else "-"
            self.particles.spawn_text(
                (self.companion.x + side * 100, self.companion.y - 92 - i * 24),
                f"{sign}{int(round(abs(val)))}", col, 19)

    def open_comp_panel(self):
        self.comp_panel_open = True
        self.comp_hover = None
        self.comp_msg = ""
        self.comp_msg_t = 0.0
        for b, _ in self.buttons:
            b.hover = False
        for b, _ in self.comp_actions:
            b.hover = False
        self.wardrobe_btn.hover = False
        self.comp_btn.hover = False

    def try_choose_species(self, sid: str):
        spec = COMPANION_MAP.get(sid)
        if spec is None:
            return
        if not self.companion.species_unlocked(sid):
            self.comp_msg = f"还没遇见它呢 —— {comp_unlock_text(spec['unlock'])}"
            self.comp_msg_t = 2.6
            return
        if sid == self.companion.species_id:
            return
        self.companion.set_species(sid, force=True)
        self._comp_flash = 1.0
        self.comp_panel_open = False
        self.companion.say(random.choice(SPEECH["cgreet"]), 2.4)
        cp = self._comp_focus()
        self.particles.spawn_sparkles(cp, n=16, spread=84)
        self.particles.spawn_hearts(cp, n=6, spread=56)

    def cycle_species(self, step: int):
        """面板里用 ← / → 在已解锁的宠物之间循环。"""
        ids = self.companion.available_species()
        if not ids:
            return
        cur = ids.index(self.companion.species_id) if self.companion.species_id in ids else 0
        nxt = ids[(cur + step) % len(ids)]
        self.try_choose_species(nxt)

    def _handle_comp_event(self, event):
        """宠物面板打开时，事件先给操作按钮，再处理卡片与关闭。"""
        for btn, spec in self.comp_actions:
            if btn.handle_event(event):
                self.do_comp_action(spec["id"])
                return

        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_t):
                self.comp_panel_open = False
            elif event.key == pygame.K_LEFT:
                self.cycle_species(-1)
            elif event.key == pygame.K_RIGHT:
                self.cycle_species(1)
            elif event.key in self.comp_key_map:
                self.do_comp_action(self.comp_key_map[event.key])
        elif event.type == pygame.MOUSEMOTION:
            self.comp_hover = None
            for rect, sid in self.comp_cards:
                if rect.collidepoint(event.pos):
                    self.comp_hover = sid
                    break
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for rect, sid in self.comp_cards:
                if rect.collidepoint(event.pos):
                    self.try_choose_species(sid)
                    return
            if not pygame.Rect(COMPANION_PANEL).collidepoint(event.pos):
                self.comp_panel_open = False

    # ---------------- 事件 ----------------
    def handle_events(self):
        # prepare_events：触摸兜底（FINGER* → 鼠标事件，且不会和 SDL 合成的事件重复）
        # translate_event：手机屏幕像素坐标 → 640x800 逻辑坐标（桌面是零成本直通）
        events = self.display.prepare_events(pygame.event.get())
        for raw_event in events:
            event = self.display.translate_event(raw_event)

            if event.type == pygame.QUIT:
                self.running = False
                continue

            # 安卓返回键：先收起打开的面板，再退出游戏
            if event.type == pygame.KEYDOWN and is_back_key(event.key):
                if self.wardrobe_open:
                    self.wardrobe_open = False
                elif self.comp_panel_open:
                    self.comp_panel_open = False
                else:
                    self.running = False
                continue

            # 衣橱打开时是"模态"：所有事件都交给它，底层按钮不响应
            if self.wardrobe_open:
                self._handle_wardrobe_event(event)
                continue

            # 宠物面板同理
            if self.comp_panel_open:
                self._handle_comp_event(event)
                continue

            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    self.running = False
                elif event.key == pygame.K_SPACE:
                    self.do_action("feed")
                elif event.key == pygame.K_r:
                    self.restart()
                elif event.key == pygame.K_c:
                    self.open_wardrobe()
                elif event.key == pygame.K_t:
                    self.open_comp_panel()
                elif event.key == pygame.K_LEFT:
                    self.cycle_outfit(-1)
                elif event.key == pygame.K_RIGHT:
                    self.cycle_outfit(1)
                elif event.key in self.comp_key_map:
                    self.do_comp_action(self.comp_key_map[event.key])
                elif event.key in self.key_map:
                    self.do_action(self.key_map[event.key])
                continue

            if self.wardrobe_btn.handle_event(event):
                self.open_wardrobe()
                continue

            if self.comp_btn.handle_event(event):
                self.open_comp_panel()
                continue

            # 直接点草地上的小宠物 = 摸摸它
            if (event.type == pygame.MOUSEBUTTONDOWN and event.button == 1
                    and self.companion.rect.collidepoint(event.pos)):
                self.do_comp_pet()
                continue

            for btn, spec in self.buttons:
                if btn.handle_event(event):
                    self.do_action(spec["id"])

    # ---------------- 更新 ----------------
    def update(self, dt):
        self.time += dt
        for c in self.clouds:
            c.update(dt)

        # 小宠物过得好 → 她更省心（快乐掉得慢）；宠物蔫了 → 她跟着操心
        comp = self.companion
        if comp.thriving:
            happiness_mul = 0.85
        elif comp.min_stat < COMP_LOW:
            happiness_mul = 1.15
        else:
            happiness_mul = 1.0

        self.pet.update(dt, self.particles, happiness_mul=happiness_mul)
        comp.update(dt, host=self.pet, particles=self.particles)

        # 双方自主动作攒下的特效请求，在这里统一播出去
        for eff in self.pet.take_effects():
            self._spawn_effect(eff)
        for eff in comp.take_effects():
            self._spawn_comp_effect(eff)

        self.particles.update(dt)

        for key, bar in self.bars.items():
            bar.update(dt, self.pet.get_stat(key), STAT_MAX)

        for b, _ in self.buttons:
            b.update(dt)
        self.wardrobe_btn.update(dt)
        self.comp_btn.update(dt)
        for b, spec in self.comp_actions:
            b.enabled = comp.can_interact(spec["id"])
            b.update(dt)
        self.wardrobe_msg_t = max(0.0, self.wardrobe_msg_t - dt)
        self.comp_msg_t = max(0.0, self.comp_msg_t - dt)
        self._wear_flash = max(0.0, self._wear_flash - dt * 1.8)
        self._comp_flash = max(0.0, self._comp_flash - dt * 1.8)

        # 面板打开时，底层的按钮不接受悬停
        if self.wardrobe_open or self.comp_panel_open:
            for b, _ in self.buttons:
                b.hover = False
            self.wardrobe_btn.hover = False
            self.comp_btn.hover = False
        if self.comp_panel_open:
            for b, _ in self.comp_actions:
                b.hover = False

        # 新衣装解锁 → 冒星光 + 报喜
        if self.pet.pending_unlocks:
            oid = self.pet.pending_unlocks.pop(0)
            name = OUTFIT_MAP[oid]["name"]
            self.pet.say(f"解锁新衣装「{name}」！按 C 看看～", 3.4)
            self.particles.spawn_sparkles(self.pet.head_pos, n=18, spread=118)
            self.particles.spawn_hearts(self.pet.head_pos, n=4, spread=64, scale=0.95)

        # 认识新宠物 → 冒星光 + 报喜
        if comp.pending_unlocks:
            sid = comp.pending_unlocks.pop(0)
            name = COMPANION_MAP[sid]["name"]
            self.pet.say(f"我们认识了新伙伴「{name}」！按 T 看看～", 3.4)
            cp = self._comp_focus()
            self.particles.spawn_sparkles(cp, n=18, spread=96)
            self.particles.spawn_hearts(cp, n=5, spread=60, scale=1.0)

        # 按钮可用状态 + "睡觉 ⇄ 叫醒" 的动态外观
        for btn, spec in self.buttons:
            aid = spec["id"]
            if aid == "sleep":
                btn.enabled = True
                if self.pet.sleeping:
                    btn.label = "叫醒"
                    btn.icon_kind = "sun"
                    btn.icon_color = (240, 186, 84)
                else:
                    btn.label = spec["label"]
                    btn.icon_kind = spec["icon"]
                    btn.icon_color = spec["btn"][4]
            else:
                btn.enabled = self.pet.can_interact(aid)

        # 睡觉时持续冒 Z
        if self.pet.sleeping:
            self._zzz_timer -= dt
            if self._zzz_timer <= 0:
                self._zzz_timer = random.uniform(0.85, 1.35)
                self.particles.spawn_zzz(self.pet.head_pos)
        else:
            self._zzz_timer = 0.0

        # 小宠物打盹也冒 Z（慢一些）
        if comp.state == "sleep":
            self._czzz_timer -= dt
            if self._czzz_timer <= 0:
                self._czzz_timer = random.uniform(1.15, 1.8)
                self.particles.spawn_zzz(self._comp_focus())
        else:
            self._czzz_timer = 0.0

    # ---------------- 绘制 ----------------
    def draw(self):
        s = self.screen
        s.blit(self.bg, (0, 0))

        for c in self.clouds:
            c.draw(s)

        # 数值条
        for key, bar in self.bars.items():
            bar.draw(s, self.pet.get_stat(key))

        # 状态提示（画在标题下方，避开头顶气泡）
        self._draw_status_hint(s)

        # 角色 & 小宠物：小宠物体型小、位置靠下，始终画在她前面
        # （落在前景 = 在她脚边溜达，永远不会被她的贴图整个盖掉）
        self.pet.draw(s)
        self.companion.draw(s)
        self.particles.draw(s)

        # 右上角"衣装" / "宠物"按钮
        self.wardrobe_btn.draw(s)
        self.comp_btn.draw(s)

        # 按钮
        for b, _ in self.buttons:
            b.draw(s)

        # 衣橱（模态，画在最上层）
        if self.wardrobe_open:
            self._draw_wardrobe(s)

        # 宠物面板（同样是模态）
        if self.comp_panel_open:
            self._draw_comp_panel(s)

        # 换装 / 换宠物瞬间的柔光
        if self._wear_flash > 0.01:
            fl = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            fl.fill((255, 246, 252, int(78 * self._wear_flash)))
            s.blit(fl, (0, 0))
        if self._comp_flash > 0.01:
            fl = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
            fl.fill((255, 248, 240, int(78 * self._comp_flash)))
            s.blit(fl, (0, 0))

        # 底部提示（手机没有键盘，提示里就不写快捷键了）
        hint = ("点按钮互动　·　点「衣装」换衣服　·　点「宠物」照顾小家伙　·　点小家伙摸摸它"
                if self.display.android else
                "点按钮互动　·　C 衣橱　·　T 宠物　·　点小宠物摸摸它　·　R 重来")
        text_at(s, hint, (WIDTH // 2, 786), size=13, color=TEXT_SOFT, center=True)

        if SHOW_FPS:
            text_at(s, f"FPS {int(self.clock.get_fps())}", (10, 10), size=14,
                    color=TEXT_SOFT)

        # 缩放到真实窗口后上屏（桌面 scale==1 时等价于原来的 pygame.display.flip()）
        self.display.present()

    def _draw_status_hint(self, surface):
        """状态不佳时，在标题下方显示一条呼吸提示。"""
        if self.pet.sleeping:
            msg, col = "嘘…她正在睡觉呢（休息时可以按 S 叫醒她）", (176, 168, 214)
        else:
            st = min(self.pet.hunger, self.pet.happiness, self.pet.energy)
            if st >= MID_THRESHOLD:
                return
            if st < LOW_THRESHOLD:
                msg, col = "呜…她有点不舒服了，快照顾一下！", (255, 150, 150)
            else:
                msg, col = "她好像有点想你了～", (200, 176, 214)

        pulse = 0.5 + 0.5 * math.sin(self.time * 3.4)
        font = get_font(15, True)
        img = font.render(msg, True, col)
        w, h = img.get_width() + 34, 28
        x = WIDTH // 2 - w // 2
        y = 74 - h // 2 + int(math.sin(self.time * 2.2) * 2)

        layer = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.rect(layer, (255, 253, 251, 236), pygame.Rect(0, 0, w, h),
                         border_radius=h // 2)
        pygame.draw.rect(layer, (*col, int(120 + 90 * pulse)), pygame.Rect(0, 0, w, h),
                         3, border_radius=h // 2)
        layer.blit(img, (17, (h - img.get_height()) // 2))
        surface.blit(layer, (x, y))

    # ---------------- 衣橱绘制 ----------------
    def _draw_wardrobe(self, surface):
        # 半透明遮罩：把注意力收到面板上
        veil = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        veil.fill((92, 74, 102, 148))
        surface.blit(veil, (0, 0))

        panel = pygame.Rect(WARDROBE_PANEL)
        draw_panel(surface, WARDROBE_PANEL, radius=30,
                   color=(255, 252, 253), edge=(246, 224, 238),
                   shadow=(66, 48, 74, 135), shadow_offset=9)

        # 标题
        ic = make_icon("hanger", 26, PINK_DEEP)
        surface.blit(ic, ic.get_rect(center=(WIDTH // 2 - 64, panel.y + 42)))
        text_at(surface, "衣 橱", (WIDTH // 2 + 6, panel.y + 42), size=28,
                color=TEXT, bold=True, center=True)
        text_at(surface, "点击卡片换装　·　← / → 快速切换　·　C / ESC 关闭",
                (WIDTH // 2, panel.y + 74), size=13, color=TEXT_LIGHT, center=True)

        done = sum(1 for o in OUTFITS if self.pet.outfit_unlocked(o["id"]))
        text_at(surface, f"已收集 {done} / {len(OUTFITS)}",
                (panel.right - 54, panel.y + 42), size=13, color=TEXT_SOFT,
                center=True)

        for rect, oid in self.cards:
            self._draw_card(surface, rect, OUTFIT_MAP[oid])

        # 锁定提示
        if self.wardrobe_msg_t > 0 and self.wardrobe_msg:
            a = clamp(self.wardrobe_msg_t / 0.45, 0, 1)
            font = get_font(15, True)
            img = font.render(self.wardrobe_msg, True, (224, 128, 156))
            img.set_alpha(int(255 * a))
            w, h = img.get_width() + 34, 32
            lay = pygame.Surface((w, h), pygame.SRCALPHA)
            pygame.draw.rect(lay, (255, 250, 252, int(240 * a)),
                             pygame.Rect(0, 0, w, h), border_radius=h // 2)
            pygame.draw.rect(lay, (246, 196, 214, int(255 * a)),
                             pygame.Rect(0, 0, w, h), 2, border_radius=h // 2)
            lay.blit(img, (17, (h - img.get_height()) // 2))
            surface.blit(lay, (WIDTH // 2 - w // 2, panel.bottom - 42))

    def _draw_card(self, surface, rect, spec):
        oid = spec["id"]
        unlocked = self.pet.outfit_unlocked(oid)
        worn = (oid == self.pet.outfit_id)
        hover = (self.wardrobe_hover == oid and unlocked)

        r = rect.copy()
        if hover:
            r.inflate_ip(6, 6)

        if worn:
            body, edge = (255, 238, 246), PINK
        elif unlocked:
            body, edge = (255, 255, 255), (238, 226, 238)
        else:
            body, edge = (243, 239, 245), (232, 226, 236)

        # 投影
        sh = pygame.Surface((r.w + 4, r.h + 10), pygame.SRCALPHA)
        pygame.draw.rect(sh, (188, 164, 190, 90),
                         pygame.Rect(0, 0, r.w, r.h), border_radius=20)
        surface.blit(sh, (r.x - 2, r.y + 5))

        pygame.draw.rect(surface, body, r, border_radius=20)
        pygame.draw.rect(surface, edge, r, 3 if worn else 2, border_radius=20)

        # 角色缩略图（真的把她画成这套衣服，不是贴图占位）
        tw, th = CARD_THUMB_SIZE
        tx, ty = r.centerx - tw // 2, r.y + 8
        thumb = self.pet.render_thumb(oid, CARD_THUMB_SIZE)
        if unlocked:
            surface.blit(thumb, (tx, ty))
        else:
            ghost = thumb.copy()
            ghost.fill((118, 108, 130, 255), special_flags=pygame.BLEND_RGBA_MULT)
            veil = pygame.Surface(CARD_THUMB_SIZE, pygame.SRCALPHA)
            veil.fill((255, 250, 252, 146))
            ghost.blit(veil, (0, 0))
            surface.blit(ghost, (tx, ty))
            lk = make_icon("lock", 30, (194, 184, 206))
            surface.blit(lk, lk.get_rect(center=(r.centerx, ty + th // 2)))

        # 名字 + 状态行
        text_at(surface, spec["name"], (r.centerx, r.y + 158), size=17,
                color=PINK_DEEP if worn else (TEXT if unlocked else (176, 168, 186)),
                bold=True, center=True)

        if worn:
            txt, col = "穿着中", PINK_DEEP
        elif unlocked:
            txt, col = spec["hint"], TEXT_LIGHT
        else:
            txt, col = unlock_text(spec["unlock"]), (200, 174, 200)
        text_at(surface, txt, (r.centerx, r.y + 180), size=12, color=col, center=True)

        if hover:
            hl = r.inflate(8, 8)
            gl = pygame.Surface(hl.size, pygame.SRCALPHA)
            pygame.draw.rect(gl, (255, 255, 255, 130),
                             pygame.Rect(0, 0, hl.w, hl.h), border_radius=24, width=5)
            surface.blit(gl, hl.topleft)

    # ---------------- 宠物面板绘制 ----------------
    def _draw_comp_panel(self, surface):
        veil = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        veil.fill((92, 74, 102, 148))
        surface.blit(veil, (0, 0))

        panel = pygame.Rect(COMPANION_PANEL)
        draw_panel(surface, COMPANION_PANEL, radius=30,
                   color=(255, 252, 253), edge=(242, 224, 240),
                   shadow=(66, 48, 74, 135), shadow_offset=9)

        # 标题
        ic = make_icon("paw", 26, (242, 168, 122))
        surface.blit(ic, ic.get_rect(center=(WIDTH // 2 - 66, panel.y + 40)))
        text_at(surface, "小 宠 物", (WIDTH // 2 + 6, panel.y + 40), size=26,
                color=TEXT, bold=True, center=True)
        text_at(surface, "点卡片换宠物　·　1 / 2 / 3 快速照顾　·　T / ESC 关闭",
                (WIDTH // 2, panel.y + 70), size=13, color=TEXT_LIGHT, center=True)

        done = sum(1 for c in COMPANIONS
                   if self.companion.species_unlocked(c["id"]))
        c = self.companion                       # 当前在陪她的小宠物
        mood_txt = {"sleep": "正在打盹…", "hungry": "肚子饿了",
                    "lonely": "有点无聊"}.get(c._mood_key(), "心情不错")
        text_at(surface, f"{c.name} · {mood_txt}",
                (panel.right - 92, panel.y + 40), size=14,
                color=PINK_DEEP if c.thriving else TEXT_LIGHT, center=True)

        # 种类卡片
        for rect, sid in self.comp_cards:
            self._draw_comp_card(surface, rect, COMPANION_MAP[sid])

        # 三条宠物数值
        for i, key in enumerate(COMP_STAT_KEYS):
            y = panel.y + COMP_BAR_TOP + i * COMP_BAR_ROW
            self._draw_comp_bar(surface, panel, key,
                                self.companion.get_stat(key), y)

        # 操作按钮
        for btn, _ in self.comp_actions:
            btn.draw(surface)

        # 底部：收集进度
        text_at(surface, f"已 收 集 {done} / {len(COMPANIONS)}",
                (panel.centerx, panel.bottom - 26), size=13,
                color=TEXT_SOFT, center=True)

        # 锁定提示
        if self.comp_msg_t > 0 and self.comp_msg:
            a = clamp(self.comp_msg_t / 0.45, 0, 1)
            font = get_font(15, True)
            img = font.render(self.comp_msg, True, (224, 128, 156))
            img.set_alpha(int(255 * a))
            w, h = img.get_width() + 34, 32
            lay = pygame.Surface((w, h), pygame.SRCALPHA)
            pygame.draw.rect(lay, (255, 250, 252, int(240 * a)),
                             pygame.Rect(0, 0, w, h), border_radius=h // 2)
            pygame.draw.rect(lay, (246, 196, 214, int(255 * a)),
                             pygame.Rect(0, 0, w, h), 2, border_radius=h // 2)
            lay.blit(img, (17, (h - img.get_height()) // 2))
            surface.blit(lay, (WIDTH // 2 - w // 2, panel.bottom - 36))

    def _draw_comp_bar(self, surface, panel, key, value, y):
        icon = make_icon(COMP_STAT_ICON[key], 22, COMP_STAT_COLOR[key])
        surface.blit(icon, icon.get_rect(center=(panel.x + 44, y + COMP_BAR_H // 2)))
        text_at(surface, COMP_STAT_LABEL[key],
                (panel.x + 66, y + COMP_BAR_H // 2 - 1), size=16,
                color=TEXT, bold=True, center=False)

        bar = pygame.Rect(panel.x + 128, y, 330, COMP_BAR_H)
        pygame.draw.rect(surface, COMP_STAT_BG[key], bar,
                         border_radius=bar.h // 2)
        pygame.draw.rect(surface, (255, 255, 255), bar, 2,
                         border_radius=bar.h // 2)

        fill_w = int((bar.w - 6) * clamp(value / COMP_MAX, 0, 1))
        if fill_w > 2:
            pygame.draw.rect(surface, COMP_STAT_FG[key],
                             pygame.Rect(bar.x + 3, bar.y + 3, fill_w, bar.h - 6),
                             border_radius=(bar.h - 6) // 2)

        low = value < COMP_LOW
        text_at(surface, f"{int(round(value))}", (bar.right + 13, bar.centery - 1),
                size=17, color=BAR_LOW_FG if low else TEXT_LIGHT, bold=True,
                center=False)

    def _draw_comp_card(self, surface, rect, spec):
        sid = spec["id"]
        unlocked = self.companion.species_unlocked(sid)
        active = (sid == self.companion.species_id)
        hover = (self.comp_hover == sid and unlocked)

        r = rect.copy()
        if hover:
            r.inflate_ip(6, 6)

        if active:
            body, edge = (255, 240, 246), PINK
        elif unlocked:
            body, edge = (255, 255, 255), (238, 226, 238)
        else:
            body, edge = (245, 242, 247), (234, 229, 239)

        sh = pygame.Surface((r.w + 4, r.h + 10), pygame.SRCALPHA)
        pygame.draw.rect(sh, (188, 164, 190, 90),
                         pygame.Rect(0, 0, r.w, r.h), border_radius=18)
        surface.blit(sh, (r.x - 2, r.y + 5))

        pygame.draw.rect(surface, body, r, border_radius=18)
        pygame.draw.rect(surface, edge, r, 3 if active else 2, border_radius=18)

        # 缩略图：真的把这只小宠物画出来，不是占位图
        tw, th = COMP_THUMB_SIZE
        tx, ty = r.centerx - tw // 2, r.y + 8
        thumb = self.companion.render_thumb(sid, COMP_THUMB_SIZE)
        if unlocked:
            surface.blit(thumb, (tx, ty))
        else:
            ghost = thumb.copy()
            ghost.fill((120, 112, 132, 255), special_flags=pygame.BLEND_RGBA_MULT)
            veil = pygame.Surface(COMP_THUMB_SIZE, pygame.SRCALPHA)
            veil.fill((255, 250, 252, 150))
            ghost.blit(veil, (0, 0))
            surface.blit(ghost, (tx, ty))
            # 灰底上直接画锁会看不清，垫一个白色圆底
            pygame.draw.circle(surface, (255, 253, 253),
                               (r.centerx, ty + th // 2), 17)
            lk = make_icon("lock", 24, (168, 156, 184))
            surface.blit(lk, lk.get_rect(center=(r.centerx, ty + th // 2)))

        text_at(surface, spec["name"], (r.centerx, r.y + 108), size=16,
                color=PINK_DEEP if active else (TEXT if unlocked else (178, 170, 188)),
                bold=True, center=True)

        if active:
            txt, col = "一起玩", PINK_DEEP
        elif unlocked:
            txt, col = spec["hint"], TEXT_LIGHT
        else:
            txt, col = comp_unlock_text(spec["unlock"]), (202, 176, 202)
        text_at(surface, txt, (r.centerx, r.y + 130), size=11, color=col,
                center=True)

        if hover:
            hl = r.inflate(8, 8)
            gl = pygame.Surface(hl.size, pygame.SRCALPHA)
            pygame.draw.rect(gl, (255, 255, 255, 130),
                             pygame.Rect(0, 0, hl.w, hl.h), border_radius=22,
                             width=5)
            surface.blit(gl, hl.topleft)

    # ---------------- 主循环 ----------------
    def run(self):
        while self.running:
            dt = min(self.clock.tick(FPS) / 1000.0, MAX_DT)
            self.handle_events()
            self.update(dt)
            self.draw()
        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    Game().run()
