#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Windows 计划任务注册器：把每日晨报挂成班次节拍（v3.33；v3.34 加
register --toast 接线本机通知；v3.36 加注册后回读验证 + 解码链收口；
v3.37 公共层二次提炼——schtask 机械件收口 tools/_schtasks_common.py，
本文件只留 digest 特有件：/TR 构造、错峰时刻、消息文案）。

任务（单任务）:
    ai-search-digest   每日 10:00 单发一轮 digest.py
                       （四段聚合 -> stdout markdown -> 班次日志一行
                         [-> Windows 弹窗通知，仅 register --toast]）

接线方式（v3.33 评估结论，详见 digest.py 模块 docstring）：晨报聚合是
确定性动作（固定通道/固定渲染/零认知），归 OS 调度器不占 LLM 班次上下
文（hotlist_watch_task.py v3.31 同款推导）。10:00 错峰在 sogou-probe
09:30 与 hotlist-watch 09:45 之后——晨报消费当日监控环 diff 产物，
排在其后才能读到今天的 hotlist_watch 行。

设计约束（沿 hotlist_watch_task.py v3.31 先例，test_v3330 钉死）:
    - /TR 嵌入引号包绝对路径；超 261 字符（schtasks /TR 硬上限）报错
      退出，不静默截断
    - **v3.36 回读验证**（hotlist_watch_task v3.35 实机抓虫同款对策
      移植）：261 检查是假安全感——/TR 未超 261 仍可能被 schtasks 静默
      截断且报 SUCCESS（悬崖实测 (250, 258]）；注册后 /Query /XML 回读
      存储的 Command+Arguments 与预期比对，不一致响亮 exit 1（本注册器
      /TR 238 字符带余量 23，暂离悬崖，但回读是兜底不是装饰——宁报错
      不留假任务）。无法回读（任务缺失/XML 无节点）只告警不判失败——
      「无法验证」不等于「验证失败」
    - 优先 pythonw.exe（免闪窗）；缺失回退 sys.executable 并 stderr 告警
    - 脚本与 shift_log 路径自治（__file__ 定位），任务无需设工作目录
    - schtasks 输出 utf-8->gbk 显式回退链解码（v3.28 实机抓虫同款；
      v3.36 起共享 tools/_subproc_decode.py，四方副本收口）
    - digest 自带 pythonw null-stdout 安全（hotlist_watch v3.31 踩坑
      修复同款），console-less 计划任务不炸已完成的聚合轮
    - 非 Windows 诚实报错退出（Linux 用 cron，见 README）

用法:
    python digest_task.py register [--at HH:MM] [--toast]
    python digest_task.py status
    python digest_task.py unregister
