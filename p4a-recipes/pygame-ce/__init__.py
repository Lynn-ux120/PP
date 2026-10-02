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

为什么还要动 setup.py？（两个坑，都是 pip 的构建后端与直接跑 setup.py 的差异）
-----------------------------------------------------------------------------
p4a 对一个 recipe 会跑两条路径，行为**不一样**：

    (a) `python setup.py build_ext -v`     ← cwd=源码根，sys.argv[0]='setup.py'
    (b) `pip install . --compile --target` ← pip 的 PEP517 后端，
      它用 `python .../pyproject_hooks/_in_process/_in_process.py <hook>` 起子进程

坑 1 —— 工程根不在 sys.path 上：
    (a) 时 `sys.path[0]` 就是源码根，`import buildconfig.get_version` 正常；
    (b) 时 `sys.path[0]` 是 pip 自己的目录，于是 setup.py 第 12 行
    `import buildconfig.get_version` 直接
    `ModuleNotFoundError: No module named 'buildconfig'`。

坑 2 —— setup.py 里的 `os.chdir` 会跳错地方（★本轮踩得最隐蔽的一个）：
    setup.py 第 173~175 行是

        # get us to the correct directory
        path = os.path.split(os.path.abspath(sys.argv[0]))[0]
        os.chdir(path)

    (a) 时 `sys.argv[0] == 'setup.py'` → chdir 到源码根，没问题；
    (b) 时 **`sys.argv[0]` 是 pip 的 `_in_process.py` 的绝对路径** →
        chdir 到 pip 的内部目录！于是后面第 329~330 行

            headers = glob.glob(os.path.join('src_c', '*.h'))
            headers.remove(os.path.join('src_c', 'scale.h'))

        的 glob 在 pip 的目录里当然一个头文件都找不到，list 为空 →
        `ValueError: list.remove(x): x not in list`。

    这个坑特别难查：`src_c/scale.h` 在源码里**明明存在**，
    build_ext 阶段也确实通过了，只有 pip 那条路径炸；
    而且**本地复现时极容易漏掉** —— 如果直接 `python -c "import
    setuptools.build_meta as bm; bm.get_requires_for_build_wheel({})"`，
    `sys.argv[0]` 会是 `'-c'`，chdir 变成原地不动，于是"本地怎么试都过、
    CI 上怎么试都挂"。要忠实复现就必须**真的用 pip 的 `BuildBackendHookCaller`
    起子进程**（见 tools/ 里的对照实验记录）。

所以补丁做三件事，插在 setup.py 顶部（锚点在第 12 行那句 import 之前，
必须早于第 173 行的 chdir）：
    1. 把源码根放进 `sys.path`（修坑 1）；
    2. 把 `sys.argv[0]` 改写成本目录下的 `setup.py`（修坑 2，让那条 chdir 变成空操作）；
    3. 顺手 `os.chdir()` 到源码根，作为双保险。

`[build-system].requires` 里必须带 **cython**：pip 的构建隔离环境里只有
requires 列出的包，而 setup.py 缺 Cython 时会直接 `sys.exit(1)`，等不到
pip 去装依赖（鸡生蛋）。

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
#
# 为什么 requires 里必须有 cython：
#   p4a 那条 `pip install .` 是**带构建隔离**跑的（日志里能看到
#   "Installing build dependencies ... done"），隔离环境里只有 requires
#   列出的包。而 pygame-ce 的 setup.py 在没有 Cython 时会直接打印
#   "You need cython." 然后 exit(1) —— 在它有机会声明构建依赖之前就退出了，
#   所以 pip 侧永远拿不到这个依赖（鸡生蛋）。必须在这里显式写上。
_SETUPTOOLS_BUILD_SYSTEM = (
    "[build-system]\n"
    'requires = ["setuptools>=61.0", "wheel", "cython<=3.2.9"]\n'
    'build-backend = "setuptools.build_meta"\n'
)

# 从 "[build-system]" 一直匹配到下一个行首的 "[" 之前（即整个段）。
_BUILD_SYSTEM_RE = re.compile(r"\[build-system\][\s\S]*?(?=\n\[|\Z)")

# ---- setup.py 顶部的兼容补丁 ---------------------------------------------
# 锚点：setup.py 第 12 行的 `import buildconfig.get_version as pg_ver`。
# 必须选在它前面，因为第 173 行的 os.chdir 也要靠这里的修正来纠正
# （见文件头部"坑 2"）。插在最顶部也最安全：pip 后端和直接跑 setup.py
# 两种情况下 `__file__` 都能拿到本文件路径。
_SETUP_ANCHOR = "import buildconfig.get_version as pg_ver"

_SETUP_PATCH = (
    "# >>> p4a-recipes/pygame-ce 补丁（开始）\n"
    "# pip 的 PEP517 后端用 `python .../_in_process.py <hook>` 起子进程，\n"
    "# 此时 sys.path[0] 和 sys.argv[0] 都指向 pip 自己，而不是本工程根目录：\n"
    "#   1) `import buildconfig...` 会 ModuleNotFoundError；\n"
    "#   2) 下面第 173 行的 `os.chdir(dirname(abspath(sys.argv[0])))`\n"
    "#      会跳到 pip 的目录，导致 `glob('src_c/*.h')` 为空，\n"
    "#      进而 `headers.remove('src_c/scale.h')` 抛 ValueError。\n"
    "# 直接跑 `python setup.py ...` 时这两条都不成立，所以只在 pip 路径下会炸。\n"
    "import os as _pg_os, sys as _pg_sys\n"
    '_pg_here = _pg_os.path.dirname(_pg_os.path.abspath(\n'
    '    globals().get("__file__") or "setup.py"))\n'
    "_pg_os.chdir(_pg_here)\n"
    "_pg_sys.path.insert(0, _pg_here)\n"
    '_pg_sys.argv[0] = _pg_os.path.join(_pg_here, "setup.py")\n'
    "# <<< p4a-recipes/pygame-ce 补丁（结束）\n"
    + _SETUP_ANCHOR
)


def _patch_setup_py(build_dir: str) -> None:
    """修正 setup.py 在 pip 构建后端下的 sys.path / sys.argv[0] / cwd。

    三件事都只在 pip 的 PEP517 后端里才出问题（详见文件头部说明）。
    """
    path = join(build_dir, "setup.py")
    with open(path, encoding="utf-8") as fp:
        text = fp.read()

    if _SETUP_ANCHOR not in text:
        raise RuntimeError(
            "setup.py 里找不到 `%s`，补丁锚点失效；"
            "上游结构可能已变化" % _SETUP_ANCHOR)
    if "_pg_sys.argv[0]" in text:
        return  # 已经打过了

    text = text.replace(_SETUP_ANCHOR, _SETUP_PATCH, 1)
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(text)


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
            # 修正 pip 构建后端下的 sys.path / sys.argv[0] / cwd。
            _patch_setup_py(".")

    def get_recipe_env(self, arch):
        env = super().get_recipe_env(arch)
        env["USE_SDL2"] = "1"
        env["PYGAME_CROSS_COMPILE"] = "TRUE"
        env["PYGAME_ANDROID"] = "TRUE"
        return env


recipe = Pygame2Recipe()
