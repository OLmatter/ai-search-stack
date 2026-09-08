#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""知乎官方 API 内容读取 —— cookie 文件 + zhihu_sign 签名，读问题/回答。

分工边界（2026-09-09 实测定稿）：
    - **搜索**仍走 zhihu_engine 降级链（SearXNG→搜狗→百度）：官方 search_v3
      即便带有效 cookie 也强制登录（401 ZERR_NOT_LOGIN），上登录账号是
      主人的产品决策，本工具不碰凭据。
    - **内容**（问题详情/回答列表）用本模块：无头 camoufox 领的访客 cookie
      （zhihu_bootstrap.py 产出）+ zhihu_sign 签名即可 200 读取。
    - 错误语义（绝不伪装真空）：
        zhihu_auth_expired    cookie 缺失/过期（401、40353、ZERR_NOT_LOGIN）
        zhihu_behavior_limited 行为风控临时限制（40362——cookie 是好的，
                              重跑引导无用，降频/稍后再试）
        zhihu_api_error       其他 API 错（含 200 包 error body 的形态）

用法:
    python zhihu_bootstrap.py                 # 先引导（一次，十几秒）
    python zhihu_content.py question 19550227
    python zhihu_content.py answers 19550227

cookie 文件: 环境变量 CHAT_SCRAPER_ZHIHU_COOKIES > state/zhihu_cookies.json
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
from typing import Dict, List, Optional

import requests

import zhihu_sign

__all__ = ["fetch_question", "fetch_answers",
           "ZhihuAuthExpired", "ZhihuBehaviorLimited"]

_TOOL = "chat-scraper"
_TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_COOKIES = "CHAT_SCRAPER_ZHIHU_COOKIES"
DEFAULT_COOKIE_PATH = os.path.join(_TOOL_DIR, "state", "zhihu_cookies.json")
_API_BASE = "https://www.zhihu.com"
TIMEOUT = 20

_AUTH_CODES = {401, 403}
_BEHAVIOR_CODE = 40362        # "您当前请求存在异常，暂时限制本次访问"


class ZhihuAuthExpired(RuntimeError):
    """cookie 缺失/过期（401/40353/ZERR_NOT_LOGIN）。重跑 zhihu_bootstrap.py。"""

    slug = "zhihu_auth_expired"


class ZhihuBehaviorLimited(RuntimeError):
    """行为风控临时限制（40362）。cookie 是好的，降频/稍后再试，勿重跑引导。"""

    slug = "zhihu_behavior_limited"


class ZhihuApiError(RuntimeError):
    """其余官方 API 错误（含 HTTP 200 包 error body 的形态）。"""

    slug = "zhihu_api_error"


def _cookie_path() -> str:
    return os.environ.get(ENV_COOKIES, DEFAULT_COOKIE_PATH)


def _load_session_state() -> Dict:
    """读 cookie 文件一次，返回 {"cookies": {...}, "user_agent": "..."}。"""
    path = _cookie_path()
    if not os.path.exists(path):
        raise ZhihuAuthExpired(
            f"cookie 文件不存在: {path}。先跑 python zhihu_bootstrap.py")
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    d_c0 = (payload.get("cookies") or {}).get("d_c0", "")
    if not d_c0:
        raise ZhihuAuthExpired(
            f"cookie 文件里没有 d_c0: {path}。重跑 python zhihu_bootstrap.py")
    return payload


def _raise_for_api_error(resp: requests.Response, body: dict) -> None:
    """把知乎的各类错误形态映射成带 slug 的异常（审查 #1/#2 修复）。

    body 里的 error.code 比HTTP 状态码更具体——40362 行为限制就是 HTTP 403
    状态 + 特定 body 码，必须先判 code 再判状态码，否则会被误诊为 cookie
    过期。
    """
    err = body.get("error") or {}
    code = err.get("code")
    message = err.get("message") or err.get("name") or resp.text[:160]
    if code == _BEHAVIOR_CODE:
        # 行为限制时 cookie 是好的（同会话其他端点可能 200）——重跑引导
        # 无用反而给被标记 IP 再压浏览器流量。正确处置：降频/稍后再试。
        raise ZhihuBehaviorLimited(
            f"HTTP {resp.status_code} code={code}: {message}。"
            f"降频/稍后再试，勿重跑引导")
    if resp.status_code in _AUTH_CODES or code == 40353 or \
            err.get("name") == "AuthenticationError":
        raise ZhihuAuthExpired(
            f"HTTP {resp.status_code} code={code}: {message}。"
            f"重跑 python zhihu_bootstrap.py")
    if err:
        raise ZhihuApiError(f"HTTP {resp.status_code} code={code}: {message}")


