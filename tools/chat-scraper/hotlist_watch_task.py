#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Windows 计划任务注册器：把热榜监控环挂成每日班次节拍（v3.31）。

任务（单任务）:
    ai-search-hotlist-watch   每日 09:45 单发一轮 hotlist_watch.py
                              （采样 -> 快照 -> hot_diff -> 班次日志一行）

v3.37：schtask 机械件收口 tools/_schtasks_common.py（三注册器公共层
二次提炼），本文件只留 hotlist 特有件：/TR 相对 --log 构造、错峰时刻、
消息文案。

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
    - **v3.35 实机抓虫**：261 检查是假安全感——/TR 全串 258 字符（未超
      261）仍被 schtasks 静默截断成 254 且报 SUCCESS（悬崖实测
      (250, 258]）；对策双保险：--log 改相对值缩 /TR（hotlist_watch.py
      相对路径锚定脚本目录）+ 注册后回读 /Query /XML 比对存储与预期，
      不一致响亮 exit 1
    - 优先 pythonw.exe（每日不闪黑窗）；同目录没有 pythonw.exe 回退
      sys.executable 并 stderr 告警
    - 脚本与 shift_log 路径自治（__file__ 定位），任务无需设工作目录
    - schtasks 输出 utf-8->gbk 显式回退链解码（中文 Windows 实测 GBK
      字节，locale 猜测崩读线程——v3.28 实机抓虫同款；v3.36 起共享
      tools/_subproc_decode.py，四方副本收口）
    - 非 Windows 诚实报错退出（Linux 用 cron，见 README）

用法:
    python hotlist_watch_task.py register [--at HH:MM] [--toast]
    python hotlist_watch_task.py status
    python hotlist_watch_task.py unregister
