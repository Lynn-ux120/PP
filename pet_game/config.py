# -*- coding: utf-8 -*-
"""
config.py —— 全局配置中心
=========================================================
所有"魔法数字"都集中在这里：窗口尺寸、粉彩色板、数值衰减速度、
互动表格、按钮布局、台词文案……

想调玩法 / 换配色 / 加台词 / 加互动，只改这个文件就够了。

【新增互动的完整步骤】
  1. 在 INTERACTIONS 里加一行（id / 名称 / 快捷键 / 图标 / 数值增减 / 特效 / 台词）
  2. 如果用了新图标，去 ui.py 的 make_icon() 里补一个分支
  3. 如果用了新特效，去 effects.py 里加一个粒子类，并在 main.py 的
     _spawn_effect() 里加一个分支
  4. 在 SPEECH 里补上对应的台词池
就这四步，不用动主循环。

【新增一套衣装的步骤】
  只有一步：在下面的 OUTFITS 列表里加一条字典。
  版型（blouse / dress / sweater / overall）与发饰（flower / sakura /
  star / moon / ribbon / bear）都是现成的，配色随便改。

【新增一只小宠物的步骤】
  只有一步：在 COMPANIONS 列表里加一条字典。
  造型（cat / rabbit / shiba / bird）都是现成的。
【新增一种宠物互动的步骤】
  在 COMPANION_ACTIONS 里加一行 + 在 SPEECH 里补台词池。
"""
import math

# =========================================================
#  窗口 & 循环
# =========================================================
TITLE            = "高紫桐的小屋 · 2D 宠物养成"
WIDTH, HEIGHT    = 640, 800
FPS              = 60
MAX_DT           = 0.05        # 单帧最大步长，防止窗口拖动后数值暴跌
CHAR_SUPERSAMPLE = 3           # 角色超采样倍率（越大越平滑，3 已足够）

# ---------------------------------------------------------
#  移动端 / 显示适配（见 platform_util.DisplayManager）
# ---------------------------------------------------------
# None = 自动：安卓全屏铺满，桌面保持 640x800 窗口（方便调试）
FULLSCREEN_MODE   = None

# 手机缩放时的插值方式 ★ 性能开关 ★
#   True  = 平滑插值（smoothscale）。画面细腻，但 640x800 → 1080x1350
#           这种放大在手机 CPU 上要 20~40 ms/帧，是掉帧的头号元凶。
#   False = 最近邻（scale）。实测快 3~6 倍；640x800 放到 1080p 上，
#           粉彩画的锯齿几乎看不出来（文字边缘会稍硬一点）。
# 默认 False；如果你的机器很新、想要最细腻的画面，可以改回 True。
MOBILE_SMOOTH_SCALE = False

# 手机上的目标帧率。手机屏幕刷新率五花八门，
# 与其追求 60 帧而不断掉帧，不如稳在 50（掉帧感更小）。
# 想更省电可以调到 40 或 30。
MOBILE_FPS = 50

# ★ 最重要的性能开关 ★
# 手机显示走 GPU 缩放（pygame.SCALED）：逻辑画布交给 SDL 的渲染器放大到整屏，
# CPU 完全不参与缩放 —— 比软件缩放省下每帧 20~40 ms，是"手机上能不能跑顺"
# 的关键。逻辑画布会和屏幕做成同比例，游戏画面居中，上下多出来的部分用
# 天空色 / 草地色填平（看上去就是一整屏）。
#
# 万一某些机型的渲染器建不出来，platform_util 会自动检测并退回软件缩放，
# 不会黑屏、不会崩。若真的遇到画面异常，把这里改成 False 再重新打包即可。
MOBILE_USE_SCALED = True

# =========================================================
#  音效 ★ 想加/换音效就改这里 ★
# ---------------------------------------------------------
# 音频文件由 tools/make_sfx.py 用纯 Python 合成到 pet_game/sfx/*.wav
# （不需要 numpy，也不依赖任何外部素材）。
#
# 【换一个互动音】把 INTERACTIONS / COMPANION_ACTIONS 那一行的
#   sfx="..." 改成 tools/make_sfx.py 里 SOUNDS 的键名即可。
# 【加一个全新音效】在 make_sfx.py 里写个 build_xxx()，
#   加进 SOUNDS 表，跑一次脚本，再来这里引用。
# =========================================================
SFX_ENABLED       = True       # 总开关（关掉 = 完全不初始化音频设备）
SFX_VOLUME        = 0.75       # 主音量基准（每个音效还会再乘自己的系数）
SFX_RATE          = 22050      # 采样率，必须和 make_sfx.py 的 SR 一致
SFX_CHANNELS      = 1          # 单声道（音效不需要立体声，省一半内存）
# 音频缓冲。太小会爆音、太大会有延迟。手机上 1024 帧 ≈ 46 ms，是稳妥值。
SFX_BUFFER        = 1024
SFX_MAX_CHANNELS  = 16         # 同时最多混几个音
SFX_MIN_GAP       = 0.045      # 同名音效的最小重播间隔，防止连点叠成噪音
SFX_DUCK_CHANCE   = 0.0        # 预留：将来做背景音乐闪避用

