#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""知乎官方 API 内容读取 —— cookie 文件 + zhihu_sign 签名，读问题/回答/文章。

分工边界（2026-09-09 实测定稿）：
    - **搜索**仍走 zhihu_engine 降级链（SearXNG→搜狗→百度）：官方 search_v3
      即便带有效 cookie 也强制登录（401 ZERR_NOT_LOGIN），上登录账号是
      主人的产品决策，本工具不碰凭据。
    - **内容**（问题详情/回答列表/专栏文章）用本模块：无头 camoufox 领的
      访客 cookie（zhihu_bootstrap.py 产出）+ zhihu_sign 签名即可 200 读取。
    - 错误语义（绝不伪装真空）：
        zhihu_auth_expired     cookie 缺失/过期（401、40353、ZERR_NOT_LOGIN）
        zhihu_behavior_limited 行为风控临时限制（40362——cookie 是好的，
                               重跑引导无用，降频/稍后再试）
        zhihu_sign_rejected    签名被拒/参数异常（10003——cookie 是好的，
                               2026-09-10 实测 cookie 有效时 members/answers
                               也可能 403+10003；判成 auth 会诱发自愈风暴）
        zhihu_not_found        端点/资源不存在（裸 404，无 error body）
        zhihu_api_error        其他 API 错（含 200 包 error body 的形态）
    - **免 cookie 兜底读法** read_via_browser()：无头 camoufox 带"百度搜索
      来路"打开知乎页面——知乎对搜索引擎引流放行（主人 2026-09-09 提出并
      实测证实：回答全文可见、无登录墙、无 VMP 挑战；Referer 的 query 用
      目标 URL 本身即可泛化）。cookie 文件缺失/过期时仍可读内容，代价是
      每次都要起浏览器（约 10s）。
    - **认证过期自愈（v3.4）**：服务端认证拒绝（ZhihuAuthExpired）时自动
      跑一次无头引导刷新 cookie 并重试原请求一次；进程内 ≥600s 冷却 +
      模块级锁，绝不形成重试风暴。本地 cookie 文件缺失不触发（引导保持
      显式，也保证离线单测零浏览器）。

用法:
    python zhihu_bootstrap.py                 # 先引导（一次，十几秒）
    python zhihu_content.py question 19550227
    python zhihu_content.py answers 19550227
    python zhihu_content.py read <任意URL>    # 通用阅读器（v3.4）：
                                              #   知乎问题/回答/文章走 API 线，
                                              #   外域 HTTP 直连→浏览器兜底

