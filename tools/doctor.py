#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ai-search-stack 工具箱体检（doctor）—— 一条命令巡检全部通道健康。

巡检项（v3.5）：
    - 本地 SearXNG 实例（zhihu 链第一环）：存活 + unresponsive_engines
    - 知乎 cookie：文件存在性 + 年龄（v3.4 起过期可自愈，但仍值得观测）
    - bilibili 官方 API：用一个知名 bvid 探活（只读、无风控压力）
    - 百度直连：首页探活（搜索风控与首页可达是两回事，这里只测通道）
    - google-bridge 服务：/health（通常按需启动，未起不算故障）
    - GitHub API：匿名可达性

用法:
    python tools/doctor.py                  # 全量巡检，逐项 ✅/❌/⚠️
    python tools/doctor.py --cookie-probe   # 只跑知乎 cookie 寿命标定探活
退出码: 0=全绿或仅可选服务未启动（--cookie-probe 时见该模式说明）;
        1=有核心通道故障。
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime

_TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
SEARXNG = os.environ.get("SEARXNG_INSTANCE", "http://127.0.0.1:8888")
COOKIE_PATH = os.path.join(_TOOL_DIR, "chat-scraper", "state",
                           "zhihu_cookies.json")
PROBE_BVID = "BV1GJ411x7h7"   # 知名视频，仅作 API 探活
TIMEOUT = 8

# v3.8.2: cookie 寿命标定（--cookie-probe）。cookie 文件的 fetched_at 只记
# "何时签发"，不记"何时失效"——寿命分布得靠周期性探活积累读数（评估员
# 共识：产出决定自愈策略）。日志在 state/ 下（已 gitignore，只留本地）。
COOKIE_LOG_PATH = os.path.join(_TOOL_DIR, "chat-scraper", "state",
                               "cookie_lifetime_log.jsonl")
PROBE_QUESTION_ID = "19550227"   # bootstrap 同款知名问题，仅作 API 探活

_results = []


def _check(name, fn, optional=False):
    try:
        detail = fn()
        _results.append((name, True, detail, optional))
        print(f"✅ {name}: {detail}")
    except Exception as e:
        _results.append((name, False, str(e)[:120], optional))
        print(f"{'⚠️' if optional else '❌'} {name}: {str(e)[:120]}")


_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}))   # 绕系统代理：代理半死会伪造全红（v3.4 注释同款）


