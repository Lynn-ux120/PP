#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/push_to_github.py —— 一键把项目推送到 GitHub
=========================================================
为什么不用 git？
    本机 hosts 把 github.com / api.github.com 指向了 127.0.0.1，
    git 走不通。这里用阿里 DoH 解析真实 IP，再通过 GitHub REST API
    直接提交文件（Git Data API），全程不需要改 hosts、不需要管理员权限。
    普通域名（百度、PyPI 等）仍然走系统 DNS，不受影响。

用法
    # Windows PowerShell
    $env:GH_TOKEN="ghp_xxxxxxxx"
    python tools/push_to_github.py

    # 或者直接传参
    python tools/push_to_github.py --token ghp_xxxx --repo PP --branch main

    # 推送后一直盯着构建，好了就把 APK 下到 dist/
    python tools/push_to_github.py --token ghp_xxxx --wait --download

前置
    GitHub 令牌需要 repo 权限（classic: 勾 repo；fine-grained: Contents=Read/Write）
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.github.com"

# =========================================================
#  DNS：只接管被 hosts 屏蔽的 GitHub 域名
# =========================================================
_BLOCKED_SUFFIX = ("github.com", "githubusercontent.com", "githubassets.com",
                   "github.io", "githubapp.com")

_dns_cache: dict = {}

_DOH_PROVIDERS = (
    "https://dns.alidns.com/resolve?name={h}&type=A",
    "https://doh.pub/dns-query?name={h}&type=A",
)


def _doh_lookup(host: str):
    """用 DoH 查一个域名的 A 记录（返回 IP 字符串或 None）。"""
    if host in _dns_cache:
        return _dns_cache[host]

    for tpl in _DOH_PROVIDERS:
        url = tpl.format(h=urllib.parse.quote(host))
        try:
            req = urllib.request.Request(url, headers={
                "Accept": "application/dns-json",
                "User-Agent": "PP-build",
            })
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode("utf-8"))
            for ans in data.get("Answer", []):
                if ans.get("type") == 1 and ans.get("data"):
                    ip = ans["data"]
                    _dns_cache[host] = ip
                    return ip
        except Exception:
            continue
    return None


def install_dns_patch():
    """把被屏蔽的 GitHub 域名重定向到 DoH 查到的真实 IP。"""
    original = socket.getaddrinfo

    def patched(host, port, family=0, type=0, proto=0, flags=0):
        if isinstance(host, str) and any(
                host == s or host.endswith("." + s) for s in _BLOCKED_SUFFIX):
            ip = _doh_lookup(host)
            if ip:
                return original(ip, port, family, type, proto, flags)
        return original(host, port, family, type, proto, flags)

    socket.getaddrinfo = patched
    return original


# =========================================================
#  GitHub API
# =========================================================
class GitHub:
    def __init__(self, token: str):
        self.token = token.strip()
        # 空令牌会一路走到 GitHub 换回 401 Bad credentials，很难反查来源；
        # 这里直接拦下（曾因误传 args.token 而非 load_token() 的结果踩过一次）。
        if not self.token:
            raise ValueError(
                "GitHub 客户端收到空令牌。检查是否误传了 args.token —— "
                "应当传 load_token(args) 的返回值。")
        self.ctx = ssl.create_default_context()

    def call(self, method: str, path: str, payload=None, raw=False,
             tries: int = 4, pause: float = 5.0):
        """发一个 API 请求。

        网络层失败会自动重试（`tries` 次）——长轮询里一次读超时
        不该让整个"等待构建"流程崩掉（踩过：等了 10 分钟被
        `TimeoutError: The read operation timed out` 打断）。
        注意 HTTPError 是正常业务响应（401/404/409…），不重试。
        """
        url = path if path.startswith("http") else API + path
        body = None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "PP-build",
        }
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        if os.environ.get("PP_DEBUG"):
            # 指纹而非明文——哈希不会被日志脱敏改写，方便两条路径对齐
            fp = hashlib.sha256(self.token.encode()).hexdigest()[:16]
            print(f"  [debug] {method} {url}")
            print(f"  [debug] token 长度={len(self.token)} sha256={fp}")

        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        for attempt in range(tries):
            try:
                with urllib.request.urlopen(req, timeout=60, context=self.ctx) as r:
                    data = r.read()
                    if os.environ.get("PP_DEBUG"):
                        print(f"  [debug] <- HTTP {r.status}")
                    return r.status, (data if raw else json.loads(data or b"{}"))
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")
                if os.environ.get("PP_DEBUG"):
                    print(f"  [debug] <- HTTP {e.code} {detail[:200]}")
                try:
                    detail = json.loads(detail).get("message", detail)
                except Exception:
                    pass
                return e.code, detail
            except Exception as exc:  # 网络层：超时 / DNS / TLS / 连接重置
                if attempt < tries - 1:
                    print(f"  · 网络抖动（{type(exc).__name__}），"
                          f"{pause:.0f}s 后重试 {attempt + 2}/{tries}")
                    time.sleep(pause)
                    continue
                print(f"  ✗ 请求失败（{type(exc).__name__}）：{exc}")
                return 0, str(exc)


