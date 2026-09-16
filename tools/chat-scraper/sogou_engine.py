#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""搜狗搜索引擎 —— 百度不可用时的第三环（真直链在 data-url 属性）

定位（2026-09-09 实测）：
    - 搜狗 web 尊重 site: 操作符（腾讯系，对知乎/CSDN 等收录好）；
    - 结果节点 div.vrwrap 的 **data-url 属性即真实直链**，无需解 /link 跳转
      （比 zhihu_engine 里的搜狗备选还省事——那是知乎站深页面，这里数据在
      节点属性上直接拿）；
    - 连发风控阈值（v3.13 标定，2026-09-16 本机实测，读数
      state/sogou_throttle_log.jsonl）：短间隔连发（探测 sleep 2s/发，
      含请求自身耗时的实测请求节奏 2~4s/发）第 1~4 发全过审
      （HTTP 200、9 行真结果），第 5 发即被重定向 antispider 页——
      **连发阈值 = 4 发**；风控后 ~171s 冷却单发即恢复。默认间隔
      8s 有充足余量，维持不变；更长连发/更高频阈值未测，仍只当保底环。

标定（v3.13）：python sogou_engine.py --probe 6 --probe-interval 2
    连发探测，每请求读数追加 state/sogou_throttle_log.jsonl，首个风控
    读数即停（参照 doctor --cookie-probe 的低成本标定模式）。

恢复曲线标定（v3.14）：python tools/doctor.py --sogou-probe
    单发探活（判定与 search 同判据），读数追加
    state/sogou_recovery_log.jsonl，自带距上次风控的秒数（对照连发
    标定日志）——连发标定测"多快触发"，恢复曲线靠风控后周期性单发
    积累"多久恢复"（v3.13 单点：~171s 单发即恢复，待更多读数）。

