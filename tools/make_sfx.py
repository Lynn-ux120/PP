# -*- coding: utf-8 -*-
"""
make_sfx.py —— 纯 Python 合成游戏音效（不需要 numpy，不依赖任何外部素材）
=========================================================
运行：  python tools/make_sfx.py
产物：  pet_game/sfx/*.wav   （22050Hz / 16bit / 单声道）

为什么自己合成
  1. 工程里一个音频素材都没有，也不想塞一堆来路不明的版权文件；
  2. 手机上装 numpy 只为生成音效不值得，p4a 的依赖越少越好编译；
  3. 参数化合成 → 想"再甜一点""再轻一点"改几个数字重跑即可。

【新增一个音效】
  1. 写一个 build_xxx() 返回 float 列表（-1~1），返回 None 表示不要这个音
  2. 加进下面的 SOUNDS 表
  3. 在 config.py 的 sfx 字段里引用它的名字
"""
from __future__ import annotations

import math
import os
import random
import struct
import sys
import wave

SR = 22050                     # 采样率（与 config.SFX_RATE 保持一致）
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "pet_game", "sfx")


# =========================================================
#  基础工具
# =========================================================
def _samples(dur: float) -> int:
    return max(1, int(dur * SR))


def osc(kind: str, phase: float) -> float:
    """相位 → 波形值（phase 单位是弧度）。"""
    if kind == "sine":
        return math.sin(phase)
    if kind == "tri":                       # 三角波：比方波柔和很多
        return 2.0 / math.pi * math.asin(math.sin(phase))
    if kind == "saw":
        return 2.0 * ((phase / math.tau) % 1.0) - 1.0
    if kind == "square":
        return 1.0 if (phase / math.tau) % 1.0 < 0.5 else -1.0
    return math.sin(phase)


def tone(dur, f0, f1=None, kind="sine", amp=1.0, attack=0.006,
         curve=4.0, vib=0.0, vib_hz=5.5, lp=0.0, delay=0.0, harmonics=()):
    """
    一个单音。

    dur      时长（秒）
    f0 → f1  音高滑音（f1=None 表示不滑）
    amp      振幅
    attack   起音时间（秒）—— 太短会有"啪"的爆音，所以默认 6ms
    curve    衰减指数，越大衰减越快
    vib      颤音深度（半音数近似用 Hz 偏差表示）
    lp       单极点低通截止频率（Hz），0 = 不滤波
    delay    整体延后多少秒开始
    harmonics [(倍频, 相对音量), ...] 叠加泛音，让音色更"厚"
    """
    n = _samples(dur)
    buf = [0.0] * n
    f1 = f0 if f1 is None else f1
    phase = 0.0
    ph_vib = 0.0
    for i in range(n):
        p = i / n
        f = f0 + (f1 - f0) * p
        ph_vib += math.tau * vib_hz / SR
        if vib:
            f += math.sin(ph_vib) * vib
        phase += math.tau * f / SR
        a = osc(kind, phase)
        for mult, hm_amp in harmonics:
            a += osc(kind, phase * mult) * hm_amp
        a /= (1.0 + sum(h for _, h in harmonics))
        # 包络：线性起音 + 指数衰减
        if attack > 0 and i < attack * SR:
            e = i / (attack * SR)
        else:
            e = math.exp(-curve * (p if attack <= 0 else (i - attack * SR) /
                                   max(1.0, n - attack * SR)))
        buf[i] = a * e * amp
    if lp:
        buf = lowpass(buf, lp)
    if delay:
        buf = [0.0] * _samples(delay) + buf
    return buf


def noise(dur, amp=1.0, attack=0.002, curve=6.0, lp=0.0, rng=None, delay=0.0):
    """噪声（咔滋 / 泡泡 / 气息）。"""
    rng = rng or random
    n = _samples(dur)
    buf = []
    for i in range(n):
        p = i / n
        e = (i / (attack * SR)) if (attack > 0 and i < attack * SR) else \
            math.exp(-curve * p)
        buf.append(rng.uniform(-1, 1) * e * amp)
    if lp:
        buf = lowpass(buf, lp)
    if delay:
        buf = [0.0] * _samples(delay) + buf
    return buf


def lowpass(buf, cutoff):
    """单极点低通。cutoff 越低越闷。"""
    a = 1.0 - math.exp(-math.tau * cutoff / SR)
    y = 0.0
    out = []
    for x in buf:
        y += a * (x - y)
        out.append(y)
    return out


