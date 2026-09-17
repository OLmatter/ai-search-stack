#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""热榜监控环组合脚本（v3.31；v3.35 增量见下）——采样 -> 快照落盘 ->
hot_diff -> 告警输出。

v3.35 增量（--toast 即时弹窗）: 加 --toast 旗标——监控环 diff 出**新增
条目**时立即弹 Windows 系统模态通知框（标题=热榜新增 N 条 + 轮次时间，
正文=前 3 条 [NEW] 平台#rank 标题 + 消失数），不等 10:00 晨报弹窗汇总。
通道复用 tools/toast.py 公用模块（v3.34 活体取证定案的 WScript.Shell
Popup，父目录注入 sys.path 取用，双模式导入同 search.py 先例）；弹窗
尽力而为：fault/异常只 stderr warn 绝不翻监控环退出码；baseline（首轮
建基线）/fault（采样挂）/零新增不弹——弹窗只报事件信号。弹窗阻塞至
自动超时（12s）或用户确认，自轮询节拍相应顺移（采样节奏主权仍在调用
方，介意就别开 --toast 或调大 --interval）。hotlist_watch_task v3.35
同款：register --toast 把旗标带进计划任务 /TR（opt-in，无旗标不含
--toast）；**v3.35 实机抓虫**：/TR 含绝对 --log 时全串 258 字符被
schtasks 静默截断成 254 仍报 SUCCESS（261 上限检查给假安全感，截断
悬崖实测在 (250, 258]）——注册器改传相对 --log（本脚本把相对路径锚
定到脚本所在目录，schtasks 任务工作目录不可设）+ 注册后回读验证，
/TR 从 258 缩到 173 字符远离悬崖。

定位（toolbox 复用边界，ARCHITECTURE.md「复用边界」）：监控告警**不进引擎**
——引擎只提供 hot()（采样原语）与 hot_diff()（两轮 diff 纯函数，v3.30）；
快照落盘/周期调度/告警输出归调用方层。本脚本是该调用方层的参考实现：
把 v3.30 演练里「两轮采样 + diff」的手工链路固化成一条命令，可单发可自
轮询，并被 hotlist_watch_task.py 注册成 Windows 每日计划任务（班次接线）。

链路（每轮）:
    1. sample:   hot(platforms, num)（on_error="report"，故障平台带 error 记录）
    2. snapshot: 全部平台零有效行 = 本轮故障，**不落快照**（不污染快照链）；
                 否则写 state/hotlist_snapshots/YYYYMMDD_HHMMSS.json
                 （同秒冲突加 _N 后缀；只保留最近 --keep 份，滚动清理）
    3. diff:     与最近一份历史快照 hot_diff（宁缺勿错：前轮缺失/报错的
                 平台整侧剔除不产假信号，v3.30 语义）——首轮无历史 = 建基线
    4. alert:    stdout 结构化 JSON（mode/status/summary/new/gone/alerts）+
                 可选 --log 追加一行班次日志格式
                 `[YYYY-MM-DD HH:MM] hotlist_watch: ...`（doctor 值班巡检
                 趋势 _shift_log_stats 可直接解析，每日 diff 进班次日志）

用法:
    # 单发（默认）：采样一次、diff 一次、退出——cron/计划任务最便宜节拍
    python hotlist_watch.py [--platforms bilibili,weibo] [--num 20]
                            [--snapshots-dir DIR] [--keep 50] [--log FILE]
                            [--toast]
    # 自轮询：每 --interval 秒一轮（监控节奏主权在调用方）
    python hotlist_watch.py --interval 600 [--toast]

退出码（--hotlist-probe 契约同构）: 0 = 有效观测（建基线/diff 完成/自轮询
正常退出）；1 = 本地故障（采样抛异常 / 全平台 error / 零有效行 / 快照写
失败）。有新增事件不算故障——事件是观测结果不是错误，走 stdout 告警与
--log，不翻退出码。

测试纪律：sample()/now 均可注入（run_once 参数），回归钉全离线——真实
采样只发生在 CLI 实跑（计划任务 /Run 实据见 CHANGELOG v3.31.0）。
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

try:  # 包内导入（同 search.py 双模式）
    from . import hotlist_engine as hl
