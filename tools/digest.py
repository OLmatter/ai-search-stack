#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""每日晨报聚合（v3.33；v3.34~v3.40 增量见下）——五段组合一次早晨
汇报，stdout markdown。

v3.40 增量（厂商 RSS 动态段）: 第五段「厂商动态（RSS）」——vendor 官宣
第一方信号此前零自动覆盖（HN watch_queries 只接社区讨论、GitHub releases
只接代码发布、热榜只接中文回声）。watch_feeds 配置 RSS/Atom URL 列表，
每源一发抓取 + stdlib xml 解析（RSS 2.0 item / Atom entry 双形态，无法
识别的形态按段故障如实报不伪装成真空）+ seen 状态
（state/digest_feed_seen.json，链接身份，每源保留 FEED_SEEN_MAX 条）
diff 出新增——首轮建基线不洪水（hotlist_watch 建基线同款语义）。
seen 状态是承重态：写不进去该段 fault（监控环失明同构）。
模板默认只收**实测验证过**的源（2026-09-17 实测 openai.com/news/rss.xml
HTTP 200 RSS 2.0；anthropic 无 RSS 两路径均 HTML 错误页、DeepMind/Meta/
HF 本机网络不可达、机器之心 /rss 已 302 下线——未实测的源不入模板，
诚实文档原则）。本段纯 stdlib（urllib + xml.etree）；feed URL 来自
本地配置文件（非任意输入），实体展开风险面受控并有 _FEED_BODY_MAX
读取上限护栏。

v3.36 增量（解码链收口）: _decode_out 链身共享 tools/_subproc_decode.py
（toast.py 同步改 import；re-export 别名保旧引用名与函数对象身份一致，
行为零变化——四方副本收口史见该模块 docstring）。

v3.35 增量（toast 通道提取为公用模块）: --toast 的弹窗通道
（send_toast 及其常量/转义/解码链）提取到 tools/toast.py 公用模块——
hotlist_watch.py 监控环同批接入 --toast（diff 出新增条目即时弹窗，不等
10:00 晨报）。本文件改为 from toast import 并 re-export 旧引用名
（send_toast/TOAST_*/_decode_out 等），函数体逐字节迁移零行为变化。

v3.34 增量（配置模板入库 + --toast 本机通知）:
    - tools/digest_config.example.json 模板入库：用户配置**缺失**时自动
      用模板当默认值（零配置可跑且默认值有形可改——复制模板到
      state/digest_config.json 即接管），模板也缺失才落代码内置常量；
      三层落回都会在晨报头部注明。仅「文件缺失」走模板层——坏 JSON/键
      类型错仍按 v3.33 语义落内置默认（配置写坏不该被模板掩盖）。
    - --toast 可选参数：晨报产出后弹 Windows 本机通知（标题=完成/故障
      + 段状态，正文含热榜新增条目摘要）。通道选型（活体取证定案）：
      * BurntToast：要 PSGallery 装模块=外部服务，拒；
      * msg.exe：对话框无自动超时（无人值守会堆积）+ Home 版缺失，拒；
      * WinRT toast（PowerShell 投影）：平台级零依赖可用，但实机双闸
        取证（2026-09-17）：全局 toast banner 开关 ToastEnabled=0 +
        SHQueryUserNotificationState=QN_QUIET_TIME（专注助手开）——
        弹三发 API 全成功屏上零可见（截图存 .scratch/），只进操作中心
        且专注助手是 WNF 会话态不可靠改；不选为主通道；
      * **WScript.Shell Popup（采用）**：powershell COM 内联单进程，
        64(信息图标)+4096(系统模态置顶)+自动超时——零模块零外部服务零
        凭据零临时文件，不受通知设置/专注助手任何影响，实机截图证据
        （专注助手开着仍清晰可见，超时自关 POPUP_RET=-1）。
      通知是尽力而为观测：失败只 stderr warn，绝不翻晨报退出码。

定位（组合层归属推导，v3.33 评估结论）：晨报是**纯组合**（零新引擎能
力，全部复用既有通道原语），归调用方层组合脚本——hotlist_watch.py v3.31
完全同构先例（引擎零改动，ARCHITECTURE.md 复用边界：监控告警/组合不进
toolbox 引擎与 MCP）。二选一评估：
    - mcp_server 新工具：拒绝——晨报价值主体是「每日定时主动产生」，
      MCP 工具是会话内被动拉取原语且无定时能力，整份 markdown 进工具
      输出烧 LLM 上下文；同一组合逻辑双入口=双真源漂移。
    - 班次脚本：拒绝——聚合是确定性动作（固定通道/固定渲染/零认知），
      v3.31 已确立接线推导：确定性节拍归 OS 调度器，不占 LLM 班次上下
      文。班次是晨报的**消费者**（读 stdout / shift_log），不是执行者。
    - tools/digest.py 独立组合脚本：采用。跨工具组合（chat-scraper +
      hackernews + github + doctor 本地状态）放 tools/ 顶层，doctor.py
      同级先例（doctor 也是跨工具组合，_sys_path_chat_scraper 注入
      sys.path）；每日节拍由 digest_task.py 注册成 schtasks（参照
      hotlist_watch_task.py v3.31 模式）。

