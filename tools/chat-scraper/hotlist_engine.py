#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""热榜聚合引擎 —— bilibili 热门/微博热搜（知乎热榜诚实上限）v3.29

定位：**无查询词的监控原语**（vendor 官宣/事件首发地监控、舆情雷达），
与 search() 的 query 语义不同构，故独立引擎 + 门面 hot() 路由 +
MCP china_hotlist 工具（bilibili_video 与 search 分工具同款先例）。

实测结论（2026-09-17 本机验证，v3.29 立项依据；逻辑探测预算 8 发）:
    - bilibili 热门: GET https://api.bilibili.com/x/web-interface/
      popular?ps=20&pn=1 **裸调即通**（连 buvid3 都不需要——对照搜索
      接口必须有 buvid3；探测 200 + code=0，20 条全结构化字段）。信封
      {code:0, data:{list:[...], no_more:bool}}；条目 bvid/title(HTML
      实体转义)/owner.name/stat.view|danmaku|like/pubdate/tname。热门页
      **无热度值字段**——如实不造 hot_value。分页 ps=20/pn=N，
      no_more=true 即到底。会话/节流复用 bilibili_engine（进程级单例，
      不重复领 buvid3）。
    - 微博热搜: weibo.com/ajax/side/hotSearch 需要访客身份。裸 UA 403
      （探测 #2）；m.weibo.cn container API 线 ok=-100 弹 passport 登录
      墙，首页只发 WEIBOCN_FROM 不够（探测 #5/#6）。本引擎走 passport
      **访客 incarnate 流**（纯 HTTP 两请求，无浏览器）：genvisitor POST
      领 tid -> incarnate GET 换 SUB/SUBP cookie，成功后缓存
      state/weibo_visitor_cookies.json 复用；信封 {ok:1, data:{realtime:
      [{word, num, label_name, is_ad, ...}]}}，is_ad=1 广告位剔除
      （bilibili 广告卡同款纪律），label_name 即 爆/热/新/沸 标签，
      num 为热搜热度值 -> hot_value。
    - 知乎热榜: **访客不可用（诚实上限，非故障）**。官方端点
      /api/v3/feed/topstory/hot-lists/total 裸调 401（探测 #1）；走
      zhihu_content cookie+签名线（自愈引导刚领的全套新访客 cookie +
      x-zse-96 签名）仍 401 code=101「身份未经过验证」（探测 #4）——
      端点需登录态。本引擎不带登录态（凭据线归主人），zhihu 平台位
      保留但恒报 zhihu_hotlist_needs_login，**不发任何网络请求**
      （不烧引导）。

用法:
    from hotlist_engine import hot
    rows = hot(platforms=["bilibili", "weibo"], num=20)

CLI:
    python hotlist_engine.py --platforms bilibili,weibo --num 20

错误协议（与仓库其他工具一致）:
    on_error="report"（默认）: 某平台出错时聚合结果里出现
        {"error": "zhihu_hotlist_needs_login: ...", "tool": "chat-scraper",
         "platform": "zhihu"}
    （热榜无查询词，错误记录不带 query 字段。）
    on_error="raise" 直接抛出; on_error="empty" 兼容旧行为返回 []。