def _get(url, timeout=TIMEOUT, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent":
                                 "ai-search-stack-doctor"})
    with _OPENER.open(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def check_searxng():
    body = _get(f"{SEARXNG}/search?q=ping&format=json")
    data = json.loads(body)
    dead = data.get("unresponsive_engines") or []
    n = len(data.get("results", []))
    return (f"{n} 条结果, {TIMEOUT}s 探活"
            + (f", 不健康引擎: {dead}" if dead else ", 引擎全健康"))


def check_cookie():
    if not os.path.exists(COOKIE_PATH):
        raise RuntimeError("cookie 文件不存在（read 会自动引导自愈，"
                           "或手动跑 zhihu_bootstrap.py）")
    with open(COOKIE_PATH, encoding="utf-8") as f:
        meta = json.load(f)
    age_h = (time.time() - os.path.getmtime(COOKIE_PATH)) / 3600
    has = all(k in (meta.get("cookies") or {})
              for k in ("d_c0", "__zse_ck"))
    if not has:
        raise RuntimeError("cookie 缺少 d_c0/__zse_ck（重跑 zhihu_bootstrap.py）")
    return (f"存在, 龄 {age_h:.1f}h"
            f"{'（>24h 建议跑一次 zhihu_bootstrap.py 续期）' if age_h > 24 else ''}")


def check_bilibili():
    body = _get(f"https://api.bilibili.com/x/web-interface/view?"
                f"bvid={PROBE_BVID}")
    code = json.loads(body).get("code")
    if code != 0:
        raise RuntimeError(f"view API code={code}")
    return "官方 API code=0"


def check_baidu():
    body = _get("https://www.baidu.com/")
    return f"首页 200, {len(body)} 字节（注意：搜索风控另行判定）"


def check_google_bridge():
    body = _get("http://127.0.0.1:18799/health", timeout=3)
    ok = json.loads(body).get("ok")
    if not ok:
        raise RuntimeError("health ok=false")
    return "服务在跑"


def check_github():
    code = urllib.request.urlopen(
        urllib.request.Request("https://api.github.com/"), timeout=TIMEOUT
    ).status
    return f"API 匿名可达 ({code})"


# ---- v3.8.2: --cookie-probe（cookie 寿命标定，独立于全量巡检） ----


def _sys_path_chat_scraper():
    cs = os.path.join(_TOOL_DIR, "chat-scraper")
    if cs not in sys.path:
        sys.path.insert(0, cs)


def _cookie_meta():
    """(cookie 文件 fetched_at, cookie 龄小时)；文件缺失/字段坏返回 (None, None)。"""
    try:
        with open(COOKIE_PATH, encoding="utf-8") as f:
            fetched_at = (json.load(f) or {}).get("fetched_at")
    except (OSError, ValueError):
        return None, None
    age_h = None
    if fetched_at:
        try:
            age_h = round(
                (time.time() - datetime.fromisoformat(fetched_at).timestamp())
                / 3600, 2)
        except (ValueError, TypeError, OSError):
            pass
    return fetched_at, age_h


def cookie_probe(entry_path=COOKIE_LOG_PATH) -> dict:
    """真实调用一次知乎 questions API 标定 cookie 活性，读数追加进 jsonl。

    复用 zhihu_content.fetch_question（签名 + 官方 API，探 PROBE_QUESTION_ID）。
    标定纪律：探活期间 monkeypatch 掉 _try_self_heal——标定要的是 cookie
    真实寿命读数；若过期即自愈刷新，每条 expired 都会被"续命"污染，
    寿命分布永远测不出来。

    读数四态：valid（API 通）/ expired（认证被拒）/ missing（cookie 文件缺
    或无 d_c0，≠ 过期，分开记）/ error（网络、行为风控等其他，不污染两类
    主读数）。返回该条读数 dict；jsonl 写失败抛 OSError 由调用方定退出码。
    """
    _sys_path_chat_scraper()
    import zhihu_content as zc

    fetched_at, age_h = _cookie_meta()
    entry = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tool": "doctor --cookie-probe",
        "question_id": PROBE_QUESTION_ID,
        "fetched_at": fetched_at,
        "cookie_age_h": age_h,
        "status": None,
        "note": "",
    }
    orig_selfheal = zc._try_self_heal
    zc._try_self_heal = lambda: False   # 禁自愈：探真实寿命（见 docstring）
    try:
        info = zc.fetch_question(PROBE_QUESTION_ID)
        entry["status"] = "valid"
        entry["note"] = (f"title={str(info.get('title', ''))[:40]} "
                         f"answers={info.get('answer_count')}")
    except zc._CookieStateMissing as e:
        entry["status"] = "missing"
        entry["note"] = str(e)[:160]
    except zc.ZhihuAuthExpired as e:
        entry["status"] = "expired"
        entry["note"] = f"{getattr(e, 'slug', '')}: {e}"[:160]
    except Exception as e:
        entry["status"] = "error"
        entry["note"] = f"{type(e).__name__}: {e}"[:160]
    finally:
        zc._try_self_heal = orig_selfheal

    os.makedirs(os.path.dirname(entry_path) or ".", exist_ok=True)
    with open(entry_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def cmd_cookie_probe() -> int:
    print(f"== cookie 寿命标定探活（问题 id {PROBE_QUESTION_ID}，禁自愈）==")
    try:
        entry = cookie_probe()
    except Exception as e:   # import 失败/日志写不进等本地故障
        print(f"❌ cookie-probe 本地故障: {type(e).__name__}: {e}")
        return 1
    icon = {"valid": "✅", "expired": "🪦",
            "missing": "⚠️", "error": "❌"}.get(entry["status"], "❓")
    print(f"{icon} status={entry['status']} "
          f"fetched_at={entry['fetched_at']} "
          f"age={entry['cookie_age_h']}h")
    print(f"   {entry['note']}")
    try:
        with open(COOKIE_LOG_PATH, encoding="utf-8") as f:
            n = sum(1 for _ in f)
        print(f"→ 已追加 {COOKIE_LOG_PATH}（累计 {n} 条标定数据）")
    except OSError:
        print(f"→ 已追加 {COOKIE_LOG_PATH}")
    # 本模式只观测不判故障：expired/valid 都是成功读数（标定数据点），exit 0
    return 0


def main(argv=None) -> int:
    import argparse
    p = argparse.ArgumentParser(
        description="ai-search-stack 工具箱体检（全量巡检或单项标定）")
    p.add_argument("--cookie-probe", action="store_true",
                   help="只跑知乎 cookie 寿命标定探活（真实调一次 questions "
                        "API，读数追加 state/cookie_lifetime_log.jsonl），"
                        "不跑全量巡检；expired/valid 均算成功观测，exit 0")
    args = p.parse_args(argv)
    if args.cookie_probe:
        return cmd_cookie_probe()
    print(f"== ai-search-stack doctor @ {time.strftime('%Y-%m-%d %H:%M')} ==")
    _check("SearXNG 本地实例", check_searxng, optional=True)
    _check("知乎 cookie", check_cookie, optional=True)
    _check("bilibili 官方 API", check_bilibili)
    _check("百度直连", check_baidu)
    _check("google-bridge 服务", check_google_bridge, optional=True)
    _check("GitHub API", check_github)
    core = [r for r in _results if not r[3]]
    core_fail = [r for r in core if not r[1]]
    opt_fail = [r for r in _results if not r[1] and r[3]]
    print(f"== 结果: 核心 {len(core) - len(core_fail)}/{len(core)} 正常"
          f"，核心故障 {len(core_fail)}，可选异常 {len(opt_fail)} ==")
    return 1 if core_fail else 0


if __name__ == "__main__":
    sys.exit(main())