四段（每段独立 try/except + 通道 on_error="report" 双保险——单通道挂
只降级为该段「通道异常」，不炸整体；全段 fault 才 exit 1）：
    1. 热榜动态（默认零网络）：消费 hotlist_watch 监控环产物——
       latest_snapshot() 最新快照 top 行 + state/shift_log.md 今日
       `hotlist_watch:` diff 行。**不自己采样不落快照**——digest 是聚合
       汇报不是第二个监控环，现场采样会重复花预算且参与快照链节奏；
       快照缺失诚实说明（监控环未启用）不代采。`--sample-hotlist` 备用
       路径现场采样一发展示（仍不落快照）。
    2. 技术社区信号：watch_queries 每条 hn_search 一发（Algolia，
       on_error="report"）。
    3. 关注项目发布：watch_repos 每仓库 github_releases 一发
       （on_error="report"）。
    4. 厂商动态（RSS）：watch_feeds 每源一发抓取解析 + seen diff
       （v3.40；vendor 官宣第一方信号，首轮建基线不洪水）。
    5. 工具箱状态（零网络）：doctor 本地状态——shift_log 近 7 天统计
       （复用 doctor._shift_log_stats，跨解析器契约 test_v3310 同款钉
       法）、知乎 cookie 龄（doctor._cookie_meta）、weibo cookie 最后
       标定读数（doctor._last_valid_entry）、热榜快照链份数。
       **不跑 doctor 全量巡检**（那是 5+ 发网络，晨报嵌它会爆预算；
       全量巡检仍是 doctor 独立命令/班次的活）。

配置 state/digest_config.json（根 .gitignore `state/` 全局忽略，只留
本地）:
    {"watch_repos": ["owner/repo", ...],
     "watch_queries": ["关键词", ...],
     "watch_platforms": ["bilibili", "weibo"],
     "watch_feeds": ["https://.../rss.xml", ...]}
文件缺失 → 落回仓库模板 tools/digest_config.example.json（v3.34），
模板也缺 → 代码内置默认；坏 JSON/键类型不对 → 内置默认。落回层级
在晨报头部注明（配置问题不炸整体）。

网络预算（默认配置 2 查询 + 2 仓库 + 1 feed）：5 发；快照缺失仍 5 发；
--sample-hotlist 再 +2（bilibili+weibo 各一）。晨报实测 ≤9。

退出码: 0 = 晨报已产出（段「通道异常」是观测内容不翻码）；1 = 全部段
fault（整份晨报零有效内容，cron 侧可报警）。

