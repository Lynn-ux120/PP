# -*- coding: utf-8 -*-
"""
sfx.py —— 音效播放层
=========================================================
设计原则：**音频出任何问题都不许影响游戏运行**。
手机上的音频后端千奇百怪（蓝牙耳机、被别的 App 抢占、静音模式…），
所以这里每一步都 try/except，拿不到设备就整个静音降级，游戏照常玩。

用法（main.py 里）：
    import sfx
    sfx.pre_init()            # ← 必须在 pygame.init() 之前
    ...
    sfx.init()                # pygame.init() 之后调
    sfx.play("click")         # 任何地方
    sfx.toggle_mute()         # 静音开关

音频文件由 tools/make_sfx.py 合成到 pet_game/sfx/*.wav。
想加音效：跑一次那个脚本 → 在 config 里引用名字即可。
"""
from __future__ import annotations

import json
import os
import sys

import pygame

from config import (SFX_BUFFER, SFX_RATE, SFX_VOLUME, SFX_MAX_CHANNELS,
                    SFX_MIN_GAP, SFX_CHANNELS)

# ---------------------------------------------------------
#  资源定位
# ---------------------------------------------------------
def _candidate_dirs() -> list:
    """音效目录可能的位置（桌面 / p4a 打包后 / 从别处启动）。"""
    out = []
    here = os.path.dirname(os.path.abspath(__file__))
    out.append(os.path.join(here, "sfx"))
    # p4a 会把应用解包到一个私有目录，sys.path 里通常能看到
    for p in list(sys.path):
        if not p:
            continue
        try:
            out.append(os.path.join(os.path.abspath(p), "sfx"))
        except OSError:
            pass
    # python-for-android 的环境变量
    for key in ("ANDROID_PRIVATE", "ANDROID_APP_PATH"):
        base = os.environ.get(key)
        if base:
            out.append(os.path.join(base, "sfx"))
    seen, uniq = set(), []
    for d in out:
        if d not in seen:
            seen.add(d)
            uniq.append(d)
    return uniq


# ---------------------------------------------------------
#  状态
# ---------------------------------------------------------
_available = False            # 音频设备是否可用
_muted = False                # 用户是否静音
_sounds: dict = {}            # name -> pygame.mixer.Sound
_last_play: dict = {}         # name -> 上次播放时刻（做去重）
_dir: str = ""
_error: str = ""


def _state_path() -> str | None:
    """
    静音开关的持久化位置。

    只在安卓上落盘（p4a 会给出可写的私有目录）；桌面调试时**不写**，
    免得在源码树里凭空多出一个状态文件。写不进去也不报错。
    """
    for key in ("ANDROID_PRIVATE", "ANDROID_APP_PATH"):
        base = os.environ.get(key)
        if base and os.path.isdir(base):
            return os.path.join(base, ".sfx_state.json")
    return None


def _load_state():
    global _muted
    path = _state_path()
    if not path:
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            _muted = bool(json.load(fh).get("muted", False))
    except Exception:
        pass


def _save_state():
    path = _state_path()
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"muted": _muted}, fh)
    except Exception:
        pass


# ---------------------------------------------------------
#  初始化
# ---------------------------------------------------------
def pre_init():
    """在 pygame.init() 之前调用：定好采样格式，避免中途重开音频设备。"""
    try:
        pygame.mixer.pre_init(SFX_RATE, -16, SFX_CHANNELS, SFX_BUFFER)
    except Exception:
        pass


def init() -> bool:
    """加载全部音效。返回是否成功（失败 = 静默模式，游戏照常）。"""
    global _available, _dir, _error

    _load_state()

    try:
        if pygame.mixer.get_init() is None:
            pygame.mixer.init(SFX_RATE, -16, SFX_CHANNELS, SFX_BUFFER)
    except Exception as exc:                     # 没声卡 / 被占用 / 服务不可用
        _available = False
        _error = "mixer init failed: %s" % exc
        return False

    try:
        pygame.mixer.set_num_channels(SFX_MAX_CHANNELS)
    except Exception:
        pass

    for d in _candidate_dirs():
        if os.path.isdir(d) and any(f.endswith(".wav") for f in os.listdir(d)):
            _dir = d
            break
    if not _dir:
        _available = False
        _error = "sfx dir not found"
        return False

    # 逐个加载；坏一个不影响其它
    for fn in sorted(os.listdir(_dir)):
        if not fn.lower().endswith(".wav"):
            continue
        name = os.path.splitext(fn)[0]
        try:
            _sounds[name] = pygame.mixer.Sound(os.path.join(_dir, fn))
        except Exception as exc:
            _error = "load %s failed: %s" % (fn, exc)

    _available = bool(_sounds)
    if not _available:
        _error = _error or "no sounds loaded"
    return _available


# ---------------------------------------------------------
#  播放
# ---------------------------------------------------------
def is_available() -> bool:
    return _available


def is_muted() -> bool:
    return _muted


def set_muted(flag: bool):
    global _muted
    _muted = bool(flag)
    _save_state()


def toggle_mute() -> bool:
    set_muted(not _muted)
    return _muted


def play(name, volume: float = 1.0, gap: float | None = None) -> bool:
    """
    播放一个音效。名字不存在 / 没音频 / 静音 → 安静地什么都不做。

    gap  同名音效的最小间隔（秒）。默认用 config.SFX_MIN_GAP。
         手机上连点按钮时，这能防止同一个音叠成噪音。
    """
    if not _available or _muted or not name:
        return False
    snd = _sounds.get(name)
    if snd is None:
        return False

    now = pygame.time.get_ticks() / 1000.0
    wait = SFX_MIN_GAP if gap is None else gap
    if wait > 0 and now - _last_play.get(name, -99.0) < wait:
        return False

    try:
        ch = pygame.mixer.find_channel()          # 全忙就放弃，不打断正在播的
        if ch is None:
            return False
        snd.set_volume(SFX_VOLUME * float(volume))
        ch.play(snd)
        _last_play[name] = now
        return True
    except Exception:
        return False


def play_any(names, **kw) -> bool:
    """按顺序尝试一组名字，播到第一个存在的就返回。"""
    for n in names:
        if n and n in _sounds and play(n, **kw):
            return True
    return False


def describe() -> str:
    if _available:
        return "sfx: ok  dir=%s  sounds=%d  muted=%s" % (
            _dir, len(_sounds), _muted)
    return "sfx: off (%s)" % (_error or "unknown")