"""
import argparse
import json
import os
import random
import sys
import threading
import time
from typing import Dict, List, Optional

import requests

try:  # 包内导入（同 search.py 双模式）
    from . import bilibili_engine as _bili
except ImportError:  # 扁平导入（sys.path 指向本目录）
    import bilibili_engine as _bili  # type: ignore

__all__ = ["hot", "ZhihuHotlistNeedsLogin", "WeiboHotlistError"]

_TOOL = "chat-scraper"
_ENGINE = "hotlist"
_STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
_ENV_WEIBO_MIN_INTERVAL = "CHAT_SCRAPER_WEIBO_MIN_INTERVAL"
TIMEOUT = 20                       # 单请求超时（秒）

_API_POPULAR = "https://api.bilibili.com/x/web-interface/popular"
_POPULAR_PAGE = 20                 # 实测服务端单页条数（ps=20 探测全额返回）
_POPULAR_MAX_PAGES = 5             # 翻页护栏：num 有效上限约 100 条

_API_HOTSEARCH = "https://weibo.com/ajax/side/hotSearch"
_PASSPORT_GEN = "https://passport.weibo.com/visitor/genvisitor"
_PASSPORT_INCARNATE = "https://passport.weibo.com/visitor/visitor"
_WEIBO_STATE_PATH = os.path.join(_STATE_DIR, "weibo_visitor_cookies.json")
_WEIBO_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36")

DEFAULT_PLATFORMS = ("bilibili", "weibo")
SUPPORTED_PLATFORMS = ("bilibili", "weibo", "zhihu")


class ZhihuHotlistNeedsLogin(RuntimeError):
    """知乎热榜端点需登录态（访客线实测死刑，见模块 docstring 探测 #1/#4）。"""

    slug = "zhihu_hotlist_needs_login"


class WeiboHotlistError(RuntimeError):
    """微博热搜访客流失败（incarnate 被拒 / 信封非 ok）。"""

    slug = "weibo_hotlist_error"


# ---------------------------------------------------------------------------
# bilibili 热门线（会话/节流复用 bilibili_engine，进程级单例）
# ---------------------------------------------------------------------------
def _hot_bilibili(num: int, vendor: str, role: str) -> List[Dict]:
    """bilibili 热门（官方 popular API，裸调即通）。

    num>20 自动翻页（护栏 5 页，有效上限约 100 条；页间走 bilibili_engine
    内置 _wait_turn 节流，no_more=true 或空页即停），跨页去重（v3.12 审查
    A1 同款）。热门页无热度值字段，如实不造 hot_value。
    """
    out: List[Dict] = []
    seen: set = set()
    if num <= 0:
        return out
    for pn in range(1, _POPULAR_MAX_PAGES + 1):
        _bili._wait_turn()
        s = _bili._get_session()
        resp = s.get(_API_POPULAR,
                     params={"ps": _POPULAR_PAGE, "pn": pn},
                     timeout=_bili.TIMEOUT)
        try:
            payload = resp.json()
        except ValueError as e:
            raise _bili.BilibiliApiError(
                f"popular non-JSON response HTTP {resp.status_code}: "
                f"{resp.text[:120]!r}") from e
        if payload.get("code") != 0:
            raise _bili.BilibiliApiError(
                f"popular code={payload.get('code')} "
                f"message={payload.get('message')}")
        data = payload.get("data") or {}
        items = data.get("list") or []
        for b in items:
            if not isinstance(b, dict):
                continue
            bvid = str(b.get("bvid") or "").strip()
            if not bvid:
                continue          # 无 bvid 的异常条目（广告卡同位素），丢弃
            if bvid in seen:
                continue          # 跨页去重（v3.12 审查 A1 同款）
            seen.add(bvid)
            stat = b.get("stat") or {}
            out.append({
                "rank": len(out) + 1,
                "title": _bili._clean_title(str(b.get("title") or "")),
                "url": f"https://www.bilibili.com/video/{bvid}",
                "platform": "bilibili",
                "engine": _ENGINE,
                "author": (b.get("owner") or {}).get("name") or "",
                "views": stat.get("view"),
                "danmaku": stat.get("danmaku"),
                "likes": stat.get("like"),
                "category": b.get("tname") or "",
                "pubdate": _bili._fmt_pubdate(int(b.get("pubdate") or 0)),
                "vendor": vendor,
                "role": role,
            })
            if len(out) >= num:
                return out
        if data.get("no_more") or not items:
            break                 # 排序穷尽/空页 = 如实停，不发多余请求
    return out


# ---------------------------------------------------------------------------
# 微博热搜线（passport 访客 incarnate 流，纯 HTTP 无浏览器）
# ---------------------------------------------------------------------------
_weibo_lock = threading.RLock()
_weibo_session: Optional[requests.Session] = None
_weibo_throttle_lock = threading.Lock()
_weibo_last_request_ts = 0.0