# 状态不佳时的软哼唧（键名对应 Pet._mood_key()）
MOOD_SFX = {
    "hungry":   "whimper",
    "unhappy":  "whimper",
    "sleepy":   "yawn",
    "critical": "whimper",
}
# 播放这些心情音的最小间隔（秒）—— 哼唧太频繁会烦人
MOOD_SFX_GAP = 14.0

# 非互动类音效（界面反馈 / 解锁 / 摸小宠物）
UI_CLICK_SFX    = "click"        # 普通按钮
UI_DENY_SFX     = "deny"         # 按钮不可用、衣服/宠物没解锁
PANEL_OPEN_SFX  = "panel_open"   # 打开衣橱 / 宠物面板
PANEL_CLOSE_SFX = "panel_close"  # 关闭面板 / 安卓返回键收起面板
WEAR_SFX        = "wear"         # 换装成功
UNLOCK_SFX      = "unlock"       # 解锁新衣装 / 新宠物
COMP_TOUCH_SFX  = "pet_hug"      # 直接摸草地上的小宠物

# 左上角"音效开关"小按钮（标题左边那块空白）
SFX_BTN_RECT = (14, 14, 44, 38)

# =========================================================
#  宠物
# =========================================================
PET_NAME    = "高紫桐"
PET_BOX_W   = 260              # 角色逻辑画布尺寸（内部坐标系）
PET_BOX_H   = 300
PET_CENTER  = (WIDTH // 2, 466)   # 角色画布中心在屏幕上的位置
GROUND_Y    = 596              # 草地顶边

# =========================================================
#  数值系统（核心玩法参数）
# =========================================================
STAT_MAX          = 100.0
INIT_HUNGER       = 78.0       # 初始饱腹值
INIT_HAPPINESS    = 82.0       # 初始快乐值
INIT_ENERGY       = 74.0       # 初始精力值

HUNGER_DECAY      = 1.10       # 饱腹值每秒自然下降
HAPPINESS_DECAY   = 0.80       # 快乐值每秒自然下降
ENERGY_DECAY      = 0.55       # 精力值每秒自然下降

LOW_THRESHOLD     = 28.0       # 低于此值 → 难过 / 犯困表情
MID_THRESHOLD     = 52.0       # 低于此值 → 无聊 / 平淡表情

# —— 睡觉 ——
SLEEP_DURATION    = 6.0        # 一次睡觉持续秒数
SLEEP_ENERGY_RATE = 11.5       # 睡觉时精力每秒回复量（6s 约 +69）
SLEEP_DECAY_MUL   = 0.25       # 睡觉时饱腹/快乐的衰减倍率

REACTION_TIME     = 1.5        # 默认"开心表情"保持秒数

# 三围数值的键名（顺序 = 数值条从上到下的顺序）
STAT_KEYS = ("hunger", "happiness", "energy")

# =========================================================
#  动作系统 ★ 想加小动作就改这里 ★
# ---------------------------------------------------------
#  动作曲线本身写在 motion.py（只描述"节奏"），这里只声明
#  "角色在什么情况下播哪条曲线、说什么话、冒什么粒子"。
#
#  【待机小动作】闲着没事时会自动挑一个播，改 PET_ANTICS 即可：
#    motion    motion.py 里的曲线名（stretch / hop / sway / tilt …）
#    dur       动作时长区间（秒），每次随机取
#    weight    相对权重，越大越常播
#    effect    顺带播放的粒子名（交给 main._spawn_effect），None 则不播
#    speech    SPEECH 里的台词池名，None 则安静
#    next      这次播完隔多久再考虑下一个（秒区间）
#  【互动动作】在 INTERACTIONS 的每一项上加一行 motion=("曲线名", 秒数)
#  【心情专属动作】PET_MOOD_ANTICS：某个表情下只准播这几个动作
# =========================================================
PET_ANTICS = [
    dict(id="stretch", motion="stretch", dur=(1.5, 1.9), weight=16.0,
         effect="sparkle", speech="antic_stretch", next=(7.0, 12.0)),
    dict(id="sway", motion="sway", dur=(1.6, 2.2), weight=15.0,
         effect="music", speech="antic_sway", next=(7.0, 12.0)),
    dict(id="hop", motion="hop", dur=(1.0, 1.4), weight=13.0,
         effect="sparkle", speech="antic_hop", next=(6.0, 10.0)),
    dict(id="tilt", motion="tilt", dur=(1.6, 2.2), weight=20.0,
         effect=None, speech="antic_tilt", next=(6.0, 11.0)),
    dict(id="twirl", motion="twirl", dur=(1.2, 1.5), weight=10.0,
         effect="sparkle", speech="antic_twirl", next=(9.0, 15.0)),
    dict(id="squat", motion="squat", dur=(1.9, 2.5), weight=12.0,
         effect=None, speech="antic_squat", next=(8.0, 13.0)),
    dict(id="shiver", motion="shiver", dur=(1.0, 1.4), weight=7.0,
         effect=None, speech="antic_shiver", next=(6.0, 10.0)),
    dict(id="doze", motion="nod", dur=(1.8, 2.4), weight=8.0,
         effect=None, speech=None, next=(8.0, 13.0)),
]
PET_ANTIC_MAP = {a["id"]: a for a in PET_ANTICS}

# 场景首次触发待机动作前的等待、以及"什么表情下只播哪些动作"
ANTIC_FIRST_GAP = (3.5, 7.0)
PET_MOOD_ANTICS = {
    "sad":   ["shiver"],       # 难过时只会缩着抖
    "tired": ["doze"],         # 犯困时只会打瞌睡
    "meh":   ["tilt", "shiver"],   # 无聊时安静一点
}

# =========================================================
#  互动表格 ★ 想加互动就改这里 ★
# ---------------------------------------------------------
#  gain      数值增减（正=恢复，负=消耗）；键名见 STAT_KEYS
#  cooldown  冷却秒数
#  require   前置条件，数值低于该值时按钮灰显
#  effect    交给 main.py 决定播放哪种粒子特效
#  react_time 互动后保持开心表情的秒数
#  motion    (motion.py 的曲线名, 秒数) —— 互动时顺带做的小动作
#  btn       (底色, 悬停色, 描边色, 文字色, 图标色)
# =========================================================
INTERACTIONS = [
    dict(id="feed", label="喂食", hotkey="F", icon="bowl",
         gain={"hunger": 26.0}, cooldown=0.45, require={},
         effect="food", speech="feed", react_time=1.5, sfx="feed",
         motion=("nod", 1.0),
         btn=((255, 214, 158), (255, 229, 186), (233, 176, 112),
              (126, 92, 58), (238, 176, 104))),

    dict(id="drink", label="喝水", hotkey="D", icon="drop",
         gain={"hunger": 9.0, "energy": 8.0}, cooldown=0.45, require={},
         effect="water", speech="drink", react_time=1.3,
         motion=("sip", 1.2),
         btn=((188, 224, 246), (214, 238, 252), (146, 196, 228),
              (66, 104, 132), (112, 176, 226))),

    dict(id="pet", label="抚摸", hotkey="P", icon="hand",
         gain={"happiness": 20.0}, cooldown=0.15, require={},
         effect="heart", speech="pet", react_time=1.5,
         motion=("sway", 1.3),
         btn=((255, 182, 206), (255, 206, 222), (233, 142, 176),
              (128, 74, 100), (242, 134, 168))),

    dict(id="hug", label="拥抱", hotkey="H", icon="hug",
         gain={"happiness": 15.0, "energy": 7.0}, cooldown=0.60, require={},
         effect="hug", speech="hug", react_time=1.8,
         motion=("squeeze", 1.5),
         btn=((255, 172, 178), (255, 202, 206), (232, 132, 140),
              (132, 72, 76), (232, 116, 126))),

    dict(id="play", label="玩耍", hotkey="Y", icon="ball",
         gain={"happiness": 30.0, "energy": -17.0}, cooldown=1.00,
         require={"energy": 16.0},
         effect="play", speech="play", react_time=2.0, sfx="play",
         motion=("hop", 1.3),
         btn=((176, 226, 208), (206, 240, 226), (134, 198, 176),
              (52, 110, 92), (110, 198, 172))),

    dict(id="sing", label="唱歌", hotkey="G", icon="note",
         gain={"happiness": 22.0, "energy": -9.0}, cooldown=0.80,
         require={"energy": 8.0},
         effect="music", speech="sing", react_time=1.9, sfx="sing",
         motion=("sway", 1.9),
         btn=((214, 196, 240), (232, 220, 250), (180, 156, 216),
              (98, 74, 140), (168, 140, 214))),

    dict(id="bath", label="洗澡", hotkey="B", icon="bubble",
         gain={"happiness": 12.0, "energy": 6.0}, cooldown=1.20, require={},
         effect="bubble", speech="bath", react_time=1.6,
         motion=("shake", 1.5),
         btn=((178, 226, 232), (208, 240, 244), (136, 196, 204),
              (56, 108, 116), (110, 190, 200))),

    dict(id="sleep", label="睡觉", hotkey="S", icon="moon",
         gain={}, cooldown=0.60, require={},
         effect="sleep", speech="sleep", react_time=0.0,
         btn=((196, 200, 238), (220, 224, 250), (156, 162, 214),
              (84, 88, 150), (140, 148, 210))),
]
INTERACTION_MAP = {i["id"]: i for i in INTERACTIONS}

# =========================================================
#  粉彩色板（Pastel）
# =========================================================
# —— 背景 ——
BG_TOP        = (255, 246, 251)   # 天空·淡樱花粉
BG_BOTTOM     = (255, 252, 238)   # 天空·淡奶油黄
CLOUD         = (255, 255, 255)
BOKEH_1       = (255, 232, 242)
BOKEH_2       = (232, 240, 255)
BOKEH_3       = (255, 248, 226)
GROUND        = (205, 236, 221)   # 草地·薄荷绿
GROUND_DEEP   = (182, 224, 205)
GRASS_LINE    = (170, 216, 194)

# —— 面板 / 文字 ——
PANEL         = (255, 253, 251)
PANEL_EDGE    = (246, 228, 236)
PANEL_SHADOW  = (236, 216, 226)
TEXT          = (120, 102, 118)
TEXT_LIGHT    = (178, 164, 180)
TEXT_SOFT     = (206, 192, 206)

# —— 主题色 ——
PINK          = (255, 168, 192)
PINK_DEEP     = (242, 134, 168)
PINK_SOFT     = (255, 214, 228)
LILAC         = (204, 178, 236)   # 呼应名字里的"紫"
LILAC_DEEP    = (168, 140, 214)
MINT          = (146, 220, 198)
MINT_DEEP     = (110, 198, 172)
BUTTER        = (255, 212, 148)
BUTTER_DEEP   = (238, 176, 104)
SKY           = (150, 206, 240)   # 呼应"精力值"
SKY_DEEP      = (112, 176, 226)

# —— 数值条 ——
BAR_HUNGER_BG = (255, 235, 216)
BAR_HUNGER_FG = (255, 186, 112)
BAR_HAPPY_BG  = (255, 228, 239)
BAR_HAPPY_FG  = (255, 150, 184)
BAR_ENERGY_BG = (226, 242, 252)
BAR_ENERGY_FG = (150, 206, 240)
BAR_LOW_FG    = (255, 138, 138)   # 数值告急时的颜色
BAR_TRACK_EDGE= (255, 255, 255)

# =========================================================
#  角色配色
# =========================================================
C_SKIN        = (255, 233, 221)
C_SKIN_SHADE  = (246, 210, 196)
C_HAIR        = (58, 50, 64)      # 发色·深棕黑
C_HAIR_DARK   = (44, 38, 52)
C_HAIR_LIGHT  = (108, 94, 118)    # 发丝高光
C_EYE         = (54, 44, 58)
C_SHIRT       = (255, 255, 255)
C_SHIRT_SHADE = (238, 240, 248)
C_LACE        = (214, 208, 232)
C_BLUSH       = (255, 146, 168)
C_MOUTH       = (214, 122, 132)
C_TONGUE      = (255, 158, 168)
C_TEAR        = (156, 208, 240)

# =========================================================
#  衣装系统 ★ 想加衣服就改这里 ★
# ---------------------------------------------------------
#  一件衣服 = 一条字典，全部字段都有默认含义，绘制代码不用改：
#    id / name / hint   标识 / 卡片标题 / 卡片上的一句话
#    unlock             解锁条件（None = 一开始就有）
#                         {"stat": "energy", "gte": 92}  某数值曾达到过
#                         {"stat_all": 90}                三条数值曾同时达到
#                         {"interactions": 25}            累计互动次数
#    style              版型 blouse(衬衫) / dress(连衣裙)
#                            sweater(毛衣) / overall(背带裙)
#    cloth / shad       衣服主色 / 暗部色
#    inner              内搭色（背带裙的白 T 用）
#    trim               领口、蕾丝、腰带等点缀色
#    bow                领口蝴蝶结颜色（None = 不画）
#    tie                发圈颜色
#    shoe               鞋子颜色
#    pin                发饰 flower / sakura / star / moon / ribbon / bear
#    pin_main/pin_accent 发饰主色 / 点缀色
#    pattern            衣服图案 none / star / flower / bear
#    accent             图案、扣子的颜色
#
#  【新增一套衣服】在下面列表里加一条字典即可，
#   绘制会自动套用；不需要写新的绘制函数。
# =========================================================
OUTFITS = [
    # ---- ① 默认：还原照片里的白衬衫 ----
    dict(id="classic", name="经典白裙", hint="最初的样子",
         unlock=None, style="blouse",
         cloth=(255, 255, 255), shad=(232, 236, 246), inner=(255, 255, 255),
         trim=C_LACE, bow=PINK, tie=PINK, shoe=(226, 214, 240),
         pin="flower", pin_main=PINK, pin_accent=BUTTER,
         pattern="none", accent=BUTTER),

    # ---- ② 樱花和服 ----
    dict(id="sakura", name="樱花和服", hint="粉粉的和风小袖",
         unlock=None, style="dress",
         cloth=(255, 202, 218), shad=(244, 170, 196), inner=(255, 255, 255),
         trim=(255, 240, 246), bow=(232, 140, 170), tie=(232, 140, 170),
         shoe=(250, 216, 226),
         pin="sakura", pin_main=(255, 178, 204), pin_accent=(255, 238, 244),
         pattern="flower", accent=(255, 244, 248)),

    # ---- ③ 星夜连衣裙（精力满过才解锁）----
    dict(id="starry", name="星夜连衣裙", hint="把整片夜空穿在身上",
         unlock={"stat": "energy", "gte": 92}, style="dress",
         cloth=(104, 112, 176), shad=(84, 92, 154), inner=(255, 255, 255),
         trim=(206, 212, 248), bow=(150, 140, 214), tie=(150, 140, 214),
         shoe=(126, 132, 196),
         pin="moon", pin_main=(255, 236, 176), pin_accent=(255, 250, 226),
         pattern="star", accent=(255, 232, 160)),

    # ---- ④ 薄荷背带裙（喂饱她）----
    dict(id="mint", name="薄荷背带裙", hint="清清爽爽的放学装",
         unlock={"stat": "hunger", "gte": 92}, style="overall",
         cloth=(150, 216, 196), shad=(124, 194, 174), inner=(255, 255, 255),
         trim=(110, 190, 168), bow=None, tie=(110, 190, 168),
         shoe=(214, 240, 230),
         pin="ribbon", pin_main=(162, 222, 204), pin_accent=(255, 255, 255),
         pattern="none", accent=(255, 214, 158)),

    # ---- ⑤ 紫罗兰洋装（多陪陪她）----
    dict(id="lilac", name="紫罗兰洋装", hint="带荷叶边的优雅小礼服",
         unlock={"interactions": 25}, style="dress",
         cloth=(206, 180, 238), shad=(180, 152, 216), inner=(255, 255, 255),
         trim=(245, 238, 252), bow=(168, 140, 214), tie=(168, 140, 214),
         shoe=(192, 166, 228),
         pin="ribbon", pin_main=(204, 178, 236), pin_accent=(255, 255, 255),
         pattern="none", accent=(168, 140, 214)),

    # ---- ⑥ 熊熊连体服（三项数值同时拉满过）----
    dict(id="bear", name="熊熊连体服", hint="毛茸茸的暖冬款",
         unlock={"stat_all": 90}, style="sweater",
         cloth=(242, 216, 180), shad=(222, 192, 154), inner=(255, 255, 255),
         trim=(206, 172, 132), bow=None, tie=(222, 176, 138),
         shoe=(214, 184, 148),
         pin="bear", pin_main=(242, 216, 180), pin_accent=(190, 152, 116),
         pattern="bear", accent=(176, 136, 100)),
]
OUTFIT_MAP = {o["id"]: o for o in OUTFITS}

_STAT_LABEL = {"hunger": "饱腹", "happiness": "快乐", "energy": "精力"}


def unlock_text(cond) -> str:
    """把解锁条件翻译成卡片上那句人话。"""
    if not cond:
        return ""
    if "stat" in cond:
        return f"{_STAT_LABEL.get(cond['stat'], cond['stat'])}曾达 {int(cond['gte'])}"
    if "stat_all" in cond:
        return f"三值曾同时达 {int(cond['stat_all'])}"
    if "interactions" in cond:
        return f"互动累计 {int(cond['interactions'])} 次"
    return "尚未解锁"


# —— 衣橱面板布局 ——
WARDROBE_BTN_RECT = (532, 12, 92, 38)      # 右上角"衣装"按钮
WARDROBE_PANEL    = (52, 128, 536, 512)    # 弹出的衣橱面板
CARD_W, CARD_H    = 152, 198
CARD_GAP_X        = 12
CARD_GAP_Y        = 14
CARD_COLS         = 3
WARDROBE_GRID_TOP = 216
CARD_THUMB_SIZE   = (98, 132)

# =========================================================
#  小宠物系统 ★ 想加宠物就改这里 ★
# ---------------------------------------------------------
#  主角身边养着一只小动物：它有独立数值（亲密 / 饱腹 / 心情）、
#  自己的 AI（闲逛 / 坐下 / 打盹 / 追蝴蝶 / 跑来蹭主角），
#  以及完全由代码绘制的造型。
#
#  【新增一只小宠物】在 COMPANIONS 里加一条字典，
#   造型 kind 用现成的 cat / rabbit / shiba / bird 即可。
#  【新增一种宠物互动】在 COMPANION_ACTIONS 里加一行。
#  【调数值】改下面 COMP_* 那几个常量。
# =========================================================
COMPANION_START   = "cat"          # 一开始陪着她的小宠物
COMP_SCALE        = 1.14           # 小宠物的整体缩放（相对主角的身量感）

COMP_MAX          = 100.0
COMP_INIT         = dict(bond=16.0, belly=78.0, mood=84.0)
COMP_BELLY_DECAY  = 0.85           # 宠物饱腹每秒下降（亲密不衰减：感情不会变淡）
COMP_MOOD_DECAY   = 0.55           # 宠物心情每秒下降
COMP_LOW          = 26.0           # 低于此值 → 宠物蔫掉
COMP_SEEK_BELLY   = 34.0           # 饱腹低于此值 → 会跑去主角身边讨食

COMP_STAT_KEYS    = ("bond", "belly", "mood")
COMP_STAT_LABEL   = {"bond": "亲密", "belly": "饱腹", "mood": "心情"}
COMP_STAT_ICON    = {"bond": "paw", "belly": "cookie", "mood": "heart"}
COMP_STAT_FG      = {"bond": (255, 168, 208), "belly": (255, 190, 130),
                     "mood": (198, 176, 240)}
COMP_STAT_BG      = {"bond": (255, 232, 242), "belly": (255, 238, 220),
                     "mood": (236, 230, 250)}
COMP_STAT_COLOR   = {"bond": PINK_DEEP, "belly": BUTTER_DEEP, "mood": LILAC_DEEP}

# —— 宠物互动表（结构和 INTERACTIONS 一样，只是数值作用在宠物身上）——
#  gain       作用于小宠物的数值增减（键名 bond / belly / mood）
#  host_gain  顺带作用于主角的数值增减（陪它玩，她也开心）
#  cooldown   冷却秒数
#  effect     交给 main.py 决定播放哪种粒子特效
#  btn        (底色, 悬停色, 描边色, 文字色, 图标色)
COMPANION_ACTIONS = [
    dict(id="cfood", label="投喂", hotkey="1", icon="cookie",
         gain={"belly": 28.0, "mood": 9.0, "bond": 4.0}, cooldown=0.5,
         host_gain={"happiness": 2.0},
         effect="cfood", speech="cfood", motion=("nod", 0.9),
         btn=((255, 222, 178), (255, 236, 204), (232, 184, 128),
              (124, 92, 56), (232, 176, 104))),

    dict(id="ctoy", label="逗它", hotkey="2", icon="yarn",
         gain={"mood": 27.0, "bond": 10.0, "belly": -4.0}, cooldown=0.9,
         host_gain={"happiness": 5.0},
         effect="ctoy", speech="ctoy", motion=("spin", 1.2), sfx="pet_play",
         btn=((186, 220, 246), (212, 236, 250), (140, 190, 224),
              (62, 104, 134), (120, 178, 228))),

    dict(id="chug", label="抱抱", hotkey="3", icon="paw",
         gain={"bond": 15.0, "mood": 12.0}, cooldown=0.6,
         host_gain={"happiness": 6.0},
         effect="chug", speech="chug", motion=("squeeze", 1.3), sfx="pet_hug",
         btn=((255, 186, 208), (255, 210, 226), (234, 146, 178),
              (128, 74, 100), (240, 138, 172))),
]
COMPANION_ACTION_MAP = {a["id"]: a for a in COMPANION_ACTIONS}

# —— 小宠物的行为权重表 ★ 想改它的性格就改这里 ★ ——
#  每次"想换个玩法"时按 weight 抽一条：
#    walk_near / walk_far  在主角附近溜达 / 跑去远处逛
#    sit                   坐下歇会儿
#    groom / stretch / roll / spin / dig  原地小动作（见 motion.py）
#    chase                 追蝴蝶
#    sleep                 打个盹
#  想让它更活泼 → 提高动作类的权重；想让它更黏人 → 提高 walk_near。
COMP_AI_TABLE = [
    dict(id="walk_near", weight=32.0, dur=(6.0, 9.0)),
    dict(id="walk_far", weight=11.0, dur=(7.0, 10.0)),
    dict(id="sit", weight=11.0, dur=(2.0, 4.6)),
    dict(id="groom", weight=8.0, dur=(2.4, 3.6)),
    dict(id="stretch", weight=7.0, dur=(1.7, 2.1)),
    dict(id="roll", weight=6.0, dur=(1.9, 2.5)),
    dict(id="spin", weight=6.0, dur=(1.8, 2.6)),
    dict(id="dig", weight=5.0, dur=(1.9, 2.7)),
    dict(id="chase", weight=10.0, dur=(4.5, 5.5)),
    dict(id="sleep", weight=2.0, dur=(3.0, 6.5)),
]

# —— 四种小宠物 ——
#  unlock 条件键名：{"bond": 60} 亲密度曾达 / {"actions": 25} 互动累计 /
#                   {"all": 88} 三值曾同时达
COMPANIONS = [
    dict(id="cat", name="咪咪", kind="cat", hint="懒洋洋的三花猫", unlock=None,
         body=(255, 242, 234), patch=(255, 200, 168), tummy=(255, 253, 248),
         ear=(255, 198, 178), inner=(255, 156, 172), tail=(255, 200, 168),
         nose=(255, 156, 168), accent=(255, 214, 162)),

    dict(id="rabbit", name="豆豆", kind="rabbit", hint="软乎乎的垂耳兔",
         unlock={"bond": 60},
         body=(255, 250, 246), patch=(240, 236, 248), tummy=(255, 255, 255),
         ear=(238, 230, 244), inner=(255, 184, 200), tail=(240, 234, 246),
         nose=(255, 170, 186), accent=(255, 206, 220)),

    dict(id="shiba", name="团子", kind="shiba", hint="爱笑的柴犬宝宝",
         unlock={"actions": 25},
         body=(255, 214, 158), patch=(246, 190, 128), tummy=(255, 252, 244),
         ear=(246, 182, 116), inner=(238, 176, 158), tail=(250, 208, 150),
         nose=(96, 78, 74), accent=(255, 176, 128)),

    dict(id="bird", name="啾啾", kind="bird", hint="叽叽喳喳的小肥鸟",
         unlock={"all": 88},
         body=(178, 220, 246), patch=(140, 198, 240), tummy=(255, 252, 240),
         ear=(168, 212, 244), inner=(255, 208, 150), tail=(150, 204, 240),
         nose=(255, 190, 96), accent=(255, 208, 150)),
]
COMPANION_MAP = {c["id"]: c for c in COMPANIONS}


def comp_unlock_text(cond) -> str:
    """把宠物的解锁条件翻译成卡片上那句人话。"""
    if not cond:
        return ""
    if "bond" in cond:
        return f"亲密度曾达 {int(cond['bond'])}"
    if "actions" in cond:
        return f"互动累计 {int(cond['actions'])} 次"
    if "all" in cond:
        return f"三值曾同时达 {int(cond['all'])}"
    return "尚未解锁"


# —— 宠物面板布局 ——
COMPANION_BTN_RECT = (532, 54, 92, 38)      # 右上角"宠物"按钮（在衣装下方）
COMPANION_PANEL    = (52, 128, 536, 476)    # 弹出的宠物面板
COMP_CARD_W, COMP_CARD_H = 112, 150
COMP_CARD_GAP      = 12
COMP_CARD_TOP      = 92        # 以下均为"相对面板顶部"的偏移
COMP_THUMB_SIZE    = (86, 86)
COMP_BAR_TOP       = 256
COMP_BAR_H         = 24
COMP_BAR_ROW       = 32
COMP_ACT_TOP       = 376
COMP_ACT_W, COMP_ACT_H = 150, 52
COMP_ACT_GAP       = 14

# =========================================================
#  按钮网格（2 行 × 4 列）
# =========================================================
BTN_W         = 138
BTN_H         = 56
BTN_GAP_X     = 10
BTN_GAP_Y     = 8
BTN_COLS      = 4
BTN_GRID_LEFT = 28          # 第一列的左边缘
BTN_GRID_TOP  = 654         # 第一行的上边缘

BTN_PANEL_RECT = (16, 642, WIDTH - 32, 156)

# =========================================================
#  UI 布局
# =========================================================
STAT_PANEL_RECT = (28, 94, WIDTH - 56, 140)
STAT_ROWS       = (110, 154, 198)     # 三条数值条的 y
STAT_BAR_X      = 168
STAT_BAR_W      = 360
STAT_BAR_H      = 26
STAT_LABEL_X    = 100
STAT_ICON_X     = 66

STAT_TEXT_COLOR = {
    "hunger":    BUTTER_DEEP,
    "happiness": PINK_DEEP,
    "energy":    SKY_DEEP,
}

# =========================================================
#  台词（可自由扩充：每个互动 / 每种心情一个池子）
# =========================================================
SPEECH = {
    # —— 互动 ——
    "feed":     ["谢谢投喂～♪", "好次！好次！", "还要还要～", "唔…好香呀"],
    "drink":    ["咕嘟咕嘟…", "水甜甜的～", "喝完啦！", "喉咙舒服多了"],
    "pet":      ["嘿嘿…好舒服", "再摸摸嘛～", "最喜欢你啦", "呼噜呼噜～"],
    "hug":      ["抱住！不放开～", "暖暖的…", "有你真好", "再抱一会儿嘛"],
    "play":     ["接住啦！再来！", "跑呀跑呀～", "哈哈哈好开心！", "这个好好玩！"],
    "sing":     ["啦～啦啦♪", "这首歌送给你", "一起来唱嘛～", "我今天心情超好"],
    "bath":     ["泡泡好多呀", "香香的～", "洗完滑溜溜！", "水温刚刚好"],
    "sleep":    ["晚安…zzZ", "我去睡一小会儿～", "困了…", "梦里也要见到你"],
    "wake":     ["唔…醒啦", "睡得好饱～", "早上好呀！", "精神满满了！"],
    # —— 状态 ——
    "hungry":   ["肚子…好饿呀", "咕噜噜…", "想吃小饼干…"],
    "unhappy":  ["有点无聊呢…", "陪陪我好不好", "想要抱抱…"],
    "sleepy":   ["哈欠…好困", "眼皮好重…", "想睡一会儿…"],
    "critical": ["呜…好难受", "快要撑不住了…"],
    "idle":     ["今天也要加油哦", "你在忙什么呀？", "阳光好暖和～"],
    # —— 待机小动作（闲着没事时自己冒出来的话）——
    "antic_stretch": ["嗯——伸个懒腰", "胳膊有点酸酸的…", "（伸展）舒服多了"],
    "antic_sway":    ["哼哼～♪", "今天心情真好", "（摇摇摆摆）"],
    "antic_hop":     ["嘿咻！", "蹦蹦跳跳～", "看我跳得多高！"],
    "antic_tilt":    ["嗯？怎么了？", "（歪歪头）", "那边有什么呀"],
    "antic_twirl":   ["转圈圈～", "裙子飞起来啦！", "旋～转～"],
    "antic_shiver":  ["呜…有点凉", "（缩了缩）", "抱抱自己…"],
    "antic_squat":   ["蹲一会儿…", "（抱着膝盖坐下）", "这里晒得到太阳"],
    # —— 小宠物 ——
    "cfood":    ["喵呜～好次！", "嘎吱嘎吱…", "呼噜呼噜～", "还有没有嘛"],
    "ctoy":     ["（扑过去）抓到啦！", "诶诶别跑～", "再来一次嘛！", "这个最好玩了"],
    "chug":     ["蹭蹭你～", "呼噜呼噜…", "抱紧一点点", "暖乎乎的"],
    "chungry":  ["肚子叫了…", "想吃小饼干…", "呜…有点饿"],
    "clonely":  ["陪我玩一会儿嘛", "有点无聊…", "你在看哪里呀"],
    "cgreet":   ["我回来陪你啦！", "今天也多多关照～", "（摇尾巴）"],
    # —— 小宠物的自娱自乐（偶尔才会出声）——
    "cgroom":   ["舔舔…", "（认真地梳理毛发）", "要干干净净的"],
    "cstretch": ["（伸了个懒腰）呼～", "骨头好舒服", "（前爪伸直）"],
    "croll":    ["（滚来滚去）", "咕噜噜～", "地上凉凉的，舒服"],
    "cspin":    ["（追着自己的尾巴）", "抓住你啦！", "转转转～"],
    "cdig":     ["（刨刨刨）", "藏点好东西在这里", "这里埋起来"],
}

# =========================================================
#  草地起伏曲线（背景、角色、小宠物共用同一条地面）
# =========================================================
def ground_top(x: float) -> float:
    """给定 x 返回草地的顶边 y。"""
    return GROUND_Y + math.sin(x * 0.017) * 7 + math.sin(x * 0.041 + 1.3) * 3

# =========================================================
#  调试
# =========================================================
SHOW_FPS = False