测试纪律：hn_fetcher / releases_fetcher / config_loader / now 均可注入
（run_digest 参数），回归钉全离线——真实链路走 digest 实测落 CHANGELOG。
"""
import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

# 弹窗通道公用模块（v3.35 自本文件提取；re-export 保旧引用名零漂移——
# 通道选型取证/契约/常量见 toast.py docstring）
from toast import (TOAST_BOX_TYPE, TOAST_SUBPROC_TIMEOUT, TOAST_TIMEOUT_S,
                   _decode_out, _default_toast_runner, _ps_quote,
                   send_toast)
from toast import TOAST_BODY_MAX as _TOAST_BODY_MAX

import _logfmt   # shift_log 行格式单一真源（v3.38 四方收口，同目录）

__version__ = "3.42.0"

_TOOL = "digest"
HERE = Path(__file__).resolve().parent
DEFAULT_CONFIG = HERE / "state" / "digest_config.json"
EXAMPLE_CONFIG = HERE / "digest_config.example.json"
DEFAULT_SHIFT_LOG = HERE / "chat-scraper" / "state" / "shift_log.md"
DEFAULT_SNAPSHOTS = HERE / "chat-scraper" / "state" / "hotlist_snapshots"
DEFAULT_FEED_SEEN = HERE / "state" / "digest_feed_seen.json"

# 内置默认关注列表（配置缺失/坏时落回；守护 ai-search-stack 自身生态 +
# 两条通用信号词；平台默认双平台——预算口径 2 查询 + 2 仓库 + 1 feed
# = 5 发）
DEFAULT_REPOS = ["anthropics/claude-code", "microsoft/vscode"]
DEFAULT_QUERIES = ["LLM agent", "AI search"]
DEFAULT_PLATFORMS = ["bilibili", "weibo"]
# 只收实测验证过的源（2026-09-17 实测 200 RSS 2.0；未验证的源不入库——
# 取证记录见模块 docstring v3.40 段）
DEFAULT_FEEDS = ["https://openai.com/news/rss.xml"]

TOP_N = 3                # 每段展示行数
HN_NUM = 5               # 每条查询 HN 行数
REL_NUM = 3              # 每仓库 release 行数
SNAP_TOP_N = 5           # 快照 top 展示行数
FEED_NUM = 5             # 每 feed 新增展示行数
FEED_PARSE_MAX = 20      # 每 feed 解析条目上限（openai feed 实测 730KB 大源）
FEED_TIMEOUT_S = 20      # 单 feed 抓取超时
FEED_SEEN_MAX = 200      # seen 状态每源保留链接数
_FEED_BODY_MAX = 2_000_000  # 响应读取上限（护栏；openai 实测 ~730KB）
_DIFF_LINE_MAX = 500     # --log 一行上限（班次流水不刷屏，hotlist_watch 同款）

# shift_log 里 hotlist_watch 产出行的形态（v3.38 起前缀片段收口
# _logfmt.STAMP_RE 合成——与写入端 hotlist_watch.render_log_line、解析
# 端 doctor._shift_log_stats 同源；固定前缀 `[YYYY-MM-DD HH:MM]
# hotlist_watch: `——跨解析器契约的消费端，v3.31 test 跨解析器钉死供方，
# 这里钉消费）。v3.39 起「匹配 + 今日过滤」双条件消费语义走
# _logfmt.parse_today_lines()（本正则作 line_re 注入，group(1)=日期
# group(2)=内容），digest 只保留行截断展示策略。
_WATCH_LINE_RE = re.compile(rf"^{_logfmt.STAMP_RE} (hotlist_watch: .*)$")

_paths_ready = False


def _ensure_paths() -> None:
    """把 hackernews / github / chat-scraper 目录注入 sys.path（一次性；
    doctor._sys_path_chat_scraper 同款先例——跨目录组合脚本不装包）。"""
    global _paths_ready
    if _paths_ready:
        return
    for sub in ("hackernews", "github", "chat-scraper"):
        p = str(HERE / sub)
        if p not in sys.path:
            sys.path.insert(0, p)
    _paths_ready = True


# ---------------------------------------------------------------------------
# 配置（缺失/坏 → 内置默认 + 注明；配置问题不炸整体）
# ---------------------------------------------------------------------------
def load_config(path: Optional[str] = None,
                loader: Optional[Callable[[Path], str]] = None
                ) -> Dict:
    """读晨报配置，返回 (config dict 形态统一) 的 dict + config_note。

    三层回退（v3.34）：用户配置**文件缺失** → 仓库模板
    digest_config.example.json → 代码内置常量；坏 JSON/顶层非 dict/键
    类型不对 → 内置默认（不落模板——配置写坏不该被模板静默掩盖）。note
    如实说明落回哪层——晨报永远出得来。loader 可注入（测试离线）。
    """
    def _read(f: Path) -> str:
        return (loader or (lambda fp: fp.read_text(encoding="utf-8")))(f)

    p = Path(path) if path else DEFAULT_CONFIG
    note = ""
    raw = None
    try:
        raw = _read(p)
    except OSError as e:
        # 文件缺失（仅此一档）走模板层：默认值有形可改，模板=活文档
        try:
            raw = _read(EXAMPLE_CONFIG)
            note = (f"配置未找到（{type(e).__name__}），"
                    "使用仓库模板默认（digest_config.example.json）")
        except Exception:                        # noqa: BLE001 —— 模板也缺
            note = f"配置未找到（{type(e).__name__}），使用内置默认"
    except Exception as e:                       # noqa: BLE001 —— 同上降级
        note = f"配置读取异常（{type(e).__name__}: {e}），使用内置默认"
    if raw is not None:
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError("顶层不是 JSON object")
        except ValueError as e:
            note = f"配置解析失败（{e}），使用内置默认"
        else:
            cfg = {}
            for key, default, typ in (
                    ("watch_repos", DEFAULT_REPOS, list),
                    ("watch_queries", DEFAULT_QUERIES, list),
                    ("watch_platforms", DEFAULT_PLATFORMS, list),
                    ("watch_feeds", DEFAULT_FEEDS, list)):
                v = data.get(key, default)
                if isinstance(v, list) and all(isinstance(x, str) for x in v):
                    cfg[key] = [x for x in v if x.strip()]
                else:
                    cfg[key] = default
                    note = (note or "") + f"{key} 类型不对落回默认；"
            return {"config": cfg, "note": note.strip()}
    return {"config": {"watch_repos": list(DEFAULT_REPOS),
                       "watch_queries": list(DEFAULT_QUERIES),
                       "watch_platforms": list(DEFAULT_PLATFORMS),
                       "watch_feeds": list(DEFAULT_FEEDS)},
            "note": note}


# ---------------------------------------------------------------------------
# 各段采集（每段独立失败降级：异常 → 该段 fault，不炸整体）
# ---------------------------------------------------------------------------
def _default_hn_fetcher(q: str, num: int) -> List[Dict]:
    _ensure_paths()
    from hackernews_client import search          # noqa: 延迟导入可注入
    return search(q=q, num=num, since="24h", on_error="report")


def _default_releases_fetcher(repo: str, num: int) -> List[Dict]:
    _ensure_paths()
    from github_client import get_releases        # noqa: 延迟导入可注入
    return get_releases(repo, num=num, on_error="report")


def _default_hotlist_sampler(platforms: List[str],
                             num: int) -> List[Dict]:
    _ensure_paths()
    import hotlist_engine as hl
    return hl.hot(platforms=platforms, num=num, on_error="report")


def fetch_hn(queries: List[str], num: int = HN_NUM,
             fetcher: Optional[Callable[[str, int], List[Dict]]] = None
             ) -> Dict:
    """HN 段：每条查询一发，返回 {status, queries: [{q, rows|error}]}。"""
    fn = fetcher or _default_hn_fetcher
    out = {"status": None, "queries": []}
    faults = 0
    for q in queries:
        try:
            rows = fn(q, num)
            err = rows[0].get("error") if (rows and isinstance(rows[0], dict)
                                           and "error" in rows[0]) else None
            if err:
                faults += 1
                out["queries"].append({"q": q, "error": str(err)[:200]})
            else:
                out["queries"].append({"q": q, "rows": rows[:num]})
        except Exception as e:                    # noqa: BLE001 —— 段降级
            faults += 1
            out["queries"].append(
                {"q": q, "error": f"{type(e).__name__}: {e}"[:200]})
    out["status"] = "fault" if faults == len(queries) and queries else "ok"
    return out


def fetch_releases(repos: List[str], num: int = REL_NUM,
                   fetcher: Optional[Callable[[str, int], List[Dict]]] = None
                   ) -> Dict:
    """GitHub 段：每仓库一发，返回 {status, repos: [{repo, rows|error}]}。"""
    fn = fetcher or _default_releases_fetcher
    out = {"status": None, "repos": []}
    faults = 0
    for repo in repos:
        try:
            rows = fn(repo, num)
            err = rows[0].get("error") if (rows and isinstance(rows[0], dict)
                                           and "error" in rows[0]) else None
            if err:
                faults += 1
                out["repos"].append({"repo": repo, "error": str(err)[:200]})
            else:
                out["repos"].append({"repo": repo, "rows": rows[:num]})
        except Exception as e:                    # noqa: BLE001 —— 段降级
            faults += 1
            out["repos"].append(
                {"repo": repo, "error": f"{type(e).__name__}: {e}"[:200]})
    out["status"] = "fault" if faults == len(repos) and repos else "ok"
    return out


def _default_feeds_fetcher(url: str) -> str:
    """抓一个 RSS/Atom 源，返回响应文本（读取上限 _FEED_BODY_MAX 护栏）。"""
    req = urllib.request.Request(
        url, headers={"User-Agent": f"ai-search-stack/{__version__}"})
    with urllib.request.urlopen(req, timeout=FEED_TIMEOUT_S) as r:
        return r.read(_FEED_BODY_MAX).decode("utf-8", "replace")


def parse_feed(xml_text: str) -> List[Dict]:
    """解析 RSS 2.0 / Atom 文本 → [{title, url, date}, ...]（cap
    FEED_PARSE_MAX；url 是条目身份，无链接条目跳过）。

    只支持 RSS 2.0（channel/item）与 Atom（feed/entry）；两类元素都不在
    → ValueError（无法识别的形态如实报故障，不伪装成「0 条真空」）。
    解析失败（坏 XML）同样抛 ValueError——调用方按段故障降级。
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ValueError(f"XML 解析失败: {e}") from e
    items: List[Dict] = []
    local = root.tag.rsplit("}", 1)[-1]
    if local == "rss":                            # RSS 2.0: channel/item
        nodes = root.findall("./channel/item")
        for it in nodes:
            url = (it.findtext("link") or "").strip()
            if not url:
                continue
            items.append({"title": (it.findtext("title") or "").strip(),
                          "url": url,
                          "date": (it.findtext("pubDate") or "").strip()})
    elif local == "feed":                         # Atom: entry
        nodes = root.findall("{*}entry")
        for it in nodes:
            link = it.find("{*}link")
            url = (link.get("href") if link is not None else "") or ""
            url = url.strip()
            if not url:
                continue
            items.append({"title": (it.findtext("{*}title") or "").strip(),
                          "url": url,
                          "date": (it.findtext("{*}updated")
                                   or it.findtext("{*}published") or "").strip()})
    else:
        raise ValueError(f"无法识别的 feed 形态（根元素 {local!r}，"
                         "支持 RSS 2.0/Atom）")
    if not items:
        raise ValueError("feed 中无可识别条目（RSS item/Atom entry 均缺）")
    return items[:FEED_PARSE_MAX]