except ImportError:  # 扁平导入（sys.path 指向本目录）
    import hotlist_engine as hl  # type: ignore

# 班次行格式单一真源（tools/_logfmt.py，在本目录的父目录——v3.38 四方
# 收口：本脚本 render_log_line 的行构造与 doctor._shift_log_stats、
# digest 消费端同一契约。格式是 render_log_line 的核心依赖，缺失即炸
# 不降级——降级副本=把漂移病藏进 except 分支，与 v3.36 解码链收口同款
# 纪律）
_PARENT_DIR = str(Path(__file__).resolve().parent.parent)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)
import _logfmt   # noqa: E402

# 弹窗通道公用模块（tools/toast.py，同在父目录——v3.35 提取自
# digest.py；父目录已由上方 _logfmt 接线注入 sys.path，缺失时降级为
# fault 工厂不炸监控环——弹窗是观测副本，缺了只许少弹不许多炸）
try:
    from toast import send_toast as _toast_send_impl
    from toast import TOAST_BODY_MAX as _TOAST_BODY_MAX
except ImportError:                              # pragma: no cover
    def _toast_send_impl(title, body):           # type: ignore
        return {"status": "fault",
                "error": "toast 模块缺失（tools/toast.py）"}
    _TOAST_BODY_MAX = 240

__all__ = ["run_once", "save_snapshot", "latest_snapshot",
           "cleanup_snapshots", "render_alerts", "render_log_line",
           "watch_toast_text"]

_TOOL = "hotlist_watch"
DEFAULT_KEEP = 50                 # 快照滚动保留份数
_LOG_LINE_MAX = 500               # 班次日志行内容上限（不刷屏班次流水）
# 快照文件名（本脚本产出）：YYYYMMDD_HHMMSS.json，同秒冲突 _N 后缀
_SNAP_RE = re.compile(r"^\d{8}_\d{6}(_\d+)?\.json$")


