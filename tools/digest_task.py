#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Windows 计划任务注册器：把每日晨报挂成班次节拍（v3.33；v3.34 加
register --toast 接线本机通知；v3.36 加注册后回读验证 + 解码链收口）。

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
import re
import subprocess
import sys
from pathlib import Path

from _subproc_decode import decode_out as _decode  # noqa: E402

HERE = Path(__file__).resolve().parent
DIGEST_PY = HERE / "digest.py"
SHIFT_LOG = HERE / "chat-scraper" / "state" / "shift_log.md"

TASK_NAME = "ai-search-digest"
DEFAULT_AT = "10:00"   # 错峰：sogou-probe 09:30 -> hotlist-watch 09:45 -> digest 10:00
TR_MAX = 261           # schtasks /TR 值硬上限（超出报错不截断）


def _python_for_task() -> str:
    """计划任务用的解释器：优先 pythonw.exe（免闪窗），缺失回退并告警。"""
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if pythonw.is_file():
        return str(pythonw)
    print(f"[digest_task] warning: {pythonw} not found; "
          f"falling back to {exe} (console window will flash daily)",
          file=sys.stderr)
    return str(exe)


def _tr_value(python: str, toast: bool = False) -> str:
    """/TR 值：嵌入引号包两个带空格安全的绝对路径 + --log 班次日志
    （--toast 再追加弹窗旗标——v3.34 opt-in，默认形态与 v3.33 逐字节
    一致，已有注册任务零漂移）。"""
    tr = f'"{python}" "{DIGEST_PY}" --log "{SHIFT_LOG}"'
    if toast:
        tr += " --toast"
    if len(tr) > TR_MAX:
        # schtasks 对 /TR 有 261 字符硬上限；超长静默截断会注册出
        # 永远跑不起来的任务——宁可不注册
        raise ValueError(
            f"/TR too long ({len(tr)} > {TR_MAX}): {tr}\n"
            "把仓库挪到更短路径，或手工注册（schtasks /Create ...）")
    return tr


def _run_schtasks(argv, runner=None):
    if runner is None:
        proc = subprocess.run(argv, capture_output=True)
    else:
        proc = runner(argv, capture_output=True, text=True)
    proc.stdout, proc.stderr = _decode(proc.stdout), _decode(proc.stderr)
    return proc


def _stream(proc, name: str) -> str:
    return getattr(proc, name, None) or ""


def _readback_tr(runner=None):
    """回读任务存储的 Command+Arguments（schtasks /Query /XML）。

    返回拼接串；任务缺失/非零退出/XML 无 Command|Arguments 节点返回
    None（调用方按「无法验证」处理，不与「验证失败」混谈）。"""
    proc = _run_schtasks(
        ["schtasks", "/Query", "/TN", TASK_NAME, "/XML"], runner=runner)
    if proc.returncode != 0:
        return None
    xml = _stream(proc, "stdout")
    m_cmd = re.search(r"<Command>(.*?)</Command>", xml, re.S)
    m_arg = re.search(r"<Arguments>(.*?)</Arguments>", xml, re.S)
    if not (m_cmd and m_arg):
        return None
    return f"{m_cmd.group(1)} {m_arg.group(1)}"


def register(at: str = DEFAULT_AT, runner=None, toast: bool = False) -> int:
    """注册/覆盖每日计划任务，返回退出码（0=注册成功承重生效）。

    toast=True 时 /TR 追加 --toast：每日晨报产出后弹 Windows 通知
    （digest.py --toast，通道与降级语义见 digest.py docstring）。
    """
    if sys.platform != "win32":
        print("[digest_task] ERROR: Windows-only（Linux 用 cron: "
              "0 10 * * * python digest.py --log state/shift_log.md）",
              file=sys.stderr)
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
    # 回读验证（v3.36 自 hotlist_watch_task v3.35 移植）：schtasks
    # /Create 会静默截断超长 /TR 且仍报 SUCCESS（本机实测 258 -> 254，
    # 悬崖 (250, 258]）——存储不一致必须响亮报错，宁报错不留一个不按
    # 预期运行的假任务。空白不敏感比对（schtasks 拆 Command/Arguments
    # 时空格归属有出入），尾部截断必现形差异逃不掉。无法回读（任务缺
    # 失/XML 无节点）只告警不判失败——「无法验证」不等于「验证失败」。
    stored = _readback_tr(runner=runner)
    if stored is None:
        print("[digest_task] warning: 回读验证不可用（/Query XML"
              " 无法解析）——已注册但未经存储比对", file=sys.stderr)
    elif "".join(stored.split()) != "".join(tr.split()):
        print(f"[digest_task] ERROR: 回读验证失败——存储 /TR 与"
              f"预期不一致（schtasks 静默截断？预期 {len(tr)} 字符，"
              f"存得 {len(stored)} 字符）\n"
              f"  预期: {tr}\n  存储: {stored}\n"
              f"  任务可能不按预期运行——请缩短仓库路径后重注册，或手工"
              f"注册（schtasks /Create ...）",
              file=sys.stderr)
        return 1
    else:
        print(f"[digest_task] 回读验证通过（存储 {len(stored)}"
              f" 字符与预期一致）")
    print(f"[digest_task] registered {TASK_NAME} "
          f"(DAILY {at} -> digest 单发一轮，班次摘要进 shift_log"
          + ("，产出后弹 Windows 通知)" if toast else ")"))
    return 0


def status(runner=None) -> int:
    """查询任务状态；0=在场，1=缺失。"""
    if sys.platform != "win32":
        print("[digest_task] ERROR: Windows-only", file=sys.stderr)
        return 1
    proc = _run_schtasks(["schtasks", "/Query", "/TN", TASK_NAME],
                         runner=runner)
    ok = proc.returncode == 0
    print(f"[digest_task] {TASK_NAME}: "
          f"{'installed' if ok else 'NOT INSTALLED'}")
    return 0 if ok else 1


def unregister(runner=None) -> int:
    """删除任务（一键回滚）；已不存在的任务视为删除成功（幂等）。"""
    if sys.platform != "win32":
        print("[digest_task] ERROR: Windows-only", file=sys.stderr)
        return 1
    proc = _run_schtasks(["schtasks", "/Delete", "/F", "/TN", TASK_NAME],
                         runner=runner)
    if proc.returncode != 0:
        blob = f"{_stream(proc, 'stdout')}{_stream(proc, 'stderr')}"
        if ("does not exist" in blob or "不存在" in blob or "找不到" in blob):
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