def highpass(buf, cutoff, mix=1.0):
    """用"原信号 - 低通"近似高通，用来去掉沉闷的低频。"""
    a = 1.0 - math.exp(-math.tau * cutoff / SR)
    y = 0.0
    out = []
    for x in buf:
        y += a * (x - y)
        out.append(x - y * mix)
    return out


def seq(*bufs):
    """顺序拼接。"""
    out = []
    for b in bufs:
        out.extend(b)
    return out


def mix(*bufs):
    """叠加（长度取最长，短的不补齐也没关系）。"""
    if not bufs:
        return []
    n = max(len(b) for b in bufs)
    out = [0.0] * n
    for b in bufs:
        for i, v in enumerate(b):
            out[i] += v
    return out


def gain(buf, g):
    return [v * g for v in buf]


def fade(buf, fin=0.004, fout=0.02):
    """首尾淡入淡出，避免播放时"嗒"的一声。"""
    n = len(buf)
    ni, no = _samples(fin), _samples(fout)
    for i in range(min(ni, n)):
        buf[i] *= i / ni
    for i in range(min(no, n)):
        buf[n - 1 - i] *= i / no
    return buf


def normalize(buf, peak=0.72):
    m = max((abs(v) for v in buf), default=0.0)
    if m < 1e-9:
        return buf
    k = peak / m
    return [v * k for v in buf]


def write_wav(path, buf, peak=0.72):
    buf = fade(normalize(buf, peak))
    frames = bytearray()
    for v in buf:
        s = int(max(-32767, min(32767, round(v * 32767))))
        frames += struct.pack("<h", s)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(bytes(frames))
    return len(frames) + 44


# =========================================================
#  音效配方
#  统一风格：柔和的波形（sine / tri）+ 快速衰减 + 适量低通，
#  听起来"软、甜、不刺耳"，和黄粉色调的画面一致。
# =========================================================
def build_click():
    return mix(
        tone(0.055, 900, 1500, "sine", 0.85, attack=0.002, curve=9.0),
        tone(0.045, 1800, 1800, "sine", 0.22, attack=0.001, curve=14.0, delay=0.004),
    )


def build_deny():
    """不可用 / 没解锁 —— 低沉的两声"嗯嗯"。"""
    def blip(delay):
        return tone(0.085, 300, 250, "tri", 0.9, attack=0.005, curve=5.0,
                    lp=1400, delay=delay)
    return mix(blip(0.0), gain(blip(0.10), 0.75))


def build_panel_open():
    return seq(
        tone(0.075, 1046, 1046, "sine", 0.7, attack=0.003, curve=7.0),
        tone(0.075, 1318, 1318, "sine", 0.7, attack=0.003, curve=7.0),
        tone(0.10, 1568, 1568, "sine", 0.7, attack=0.003, curve=6.0),
    )


def build_panel_close():
    return seq(
        tone(0.075, 1568, 1568, "sine", 0.6, attack=0.003, curve=7.0),
        tone(0.075, 1318, 1318, "sine", 0.6, attack=0.003, curve=7.0),
        tone(0.10, 1046, 1046, "sine", 0.6, attack=0.003, curve=6.0),
    )


def build_feed():
    """喂食：两口"咔嚓 + 咕嘟"。"""
    bite = lambda p: mix(
        noise(0.055, 0.5, curve=11.0, lp=2600),
        tone(0.075, 210 + p, 160, "tri", 0.75, attack=0.004, curve=6.0, lp=1800),
    )
    return seq(bite(0), bite(-20), bite(10))


def build_drink():
    """喝水：咕嘟两下，带一点胸腔共鸣。"""
    gulp = lambda f, d: tone(0.10, f, f * 0.62, "sine", 0.85,
                             attack=0.008, curve=5.0, vib=14.0, vib_hz=13.0,
                             lp=1600, delay=d)
    return mix(
        gulp(430, 0.0), gulp(400, 0.14),
        tone(0.34, 150, 130, "sine", 0.18, attack=0.02, curve=3.0, lp=600),
    )


