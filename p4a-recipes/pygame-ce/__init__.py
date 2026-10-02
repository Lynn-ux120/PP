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

为什么还要改 pyproject.toml？
-----------------------------
pygame-ce 从 2.5.0 起把 **meson** 设为默认构建后端（`build-backend = 'mesonpy'`），
但它的 `meson.build` 里对 Android 是直接报错退出的：

    elif host_machine.system() == 'android'
        error('The meson buildconfig of pygame-ce does not support android for now.',
              'However it may be added in the future')

而 pip 只认 `pyproject.toml` 的 `[build-system]`：看到 meson 就一定走 meson，
表现为在 x86 runner 上试图**运行**交叉编译出来的 ARM 程序：

    meson.build:1:0: ERROR: Could not invoke sanity check executable ...
    sanity_check_for_c.py-.../sanity_check_for_c.exe', binary or interpreter not executable

于是唯一支持 Android 的 `setup.py`（2.5.8 里仍是完整的老式 setuptools 脚本，
会读根目录的 `Setup` 文件、认 `PYGAME_ANDROID` 环境变量，且**不含
longintrepr.h**）被完全跳过。所以这里只把 `[build-system]` 换成 setuptools，
让 p4a 那条 `pip install .` 走 `setup.py`。

⚠️ `[project]` 表**必须原样保留，绝对不能改**（踩过两次坑）：
   - 删掉整个 `[project]` → `buildconfig/get_version.py` 取不到
     `conf["project"]["version"]` → `KeyError: 'project'`；
   - 只留一个 `[project] name/version` 最小集 → setuptools 认为其余字段
     "在 pyproject 外定义、被忽略"，随后在 `_long_description` 里
     `AttributeError: 'NoneType' object has no attribute 'get'`。
   p4a 跑的是 `python setup.py build_ext`，而 setuptools 只要看到 `[project]`
   就会拿它当权威元数据源，两边必须一致。
   （已用真实 sdist 做过对照实验：保留原 `[project]` + 只换 `[build-system]`
   → 通过；最小化 `[project]` → 复现上述两个错误。）

用法：
    1. buildozer.spec 里
           requirements = python3,pygame-ce,pyjnius
           p4a.local_recipes = ./p4a-recipes
    2. 游戏代码里照旧 `import pygame`，不用改任何一行。
"""
import os
import re
from os.path import join

from pythonforandroid.recipe import CompiledComponentsPythonRecipe
from pythonforandroid.toolchain import current_directory

# 用来顶掉 meson 后端。只替换 [build-system] 段，[project] 保持上游原样。
_SETUPTOOLS_BUILD_SYSTEM = (
    "[build-system]\n"
    'requires = ["setuptools>=61.0", "wheel"]\n'
    'build-backend = "setuptools.build_meta"\n'
)

# 从 "[build-system]" 一直匹配到下一个行首的 "[" 之前（即整个段）。
_BUILD_SYSTEM_RE = re.compile(r"\[build-system\][\s\S]*?(?=\n\[|\Z)")


def _force_setuptools_backend(build_dir: str) -> None:
    """把源码树里的 [build-system] 从 meson 换成 setuptools。

    只动这一段：`[project]` 是 setup.py / buildconfig.get_version 的元数据来源，
    改坏它会让构建在元数据解析阶段就崩（见文件头部说明）。

    余下的 `[tool.meson-python.args]` / `[tool.cibuildwheel.*]` 段会被保留，
    它们对 setuptools 是无关的第三方工具表，不会生效也不会报错。
    """
    path = join(build_dir, "pyproject.toml")
    if not os.path.exists(path):
        raise RuntimeError(
            "pyproject.toml 不见了：本配方依赖它来关掉 meson 后端，"
            "请检查上游包结构是否变化")

    with open(path, encoding="utf-8") as fp:
        text = fp.read()

    new_text, count = _BUILD_SYSTEM_RE.subn(
        _SETUPTOOLS_BUILD_SYSTEM, text, count=1)
    if count != 1:
        raise RuntimeError(
            "pyproject.toml 里没找到 [build-system] 段，"
            "无法切换到 setuptools 后端；上游结构可能已变化")

    with open(path, "w", encoding="utf-8") as fp:
        fp.write(new_text)


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
            sdl_mixer_includes = " ".join(
                "-I" + d for d in dict.fromkeys(
                    list(sdl2_mixer_recipe.get_include_dirs(arch))
                    + [join(boot, "jni", "SDL2_mixer", "include"),
                       join(boot, "jni", "SDL2_mixer")]))

            sdl2_image_recipe = self.get_recipe("sdl2_image", self.ctx)
            sdl_image_includes = " ".join(
                "-I" + d for d in dict.fromkeys(
                    list(sdl2_image_recipe.get_include_dirs(arch))
                    + [join(boot, "jni", "SDL2_image", "include"),
                       join(boot, "jni", "SDL2_image")]))

            sdl_ttf_includes = " ".join(
                "-I" + d for d in dict.fromkeys(
                    [join(boot, "jni", "SDL2_ttf", "include"),
                     join(boot, "jni", "SDL2_ttf")]))

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

            # 关掉 meson 后端，逼 pip 走 setup.py（详见文件头部说明）。
            _force_setuptools_backend(".")

    def get_recipe_env(self, arch):
        env = super().get_recipe_env(arch)
        env["USE_SDL2"] = "1"
        env["PYGAME_CROSS_COMPILE"] = "TRUE"
        env["PYGAME_ANDROID"] = "TRUE"
        return env


recipe = Pygame2Recipe()