def _weibo_min_interval() -> float:
    """读取环境变量配置的最小请求间隔（秒），非法值回退默认。"""
    raw = os.environ.get(_ENV_WEIBO_MIN_INTERVAL, "")
    try:
        val = float(raw) if raw else 5.0
    except ValueError:
        return 5.0
    return val if val >= 0 else 5.0


def _weibo_wait_turn() -> None:
    """所有对外微博请求前调用: 保证与上一次间隔 >= min_interval。"""
    global _weibo_last_request_ts
    with _weibo_throttle_lock:
        wait = _weibo_last_request_ts + _weibo_min_interval() - \
            time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _weibo_last_request_ts = time.monotonic()


def _get_weibo_session() -> requests.Session:
    """懒加载进程级会话（trust_env=False 同仓库各引擎惯例）。"""
    global _weibo_session
    with _weibo_lock:
        if _weibo_session is None:
            s = requests.Session()
            s.trust_env = False
            s.headers.update({
                "User-Agent": _WEIBO_UA,
                "Referer": "https://weibo.com/",
            })
            _weibo_session = s
        return _weibo_session


def _load_weibo_state() -> Dict[str, str]:
    """读缓存的访客 cookie（无/坏文件返回空 dict，不抛）。"""
    try:
        with open(_WEIBO_STATE_PATH, encoding="utf-8") as f:
            payload = json.load(f)
        cookies = payload.get("cookies") or {}
        return {str(k): str(v) for k, v in cookies.items()
                if k in ("SUB", "SUBP") and v}
    except (OSError, ValueError):
        return {}


def _save_weibo_state(cookies: Dict[str, str]) -> None:
    """缓存 SUB/SUBP（写失败只打 stderr——缓存是优化不是依赖）。"""
    try:
        os.makedirs(_STATE_DIR, exist_ok=True)
        payload = {"cookies": cookies, "user_agent": _WEIBO_UA,
                   "saved_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        with open(_WEIBO_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(f"[hotlist_engine] weibo cookie 缓存写失败: {e}",
              file=sys.stderr)


def _parse_jsonp(text: str, prefix: str) -> Dict:
    """剥 JSONP 壳: "window.gen_callback && gen_callback({...});" -> {...}。

    实测壳形态带 window. 前缀与 && 短路表达式——只要求 prefix 出现在文中，
    取最外层括号内容解析（不假设壳的具体写法）。
    """
    t = (text or "").strip().rstrip(";")
    if prefix not in t:
        raise WeiboHotlistError(
            f"passport JSONP 壳异常: {text[:120]!r}")
    i, j = t.find("("), t.rfind(")")
    if i < 0 or j <= i:
        raise WeiboHotlistError(
            f"passport JSONP 无括号体: {text[:120]!r}")
    try:
        return json.loads(t[i + 1:j])
    except ValueError as e:
        raise WeiboHotlistError(
            f"passport JSONP 非 JSON: {text[:120]!r}") from e