def _load_seen(path: Optional[str]) -> Dict:
    """读 seen 状态 {feed_url: [链接...]};缺失/坏按空处理（下轮建基线）。"""
    p = Path(path) if path else DEFAULT_FEED_SEEN
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_seen(data: Dict, path: Optional[str]) -> None:
    p = Path(path) if path else DEFAULT_FEED_SEEN
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                 encoding="utf-8")


def fetch_feeds(feeds: List[str],
                fetcher: Optional[Callable[[str], str]] = None,
                seen_path: Optional[str] = None) -> Dict:
    """厂商 RSS 段：每源一发，返回 {status, feeds: [{url, new|error,
    baseline?|new_n?|seen_n?}], error?}。

    - 首轮（seen 无该源）= 建基线：本轮条目全部计入 seen、new=[]、
      baseline=N（hotlist_watch 建基线同款语义——不洪水告警）。
    - seen 状态是承重态：写失败 → 整段 fault（监控环失明同构）。
    - status 语义与 HN/GitHub 段一致：全部源 fault 才段 fault；空列表
      = "empty"（未配置，诚实不算故障）。
    """
    fn = fetcher or _default_feeds_fetcher
    out: Dict = {"status": None, "feeds": []}
    if not feeds:
        out["status"] = "empty"
        return out
    seen = _load_seen(seen_path)
    faults = 0
    for url in feeds:
        entry: Dict = {"url": url}
        try:
            items = parse_feed(fn(url))
        except Exception as e:                    # noqa: BLE001 —— 段降级
            faults += 1
            entry["error"] = f"{type(e).__name__}: {e}"[:200]
            out["feeds"].append(entry)
            continue
        known = set(seen.get(url) or [])
        entry["seen_n"] = len(known)
        if not known:
            entry["baseline"] = len(items)        # 首轮建基线，不洪水
            entry["new"] = []
            entry["items"] = items[:FEED_NUM]     # 基线轮展示源顶样目
        else:
            fresh = [it for it in items if it["url"] not in known]
            entry["new_n"] = len(fresh)
            entry["new"] = fresh[:FEED_NUM]
        merged = list(dict.fromkeys(
            (seen.get(url) or []) + [it["url"] for it in items]))
        seen[url] = merged[-FEED_SEEN_MAX:]
        out["feeds"].append(entry)
    try:
        _save_seen(seen, seen_path)
    except OSError as e:
        out["status"] = "fault"
        out["error"] = f"seen 状态写失败（OSError: {e})"[:200]
        return out
    out["status"] = "fault" if faults == len(feeds) else "ok"
    return out


