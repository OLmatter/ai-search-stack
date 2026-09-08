"""真冒烟测试：只调公网只读 API，验证工具端到端能出真实结果。

默认只跑 hn + github（最稳、零部署）。其余工具按参数显式开。
CI 里本文件以 continue-on-error 运行（网络抖动不应打断构建），
本地排障时全量跑：python tests/smoke_live.py --all
"""
import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def ok(label, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {label} {detail}")
    return cond


def smoke_hackernews():
    r = subprocess.run(
        [sys.executable, str(REPO / "tools/hackernews/hackernews_client.py"),
         "python", "--since", "30d", "--vendor", "smoke", "--role", "verify"],
        capture_output=True, text=True, timeout=60)
    try:
        results = json.loads(r.stdout)
    except json.JSONDecodeError:
        return ok("hackernews", False, f"stdout 非 JSON: {r.stdout[:120]}")
    real = [x for x in results if "error" not in x]
    return ok("hackernews", r.returncode == 0 and len(real) >= 1,
              f"{len(real)} 条真实结果")


def smoke_github():
    r = subprocess.run(
        [sys.executable, str(REPO / "tools/github/github_client.py"),
         "releases", "anthropics/claude-code", "--num", "3",
         "--vendor", "smoke", "--role", "verify"],
        capture_output=True, text=True, timeout=60)
    if r.returncode != 0 and "403" in r.stderr and "rate limit" in r.stderr:
        print("[SKIP] github 匿名限额 60/h 耗尽（配额问题，非工具故障；"
              "设 GITHUB_TOKEN 可解除）")
        return True
    try:
        results = json.loads(r.stdout)
    except json.JSONDecodeError:
        return ok("github", False, f"stdout 非 JSON: {r.stdout[:120]}")
    return ok("github", r.returncode == 0 and len(results) >= 1,
              f"{len(results)} 条 release")


def smoke_searxng():
    """需本地实例：tools/searxng/docker 下 docker compose up -d"""
    try:
        with urllib.request.urlopen(
                "http://127.0.0.1:8888/search?q=ping&format=json",
                timeout=20) as resp:
            data = json.loads(resp.read())
        return ok("searxng", len(data.get("results", [])) >= 1,
                  f"{len(data.get('results', []))} 条")
    except Exception as e:
        return ok("searxng", False, f"本地实例未起或异常: {e}")


def smoke_bilibili():
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, r'%s'); "
         "from search import search; rs = search('python', platforms=['bilibili'], num=3); "
         "print(len([x for x in rs if 'error' not in x]))"
         % (REPO / "tools/chat-scraper")],
        capture_output=True, text=True, timeout=90)
    return ok("chat-scraper/bilibili", r.returncode == 0 and r.stdout.strip() and
              int(r.stdout.strip() or 0) >= 1, f"{r.stdout.strip()} 条")


SMOKES = {"hn": smoke_hackernews, "gh": smoke_github,
          "searxng": smoke_searxng, "bilibili": smoke_bilibili}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("tools", nargs="*", choices=[*SMOKES, "all"], default=["hn", "gh"])
    args = ap.parse_args()
    names = list(SMOKES) if "all" in args.tools else (args.tools or ["hn", "gh"])
    sys.exit(0 if all(SMOKES[n]() for n in names) else 1)
