# -*- coding: utf-8 -*-
"""
p4a 配方：pygame-ce（社区维护版 pygame）
=========================================================

为什么必须自己带一个配方？
--------------------------
1) p4a 内置的 `pygame` 配方写死了 **pygame 2.1.0**（2021 年），而它的 C 源码里
   还在 `#include "longintrepr.h"`。该头文件从 Python 3.11 起不再位于默认
   include 路径，所以用新版 p4a（镜像里是 Python 3.14）编译必然报：

       src_c/_sdl2/sdl2.c:211:12: fatal error: 'longintrepr.h' file not found

   pygame 上游已停止维护，`pygame-ce` 是社区续作的替代品，提供**同名 `pygame`
   模块**（可无缝替换），且 2.5.8 已支持到 Python 3.15。

2) p4a 官方配方库里 **没有** pygame-ce，所以自带一份（local_recipes 优先级更高）。

为什么还要动 pyproject.toml？
-----------------------------
pygame-ce 从 2.5.0 起把 **meson** 设为默认构建后端，但它的 `meson.build` 里
对 Android 是直接报错退出的：

    elif host_machine.system() == 'android'
        error('The meson buildconfig of pygame-ce does not support android for now.',
              'However it may be added in the future')

而 pip 只要在源码根目录看到 `pyproject.toml` 的 `[build-system]`，就**一定**会走
meson（表现为在 x86 runner 上试图运行交叉编译出的 ARM 程序）：

    meson.build:1:0: ERROR: Could not invoke sanity check executable ...
    sanity_check_for_c.exe', binary or interpreter not executable

于是唯一支持 Android 的 `setup.py` 路径被完全跳过。这里把构建后端换回
setuptools，强制走 `setup.py` + 下面写好的 `Setup` 文件（与 p4a 官方 pygame
配方的流程一致）。

用法：
    1. buildozer.spec 里
           requirements = python3,pygame-ce,pyjnius
           p4a.local_recipes = ./p4a-recipes
    2. 游戏代码里照旧 `import pygame`，不用改任何一行。
"""
import os
from os.path import join

from pythonforandroid.recipe import CompiledComponentsPythonRecipe
from pythonforandroid.toolchain import current_directory

# 强制走 setup.py（Android 唯一可用的构建路径）。
#
# 注意：[project] 段**不能删**。setup.py 第 12 行就 `import buildconfig.get_version`，
# 而 get_version.py 在 Python>=3.11 下会 tomllib 读 pyproject.toml 的
# `conf["project"]["version"]`。上一版把整个文件覆盖掉，直接
# `KeyError: 'project'` 挂在 setup.py 第 12 行。
# 这里只保留 name/version 最小集，避免 setuptools 对 readme/license 等
# 与 setup.py 重复定义的字段抛 InvalidConfigError（已本地实测：name/version
# 两处同时定义不会报错，[project] 的值会胜出）。
_SETUPTOOLS_PYPROJECT = """\
# 由 p4a-recipes/pygame-ce 覆写：pygame-ce 默认的 meson 后端不支持 Android，
# 必须退回 setuptools + setup.py（原因见该配方文件头部）。
[build-system]
requires = ["setuptools>=61.0", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "pygame-ce"
version = "{version}"
"""


def _inc_flags(dirs) -> str:
    """把目录列表拼成 -I 参数，顺便去重。

    多传几个不存在的 -I 目录对 clang 是无害的，所以这里按
    "配方提供的目录 + 硬编码回退路径" 两种来源合起来收集，
    避免某一种在特定 p4a 版本上取不到头文件目录。
    """
    seen, out = set(), []
    for d in dirs:
        if d and d not in seen:
            seen.add(d)
            out.append("-I" + d)
    return " ".join(out)