cookie 文件: 环境变量 CHAT_SCRAPER_ZHIHU_COOKIES > state/zhihu_cookies.json
"""
import argparse
import json
import os
import re
import sys
import threading
import time
import urllib.parse
from datetime import datetime
from typing import Dict, List

import requests

import zhihu_sign

__all__ = ["fetch_question", "fetch_answers", "fetch_article", "read",
           "read_via_browser", "ZhihuAuthExpired", "ZhihuBehaviorLimited",
           "ZhihuSignRejected", "ZhihuNotFound", "ZhihuApiError", "ReadError"]

_TOOL = "chat-scraper"
_TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_COOKIES = "CHAT_SCRAPER_ZHIHU_COOKIES"
DEFAULT_COOKIE_PATH = os.path.join(_TOOL_DIR, "state", "zhihu_cookies.json")
_API_BASE = "https://www.zhihu.com"
TIMEOUT = 20

_AUTH_CODES = {401, 403}
_BEHAVIOR_CODE = 40362        # "您当前请求存在异常，暂时限制本次访问"
_SIGN_REJECTED_CODE = 10003   # 签名/参数被拒（≠ cookie 过期，见模块 docstring）

# ---- 自愈闸门（v3.4）：模块级时间戳 + 锁，≥600s 冷却 --------------------
_SELFHEAL_COOLDOWN_S = 600.0
_selfheal_lock = threading.Lock()
# 初值 = -冷却时长：保证进程内首次认证失败即可自愈（monotonic 可能已是开机大值）
_selfheal_last_ts = -_SELFHEAL_COOLDOWN_S


class ZhihuAuthExpired(RuntimeError):
    """cookie 缺失/过期（401/40353/ZERR_NOT_LOGIN）。重跑 zhihu_bootstrap.py。"""

    slug = "zhihu_auth_expired"


class _CookieStateMissing(ZhihuAuthExpired):
    """cookie 文件缺失/无 d_c0（本地状态问题，非服务端应答）。

    单独子类化：自愈只针对服务端认证拒绝；本地文件缺失保持显式引导，
    且离线单测不会因此意外起浏览器。
    """


class ZhihuBehaviorLimited(RuntimeError):
    """行为风控临时限制（40362）。cookie 是好的，降频/稍后再试，勿重跑引导。"""

    slug = "zhihu_behavior_limited"


class ZhihuSignRejected(RuntimeError):
    """签名被拒/参数异常（code 10003）。cookie 是好的——判成 auth_expired
    会诱发无意义的自愈重试风暴（2026-09-10 实测 cookie 有效时 members/
    answers 端点也回 403+10003）。"""

    slug = "zhihu_sign_rejected"


class ZhihuNotFound(RuntimeError):
    """端点或资源不存在（HTTP 404，含裸 404 无 error body 的形态）。"""

    slug = "zhihu_not_found"


class ZhihuApiError(RuntimeError):
    """其余官方 API 错误（含 HTTP 200 包 error body 的形态）。"""

    slug = "zhihu_api_error"


class ReadError(RuntimeError):
    """通用阅读器（read/_generic_read_*）的硬失败：换浏览器线也救不回来
    的（404/5xx、浏览器线正文仍为空等）。"""

    slug = "read_failed"


class _HttpSoftFail(Exception):
    """通用阅读器 HTTP 线的软失败——值得换浏览器线再试
    （403/网络异常/疑似反爬短正文）。模块内部用，不出 __all__。"""


def _cookie_path() -> str:
    return os.environ.get(ENV_COOKIES, DEFAULT_COOKIE_PATH)


def _load_session_state() -> Dict:
    """读 cookie 文件一次，返回 {"cookies": {...}, "user_agent": "..."}。"""
    path = _cookie_path()
    if not os.path.exists(path):
        raise _CookieStateMissing(
            f"cookie 文件不存在: {path}。先跑 python zhihu_bootstrap.py")
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    d_c0 = (payload.get("cookies") or {}).get("d_c0", "")
    if not d_c0:
        raise _CookieStateMissing(
            f"cookie 文件里没有 d_c0: {path}。重跑 python zhihu_bootstrap.py")
    return payload


def _raise_for_api_error(resp: requests.Response, body: dict) -> None:
    """把知乎的各类错误形态映射成带 slug 的异常（审查 #1/#2 + v3.4 修正）。

    body 里的 error.code 比 HTTP 状态码更具体——40362 行为限制、10003 签名
    被拒都是 HTTP 403 状态 + 特定 body 码，必须先判 code 再判状态码，否则
    会被误诊为 cookie 过期（10003 误诊曾是自愈风暴的直接诱因，前置修正）。
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
    if code == _SIGN_REJECTED_CODE:
        # 必须先于认证检查：403+10003 是"签名/参数被拒"不是 cookie 过期
        raise ZhihuSignRejected(
            f"HTTP {resp.status_code} code={code}: {message}。"
            f"签名被拒/参数异常——非 cookie 问题，勿重跑引导，"
            f"检查签名算法/URL 参数")
    if resp.status_code == 404 or code == 404:
        # 裸 404（无 error body）此前以无 slug 的 HTTPError 穿透——协议缺口
        raise ZhihuNotFound(
            f"HTTP 404: 端点或资源不存在: {getattr(resp, 'url', '')}")
    # auth 判定必须有结构化 error 佐证（审查 v3.4：403 无 error body 的 WAF
    # 页误判 auth 会白烧一次引导）——无 error 的 4xx/5xx 落到末尾 generic
    if err and (resp.status_code in _AUTH_CODES or code == 40353 or
                err.get("name") == "AuthenticationError"):
        raise ZhihuAuthExpired(
            f"HTTP {resp.status_code} code={code}: {message}。"
            f"重跑 python zhihu_bootstrap.py（v3.4 起可自动自愈一次）")
    if err:
        raise ZhihuApiError(f"HTTP {resp.status_code} code={code}: {message}")
    if resp.status_code >= 400:
        raise ZhihuApiError(
            f"HTTP {resp.status_code}（无结构化错误体）: {resp.text[:160]!r}")


