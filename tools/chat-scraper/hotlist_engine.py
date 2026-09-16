#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""热榜聚合引擎 —— bilibili 热门/微博热搜（知乎热榜诚实上限）v3.30

定位：**无查询词的监控原语**（vendor 官宣/事件首发地监控、舆情雷达），
与 search() 的 query 语义不同构，故独立引擎 + 门面 hot() 路由 +
MCP china_hotlist 工具（bilibili_video 与 search 分工具同款先例）。

v3.30 增量（监控闭环补全 + cookie 寿命标定起步）:
    - hot_diff(before, after)：两轮采样 diff 纯函数（零网络）。榜单本身
      只是「正在发生」，两轮快照的**新增条目才是事件信号**（刚上榜 =
      正在发生的事）。架构推导：diff 是纯计算不是网络操作，落引擎层
      作纯函数（可离线钉测、可被任意监控环组合），不挂 hot() 参数
      （那会把两次采样焊死进一次调用，翻倍网络且无法控制采样间隔——
      监控节奏是调用方的事，toolbox 复用边界：监控告警不包含）。
      2026-09-17 真实演练：同 query 主题两轮采样（间隔 >=10 分钟），
      diff 实据见 CHANGELOG v3.30.0。
    - weibo_probe_once：微博访客 cookie 寿命标定单发探活（doctor 热榜
      探活项的引擎侧实现）。**禁 incarnate 纪律**（知乎 cookie_probe
      禁自愈同构）：只动用 state 缓存 cookie 真调一次 hotSearch，失效
      如实记 expired，绝不顺手续命——若探活即重领，每条 expired 都被
      续命污染，寿命分布永远测不出来（实际使用路径 hot() 的自动重领
      不受影响）。读数追加 state/weibo_cookie_lifetime_log.jsonl
      （独立 jsonl——仓库标定流先例：cookie_lifetime_log /
      sogou_recovery_log / sogou_throttle_log 各自独立流，互不混写；
      同日志带 platform 字段的方案被否：不同标定对象节奏/寿命/四态
      语义都不同，混写会让钩子活性检查无法按流判读数）。
      saved_at 自 v3.29 落盘自带——寿命标定起步的数据基座。

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
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests

try:  # 包内导入（同 search.py 双模式）
    from . import bilibili_engine as _bili
except ImportError:  # 扁平导入（sys.path 指向本目录）
    import bilibili_engine as _bili  # type: ignore

__all__ = ["hot", "hot_diff", "weibo_probe_once",
           "ZhihuHotlistNeedsLogin", "WeiboHotlistError",
           "WeiboHotlistAuthRejected"]

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
# v3.30: 微博访客 cookie 寿命标定读数（独立 jsonl，仓库标定流先例）
WEIBO_LIFETIME_LOG_PATH = os.path.join(_STATE_DIR,
                                       "weibo_cookie_lifetime_log.jsonl")
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