# =========================================================
#  文件收集
# =========================================================
SKIP_DIRS = {".git", ".workbuddy", "__pycache__", "preview", ".buildozer",
             "bin", "out", "dist", ".pytest_cache", ".venv", "venv",
             ".vscode", ".idea"}
SKIP_FILES = {"debug.log", ".DS_Store", "Thumbs.db", ".build_log.txt"}
SKIP_EXT = {".pyc", ".pyo", ".apk", ".aab"}

# 仓库根要保留的隐藏文件（其余以 "." 开头的一律不上传）。
# 理由是这类文件几乎都是本机排障产物（.build_log.txt、.probe.txt…），
# 传上去只会在公开仓库里留垃圾；而真正的仓库配置就那么几个，白名单即可。
KEEP_DOTFILES = {".gitattributes", ".gitignore", ".gitmodules", ".editorconfig"}

# 同理，隐藏**目录**默认整个跳过，只放行真正要进仓库的那一个。
# 漏掉这条会造成实打实的泄漏：.preview_new/ 这种排障目录虽然名字以 "." 开头，
# 但 SKIP_DIRS 是精确名匹配，os.walk 会照走不误，里面的 PNG 就被推上公开仓库了。
KEEP_DOTDIRS = {".github"}

# 凭据类文件：名字里出现这些关键词就一律不上传。
# 曾经因为只用 .gitignore 排除、脚本又绕过了 git，差点把 .gh_token 明文推到公开仓库。
SECRET_HINTS = ("token", "secret", "credential", ".gh_token", ".env",
                "id_rsa", "id_ed25519", ".pem", ".key", "passwd", "password")


def is_secret(rel: str) -> bool:
    low = rel.lower()
    name = os.path.basename(low)
    if name in {".gh_token", "token.txt", ".env", ".netrc"}:
        return True
    if low.endswith((".pem", ".key", ".p12", ".pfx")):
        return True
    return any(h in name for h in SECRET_HINTS)


def is_scratch(rel: str) -> bool:
    """排障用的临时脚本，不该进公开仓库。

    本工程约定：以**单个下划线**开头的文件（如 tools/_check_state.py）
    是一次性调试脚本，用完就丢。
    注意必须排除 ``__init__.py`` 这种双下划线文件——p4a-recipes 里的
    配方正是 ``__init__.py``，它**必须**上传，否则云端 p4a 找不到配方。
    """
    name = os.path.basename(rel)
    return name.startswith("_") and not name.startswith("__")