def _try_self_heal() -> bool:
    """进程级自愈闸门：跑一次无头引导刷新 cookie。

    约束（两评估员共识 + 主人实测）：
        - 模块级时间戳 + 锁：≥600s 冷却，冷却内置位（并发调用只放一个进
          引导，其余直接拿 False，不排队重复引导）；
        - headless=True 无人值守不弹窗；
        - 引导失败打印 stderr 后返回 False（调用方抛原异常），不吞错。
    """
    global _selfheal_last_ts
    with _selfheal_lock:
        now = time.monotonic()
        if now - _selfheal_last_ts < _SELFHEAL_COOLDOWN_S:
            return False
        _selfheal_last_ts = now   # 锁内置位：冷却从"尝试时刻"起算
    print(f"[zhihu_content] self-heal: 认证过期 -> 无头引导刷新 cookie "
          f"(headless, 冷却 {_SELFHEAL_COOLDOWN_S:.0f}s)...", file=sys.stderr)
    try:
        import zhihu_bootstrap
        zhihu_bootstrap.bootstrap(out_path=_cookie_path(), headless=True)
    except Exception as e:
        print(f"[zhihu_content] self-heal 失败: {type(e).__name__}: {e}",
              file=sys.stderr)
        return False
    print("[zhihu_content] self-heal: cookie 已刷新，重试原请求一次...",
          file=sys.stderr)
    return True


def _api_request(path_query: str) -> dict:
    """签名 GET 官方 API（单次，不含自愈）。path_query 形如
    /api/v4/questions/19550227。"""
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
    if resp.status_code == 404:
        # 裸 404 常无 error body，json() 都进不去——在解析前先给 slug
        raise ZhihuNotFound(f"HTTP 404: 端点或资源不存在: {url}")
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


def _api_get(path_query: str) -> dict:
    """签名 GET 官方 API；服务端认证拒绝时自动自愈一次后重试（v3.4）。

    防递归：重试直接调 _api_request，天然不再触发自愈——重试仍失败就把
    该次异常如实抛出。本地 cookie 文件缺失（_CookieStateMissing）不触发
    自愈，保持引导显式。
    """
    try:
        return _api_request(path_query)
    except ZhihuAuthExpired as exc:
        if isinstance(exc, _CookieStateMissing):
            raise
        if not _try_self_heal():
            raise
        return _api_request(path_query)


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