def fetch_hotlist(snapshots_dir: Optional[str] = None,
                  shift_log: Optional[str] = None,
                  today: Optional[datetime] = None,
                  platforms: Optional[List[str]] = None,
                  sample: bool = False,
                  sampler: Optional[Callable[..., List[Dict]]] = None
                  ) -> Dict:
    """热榜段：默认零网络消费监控环产物；sample=True 现场采样一发（仍不
    落快照——digest 不是监控环，不参与快照链）。

    返回 {status, snapshot_ts, snapshot_path, top: [...], watch_lines:
    [...], platforms_note, error?}。快照缺失且未 sample → status="empty"
    （诚实说明，不算 fault——监控环未启用是常态不是晨报故障）。
    """
    _ensure_paths()
    import hotlist_watch as hw
    d = today or datetime.now()
    out: Dict = {"status": None, "snapshot_ts": None, "snapshot_path": None,
                 "top": [], "watch_lines": [], "platforms_note": None}
    # 1) shift_log 今日 diff 行（消费 hotlist_watch 班次日志产出）
    log = Path(shift_log) if shift_log else DEFAULT_SHIFT_LOG
    try:
        text = log.read_text(encoding="utf-8") if log.is_file() else ""
    except OSError:
        text = ""
    today_s = d.strftime("%Y-%m-%d")
    # 今日 diff 行：解析+日期过滤双条件走 _logfmt.parse_today_lines
    # （v3.39 下沉——行级契约单一真源），digest 只保留截断展示策略
    out["watch_lines"] = [s[:_DIFF_LINE_MAX] for s in
                          _logfmt.parse_today_lines(text, today_s,
                                                    _WATCH_LINE_RE)]
    # 2) 最新快照 top 行
    snap_dir = snapshots_dir or str(DEFAULT_SNAPSHOTS)
    prev = hw.latest_snapshot(snap_dir)
    if prev is not None:
        path, payload = prev
        out["snapshot_path"], out["snapshot_ts"] = path, payload.get("ts")
        plats = set(platforms or DEFAULT_PLATFORMS)
        rows = [r for r in (payload.get("rows") or [])
                if isinstance(r, dict) and "error" not in r
                and r.get("platform") in plats]
        rows.sort(key=lambda r: (r.get("platform", ""), r.get("rank", 0)))
        out["top"] = [{k: r.get(k) for k in
                       ("platform", "rank", "title", "url")}
                      for r in rows[:SNAP_TOP_N]]
        out["status"] = "ok"
        return out
    if sample:                                    # 备用路径：现场采样一发
        fn = sampler or _default_hotlist_sampler
        try:
            rows = fn(list(platforms or DEFAULT_PLATFORMS), 20)
            errs = [r for r in rows if isinstance(r, dict) and "error" in r]
            valid = [r for r in rows if isinstance(r, dict)
                     and "error" not in r]
            if not valid:
                out["status"] = "fault"
                out["error"] = ("现场采样零有效行: "
                                + "; ".join(str(r.get("error"))[:120]
                                            for r in errs)[:300]
                                if errs else "现场采样零有效行")
                return out
            out["snapshot_ts"] = d.strftime("%Y-%m-%d %H:%M:%S") + "（现场采样）"
            out["top"] = [{k: r.get(k) for k in
                           ("platform", "rank", "title", "url")}
                          for r in valid[:SNAP_TOP_N]]
            if errs:
                out["platforms_note"] = (
                    "部分平台异常: " + "; ".join(str(r.get("error"))[:80]
                                                for r in errs)[:200])
            out["status"] = "ok"
        except Exception as e:                    # noqa: BLE001 —— 段降级
            out["status"], out["error"] = "fault", f"{type(e).__name__}: {e}"[:200]
        return out
    out["status"] = "empty"
    out["error"] = ("监控环未启用（无快照）——python hotlist_watch.py 单发"
                    "一轮建基线，或 hotlist_watch_task.py register 挂每日"
                    "节拍；--sample-hotlist 可现场采样")
    return out


