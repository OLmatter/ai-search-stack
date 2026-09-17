#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Windows 计划任务注册器：把 watchdog.py 挂成常驻（v3.28）。

两个任务（同一入口 watchdog.py，幂等——服务健康时秒退零动作）：
    ai-search-gbridge-boot       ONLOGON 登录自启（登录即拉起，不等首个巡检周期）
    ai-search-gbridge-watchdog   每 N 分钟巡检（默认 15；死亡恢复上限 = 巡检间隔）

子命令:
    register [--interval N]      注册/覆盖（/F）两个任务
    status                       查询两个任务状态
    unregister                   删除两个任务（一键回滚）

v3.37：schtask 机械件收口 tools/_schtasks_common.py（三注册器公共层
二次提炼），本文件只留 watchdog 特有件：双任务语义（MINUTE 承重 +
ONLOGON 可选降级、循环删 + failed 聚合）、/TR 构造、消息文案。

设计约束（test_v3280 钉死）:
    - /TR 用嵌入引号包绝对路径（Program Files 类带空格路径必须整串引住）；
      超 261 字符（schtasks /TR 硬上限）报错退出，不静默截断
    - 优先 pythonw.exe（计划任务跑 python.exe 每 15 分钟闪一次黑窗）；
      同目录没有 pythonw.exe 时回退 sys.executable 并 stderr 告警
    - watchdog.py 路径自治（__file__ 定位），任务无需设工作目录
    - 非 Windows 诚实报错退出（Linux 常驻用 cron @reboot，见 README）

用法:
    python watchdog_task.py register
    python watchdog_task.py status
    python watchdog_task.py unregister