class Pygame2Recipe(CompiledComponentsPythonRecipe):
    """
    SDL2 版的 pygame-ce 配方。

    .. warning:: 和官方配方一样，freetype / portmidi / libjpeg 这些
        pygame 的可选子模块不在构建范围内。本项目只用到
        pygame.font（走 SDL2_ttf，已包含），因此没有影响。
    """

    version = "2.5.8"
    url = ("https://github.com/pygame-community/pygame-ce/"
           "archive/refs/tags/{version}.tar.gz")

    # 装进 site-packages 后的目录名是 `pygame`（pygame-ce 提供同名模块），
    # 而不是 `pygame-ce`。p4a 用它判断"是否已安装"，写错会导致每次都重建。
    site_packages_name = "pygame"
    name = "pygame-ce"

    depends = ["sdl2", "sdl2_image", "sdl2_mixer", "sdl2_ttf",
               "setuptools", "jpeg", "png"]
    call_hostpython_via_targetpython = False  # 因为要用 setuptools
    install_in_hostpython = False

    def prebuild_arch(self, arch):
        super().prebuild_arch(arch)
        with current_directory(self.get_build_dir(arch.arch)):
            setup_template = open(
                join("buildconfig", "Setup.Android.SDL2.in")).read()
            env = self.get_recipe_env(arch)
            env["ANDROID_ROOT"] = join(self.ctx.ndk.sysroot, "usr")

            png = self.get_recipe("png", self.ctx)
            png_lib_dir = join(png.get_build_dir(arch.arch), ".libs")

            jpeg = self.get_recipe("jpeg", self.ctx)
            jpeg_lib_dir = jpeg.get_build_dir(arch.arch)

            boot = self.ctx.bootstrap.build_dir

            sdl2_mixer_recipe = self.get_recipe("sdl2_mixer", self.ctx)
            sdl_mixer_includes = _inc_flags(
                list(sdl2_mixer_recipe.get_include_dirs(arch))
                + [join(boot, "jni", "SDL2_mixer", "include"),
                   join(boot, "jni", "SDL2_mixer")])

            sdl2_image_recipe = self.get_recipe("sdl2_image", self.ctx)
            sdl_image_includes = _inc_flags(
                list(sdl2_image_recipe.get_include_dirs(arch))
                + [join(boot, "jni", "SDL2_image", "include"),
                   join(boot, "jni", "SDL2_image")])

            sdl_ttf_includes = _inc_flags(
                [join(boot, "jni", "SDL2_ttf", "include"),
                 join(boot, "jni", "SDL2_ttf")])

            setup_file = setup_template.format(
                sdl_includes=(
                    " -I" + join(boot, "jni", "SDL", "include")
                    + " -L" + join(boot, "libs", str(arch))
                    + " -L" + png_lib_dir
                    + " -L" + jpeg_lib_dir
                    + " -L" + arch.ndk_lib_dir_versioned),
                sdl_ttf_includes=sdl_ttf_includes,
                sdl_image_includes=sdl_image_includes,
                sdl_mixer_includes=sdl_mixer_includes,
                # 模板里没有 {jpeg_includes} / {png_includes} 占位符，
                # 多传的键 str.format 会忽略，留着只是和官方配方保持对称。
                jpeg_includes="-I" + jpeg.get_build_dir(arch.arch),
                png_includes="-I" + png.get_build_dir(arch.arch),
                freetype_includes="",
            )
            open("Setup", "w").write(setup_file)

            # setup.py 里有一段：如果 buildconfig/Setup.SDL2.in 比 Setup 新，
            # 就用**桌面版模板**重建 Setup，把我们的 Android 配置冲掉。
            # 解压出来的模板 mtime 来自 tar，某些解压方式会把它设成"现在"，
            # 所以这里显式把 Setup 的时间戳推到最新，彻底消除这个隐患。
            os.utime("Setup", None)

            # 关掉 meson 后端（详见文件头部说明），逼 pip 走 setup.py。
            with open("pyproject.toml", "w") as fp:
                fp.write(_SETUPTOOLS_PYPROJECT.format(version=self.version))

    def get_recipe_env(self, arch):
        env = super().get_recipe_env(arch)
        env["USE_SDL2"] = "1"
        env["PYGAME_CROSS_COMPILE"] = "TRUE"
        env["PYGAME_ANDROID"] = "TRUE"
        return env


recipe = Pygame2Recipe()