def _fmt_epoch(v) -> str:
    """epoch 秒 → 本地时间可读串；非数值原样透传（API 形态变化不炸）。"""
    try:
        return datetime.fromtimestamp(int(v)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return v if isinstance(v, str) else ""


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


_ARTICLE_URL_RE = re.compile(r"zhuanlan\.zhihu\.com/p/(\d+)")
_ARTICLE_INCLUDE = "title,created,updated,voteup_count,comment_count,content"


def _article_id(article_or_url) -> str:
    """接受纯数字 id 或 zhuanlan.zhihu.com/p/{id} URL，提取纯数字 id。"""
    s = str(article_or_url).strip()
    m = _ARTICLE_URL_RE.search(s)
    if m:
        return m.group(1)
    if re.fullmatch(r"\d+", s):
        return s
    raise ZhihuApiError(f"invalid article id or url: {article_or_url!r}")


def fetch_article(article_or_url) -> Dict:
    """专栏文章（v3.4）：{id, title, content(纯文本≤8000), created, updated,
    voteup, comment_count, url, engine:"zhihu-api"}。

    端点 `GET /api/v4/articles/{id}` 已实测存在（2026-09-10，HTTP 200）；
    include 用逗号语法，但服务器是否真回 content 未静态保证——content 空
    回退 excerpt，再空**如实报字段缺失**，绝不伪装正文为空（通用阅读器
    的真空纪律同样适用于这里）。
    """
    aid = _article_id(article_or_url)
    data = _api_get(f"/api/v4/articles/{aid}?include={_ARTICLE_INCLUDE}")
    text = _strip_html(data.get("content") or "")
    if not text:
        text = _strip_html(data.get("excerpt") or "")
    if not text:
        raise ZhihuApiError(
            f"article {aid}: API 未返回 content/excerpt 字段（include 逗号"
            f"语法可能未生效），返回键={sorted(data)}——如实报缺，不伪装正文为空")
    return {
        "id": str(data.get("id", aid)),
        # 审查 v3.4 #7：知乎 API 的文章 title 是 URL 编码态（%28%29 等）
        "title": urllib.parse.unquote(data.get("title", "")),
        "content": text[:8000],
        "created": _fmt_epoch(data.get("created")),
        "updated": _fmt_epoch(data.get("updated")),
        "voteup": data.get("voteup_count", 0),
        "comment_count": data.get("comment_count", 0),
        "url": f"https://zhuanlan.zhihu.com/p/{aid}",
        "engine": "zhihu-api",
    }


def _check_page_url(url: str) -> str:
    """知乎内容页 URL 校验（www./zhuanlan./裸域均放行；防域伪装）。
    校验在浏览器启动前执行，可离线单测。"""
    if not re.fullmatch(r"https?://(?:www\.|zhuanlan\.)?zhihu\.com/\S+",
                        url or ""):
        raise ZhihuApiError(f"not a zhihu page url: {url!r}")
    return url


def _check_http_url(url: str) -> str:
    """任意 URL 的最低限度护栏：仅 http(s) 绝对 URL（防 javascript:/file:）。"""
    p = urllib.parse.urlparse(url or "")
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ReadError(f"not a http(s) url: {url!r}")
    return url


def read_via_browser(url: str, headless: bool = True,
                     wait_ms: int = 6000) -> Dict:
    """免 cookie 读知乎页面：无头 camoufox + 百度搜索来路（SEO 引流放行）。

    实测（2026-09-09）：回答全文可见、无登录墙、无 VMP 挑战；Referer 的
    query 用目标 URL 本身即可泛化。代价是每次起浏览器（约 10s）——
    结构化读取请优先走 fetch_question/fetch_answers（cookie 线）。

    Returns:
        {title, content(纯文本, 截 8000 字), url, engine: "zhihu-seo-browser"}
    """
    _check_page_url(url)
    try:
        from camoufox.sync_api import Camoufox
    except ImportError as e:
        raise RuntimeError(
            "camoufox 未安装。安装：pip install \"camoufox[geoip]\" "
            "&& python -m camoufox fetch") from e
    referer = "https://www.baidu.com/s?wd=" + urllib.parse.quote(url)
    with Camoufox(headless=headless, geoip=True) as browser:
        ctx = browser.new_context(locale="zh-CN", timezone_id="Asia/Shanghai")
        page = ctx.new_page()
        page.goto(url, referer=referer,
                  wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(wait_ms)
        if "signin" in (page.url or ""):
            raise ZhihuAuthExpired(
                f"被重定向到登录页（SEO 引流放行失效？）: {page.url!r}")
        title = page.title()
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(page.content(), "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        # 回答/文章正文节点优先，整页文本兜底
        nodes = soup.select(".post-content, .RichContent-inner, "
                            ".QuestionRichText, .QuestionDetail")
        text = "\n".join(n.get_text("\n", strip=True)
                         for n in nodes).strip()
        if not text:
            text = soup.get_text("\n", strip=True)
        return {
            "title": title,
            "content": text[:8000],
            "url": page.url,
            "engine": "zhihu-seo-browser",
        }


# ---- 通用阅读器（v3.4，两评估员共识：阅读线服务所有搜索产出） ------------

# 正文选择器优先级：语义标签 > 常见博客容器 > main > #content > body 兜底
_GENERIC_SELECTORS = ("article, .post-content, .article-content, "
                      "main, #content")
_MIN_ARTICLE_CHARS = 200   # 低于此判疑似反爬/空壳页 → 换浏览器线

# 与 baidu_engine 同款 Chrome 文档导航 Accept（requests 默认 */* 是机器人
# 指纹——百度实测结论，通用 HTTP 线同样适用）
_GENERIC_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/152.0.0.0 Safari/537.36"),
    "Accept": ("text/html,application/xhtml+xml,application/xml;q=0.9,"
               "image/avif,image/webp,image/apng,*/*;q=0.8,"
               "application/signed-exchange;v=b3;q=0.7"),
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",   # 不声明 br：requests 可能解不了
    "Connection": "keep-alive",
}


def _generic_session() -> requests.Session:
    """通用 HTTP 线会话：强制直连（系统代理半死时会伪造故障，与全工具箱
    一致 trust_env=False）+ 完整 Chrome 头。"""
    sess = requests.Session()
    sess.trust_env = False
    sess.headers.update(_GENERIC_HEADERS)
    return sess


def _bs4_soup(html: str):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html or "", "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup


def _extract_text_from_soup(soup) -> str:
    """选择器优先提取正文，body 纯文本兜底（soup 已去 script/style）。"""
    nodes = soup.select(_GENERIC_SELECTORS)
    text = "\n".join(n.get_text("\n", strip=True) for n in nodes).strip()
    if not text:
        body = soup.body or soup
        text = body.get_text("\n", strip=True)
    return text


def _extract_article_text(html: str) -> str:
    """HTML 字符串 → 正文纯文本（去 script/style；浏览器线用）。"""
    return _extract_text_from_soup(_bs4_soup(html))


def _page_title(soup) -> str:
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content", "").strip():
        return og["content"].strip()
    if soup.title and soup.title.get_text(strip=True):
        return soup.title.get_text(strip=True)
    return ""


def _generic_read_http(url: str, timeout: int = 20) -> Dict:
    """外域 HTTP 直连读取。软失败（值得换浏览器线的）抛 _HttpSoftFail：
    网络异常、403、正文 <200 字（疑似反爬/空壳）。硬失败（换浏览器也一样
    死的 404/5xx）直接抛 ReadError——不烧浏览器（一次约 10s+）。"""
    sess = _generic_session()
    try:
        resp = sess.get(url, timeout=timeout)
    except requests.exceptions.RequestException as e:
        raise _HttpSoftFail(f"{type(e).__name__}: {e}") from e
    if resp.status_code == 403:
        raise _HttpSoftFail(f"HTTP 403（疑似反爬）: {resp.url}")
    if resp.status_code >= 400:
        raise ReadError(f"HTTP {resp.status_code}: {resp.url}——"
                        f"换浏览器线也一样死，如实报错")
    # Content-Type 护栏（审查 v3.4 #2）：>200 字的 JSON/二进制不是"正文"
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if ctype and "html" not in ctype:
        raise _HttpSoftFail(
            f"Content-Type {ctype.split(';')[0]!r} 非 HTML: {resp.url}")
    soup = _bs4_soup(resp.text)   # 一次解析，正文与标题共用
    text = _extract_text_from_soup(soup)
    if len(text) < _MIN_ARTICLE_CHARS:
        raise _HttpSoftFail(
            f"疑似反爬/空壳页（正文仅 {len(text)} 字 < "
            f"{_MIN_ARTICLE_CHARS}）: {resp.url}")
    return {
        "title": _page_title(soup),
        "content": text[:8000],
        "url": resp.url,
        "engine": "http",
    }


def _generic_read_browser(url: str, headless: bool = True,
                          wait_ms: int = 4000) -> Dict:
    """浏览器兜底：无头 camoufox 直开（无需 Referer 技巧——那是知乎 SEO
    特性）。engine="browser"。"""
    _check_http_url(url)
    try:
        from camoufox.sync_api import Camoufox
    except ImportError as e:
        raise RuntimeError(
            "camoufox 未安装。安装：pip install \"camoufox[geoip]\" "
            "&& python -m camoufox fetch") from e
    with Camoufox(headless=headless, geoip=True) as browser:
        ctx = browser.new_context(locale="zh-CN", timezone_id="Asia/Shanghai")
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(wait_ms)
        text = _extract_article_text(page.content())
        if not text:
            raise ReadError(
                f"浏览器线正文为空: {page.url}——如实报错，不伪装")
        # 审查 v3.4 #3：<200 字不再一票否决——浏览器线能过反爬说明页面
        # 是真的，短博文/短回答照实返回（HTTP 线的 <200 判据只服务反爬检测）
        return {
            "title": page.title(),
            "content": text[:8000],
            "url": page.url,
            "engine": "browser",
        }


def _generic_read(url: str) -> Dict:
    """外域读取编排：HTTP 直连优先，软失败换浏览器线（动作打 stderr）。"""
    try:
        return _generic_read_http(url)
    except _HttpSoftFail as soft:
        print(f"[zhihu_content] http 线软失败（{soft}）→ 浏览器兜底",
              file=sys.stderr)
        return _generic_read_browser(url)


_QUESTION_RE = re.compile(r"zhihu\.com/question/(\d+)")
_ANSWER_RE = re.compile(r"zhihu\.com/question/(\d+)/answer/(\d+)")
_ZHUANLAN_RE = re.compile(r"zhuanlan\.zhihu\.com/p/(\d+)")


class _AnswerMiss(Exception):
    """目标回答不在返回的首页集合里（分流到浏览器线读取）。"""


def read(url: str) -> Dict:
    """通用阅读器（v3.4）：一个入口读任意 URL，返回统一
    {title, content, url, engine}。

    分流：
        知乎问题                 -> fetch_question（cookie+签名 API）
        知乎 question/answer/aid -> fetch_answers 过滤该 aid；过滤不到或
                                    API 线挂 → read_via_browser 兜底
        知乎专栏 /p/{id}          -> fetch_article
        其他知乎 URL              -> read_via_browser（SEO 引流线）
        非知乎域名                -> HTTP 直连 + 选择器提取；403/网络异常/
                                    疑似反爬（正文<200字）→ 无头浏览器兜底
    """
    u = _check_http_url((url or "").strip())
    host = (urllib.parse.urlparse(u).hostname or "").lower()

    def _api_or_browser(project, fn):
        """知乎 API 三分支共用的兜底（审查 v3.4 #1/#4）：API 线任何失败
        （含非 JSON 403 的裸 HTTPError）都回浏览器线；成功走 project 归一
        成 {title, content, url, engine}。"""
        try:
            return project(fn())
        except (ZhihuAuthExpired, ZhihuBehaviorLimited, ZhihuSignRejected,
                ZhihuNotFound, ZhihuApiError,
                requests.exceptions.HTTPError) as e:
            print(f"[zhihu_content] API 线失败"
                  f"（{getattr(e, 'slug', type(e).__name__)}）→ "
                  f"浏览器兜底", file=sys.stderr)
            return read_via_browser(u)

    if host == "zhihu.com" or host.endswith(".zhihu.com"):
        m = _ANSWER_RE.search(u)
        if m:
            qid, aid = m.group(1), m.group(2)

            def _answer_project(answers):
                hit = next((a for a in answers
                            if str(a.get("url", "")).rstrip("/")
                            .endswith(f"/answer/{aid}")), None)
                if hit is None:
                    raise _AnswerMiss()
                return {
                    "title": f"知乎回答 by {hit.get('author', '')} "
                             f"(question/{qid})",
                    "content": hit.get("excerpt", ""),
                    "url": hit.get("url") or u,
                    "engine": "zhihu-api",
                }

            try:
                return _api_or_browser(
                    _answer_project, lambda: fetch_answers(qid, num=20))
            except _AnswerMiss:
                # 前 20 条没有目标回答（真知乎常态）——SEO 浏览器线读
                print("[zhihu_content] 目标回答不在首页 20 条 → 浏览器线",
                      file=sys.stderr)
                return read_via_browser(u)
        m = _QUESTION_RE.search(u)
        if m:
            return _api_or_browser(
                lambda q: {"title": q["title"], "content": q["detail"],
                           "url": q["url"], "engine": "zhihu-api"},
                lambda: fetch_question(m.group(1)))
        m = _ZHUANLAN_RE.search(u)
        if m:
            return _api_or_browser(
                lambda a: {"title": a["title"], "content": a["content"],
                           "url": a["url"], "engine": "zhihu-api"},
                lambda: fetch_article(m.group(1)))
        return read_via_browser(u)
    return _generic_read(u)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="知乎官方 API 内容读取（需先 zhihu_bootstrap.py 领 cookie）"
                    "+ 通用阅读器 read <url>")
    sub = parser.add_subparsers(dest="cmd", required=True)
    pq = sub.add_parser("question", help="问题详情")
    pq.add_argument("id")
    pa = sub.add_parser("answers", help="回答列表")
    pa.add_argument("id")
    pa.add_argument("--num", type=int, default=10)
    pa_ = sub.add_parser("article", help="专栏文章（官方 API 线，v3.4）")
    pa_.add_argument("id_or_url")
    pp = sub.add_parser("page", help="免 cookie 读页面全文（无头浏览器+百度来路）")
    pp.add_argument("url")
    pr = sub.add_parser("read", help="通用阅读器（v3.4）：知乎问题/回答/文章"
                                     "走 API，外域 HTTP→浏览器兜底")
    pr.add_argument("url")
    args = parser.parse_args()

    try:
        if args.cmd == "question":
            out = fetch_question(args.id)
        elif args.cmd == "page":
            out = read_via_browser(args.url)
        elif args.cmd == "article":
            out = fetch_article(args.id_or_url)
        elif args.cmd == "read":
            out = read(args.url)
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