"""
import argparse
import sys
from pathlib import Path

# 子进程输出解码公用模块（tools/_subproc_decode.py，v3.36 四方副本收口；
# 父目录注入 sys.path 取用——hotlist_watch_task v3.36 同款。GBK 解码
# 对 schtasks 输出是承重件，模块缺失响亮 ImportError 不静默降级）
_PARENT = str(Path(__file__).resolve().parent.parent)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)
from _subproc_decode import decode_out as _decode  # noqa: E402,F401
# ^ v3.36 四方 is 钉承重绑定（test_v3360）：_run_schtasks 收口公共层后
# 本文件不再直接消费 _decode，但别名绑定必须存活——身份断链=收口失败

# schtasks 机械件公共层（v3.37 自三注册器二次提炼）：run_schtasks/stream
# 签名不变同对象直引；python_for_task 签名带参（tag/cadence 注入——
# 本注册器高频跑，闪窗措辞 "on each run" 与单任务 "daily" 不同，参数
# 化不硬统一），下方 1 行委托包装保旧引用名零漂移
from _schtasks_common import (check_tr_length, is_already_gone,  # noqa: E402
                              python_for_task, win32_guard)
from _schtasks_common import stream as _stream  # noqa: E402
from _schtasks_common import run_schtasks as _run_schtasks  # noqa: E402

HERE = Path(__file__).resolve().parent
WATCHDOG_PY = HERE / "watchdog.py"

TAG = "watchdog_task"  # 消息前缀（公共层告警/报错注入）
TASK_BOOT = "ai-search-gbridge-boot"
TASK_WATCHDOG = "ai-search-gbridge-watchdog"
DEFAULT_INTERVAL = 15          # 分钟；死亡恢复上限 = 巡检间隔
# TR_MAX 由公共层 check_tr_length 承载（261 硬上限，本文件不再直引）

# 参照物：本机已有 ai-search-sogou-probe（v3.21 时代手工注册）——
# 本工具把注册/查询/卸载固化为可复跑脚本，命名沿用 ai-search- 前缀。


def _python_for_task() -> str:
    """计划任务用的解释器（公共层 python_for_task，前缀 + 高频闪窗
    措辞注入本注册器——每 N 分钟跑一次，非 daily）。"""
    return python_for_task(TAG, cadence="on each run")


def _tr_value(python: str, interval_required: bool = False) -> str:
    """/TR 值：嵌入引号包两个带空格安全的绝对路径。"""
    tr = f'"{python}" "{WATCHDOG_PY}"'
    check_tr_length(tr)  # 261 上限 + 超长报错文案在公共层（超长宁可不注册）
    return tr


def register(interval: int = DEFAULT_INTERVAL, runner=None) -> int:
    """注册/覆盖两个计划任务，返回退出码。

    退出码语义（承重任务定成败）：MINUTE 巡检任务注册失败 = 1（常驻
    未生效）；仅 ONLOGON 开机任务失败 = 0 + stderr 响亮降级告警——
    实测（2026-09-17）普通权限令牌注册 ONLOGON 触发器被系统拒绝
    （「拒绝访问」，限当前用户 + /IT 亦然），此时常驻由 MINUTE 巡检
    兜底：开机后 ≤interval 分钟内恢复。管理员会话重跑 register 可补上
    开机任务。
    """
    if not win32_guard(TAG, " (Linux 用 cron @reboot，"
                            "见 tools/google-bridge/README.md)"):
        return 1
    python = _python_for_task()
    try:
        tr = _tr_value(python)
    except ValueError as e:
        print(f"[watchdog_task] ERROR: {e}", file=sys.stderr)
        return 1
    # 先承重任务，后开机增强任务
    argv = ["schtasks", "/Create", "/F", "/TN", TASK_WATCHDOG, "/TR", tr,
            "/SC", "MINUTE", "/MO", str(interval)]
    proc = _run_schtasks(argv, runner=runner)
    if proc.returncode != 0:
        print(f"[watchdog_task] register FAILED (load-bearing) "
              f"{TASK_WATCHDOG}\n"
              f"  stdout: {_stream(proc, 'stdout').strip()}\n"
              f"  stderr: {_stream(proc, 'stderr').strip()}",
              file=sys.stderr)
        return 1
    print(f"[watchdog_task] registered {TASK_WATCHDOG} "
          f"(MINUTE {interval} — death recovery bound = interval)")
    # ONLOGON 开机即拉：增强项。被拒（无管理员）= 降级，不判失败
    argv_boot = ["schtasks", "/Create", "/F", "/TN", TASK_BOOT, "/TR", tr,
                 "/SC", "ONLOGON", "/RL", "LIMITED"]
    proc = _run_schtasks(argv_boot, runner=runner)
    if proc.returncode != 0:
        print(f"[watchdog_task] DEGRADED: boot task {TASK_BOOT} not "
              f"registered ({_stream(proc, 'stderr').strip() or 'rejected'})"
              f"——开机后由 MINUTE 巡检兜底恢复（≤{interval} 分钟）；"
              f"管理员会话重跑 register 可补上", file=sys.stderr)
    else:
        print(f"[watchdog_task] registered {TASK_BOOT} (ONLOGON)")
    return 0


def status(runner=None) -> int:
    """查询两个任务；0=承重任务在场（开机任务缺失只提示），1=承重任务缺失。"""
    if not win32_guard(TAG):
        return 1
    proc = _run_schtasks(
        ["schtasks", "/Query", "/TN", TASK_WATCHDOG], runner=runner)
    core = proc.returncode == 0
    print(f"[watchdog_task] {TASK_WATCHDOG}: "
          f"{'installed' if core else 'NOT INSTALLED (load-bearing)'}")
    proc = _run_schtasks(
        ["schtasks", "/Query", "/TN", TASK_BOOT], runner=runner)
    boot = proc.returncode == 0
    print(f"[watchdog_task] {TASK_BOOT}: "
          f"{'installed' if boot else 'not installed (optional, needs admin)'}")
    return 0 if core else 1


def unregister(runner=None) -> int:
    """删除两个任务（一键回滚）；已不存在的任务视为删除成功。

    双任务语义（与单任务注册器不硬统一的差异处）：循环逐删 +
    failed 聚合——任一任务真实失败整体 exit 1，「不存在」逐任务幂等
    但不计失败（单任务版本任务成败即返回值）。"""
    if not win32_guard(TAG):
        return 1
    failed = []
    for name in (TASK_BOOT, TASK_WATCHDOG):
        proc = _run_schtasks(
            ["schtasks", "/Delete", "/F", "/TN", name], runner=runner)
        if proc.returncode != 0:
            # 任务本就不存在 = 目标状态已达成，不算失败（幂等回滚）。
            # 中英文措辞三认（「系统找不到指定的文件」/does not exist/
            # 「找不到」）——匹配收口公共层 is_already_gone
            if is_already_gone(proc):
                print(f"[watchdog_task] {name}: not installed (already gone)")
            else:
                failed.append(name)
                print(f"[watchdog_task] unregister FAILED {name}\n"
                      f"  stdout: {_stream(proc, 'stdout').strip()}\n"
                      f"  stderr: {_stream(proc, 'stderr').strip()}",
                      file=sys.stderr)
        else:
            print(f"[watchdog_task] unregistered {name}")
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="google-bridge 看门狗 Windows 计划任务注册器")
    sub = parser.add_subparsers(dest="cmd", required=True)
    reg = sub.add_parser("register", help="注册/覆盖两个计划任务")
    reg.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                     help=f"巡检间隔分钟（默认 {DEFAULT_INTERVAL}）")
    sub.add_parser("status", help="查询任务状态")
    sub.add_parser("unregister", help="删除两个任务（回滚）")
    args = parser.parse_args()
    if args.cmd == "register":
        return register(interval=args.interval)
    if args.cmd == "status":
        return status()
    return unregister()


if __name__ == "__main__":
    sys.exit(main())