# ---------------------------------------------------------------------------
# 快照落盘（调用方层状态；引擎无状态——v3.30 架构推导的另一半）
# ---------------------------------------------------------------------------
def save_snapshot(snapshots_dir: str, rows: List[Dict], platforms: List[str],
                  num: int, now: Optional[datetime] = None) -> str:
    """写一份快照 JSON，返回文件路径。同秒冲突自动加 _N 后缀。

    内容：{ts, tool, platforms, num, rows}——rows 是 hot() 原始输出
    （含 error 记录，如实落盘；diff 时 hot_diff 自会剔除）。
    """
    d = Path(snapshots_dir)
    d.mkdir(parents=True, exist_ok=True)
    ts = (now or datetime.now())
    base = ts.strftime("%Y%m%d_%H%M%S")
    path = d / f"{base}.json"
    i = 2
    while path.exists():            # 同秒两次采样（自轮询极小 interval）不覆盖
        path = d / f"{base}_{i}.json"
        i += 1
    payload = {
        "ts": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "tool": _TOOL,
        "platforms": list(platforms),
        "num": num,
        "rows": rows,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(path)               # 同目录替换，写一半不留半截快照
    return str(path)


def latest_snapshot(snapshots_dir: str) -> Optional[Tuple[str, Dict]]:
    """读最近一份快照，返回 (path, payload)；目录无快照/全部坏文件返回 None。

    只认本脚本命名形态（_SNAP_RE）——目录里混进的其它 json 不当快照链一环。
    坏文件（非 JSON）跳过读再旧一份：一份损坏不能让监控环死掉。
    """
    d = Path(snapshots_dir)
    if not d.is_dir():
        return None
    for p in sorted((x for x in d.iterdir()
                     if _SNAP_RE.match(x.name)),
                    reverse=True):
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue                # 损坏快照跳过，往前找（宁缺勿错）
        if isinstance(payload, dict) and isinstance(
                payload.get("rows"), list):
            return str(p), payload
    return None


def cleanup_snapshots(snapshots_dir: str, keep: int = DEFAULT_KEEP) -> int:
    """滚动清理：只留最近 keep 份快照，返回删除数（keep<1 视为不清理）。"""
    if keep < 1:
        return 0
    d = Path(snapshots_dir)
    if not d.is_dir():
        return 0
    snaps = sorted((x for x in d.iterdir() if _SNAP_RE.match(x.name)),
                   reverse=True)
    removed = 0
    for p in snaps[keep:]:
        try:
            p.unlink()
            removed += 1
        except OSError:
            continue                # 删不掉（占用/权限）不炸监控环
    return removed


# ---------------------------------------------------------------------------
# 单轮监控（采样 -> 快照 -> diff -> 告警）
# ---------------------------------------------------------------------------
def _valid_rows(rows: List[Dict]) -> List[Dict]:
    return [r for r in rows if isinstance(r, dict) and "error" not in r]


def run_once(platforms: Optional[List[str]] = None, num: int = 20,
             snapshots_dir: str = "state/hotlist_snapshots",
             keep: int = DEFAULT_KEEP,
             sampler: Optional[Callable[..., List[Dict]]] = None,
             now: Optional[datetime] = None,
             log_path: Optional[str] = None) -> Dict:
    """跑一轮监控环，返回结果 dict（也是 stdout 结构化输出的来源）。

    sampler 默认 hotlist_engine.hot；测试注入假采样即全离线。
    status 三态：
        baseline  首轮无历史快照——只落基线不产信号
        diff      与最近历史快照完成 diff
        fault     采样异常 / 全平台 error / 零有效行——不落快照
    fault 时 result 带 "error" 字段；快照写失败同样归 fault（快照链是
    本脚本的承重状态，写不进去等于监控环失明，如实报故障）。
    """
    fn = sampler or hl.hot
    result: Dict = {"tool": _TOOL, "mode": "once", "status": None,
                    "ts": (now or datetime.now()).strftime(
                        "%Y-%m-%d %H:%M:%S"),
                    "platforms": list(platforms or hl.DEFAULT_PLATFORMS),
                    "num": num}
    try:
        rows = fn(platforms=result["platforms"], num=num,
                  on_error="report")
    except Exception as e:          # noqa: BLE001 —— 归 fault，不炸调用方
        result["status"], result["error"] = "fault", f"{type(e).__name__}: {e}"
        _maybe_log(log_path, result, now=now)
        return result
    valid = _valid_rows(rows)
    result["rows_total"] = len(rows)
    result["rows_valid"] = len(valid)
    if not valid:                   # 全 error 或全空 = 通道级故障，不落快照
        errs = [r.get("error", "?") for r in rows if isinstance(r, dict)
                and "error" in r]
        result["status"] = "fault"
        result["error"] = ("零有效行（全平台 error/空）: "
                           + "; ".join(errs)[:300]) if errs else "零有效行"
        _maybe_log(log_path, result, now=now)
        return result
    prev = latest_snapshot(snapshots_dir)
    try:
        cur = save_snapshot(snapshots_dir, rows, result["platforms"], num,
                            now=now)
    except OSError as e:
        result["status"], result["error"] = "fault", f"快照写失败: {e}"
        _maybe_log(log_path, result, now=now)
        return result
    result["cur_snapshot"] = cur
    result["removed_snapshots"] = cleanup_snapshots(snapshots_dir, keep)
    if prev is None:
        result["status"], result["prev_snapshot"] = "baseline", None
        result["summary"] = {"new": 0, "gone": 0, "kept": len(valid)}
        result["new"], result["gone"] = [], []
        result["alerts"] = []
        _maybe_log(log_path, result, now=now)
        return result
    result["prev_snapshot"] = prev[0]
    diff = hl.hot_diff(prev[1].get("rows") or [], rows)
    result["status"] = "diff"
    result["summary"] = {"new": len(diff["new"]), "gone": len(diff["gone"]),
                         "kept": diff["kept"], "platforms": diff["platforms"],
                         "skipped_platforms": diff["skipped_platforms"]}
    result["new"], result["gone"] = diff["new"], diff["gone"]
    result["alerts"] = render_alerts(diff)
    _maybe_log(log_path, result, now=now)
    return result


def render_alerts(diff: Dict) -> List[str]:
    """把 hot_diff 结果渲染成告警行：[NEW]/[GONE] + 平台#rank + 标题。"""
    out: List[str] = []
    for tag, key in (("NEW", "new"), ("GONE", "gone")):
        for r in diff.get(key) or []:
            rank = r.get("rank")
            out.append(f"[{tag}] [{r.get('platform', '?')}#{rank}] "
                       f"{r.get('title', '')} ({r.get('url', '')})")
    return out


def render_log_line(result: Dict) -> str:
    """班次日志一行（doctor _shift_log_stats 可解析的 `[YYYY-MM-DD HH:MM] `
    前缀），内容自 identifying 前缀 hotlist_watch:。超长截断（班次流水
    不是数据转储——明细在快照文件与 stdout JSON 里）。行构造 v3.38 起
    走 _logfmt.make_line 单一真源（与解析端同源）。"""
    plats = result.get("platforms") or []
    head = "+".join(plats) if 0 < len(plats) <= 3 else f"{len(plats)}平台"
    if result["status"] == "fault":
        body = f"hotlist_watch: 故障未落快照（{head} 采样）——{result.get('error', '?')}"
    elif result["status"] == "baseline":
        body = (f"hotlist_watch: 建基线（{head}，有效 {result.get('rows_valid', 0)}"
                f" 行）——下一轮起产 diff 信号")
    else:
        s = result.get("summary") or {}
        body = (f"hotlist_watch: diff（{head}）新增 {s.get('new', 0)} "
                f"消失 {s.get('gone', 0)} 保留 {s.get('kept', 0)}")
        alerts = result.get("alerts") or []
        if alerts:
            body += " | " + "；".join(alerts)
    skipped = (result.get("summary") or {}).get("skipped_platforms") or {}
    if skipped:
        body += f" | 单侧剔除: {', '.join(sorted(skipped))}"
    return _logfmt.make_line(result["ts"], body, _LOG_LINE_MAX)


def watch_toast_text(result: Dict) -> tuple:
    """从监控轮产物构建弹窗 (title, body)——新增条目数 + 前 3 条
    [NEW] 平台#rank 标题 + 消失数。

    标题直接取结构化行（result["new"] 的 {platform, rank, title, url}），
    不含 URL 后缀，无需 digest extract_new_entries 的内嵌括号截断；正文
    截 TOAST_BODY_MAX 上限（弹窗不是数据转储）。"""
    s = result.get("summary") or {}
    n = int(s.get("new", 0) or 0)
    title = f"热榜新增 {n} 条 {(result.get('ts') or '')[-8:]}"
    titles: List[str] = []
    for r in (result.get("new") or [])[:3]:
        t = str((r or {}).get("title", "")).strip()
        if t:
            titles.append(f"[{(r or {}).get('platform', '?')}"
                          f"#{(r or {}).get('rank', '?')}] {t}")
    body = " ".join(titles)
    gone = int(s.get("gone", 0) or 0)
    if gone:
        body += f" | 消失 {gone}"
    return title, body[:_TOAST_BODY_MAX]


def _maybe_log(log_path: Optional[str], result: Dict,
               now: Optional[datetime] = None) -> None:
    """--log 追加一行（班次日志格式）。写失败只 warn——日志是观测副本，
    不能反过来把监控环打成 fault。"""
    if not log_path:
        return
    try:
        p = Path(log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(render_log_line(result) + "\n")
    except OSError as e:
        _warn(f"[{_TOOL}] log 写失败: {e}")


# ---------------------------------------------------------------------------
# CLI（单发 / 自轮询）
# ---------------------------------------------------------------------------
def _emit(text: str) -> None:
    """stdout 输出（pythonw 安全）：计划任务跑 pythonw 时无控制台，
    sys.stdout 为 None——print 会 AttributeError 把已完成的监控轮
    （快照/--log 都已落盘）打成丑死。观测产物落了盘，打印直接跳过。"""
    if sys.stdout is None:
        return
    print(text)


def _warn(text: str) -> None:
    """stderr 输出（pythonw 安全，同 _emit）。"""
    if sys.stderr is None:
        return
    print(text, file=sys.stderr)


def _send_toast(title: str, body: str) -> Dict:
    """弹一发（尽力而为）：通道异常归 fault dict 不抛——通知是观测副本，
    绝不炸已落盘的监控轮（快照/--log 在 run_once 内已落）。"""
    try:
        return _toast_send_impl(title, body)
    except Exception as e:                       # noqa: BLE001 —— 同上
        return {"status": "fault",
                "error": f"{type(e).__name__}: {e}"[:200]}


def _maybe_toast(result: Dict) -> None:
    """--toast 接线：diff 出**新增条目**才弹（baseline/fault/零新增不弹
    ——弹窗只报事件信号）；失败只 warn 不翻退出码。"""
    s = result.get("summary") or {}
    if result.get("status") != "diff" or not s.get("new"):
        return
    title, body = watch_toast_text(result)
    t = _send_toast(title, body)
    if t.get("status") == "fault":
        _warn(f"[{_TOOL}] toast 弹窗失败（尽力而为不翻码）: "
              f"{t.get('error', '?')}")


def _cycle(platforms, num, snapshots_dir, keep, log_path,
           toast: bool = False) -> int:
    """跑一轮并打印结构化 JSON，返回退出码（0 有效观测 / 1 故障）。"""
    result = run_once(platforms=platforms, num=num,
                      snapshots_dir=snapshots_dir, keep=keep,
                      log_path=log_path)
    _emit(json.dumps(result, ensure_ascii=False, indent=1))
    if toast:
        _maybe_toast(result)
    return 1 if result["status"] == "fault" else 0


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="热榜监控环（采样->快照->hot_diff->告警；调用方层组合，"
                    "引擎不含监控——ARCHITECTURE.md 复用边界）")
    parser.add_argument("--platforms", default=None,
                        help="逗号分隔平台名，如 bilibili,weibo；省略为"
                             " hot() 默认可用集")
    parser.add_argument("--num", type=int, default=20)
    parser.add_argument("--interval", type=float, default=None,
                        help="自轮询间隔秒；省略 = 单发模式（cron 节拍）")
    parser.add_argument("--snapshots-dir", default=None,
                        help="快照目录（默认 <本脚本>/state/hotlist_snapshots）")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP,
                        help=f"快照滚动保留份数（默认 {DEFAULT_KEEP}；"
                             f"<1 不清理）")
    parser.add_argument("--log", default=None,
                        help="告警/状态追加日志（班次日志格式一行一条，"
                             "如 state/shift_log.md；**相对路径按本脚本所"
                             "在目录锚定**——schtasks 任务工作目录不可设"
                             "（/Create 无该参数，恒为 system32），注册器"
                             "因此传相对值缩 /TR）")
    parser.add_argument("--toast", action="store_true",
                        help="diff 出新增条目时立即弹 Windows 系统模态通"
                             "知框（tools/toast.py 公用通道；baseline/"
                             "fault/零新增不弹；尽力而为失败不翻退出码）")
    args = parser.parse_args()
    # --log 相对路径锚定本脚本目录（schtasks 任务无工作目录可设，恒为
    # system32——绝对路径照旧不受影响；v3.35 注册器借相对值缩 /TR）
    if args.log and not Path(args.log).is_absolute():
        args.log = str(Path(__file__).resolve().parent / args.log)
    platforms = ([p for p in args.platforms.split(",") if p.strip()]
                 if args.platforms else None)
    snapshots_dir = args.snapshots_dir or str(
        Path(__file__).resolve().parent / "state" / "hotlist_snapshots")
    if args.interval is None:       # 单发：一次采样一次 diff
        return _cycle(platforms, args.num, snapshots_dir, args.keep,
                      args.log, toast=args.toast)
    if args.interval <= 0:
        parser.error("--interval must be > 0")
    # 自轮询：单轮故障不退出（瞬时网抖不该杀死监控环），下一轮自愈；
    # Ctrl-C 干净退出 0
    while True:
        try:
            code = _cycle(platforms, args.num, snapshots_dir, args.keep,
                          args.log, toast=args.toast)
            if code:
                _warn(f"[{_TOOL}] 本轮 fault（自轮询继续，下一轮自愈）")
        except KeyboardInterrupt:
            return 0
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            return 0


if __name__ == "__main__":
    sys.exit(_main())
