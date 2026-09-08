#!/usr/bin/env python
"""知乎专用搜索：降级链 本机SearXNG → 搜狗 → 百度 site:

为什么需要专用引擎（2026-09-09 实测，证据存 .scratch/r2/）：
- 知乎官方 API 纯 HTTP 不可用：x-zse-96（"101_3_3.0"）签名算法已移植且
  服务器验签通过（错误码 10003→40353 跃迁为证），但 search_v3 有边缘 WAF
  （400 {"HitLabels":null}，与签名无关），且访客 cookie d_c0/__zse_ck 由
  zse-ck VMP 浏览器挑战签发，纯 HTTP 拿不到。除非未来加无头浏览器引导
  cookie，否则此路不通。
- 主路径：本机 SearXNG 实例（searxng/docker 一条命令起，brave 后端实测
  唯一严格尊重 site: 且返回直链、零验证码）。
- 备选：搜狗 web 尊重 site:（腾讯系与知乎合作收录好），但结果包在
  /link?url= 跳转里，需二次解析（默认开启，间隔节流，可关）。
- 保底：百度 site:（复用 baidu_engine；百度软风控是 IP 级、时好时坏）。

错误协议与仓库统一：search(..., on_error="report"/"raise"/"empty")。
链条内单引擎故障自动降级；全链失败才报错（slug 取最后一环）。
"""
import json
import re
import sys
import threading
import time
import urllib.parse
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

__all__ = ["search"]

_TOOL = "chat-scraper"
_PLATFORM = "zhihu"

SEARXNG_INSTANCE = "http://127.0.0.1:8888"   # tools/searxng/docker 起的本地实例
ENV_SEARXNG_INTERVAL = "CHAT_SCRAPER_SEARXNG_MIN_INTERVAL"
ENV_SOGOU_INTERVAL = "CHAT_SCRAPER_SOGOU_MIN_INTERVAL"
ENV_SOGOU_RESOLVE = "CHAT_SCRAPER_SOGOU_RESOLVE"
DEFAULT_SEARXNG_INTERVAL = 2.0   # 本机服务，但背后是真实上游引擎，保持礼貌
DEFAULT_SOGOU_INTERVAL = 5.0     # 搜狗验证码随频率上升，宁慢勿封

_SINCE_TO_SEARXNG = {"24h": "day", "7d": "week", "30d": "month", "90d": "year"}
_SOGOU_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
_throttle_lock = threading.Lock()
_last_searxng_ts = [0.0]
_last_sogou_ts = [0.0]
_last_resolve_ts = [0.0]


class SearxngUnavailable(RuntimeError):
    slug = "searxng_unavailable"


class SogouBlocked(RuntimeError):
    slug = "sogou_blocked"


def _env_interval(env: str, default: float) -> float:
    raw = ""
    import os
    raw = os.environ.get(env, "")
    try:
        val = float(raw) if raw else default
    except ValueError:
        return default
    return val if val >= 0 else default


def _wait_turn(ts_slot: List[float], interval: float) -> None:
    """模块级节流：先到先得占位， sleep 在锁外（与 baidu_engine 同款设计）。"""
    while True:
        wait_s = 0.0
        with _throttle_lock:
            now = time.monotonic()
            elapsed = now - ts_slot[0]
            if ts_slot[0] > 0 and elapsed < interval:
                wait_s = interval - elapsed
            else:
                ts_slot[0] = now
                return
        time.sleep(wait_s)


def _clean_sogou_title(s: str) -> str:
    """搜狗标题高亮形如 <em><!--red_beg-->关键词<!--red_end--></em>。

    分隔符必须用空串：get_text(" ") 会在高亮标签边界插空格，
    中文标题（如「从零开始学Python」）会被拆成「从零开始学 Python」。
    """
    s = re.sub(r"<!--/?red_(?:beg|end)-->", "", s or "")
    s = re.sub(r"<[^>]+>", "", s)
    import html as _html
    return _html.unescape(s).strip()


