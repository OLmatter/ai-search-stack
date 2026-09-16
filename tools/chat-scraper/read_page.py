#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""通用网页阅读原语 —— SSRF 护栏 + 错误页识别 + HTTP/浏览器双线读取。

出身（v3.28，C1 拆分裁决）：本模块原是 zhihu_content.py 的「通用阅读器」
半边（v3.4 引入，历经 v3.5 错误页判据、v3.7 SSRF 护栏、v3.11 截断可见化
六轮叠加）。zhihu_content.py 长到 1109 行后两簇关注点彻底可分——知乎
API 线（cookie/签名/自愈/fetch_*）与通用阅读线（本模块）的依赖集毫无
交集（bs4/camoufox/SSRF vs zhihu_sign/zhihu_bootstrap），且 MCP 的
read_page 工具名与本模块天然对齐，故拆出。

**边界铁律：本模块零知乎依赖**。知乎 URL 的 API 分流（fetch_question/
fetch_answers/fetch_article/read_via_browser SEO 线）留在 zhihu_content.read()
分流器里；本模块只提供「拿到一个已判定合法的公网 URL → 读出正文」的原语：
    read_generic(url)   外域读取编排：HTTP 直连优先，软失败换浏览器线
    check_http_url(url) 最低限度 URL 护栏（scheme 白名单 + SSRF 私网拒绝）
    ReadError           硬失败（换浏览器线也救不回来），slug="read_failed"

其余下划线名是历史形态的延续（zhihu_content 按名重导出以保兼容钉），
新代码一律走公开入口。
"""
import ipaddress
import socket
import sys
import urllib.parse

import requests

__all__ = ["read_generic", "check_http_url", "ReadError"]


class ReadError(RuntimeError):
    """通用阅读器（read_generic 及各线）的硬失败：换浏览器线也救不回来
    的（404/5xx、浏览器线正文仍为空等）。"""

    slug = "read_failed"


class _HttpSoftFail(Exception):
    """通用阅读器 HTTP 线的软失败——值得换浏览器线再试
    （403/网络异常/疑似反爬短正文）。模块内部用，不出 __all__。"""


# 正文输出统一截断上限（v3.11 起截断必须可见：输出带 truncated 标记，
# 不再让调用方把"被剪过的 content"误当全文——诚实纪律适用于截断）。
CONTENT_LIMIT = 8000


def _content_field(text: str) -> "tuple[str, bool]":
    """(截断后正文, 是否发生截断)。所有 content 输出口径一致。"""
    return text[:CONTENT_LIMIT], len(text) > CONTENT_LIMIT


# 私网/链路本地段黑名单（v3.7 SSRF 护栏）：read() 可读任意 URL，hostname
# 解析进这些段一律拒绝，防止把内网服务当"网页"读出来。
_PRIVATE_NETS = tuple(
    ipaddress.ip_network(n) for n in (
        "127.0.0.0/8",      # loopback
        "10.0.0.0/8",       # RFC1918
        "172.16.0.0/12",    # RFC1918
        "192.168.0.0/16",   # RFC1918
        "169.254.0.0/16",   # link-local（含云元数据 169.254.169.254）
        "::1/128",          # IPv6 loopback
    ))


def _is_private_host(hostname: str) -> bool:
    """hostname 解析出的任一 IP 落在私网/链路本地段 → True。

    DNS 解析失败按私网处理（fail-closed：解析不了的域名本来也连不上，
    但不能给"解析失败→放行→直连内网字面 IP"留旁路）。
    纯函数，可离线单测（mock socket.getaddrinfo）。
    """
    try:
        infos = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, OSError, UnicodeError):
        return True
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return True
        if any(ip in net for net in _PRIVATE_NETS):
            return True
    return False


def _check_http_url(url: str) -> str:
    """任意 URL 的最低限度护栏：仅 http(s) 绝对 URL（防 javascript:/file:）；
    hostname 解析进私网/链路本地段一律拒绝（SSRF 护栏，slug 沿用
    read_failed）。合法公网域名照常放行。"""
    p = urllib.parse.urlparse(url or "")
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ReadError(f"not a http(s) url: {url!r}")
    hostname = p.hostname
    if hostname and _is_private_host(hostname):
        raise ReadError(
            f"私网/链路本地地址拒绝读取（SSRF 护栏）: {hostname!r} ({url})")
    return url


# 历史名对齐：zhihu_content 按原名重导出（v3.28 拆分兼容层）
check_http_url = _check_http_url


def _raise_if_error_page(text: str, url: str) -> None:
    """短文本命中错误/验证页标记 → ReadError（绝不把验证页当正文返回）。

    长文本（≥500 字）含同词视为正常讨论（技术文聊"环境异常"很常见），
    不判；错误页实测 75B~数百字。
    """
    if len(text) >= _ERROR_PAGE_MAX_LEN:
        return
    for marker in _ERROR_PAGE_MARKERS:
        if marker in text:
            raise ReadError(
                f"命中错误页标记 {marker!r}（正文仅 {len(text)} 字）: {url}——"
                f"该站点对自动化环境返回了验证/错误页，如实报错")


# 浏览器线错误页标记（审查 v3.5 #3/#4）。仅在"短文本"时判定：长文含同词
# 多为正常讨论（如技术文聊"环境异常"），不能误杀。错误页实测 75B~数百字。
_ERROR_PAGE_MARKERS = ("完成验证后即可继续访问", "环境异常", "参数错误",
                       "该内容已被发布者删除", "此内容因违规无法查看",
                       "操作过于频繁", "当前环境异常", "内容审核中")
_ERROR_PAGE_MAX_LEN = 500


# ---- 通用阅读线（v3.4 起，两评估员共识：阅读线服务所有搜索产出） --------

# 正文选择器优先级：语义标签 > 常见博客容器 > main > #content > body 兜底
# （#js_content=微信公众号文章、.rich_media_content=微信正文容器）
_GENERIC_SELECTORS = ("article, .post-content, .article-content, "
                      "#js_content, .rich_media_content, "
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


def _generic_read_http(url: str, timeout: int = 20) -> dict:
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
    content, truncated = _content_field(text)
    return {
        "title": _page_title(soup),
        "content": content,
        "truncated": truncated,
        "url": resp.url,
        "engine": "http",
    }


def _generic_read_browser(url: str, headless: bool = True,
                          wait_ms: int = 4000) -> dict:
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
        _raise_if_error_page(text, page.url)
        # 审查 v3.4 #3：<200 字不再一票否决——浏览器线能过反爬说明页面
        # 是真的，短博文/短回答照实返回（HTTP 线的 <200 判据只服务反爬检测）
        content, truncated = _content_field(text)
        return {
            "title": page.title(),
            "content": content,
            "truncated": truncated,
            "url": page.url,
            "engine": "browser",
        }


def read_generic(url: str) -> dict:
    """外域读取编排：HTTP 直连优先，软失败换浏览器线（动作打 stderr）。"""
    try:
        return _generic_read_http(url)
    except _HttpSoftFail as soft:
        print(f"[read_page] http 线软失败（{soft}）→ 浏览器兜底",
              file=sys.stderr)
        return _generic_read_browser(url)


# 历史名对齐（v3.28 前的内部名；zhihu_content.read 旧路径兼容）
_generic_read = read_generic
