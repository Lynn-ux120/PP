"""GitHub 认证链路诊断（只读，不推送任何东西）。

用法：
    python tools/diag_github.py

会依次检查：
  1. .gh_token 文件的字节形态（长度、是否有 CR/LF/BOM/零宽字符）
  2. 匿名访问 api.github.com —— 确认我们连上的确实是真 GitHub，
     排除"本机 hosts 封锁 + DoH 落到仿冒端点"的可能
  3. Authorization 头用 `token` 与 `Bearer` 两种写法分别试一次
  4. /rate_limit —— 顺带看令牌有没有额度
"""
import hashlib
import os
import sys
import urllib.error
import urllib.request
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import push_to_github as P  # noqa: E402


def mask(t: str) -> str:
    if len(t) <= 12:
        return f"<{len(t)} 字符>"
    return f"{t[:4]}{'*' * (len(t) - 8)}{t[-4:]}"


def probe(headers, label):
    req = urllib.request.Request("https://api.github.com/user", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8", "replace")
            print(f"  [{label}] HTTP {r.status}  {body[:140]}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        print(f"  [{label}] HTTP {e.code}  {body[:200]}")
    except Exception as exc:  # noqa: BLE001
        print(f"  [{label}] 连接失败：{type(exc).__name__}: {exc}")


def main():
    path = os.path.join(ROOT, ".gh_token")
    if not os.path.exists(path):
        print(f"✗ 找不到 {path}")
        return 1

    raw = open(path, "rb").read()
    print("=== 1. 令牌文件形态 ===")
    print(f"  字节数        : {len(raw)}")
    print(f"  含 CR(\\r)    : {b'\\r' in raw}")
    print(f"  含 LF(\\n)    : {b'\\n' in raw}")
    print(f"  含 UTF-8 BOM : {raw.startswith(b'\\xef\\xbb\\xbf')}")
    print(f"  非 ASCII 字节 : {sum(1 for b in raw if b > 127)}")
    print(f"  SHA256(前16)  : {hashlib.sha256(raw).hexdigest()[:16]}")

    token = P.load_token(SimpleNamespace(token_file=path, token=""))
    print(f"  清洗后长度    : {len(token)}")
    print(f"  掩码          : {mask(token)}")
    print(f"  前缀 ghp_     : {token.startswith('ghp_')}")
    print(f"  字符类型掩码  : "
          + "".join("A" if c.isupper() else "a" if c.islower()
                    else "9" if c.isdigit() else "!" for c in token))
    legal = all(c.isalnum() or c == "_" for c in token)
    print(f"  是否全部合法  : {legal}")

    print("\n=== 2. 绕过 hosts 封锁 ===")
    P.install_dns_patch()
    ip = P._doh_lookup("api.github.com")
    print(f"  api.github.com → {ip or '解析失败'}")

    base = {"Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "PP-diag"}

    print("\n=== 3. 匿名访问（验证端点真实性）===")
    probe(base, "无认证")

    for scheme in ("token", "Bearer"):
        print(f"\n=== 4. Authorization: {scheme} ===")
        h = dict(base)
        h["Authorization"] = f"{scheme} {token}"
        probe(h, scheme)

    print("\n=== 5. /rate_limit ===")
    h = dict(base)
    h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request("https://api.github.com/rate_limit", headers=h)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"  HTTP {r.status}  {r.read().decode('utf-8', 'replace')[:160]}")
    except urllib.error.HTTPError as e:
        print(f"  HTTP {e.code}  {e.read().decode('utf-8', 'replace')[:200]}")

    print("\n=== 6. 完全复刻推送脚本的请求方式 ===")
    print("  （同一个 token 走 push_to_github.GitHub.call，用于隔离差异）")
    gh = P.GitHub(token)
    code, res = gh.call("GET", "/user")
    print(f"  GitHub.call('GET','/user') → HTTP {code}  "
          f"{str(res)[:140]}")

    print("\n=== 7. 直接读取脚本内部实际发送的请求 ===")
    print(f"  GitHub.token 长度 : {len(gh.token)}")
    print(f"  GitHub.token 掩码 : {mask(gh.token)}")
    print(f"  ssl 上下文        : {gh.ctx is not None}")
    import urllib.request as _u
    req = _u.Request(P.API + "/user",
                     headers={"Authorization": f"Bearer {gh.token}",
                              "Accept": "application/vnd.github+json",
                              "X-GitHub-Api-Version": "2022-11-28",
                              "User-Agent": "PP-build"},
                     method="GET")
    print(f"  实际请求头        : {dict(req.header_items())}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
