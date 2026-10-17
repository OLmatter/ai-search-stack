#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""财经舆情与宏观快讯直连引擎（v3.45.0）—— 东方财富股吧/7x24快讯 + 雪球电报/行情 + 新浪7x24。

实测结论（2026-10-16 本机直连验证）:
    1. eastmoney_guba : 东方财富股吧 https://guba.eastmoney.com/list,{code}.html SSR 内嵌
                        标准 JSON 变量 `var article_list = {...}`，单页免登录直接提取 80 条散户实况帖。
    2. eastmoney_724  : 东方财富 7x24 全球财经快讯 JSON API
                        https://np-weblist.eastmoney.com/comm/web/getFastNewsList
    3. xueqiu_724     : 雪球 7x24 实时电报（先 GET https://xueqiu.com/about 领 xq_a_token 访客 cookie，
                        再调 https://xueqiu.com/statuses/livenews/list.json，免阿里云 WAF）。
    4. xueqiu_quote   : 雪球批量实时股票/指数行情 https://stock.xueqiu.com/v5/stock/batch/quote.json
    5. sina_724       : 新浪财经 7x24 全球实时电报 https://zhibo.sina.com.cn/api/zhibo/feed
"""
import json
import re
from typing import Dict, List, Tuple

import requests

__all__ = ["SUPPORTED_SOURCES", "fetch_wire", "FinanceWireError"]

_TOOL = "finance-wire"
SUPPORTED_SOURCES: Tuple[str, ...] = (
    "eastmoney_guba", "eastmoney_724", "xueqiu_724", "xueqiu_quote", "sina_724",
)
_UA_PC = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)
TIMEOUT = 15


class FinanceWireError(RuntimeError):
    """财经快讯/股吧接口解析或响应错误。"""
    slug = "finance_wire_error"


def _fetch_eastmoney_guba(session: requests.Session, symbol: str, num: int) -> List[Dict]:
    code = (symbol or "zssh000001").strip() or "zssh000001"
    url = f"https://guba.eastmoney.com/list,{code}.html"
    resp = session.get(url, headers={"User-Agent": _UA_PC}, timeout=TIMEOUT)
    resp.raise_for_status()
    m = re.search(r"var\s+article_list\s*=\s*(\{.*?\});", resp.text, re.S)
    if not m:
        raise FinanceWireError(f"guba page missing article_list for {code!r}")
    data = json.loads(m.group(1))
    re_list = data.get("re") or []
    out: List[Dict] = []
    for item in re_list[:max(1, int(num))]:
        if not isinstance(item, dict):
            continue
        pid = item.get("post_id")
        out.append({
            "id": str(pid or ""),
            "title": (item.get("post_title") or "").strip(),
            "author": ((item.get("user_nickname") or "")).strip(),
            "clicks": int(item.get("post_click_count") or 0),
            "comments": int(item.get("post_comment_count") or 0),
            "publish_time": item.get("post_publish_time") or "",
            "url": f"https://guba.eastmoney.com/news,{code},{pid}.html" if pid else url,
            "source": "eastmoney_guba",
        })
    return out


def _fetch_eastmoney_724(session: requests.Session, num: int) -> List[Dict]:
    resp = session.get(
        "https://np-weblist.eastmoney.com/comm/web/getFastNewsList",
        params={
            "client": "web", "biz": "web_724", "fastColumn": "102",
            "sortEnd": "", "pageSize": max(1, min(int(num), 50)), "req_trace": "1",
        },
        headers={"User-Agent": _UA_PC, "Referer": "https://kuaixun.eastmoney.com/"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    rows = ((resp.json().get("data") or {}).get("fastNewsList")) or []
    return [
        {
            "id": str(r.get("code") or ""),
            "title": (r.get("title") or "").strip(),
            "content": (r.get("summary") or r.get("title") or "").strip(),
            "publish_time": r.get("showTime") or "",
            "source": "eastmoney_724",
        }
        for r in rows[:max(1, int(num))] if isinstance(r, dict)
    ]


def _warm_xueqiu(session: requests.Session) -> None:
    session.headers.update({"User-Agent": _UA_PC, "Referer": "https://xueqiu.com/"})
    if not session.cookies.get("xq_a_token"):
        session.get("https://xueqiu.com/about", timeout=TIMEOUT)


def _fetch_xueqiu_724(session: requests.Session, num: int) -> List[Dict]:
    _warm_xueqiu(session)
    resp = session.get(
        "https://xueqiu.com/statuses/livenews/list.json",
        params={"since_id": -1, "max_id": -1, "count": max(1, min(int(num), 30))},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    items = (resp.json().get("items")) or []
    return [
        {
            "id": str(x.get("id") or ""),
            "content": (x.get("text") or "").strip(),
            "created_at": x.get("created_at"),
            "url": x.get("target") or "https://xueqiu.com/",
            "source": "xueqiu_724",
        }
        for x in items[:max(1, int(num))] if isinstance(x, dict)
    ]


def _fetch_xueqiu_quote(session: requests.Session, symbols: str) -> List[Dict]:
    _warm_xueqiu(session)
    sym = (symbols or "SH000001,SZ399001,HKHSI").strip()
    resp = session.get(
        "https://stock.xueqiu.com/v5/stock/batch/quote.json",
        params={"symbol": sym, "extend": "detail"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    items = ((resp.json().get("data") or {}).get("items")) or []
    out: List[Dict] = []
    for it in items:
        q = (it.get("quote") if isinstance(it, dict) else None) or {}
        if not q:
            continue
        out.append({
            "symbol": q.get("symbol"),
            "name": q.get("name"),
            "current": q.get("current"),
            "percent": q.get("percent"),
            "chg": q.get("chg"),
            "market_capital": q.get("market_capital"),
            "amount": q.get("amount"),
            "source": "xueqiu_quote",
        })
    return out


def _fetch_sina_724(session: requests.Session, num: int) -> List[Dict]:
    resp = session.get(
        "https://zhibo.sina.com.cn/api/zhibo/feed",
        params={"page": 1, "page_size": max(1, min(int(num), 30)), "zhibo_id": 152},
        headers={"User-Agent": _UA_PC, "Referer": "https://finance.sina.com.cn/7x24/"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    feed = (((resp.json().get("result") or {}).get("data") or {}).get("feed") or {}).get("list") or []
    return [
        {
            "id": str(x.get("id") or ""),
            "content": (x.get("rich_text") or "").strip(),
            "publish_time": x.get("create_time") or "",
            "url": x.get("docurl") or "https://finance.sina.com.cn/7x24/",
            "source": "sina_724",
        }
        for x in feed[:max(1, int(num))] if isinstance(x, dict)
    ]


def fetch_wire(
    source: str = "eastmoney_724",
    query: str = "",
    num: int = 10,
    on_error: str = "report",
) -> List[Dict]:
    """统一财经/宏观电报与股吧散户舆情读取入口。"""
    src = (source or "").strip().lower()
    if src not in SUPPORTED_SOURCES:
        err = ValueError(
            f"unknown finance source {source!r}; supported: {list(SUPPORTED_SOURCES)}"
        )
        if on_error == "raise":
            raise err
        if on_error == "report":
            return [{"error": f"ValueError: {err}", "tool": _TOOL,
                     "query": query, "source": src}]
        return []
    try:
        s = requests.Session()
        s.trust_env = False
        if src == "eastmoney_guba":
            return _fetch_eastmoney_guba(s, query, num)
        if src == "eastmoney_724":
            return _fetch_eastmoney_724(s, num)
        if src == "xueqiu_724":
            return _fetch_xueqiu_724(s, num)
        if src == "xueqiu_quote":
            return _fetch_xueqiu_quote(s, query)
        return _fetch_sina_724(s, num)
    except Exception as e:
        if on_error == "raise":
            raise
        if on_error == "report":
            slug = getattr(e, "slug", None) or type(e).__name__
            return [{"error": f"{slug}: {e}", "tool": _TOOL,
                     "query": query, "source": src}]
        return []
