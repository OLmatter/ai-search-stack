#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""掘金（juejin.cn）官方搜索 API 引擎（文章分类，结构化字段）

实测结论（2026-09-16 本机验证，v3.28 重写的依据，2 发探测预算）:
    - 裸调即通: GET https://api.juejin.cn/search_api/v1/search?query=...&
      id_type=0&cursor=0&limit=20&search_type=0 不需要任何 cookie/签名
      （对照 bilibili 必须先领 buvid3——掘金首页预热同样不需要，两发探测
      均为纯裸调直连成功）。
    - 信封: {"err_no": 0, "err_msg": "success", "data": [...], "count": N,
      "cursor": "<不透明游标串>", "has_more": true}。data 是**直接列表**
      （不是 {result: []} 包装）。
    - 条目: {"result_type": 2, "result_model": {"article_id", "article_info":
      {title, brief_content, ctime(unix 秒字符串), view_count, digg_count,
      comment_count, ...}, "author_user_info": {user_name, ...},
      "category": {category_name, ...}}}。综合搜索（search_type=0）两发
      探测均全量返回 result_type=2（文章），仍按类型显式过滤防形态变化。
    - 分页: 下一页 cursor = 响应顶层 cursor 字段（不透明串，如
      "20_20260917021600EA..."），has_more=False 或 cursor 缺失即到底。
    - 标题实测无 <mark> 高亮标记，仍按引擎惯例剥标签+还原实体（防御性，
      与 bilibili 同款 _clean_title）。

用法:
    from juejin_engine import search
    results = search("python 教程", num=10)

CLI:
    python juejin_engine.py "python 教程" --num 10

错误协议（与仓库其他工具一致）:
    on_error="report"（默认）: 出错返回
        [{"error": "juejin_api_error: err_no=...", "tool": "chat-scraper",
          "query": q, "platform": "juejin"}]
    on_error="raise" 抛出; on_error="empty" 兼容旧行为返回 []。
