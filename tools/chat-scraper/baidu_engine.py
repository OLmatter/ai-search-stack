#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""百度搜索引擎 —— site: 站内过滤 + 无 site: 通用搜索

实测结论（2026-09-09 本机验证，v3 重写的依据）:
    - 百度尊重 site: 操作符: "claude site:zhihu.com" 首次请求 19/19 全部命中
      zhuanlan.zhihu.com 真实直链。
    - 解析法: 结果节点 div.result 的 h3 文本 + **mu 属性**。mu 即真实目标 URL，
      免去百度 link 重定向解析；h3 内 a[href] 只是百度跳转链，不可直接用。
    - 软风控: 短间隔连发会返回 HTTP 200 的占位页，
      特征 len(html) < 5000 且含 "timeout"（实测 1488 字节）。
      因此必须: Session 复用 + 请求间隔(默认 20s, >=15s) + 占位页检测 + 指数退避。
      占位页属于 error（baidu_soft_blocked），绝不当 0 结果静默返回。

用法:
    from baidu_engine import search
    results = search("claude", site="zhihu.com", num=10)

CLI:
    python baidu_engine.py "claude" --site zhihu.com --num 10

错误协议（与仓库其他工具一致）:
    on_error="report"（默认）: 出错返回
        [{"error": "baidu_soft_blocked: ...", "tool": "chat-scraper",
          "query": q, "platform": p}]
    on_error="raise" 抛出; on_error="empty" 兼容旧行为返回 []。
