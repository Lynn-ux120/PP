# -*- coding: utf-8 -*-
"""
p4a 配方：pygame-ce（社区维护版 pygame）
=========================================================

为什么必须自己带一个配方？
    python-for-android 内置的 `pygame` 配方写死了 **pygame 2.1.0**（2021 年），
    而 pygame 2.1.0 里 `src_c/_sdl2/sdl2.c` 还在 `#include "longintrepr.h"`。
    这个头文件从 Python 3.11 起就不再放在默认 include 路径下了，
    于是新版 p4a（镜像里是 Python 3.14）一编译就报：

        src_c/_sdl2/sdl2.c:211:12: fatal error: 'longintrepr.h' file not found

    pygame 上游已停止维护，`pygame-ce` 是社区续作的替代品，
    它提供**同名 `pygame` 模块**（可无缝替换），且支持到 Python 3.15。

用法：
    1. buildozer.spec 里
           requirements = python3,pygame-ce,pyjnius
           p4a.local_recipes = ./p4a-recipes
    2. 游戏代码里照旧 `import pygame`，不用改任何一行。

本文件基于 p4a 官方 pygame 配方改写（构建流程完全一致），仅更换：
    name / site_packages_name / version / url
并加固了 include 路径的收集（见 _inc_flags 的说明）。
"""
from os.path import join

from pythonforandroid.recipe import CompiledComponentsPythonRecipe
from pythonforandroid.toolchain import current_directory


def _inc_flags(dirs) -> str:
    """把目录列表拼成 -I 参数，顺便去重。

    多传几个不存在的 -I 目录对 clang 是无害的，所以这里宁可按
    "官方配方的写法 + 硬编码回退路径" 两种来源合起来收集，
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

    site_packages_name = "pygame-ce"
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
                png_includes="-I" + png.get_build_dir(arch),
                freetype_includes="",
            )
            open("Setup", "w").write(setup_file)

    def get_recipe_env(self, arch):
        env = super().get_recipe_env(arch)
        env["USE_SDL2"] = "1"
        env["PYGAME_CROSS_COMPILE"] = "TRUE"
        env["PYGAME_ANDROID"] = "TRUE"
        return env


recipe = Pygame2Recipe()