def _api_get(path_query: str) -> dict:
    """签名 GET 官方 API。path_query 形如 /api/v4/questions/19550227。"""
    payload = _load_session_state()
    d_c0 = payload["cookies"]["d_c0"]
    url = _API_BASE + path_query
    headers = zhihu_sign.sign_headers(url, d_c0)
    headers.update({
        "User-Agent": payload.get("user_agent") or
        (f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
         f"(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"),
        "Referer": "https://www.zhihu.com/",
        # UA 用签发 cookie 的浏览器原 UA（审查 #6：跨指纹是现成把柄）
        "Cookie": "; ".join(f"{k}={v}"
                            for k, v in payload["cookies"].items()),
    })
    resp = requests.get(url, headers=headers, timeout=TIMEOUT)
    try:
        body = resp.json()
    except ValueError:
        resp.raise_for_status()
        raise ZhihuApiError(
            f"HTTP {resp.status_code} non-JSON: {resp.text[:160]!r}")
    # 知乎部分错误以 HTTP 200 包 error body 返回（审查 #2：不查会伪装真空）
    _raise_for_api_error(resp, body)
    resp.raise_for_status()
    return body


def _check_question_id(question_id: str) -> str:
    """问题 id 必须是纯数字（审查 #5：防止 path 拼接打到别的端点）。"""
    qid = str(question_id).strip()
    if not re.fullmatch(r"\d+", qid):
        raise ZhihuApiError(f"invalid question id: {question_id!r}")
    return qid


def _strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    import html as _html
    return re.sub(r"\s+", " ", _html.unescape(s)).strip()


def fetch_question(question_id: str) -> Dict:
    """问题详情：{id, title, detail(纯文本), answer_count, url}。

    include 必带 answer_count，否则恒为 0（API 默认裁剪字段）。
    """
    qid = _check_question_id(question_id)
    data = _api_get(f"/api/v4/questions/{qid}?include=detail,answer_count")
    return {
        "id": str(data.get("id", qid)),
        "title": data.get("title", ""),
        "detail": _strip_html(data.get("detail", ""))[:2000],
        "answer_count": data.get("answer_count", 0),
        "url": f"https://www.zhihu.com/question/{qid}",
        "engine": "zhihu-api",
    }


def fetch_answers(question_id: str, num: int = 10,
                  sort_by: str = "default") -> List[Dict]:
    """回答列表：[{author, excerpt, voteup, url}]。

    端点用 web 播放器同款 /feeds（实测 2026-09-09）：/answers 子端点会被
    行为风控 40362 临时限制，/feeds 正常。include 分号分隔是官方格式。
    """
    qid = _check_question_id(question_id)
    if num <= 0:
        return []
    params = urllib.parse.urlencode({
        "include": "data[*].content;data[*].author",
        "offset": 0,
        "limit": min(num, 20),
        "sort_by": sort_by,
    })
    data = _api_get(f"/api/v4/questions/{qid}/feeds?{params}")
    out: List[Dict] = []
    for ans in data.get("data", [])[:num]:
        target = ans.get("target") or ans
        aid = target.get("id", "")
        out.append({
            "author": (target.get("author") or {}).get("name", ""),
            "excerpt": (target.get("excerpt") or
                        _strip_html(target.get("content", "")))[:500],
            "voteup": target.get("voteup_count", 0),
            "url": f"https://www.zhihu.com/question/{qid}/answer/{aid}",
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