"""
import argparse
import json
import os
import sys
import threading
import time
import urllib.parse
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

__all__ = ["search", "BaiduSoftBlocked"]

_TOOL = "chat-scraper"
_HOME_URL = "https://www.baidu.com/"
_SEARCH_URL = "https://www.baidu.com/s"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
_MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
              "AppleWebKit/605.1.15 (KHTML, like Gecko) "
              "Version/17.5 Mobile/15E148 Safari/604.1")
# 完整 Chrome 文档导航 Accept。requests 默认 `Accept: */*` 配 Chrome UA 是
# 机器人指纹——同 IP 对照实测：三件套被封、补上此头 2/2 过审（缺一不可）。
_ACCEPT_FULL = ("text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,image/apng,*/*;q=0.8,"
                "application/signed-exchange;v=b3;q=0.7")

# 环境变量：两次百度请求的最小间隔秒数。生产建议 >=15（README 有说明）。
ENV_MIN_INTERVAL = "CHAT_SCRAPER_BAIDU_MIN_INTERVAL"
ENV_PROXY = "CHAT_SCRAPER_BAIDU_PROXY"    # 默认空=直连；显式设置才走代理
DEFAULT_MIN_INTERVAL = 20.0
TIMEOUT = 20                      # 单请求超时（秒）
RESULTS_PER_PAGE = 20             # rn 参数；未登录状态下 20 是稳定单页上限
MAX_SOFTBLOCK_RETRIES = 2         # 占位页最大重试次数（总尝试 = 1 + 2）
BACKOFF_MULTIPLIER = 2.0          # 第 n 次重试前等待 interval * MULTIPLIER ** n
PLACEHOLDER_MAX_LEN = 5000        # 占位页判定: len(html) < 此值且含 "timeout"
# 摘要节点选择器，按命中顺序取第一个。2026-09 真实结果页实测: 摘要在
# span[class*="summary-text"]（cos 新 UI，class 带随机后缀只能子串匹配）;
# 后两个是旧版 UI 的兜底。title/mu 才是主键，摘要缺失不影响可用性。
_SNIPPET_SELECTORS = ('[class*="summary-text"]', '.c-abstract', '[class*="content-right"]')
# since -> 百度 gpc=stf 的 stftype（1=一天 2=一周 3=一月）及滚动窗口秒数。
# 百度时间过滤本身是近似 best-effort，其余 since 取值不生效（stderr 告警）。
_SINCE_TO_STFTYPE = {"24h": 1, "7d": 2, "30d": 3}
_SINCE_WINDOW_SECONDS = {"24h": 86400, "7d": 604800, "30d": 2592000}


class BaiduSoftBlocked(Exception):
    """百度软风控占位/验证页（HTTP 200 但内容非结果页）。

    slug 属性供统一错误协议使用: error 字段形如 "baidu_soft_blocked: ..."。
    """

    slug = "baidu_soft_blocked"


_session: Optional[requests.Session] = None
_mobile_session: Optional[requests.Session] = None
_session_lock = threading.Lock()
_throttle_lock = threading.Lock()
_last_request_ts = 0.0


def _min_interval() -> float:
    """读取环境变量配置的最小请求间隔（秒），非法值回退默认。"""
    raw = os.environ.get(ENV_MIN_INTERVAL, "")
    try:
        val = float(raw) if raw else DEFAULT_MIN_INTERVAL
    except ValueError:
        return DEFAULT_MIN_INTERVAL
    return val if val >= 0 else DEFAULT_MIN_INTERVAL


def _wait_turn() -> None:
    """所有对外请求前调用: 保证与上一次百度请求间隔 >= min_interval。

    阈值时间戳用 time.monotonic，不受系统改钟影响。
    """
    global _last_request_ts
    with _throttle_lock:
        wait = _last_request_ts + _min_interval() - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request_ts = time.monotonic()


def _get_session(mobile: bool = False) -> requests.Session:
    """懒加载进程级会话（桌面/移动各一个，UA 与 Referer 分开）。

    头指纹是软风控的直接开关（2026-09-09 同 IP 对照实测）：Chrome UA 配
    requests 默认 `Accept: */*` 是典型机器人指纹——三件套（UA+Referer+
    Accept-Language）组合被封，补上完整 Chrome Accept 四件套后 2/2 直连
    过审。所以 Accept 四件套一个都不能省。
    """
    global _session, _mobile_session
    with _session_lock:
        if (mobile and _mobile_session is not None) or \
                (not mobile and _session is not None):
            return _mobile_session if mobile else _session
        _wait_turn()
        s = requests.Session()
        # trust_env=False: 本工具面向中国平台直连场景。本机实测系统代理
        # （如 Clash 127.0.0.1:7897）半死不活时会返回 ProxyError 或
        # 1488 字节的 "timeout" 页——与百度占位页特征相同，会污染判定。
        # 需要代理时用 CHAT_SCRAPER_BAIDU_PROXY 显式指定（且仅当代理真的
        # 为 baidu.com 换出口时有效——Clash 规则分流国内域名仍走直连）。
        s.trust_env = False
        proxy = os.environ.get(ENV_PROXY, "")
        if proxy:
            s.proxies.update({"http": proxy, "https": proxy})
        if mobile:
            s.headers.update({
                "User-Agent": _MOBILE_UA,
                "Referer": "https://m.baidu.com/",
                "Accept": _ACCEPT_FULL,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            })
        else:
            s.headers.update({
                "User-Agent": _UA,
                "Referer": "https://www.baidu.com/",
                "Accept": _ACCEPT_FULL,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            })
            s.get(_HOME_URL, timeout=TIMEOUT)
        if mobile:
            _mobile_session = s
        else:
            _session = s
        return s


def _looks_soft_blocked(html: str) -> Optional[str]:
    """检测软风控页。返回原因描述（非 None 即被风控），None 表示正常结果页。"""
    if len(html) < PLACEHOLDER_MAX_LEN and "timeout" in html:
        return f"placeholder page (len={len(html)}, contains 'timeout')"
    if ("安全验证" in html) or ("wappass" in html):
        return "captcha-like page (安全验证/wappass marker)"
    return None


def _parse_results(html: str) -> List[Dict[str, str]]:
    """解析结果页 HTML -> [{title, url, snippet}]

    mu 属性即真实直链（见模块 docstring），以此为主键并按 url 去重。
    """
    soup = BeautifulSoup(html, "lxml")
    out: List[Dict[str, str]] = []
    seen = set()
    for node in soup.select("div.result, div.result-op"):
        h3 = node.select_one("h3")
        mu = (node.get("mu") or "").strip()
        if h3 is None or not mu or mu in seen:
            continue
        seen.add(mu)
        snippet = ""
        for sel in _SNIPPET_SELECTORS:
            abstract = node.select_one(sel)
            if abstract is not None:
                snippet = abstract.get_text(" ", strip=True)
                break
        out.append({
            "title": h3.get_text(" ", strip=True),
            "url": mu,
            "snippet": snippet,
        })
    return out


def _since_to_gpc(since: Optional[str]) -> str:
    """since -> 百度 gpc=stf 时间过滤参数（滚动窗口）。不支持/为空返回 ""。"""
    if not since:
        return ""
    stftype = _SINCE_TO_STFTYPE.get(since)
    if stftype is None:
        print(f"[baidu_engine] warning: unsupported since={since!r} "
              f"(only 24h/7d/30d); no time filter applied", file=sys.stderr)
        return ""
    now = int(time.time())
    window = _SINCE_WINDOW_SECONDS[since]
    # gpc 形如 "stf=<begin>,<end>|stftype=<n>"，requests 会自动 urlencode
    return f"stf={now - window},{now}|stftype={stftype}"


def _record(row: Dict[str, str], platform: str, since: Optional[str],
            vendor: str, role: str, engine: str = "baidu") -> Dict:
    """补齐统一结果字段。"""
    return {
        "title": row["title"],
        "url": row["url"],
        "snippet": row["snippet"],
        "platform": platform,
        "engine": engine,
        "vendor": vendor,
        "role": role,
        "since": since or "all",
    }


def search(
    q: str,
    num: int = 10,
    since: Optional[str] = None,
    vendor: str = "?",
    role: str = "primary",
    site: Optional[str] = None,
    platform: Optional[str] = None,
    on_error: str = "report",
) -> List[Dict]:
    """百度搜索（可带 site: 站内过滤）。

    Args:
        q: 搜索关键词
        num: 返回条数上限（单页最多 RESULTS_PER_PAGE 条，超出只返回单页内容）
        since: 时间窗 24h/7d/30d -> gpc=stf（best-effort，见常量注释）;
            None/"" 不过滤
        vendor: 主题分类（指标用，透传）
        role: primary / fallback / verify（透传）
        site: 站点域名如 "zhihu.com"; None 表示无 site: 通用搜索
        platform: 结果 platform 字段的展示名; 默认 site 或 "general"
        on_error: "report" / "raise" / "empty"（见模块 docstring）

    Returns:
        [{title, url, snippet, platform, engine, vendor, role, since}, ...]
    """
    name = platform or site or "general"
    try:
        rows, engine = _search_impl(q, num, since, site, name)
        return [_record(r, name, since, vendor, role, engine) for r in rows]
    except Exception as e:
        if on_error == "raise":
            raise
        if on_error == "report":
            slug = getattr(e, "slug", None) or type(e).__name__
            return [{"error": f"{slug}: {e}", "tool": _TOOL,
                     "query": q, "platform": name}]
        return []  # on_error == "empty": 兼容旧行为


def _parse_mobile_results(html: str) -> List[Dict[str, str]]:
    """移动端结果页解析：真 URL 在 div.c-result 的 data-log 属性 JSON 里
    （{"fm":"alop",...,"mu":"https://..."}），页面无 mu DOM 属性。

    百度自家内容卡（mu 指向 *.baidu.com）对站内搜索是噪音，丢弃。
    """
    soup = BeautifulSoup(html, "lxml")
    out: List[Dict[str, str]] = []
    seen = set()
    for node in soup.select("div.c-result"):
        try:
            mu = (json.loads(node.get("data-log") or "{}").get("mu") or "").strip()
        except ValueError:
            continue
        if not mu or mu in seen:
            continue
        netloc = urllib.parse.urlparse(mu).netloc
        if netloc.endswith("baidu.com"):
            continue
        seen.add(mu)
        title_el = node.select_one("h3") or node
        title = title_el.get_text(" ", strip=True)[:120]
        snippet_el = node.select_one("[class*='content'], .c-abstract")
        snippet = snippet_el.get_text(" ", strip=True)[:300] if snippet_el else ""
        out.append({"title": title, "url": mu, "snippet": snippet})
    return out


def _mobile_search_impl(q: str, num: int, since: Optional[str],
                        site: Optional[str]) -> List[Dict[str, str]]:
    """移动端备选子路径：m.baidu.com 与桌面端是独立风控桶——实测同一被锁
    IP 上桌面 302 验证码、移动端照常出真实结果页。

    判据与桌面不同：真页 = 页面大且含 c-result；被封 = 小页/跳 wappass。
    移动端页面的内联 JS 本身含 wappass 字样，桌面版的 wappass html 标记
    在这里会全量误报，严禁复用。
    """
    s = _get_session(mobile=True)
    params: Dict[str, object] = {
        "word": f"{q} site:{site}" if site else q,
    }
    gpc = _since_to_gpc(since)
    if gpc:
        params["gpc"] = gpc
    _wait_turn()
    resp = s.get("https://m.baidu.com/s", params=params, timeout=TIMEOUT)
    if "wappass" in resp.url:
        raise BaiduSoftBlocked(
            f"mobile redirected to captcha ({resp.url[:80]!r})")
    if "c-result" not in resp.text:
        raise BaiduSoftBlocked(
            f"mobile page lacks results (len={len(resp.text)}, "
            f"url={resp.url[:80]!r})")
    return _parse_mobile_results(resp.text)[:num]


def _search_impl(q: str, num: int, since: Optional[str],
                 site: Optional[str], name: str) -> Tuple[List[Dict[str, str]], str]:
    """实际请求 + 占位页退避重试；桌面穷尽后切移动端桶。

    返回 (rows, engine)；失败抛 BaiduSoftBlocked（message 含桌面+移动双端
    结局）/ requests 异常。
    """
    s = _get_session()
    params: Dict[str, object] = {
        "wd": f"{q} site:{site}" if site else q,
        "rn": RESULTS_PER_PAGE,
    }
    gpc = _since_to_gpc(since)
    if gpc:
        params["gpc"] = gpc

    reason = ""
    for attempt in range(MAX_SOFTBLOCK_RETRIES + 1):
        _wait_turn()
        resp = s.get(_SEARCH_URL, params=params, timeout=TIMEOUT)
        reason = _looks_soft_blocked(resp.text)
        if reason is None:
            return _parse_results(resp.text)[:num], "baidu"
        if attempt < MAX_SOFTBLOCK_RETRIES:
            # 指数退避: interval * 2, interval * 4
            time.sleep(_min_interval() * (BACKOFF_MULTIPLIER ** (attempt + 1)))
    # 桌面桶穷尽 → 移动端桶（独立风控，实测桌面被锁时仍可用）
    try:
        return _mobile_search_impl(q, num, since, site), "baidu-mobile"
    except BaiduSoftBlocked as me:
        raise BaiduSoftBlocked(
            f"desktop: {reason}; gave up after {MAX_SOFTBLOCK_RETRIES + 1} "
            f"attempts (min_interval={_min_interval():g}s); "
            f"mobile fallback also failed: {me}") from me


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="百度搜索（支持 site: 站内过滤）")
    parser.add_argument("q", help="query")
    parser.add_argument("--site", default=None,
                        help="站点域名，如 zhihu.com；省略为通用搜索")
    parser.add_argument("--num", type=int, default=10)
    parser.add_argument("--since", default=None,
                        help="24h/7d/30d（best-effort），省略不过滤")
    parser.add_argument("--vendor", default="?")
    parser.add_argument("--role", default="primary")
    parser.add_argument("--on-error", default="report",
                        choices=["report", "raise", "empty"])
    args = parser.parse_args()
    results = search(args.q, num=args.num, since=args.since,
                     vendor=args.vendor, role=args.role, site=args.site,
                     on_error=args.on_error)
    errors = [r for r in results if "error" in r]
    if errors:
        for r in errors:
            print(f"[baidu_engine] error ({r.get('platform', '?')}): {r['error']}",
                  file=sys.stderr)
        return 1
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
