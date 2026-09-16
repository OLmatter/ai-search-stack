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
import subprocess
import sys
from pathlib import Path

# 子进程输出解码公用模块（tools/_subproc_decode.py，v3.36 四方副本收口；
# 父目录注入 sys.path 取用——hotlist_watch_task v3.36 同款。GBK 解码
# 对 schtasks 输出是承重件，模块缺失响亮 ImportError 不静默降级）
_PARENT = str(Path(__file__).resolve().parent.parent)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)
from _subproc_decode import decode_out as _decode  # noqa: E402

HERE = Path(__file__).resolve().parent
WATCHDOG_PY = HERE / "watchdog.py"

TASK_BOOT = "ai-search-gbridge-boot"
TASK_WATCHDOG = "ai-search-gbridge-watchdog"
DEFAULT_INTERVAL = 15          # 分钟；死亡恢复上限 = 巡检间隔
TR_MAX = 261                   # schtasks /TR 值硬上限（超出报错不截断）

# 参照物：本机已有 ai-search-sogou-probe（v3.21 时代手工注册）——
# 本工具把注册/查询/卸载固化为可复跑脚本，命名沿用 ai-search- 前缀。


def _python_for_task() -> str:
    """计划任务用的解释器：优先 pythonw.exe（免闪窗），缺失回退并告警。"""
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if pythonw.is_file():
        return str(pythonw)
    print(f"[watchdog_task] warning: {pythonw} not found; "
          f"falling back to {exe} (console window will flash on each run)",
          file=sys.stderr)
    return str(exe)


def _tr_value(python: str, interval_required: bool = False) -> str:
    """/TR 值：嵌入引号包两个带空格安全的绝对路径。"""
    tr = f'"{python}" "{WATCHDOG_PY}"'
    if len(tr) > TR_MAX:
        # schtasks 对 /TR 有 261 字符硬上限；超长静默截断会注册出
        # 永远跑不起来的任务——宁可不注册
        raise ValueError(
            f"/TR too long ({len(tr)} > {TR_MAX}): {tr}\n"
            "把仓库挪到更短路径，或手工注册（schtasks /Create ...）")
    return tr


def _run_schtasks(argv, runner=None):
    """跑 schtasks 并返回 stdout/stderr 已解码为 str 的结果（runner 可注入）。

    字节层收包 + 显式回退链解码（见 _decode，共享 tools/_subproc_decode.py）
    ——不用 text=True 的 locale 猜测（实测崩读线程）。unregister 的幂等
    匹配（「不存在」/does not exist）依赖解码正确。
    """
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


def register(interval: int = DEFAULT_INTERVAL, runner=None) -> int:
    """注册/覆盖两个计划任务，返回退出码。

    退出码语义（承重任务定成败）：MINUTE 巡检任务注册失败 = 1（常驻
    未生效）；仅 ONLOGON 开机任务失败 = 0 + stderr 响亮降级告警——
    实测（2026-09-17）普通权限令牌注册 ONLOGON 触发器被系统拒绝
    （「拒绝访问」，限当前用户 + /IT 亦然），此时常驻由 MINUTE 巡检
    兜底：开机后 ≤interval 分钟内恢复。管理员会话重跑 register 可补上
    开机任务。
    """
    if sys.platform != "win32":
        print("[watchdog_task] ERROR: Windows-only (Linux 用 cron @reboot，"
              "见 tools/google-bridge/README.md)", file=sys.stderr)
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
    if sys.platform != "win32":
        print("[watchdog_task] ERROR: Windows-only", file=sys.stderr)
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
    """删除两个任务（一键回滚）；已不存在的任务视为删除成功。"""
    if sys.platform != "win32":
        print("[watchdog_task] ERROR: Windows-only", file=sys.stderr)
        return 1
    failed = []
    for name in (TASK_BOOT, TASK_WATCHDOG):
        proc = _run_schtasks(
            ["schtasks", "/Delete", "/F", "/TN", name], runner=runner)
        if proc.returncode != 0:
            # 任务本就不存在 = 目标状态已达成，不算失败（幂等回滚）。
            # 中文 schtasks 的措辞是「系统找不到指定的文件」（实测），
            # 英文是 "does not exist"——三个措辞都要认
            blob = f"{_stream(proc, 'stdout')}{_stream(proc, 'stderr')}"
            if ("does not exist" in blob or "不存在" in blob
                    or "找不到" in blob):
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
