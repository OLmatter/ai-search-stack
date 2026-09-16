#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Windows 计划任务注册器：把热榜监控环挂成每日班次节拍（v3.31）。

任务（单任务）:
    ai-search-hotlist-watch   每日 09:45 单发一轮 hotlist_watch.py
                              （采样 -> 快照 -> hot_diff -> 班次日志一行）

接线方式推导（二选一：班次提示词片段 vs schtasks）——选 schtasks：
    - 每日 diff 节拍是确定性动作（采样/diff/追加一行），零 agent 认知；
      班次会话（CronUpdate 驱动）是 Agent 调度框架——ARCHITECTURE.md
      「复用边界」明确调度/监控告警不进 toolbox，确定性节拍归 OS 调度器
      （ai-search-sogou-probe v3.21 / ai-search-gbridge-watchdog v3.28
      同款先例），不该占用 LLM 班次上下文、也不该等主人下次 CronUpdate
      粘贴片段（人在环里的机器活）。
    - 热榜 diff 落 state/shift_log.md（班次日志）：doctor 值班巡检趋势
      （_shift_log_stats）按 `[YYYY-MM-DD HH:MM]` 行解析，机器行自带
      hotlist_watch: 前缀自报家门，值班连续性观测天然覆盖。

设计约束（沿 google-bridge/watchdog_task.py v3.28 先例，test_v3310 钉死）:
    - /TR 用嵌入引号包绝对路径（带空格路径必须整串引住）；超 261 字符
      （schtasks /TR 硬上限）报错退出，不静默截断
    - 优先 pythonw.exe（每日不闪黑窗）；同目录没有 pythonw.exe 回退
      sys.executable 并 stderr 告警
    - 脚本与 shift_log 路径自治（__file__ 定位），任务无需设工作目录
    - schtasks 输出 utf-8->gbk 显式回退链解码（中文 Windows 实测 GBK
      字节，locale 猜测崩读线程——v3.28 实机抓虫同款）
    - 非 Windows 诚实报错退出（Linux 用 cron，见 README）

用法:
    python hotlist_watch_task.py register [--at HH:MM]
    python hotlist_watch_task.py status
    python hotlist_watch_task.py unregister