def _incarnate_weibo_visitor() -> Dict[str, str]:
    """passport 访客 incarnate 流：genvisitor 领 tid -> incarnate 换
    SUB/SUBP cookie（纯 HTTP 两请求，无浏览器）。失败抛 WeiboHotlistError。
    """
    s = _get_weibo_session()
    _weibo_wait_turn()
    fp = json.dumps({
        "os": "1",
        "browser": "Chrome152,0,0,0",
        "fonts": "undefined",
        "screenInfo": "1920*1080*30",
        "plugins": "undefined",
    }, separators=(",", ":"))
    try:
        resp = s.post(_PASSPORT_GEN,
                      data={"cb": "gen_callback", "fp": fp},
                      timeout=TIMEOUT)
    except requests.RequestException as e:
        raise WeiboHotlistError(f"genvisitor 网络失败: {e}") from e
    gen = _parse_jsonp(resp.text, "gen_callback")
    tid = (gen.get("data") or {}).get("tid")
    if gen.get("retcode") != 20000000 or not tid:
        raise WeiboHotlistError(
            f"genvisitor 被拒: retcode={gen.get('retcode')} "
            f"msg={gen.get('msg')}")
    _weibo_wait_turn()
    try:
        resp = s.get(_PASSPORT_INCARNATE, params={
            "a": "incarnate", "t": tid, "w": "2", "c": "095", "gc": "",
            "cb": "cross_domain", "from": "weibo",
            "_rand": str(random.random()),
        }, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise WeiboHotlistError(f"incarnate 网络失败: {e}") from e
    inc = _parse_jsonp(resp.text, "cross_domain")
    data = inc.get("data") or {}
    sub, subp = data.get("sub"), data.get("subp")
    if inc.get("retcode") != 20000000 or not sub or not subp:
        raise WeiboHotlistError(
            f"incarnate 被拒: retcode={inc.get('retcode')} "
            f"msg={inc.get('msg')}")
    return {"SUB": sub, "SUBP": subp}


def _call_hotsearch(cookies: Dict[str, str]) -> Dict:
    """调热搜接口（节流），返回信封 dict。"""
    s = _get_weibo_session()
    _weibo_wait_turn()
    resp = s.get(_API_HOTSEARCH, cookies=cookies, timeout=TIMEOUT)
    if resp.status_code in (401, 403):
        raise WeiboHotlistError(
            f"hotSearch HTTP {resp.status_code}（访客身份被拒，"
            f"cookie 可能失效）: {resp.text[:120]!r}")
    try:
        return resp.json()
    except ValueError as e:
        raise WeiboHotlistError(
            f"hotSearch non-JSON HTTP {resp.status_code}: "
            f"{resp.text[:120]!r}") from e


def _hot_weibo(num: int, vendor: str, role: str) -> List[Dict]:
    """微博热搜（ajax/side/hotSearch + 访客 incarnate cookie）。

    cookie 策略：先试 state 缓存 -> 失效则 incarnate 一次并重试一次 ->
    仍失败如实抛（不无限重试）。is_ad=1 广告位剔除（宁缺勿错）。
    """
    if num <= 0:
        return []
    with _weibo_lock:
        cookies = _load_weibo_state()
        fresh = False
        try:
            payload = _call_hotsearch(cookies) if cookies else None
        except WeiboHotlistError:
            payload = None           # 缓存失效 -> 走 incarnate 重领
        if payload is None:
            cookies = _incarnate_weibo_visitor()
            _save_weibo_state(cookies)
            fresh = True
            payload = _call_hotsearch(cookies)
        if payload.get("ok") != 1 and not fresh:
            # 信封级失效（HTTP 200 但 ok!=1，同 401/403 处置）：重领一次再试
            cookies = _incarnate_weibo_visitor()
            _save_weibo_state(cookies)
            fresh = True
            payload = _call_hotsearch(cookies)
        if payload.get("ok") != 1:
            # 刚 incarnate 还失败 = 真被拒，如实抛（不无限重试）
            raise WeiboHotlistError(
                f"hotSearch ok={payload.get('ok')} "
                f"(fresh_incarnate={fresh})")
        realtime = (payload.get("data") or {}).get("realtime") or []
        out: List[Dict] = []
        for item in realtime:
            if not isinstance(item, dict):
                continue
            if item.get("is_ad"):
                continue             # 广告位剔除（宁缺勿错，如实少一条）
            word = str(item.get("word") or "").strip()
            if not word:
                continue
            scheme = str(item.get("word_scheme") or f"#{word}#")
            out.append({
                "rank": len(out) + 1,
                "title": word,
                "url": ("https://s.weibo.com/weibo?q="
                        + requests.utils.quote(scheme)),
                "platform": "weibo",
                "engine": _ENGINE,
                "hot_value": item.get("num"),
                "label": str(item.get("label_name") or ""),
                "vendor": vendor,
                "role": role,
            })
            if len(out) >= num:
                break
        return out


# ---------------------------------------------------------------------------
# 知乎热榜线（诚实上限：零网络请求）
# ---------------------------------------------------------------------------
def _hot_zhihu(num: int, vendor: str, role: str) -> List[Dict]:
    """知乎热榜：访客不可用（实测 401 code=101，见模块 docstring）。

    不发任何网络请求（不烧引导）——直接报诚实错误，由 hot() 按错误协议
    记录。端点形态/登录态接入留待凭据线（归主人）。
    """
    raise ZhihuHotlistNeedsLogin(
        "官方热榜端点 /api/v3/feed/topstory/hot-lists/total 需登录态——"
        "2026-09-17 实测：裸调 401；zhihu_content 签名线（自愈引导刚刷新"
        "的全套新访客 cookie + x-zse-96 签名）仍 401 code=101「身份未经"
        "验证」。本引擎不带登录态（凭据线归主人），此为诚实上限非故障")


_FETCHERS = {
    "bilibili": _hot_bilibili,
    "weibo": _hot_weibo,
    "zhihu": _hot_zhihu,
}


def hot(platforms: Optional[List[str]] = None, num: int = 10,
        vendor: str = "?", role: str = "primary",
        on_error: str = "report") -> List[Dict]:
    """热榜聚合（无查询词）：按平台取榜单前 num 条，顺序聚合。

    Args:
        platforms: 平台名列表（bilibili/weibo/zhihu）。
            None/空 -> DEFAULT_PLATFORMS（bilibili+weibo，实测可用集）。
            zhihu 可显式传入但恒报 zhihu_hotlist_needs_login（诚实上限，
            零网络请求）；未知平台报 ValueError。
        num: 每个平台的返回条数上限
        vendor: 主题分类（指标用，透传）
        role: primary / fallback / verify（透传）
        on_error: "report"（默认）/ "raise" / "empty"（见模块 docstring）

    Returns:
        [{rank, title, url, platform, engine, ...平台特有字段, vendor,
          role}, ...]；出错平台按 on_error 协议处理（report 时错误记录
        带 platform 无 query——热榜无查询词）。
    """
    names: List[str] = []
    for p in (platforms or DEFAULT_PLATFORMS):
        name = str(p).strip().lower()
        if name and name not in names:
            names.append(name)
    if not names:
        names = list(DEFAULT_PLATFORMS)
    for name in names:
        if name not in _FETCHERS:
            raise ValueError(
                f"unknown hotlist platform {name!r}; "
                f"supported: {', '.join(SUPPORTED_PLATFORMS)}")

    rows: List[Dict] = []
    for name in names:
        try:
            rows.extend(_FETCHERS[name](num, vendor, role))
        except Exception as e:  # noqa: BLE001 —— 按错误协议分流
            if on_error == "raise":
                raise
            if on_error == "report":
                slug = getattr(e, "slug", None) or type(e).__name__
                rows.append({"error": f"{slug}: {e}", "tool": _TOOL,
                             "platform": name})
            # on_error == "empty": 静默跳过故障平台
    return rows


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="热榜聚合（bilibili 热门/微博热搜；知乎诚实上限）")
    parser.add_argument("--platforms", default=None,
                        help="逗号分隔平台名，如 bilibili,weibo；"
                             "省略为默认可用集")
    parser.add_argument("--num", type=int, default=10)
    parser.add_argument("--vendor", default="?")
    parser.add_argument("--role", default="primary")
    parser.add_argument("--on-error", default="report",
                        choices=["report", "raise", "empty"])
    args = parser.parse_args()
    platforms = ([p for p in args.platforms.split(",") if p.strip()]
                 if args.platforms else None)
    rows = hot(platforms=platforms, num=args.num, vendor=args.vendor,
               role=args.role, on_error=args.on_error)
    errors = [r for r in rows if "error" in r]
    if errors:
        for r in errors:
            print(f"[hotlist_engine] error ({r.get('platform', '?')}): "
                  f"{r['error']}", file=sys.stderr)
        return 1
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