def collect_files():
    picked = []
    secrets = []
    scratch = []
    skipped_dirs = []
    for base, dirs, files in os.walk(ROOT):
        kept = []
        for d in dirs:
            if d in SKIP_DIRS:
                continue
            # 隐藏目录（.preview_new/、.bench_cache/…）整棵剪掉，只放行白名单
            if d.startswith(".") and d not in KEEP_DOTDIRS:
                skipped_dirs.append(
                    os.path.relpath(os.path.join(base, d), ROOT)
                    .replace(os.sep, "/") + "/")
                continue
            kept.append(d)
        dirs[:] = kept
        for fn in files:
            if fn in SKIP_FILES or os.path.splitext(fn)[1] in SKIP_EXT:
                continue
            full = os.path.join(base, fn)
            rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
            if is_secret(rel):
                secrets.append(rel)
                continue
            if is_scratch(rel):
                scratch.append(rel)
                continue
            if fn.startswith(".") and fn not in KEEP_DOTFILES:
                scratch.append(rel)
                continue
            picked.append((rel, full))
    picked.sort()
    for rel in skipped_dirs:
        print(f"      · 跳过隐藏目录：{rel}")
    for rel in secrets:
        print(f"      ! 跳过疑似凭据文件：{rel}")
    for rel in scratch:
        print(f"      · 跳过临时调试脚本：{rel}")
    return picked


# =========================================================
#  推送
# =========================================================
def push(gh: GitHub, repo: str, branch: str, message: str):
    code, user = gh.call("GET", "/user")
    if code != 200:
        print(f"  ✗ 令牌无效（HTTP {code}）：{user}")
        print("    classic 令牌固定 40 字符，请确认没有复制漏字符。")
        return None
    owner = user["login"]
    print(f"  ✓ 令牌有效，账号：{owner}")

    # 仓库不存在就建
    code, _ = gh.call("GET", f"/repos/{owner}/{repo}")
    if code == 404:
        code, res = gh.call("POST", "/user/repos", {
            "name": repo,
            "private": False,
            "description": "高紫桐的小屋 · Pygame 2D 宠物养成（含安卓 APK 云端构建）",
            "auto_init": False,
        })
        if code not in (200, 201):
            print(f"  ✗ 创建仓库失败（HTTP {code}）：{res}")
            return None
        print(f"  ✓ 已创建仓库 {owner}/{repo}")
    else:
        print(f"  ✓ 仓库已存在 {owner}/{repo}")

    # 已有分支 → 拿到父提交
    parent = None
    code, res = gh.call("GET", f"/repos/{owner}/{repo}/git/ref/heads/{branch}")
    if code == 200:
        parent = res["object"]["sha"]
        print(f"  · 已有 {branch} 分支，本次为增量提交")
    else:
        # 空仓库的 git/blobs、git/trees 一律返回 409 "Git Repository is empty"，
        # 必须先用 Contents API 落一个初始提交，把仓库"激活"。
        code, res = gh.call(
            "PUT", f"/repos/{owner}/{repo}/contents/.gitkeep",
            {"message": "chore: 初始化仓库",
             "content": base64.b64encode(b"# PP\n").decode("ascii"),
             "branch": branch})
        if code not in (200, 201):
            print(f"  ✗ 初始化空仓库失败（HTTP {code}）：{res}")
            return None
        parent = res["commit"]["sha"]
        print(f"  ✓ 空仓库已激活，root 提交 {parent[:8]}")

    files = collect_files()
    print(f"  · 待上传 {len(files)} 个文件")

    tree = []
    for rel, full in files:
        with open(full, "rb") as f:
            content = base64.b64encode(f.read()).decode("ascii")
        code, res = gh.call("POST", f"/repos/{owner}/{repo}/git/blobs",
                            {"content": content, "encoding": "base64"})
        if code not in (200, 201):
            print(f"  ✗ 上传 {rel} 失败（HTTP {code}）：{res}")
            return None
        tree.append({"path": rel, "mode": "100644", "type": "blob",
                     "sha": res["sha"]})
        print(f"      + {rel}")

    code, res = gh.call("POST", f"/repos/{owner}/{repo}/git/trees", {"tree": tree})
    if code not in (200, 201):
        print(f"  ✗ 创建目录树失败：{res}")
        return None
    tree_sha = res["sha"]

    commit_payload = {"message": message, "tree": tree_sha}
    if parent:
        commit_payload["parents"] = [parent]
    code, res = gh.call("POST", f"/repos/{owner}/{repo}/git/commits", commit_payload)
    if code not in (200, 201):
        print(f"  ✗ 创建提交失败：{res}")
        return None
    commit_sha = res["sha"]
    print(f"  ✓ 提交 {commit_sha[:8]}  {message}")

    if parent:
        code, res = gh.call("PATCH", f"/repos/{owner}/{repo}/git/refs/heads/{branch}",
                            {"sha": commit_sha, "force": False})
    else:
        code, res = gh.call("POST", f"/repos/{owner}/{repo}/git/refs",
                            {"ref": f"refs/heads/{branch}", "sha": commit_sha})
    if code not in (200, 201):
        print(f"  ✗ 更新分支失败：{res}")
        return None

    print(f"  ✓ 已推送到 {branch}")
    return owner, commit_sha


