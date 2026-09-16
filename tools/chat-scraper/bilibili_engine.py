#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""bilibili 官方搜索 API 引擎（video 分类，结构化字段）

实测结论（2026-09-09 本机验证，v3 重写的依据）:
    - 裸调即通: 先 GET https://www.bilibili.com/ 从 Set-Cookie 拿 buvid3
      （未登录调搜索接口基本必须有 buvid3，否则常见 -412），
      再带 cookie 调 search/type?search_type=video&... -> code=0。
    - 字段: result[].title 含 <em class="keyword"> 高亮（正则剥掉）、author、
      pubdate(unix 秒)、play、bvid -> https://www.bilibili.com/video/{bvid}。
    - 广告过滤必须: 部分条目 bvid 为空（无 bvid、pubdate=1970 的
      "咨询领福利"推广卡），一律丢弃。
    - 风控可能升级要求 wbi 签名: wbi 实现已内置（nav 未登录也下发 wbi_img；
      mixin_key=按固定重排表混淆取前 32 位; w_rid=md5(排序后 urlencode 参数
      + mixin_key)）。收到 code=-403/-412 时自动带签名重试一次。

用法:
    from bilibili_engine import search, fetch_video, fetch_subtitles
    results = search("python 教程", num=10)
    info = fetch_video("BV1GJ411x7h7")            # 结构化详情（含 cid）
    subs = fetch_subtitles("BV1GJ411x7h7")        # 字幕链路（未登录实测恒空列表，见下）

CLI:
    python bilibili_engine.py "python 教程" --num 10

错误协议（与仓库其他工具一致）:
    on_error="report"（默认）: 出错返回
        [{"error": "bilibili_api_error: code=-412 ...", "tool": "chat-scraper",
          "query": q, "platform": "bilibili"}]
    on_error="raise" 抛出; on_error="empty" 兼容旧行为返回 []。