错误协议与仓库统一：search(..., on_error="report"/"raise"/"empty")。
"""
import datetime
import json
import os
import re
import sys
import threading
import time
import urllib.parse
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

__all__ = ["search", "probe_burst", "probe_once", "SogouBlocked"]

_TOOL = "chat-scraper"
_SEARCH_URL = "https://www.sogou.com/web"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
# 完整 Chrome Accept（与 baidu_engine 同理：*/* 配 Chrome UA 是机器人指纹）
_ACCEPT_FULL = ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8,"
                "application/signed-exchange;v=b3;q=0.7")

ENV_MIN_INTERVAL = "CHAT_SCRAPER_SOGOU_MIN_INTERVAL"
DEFAULT_MIN_INTERVAL = 8.0
TIMEOUT = 15
# v3.13 连发阈值标定：读数日志（参照 cookie_lifetime_log.jsonl 的 jsonl 模式）
_STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
PROBE_LOG_PATH = os.path.join(_STATE_DIR, "sogou_throttle_log.jsonl")
# v3.14 恢复曲线标定：doctor --sogou-probe 单发探活读数（见 probe_once）
RECOVERY_LOG_PATH = os.path.join(_STATE_DIR, "sogou_recovery_log.jsonl")

_throttle_lock = threading.Lock()
_last_request_ts = 0.0


class SogouBlocked(RuntimeError):
    """搜狗风控页（验证码/antispider）。slug 供统一错误协议使用。"""

    slug = "sogou_blocked"


def _min_interval() -> float:
    raw = os.environ.get(ENV_MIN_INTERVAL, "")
    try:
        val = float(raw) if raw else DEFAULT_MIN_INTERVAL
    except ValueError:
        return DEFAULT_MIN_INTERVAL
    return val if val >= 0 else DEFAULT_MIN_INTERVAL


def _wait_turn() -> None:
    global _last_request_ts
    with _throttle_lock:
        wait = _last_request_ts + _min_interval() - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request_ts = time.monotonic()


def _clean_title(s: str) -> str:
    """搜狗标题高亮形如 <em><!--red_beg-->关键词<!--red_end--></em>。
    分隔符必须空串（同 zhihu_engine：get_text(" ") 会拆散中文标题）。"""
    s = re.sub(r"<!--/?red_(?:beg|end)-->", "", s or "")
    s = re.sub(r"<[^>]+>", "", s)
    import html as _html
    return _html.unescape(s).strip()


def _parse_results(html: str) -> List[Dict[str, str]]:
    """搜狗结果页 -> [{title, url, snippet}]。

    data-url 属性=真实直链（实测在 vrwrap 节点上）；没有时回退 h3 a 的
    href（可能是 /link 跳转链，保留原样不解析——第三环不再花请求）。
    """
    soup = BeautifulSoup(html, "lxml")
    out: List[Dict[str, str]] = []
    seen = set()
    for node in soup.select("div.vrwrap, div.rb"):
        a = node.select_one("h3 a[href]")
        if a is None:
            continue
        url = (node.get("data-url") or "").strip()
        if not url:
            href = (a.get("href") or "").strip()
            if not href:
                continue
            url = ("https://www.sogou.com" + href) if href.startswith("/link") else href
        if url in seen:
            continue
        seen.add(url)
        snippet = ""
        for sel in (".space-txt", ".str_info", ".text-layout", ".fz-mid", "p"):
            el = node.select_one(sel)
            if el is not None:
                text = el.get_text(" ", strip=True)
                if text:
                    snippet = text[:300]
                    break
        out.append({
            "title": _clean_title(a.get_text("", strip=False)),
            "url": url,
            "snippet": snippet,
        })
    return out


def _blocked(status: int, url: str, text: str) -> bool:
    """主风控判定（search 与 probe_burst 共用，判据逐字一致）。"""
    return status != 200 or "antispider" in url or "验证码" in text[:2000]


def _soft_blocked(text: str) -> bool:
    """0 行结果时的软风控判定：全文有标记 → 软风控不是真空。

    标记可能出现在任意正常结果的标题/摘要里（如搜"反爬虫"主题），
    只在 0 行时查全文，无条件查会误杀真结果（审查 B2）。"""
    return "验证码" in text or "antispider" in text.lower()


def _new_session() -> requests.Session:
    """与 search() 同款会话（headers/代理指纹），probe_burst 复用。"""
    session = requests.Session()
    session.trust_env = False
    proxy = os.environ.get("CHAT_SCRAPER_SOGOU_PROXY", "")
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
    session.headers.update({
        "User-Agent": _UA,
        "Referer": "https://www.sogou.com/",
        "Accept": _ACCEPT_FULL,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    return session


def probe_burst(count: int = 6, interval: float = 2.0,
                query: str = "人工智能",
                log_path: Optional[str] = PROBE_LOG_PATH) -> List[Dict]:
    """连发风控阈值标定（v3.13，参照 doctor --cookie-probe 低成本标定模式）。

    以短间隔连发 count 次搜索请求——绕过默认 8s 节流（探测目的就是测短
    间隔是否触发风控；每次请求前仍如实更新引擎级节流时间戳，同进程内的
    普通 search 不至于贴脸连发）。每请求读数一行追加 jsonl：

        {ts, tool, seq, interval, http, rows, blocked, note}

    - blocked 判定与 search() 同判据（_blocked / 0 行 + _soft_blocked）；
    - 首个风控读数即停：证据已到手，不烧多余请求；
    - 网络异常记一行 error 读数即停（网络不通测不出风控阈值）；
    - log_path=None 只测不落账（测试用）。

    返回读数列表。阈值声明以 jsonl 实测读数为准（判词只收证据链）。
    """
    global _last_request_ts
    readings: List[Dict] = []
    session = _new_session()
    log_f = None
    try:
        if log_path:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            log_f = open(log_path, "a", encoding="utf-8")
        for seq in range(count):
            if seq:
                time.sleep(interval)
            entry: Dict = {
                "ts": datetime.datetime.now().astimezone()
                .isoformat(timespec="seconds"),
                "tool": "sogou_engine --probe",
                "seq": seq,
                "interval": interval,
                "http": None,
                "rows": None,
                "blocked": False,
                "note": "",
            }
            try:
                with _throttle_lock:
                    _last_request_ts = time.monotonic()
                resp = session.get(_SEARCH_URL,
                                   params={"query": query}, timeout=TIMEOUT)
                rows = _parse_results(resp.text)
                entry["http"] = resp.status_code
                entry["rows"] = len(rows)
                if _blocked(resp.status_code, resp.url, resp.text) or \
                        (not rows and _soft_blocked(resp.text)):
                    entry["blocked"] = True
                    entry["note"] = f"url={resp.url[:80]!r}"
            except Exception as e:  # noqa: BLE001 —— 读数即产物，不能炸
                entry["note"] = f"{type(e).__name__}: {str(e)[:140]}"
                readings.append(entry)
                if log_f:
                    log_f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    log_f.flush()
                break
            readings.append(entry)
            if log_f:
                log_f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                log_f.flush()
            if entry["blocked"]:
                break   # 首个风控读数即停：证据到手，不烧多余请求
    finally:
        if log_f:
            log_f.close()
    return readings


def _since_last_block_s(
        throttle_log: Optional[str] = PROBE_LOG_PATH) -> "Optional[float]":
    """距连发标定日志最后一次风控读数的秒数（恢复曲线的 x 轴）。

    扫 sogou_throttle_log.jsonl 找末条 blocked=true 的 ts 起算；无记录、
    文件缺失、坏行（含合法 JSON 但非对象行）一律如实返回 None
    （best-effort 字段，不阻塞探活本体）。
    """
    if not throttle_log:
        return None
    last_block_ts = ""
    try:
        with open(throttle_log, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and e.get("blocked"):
                    last_block_ts = e.get("ts") or ""
    except OSError:
        return None
    if not last_block_ts:
        return None
    try:
        dt = datetime.datetime.fromisoformat(last_block_ts)
    except ValueError:
        return None
    return round(time.time() - dt.timestamp(), 1)


def probe_once(query: str = "人工智能",
               log_path: Optional[str] = RECOVERY_LOG_PATH,
               tool: str = "sogou_engine probe_once",
               throttle_log: Optional[str] = PROBE_LOG_PATH) -> Dict:
    """单发探活（v3.14 恢复曲线标定，doctor --sogou-probe 的引擎侧实现）。

    连发标定（probe_burst）测的是"多快触发风控"；恢复曲线要的是"风控后
    多久恢复"——无法一次测出，只能靠风控后周期性单发探活积累读数：每次
    一发请求，记录此刻是否仍被风控，读数自带距上次风控的秒数
    （since_last_block_s，从连发标定日志末条 blocked 读数起算，无记录为
    null）。恢复阈值以 jsonl 实测读数为准（判词只收证据链；v3.13 单点：
    风控后 ~171s 单发即恢复）。

    - 判定与 search() 逐字同判据（_blocked / 0 行 + _soft_blocked）；
    - 走引擎默认节流 _wait_turn——探活不是攻击，不绕节流；
    - 读数一行追加 log_path（默认 state/sogou_recovery_log.jsonl；
      None 只测不落账，测试用）：

        {ts, tool, http, rows, blocked, since_last_block_s, note}

    - 网络异常也记读数落账（风控期 RST/超时是恢复曲线的真实数据点）。
    返回该条读数 dict。
    """
    entry: Dict = {
        "ts": datetime.datetime.now().astimezone()
        .isoformat(timespec="seconds"),
        "tool": tool,
        "http": None,
        "rows": None,
        "blocked": False,
        "since_last_block_s": _since_last_block_s(throttle_log),
        "note": "",
    }
    try:
        _wait_turn()
        session = _new_session()
        resp = session.get(_SEARCH_URL,
                           params={"query": query}, timeout=TIMEOUT)
        rows = _parse_results(resp.text)
        entry["http"] = resp.status_code
        entry["rows"] = len(rows)
        if _blocked(resp.status_code, resp.url, resp.text) or \
                (not rows and _soft_blocked(resp.text)):
            entry["blocked"] = True
            entry["note"] = f"url={resp.url[:80]!r}"
    except Exception as e:  # noqa: BLE001 —— 读数即产物，不能炸
        entry["note"] = f"{type(e).__name__}: {str(e)[:140]}"
    if log_path:
        os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def search(q: str, num: int = 10, since: Optional[str] = None,
           vendor: str = "?", role: str = "fallback",
           site: Optional[str] = None, platform: Optional[str] = None,
           on_error: str = "report") -> List[Dict]:
    """搜狗搜索（可带 site: 站内过滤）。

    注意：搜狗 web 无时间窗参数，since 仅透传记录不做过滤（README 已注明）。
    """
    name = platform or site or "general"
    try:
        _wait_turn()
        session = _new_session()
        query = f"{q} site:{site}" if site else q
        resp = session.get(_SEARCH_URL,
                           params={"query": query}, timeout=TIMEOUT)
        if _blocked(resp.status_code, resp.url, resp.text):
            raise SogouBlocked(
                f"HTTP {resp.status_code}, url={resp.url[:80]!r}")
        rows = _parse_results(resp.text)
        if not rows and _soft_blocked(resp.text):
            # 结构正常却 0 条 + 全文有风控标记 → 软风控不是真空（审查 B2）
            raise SogouBlocked("soft-block page (0 parsed rows, "
                               "risk markers present)")
        return [{
            "title": r["title"],
            "url": r["url"],
            "snippet": r["snippet"],
            "platform": name,
            "engine": "sogou",
            "vendor": vendor,
            "role": role,
            "since": since or "all",
        } for r in rows[:num]]
    except Exception as e:
        if on_error == "raise":
            raise
        if on_error == "report":
            slug = getattr(e, "slug", None) or type(e).__name__
            return [{"error": f"{slug}: {e}", "tool": _TOOL,
                     "query": q, "platform": name}]
        return []  # on_error == "empty"


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(
        description="搜狗搜索（site: 站内过滤；百度不可用时的第三环）")
    p.add_argument("q", help="query", nargs="?", default=None)
    p.add_argument("--site", default=None,
                   help="站点域名，如 csdn.net；省略为通用搜索")
    p.add_argument("--num", type=int, default=10)
    p.add_argument("--vendor", default="?")
    p.add_argument("--role", default="fallback")
    p.add_argument("--on-error", default="report",
                   choices=["report", "raise", "empty"])
    p.add_argument("--probe", type=int, default=0, metavar="N",
                   help="连发风控阈值标定：短间隔连发 N 次即退出，每请求"
                        "读数追加 state/sogou_throttle_log.jsonl（首个"
                        "风控读数即停），不做普通搜索；间隔配 "
                        "--probe-interval")
    p.add_argument("--probe-interval", type=float, default=2.0,
                   help="探测连发间隔秒数（默认 2，远小于默认节流 8s）")
    args = p.parse_args()
    if args.probe > 0:
        readings = probe_burst(count=args.probe,
                               interval=args.probe_interval)
        print(json.dumps(readings, ensure_ascii=False, indent=2))
        hits = sum(1 for r in readings if r["blocked"])
        print(f"[sogou_engine] probe: {len(readings)} 发，风控 {hits} 次"
              f"（读数已追加 {PROBE_LOG_PATH}）", file=sys.stderr)
        sys.exit(0)
    if not args.q:
        p.error("缺少搜索词 q（或使用 --probe N 做阈值标定）")
    results = search(args.q, num=args.num, vendor=args.vendor,
                     role=args.role, site=args.site, on_error=args.on_error)
    _errors = [r for r in results if "error" in r]
    if _errors:
        for r in _errors:
            print(f"[sogou_engine] error: {r['error']}", file=sys.stderr)
        sys.exit(1)
    print(__import__("json").dumps(results, ensure_ascii=False, indent=2))