def wait_and_download(gh: GitHub, owner: str, repo: str, branch: str,
                      outdir: str, head_sha: str = "", timeout_min: int = 90):
    """等本次推送触发的那次运行。

    必须按 head_sha 过滤：新推送的 run 记录有几秒的注册延迟，
    如果直接取列表第一条，会抓到**上一次**的陈旧运行，
    于是"刚推完就报构建失败"。这个竞态踩过一次。
    """
    print("\n=== 等待云端构建 ===")
    if head_sha:
        print(f"  · 目标提交 {head_sha[:8]}")
    deadline = time.time() + timeout_min * 60
    started = time.time()
    run = None
    seen_any = False
    idle = 0
    beat = 0
    misses = 0
    while time.time() < deadline:
        elapsed = int((time.time() - started) / 60)
        code, res = gh.call(
            "GET", f"/repos/{owner}/{repo}/actions/runs"
                   f"?branch={branch}&per_page=20")
        if code != 200:
            idle += 1
            if idle % 5 == 0:
                print(f"  · 连续 {idle} 次没拿到运行列表（已等 {elapsed} 分钟），继续…")
            time.sleep(30)
            continue

        idle = 0
        runs = res.get("workflow_runs", [])
        if head_sha:
            # 用**前缀**匹配：正常推送路径传进来的是完整 40 位 sha，
            # 而 `--watch --sha` 通常只给前 8 位（GitHub 页面上的短 sha）。
            # 早先这里写的是 `== head_sha`，于是短 sha 永远匹配不到，
            # 表现为一直刷"运行记录还没注册"直到超时。
            runs = [r for r in runs
                    if (r.get("head_sha") or "").startswith(head_sha)]
        if not runs:
            if not seen_any:
                misses += 1
                if misses <= 3:
                    print("  · 运行记录还没注册，稍等…")
                elif misses == 4:
                    print("  · 仍未找到匹配该提交的运行 —— 若是用 --watch 查"
                          "旧构建，请确认 --sha 写的是该次提交的 sha。")
            time.sleep(10)
            continue
        seen_any = True
        r = runs[0]
        tag = f'{r["id"]} {r["status"]}/{r.get("conclusion")}'
        if run != tag:
            run = tag
            beat = elapsed
            print(f"  · [{elapsed} 分钟] 运行 {r['id']}：{r['status']} "
                  f"{r.get('conclusion') or ''}".rstrip())
        elif elapsed >= beat + 5:
            beat = elapsed
            print(f"  · [{elapsed} 分钟] 仍在构建中（fetch/编译阶段较慢是正常的）")
        if r["status"] == "completed":
            if r.get("conclusion") != "success":
                print(f"  ✗ 构建未成功：{r.get('conclusion')}"
                      f"\n    日志：{r['html_url']}")
                return None
            return _download(gh, owner, repo, r["id"], outdir,
                             r["html_url"])
        time.sleep(30)
    print("  ✗ 等待超时，请自行到 Actions 页面查看")
    return None


