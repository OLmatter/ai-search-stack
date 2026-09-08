#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""知乎官方 API 内容读取 —— cookie 文件 + zhihu_sign 签名，读问题/回答。

分工边界（2026-09-09 实测定稿）：
    - **搜索**仍走 zhihu_engine 降级链（SearXNG→搜狗→百度）：官方 search_v3
      即便带有效 cookie 也强制登录（401 ZERR_NOT_LOGIN），上登录账号是
      主人的产品决策，本工具不碰凭据。
    - **内容**（问题详情/回答列表）用本模块：无头 camoufox 领的访客 cookie
      （zhihu_bootstrap.py 产出）+ zhihu_sign 签名即可 200 读取。
    - cookie 过期（401/403/40353）→ 报 zhihu_auth_expired 并提示重跑引导。

用法:
    python zhihu_bootstrap.py                 # 先引导（一次，十几秒）
    python zhihu_content.py question 19550227
    python zhihu_content.py answers 19550227

库调用:
    from zhihu_content import fetch_question, fetch_answers
    q = fetch_question("19550227")

cookie 文件: 环境变量 CHAT_SCRAPER_ZHIHU_COOKIES > state/zhihu_cookies.json
"""
import argparse
import json
import os
import sys
import urllib.parse
from typing import Dict, List, Optional

import requests

import zhihu_sign

__all__ = ["fetch_question", "fetch_answers", "ZhihuAuthExpired"]

_TOOL = "chat-scraper"
_TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_COOKIES = "CHAT_SCRAPER_ZHIHU_COOKIES"
DEFAULT_COOKIE_PATH = os.path.join(_TOOL_DIR, "state", "zhihu_cookies.json")
_API = "https://www.zhihu.com/api/v4"
TIMEOUT = 20

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")
_AUTH_CODES = {401, 403}


class ZhihuAuthExpired(RuntimeError):
    """cookie 缺失/过期（401/403/40353）。重跑 zhihu_bootstrap.py 即可。"""

    slug = "zhihu_auth_expired"


def _cookie_path() -> str:
    return os.environ.get(ENV_COOKIES, DEFAULT_COOKIE_PATH)


def _load_d_c0() -> str:
    path = _cookie_path()
    if not os.path.exists(path):
        raise ZhihuAuthExpired(
            f"cookie 文件不存在: {path}。先跑 python zhihu_bootstrap.py")
    with open(path, encoding="utf-8") as f:
        cookies = json.load(f).get("cookies", {})
    d_c0 = cookies.get("d_c0", "")
    if not d_c0:
        raise ZhihuAuthExpired(
            f"cookie 文件里没有 d_c0: {path}。重跑 python zhihu_bootstrap.py")
    return d_c0


def _cookie_header() -> str:
    path = _cookie_path()
    with open(path, encoding="utf-8") as f:
        cookies = json.load(f).get("cookies", {})
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def _api_get(path_query: str) -> dict:
    """签名 GET 官方 API。path_query 形如 /api/v4/questions/19550227。"""
    url = _API.replace("/api/v4", "") + path_query   # zhihu_sign 只需域名前缀完整
    headers = zhihu_sign.sign_headers(url, _load_d_c0())
    headers.update({
        "User-Agent": _UA,
        "Referer": "https://www.zhihu.com/",
        "Cookie": _cookie_header(),
    })
    resp = requests.get(url, headers=headers, timeout=TIMEOUT)
    if resp.status_code in _AUTH_CODES:
        detail = resp.text[:160]
        raise ZhihuAuthExpired(
            f"HTTP {resp.status_code}（cookie 缺失或过期）: {detail}。"
            f"重跑 python zhihu_bootstrap.py")
    resp.raise_for_status()
    return resp.json()


def _strip_html(s: str) -> str:
    import re
    import html as _html
    return _html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()


def fetch_question(question_id: str) -> Dict:
    """问题详情：{id, title, detail(纯文本), answer_count, url}。

    include 必带 answer_count，否则恒为 0（API 默认裁剪字段）。
    """
    data = _api_get(f"/api/v4/questions/{question_id}?include=detail,answer_count")
    return {
        "id": str(data.get("id", question_id)),
        "title": data.get("title", ""),
        "detail": _strip_html(data.get("detail", ""))[:2000],
        "answer_count": data.get("answer_count", 0),
        "url": f"https://www.zhihu.com/question/{question_id}",
        "engine": "zhihu-api",
    }


def fetch_answers(question_id: str, num: int = 10,
                  sort_by: str = "default") -> List[Dict]:
    """回答列表：[{author, excerpt, voteup, url}]。

    端点用 web 播放器同款 /feeds（实测 2026-09-09）：/answers 子端点会被
    行为风控 40362 临时限制，/feeds 正常。include 分号分隔是官方格式。
    """
    params = urllib.parse.urlencode({
        "include": "data[*].content;data[*].author",
        "offset": 0,
        "limit": min(num, 20),
        "sort_by": sort_by,
    })
    data = _api_get(f"/api/v4/questions/{question_id}/feeds?{params}")
    out: List[Dict] = []
    for ans in data.get("data", [])[:num]:
        target = ans.get("target") or ans
        aid = target.get("id", "")
        out.append({
            "author": (target.get("author") or {}).get("name", ""),
            "excerpt": (target.get("excerpt") or
                        _strip_html(target.get("content", "")))[:500],
            "voteup": target.get("voteup_count", 0),
            "url": f"https://www.zhihu.com/question/{question_id}/answer/{aid}",
            "engine": "zhihu-api",
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="知乎官方 API 内容读取（需先 zhihu_bootstrap.py 领 cookie）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pq = sub.add_parser("question", help="问题详情")
    pq.add_argument("id")
    pa = sub.add_parser("answers", help="回答列表")
    pa.add_argument("id")
    pa.add_argument("--num", type=int, default=10)
    args = parser.parse_args()

    try:
        if args.cmd == "question":
            out = fetch_question(args.id)
        else:
            out = fetch_answers(args.id, num=args.num)
    except Exception as e:
        slug = getattr(e, "slug", None) or type(e).__name__
        print(f"[zhihu_content] error {slug}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