def _searxng_search(q: str, num: int, since: Optional[str],
                    vendor: str, role: str) -> List[Dict]:
    """主路径：本机 SearXNG，site: 过滤交给聚合后端（实测 brave 严格尊重）。"""
    _wait_turn(_last_searxng_ts, _env_interval(
        ENV_SEARXNG_INTERVAL, DEFAULT_SEARXNG_INTERVAL))
    instance = SEARXNG_INSTANCE.rstrip("/")
    params: Dict[str, object] = {
        "q": f"{q} site:zhihu.com",
        "format": "json",
        "safesearch": "0",
    }
    tr = _SINCE_TO_SEARXNG.get(since or "")
    if tr:
        params["time_range"] = tr
    try:
        resp = requests.get(f"{instance}/search", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise SearxngUnavailable(
            f"instance {instance}: {type(e).__name__}: {e}") from e
    out: List[Dict] = []
    for item in data.get("results", [])[:num]:
        url = item.get("url", "")
        if "zhihu.com/" not in url:   # 后端偶尔漏进无关域，二次保险
            continue
        out.append({
            "title": item.get("title", ""),
            "url": url,
            "snippet": (item.get("content") or "").strip(),
            "platform": _PLATFORM,
            "engine": f"searxng:{item.get('engine', '?')}",
            "vendor": vendor,
            "role": role,
            "since": since or "all",
        })
    return out


def _sogou_parse(html: str) -> List[Dict]:
    """搜狗结果页 -> [{title, link_href, snippet}]（link_href 可能是 /link 跳转）。"""
    soup = BeautifulSoup(html, "lxml")
    out: List[Dict] = []
    seen = set()
    for node in soup.select("div.vrwrap, div.rb"):
        a = node.select_one("h3 a[href]")
        if a is None:
            continue
        href = (a.get("href") or "").strip()
        if not href:
            continue
        if href.startswith("/link"):
            href = "https://www.sogou.com" + href
        if href in seen:
            continue
        seen.add(href)
        snippet = ""
        for sel in (".space-txt", ".str_info", ".text-layout", ".fz-mid", "p"):
            el = node.select_one(sel)
            if el is not None:
                text = el.get_text(" ", strip=True)
                if text:
                    snippet = text[:300]
                    break
        out.append({
            # strip=False：bs4 的 strip 会逐节点去空白，把「 - 知乎」的空格吃掉
            "title": _clean_sogou_title(a.get_text("", strip=False)),
            "link_href": href,
            "snippet": snippet,
        })
    return out


_LOCATION_RE = re.compile(r'window\.location\.replace\("([^"]+)"\)')


def _resolve_sogou_link(session: requests.Session, link_url: str) -> str:
    """解开搜狗 /link?url= 跳转：302 Location 或 location.replace 页面。

    失败原样返回跳转链（调用方不做二次尝试）。
    """
    _wait_turn(_last_resolve_ts, 2.0)
    try:
        resp = session.get(link_url, timeout=10, allow_redirects=False,
                           headers={"User-Agent": _SOGOU_UA})
        if 300 <= resp.status_code < 400:
            return resp.headers.get("Location") or link_url
        m = _LOCATION_RE.search(resp.text)
        return m.group(1) if m else link_url
    except Exception:
        return link_url


def _sogou_search(q: str, num: int, vendor: str, role: str,
                  since: Optional[str] = None) -> List[Dict]:
    """备选路径：搜狗 site: 搜索（跳转解析默认开，可 env 关）。

    注意：搜狗 web 无时间窗参数，since 仅透传记录不做过滤（与文档一致）。
    """
    import os
    _wait_turn(_last_sogou_ts, _env_interval(
        ENV_SOGOU_INTERVAL, DEFAULT_SOGOU_INTERVAL))
    session = requests.Session()
    session.headers.update({"User-Agent": _SOGOU_UA})
    resp = session.get("https://www.sogou.com/web",
                       params={"query": f"{q} site:zhihu.com"}, timeout=15)
    if resp.status_code != 200 or "antispider" in resp.url or \
            "验证码" in resp.text[:2000]:
        raise SogouBlocked(
            f"HTTP {resp.status_code}, url={resp.url[:80]!r}")
    parsed = _sogou_parse(resp.text)
    resolve = os.environ.get(ENV_SOGOU_RESOLVE, "1") not in ("0", "false")
    out: List[Dict] = []
    for row in parsed[:num]:
        url = row["link_href"]
        if resolve and "/link?url=" in url:
            url = _resolve_sogou_link(session, url)
        out.append({
            "title": row["title"],
            "url": url,
            "snippet": row["snippet"],
            "platform": _PLATFORM,
            "engine": "sogou",
            "vendor": vendor,
            "role": role,
            "since": since or "all",
        })
    return out


def _baidu_fallback(q: str, num: int, since: Optional[str],
                    vendor: str, role: str) -> List[Dict]:
    """保底：百度 site:（软风控期会报 baidu_soft_blocked / ConnectionError）。"""
    import baidu_engine
    rows = baidu_engine.search(q, num=num, since=since, vendor=vendor,
                               role=role, site="zhihu.com",
                               platform=_PLATFORM, on_error="raise")
    for r in rows:
        r["engine"] = "baidu"
    return rows


def search(q: str, num: int = 10, since: Optional[str] = None,
           vendor: str = "?", role: str = "primary",
           site: str = "zhihu.com",
           on_error: str = "report") -> List[Dict]:
    """知乎搜索：SearXNG → 搜狗 → 百度 降级链。

    单引擎报错或 0 结果都触发降级（site: 限定下 0 结果常常是引擎索引弱，
    不是真空）；全链失败时按 on_error 协议报错，error 里带完整链条日志。
    site 参数保留（zhuanlan 路由会传 zhuanlan.zhihu.com），当前实现固定
    查 zhihu.com 全域——zhuanlan 的差异留给百度保底路径。
    """
    chain: List[str] = []
    last_error: Optional[Exception] = None
    for name, fn in (("searxng", lambda: _searxng_search(q, num, since, vendor, role)),
                     ("sogou", lambda: _sogou_search(q, num, vendor, role, since)),
                     ("baidu", lambda: _baidu_fallback(q, num, since, vendor, role))):
        chain.append(name)
        try:
            rows = fn()
            if rows:
                return rows
            chain[-1] += "(0条)"      # 真空也降级：下一引擎可能索引更好
        except Exception as e:        # noqa: BLE001 —— 链式降级就是来吃异常的
            last_error = e
            chain[-1] += f"(失败:{type(e).__name__})"
    if last_error is not None:
        if on_error == "raise":
            raise last_error
        if on_error == "report":
            slug = getattr(last_error, "slug", None) or type(last_error).__name__
            return [{"error": f"{slug}: {last_error}", "tool": _TOOL,
                     "query": q, "platform": _PLATFORM,
                     "chain": "→".join(chain) or "none"}]
    return []   # 全链真空（都成功但都 0 结果）——这是真 0 结果


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(
        description="知乎搜索（SearXNG→搜狗→百度 降级链）")
    p.add_argument("q", help="query")
    p.add_argument("--num", type=int, default=10)
    p.add_argument("--since", default=None,
                   help="24h/7d/30d/90d（仅 searxng 路径生效），省略不过滤")
    p.add_argument("--vendor", default="?")
    p.add_argument("--role", default="primary")
    p.add_argument("--on-error", default="report",
                   choices=["report", "raise", "empty"])
    args = p.parse_args()
    results = search(args.q, num=args.num, since=args.since,
                     vendor=args.vendor, role=args.role,
                     on_error=args.on_error)
    _errors = [r for r in results if "error" in r]
    if _errors:
        for r in _errors:
            print(f"[zhihu_engine] error: {r['error']} (chain: "
                  f"{r.get('chain', '?')})", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(results, ensure_ascii=False, indent=2))