"""
import argparse
import datetime
import hashlib
import html
import json
import os
import re
import sys
import threading
import time
import urllib.parse
from typing import Dict, List, Optional, Tuple

import requests

__all__ = ["search", "fetch_video", "fetch_subtitles", "BilibiliApiError"]

_TOOL = "chat-scraper"
_PLATFORM = "bilibili"
_HOME_URL = "https://www.bilibili.com/"
_API_SEARCH = "https://api.bilibili.com/x/web-interface/search/type"
_API_NAV = "https://api.bilibili.com/x/web-interface/nav"
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")

# 环境变量：两次 bilibili 请求的最小间隔秒数
ENV_MIN_INTERVAL = "CHAT_SCRAPER_BILIBILI_MIN_INTERVAL"
DEFAULT_MIN_INTERVAL = 3.0
TIMEOUT = 20                      # 单请求超时（秒）
ORDER = "totalrank"               # 综合排序（官方默认）
RESULTS_PER_PAGE = 30             # 官方单页上限约 30 条
MAX_PAGES = 5                     # 搜索翻页护栏（v3.11）：num 有效上限约 150
WBI_KEY_TTL = 3600.0              # wbi key 缓存时长（官方按天轮换，1h 足够新鲜）
RETRYABLE_CODES = {-403, -412}    # 收到即认为可能要求 wbi 签名，签名重试一次
# wbi 签名用的固定重排表（来源 bilibili-API-collect，社区逆向的混淆表）
_MIXIN_KEY_ENC_TAB = [46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
                      27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
                      37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
                      22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52]
MIXIN_KEY_LEN = 32
# since -> 客户端按 pubdate 过滤的滚动窗口秒数（API 本身不支持时间过滤）
_SINCE_WINDOWS = {"24h": 86400, "7d": 604800, "30d": 2592000, "90d": 7776000}


class BilibiliApiError(Exception):
    """bilibili API 返回非 0 code 或非 JSON 响应。"""

    slug = "bilibili_api_error"


_session: Optional[requests.Session] = None
# RLock: _get_wbi_keys 持锁时会再调 _get_session()，非重入 Lock 会自锁死
_session_lock = threading.RLock()
_throttle_lock = threading.Lock()
_last_request_ts = 0.0
_wbi_keys: Optional[Tuple[str, str]] = None
_wbi_keys_ts = 0.0


def _min_interval() -> float:
    """读取环境变量配置的最小请求间隔（秒），非法值回退默认。"""
    raw = os.environ.get(ENV_MIN_INTERVAL, "")
    try:
        val = float(raw) if raw else DEFAULT_MIN_INTERVAL
    except ValueError:
        return DEFAULT_MIN_INTERVAL
    return val if val >= 0 else DEFAULT_MIN_INTERVAL


def _wait_turn() -> None:
    """所有对外请求前调用: 保证与上一次 bilibili 请求间隔 >= min_interval。"""
    global _last_request_ts
    with _throttle_lock:
        wait = _last_request_ts + _min_interval() - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request_ts = time.monotonic()


def _get_session() -> requests.Session:
    """懒加载进程级会话: 先访问首页拿 buvid3 cookie。"""
    global _session
    with _session_lock:
        if _session is None:
            _wait_turn()
            s = requests.Session()
            # trust_env=False: 同 baidu_engine —— 系统代理半死不活会伪造
            # ProxyError/timeout 页，bilibili 在中国网络下直连即通
            s.trust_env = False
            s.headers.update({
                "User-Agent": _UA,
                "Referer": "https://www.bilibili.com/",
                "Origin": "https://www.bilibili.com",
            })
            s.get(_HOME_URL, timeout=TIMEOUT)
            _session = s
        return _session


def _get_wbi_keys(force_refresh: bool = False) -> Tuple[str, str]:
    """获取 wbi 签名的 img_key/sub_key（带 TTL 缓存）。

    nav 接口未登录也下发 wbi_img.img_url/sub_url，key 在 URL 文件名里。
    """
    global _wbi_keys, _wbi_keys_ts
    with _session_lock:
        fresh = (_wbi_keys is not None
                 and time.monotonic() - _wbi_keys_ts < WBI_KEY_TTL)
        if fresh and not force_refresh:
            assert _wbi_keys is not None
            return _wbi_keys
        _wait_turn()
        s = _get_session()
        resp = s.get(_API_NAV, timeout=TIMEOUT)
        try:
            nav = resp.json()
        except ValueError as e:
            raise BilibiliApiError(
                f"nav returned non-JSON (HTTP {resp.status_code}): {e}") from e
        wbi_img = ((nav.get("data") or {}).get("wbi_img") or {})
        img_key = _key_from_url(wbi_img.get("img_url", ""))
        sub_key = _key_from_url(wbi_img.get("sub_url", ""))
        if not img_key or not sub_key:
            raise BilibiliApiError("failed to extract wbi keys from nav response")
        _wbi_keys = (img_key, sub_key)
        _wbi_keys_ts = time.monotonic()
        return _wbi_keys


def _key_from_url(url: str) -> str:
    """wbi key = URL 文件名去扩展名（.../xxxx.png -> xxxx）。"""
    return url.rstrip("/").split("/")[-1].split(".")[0]


def _mixin_key(orig: str) -> str:
    """按固定重排表混淆 img_key+sub_key，取前 32 位。"""
    return "".join(orig[i] for i in _MIXIN_KEY_ENC_TAB)[:MIXIN_KEY_LEN]


def _wbi_sign(params: Dict[str, object], img_key: str, sub_key: str) -> Dict[str, object]:
    """按 bilibili-API-collect 的 wbi 算法生成带 wts/w_rid 的参数。"""
    p = dict(params)
    p["wts"] = round(time.time())
    p = dict(sorted(p.items()))
    # 过滤 value 中的 "!'()*" 字符是官方前端行为，签名校验同样按过滤后算
    p = {k: "".join(c for c in str(v) if c not in "!'()*") for k, v in p.items()}
    query = urllib.parse.urlencode(p)
    p["w_rid"] = hashlib.md5((query + _mixin_key(img_key + sub_key)).encode()).hexdigest()
    return p


def _call_search(s: requests.Session, params: Dict[str, object]) -> Dict:
    """调搜索接口（节流），非 JSON 响应抛 BilibiliApiError。"""
    _wait_turn()
    resp = s.get(_API_SEARCH, params=params, timeout=TIMEOUT)
    try:
        return resp.json()
    except ValueError:
        raise BilibiliApiError(
            f"non-JSON response HTTP {resp.status_code}: {resp.text[:120]!r}")


def _clean_title(s: str) -> str:
    """剥掉标题里的 <em class="keyword"> 高亮标签，并还原 HTML 实体
    （API 标题里 &lt; &amp; 等是转义过的，实测会出现）。"""
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def _fmt_pubdate(ts: int) -> str:
    if not ts:      # 0 = 缺失/广告卡，伪造 "1970-01-01" 是撒谎
        return ""
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def search(
    q: str,
    num: int = 10,
    since: Optional[str] = None,
    vendor: str = "?",
    role: str = "primary",
    page: int = 1,
    on_error: str = "report",
) -> List[Dict]:
    """bilibili 视频搜索（官方 API，结构化字段）。

    Args:
        q: 搜索关键词
        num: 返回条数上限。单页约 30 条；num>30 自动翻页（护栏 MAX_PAGES=5
            页，即有效上限约 150 条）——护栏耗尽或服务端空页时安静返回已
            收集条数（护栏是防失控，不是异常信号；页间节流走引擎内置
            _wait_turn，风控压力与分页次数线性可控）
        since: 时间窗 24h/7d/30d/90d -> 客户端按 pubdate 过滤（API 不支持
            服务端时间过滤，过滤后可能少于 num）; None/"" 不过滤
        vendor: 主题分类（指标用，透传）
        role: primary / fallback / verify（透传）
        page: 起始页码（从 1 开始；翻页自该页起算）
        on_error: "report" / "raise" / "empty"（见模块 docstring）

    Returns:
        [{title, url, snippet, platform, engine, author, play, pubdate,
          vendor, role, since}, ...]
    """
    try:
        return _search_impl(q, num, since, vendor, role, page)
    except Exception as e:
        if on_error == "raise":
            raise
        if on_error == "report":
            slug = getattr(e, "slug", None) or type(e).__name__
            return [{"error": f"{slug}: {e}", "tool": _TOOL,
                     "query": q, "platform": _PLATFORM}]
        return []  # on_error == "empty": 兼容旧行为


def _search_impl(q: str, num: int, since: Optional[str], vendor: str,
                 role: str, page: int) -> List[Dict]:
    s = _get_session()

    cutoff = 0.0
    if since:
        window = _SINCE_WINDOWS.get(since)
        if window is None:
            print(f"[bilibili_engine] warning: unsupported since={since!r} "
                  f"(only 24h/7d/30d/90d); no time filter applied",
                  file=sys.stderr)
        else:
            cutoff = time.time() - window

    out: List[Dict] = []
    if num <= 0:
        return out
    fetched_pages = 0
    p = page
    while fetched_pages < MAX_PAGES and len(out) < num:
        params: Dict[str, object] = {
            "search_type": "video",
            "keyword": q,
            "order": ORDER,
            "page": p,
        }
        payload = _call_search(s, params)   # 内置 _wait_turn 引擎级节流
        if payload.get("code") in RETRYABLE_CODES:
            # 风控升级要求 wbi 签名时自动签名重试一次（见模块 docstring）
            img_key, sub_key = _get_wbi_keys(force_refresh=True)
            payload = _call_search(s, _wbi_sign(params, img_key, sub_key))
        if payload.get("code") != 0:
            raise BilibiliApiError(
                f"code={payload.get('code')} message={payload.get('message')}")

        items = (payload.get("data") or {}).get("result") or []
        for item in items:
            bvid = item.get("bvid") or ""
            if not bvid:
                continue  # 无 bvid 的是广告推广卡（pubdate=1970 的"咨询领福利"），丢弃
            pubdate = int(item.get("pubdate") or 0)
            if cutoff and pubdate < cutoff:
                continue
            out.append({
                "title": _clean_title(item.get("title", "")),
                "url": f"https://www.bilibili.com/video/{bvid}",
                "snippet": (item.get("description") or "").strip(),
                "platform": _PLATFORM,
                "engine": "bilibili",
                "author": item.get("author", ""),
                "play": item.get("play"),
                "pubdate": _fmt_pubdate(pubdate),
                "vendor": vendor,
                "role": role,
                "since": since or "all",
            })
            if len(out) >= num:
                break
        fetched_pages += 1
        p += 1
        if not items:
            break   # 服务端空页 = 真空到底，如实停，不发多余请求
    return out


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="bilibili 官方 API 视频搜索")
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
            print(f"[bilibili_engine] error: {r['error']}", file=sys.stderr)
        return 1
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main())


def _extract_bvid(video: str) -> Optional[str]:
    """从纯 BV 号或任意含 BV 号的 URL 里提取 bvid；不匹配返回 None。"""
    m = re.search(r"(BV[0-9A-Za-z]{10})", video or "")
    return m.group(1) if m else None


def fetch_video(video: str, vendor: str = "?", role: str = "primary",
                on_error: str = "report") -> Dict:
    """视频结构化详情：官方 view API（公开、免 wbi）。

    video 接受纯 bvid（BV1xx…）或任意含 BV 号的 URL。成功返回 Dict；
    on_error="report" 时错误返回 List（统一错误协议）——两种返回形态；
    风控/不存在按统一错误协议处理。cid 为 P1 的 cid（多 P 视频各分 P 的
    cid 见 view 原始响应 data.pages，本工具不展开）。
    """
    bvid = _extract_bvid(video)
    if not bvid:
        err = ValueError(f"invalid bvid: {video!r}")
        if on_error == "raise":
            raise err
        if on_error == "report":
            return [{"error": f"ValueError: {err}", "tool": _TOOL,
                     "query": video, "platform": _PLATFORM}]
        return []
    try:
        s = _get_session()
        _wait_turn()
        resp = s.get("https://api.bilibili.com/x/web-interface/view",
                     params={"bvid": bvid}, timeout=TIMEOUT)
        resp.raise_for_status()   # 412/5xx HTML 页直接走 HTTPError，别假装 JSON
        data = resp.json()
        if data.get("code") != 0:
            raise BilibiliApiError(
                f"code={data.get('code')} message={data.get('message')}")
        v = data.get("data") or {}
        from datetime import datetime as _dt
        return {
            "title": _clean_title(v.get("title", "")),
            "desc": (v.get("desc") or "").strip()[:2000],
            "owner": (v.get("owner") or {}).get("name", ""),
            "cid": v.get("cid"),
            "view": v.get("stat", {}).get("view", 0),
            "danmaku": v.get("stat", {}).get("danmaku", 0),
            "like": v.get("stat", {}).get("like", 0),
            "favorite": v.get("stat", {}).get("favorite", 0),
            "pubdate": _fmt_pubdate(int(v.get("pubdate") or 0)),
            "url": f"https://www.bilibili.com/video/{bvid}",
            "platform": _PLATFORM,
            "engine": "bilibili-api",
            "vendor": vendor,
            "role": role,
        }
    except Exception as e:
        if on_error == "raise":
            raise
        if on_error == "report":
            slug = getattr(e, "slug", None) or type(e).__name__
            return [{"error": f"{slug}: {e}", "tool": _TOOL,
                     "query": video, "platform": _PLATFORM}]
        return []


_API_PLAYER = "https://api.bilibili.com/x/player/wbi/v2"


def fetch_subtitles(video: str, on_error: str = "report") -> Dict:
    """B 站视频 CC 字幕读取（v3.9）：view API 拿 cid → player/wbi/v2（wbi
    签名，密钥复用引擎内置缓存）拿 subtitle.subtitles 列表 → 字幕逐个
    拉 JSON 正文（{"from","to","content"} 行列表）。

    video 接受纯 bvid 或任意含 BV 号的 URL；取 P1（view 响应的 data.cid）。

    **实测上限（2026-09-16，如实报告）**：未登录访客请求 subtitle 列表
    **恒为空**——三个视频实测（含标题自带"CC字幕更新完毕"、确有 CC 字幕
    的视频），B 站仅向登录态（SESSDATA）下发字幕列表，手动上传 CC 亦不
    豁免；AI 识别字幕更需登录。本工具不带登录态，故当前 subtitles 恒为
    空列表（has_subtitles=False）。这**不是故障**，是当前真实上限：请求
    链路（cid→签名→列表→正文解析）已按登录态可用形态实现并全量 mock
    测试，未来接入 SESSDATA 即可直接出数据。

    on_error 协议同 fetch_video：成功返回 Dict；"report" 时错误返回 List
    （统一错误协议）；"raise"/"empty" 同款。
    """
    bvid = _extract_bvid(video)
    if not bvid:
        err = ValueError(f"invalid bvid: {video!r}")
        if on_error == "raise":
            raise err
        if on_error == "report":
            return [{"error": f"ValueError: {err}", "tool": _TOOL,
                     "query": video, "platform": _PLATFORM}]
        return []
    try:
        s = _get_session()
        # 1) view 拿 cid（顺带 title/owner 方便核对拿对了视频）
        _wait_turn()
        resp = s.get("https://api.bilibili.com/x/web-interface/view",
                     params={"bvid": bvid}, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise BilibiliApiError(
                f"view code={data.get('code')} "
                f"message={data.get('message')}")
        v = data.get("data") or {}
        cid = v.get("cid")
        if not cid:
            raise BilibiliApiError("view 响应无 cid（API 形态变化？）")
        # 2) player/wbi/v2 拿字幕列表（wbi 签名；wbi 键带 1h TTL 缓存）
        img_key, sub_key = _get_wbi_keys()
        _wait_turn()
        resp = s.get(_API_PLAYER,
                     params=_wbi_sign({"bvid": bvid, "cid": int(cid)},
                                      img_key, sub_key),
                     timeout=TIMEOUT)
        pdata = resp.json()
        if pdata.get("code") in RETRYABLE_CODES:
            # 与 search() 同款对称健壮性：wbi 键过期(-403)/风控(-412)时
            # 强制刷新密钥重试一次（审查 v3.9：原实现缺此路径）
            img_key, sub_key = _get_wbi_keys(force_refresh=True)
            _wait_turn()
            resp = s.get(_API_PLAYER,
                         params=_wbi_sign({"bvid": bvid, "cid": int(cid)},
                                          img_key, sub_key),
                         timeout=TIMEOUT)
            pdata = resp.json()
        if pdata.get("code") != 0:
            raise BilibiliApiError(
                f"player code={pdata.get('code')} "
                f"message={pdata.get('message')}")
        subs = (((pdata.get("data") or {}).get("subtitle") or {})
                .get("subtitles")) or []
        # 3) 逐个拉字幕正文（手动 CC 字幕 URL 访客可读；需要 Referer）
        out = []
        for st in subs:
            if not isinstance(st, dict):
                continue
            url = (st.get("subtitle_url") or "").strip()
            if url.startswith("//"):
                url = "https:" + url
            item = {
                "lan": st.get("lan", ""),
                "lan_doc": st.get("lan_doc", ""),
                "ai_type": st.get("ai_type", 0),
                "url": url,
                "lines": [],
                "line_count": 0,
            }
            if url:
                _wait_turn()
                r2 = s.get(url, timeout=TIMEOUT, headers={
                    "Referer": "https://www.bilibili.com/"})
                r2.raise_for_status()
                body = r2.json()
                item["lines"] = [
                    {"from": ln.get("from"), "to": ln.get("to"),
                     "content": (ln.get("content") or "")}
                    for ln in (body.get("body") or []) if isinstance(ln, dict)]
                item["line_count"] = len(item["lines"])
            out.append(item)
        return {
            "bvid": bvid,
            "cid": cid,
            "title": _clean_title(v.get("title", "")),
            "owner": (v.get("owner") or {}).get("name", ""),
            "has_subtitles": bool(out),
            "subtitles": out,
            "url": f"https://www.bilibili.com/video/{bvid}",
            "platform": _PLATFORM,
            "engine": "bilibili-api",
            # 空列表不是故障，note 把实测结论讲清楚，防调用方误判真空/故障
            "note": "" if out else
            "该视频字幕列表为空。实测（2026-09-16，3 视频验证）：未登录访客"
            "请求 subtitle 列表恒为空——B站仅向登录态（SESSDATA）下发字幕，"
            "手动 CC 亦不豁免；本工具不带登录态，非故障",
        }
    except Exception as e:
        if on_error == "raise":
            raise
        if on_error == "report":
            slug = getattr(e, "slug", None) or type(e).__name__
            return [{"error": f"{slug}: {e}", "tool": _TOOL,
                     "query": video, "platform": _PLATFORM}]
        return []