"""
import argparse
import datetime
import html
import json
import os
import re
import sys
import threading
import time
from typing import Dict, List, Optional

import requests

__all__ = ["search", "JuejinApiError"]

_TOOL = "chat-scraper"
_PLATFORM = "juejin"
_API_SEARCH = "https://api.juejin.cn/search_api/v1/search"
_HOME_URL = "https://juejin.cn/"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")

# 环境变量：两次掘金请求的最小间隔秒数
ENV_MIN_INTERVAL = "CHAT_SCRAPER_JUEJIN_MIN_INTERVAL"
DEFAULT_MIN_INTERVAL = 2.0
TIMEOUT = 20                      # 单请求超时（秒）
PAGE_LIMIT = 20                   # 实测服务端单页条数（limit=20 探测全额返回）
MAX_PAGES = 5                     # 搜索翻页护栏：num 有效上限约 100 条
RESULT_TYPE_ARTICLE = 2           # 实测文章条目的 result_type
# since -> 客户端按 ctime 过滤的滚动窗口秒数（API 本身不支持时间过滤）
_SINCE_WINDOWS = {"24h": 86400, "7d": 604800, "30d": 2592000, "90d": 7776000}


class JuejinApiError(Exception):
    """掘金 API 返回非 0 err_no 或非 JSON 响应。"""

    slug = "juejin_api_error"


_session: Optional[requests.Session] = None
_session_lock = threading.RLock()
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
    """所有对外请求前调用: 保证与上一次掘金请求间隔 >= min_interval。"""
    global _last_request_ts
    with _throttle_lock:
        wait = _last_request_ts + _min_interval() - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request_ts = time.monotonic()


def _get_session() -> requests.Session:
    """懒加载进程级会话。

    实测裸调即通（无需预热 cookie），会话仅复用连接池 + 统一请求头。
    trust_env=False: 同 baidu/bilibili 引擎——系统代理半死不活会伪造
    ProxyError/timeout，掘金在中国网络下直连即通。
    """
    global _session
    with _session_lock:
        if _session is None:
            s = requests.Session()
            s.trust_env = False
            s.headers.update({
                "User-Agent": _UA,
                "Referer": _HOME_URL,
                "Origin": "https://juejin.cn",
            })
            _session = s
        return _session


def _call_search(s: requests.Session, params: Dict[str, object]) -> Dict:
    """调搜索接口（节流），非 JSON 响应抛 JuejinApiError。"""
    _wait_turn()
    resp = s.get(_API_SEARCH, params=params, timeout=TIMEOUT)
    try:
        return resp.json()
    except ValueError:
        raise JuejinApiError(
            f"non-JSON response HTTP {resp.status_code}: {resp.text[:120]!r}")


def _check_payload(payload: Dict) -> None:
    """err_no != 0 视为 API 故障（风控/参数拒收），按统一错误协议上报。"""
    if payload.get("err_no") != 0:
        raise JuejinApiError(
            f"err_no={payload.get('err_no')} err_msg={payload.get('err_msg')}")


def _clean_title(s: str) -> str:
    """剥掉标题里可能的 HTML 标记（如高亮 <mark>），并还原 HTML 实体。

    实测当前标题无标记，此为防御性清洗（与 bilibili 同款）。
    """
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def _fmt_pubdate(ts: int) -> str:
    if not ts:      # 0 = 缺失，伪造 "1970-01-01" 是撒谎
        return ""
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def search(
    q: str,
    num: int = 10,
    since: Optional[str] = None,
    vendor: str = "?",
    role: str = "primary",
    on_error: str = "report",
) -> List[Dict]:
    """掘金文章搜索（官方 API，结构化字段）。

    Args:
        q: 搜索关键词
        num: 返回条数上限。单页 20 条；num>20 自动翻页（护栏 MAX_PAGES=5
            页，即有效上限约 100 条）——护栏耗尽或 has_more=False 时安静
            返回已收集条数（护栏是防失控，不是异常信号；页间节流走引擎
            内置 _wait_turn）
        since: 时间窗 24h/7d/30d/90d -> 客户端按 ctime 过滤（API 不支持
            服务端时间过滤，过滤后可能少于 num）; None/"" 不过滤
        vendor: 主题分类（指标用，透传）
        role: primary / fallback / verify（透传）
        on_error: "report" / "raise" / "empty"（见模块 docstring）

    Returns:
        [{title, url, snippet, platform, engine, author, views, diggs,
          comments, category, pubdate, vendor, role, since}, ...]
    """
    try:
        return _search_impl(q, num, since, vendor, role)
    except Exception as e:
        if on_error == "raise":
            raise
        if on_error == "report":
            slug = getattr(e, "slug", None) or type(e).__name__
            return [{"error": f"{slug}: {e}", "tool": _TOOL,
                     "query": q, "platform": _PLATFORM}]
        return []  # on_error == "empty": 兼容旧行为


def _search_impl(q: str, num: int, since: Optional[str], vendor: str,
                 role: str) -> List[Dict]:
    s = _get_session()

    cutoff = 0.0
    if since:
        window = _SINCE_WINDOWS.get(since)
        if window is None:
            print(f"[juejin_engine] warning: unsupported since={since!r} "
                  f"(only 24h/7d/30d/90d); no time filter applied",
                  file=sys.stderr)
        else:
            cutoff = time.time() - window

    out: List[Dict] = []
    seen_ids: set = set()
    if num <= 0:
        return out
    fetched_pages = 0
    cursor = "0"
    while fetched_pages < MAX_PAGES and len(out) < num:
        payload = _call_search(s, {
            "query": q,
            "id_type": "0",       # 0 = 文章（实测缺省也返回文章，显式带上）
            "cursor": cursor,
            "limit": str(PAGE_LIMIT),
            "search_type": "0",   # 0 = 综合搜索（实测全量返回文章条目）
        })
        _check_payload(payload)

        items = payload.get("data") or []
        page_new = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            model = item.get("result_model")
            # 只收实测的文章 dict 形态；其余类型/形态（用户/合集/标签、
            # 旧版 {"result_model": "article", "item": {...}} 字符串形态）
            # 一律丢弃——宁缺勿错，形态变化时以 0 结果如实暴露而非混入脏数据
            if not isinstance(model, dict):
                continue
            if item.get("result_type") != RESULT_TYPE_ARTICLE:
                continue
            article_id = str(model.get("article_id") or "").strip()
            if not article_id:
                continue  # 无 article_id 的异常条目（广告卡同位素），丢弃
            if article_id in seen_ids:
                continue  # 跨页去重（bilibili v3.12 审查 A1 同款）
            seen_ids.add(article_id)
            info = model.get("article_info") or {}
            ctime = int(info.get("ctime") or 0)   # 实测为 unix 秒字符串
            if cutoff and ctime < cutoff:
                continue
            out.append({
                "title": _clean_title(str(info.get("title") or "")),
                "url": f"https://juejin.cn/post/{article_id}",
                "snippet": (info.get("brief_content") or "").strip(),
                "platform": _PLATFORM,
                "engine": "juejin",
                "author": ((model.get("author_user_info") or {})
                           .get("user_name") or ""),
                "views": info.get("view_count"),
                "diggs": info.get("digg_count"),
                "comments": info.get("comment_count"),
                "category": ((model.get("category") or {})
                             .get("category_name") or ""),
                "pubdate": _fmt_pubdate(ctime),
                "vendor": vendor,
                "role": role,
                "since": since or "all",
            })
            page_new += 1
            if len(out) >= num:
                break
        fetched_pages += 1
        if not items:
            break   # 服务端空页 = 真空到底，如实停，不发多余请求
        if payload.get("has_more") and payload.get("cursor"):
            cursor = str(payload["cursor"])
        else:
            break   # has_more=False 或游标缺失 = 排序穷尽信号，如实停
    return out


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="掘金官方 API 文章搜索")
    parser.add_argument("q", help="query")
    parser.add_argument("--num", type=int, default=10)
    parser.add_argument("--since", default=None,
                        help="24h/7d/30d/90d（客户端过滤），省略不过滤")
    parser.add_argument("--vendor", default="?")
    parser.add_argument("--role", default="primary")
    parser.add_argument("--on-error", default="report",
                        choices=["report", "raise", "empty"])
    args = parser.parse_args()
    results = search(args.q, num=args.num, since=args.since,
                     vendor=args.vendor, role=args.role,
                     on_error=args.on_error)
    errors = [r for r in results if "error" in r]
    if errors:
        for r in errors:
            print(f"[juejin_engine] error: {r['error']}", file=sys.stderr)
        return 1
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