class WeiboHotlistAuthRejected(WeiboHotlistError):
    """hotSearch 明确拒绝访客身份（HTTP 401/403）——cookie 死亡信号。

    v3.30 细分：weibo_probe_once 据此把标定读数判 expired（寿命死亡的
    关键数据点），与 non-JSON 等页面形态异常（error 态）区分，不靠错误
    信息字符串猜。是 WeiboHotlistError 子类——hot() 的 except/重领流程
    与 report 协议行为不变（except 父类照常命中；slug 更精确到
    weibo_hotlist_auth_rejected，属错误分类学细化非行为变更）。
    """

    slug = "weibo_hotlist_auth_rejected"


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
        raise WeiboHotlistAuthRejected(
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


# ---------------------------------------------------------------------------
# 榜单 diff（v3.30：两轮采样的监控信号，纯函数零网络）
# ---------------------------------------------------------------------------
def _entry_key(row: Dict) -> Tuple[str, str]:
    """条目身份键：(platform, url)；url 缺失回退 title（防御脏数据）。

    url 在两条线都跨轮稳定：bilibili 是 bvid 视频 URL、微博是
    s.weibo.com 词检索 URL——同一热点的 URL 不随轮次变化，可作身份。
    """
    return (str(row.get("platform") or ""),
            str(row.get("url") or "") or str(row.get("title") or ""))


def _group_hot_rows(rows: Optional[List[Dict]]
                    ) -> Tuple[Dict[str, Dict[Tuple[str, str], Dict]],
                               Dict[str, Dict]]:
    """按平台分组有效榜单条目；error 记录（report 协议产物）不进组。

    返回 ({platform: {身份键: row}}, {platform: 首条 error 记录})。
    """
    groups: Dict[str, Dict[Tuple[str, str], Dict]] = {}
    errs: Dict[str, Dict] = {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        if "error" in r:
            errs.setdefault(str(r.get("platform") or "?"), r)
            continue
        p = str(r.get("platform") or "?")
        groups.setdefault(p, {})[_entry_key(r)] = r
    return groups, errs


def hot_diff(before: Optional[List[Dict]],
             after: Optional[List[Dict]]) -> Dict:
    """两轮热榜采样 diff（v3.30，纯函数零网络）——新增条目=事件信号。

    用法：调用方间隔 >=10 分钟做两轮 hot() 采样，本函数只算差集：

        rows1 = hot(platforms=["bilibili", "weibo"], num=20)
        # ... >=10 分钟 ...
        rows2 = hot(platforms=["bilibili", "weibo"], num=20)
        diff = hot_diff(rows1, rows2)

    架构推导（为何是纯函数而非 hot() 的 baseline 参数）：diff 是纯计算
    不是网络操作；baseline 参数会把两次采样焊死进一次调用（翻倍网络、
    无法控制采样间隔、监控节奏失去调用方主权）。引擎不存快照状态——
    快照落盘/周期调度是监控环调用方的事（toolbox 复用边界：监控告警
    不包含）。

    身份 = (platform, url)（url 跨轮稳定，见 _entry_key）。返回::

        {
          "new":  [row, ...]   # 后轮新增（after 子集，platform+rank 升序）
          "gone": [row, ...]   # 前轮有后轮无（before 子集，同序）
          "kept": int,         # 两轮都在的条目总数
          "platforms": {p: {"new": n, "gone": m, "kept": k}},
                               # 仅实际做了 diff 的平台
          "skipped_platforms": {p: 原因},
                               # 单侧无有效榜单的平台——整侧剔除不产信号
        }

    宁缺勿错：某平台单侧报错（on_error="report" 的 error 记录）或单侧
    未采样时，该平台**整侧剔除**进 skipped_platforms——否则前轮报错、
    后轮恢复会把全榜误报成「新增」的假事件信号。输入只读不改（纯函数，
    返回的 row 是原 dict 引用，不做拷贝不注字段）。
    """
    groups_b, errs_b = _group_hot_rows(before)
    groups_a, errs_a = _group_hot_rows(after)
    new_rows: List[Dict] = []
    gone_rows: List[Dict] = []
    kept = 0
    summary: Dict[str, Dict[str, int]] = {}
    skipped: Dict[str, str] = {}
    for p in sorted(set(groups_b) | set(groups_a)):
        b, a = groups_b.get(p), groups_a.get(p)
        if b is None or a is None:
            reasons = []
            if b is None:
                reasons.append("前轮" + ("该平台报错" if p in errs_b
                                          else "未采样该平台"))
            if a is None:
                reasons.append("后轮" + ("该平台报错" if p in errs_a
                                          else "未采样该平台"))
            skipped[p] = "；".join(reasons) + "——整侧剔除不产信号"
            continue
        new_keys = a.keys() - b.keys()
        gone_keys = b.keys() - a.keys()
        kept += len(a) - len(new_keys)
        summary[p] = {"new": len(new_keys), "gone": len(gone_keys),
                      "kept": len(a) - len(new_keys)}
        new_rows.extend(a[k] for k in new_keys)
        gone_rows.extend(b[k] for k in gone_keys)

    def _order(row: Dict):
        rank = row.get("rank")
        return (str(row.get("platform") or ""),
                rank if isinstance(rank, int) else 10 ** 9)

    new_rows.sort(key=_order)
    gone_rows.sort(key=_order)
    return {"new": new_rows, "gone": gone_rows, "kept": kept,
            "platforms": summary, "skipped_platforms": skipped}


# ---------------------------------------------------------------------------
# 微博访客 cookie 寿命标定（v3.30：单发探活读数，禁 incarnate 纪律）
# ---------------------------------------------------------------------------
def _append_jsonl(path: str, entry: Dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def weibo_probe_once(log_path: Optional[str] = WEIBO_LIFETIME_LOG_PATH,
                     tool: str = "hotlist_engine weibo_probe_once") -> Dict:
    """微博访客 cookie 寿命标定单发探活（doctor 热榜探活项的引擎侧实现）。

    标定纪律：**禁 incarnate**（知乎 cookie_probe 禁自愈同构，见模块
    docstring）——只动用 state 缓存 cookie 真调一次 hotSearch，失效如实
    记 expired，绝不续命；实际使用路径 hot() 的自动重领不受影响（探活
    归探活，使用归使用，两条路径互不污染）。

    读数四态（知乎 cookie_lifetime_log 同构）：
        valid   信封 ok=1（note 带 top1 词与条数）
        expired HTTP 401/403（WeiboHotlistAuthRejected 明确身份拒绝）或
                信封 ok!=1——cookie 死亡读数（寿命标定的关键数据点：
                死亡时刻的 cookie_age_h）
        missing 无缓存 cookie（零网络——不 incarnate 不烧 passport）
        error   non-JSON/网络等其他异常（不污染两类主读数）
    cookie 年龄从缓存 saved_at 起算（v3.29 落盘自带）。

    读数一行追加 log_path（默认 state/weibo_cookie_lifetime_log.jsonl；
    None 只测不落账，测试用）：
        {ts, tool, saved_at, cookie_age_h, status, note}
    返回该条读数 dict。
    """
    entry: Dict = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tool": tool,
        "saved_at": None,
        "cookie_age_h": None,
        "status": None,
        "note": "",
    }
    try:
        with open(_WEIBO_STATE_PATH, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        payload = {}
    saved_at = payload.get("saved_at")
    entry["saved_at"] = saved_at
    if saved_at:
        try:
            age_s = time.time() - datetime.strptime(
                str(saved_at), "%Y-%m-%d %H:%M:%S").timestamp()
            entry["cookie_age_h"] = round(age_s / 3600, 2)
        except (ValueError, TypeError, OSError):
            pass        # 坏 saved_at：龄读数为 None，不影响状态判定
    cookies = {str(k): str(v)
               for k, v in (payload.get("cookies") or {}).items()
               if k in ("SUB", "SUBP") and v}
    if not cookies:
        entry["status"] = "missing"
        entry["note"] = ("无缓存访客 cookie（missing != 过期；首次实际"
                         "使用时 hot() 会 incarnate 重领）")
    else:
        try:
            env = _call_hotsearch(cookies)
        except WeiboHotlistAuthRejected as e:   # HTTP 401/403 明确身份拒绝
            entry["status"] = "expired"
            entry["note"] = str(e)[:160]
        except Exception as e:           # non-JSON/网络等其他异常
            entry["status"] = "error"
            entry["note"] = f"{type(e).__name__}: {str(e)[:140]}"
        else:
            if env.get("ok") == 1:
                entry["status"] = "valid"
                realtime = (env.get("data") or {}).get("realtime") or []
                words = [str(i.get("word") or "") for i in realtime
                         if isinstance(i, dict) and i.get("word")
                         and not i.get("is_ad")]
                entry["note"] = (f"top1={words[0] if words else '?'} "
                                 f"rows={len(words)}")
            else:
                # 信封级失效（HTTP 200 但 ok!=1）= cookie 死亡同读数
                entry["status"] = "expired"
                entry["note"] = (f"信封 ok={env.get('ok')}（cookie 失效；"
                                 f"标定禁 incarnate 不续命）")
    if log_path:
        _append_jsonl(log_path, entry)
    return entry


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