def _download_to(gh: GitHub, api_path: str, dst: str) -> bool:
    """下载一个会 **302 到 Azure Blob** 的接口（构建产物 zip）。

    GitHub 的 `.../actions/artifacts/{id}/zip` 会 302 到
    `productionresultssa*.blob.core.windows.net` 上的**预签名**地址。
    默认 opener 会把 `Authorization` 头一起转发过去，Azure 回：

        401 InvalidAuthenticationInfo
        The access token was missing or malformed.

    —— 和当初取 Actions 日志踩的是同一个坑（见 tools/gh_actions.py 的
    fetch_log）。所以先用 NoRedirect 拿 Location，再**不带认证头**下载。
    """
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    url = API + api_path
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {gh.token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "PP-build"})
    try:
        opener = urllib.request.build_opener(NoRedirect)
        with opener.open(req, timeout=30) as r:
            # 没有重定向，说明直接给了内容
            with open(dst, "wb") as f:
                shutil.copyfileobj(r, f)
            return True
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location")
        if not loc:
            print(f"  ✗ 下载失败（HTTP {e.code}，且响应里没有 Location）")
            return False
    except Exception as exc:
        print(f"  ✗ 下载失败（{type(exc).__name__}）：{exc}")
        return False

    plain = urllib.request.Request(loc, headers={"User-Agent": "PP-build"})
    with urllib.request.urlopen(plain, timeout=300) as r:
        with open(dst, "wb") as f:
            shutil.copyfileobj(r, f)
    return True


def _extract_apks(zip_path: str, outdir: str):
    """把产物 zip 里的 .apk 解出来（artifact 里就是一个 zip 包着 apk）。"""
    found = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.filename.lower().endswith(".apk"):
                target = os.path.join(outdir, os.path.basename(info.filename))
                with zf.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                found.append(target)
    return found


def _download(gh: GitHub, owner: str, repo: str, run_id: int,
              outdir: str, run_url: str):
    code, res = gh.call("GET",
                        f"/repos/{owner}/{repo}/actions/runs/{run_id}/artifacts")
    arts = res.get("artifacts", []) if code == 200 else []
    if not arts:
        print("  ✗ 没找到构建产物，请到页面确认：", run_url)
        return None
    os.makedirs(outdir, exist_ok=True)
    for art in arts:
        zpath = os.path.join(outdir, art["name"] + ".zip")
        if not _download_to(
                gh, f"/repos/{owner}/{repo}/actions/artifacts/{art['id']}/zip",
                zpath):
            print(f"  ✗ 下载 {art['name']} 失败")
            continue
        print(f"  ✓ 已下载 {art['name']}.zip  "
              f"({os.path.getsize(zpath) / 1048576:.1f} MB)")

        try:
            apks = _extract_apks(zpath, outdir)
        except zipfile.BadZipFile as exc:
            print(f"  ✗ {zpath} 不是合法 zip：{exc}")
            continue
        if not apks:
            print(f"  ! {art['name']}.zip 里没找到 .apk（保留 zip 供检查）")
            continue
        for a in apks:
            print(f"      → {a}  ({os.path.getsize(a) / 1048576:.1f} MB)")
        # 解出来了就把 zip 清掉，dist/ 里只留 apk
        os.remove(zpath)

    print(f"\n构建页面：{run_url}")
    return outdir


