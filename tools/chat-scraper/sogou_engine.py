#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""搜狗搜索引擎 —— 百度不可用时的第三环（真直链在 data-url 属性）

定位（2026-09-09 实测）：
    - 搜狗 web 尊重 site: 操作符（腾讯系，对知乎/CSDN 等收录好）；
    - 结果节点 div.vrwrap 的 **data-url 属性即真实直链**，无需解 /link 跳转
      （比 zhihu_engine 里的搜狗备选还省事——那是知乎站深页面，这里数据在
      节点属性上直接拿）；
    - 连发风控阈值未测，只当保底环用：默认间隔 8s、出错即抛。

错误协议与仓库统一：search(..., on_error="report"/"raise"/"empty")。
"""
import os
import re
import sys
import threading
import time
import urllib.parse
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

__all__ = ["search", "SogouBlocked"]

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
        query = f"{q} site:{site}" if site else q
        resp = session.get(_SEARCH_URL,
                           params={"query": query}, timeout=TIMEOUT)
        if resp.status_code != 200 or "antispider" in resp.url or \
                "验证码" in resp.text[:2000]:
            raise SogouBlocked(
                f"HTTP {resp.status_code}, url={resp.url[:80]!r}")
        rows = _parse_results(resp.text)
        if not rows:
            # 结构正常却 0 条 + 全文有风控标记 → 软风控不是真空。
            # antispider 只在 0 行时查全文：它可能出现在任意正常结果的
            # 标题/摘要里（如搜"反爬虫"主题），无条件查会误杀真结果（审查 B2）
            if "验证码" in resp.text or "antispider" in resp.text.lower():
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
    p.add_argument("q", help="query")
    p.add_argument("--site", default=None,
                   help="站点域名，如 csdn.net；省略为通用搜索")
    p.add_argument("--num", type=int, default=10)
    p.add_argument("--vendor", default="?")
    p.add_argument("--role", default="fallback")
    p.add_argument("--on-error", default="report",
                   choices=["report", "raise", "empty"])
    args = p.parse_args()
    results = search(args.q, num=args.num, vendor=args.vendor,
                     role=args.role, site=args.site, on_error=args.on_error)
    _errors = [r for r in results if "error" in r]
    if _errors:
        for r in _errors:
            print(f"[sogou_engine] error: {r['error']}", file=sys.stderr)
        sys.exit(1)
    print(__import__("json").dumps(results, ensure_ascii=False, indent=2))