"""
import argparse
import sys
from pathlib import Path

# 子进程输出解码公用模块（tools/_subproc_decode.py，v3.36 四方副本收口；
# 父目录注入 sys.path 取用——hotlist_watch.py 取 toast.py 同款先例。
# GBK 解码对 schtasks 输出是承重件，模块缺失响亮 ImportError 不静默降级）
_PARENT = str(Path(__file__).resolve().parent.parent)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)
from _subproc_decode import decode_out as _decode  # noqa: E402,F401
# ^ v3.36 四方 is 钉承重绑定（test_v3360）：_run_schtasks 收口公共层后
# 本文件不再直接消费 _decode，但别名绑定必须存活——身份断链=收口失败

# schtasks 机械件公共层（v3.37 自三注册器二次提炼）：run_schtasks/stream
# 签名不变同对象直引；python_for_task/readback_tr 签名带参（tag/
# task_name 注入），下方 1 行委托包装保旧引用名零漂移（v3350/v3360
# 测试原名调用不断）
from _schtasks_common import (TR_MAX, check_tr_length, is_already_gone,  # noqa: E402
                              python_for_task, readback_tr, verify_stored_tr,
                              win32_guard)
from _schtasks_common import stream as _stream  # noqa: E402
from _schtasks_common import run_schtasks as _run_schtasks  # noqa: E402

HERE = Path(__file__).resolve().parent
WATCH_PY = HERE / "hotlist_watch.py"
# 班次日志位置：HERE / state / shift_log.md（v3.35 起注册器传**相对**
# --log，由 hotlist_watch.py 锚定到脚本目录——绝对 SHIFT_LOG 常量随之
# 移除，防 dead const；doctor/digest 消费端不受影响，文件位置不变）

TAG = "hotlist_watch_task"  # 消息前缀（公共层告警/报错注入）
TASK_NAME = "ai-search-hotlist-watch"
DEFAULT_AT = "09:45"           # 与 ai-search-sogou-probe（09:30）错峰
# TR_MAX 自公共层导入（schtasks /TR 值硬上限 261）


def _python_for_task() -> str:
    """计划任务用的解释器（公共层 python_for_task，前缀注入本注册器）。"""
    return python_for_task(TAG)


def _readback_tr(runner=None):
    """回读存储 /TR（公共层 readback_tr，task_name 注入本注册器）。"""
    return readback_tr(TASK_NAME, runner=runner)


def _tr_value(python: str, toast: bool = False) -> str:
    """/TR 值：嵌入引号包两个带空格安全的绝对路径 + **相对** --log
    （--toast 再追加弹窗旗标——v3.35 opt-in）。

    v3.35 实机抓虫：绝对 --log 使全串 258 字符被 schtasks **静默截断**
    成 254 仍报 SUCCESS（截断悬崖实测在 (250, 258]，261 上限检查给的是
    假安全感）——hotlist_watch.py 已把相对 --log 锚定到脚本所在目录
    （任务工作目录不可设），注册器改传相对值：/TR 258 -> 173 字符远离
    悬崖；register 内另有回读验证兜底（存储不一致响亮 exit 1）。
    """
    tr = (f'"{python}" "{WATCH_PY}" '
          f'--log state/shift_log.md')
    if toast:
        tr += " --toast"
    check_tr_length(tr)  # 261 上限 + 超长报错文案在公共层（超长宁可不注册）
    return tr


def register(at: str = DEFAULT_AT, runner=None, toast: bool = False) -> int:
    """注册/覆盖每日计划任务，返回退出码（0=注册成功承重生效）。

    toast=True 时 /TR 追加 --toast：监控环 diff 出新增条目当日 09:45 即
    时弹 Windows 通知（hotlist_watch.py --toast，通道与降级语义见
    hotlist_watch.py docstring）——不等 10:00 晨报汇总弹窗。"""
    if not win32_guard(TAG, "（Linux 用 cron: "
                            "45 9 * * * python hotlist_watch.py "
                            "--log state/shift_log.md）"):
        return 1
    try:
        tr = _tr_value(_python_for_task(), toast=toast)
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
    # 回读验证（v3.35 实机抓虫对策；v3.37 收口公共层 verify_stored_tr）：
    # schtasks /Create 会静默截断超长 /TR 且仍报 SUCCESS（本机实测
    # 258 -> 254，悬崖 (250, 258]）——存储不一致响亮 exit 1，宁报错不
    # 留一个不按预期运行的假任务；无法回读只告警不判失败（「无法验证」
    # 不等于「验证失败」）。
    if not verify_stored_tr(TASK_NAME, tr, TAG, runner=runner):
        return 1
    print(f"[hotlist_watch_task] registered {TASK_NAME} "
          f"(DAILY {at} -> hotlist_watch 单发一轮，diff 进班次日志"
          + ("，新增条目即时弹 Windows 通知)" if toast else ")"))
    return 0


def status(runner=None) -> int:
    """查询任务状态；0=在场，1=缺失。"""
    if not win32_guard(TAG):
        return 1
    proc = _run_schtasks(
        ["schtasks", "/Query", "/TN", TASK_NAME], runner=runner)
    ok = proc.returncode == 0
    print(f"[hotlist_watch_task] {TASK_NAME}: "
          f"{'installed' if ok else 'NOT INSTALLED'}")
    return 0 if ok else 1


def unregister(runner=None) -> int:
    """删除任务（一键回滚）；已不存在的任务视为删除成功（幂等）。

    单任务语义：本任务成败即返回值（watchdog 双任务版是循环删 +
    failed 聚合——语义差异承重，见公共层 docstring，不硬统一）。"""
    if not win32_guard(TAG):
        return 1
    proc = _run_schtasks(
        ["schtasks", "/Delete", "/F", "/TN", TASK_NAME], runner=runner)
    if proc.returncode != 0:
        # 中文 schtasks「系统找不到指定的文件」/ 英文 "does not exist"
        # ——三措辞匹配收口公共层 is_already_gone
        if is_already_gone(proc):
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
    reg.add_argument("--toast", action="store_true",
                     help="/TR 追加 --toast：新增条目即时弹 Windows 通知")
    sub.add_parser("status", help="查询任务状态")
    sub.add_parser("unregister", help="删除任务（回滚）")
    args = parser.parse_args()
    if args.cmd == "register":
        return register(at=args.at, toast=args.toast)
    if args.cmd == "status":
        return status()
    return unregister()


if __name__ == "__main__":
    sys.exit(main())