def build_pet():
    """抚摸：猫咪呼噜 + 一点甜星光。"""
    n = _samples(0.46)
    purr = []
    ph = 0.0
    trem = 0.0
    for i in range(n):
        p = i / n
        trem += math.tau * 22.0 / SR
        f = 148 + math.sin(trem) * 6.0
        ph += math.tau * f / SR
        a = osc("tri", ph) * (0.55 + 0.45 * math.sin(trem))
        purr.append(a)
    purr = lowpass(purr, 900)
    e = [min(1.0, i / (0.03 * SR)) * min(1.0, (n - i) / (0.10 * SR))
         for i in range(n)]
    purr = [v * ee * 0.9 for v, ee in zip(purr, e)]
    return mix(purr,
               [0.0] * _samples(0.16) + tone(0.26, 1568, 2093, "sine", 0.16,
                                            attack=0.01, curve=5.0))


def build_hug():
    """拥抱：暖暖的两声，像把人揽进怀里。"""
    return mix(
        tone(0.22, 392, 392, "sine", 0.8, attack=0.012, curve=4.0,
             harmonics=((2, 0.22), (3, 0.08))),
        tone(0.30, 523, 523, "sine", 0.8, attack=0.014, curve=3.4,
             harmonics=((2, 0.20), (3, 0.07)), delay=0.13),
    )


def build_play():
    """玩耍：弹跳的琶音。"""
    notes = (523, 659, 784, 1047)
    return mix(*[
        tone(0.14, f, f, "tri", 0.62, attack=0.004, curve=6.0,
             lp=3400, delay=i * 0.052, harmonics=((2, 0.18),))
        for i, f in enumerate(notes)
    ])


def build_sing():
    """唱歌：五声音阶的小句子。"""
    notes = ((523, 0.13), (587, 0.13), (659, 0.17), (784, 0.13), (880, 0.30))
    out = []
    t = 0.0
    for f, d in notes:
        out.append(tone(d + 0.06, f, f, "sine", 0.6, attack=0.02, curve=3.4,
                        vib=5.0, vib_hz=5.0, delay=t, harmonics=((2, 0.16),)))
        t += d * 0.92
    return mix(*out)


def build_bath():
    """洗澡：泡泡噗噗冒出来 + 水声。"""
    rng = random.Random(7)
    parts = [gain(noise(0.50, 1.0, attack=0.05, curve=2.4, lp=1500), 0.16)]
    t = 0.02
    f = 700
    while t < 0.46:
        parts.append(tone(0.075, f, f * 1.7, "sine", 0.45,
                          attack=0.004, curve=8.0, delay=t))
        t += rng.uniform(0.05, 0.10)
        f = rng.uniform(620, 1250)
    return mix(*parts)


def build_sleep():
    """睡觉：往下走的摇篮曲。"""
    notes = (659, 587, 523, 440)
    t = 0.0
    out = [tone(0.72, 110, 100, "sine", 0.14, attack=0.09, curve=1.6, lp=500)]
    for f in notes:
        out.append(tone(0.30, f, f, "sine", 0.52, attack=0.035, curve=2.6,
                        delay=t, harmonics=((2, 0.14),)))
        t += 0.16
    return mix(*out)


def build_wake():
    """叫醒：往上走的三声，亮一点。"""
    return mix(*[
        tone(0.20, f, f, "sine", 0.6, attack=0.008, curve=4.5,
             delay=i * 0.085, harmonics=((2, 0.24),))
        for i, f in enumerate((523, 659, 880))
    ])


def build_wear():
    """换装：一闪而过的魔法星光。"""
    return mix(*[
        tone(0.22, f, f * 1.04, "sine", 0.34, attack=0.002, curve=9.0,
             delay=i * 0.030)
        for i, f in enumerate((1046, 1318, 1568, 2093, 2637))
    ])


def build_unlock():
    """解锁新内容：四音上行 + 闪亮尾音。"""
    out = [
        tone(0.34, f, f, "sine", 0.55, attack=0.006, curve=5.0,
             delay=i * 0.075, harmonics=((2, 0.22), (3, 0.07)))
        for i, f in enumerate((523, 659, 784, 1046))
    ]
    out.append(tone(0.55, 1568, 1568, "sine", 0.30, attack=0.004, curve=6.0,
                    delay=0.30, harmonics=((2, 0.18),)))
    return mix(*out)


def build_pet_feed():
    """小宠物吃饭：比主角更"脆"的小口脆响。"""
    rng = random.Random(11)
    parts = []
    t = 0.0
    for _ in range(3):
        f = rng.uniform(380, 520)
        parts.append(mix(
            gain(noise(0.045, 1.0, curve=13.0, lp=3600), 0.34),
            tone(0.06, f, f * 0.7, "tri", 0.5, attack=0.003, curve=8.0,
                 delay=t, lp=2600),
        ))
        t += 0.085
    return mix(*parts)