def fetch_toolbox(now: Optional[datetime] = None,
                  shift_log: Optional[str] = None,
                  snapshots_dir: Optional[str] = None) -> Dict:
    """工具箱状态段（零网络）：doctor 本地状态只读，不跑全量巡检。

    返回 {status, shift_stats(摘要 str|None), cookie_age_h, weibo_reading,
    snapshots_n, snapshots_latest, error?}。单项读不到如实带 None——
    本地状态观测缺失是常态不是故障（doctor 可选项同款语义）。
    """
    out: Dict = {"status": None, "shift_stats": None, "cookie_age_h": None,
                 "weibo_reading": None, "snapshots_n": 0,
                 "snapshots_latest": None}
    try:
        import doctor as dr
        log = str(shift_log) if shift_log else str(DEFAULT_SHIFT_LOG)
        stats = dr._shift_log_stats(log, now or datetime.now())
        if stats and stats["total"]:
            last = stats["last"] or stats["last_any"]
            out["shift_stats"] = (f"近 {dr.SHIFT_LOG_WINDOW_DAYS} 天 "
                                  f"{stats['count']} 条覆盖 {stats['days']} 天"
                                  + (f"，最近 [{last[0]}] {last[1]}" if last else ""))
        fetched_at, age_h = dr._cookie_meta()
        out["cookie_age_h"] = age_h
        weibo = dr._last_valid_entry(dr.WEIBO_LIFETIME_LOG_PATH)
        if weibo:
            out["weibo_reading"] = {
                "status": weibo.get("status"),
                "cookie_age_h": weibo.get("cookie_age_h")}
        sd = Path(snapshots_dir) if snapshots_dir else DEFAULT_SNAPSHOTS
        if sd.is_dir():
            snaps = sorted((x for x in sd.iterdir()
                            if re.match(r"^\d{8}_\d{6}(_\d+)?\.json$", x.name)),
                           reverse=True)
            out["snapshots_n"] = len(snaps)
            if snaps:
                out["snapshots_latest"] = snaps[0].stem
        out["status"] = "ok"
    except Exception as e:                        # noqa: BLE001 —— 段降级
        out["status"], out["error"] = "fault", f"{type(e).__name__}: {e}"[:200]
    return out


# ---------------------------------------------------------------------------
# markdown 渲染
# ---------------------------------------------------------------------------
def render(hotlist: Dict, hn: Dict, releases: Dict, toolbox: Dict,
           config_note: str, now: Optional[datetime] = None,
           feeds: Optional[Dict] = None) -> str:
    """五段渲染成 markdown 晨报（段 fault 渲染成 ⚠️ 通道异常行）。

    feeds=None 视为未配置（旧调用方兼容形态，渲染 empty 路径）。"""
    ts = _logfmt.stamp(now or datetime.now())
    lines = [f"# 晨报 {ts}", ""]
    if config_note:
        lines += [f"> 配置: {config_note}", ""]

    # 1 热榜动态
    lines.append("## 热榜动态（hotlist_watch 监控环）")
    if hotlist["status"] == "ok":
        if hotlist.get("snapshot_ts"):
            lines.append(f"- 最新快照 {hotlist['snapshot_ts']}"
                         f"（{Path(hotlist['snapshot_path']).name if hotlist.get('snapshot_path') else '现场采样'}）")
        for ln in hotlist.get("watch_lines") or []:
            lines.append(f"- 今日监控: {ln}")
        for r in hotlist.get("top") or []:
            lines.append(f"  - [{r.get('platform')}#{r.get('rank')}] "
                         f"{r.get('title')} ({r.get('url')})")
        if hotlist.get("platforms_note"):
            lines.append(f"- ⚠️ {hotlist['platforms_note']}")
        if not (hotlist.get("watch_lines") or hotlist.get("top")):
            lines.append("- 快照在但无可展示行（平台过滤后为空？）")
    elif hotlist["status"] == "empty":
        lines.append(f"- （未启用）{hotlist.get('error', '')}")
    else:
        lines.append(f"- ⚠️ 通道异常: {hotlist.get('error', '?')}")
    lines.append("")

    # 2 技术社区信号
    lines.append("## 技术社区信号（Hacker News, 24h）")
    for item in hn.get("queries") or []:
        if "error" in item:
            lines.append(f"- `{item['q']}` ⚠️ 通道异常: {item['error']}")
            continue
        lines.append(f"- `{item['q']}`:")
        for r in item.get("rows") or []:
            lines.append(f"  - [{r.get('points', 0)} 分/{r.get('comments', 0)} 评]"
                         f" {r.get('title', '')} — {r.get('url', '')}")
    lines.append("")

    # 3 关注项目发布
    lines.append("## 关注项目发布（GitHub Releases）")
    for item in releases.get("repos") or []:
        if "error" in item:
            lines.append(f"- `{item['repo']}` ⚠️ 通道异常: {item['error']}")
            continue
        lines.append(f"- `{item['repo']}`:")
        for r in item.get("rows") or []:
            head = (r.get("content") or "").replace("\n", " ")[:120]
            lines.append(f"  - [{r.get('tag', '')}] {r.get('title', '')}"
                         f"（{r.get('ts', '')[:10]}）{head}"
                         + (" ..." if len(r.get("content") or "") > 120 else ""))
    lines.append("")

    # 4 厂商动态（RSS，v3.40；vendor 官宣第一方信号）
    fs = feeds or {"status": "empty", "feeds": []}
    lines.append("## 厂商动态（RSS）")
    if fs["status"] == "empty":
        lines.append("- （未配置）watch_feeds 为空——厂商 RSS 段关闭")
    elif fs["status"] == "fault" and fs.get("error"):
        lines.append(f"- ⚠️ 通道异常: {fs['error']}")
    for f in fs.get("feeds") or []:
        host = urllib.parse.urlparse(f.get("url", "")).netloc or f.get("url", "?")
        if "error" in f:
            lines.append(f"- `{host}` ⚠️ 通道异常: {f['error']}")
            continue
        if f.get("baseline") is not None:
            lines.append(f"- `{host}` 建基线 {f['baseline']} 条（下轮起产新增）")
            for it in f.get("items") or []:
                date = (it.get("date") or "")[:10]
                head = f" [{date}]" if date else ""
                lines.append(f"  -{head} {it.get('title', '')}"
                             f" — {it.get('url', '')}")
        elif f.get("new"):
            lines.append(f"- `{host}` 新增 {f.get('new_n', len(f['new']))} 条:")
            for it in f["new"]:
                date = (it.get("date") or "")[:10]
                head = f" [{date}]" if date else ""
                lines.append(f"  -{head} {it.get('title', '')}"
                             f" — {it.get('url', '')}")
        else:
            lines.append(f"- `{host}` 无新增（已见 {f.get('seen_n', 0)} 条）")
    lines.append("")

    # 5 工具箱状态
    lines.append("## 工具箱状态（doctor 本地状态，零网络）")
    if toolbox["status"] == "ok":
        lines.append(f"- 值班流水: {toolbox.get('shift_stats') or '无记录（可选观测未启用）'}")
        cookie = toolbox.get("cookie_age_h")
        lines.append(f"- 知乎 cookie: {'龄 %.1fh' % cookie if cookie is not None else '无读数'}")
        wb = toolbox.get("weibo_reading")
        lines.append("- weibo cookie 标定: "
                     + (f"{wb.get('status')}（龄 {wb.get('cookie_age_h')}h）"
                        if wb else "无读数（可选观测未启用）"))
        lines.append(f"- 热榜快照链: {toolbox.get('snapshots_n', 0)} 份"
                     f"，最新 {toolbox.get('snapshots_latest') or '-'}")
    else:
        lines.append(f"- ⚠️ 通道异常: {toolbox.get('error', '?')}")
    lines.append("")

    footer = " | ".join(f"{name} {icon}" for name, icon in (
        ("热榜", {"ok": "✅", "empty": "➖", "fault": "⚠️"}[hotlist["status"]]),
        ("HN", "✅" if hn["status"] == "ok" else "⚠️"),
        ("GitHub", "✅" if releases["status"] == "ok" else "⚠️"),
        ("RSS", {"ok": "✅", "empty": "➖", "fault": "⚠️"}[fs["status"]]),
        ("状态", "✅" if toolbox["status"] == "ok" else "⚠️")))
    lines.append("---")
    lines.append(f"digest v{__version__} | 段状态: {footer}")
    return "\n".join(lines)