"""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WATCH_PY = HERE / "hotlist_watch.py"
SHIFT_LOG = HERE / "state" / "shift_log.md"

TASK_NAME = "ai-search-hotlist-watch"
DEFAULT_AT = "09:45"           # 与 ai-search-sogou-probe（09:30）错峰
TR_MAX = 261                   # schtasks /TR 值硬上限（超出报错不截断）


def _python_for_task() -> str:
    """计划任务用的解释器：优先 pythonw.exe（免闪窗），缺失回退并告警。"""
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if pythonw.is_file():
        return str(pythonw)
    print(f"[hotlist_watch_task] warning: {pythonw} not found; "
          f"falling back to {exe} (console window will flash daily)",
          file=sys.stderr)
    return str(exe)


def _tr_value(python: str) -> str:
    """/TR 值：嵌入引号包两个带空格安全的绝对路径 + --log 班次日志。"""
    tr = (f'"{python}" "{WATCH_PY}" '
          f'--log "{SHIFT_LOG}"')
    if len(tr) > TR_MAX:
        # schtasks 对 /TR 有 261 字符硬上限；超长静默截断会注册出
        # 永远跑不起来的任务——宁可不注册
        raise ValueError(
            f"/TR too long ({len(tr)} > {TR_MAX}): {tr}\n"
            "把仓库挪到更短路径，或手工注册（schtasks /Create ...）")
    return tr


def _decode(raw):
    """schtasks 输出解码：utf-8 严格 → gbk 严格 → replace 兜底。

    实测（2026-09-17，watchdog_task 同款）：中文 Windows 的 schtasks
    输出是 GBK 字节；Anaconda python 在 Git Bash 下 locale 首选编码报
    utf-8，直接按它解会崩。"""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    for codec in ("utf-8", "gbk"):
        try:
            return raw.decode(codec)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def _run_schtasks(argv, runner=None):
    """跑 schtasks 并返回 stdout/stderr 已解码为 str 的结果（runner 可注入）。"""
    if runner is None:
        proc = subprocess.run(argv, capture_output=True)
        proc.stdout, proc.stderr = _decode(proc.stdout), _decode(proc.stderr)
        return proc
    proc = runner(argv, capture_output=True, text=True)
    proc.stdout, proc.stderr = _decode(proc.stdout), _decode(proc.stderr)
    return proc


def _stream(proc, name: str) -> str:
    """None 安全取 stdout/stderr 文本。"""
    return getattr(proc, name, None) or ""


def register(at: str = DEFAULT_AT, runner=None) -> int:
    """注册/覆盖每日计划任务，返回退出码（0=注册成功承重生效）。"""
    if sys.platform != "win32":
        print("[hotlist_watch_task] ERROR: Windows-only（Linux 用 cron: "
              "45 9 * * * python hotlist_watch.py --log state/shift_log.md）",
              file=sys.stderr)
        return 1
    try:
        tr = _tr_value(_python_for_task())
    except ValueError as e:
        print(f"[hotlist_watch_task] ERROR: {e}", file=sys.stderr)
        return 1
    argv = ["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/TR", tr,
            "/SC", "DAILY", "/ST", at]
    proc = _run_schtasks(argv, runner=runner)
    if proc.returncode != 0:
        print(f"[hotlist_watch_task] register FAILED {TASK_NAME}\n"
              f"  stdout: {_stream(proc, 'stdout').strip()}\n"
              f"  stderr: {_stream(proc, 'stderr').strip()}",
              file=sys.stderr)
        return 1
    print(f"[hotlist_watch_task] registered {TASK_NAME} "
          f"(DAILY {at} -> hotlist_watch 单发一轮，diff 进班次日志)")
    return 0


def status(runner=None) -> int:
    """查询任务状态；0=在场，1=缺失。"""
    if sys.platform != "win32":
        print("[hotlist_watch_task] ERROR: Windows-only", file=sys.stderr)
        return 1
    proc = _run_schtasks(
        ["schtasks", "/Query", "/TN", TASK_NAME], runner=runner)
    ok = proc.returncode == 0
    print(f"[hotlist_watch_task] {TASK_NAME}: "
          f"{'installed' if ok else 'NOT INSTALLED'}")
    return 0 if ok else 1


def unregister(runner=None) -> int:
    """删除任务（一键回滚）；已不存在的任务视为删除成功（幂等）。"""
    if sys.platform != "win32":
        print("[hotlist_watch_task] ERROR: Windows-only", file=sys.stderr)
        return 1
    proc = _run_schtasks(
        ["schtasks", "/Delete", "/F", "/TN", TASK_NAME], runner=runner)
    if proc.returncode != 0:
        # 中文 schtasks「系统找不到指定的文件」/ 英文 "does not exist"
        blob = f"{_stream(proc, 'stdout')}{_stream(proc, 'stderr')}"
        if ("does not exist" in blob or "不存在" in blob or "找不到" in blob):
            print(f"[hotlist_watch_task] {TASK_NAME}: not installed "
                  f"(already gone)")
            return 0
        print(f"[hotlist_watch_task] unregister FAILED {TASK_NAME}\n"
              f"  stdout: {_stream(proc, 'stdout').strip()}\n"
              f"  stderr: {_stream(proc, 'stderr').strip()}",
              file=sys.stderr)
        return 1
    print(f"[hotlist_watch_task] unregistered {TASK_NAME}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="热榜监控环 Windows 每日计划任务注册器")
    sub = parser.add_subparsers(dest="cmd", required=True)
    reg = sub.add_parser("register", help="注册/覆盖每日计划任务")
    reg.add_argument("--at", default=DEFAULT_AT,
                     help=f"每日触发时间 HH:MM（默认 {DEFAULT_AT}）")
    sub.add_parser("status", help="查询任务状态")
    sub.add_parser("unregister", help="删除任务（回滚）")
    args = parser.parse_args()
    if args.cmd == "register":
        return register(at=args.at)
    if args.cmd == "status":
        return status()
    return unregister()


if __name__ == "__main__":
    sys.exit(main())
