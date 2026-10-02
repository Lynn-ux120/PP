# PP · 高紫桐的小屋

一个用 **Python + Pygame** 手写的 2D 宠物养成小游戏，并且已经改造为**可以直接打包成安卓 APK、在手机上安装运行**。

主角形象参考 `pphoto.jpg`，**全部用代码绘制**（超采样画笔 + 贴纸描边），不依赖任何美术素材。

---

## 一、手机上怎么装

### 1. 云端自动出包（推荐，Windows 也能用）

本仓库已经配好 GitHub Actions 流水线，**只要把代码推上来就会自动编译 APK**：

1. 打开仓库的 **Actions** 页面 → 左侧选 **Build Android APK**
2. 推送代码后它自动开始跑；也可以点 **Run workflow** 手动触发
3. 首次构建约 **30~50 分钟**（要下载 Android SDK/NDK 并编译 pygame）；
   之后命中缓存一般 **10 分钟以内**
4. 跑完后在本次运行页面底部 **Artifacts** 区域下载 `pp-apk.zip`，解压得到 `*.apk`

### 2. 装到手机上

1. 把 APK 传到手机（微信/QQ 传文件、数据线、网盘都行）
2. 手机设置里允许「安装未知来源应用」
3. 点开 APK 安装 → 桌面出现「高紫桐的小屋」

APK 是 **debug 签名**，可以直接侧载安装，不需要 Google Play。

### 3. 本地构建（Linux / macOS / WSL）

```bash
pip install buildozer cython
buildozer android debug      # 产物在 bin/*.apk
```

> Windows 原生环境跑不了 buildozer（它依赖 Linux 工具链），所以本机请走上面的云端构建。

---

## 二、电脑上怎么玩

```bash
cd pet_game
pip install pygame
python main.py
```

快捷键：

| 键 | 作用 | 键 | 作用 |
|---|---|---|---|
| `F` / `P` / `D` / `H` | 喂食 / 抚摸 / 喝水 / 抱抱 | `C` | 打开衣橱 |
| `Y` / `G` / `B` / `S` | 玩耍 / 唱歌 / 洗澡 / 睡觉 | `T` | 打开宠物面板 |
| `←` `→` | 切换衣装 / 切换小宠物 | `1` `2` `3` | 照顾小宠物 |
| `R` | 重来 | `ESC` | 退出 |

---

## 三、手机上做了什么适配

游戏内部始终按 **640×800 的逻辑画布**绘制，适配全部收在 `pet_game/platform_util.py` 一层里，游戏逻辑和绘制代码一行没改：

| 能力 | 做法 |
|---|---|
| **分辨率自适应** | 逻辑画布等比缩放铺满任意手机屏幕，多余区域用**游戏自身的背景渐变**填充（不是黑边）。桌面窗口尺寸恰好等于逻辑尺寸时 `scale == 1`，直接就是原窗口，**零额外开销** |
| **触摸操作** | 坐标自动从屏幕像素换算回 640×800 逻辑坐标；SDL 已合成鼠标事件的场景直接用，没有时用 `FINGER*` 兜底合成，并保证**一次点击不会被处理两遍** |
| **返回键** | 先收起打开的面板（衣橱 / 宠物），没有面板时才退出游戏 |
| **屏幕常亮** | `FLAG_KEEP_SCREEN_ON`，玩着玩着不会黑屏 |
| **沉浸式全屏** | 隐藏状态栏与导航栏 |
| **中文字体** | 自动扫描安卓 `/system/fonts` 下的 CJK 字体，中文不会变方块 |
| **提示文案** | 检测到手机时，底部提示自动去掉键盘快捷键 |

---

## 四、目录结构

```
PP/
├─ buildozer.spec              # python-for-android 打包配置
├─ icon.png / presplash.png    # 应用图标与启动图（由 tools/make_icon.py 生成）
├─ .github/workflows/
│   └─ build-apk.yml           # 云端构建 APK
├─ tools/
│   ├─ make_icon.py            # 用角色贴图生成图标与启动图
│   └─ push_to_github.py       # 一键推送脚本
└─ pet_game/                   # 游戏本体
    ├─ main.py                 # 主循环 / 场景组装 / 事件分发
    ├─ config.py               # ★ 所有可调参数（改这里就能加内容）
    ├─ platform_util.py        # ★ 桌面 / 安卓 双端适配层
    ├─ pet.py                  # 主角：状态机 + 表情 + 衣装 + 姿态动画
    ├─ companion.py            # 小宠物：AI 行为表 + 动作
    ├─ motion.py               # 动作曲线库
    ├─ effects.py              # 粒子特效
    ├─ ui.py                   # 按钮 / 数值条 / 图标
    ├─ utils.py                # 画笔、字体、贴纸描边
    └─ tools/                  # 开发辅助（无头截图、自测，不进 APK）
```

---

## 五、怎么继续加东西

设计上**只改 `config.py` 就够了**，其余部分会自动生成：

- **加互动**：往 `config.INTERACTIONS` 里加一条 → 按钮、快捷键、冷却、特效都会自动接上
- **加衣装**：往 `config.OUTFITS` 里加一条 → 卡片、缩略图、解锁判断自动生成
- **加小宠物**：往 `config.COMPANIONS` 里加一条 → 卡片、AI 权重、快捷键自动生成
- **加动作**：在 `motion.py` 的 `MOTION_LIB` 里加一条曲线 → 任何角色/宠物都能播

改完跑一下自测：

```bash
cd pet_game
python tools/test_mobile.py     # 移动端适配自测（33 项）
python tools/screenshot.py      # 无头渲染全部状态到 preview/
python tools/screenshot.py --bench   # 性能基准
```

---

## 六、常见问题

**Q：Actions 构建失败了怎么办？**
看运行日志里 `buildozer -v android debug` 那一步的报错。最常见的是 SDK/NDK 版本不匹配，
可以改 `buildozer.spec` 里的 `android.api` / `android.ndk` 再推一次（有缓存，重试很快）。

**Q：手机上画面上下有留白？**
游戏是 640×800（4:5），全面屏手机是约 9:19.5，等比缩放后必然有留白。
留白区域用背景渐变补上了，不会突兀。想彻底铺满需要改游戏布局比例，属于设计改动。

**Q：低端机掉帧？**
把 `config.MOBILE_SMOOTH_SCALE` 改成 `False`，缩放改用邻近采样，会快一些（边缘略生硬）。
