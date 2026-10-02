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
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

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

    def call(self, method: str, path: str, payload=None, raw=False):
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


# =========================================================
#  文件收集
# =========================================================
SKIP_DIRS = {".git", ".workbuddy", "__pycache__", "preview", ".buildozer",
             "bin", "out", "dist", ".pytest_cache", ".venv", "venv",
             ".vscode", ".idea"}
SKIP_FILES = {"debug.log", ".DS_Store", "Thumbs.db"}
SKIP_EXT = {".pyc", ".pyo", ".apk", ".aab"}

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


def collect_files():
    picked = []
    skipped = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if fn in SKIP_FILES or os.path.splitext(fn)[1] in SKIP_EXT:
                continue
            full = os.path.join(base, fn)
            rel = os.path.relpath(full, ROOT).replace(os.sep, "/")
            if is_secret(rel):
                skipped.append(rel)
                continue
            picked.append((rel, full))
    picked.sort()
    for rel in skipped:
        print(f"      ! 跳过疑似凭据文件：{rel}")
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
    return owner


def wait_and_download(gh: GitHub, owner: str, repo: str, branch: str,
                      outdir: str, timeout_min: int = 90):
    print("\n=== 等待云端构建 ===")
    deadline = time.time() + timeout_min * 60
    run = None
    while time.time() < deadline:
        code, res = gh.call(
            "GET", f"/repos/{owner}/{repo}/actions/runs"
                   f"?branch={branch}&per_page=5")
        if code == 200 and res.get("workflow_runs"):
            r = res["workflow_runs"][0]
            tag = f'{r["id"]} {r["status"]}/{r.get("conclusion")}'
            if run != tag:
                run = tag
                print(f"  · 运行 {r['id']}：{r['status']} "
                      f"{r.get('conclusion') or ''}".rstrip())
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
        dst = os.path.join(outdir, art["name"] + ".zip")
        code, blob = gh.call(
            "GET", f"/repos/{owner}/{repo}/actions/artifacts/{art['id']}/zip",
            raw=True)
        if code != 200:
            print(f"  ✗ 下载 {art['name']} 失败：{blob}")
            continue
        with open(dst, "wb") as f:
            f.write(blob)
        print(f"  ✓ 已下载 {dst}  ({len(blob) / 1048576:.1f} MB)")
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
    print("\n=== 推送 ===")
    owner = push(gh, args.repo, args.branch, args.message)
    if not owner:
        return 1

    print(f"\n仓库地址：https://github.com/{owner}/{args.repo}")
    print(f"构建页面：https://github.com/{owner}/{args.repo}/actions")

    if args.wait or args.download:
        wait_and_download(gh, owner, args.repo, args.branch, args.outdir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