def render_log_line(now: Optional[datetime] = None, sections=None) -> str:
    """班次日志一行（doctor _shift_log_stats 可解析的 `[YYYY-MM-DD HH:MM] `
    前缀 + digest: 自报家门），内容是五段状态摘要。格式构造 v3.38 起
    走 _logfmt 单一真源（stamp + make_line）。"""
    sec = sections or {}
    body = (f"digest: 热榜={sec.get('hotlist', '?')} "
            f"HN={sec.get('hn', '?')} GitHub={sec.get('releases', '?')} "
            f"RSS={sec.get('feeds', '?')} "
            f"状态={sec.get('toolbox', '?')}")
    return _logfmt.make_line(_logfmt.stamp(now), body, _DIFF_LINE_MAX)


# ---------------------------------------------------------------------------
# --toast 本机通知（v3.34；通道选型取证见模块 docstring——WScript.Shell
# Popup 64+4096 系统模态 + 自动超时，不受通知设置/专注助手影响）
# ---------------------------------------------------------------------------
_NEW_COUNT_RE = re.compile(r"新增 (\d+)")
# hotlist_watch.render_alerts 形态：[NEW] [平台#rank] 标题 (url)——标题自身
# 可含括号，取**最后**一个 " (" 才是 url 起界（跨解析器消费端钉）
_NEW_TITLE_RE = re.compile(r"\[NEW\] \[[^\]]*\] (.+)")


def extract_new_entries(watch_lines: List[str]) -> Dict:
    """从热榜段 watch_lines 提取新增条目摘要 {count, titles}。

    count 取各 diff 行「新增 N」之和（监控环一天可多轮）；titles 取
    [NEW] 告警标题去重保序最多 3 个。解析不出 = 诚实空（弹窗只报段状态）。
    """
    count = 0
    titles: List[str] = []
    for ln in watch_lines or []:
        m = _NEW_COUNT_RE.search(ln)
        if m:
            count += int(m.group(1))
        seg = ln.split("|", 1)[1] if "|" in ln else ""
        for part in (seg or ln).split("；"):
            t = _NEW_TITLE_RE.match(part.strip())
            if t:
                title = t.group(1).strip()
                cut = title.rfind(" (")
                if cut > 0:
                    title = title[:cut]
                if title and title not in titles:
                    titles.append(title)
    return {"count": count, "titles": titles[:3]}


def toast_text(result: Dict) -> tuple:
    """从 run_digest 产物构建弹窗 (title, body)——完成/故障 + 段状态
    + 热榜新增条目摘要。sections 缺某段键（旧形态调用方）渲染 ➖ 不虚报
    ⚠️——非故障不许伪装成故障。"""
    fault = result.get("overall") == "fault"
    title = f"晨报{'故障' if fault else '完成'} {result.get('ts', '')[-8:]}"
    icons = {"hotlist": "热榜", "hn": "HN", "releases": "GitHub",
             "feeds": "RSS", "toolbox": "状态"}
    parts = []
    for k, name in icons.items():
        v = result.get("sections", {}).get(k)
        parts.append(f"{name}"
                     + ("✅" if v == "ok"
                        else "➖" if v in ("empty", None)
                        else "⚠️"))
    body = " ".join(parts)
    new = result.get("new_entries") or {}
    if new.get("count"):
        head = f" | 热榜新增 {new['count']} 条"
        if new.get("titles"):
            head += "：" + " / ".join(new["titles"])
        body += head
    if fault:
        body += " | 全部段 fault——整份晨报零有效内容"
    return title, body[:_TOAST_BODY_MAX]


