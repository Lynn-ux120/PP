# =========================================================
#  buildozer.spec —— 把 pet_game 打包成安卓 APK
# =========================================================
#  本地（Linux / macOS / WSL）构建：
#      pip install buildozer cython
#      buildozer android debug
#      产物：bin/*.apk
#
#  Windows 用户：本机没有 Linux 工具链，请走 GitHub Actions 云端构建
#      （.github/workflows/build-apk.yml，推送到 main 后自动出 APK）
# =========================================================

[app]

# 应用名（手机桌面上显示的名字）
title = 高紫桐的小屋

# 包名 = package.domain + "." + package.name  →  org.fenghuayuan.pp
package.name = pp
package.domain = org.fenghuayuan

# 游戏代码所在目录（相对于本文件）
source.dir = pet_game

# 打进 APK 的文件类型
source.include_exts = py,png,jpg,jpeg,ttf,otf,ttc,json,txt

# 开发辅助目录不进 APK（体积和启动速度都受益）
source.exclude_dirs = tools,preview,__pycache__,.git,.pytest_cache
source.exclude_patterns = *.pyc,*.pyo,*.md,debug.log

version = 1.0.0

# pygame 由 python-for-android 的 pygame 配方编译（对应 SDL2）
# pyjnius 用于屏幕常亮 / 沉浸式全屏（platform_util.py 里有 try/except 兜底）
requirements = python3,pygame,pyjnius

# 竖屏（游戏逻辑分辨率 640x800 就是竖屏比例）
orientation = portrait
fullscreen = 1

# 图标 / 启动图（由 tools/make_icon.py 用游戏里的角色贴图生成）
icon.filename = icon.png
presplash.filename = presplash.png
presplash.color = #FDF2F7

# ---------------- 安卓参数 ----------------
android.api = 34
android.minapi = 24
# NDK 版本故意不写死：让 buildozer 用与自身 python-for-android 匹配的默认版本。
# 写死一个版本有可能撞上 p4a 不支持的区间，且要多下载一份 ~1GB 的 NDK。
# android.ndk =
# 只编 arm64 可以省掉几乎一半的编译时间（pygame / CPython 要按架构各编一遍）。
# 2018 年之后在售的安卓手机基本都是 arm64；
# 如果装到很老的 32 位机器上提示不兼容，把 armeabi-v7a 加回来重跑即可。
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = True
android.debug_artifact = apk
android.release_artifact = apk

# 这个游戏不需要任何敏感权限
android.permissions =

# 允许非 ASCII 应用名正常写进 strings.xml
android.enable_androidx = True

[buildozer]
log_level = 2
# 容器里 buildozer 一定是 root 身份运行。若保持默认的 1，
# 它会弹出 "Are you sure you want to continue [y/n]?" 交互确认，
# 而 CI 是非交互环境 → 读到 EOF → EOFError 直接构建失败。
warn_on_root = 0