"""
import argparse
import sys
from pathlib import Path

from _subproc_decode import decode_out as _decode  # noqa: F401
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
DIGEST_PY = HERE / "digest.py"
SHIFT_LOG = HERE / "chat-scraper" / "state" / "shift_log.md"

TAG = "digest_task"    # 消息前缀（公共层告警/报错注入）
TASK_NAME = "ai-search-digest"
DEFAULT_AT = "10:00"   # 错峰：sogou-probe 09:30 -> hotlist-watch 09:45 -> digest 10:00
# TR_MAX 自公共层导入（schtasks /TR 值硬上限 261）


def _python_for_task() -> str:
    """计划任务用的解释器（公共层 python_for_task，前缀注入本注册器）。"""
    return python_for_task(TAG)


def _readback_tr(runner=None):
    """回读存储 /TR（公共层 readback_tr，task_name 注入本注册器）。"""
    return readback_tr(TASK_NAME, runner=runner)


def _tr_value(python: str, toast: bool = False) -> str:
    """/TR 值：嵌入引号包两个带空格安全的绝对路径 + --log 班次日志
    （--toast 再追加弹窗旗标——v3.34 opt-in，默认形态与 v3.33 逐字节
    一致，已有注册任务零漂移）。"""
    tr = f'"{python}" "{DIGEST_PY}" --log "{SHIFT_LOG}"'
    if toast:
        tr += " --toast"
    check_tr_length(tr)  # 261 上限 + 超长报错文案在公共层（超长宁可不注册）
    return tr


def register(at: str = DEFAULT_AT, runner=None, toast: bool = False) -> int:
    """注册/覆盖每日计划任务，返回退出码（0=注册成功承重生效）。

    toast=True 时 /TR 追加 --toast：每日晨报产出后弹 Windows 通知
    （digest.py --toast，通道与降级语义见 digest.py docstring）。
    """
    if not win32_guard(TAG, "（Linux 用 cron: "
                            "0 10 * * * python digest.py --log "
                            "state/shift_log.md）"):
        return 1
    try:
        tr = _tr_value(_python_for_task(), toast=toast)
    except ValueError as e:
        print(f"[digest_task] ERROR: {e}", file=sys.stderr)
        return 1
    argv = ["schtasks", "/Create", "/F", "/TN", TASK_NAME, "/TR", tr,
            "/SC", "DAILY", "/ST", at]
    proc = _run_schtasks(argv, runner=runner)
    if proc.returncode != 0:
        print(f"[digest_task] register FAILED {TASK_NAME}\n"
              f"  stdout: {_stream(proc, 'stdout').strip()}\n"
              f"  stderr: {_stream(proc, 'stderr').strip()}",
              file=sys.stderr)
        return 1
    # 回读验证（v3.36 自 hotlist_watch_task v3.35 移植；v3.37 收口公共层
    # verify_stored_tr）：schtasks /Create 会静默截断超长 /TR 且仍报
    # SUCCESS（本机实测 258 -> 254，悬崖 (250, 258]）——存储不一致响亮
    # exit 1，宁报错不留一个不按预期运行的假任务；无法回读只告警不判
    # 失败（「无法验证」不等于「验证失败」）。
    if not verify_stored_tr(TASK_NAME, tr, TAG, runner=runner):
        return 1
    print(f"[digest_task] registered {TASK_NAME} "
          f"(DAILY {at} -> digest 单发一轮，班次摘要进 shift_log"
          + ("，产出后弹 Windows 通知)" if toast else ")"))
    return 0


def status(runner=None) -> int:
    """查询任务状态；0=在场，1=缺失。"""
    if not win32_guard(TAG):
        return 1
    proc = _run_schtasks(["schtasks", "/Query", "/TN", TASK_NAME],
                         runner=runner)
    ok = proc.returncode == 0
    print(f"[digest_task] {TASK_NAME}: "
          f"{'installed' if ok else 'NOT INSTALLED'}")
    return 0 if ok else 1


def unregister(runner=None) -> int:
    """删除任务（一键回滚）；已不存在的任务视为删除成功（幂等）。

    单任务语义：本任务成败即返回值（watchdog 双任务版是循环删 +
    failed 聚合——语义差异承重，见公共层 docstring，不硬统一）。"""
    if not win32_guard(TAG):
        return 1
    proc = _run_schtasks(["schtasks", "/Delete", "/F", "/TN", TASK_NAME],
                         runner=runner)
    if proc.returncode != 0:
        if is_already_gone(proc):  # 中英文「不存在」三措辞匹配在公共层
            print(f"[digest_task] {TASK_NAME}: not installed (already gone)")
            return 0
        print(f"[digest_task] unregister FAILED {TASK_NAME}\n"
              f"  stdout: {_stream(proc, 'stdout').strip()}\n"
              f"  stderr: {_stream(proc, 'stderr').strip()}",
              file=sys.stderr)
        return 1
    print(f"[digest_task] unregistered {TASK_NAME}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="每日晨报 Windows 计划任务注册器")
    sub = parser.add_subparsers(dest="cmd", required=True)
    reg = sub.add_parser("register", help="注册/覆盖每日计划任务")
    reg.add_argument("--at", default=DEFAULT_AT,
                     help=f"每日触发时间 HH:MM（默认 {DEFAULT_AT}）")
    reg.add_argument("--toast", action="store_true",
                     help="/TR 追加 --toast：晨报产出后弹 Windows 通知")
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