def run_digest(config_path: Optional[str] = None,
               config_loader: Optional[Callable[[Path], str]] = None,
               hn_fetcher: Optional[Callable[[str, int], List[Dict]]] = None,
               releases_fetcher: Optional[Callable[[str, int], List[Dict]]] = None,
               feeds_fetcher: Optional[Callable[[str], str]] = None,
               hotlist_sampler: Optional[Callable[..., List[Dict]]] = None,
               sample_hotlist: bool = False,
               shift_log: Optional[str] = None,
               snapshots_dir: Optional[str] = None,
               feed_seen_path: Optional[str] = None,
               now: Optional[datetime] = None) -> Dict:
    """跑一次晨报聚合，返回 {markdown, sections, statuses}。

    所有通道可注入——测试全离线。单通道失败降级为该段 fault；全段 fault
    时 overall="fault"（CLI 侧 exit 1）。
    """
    d = now or datetime.now()
    cfg = load_config(config_path, loader=config_loader)
    config, note = cfg["config"], cfg["note"]
    hotlist = fetch_hotlist(shift_log=shift_log,
                            snapshots_dir=snapshots_dir,
                            today=d, platforms=config["watch_platforms"],
                            sample=sample_hotlist, sampler=hotlist_sampler)
    hn = fetch_hn(config["watch_queries"], fetcher=hn_fetcher)
    rel = fetch_releases(config["watch_repos"], fetcher=releases_fetcher)
    fds = fetch_feeds(config["watch_feeds"], fetcher=feeds_fetcher,
                      seen_path=feed_seen_path)
    tb = fetch_toolbox(now=d, shift_log=shift_log,
                       snapshots_dir=snapshots_dir)
    sections = {"hotlist": hotlist["status"], "hn": hn["status"],
                "releases": rel["status"], "feeds": fds["status"],
                "toolbox": tb["status"]}
    md = render(hotlist, hn, rel, tb, note, now=d, feeds=fds)
    overall = "fault" if all(v == "fault" for v in sections.values()) else "ok"
    return {"markdown": md, "sections": sections, "overall": overall,
            "ts": d.strftime("%Y-%m-%d %H:%M:%S"),
            "new_entries": extract_new_entries(hotlist.get("watch_lines"))}


# ---------------------------------------------------------------------------
# CLI（pythonw 安全：sys.stdout 可能为 None——hotlist_watch v3.31 同款）
# ---------------------------------------------------------------------------
def _emit(text: str) -> None:
    if sys.stdout is None:
        return
    print(text)


def _warn(text: str) -> None:
    if sys.stderr is None:
        return
    print(text, file=sys.stderr)


def _maybe_log(log_path: Optional[str], result: Dict,
               now: Optional[datetime] = None) -> None:
    """--log 追加一行班次摘要。写失败只 warn——日志是观测副本。"""
    if not log_path:
        return
    try:
        p = Path(log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(render_log_line(now, result["sections"]) + "\n")
    except OSError as e:
        _warn(f"[{_TOOL}] log 写失败: {e}")


def _main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="每日晨报聚合（五段组合一次早晨汇报，stdout markdown；"
                    "组合层脚本——hotlist_watch v3.31 调用方层先例，引擎/"
                    "MCP 零改动）")
    parser.add_argument("--config", default=None,
                        help=f"配置文件（默认 {DEFAULT_CONFIG}；缺失/坏落回"
                             f"内置默认并注明）")
    parser.add_argument("--log", default=None,
                        help="班次摘要追加（一行一条，如 state/shift_log.md）")
    parser.add_argument("--sample-hotlist", action="store_true",
                        help="热榜段现场采样一发（备用路径；默认零网络消费"
                             "监控环快照）")
    parser.add_argument("--toast", action="store_true",
                        help="晨报产出后弹 Windows 系统模态通知框（标题+段"
                             "状态+热榜新增摘要；WScript.Shell Popup 自动"
                             "超时，尽力而为失败只 warn 不翻退出码）")
    args = parser.parse_args(argv)
    result = run_digest(config_path=args.config,
                        sample_hotlist=args.sample_hotlist)
    _emit(result["markdown"])
    _maybe_log(args.log, result)
    if args.toast:
        try:
            title, body = toast_text(result)
            t = send_toast(title, body)
            if t.get("status") == "fault":
                _warn(f"[{_TOOL}] toast 弹窗失败（尽力而为不翻码）: "
                      f"{t.get('error', '?')}")
        except Exception as e:                    # noqa: BLE001 —— 同上
            _warn(f"[{_TOOL}] toast 弹窗异常（尽力而为不翻码）: "
                  f"{type(e).__name__}: {e}")
    if result["overall"] == "fault":
        _warn(f"[{_TOOL}] 全部段 fault——整份晨报零有效内容")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main())
