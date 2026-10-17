#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""微博移动端 H5 直连搜索引擎（v3.45.0）—— 免登录 .weibo.cn 访客流 + 实时/综合搜索。

实测结论（2026-10-16 突破 m.weibo.cn ok=-100 拦截）:
    - hotlist_engine.py 的 passport.weibo.com 访客流签发的是 .weibo.com 域 cookie，
      而 m.weibo.cn/api/container/getIndex 强制要求 .weibo.cn 域的 SUB/SUBP cookie。
    - 单次 POST https://visitor.passport.weibo.cn/visitor/genvisitor2
      (Form: cb=visitor_gray_callback&tid=&from=weibo, <0.3s) 即可从响应 Set-Cookie
      直接拿到 .weibo.cn 域的 SUB/SUBP（缓存至 state/mweibo_visitor_cookies.json 复用）。
    - 携带该 cookie 后，m.weibo.cn/api/container/getIndex 全系接口稳定返回 ok=1：
      1) type=61（实时流）：按发布时间秒级倒序返回最新微博；
      2) type=1（综合/热门流）：返回高赞/高转发讨论；
      3) 彻底摆脱原 baidu site:weibo.com 的 20s 节流与收录延迟。
"""
import html
import json
import os
import re
import threading
import time
import urllib.parse
from typing import Dict, List, Optional

import requests

__all__ = ["search", "WeiboSearchError"]

_TOOL = "chat-scraper"
_PLATFORM = "weibo"
_GENVISITOR2_URL = "https://visitor.passport.weibo.cn/visitor/genvisitor2"
_SEARCH_URL = "https://m.weibo.cn/api/container/getIndex"
_UA_H5 = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
_STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
_COOKIE_CACHE_PATH = os.path.join(_STATE_DIR, "mweibo_visitor_cookies.json")
TIMEOUT = 15
TEXT_LIMIT = 1000
_lock = threading.Lock()


class WeiboSearchError(RuntimeError):
    """微博移动端搜索失败或访客凭证获取失败。"""
    slug = "weibo_search_error"


def _strip_html(raw: str) -> str:
    if not raw:
        return ""
    txt = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    txt = re.sub(r"<[^>]+>", "", txt)
    return html.unescape(txt).strip()


def _mint_mweibo_cookies(session: requests.Session) -> Dict[str, str]:
    """单次 POST genvisitor2 签发 .weibo.cn 域访客 SUB/SUBP cookie。"""
    headers = {
        "User-Agent": _UA_H5,
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://visitor.passport.weibo.cn",
        "Referer": (
            "https://visitor.passport.weibo.cn/visitor/visitor"
            "?a=enter&url=https%3A%2F%2Fm.weibo.cn%2F"
        ),
    }
    resp = session.post(
        _GENVISITOR2_URL,
        data="cb=visitor_gray_callback&tid=&from=weibo",
        headers=headers,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    cookies = {c.name: c.value for c in session.cookies if c.value}
    if not cookies.get("SUB"):
        m_sub = re.search(r'"sub"\s*:\s*"([^"]+)"', resp.text)
        m_subp = re.search(r'"subp"\s*:\s*"([^"]+)"', resp.text)
        if m_sub and m_sub.group(1):
            cookies["SUB"] = m_sub.group(1)
            if m_subp and m_subp.group(1):
                cookies["SUBP"] = m_subp.group(1)
    if not cookies.get("SUB"):
        raise WeiboSearchError("genvisitor2 未下发 SUB 访客 cookie")
    try:
        os.makedirs(_STATE_DIR, exist_ok=True)
        with open(_COOKIE_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"saved_at": time.time(), "cookies": cookies}, f)
    except Exception:
        pass
    return cookies


def _load_or_mint_cookies(session: requests.Session, force_refresh: bool = False) -> Dict[str, str]:
    if not force_refresh and os.path.exists(_COOKIE_CACHE_PATH):
        try:
            with open(_COOKIE_CACHE_PATH, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if time.time() - float(cached.get("saved_at", 0)) < 86400:
                ck = cached.get("cookies") or {}
                if ck.get("SUB"):
                    return ck
        except Exception:
            pass
    return _mint_mweibo_cookies(session)


def _extract_mblogs(cards: List[Dict]) -> List[Dict]:
    """递归提取 cards 及 card_group 内的 mblog 对象。"""
    mblogs: List[Dict] = []
    for c in cards or []:
        if not isinstance(c, dict):
            continue
        if isinstance(c.get("mblog"), dict):
            mblogs.append(c["mblog"])
        for sub in (c.get("card_group") or []):
            if isinstance(sub, dict) and isinstance(sub.get("mblog"), dict):
                mblogs.append(sub["mblog"])
    return mblogs


def search(
    q: str,
    mode: str = "realtime",
    num: int = 10,
    page: int = 1,
    since: Optional[str] = "7d",
    vendor: str = "?",
    role: str = "primary",
    on_error: str = "report",
) -> List[Dict]:
    """微博移动端免登录直搜（mode: 'realtime'=type 61 实时流 | 'hot'=type 1 综合热门）。"""
    query = (q or "").strip()
    if not query:
        err = ValueError("empty weibo query")
        if on_error == "raise":
            raise err
        if on_error == "report":
            return [{"error": f"ValueError: {err}", "tool": _TOOL,
                     "query": q, "platform": _PLATFORM}]
        return []

    search_type = "1" if mode == "hot" else "61"
    containerid = f"100103type={search_type}&q={query}"
    params = {
        "containerid": containerid,
        "page_type": "searchall",
        "page": max(1, int(page)),
    }

    try:
        s = requests.Session()
        s.trust_env = False
        ck = _load_or_mint_cookies(s, force_refresh=False)
        headers = {
            "User-Agent": _UA_H5,
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "MWeibo-Pwa": "1",
            "Referer": "https://m.weibo.cn/search?containerid=" + urllib.parse.quote(containerid),
        }
        resp = s.get(_SEARCH_URL, params=params, headers=headers, cookies=ck, timeout=TIMEOUT)
        resp.raise_for_status()
        body = resp.json()
        if body.get("ok") != 1:
            # 访客 cookie 过期则强制重签一次
            ck = _load_or_mint_cookies(s, force_refresh=True)
            resp = s.get(_SEARCH_URL, params=params, headers=headers, cookies=ck, timeout=TIMEOUT)
            resp.raise_for_status()
            body = resp.json()
        if body.get("ok") != 1:
            raise WeiboSearchError(f"m.weibo.cn getIndex ok={body.get('ok')} msg={body.get('msg')}")

        cards = (body.get("data") or {}).get("cards") or []
        mblogs = _extract_mblogs(cards)
        out: List[Dict] = []
        seen_ids = set()
        for mb in mblogs:
            mid = str(mb.get("id") or mb.get("mid") or "")
            if not mid or mid in seen_ids:
                continue
            seen_ids.add(mid)
            text_clean = _strip_html(mb.get("text") or "")
            truncated = len(text_clean) > TEXT_LIMIT
            if truncated:
                text_clean = text_clean[:TEXT_LIMIT]
            user = mb.get("user") or {}
            author = user.get("screen_name") or ""
            first_line = text_clean.split("\n", 1)[0][:80]
            out.append({
                "id": mid,
                "title": f"@{author}: {first_line}" if author else first_line,
                "content": text_clean,
                "truncated": truncated,
                "author": author,
                "created_at": mb.get("created_at") or "",
                "attitudes_count": int(mb.get("attitudes_count") or 0),
                "comments_count": int(mb.get("comments_count") or 0),
                "reposts_count": int(mb.get("reposts_count") or 0),
                "url": f"https://m.weibo.cn/detail/{mid}",
                "platform": _PLATFORM,
                "engine": "mweibo-api",
                "vendor": vendor,
                "role": role,
                "since": since or "all",
            })
            if len(out) >= int(num):
                break
        return out
    except Exception as e:
        if on_error == "raise":
            raise
        if on_error == "report":
            slug = getattr(e, "slug", None) or type(e).__name__
            return [{"error": f"{slug}: {e}", "tool": _TOOL,
                     "query": q, "platform": _PLATFORM}]
        return []
