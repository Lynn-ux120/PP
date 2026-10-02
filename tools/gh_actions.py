# -*- coding: utf-8 -*-
"""查看 GitHub Actions 的运行 / 任务 / 日志（只读）。

用法：
    python tools/gh_actions.py runs                 # 最近的运行列表
    python tools/gh_actions.py jobs <run_id>        # 某次运行的步骤明细
    python tools/gh_actions.py logs <run_id>        # 下载失败步骤的日志

依赖 tools/push_to_github.py 里的 GitHub 客户端与 DNS 绕过（本机 hosts 屏蔽了 GitHub）。

注意：GitHub 的日志接口会 302 到 Azure Blob，默认的 urllib 会把 Authorization
头一起转发过去，Azure 会回 401 InvalidAuthenticationInfo。
所以这里先用自定义的 NoRedirect 拿到 Location，再**不带认证头**去下载。
"""
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import push_to_github as P  # noqa: E402

OWNER, REPO = "Lynn-ux120", "PP"


def client():
    P.install_dns_patch()
    token = P.load_token(type("A", (), {"token_file": ".gh_token", "token": ""})())
    return P.GitHub(token)


def cmd_runs(gh, argv):
    code, res = gh.call("GET", f"/repos/{OWNER}/{REPO}/actions/runs?per_page=15")
    if code != 200:
        print("HTTP", code, res)
        return 1
    print(f"{'run_id':>12}  {'commit':8}  {'状态':12} {'结论':10} 创建时间")
    for r in res.get("workflow_runs", []):
        print(f"{r['id']:>12}  {r['head_sha'][:8]}  {r['status']:12} "
              f"{r.get('conclusion') or '-':10} {r['created_at']}")
    return 0


def cmd_jobs(gh, argv):
    run_id = argv[0]
    code, res = gh.call("GET", f"/repos/{OWNER}/{REPO}/actions/runs/{run_id}/jobs")
    if code != 200:
        print("HTTP", code, res)
        return 1
    for j in res["jobs"]:
        print(f"JOB {j['id']}  {j['name']}  ->  {j.get('conclusion')}")
        for s in j.get("steps", []):
            mark = {"success": "OK  ", "failure": "FAIL",
                    "skipped": "skip"}.get(s.get("conclusion"), "?   ")
            print(f"   {mark} {s['number']:>2}  {s['name']}")
    return 0


def fetch_log(gh, job_id: int, token: str | None = None) -> bytes:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    url = f"https://api.github.com/repos/{OWNER}/{REPO}/actions/jobs/{job_id}/logs"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {gh.token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "PP-build"})
    try:
        opener = urllib.request.build_opener(NoRedirect)
        opener.open(req, timeout=30)
        return b""
    except urllib.error.HTTPError as e:
        loc = e.headers.get("Location")
        if not loc:
            return f"<no redirect: HTTP {e.code}>".encode()
        # 关键：第二次请求不要带 Authorization
        plain = urllib.request.Request(loc, headers={"User-Agent": "PP-build"})
        with urllib.request.urlopen(plain, timeout=120) as r:
            return r.read()


def cmd_logs(gh, argv):
    run_id = argv[0]
    code, res = gh.call("GET", f"/repos/{OWNER}/{REPO}/actions/runs/{run_id}/jobs")
    if code != 200:
        print("HTTP", code, res)
        return 1
    for j in res["jobs"]:
        if j.get("conclusion") not in (None, "success"):
            data = fetch_log(gh, j["id"])
            print(f"=== JOB {j['id']} {j['name']}  {len(data)} bytes ===")
            text = data.decode("utf-8", "replace")
            # 只打印有信息量的行，避免刷屏
            keep = []
            for line in text.splitlines():
                s = re.sub(r"^\S+Z\s?", "", line)
                if re.search(r"error|Error|ERROR|Traceback|Exception|##\[error\]|"
                             r"failed|FAILED|No such|not found|WARNING|警告|"
                             r"buildozer|Downloading|Unpacking|Installing|"
                             r"Command failed|STDERR", s):
                    keep.append(s.rstrip())
            print("\n".join(keep[-80:]) if keep else "(无明显错误行，打印末 40 行)")
            if not keep:
                print("\n".join(text.splitlines()[-40:]))
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    gh = client()
    cmd = sys.argv[1]
    table = {"runs": cmd_runs, "jobs": cmd_jobs, "logs": cmd_logs}
    if cmd not in table:
        print(__doc__)
        return 2
    if cmd != "runs" and len(sys.argv) < 3:
        print("需要 run_id")
        return 2
    return table[cmd](gh, sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())