def load_token(args) -> str:
    """按优先级取令牌：--token-file > GH_TOKEN_FILE > --token > GH_TOKEN。

    取到的令牌会做一次"清洗"：去掉首尾空白、所有换行、
    以及复制时常见的零宽字符（U+200B/200C/200D/FEFF），
    这些字符肉眼看不见，却会让 GitHub 直接返回 401。
    """
    raw = ""
    path = args.token_file or os.environ.get("GH_TOKEN_FILE", "")
    if path:
        p = path if os.path.isabs(path) else os.path.join(ROOT, path)
        try:
            with open(p, "r", encoding="utf-8") as f:
                raw = f.read()
            print(f"  · 已从文件读取令牌：{p}")
        except OSError as exc:
            print(f"  ✗ 无法读取令牌文件 {p}：{exc}")
            return ""
    elif args.token:
        raw = args.token
    elif os.environ.get("GH_TOKEN"):
        raw = os.environ["GH_TOKEN"]
    else:
        return ""

    for junk in ("\u200b", "\u200c", "\u200d", "\ufeff", "\xa0"):
        raw = raw.replace(junk, "")
    return "".join(raw.split())


def diagnose(token: str) -> bool:
    """令牌形态自检——在发请求之前就指出问题，省得白等一轮。"""
    n = len(token)
    if token.startswith("ghp_"):
        expect = "40 字符（ghp_ + 36）"
        ok = n == 40
    elif token.startswith("github_pat_"):
        expect = "93 字符左右（github_pat_ + 82）"
        ok = 80 <= n <= 100
    elif token.startswith("gho_"):
        expect = "40 字符（gho_ + 36）"
        ok = n == 40
    else:
        expect = "以 ghp_ / gho_ / github_pat_ 开头"
        ok = False

    if not ok:
        print(f"  ✗ 令牌长度是 {n} 字符，疑似被截断。")
        print(f"    正确格式：{expect}")
        print(f"    收到片段：{token[:12]}…{token[-4:] if n > 16 else ''}")
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--token", default="")
    ap.add_argument("--token-file", default="",
                    help="从文件读取令牌（推荐，可绕开聊天框截断）")
    ap.add_argument("--repo", default="PP")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--message", default="游戏本体 + 安卓打包配置 + 云端构建流水线")
    ap.add_argument("--wait", action="store_true", help="推完后等构建结果")
    ap.add_argument("--download", action="store_true", help="构建成功后下载 APK")
    ap.add_argument("--watch", action="store_true",
                    help="不推送，只盯已经触发的那次构建（配合 --download）")
    ap.add_argument("--sha", default="", help="配合 --watch：只盯这个提交")
    ap.add_argument("--outdir", default=os.path.join(ROOT, "dist"))
    args = ap.parse_args()

    token = load_token(args)
    if not token:
        print("✗ 缺少令牌。")
        print("  推荐用法：把令牌写进 D:\\PP\\.gh_token 后运行")
        print("    python tools/push_to_github.py --token-file .gh_token --wait --download")
        print("  或设置环境变量 GH_TOKEN / GH_TOKEN_FILE。")
        return 2

    if not diagnose(token):
        return 2

    print("=== 绕过本机 hosts 对 GitHub 的屏蔽 ===")
    install_dns_patch()
    ip = _doh_lookup("api.github.com")
    print(f"  · api.github.com → {ip or '解析失败'}")

    gh = GitHub(token)

    if args.watch:
        # 已经推过了，只想盯构建结果，就别再推一次（否则会多触发一次构建）
        code, user = gh.call("GET", "/user")
        if code != 200:
            print(f"  ✗ 令牌无效（HTTP {code}）：{user}")
            return 1
        owner = user["login"]
        print(f"  ✓ 账号：{owner}（跳过推送，只盯构建）")
        wait_and_download(gh, owner, args.repo, args.branch, args.outdir,
                          head_sha=args.sha)
        return 0

    print("\n=== 推送 ===")
    pushed = push(gh, args.repo, args.branch, args.message)
    if not pushed:
        return 1
    owner, commit_sha = pushed

    print(f"\n仓库地址：https://github.com/{owner}/{args.repo}")
    print(f"构建页面：https://github.com/{owner}/{args.repo}/actions")

    if args.wait or args.download:
        wait_and_download(gh, owner, args.repo, args.branch, args.outdir,
                          head_sha=commit_sha)
    return 0


if __name__ == "__main__":
    sys.exit(main())
