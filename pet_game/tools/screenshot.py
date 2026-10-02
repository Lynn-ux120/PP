# -*- coding: utf-8 -*-
"""
tools/screenshot.py —— 无头渲染预览图（开发辅助工具）
=========================================================
不弹窗口，直接把各个状态渲染成 PNG，方便快速检查画面 / 做版本对比。

用法：
    python tools/screenshot.py            # 输出到 ./preview/
    python tools/screenshot.py -o D:\\out  # 指定输出目录
    python tools/screenshot.py --bench     # 顺便跑一个性能测试
"""
from __future__ import annotations

import argparse
import os
import sys
import time

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pygame  # noqa: E402
import main as M  # noqa: E402


def render(game, frames=1, dt=1.0 / 60):
    for _ in range(frames):
        game.update(dt)
    game.draw()
    return game.screen


def save(game, path, frames=1):
    img = render(game, frames)
    pygame.image.save(img, path)
    print("  ->", os.path.basename(path))


def quiet(game):
    """清掉台词气泡和残留粒子，方便拍"干净"的状态图。"""
    game.pet.say_text = ""
    game.pet._say_timer = 0.0
    game.companion.say_text = ""
    game.companion._say_timer = 0.0
    game.particles.clear()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default=os.path.join(ROOT, "preview"))
    ap.add_argument("--bench", action="store_true", help="顺便跑一个性能测试")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    g = M.Game()
    out = args.out

    # ---------- 状态图 ----------
    quiet(g)
    save(g, os.path.join(out, "01_normal.png"), 40)

    g.pet.hunger, g.pet.happiness, g.pet.energy = 44.0, 44.0, 60.0
    quiet(g)
    save(g, os.path.join(out, "05_meh.png"), 40)

    g.pet.reaction_timer = 0.0
    g.pet.hunger, g.pet.happiness, g.pet.energy = 11.0, 17.0, 70.0
    quiet(g)
    save(g, os.path.join(out, "04_sad.png"), 45)

    # 精力见底 → 犯困
    g.pet.hunger, g.pet.happiness, g.pet.energy = 82.0, 84.0, 12.0
    quiet(g)
    save(g, os.path.join(out, "07_tired.png"), 40)

    # 睡觉中
    g.pet.hunger, g.pet.happiness, g.pet.energy = 82.0, 84.0, 30.0
    quiet(g)
    g.do_action("sleep")
    save(g, os.path.join(out, "08_sleeping.png"), 70)

    # 眨眼
    g.pet.wake_up()
    g.pet.reaction_timer = 0.0
    g.pet.hunger, g.pet.happiness, g.pet.energy = 90.0, 92.0, 90.0
    g.pet.say_text, g.pet._say_timer = "", 0.0
    g.pet._blinking = 0.12
    quiet(g)
    save(g, os.path.join(out, "06_blink.png"), 1)

    # ---------- 每个互动的特效图 ----------
    shots = [
        ("feed", "10_feed.png"), ("drink", "11_drink.png"),
        ("pet", "12_pet.png"), ("hug", "13_hug.png"),
        ("play", "14_play.png"), ("sing", "15_sing.png"),
        ("bath", "16_bath.png"),
    ]
    for action, fname in shots:
        g.pet.wake_up()
        g.pet.reaction_timer = 0.0
        g.pet.hunger, g.pet.happiness, g.pet.energy = 62.0, 60.0, 88.0
        g.pet._cooldowns.clear()
        quiet(g)
        g.do_action(action)
        save(g, os.path.join(out, fname), 14)

    # ---------- 衣装 ----------
    # 先把所有衣服解锁，才能拍全 6 张卡片
    g.pet._max_seen = {k: 100.0 for k in g.pet._max_seen}
    g.pet.interaction_count = 99
    g.pet.hunger, g.pet.happiness, g.pet.energy = 84.0, 86.0, 88.0
    g.pet.pending_unlocks.clear()
    quiet(g)
    g.wardrobe_open = True
    save(g, os.path.join(out, "20_wardrobe.png"), 1)

    # 锁定态的衣橱（新建一局 = 只解锁了前两套）
    g2 = M.Game()
    g2.pet.pending_unlocks.clear()
    quiet(g2)
    g2.wardrobe_open = True
    save(g2, os.path.join(out, "21_wardrobe_locked.png"), 1)

    # 每套衣服的全身照
    for i, spec in enumerate(M.OUTFITS):
        g.wardrobe_open = False
        g.pet.set_outfit(spec["id"], force=True)
        g.pet.reaction_timer = 0.0
        g.pet.pending_unlocks.clear()
        quiet(g)
        save(g, os.path.join(out, f"22_{i + 1}_outfit_{spec['id']}.png"), 24)

    # ---------- 小宠物 ----------
    c = g.companion
    c._max_seen = {k: 100.0 for k in c._max_seen}
    c.action_count = 99
    c.unlocked = {x["id"] for x in M.COMPANIONS}
    c.pending_unlocks.clear()
    quiet(g)
    g.comp_panel_open = True
    save(g, os.path.join(out, "30_companion.png"), 1)

    # 锁定态的宠物面板（新建一局 = 只遇见第一只）
    g3 = M.Game()
    g3.pet.pending_unlocks.clear()
    g3.companion.pending_unlocks.clear()
    quiet(g3)
    g3.comp_panel_open = True
    save(g3, os.path.join(out, "31_companion_locked.png"), 1)

    # 四种小宠物在草地上的样子（主角换回经典造型，画面干净些）
    g.comp_panel_open = False
    g.pet.set_outfit(M.OUTFITS[0]["id"], force=True)
    g.pet.unlocked = {o["id"] for o in M.OUTFITS}
    g.pet.pending_unlocks.clear()
    for i, spec in enumerate(M.COMPANIONS):
        c.set_species(spec["id"], force=True)
        c.state, c.state_t = "idle", 6.0
        c.x = M.PET_CENTER[0] - 172
        c.belly, c.mood = 84.0, 88.0
        quiet(g)
        save(g, os.path.join(out, f"32_{i + 1}_pet_{spec['id']}.png"), 24)

    # 三种宠物互动
    c.set_species("cat", force=True)
    c.x = M.PET_CENTER[0] - 172
    for action, fname in (("cfood", "34_pet_feed.png"),
                          ("ctoy", "35_pet_toy.png"),
                          ("chug", "36_pet_hug.png")):
        c.state, c.state_t = "idle", 6.0
        c.x = M.PET_CENTER[0] - 172
        c._cooldowns.clear()
        c.belly, c.mood, c.bond = 58.0, 58.0, 58.0
        quiet(g)
        g.do_comp_action(action)
        save(g, os.path.join(out, fname), 12)

    # 蔫掉（饿了 / 委屈）
    c.belly, c.mood = 12.0, 14.0
    c.state, c.state_t = "idle", 6.0
    c.reaction_timer = 0.0
    c.x = M.PET_CENTER[0] - 172
    quiet(g)
    save(g, os.path.join(out, "37_pet_sad.png"), 24)

    # 陪主角一起睡
    c.belly, c.mood = 80.0, 84.0
    c.x = g.pet.x + 158
    c.state, c.state_t = "sleep", 6.0
    c.reaction_timer = 0.0
    quiet(g)
    save(g, os.path.join(out, "38_pet_sleep.png"), 30)

    # ---------- 动作：主角的待机小动作（取动作中途的一帧）----------
    g.pet.set_outfit(M.OUTFITS[0]["id"], force=True)
    g.pet.hunger, g.pet.happiness, g.pet.energy = 86.0, 88.0, 86.0
    g.pet.reaction_timer = 0.0
    antic_shots = [("stretch", 1.7), ("sway", 1.8), ("hop", 1.2),
                   ("tilt", 1.8), ("squat", 2.2), ("twirl", 1.3),
                   ("shiver", 1.2)]
    for name, dur in antic_shots:
        g.pet._antic_timer = 9e9          # 别让她自己乱插动作
        g.pet.motion.stop()
        quiet(g)
        g.pet.motion.play(name, dur)
        save(g, os.path.join(out, f"40_antic_{name}.png"), int(dur * 0.5 * 60))

    # 互动自带动作（喝水仰头 / 拥抱挤压…取互动后不久）
    for action, fname in (("drink", "41_act_drink.png"),
                          ("hug", "41_act_hug.png"),
                          ("bath", "41_act_bath.png")):
        g.pet._cooldowns.clear()
        g.pet.hunger, g.pet.happiness, g.pet.energy = 62.0, 60.0, 88.0
        quiet(g)
        g.do_action(action)
        save(g, os.path.join(out, fname), 34)

    # ---------- 动作：小宠物的自娱自乐 ----------
    # 把主角临时挪到屏幕边上，腾出一块干净的地方拍小宠物
    g.pet.x = 556
    c.set_species("cat", force=True)
    g.pet._antic_timer = 9e9
    pet_act_shots = [("groom", 3.0), ("stretch", 1.9), ("roll", 2.2),
                     ("spin", 2.2), ("dig", 2.3), ("sit", 3.0)]
    for name, dur in pet_act_shots:
        c.x = 150
        c.belly, c.mood = 80.0, 84.0
        c.reaction_timer = 0.0
        c.motion.stop()
        quiet(g)
        c.state, c.state_t = name, dur
        c.motion.play(name, dur)
        # 采 0.42 这个时刻：刨地/舔毛的曲线在 0.5 处正好回到中间值，看不出动作
        save(g, os.path.join(out, f"42_pet_{name}.png"), int(dur * 0.42 * 60))

    if args.bench:
        print("\n[性能]")
        g.wardrobe_open = False
        g.comp_panel_open = False
        c.state, c.state_t = "walk", 6.0
        t0 = time.perf_counter()
        N = 600
        for _ in range(N):
            g.update(1 / 60)
            g.draw()
        cost = (time.perf_counter() - t0) / N * 1000
        print(f"  常规界面  {N} 帧平均 {cost:.2f} ms/帧  (60FPS 预算 16.7ms)")

        g.wardrobe_open = True
        t0 = time.perf_counter()
        for _ in range(N):
            g.update(1 / 60)
            g.draw()
        cost = (time.perf_counter() - t0) / N * 1000
        print(f"  衣橱展开  {N} 帧平均 {cost:.2f} ms/帧")
        g.wardrobe_open = False

        g.comp_panel_open = True
        t0 = time.perf_counter()
        for _ in range(N):
            g.update(1 / 60)
            g.draw()
        cost = (time.perf_counter() - t0) / N * 1000
        print(f"  宠物面板  {N} 帧平均 {cost:.2f} ms/帧")
        g.comp_panel_open = False

    print("\n完成，输出目录：", out)


if __name__ == "__main__":
    main()