def build_pet_play():
    """逗小宠物：吱吱叫的小玩具。"""
    return mix(
        tone(0.16, 680, 1500, "tri", 0.62, attack=0.004, curve=3.0, lp=4200),
        tone(0.10, 1500, 820, "tri", 0.45, attack=0.003, curve=5.5,
             lp=4200, delay=0.13),
    )


def build_pet_hug():
    """抱小宠物：软软的"喵呜"。"""
    return mix(
        tone(0.30, 620, 900, "tri", 0.55, attack=0.02, curve=1.8,
             vib=12.0, vib_hz=7.0, lp=2600),
        tone(0.24, 880, 700, "sine", 0.36, attack=0.03, curve=2.2,
             vib=10.0, vib_hz=7.0, delay=0.10, lp=2600),
    )


def build_whimper():
    """状态不佳的哼唧：软软地往下掉。"""
    n = _samples(0.40)
    buf = []
    ph = 0.0
    trem = 0.0
    for i in range(n):
        p = i / n
        f = 430 - 120 * p
        trem += math.tau * 6.5 / SR
        ph += math.tau * (f + math.sin(trem) * 9.0) / SR
        buf.append(osc("tri", ph) * (0.72 + 0.28 * math.sin(trem)))
    buf = [v * min(1.0, i / (0.05 * SR)) *
           min(1.0, (n - i) / (0.16 * SR)) * 0.85 for i, v in enumerate(buf)]
    return lowpass(buf, 1900)


def build_yawn():
    """犯困：一个长长的哈欠。"""
    n = _samples(0.62)
    buf = []
    ph = 0.0
    for i in range(n):
        p = i / n
        f = 300 + 260 * math.sin(p * math.pi)          # 先升后降
        ph += math.tau * f / SR
        buf.append(osc("sine", ph) * 0.6)
    buf = lowpass(buf, 1200)
    e = [math.sin(p * math.pi) for p in (i / n for i in range(n))]
    breath = lowpass(noise(0.62, 1.0, attack=0.06, curve=1.6, lp=900), 900)
    return mix([v * ee * 0.6 for v, ee in zip(buf, e)],
               gain(breath, 0.20))


SOUNDS = {
    "click": build_click,
    "deny": build_deny,
    "panel_open": build_panel_open,
    "panel_close": build_panel_close,
    "feed": build_feed,
    "drink": build_drink,
    "pet": build_pet,
    "hug": build_hug,
    "play": build_play,
    "sing": build_sing,
    "bath": build_bath,
    "sleep": build_sleep,
    "wake": build_wake,
    "wear": build_wear,
    "unlock": build_unlock,
    "pet_feed": build_pet_feed,
    "pet_play": build_pet_play,
    "pet_hug": build_pet_hug,
    "whimper": build_whimper,
    "yawn": build_yawn,
}

# 每个音效的播放音量微调（1.0 = 用 config.SFX_VOLUME 的基准）
VOLUME = {
    "click": 0.85, "deny": 0.9, "panel_open": 0.8, "panel_close": 0.75,
    "feed": 0.9, "drink": 0.85, "pet": 0.8, "hug": 0.85, "play": 0.85,
    "sing": 0.8, "bath": 0.8, "sleep": 0.75, "wake": 0.85, "wear": 0.7,
    "unlock": 0.9, "pet_feed": 0.85, "pet_play": 0.8, "pet_hug": 0.8,
    "whimper": 0.7, "yawn": 0.7,
}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    only = sys.argv[1:] or None
    total = 0
    for name, fn in sorted(SOUNDS.items()):
        if only and name not in only:
            continue
        buf = fn()
        if buf is None:
            continue
        path = os.path.join(OUT_DIR, name + ".wav")
        size = write_wav(path, buf, peak=0.72 * VOLUME.get(name, 1.0))
        total += size
        print("%-14s %6.2fs  %6.1f KB" % (name, len(buf) / SR, size / 1024.0))
    print("-" * 36)
    print("共 %d 个音效，合计 %.1f KB  →  %s"
          % (len(SOUNDS), total / 1024.0, OUT_DIR))


if __name__ == "__main__":
    main()
