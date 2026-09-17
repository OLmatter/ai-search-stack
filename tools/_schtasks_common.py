#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Windows 计划任务注册器公共层（v3.37 自三注册器二次提炼）。

消费方（三注册器）：
    - tools/digest_task.py                  （单任务 ai-search-digest）
    - tools/chat-scraper/hotlist_watch_task.py（单任务 ai-search-hotlist-watch）
    - tools/google-bridge/watchdog_task.py  （双任务 boot+watchdog 循环）

v3.37 收口史（v3.36 解码链四方收口的同思路下一环——副本漂移是潜伏病）：
此前三份**功能等价**副本散落各注册器——
    - _python_for_task（pythonw 优先/缺失回退告警）×3
    - _run_schtasks（字节层收包 + _decode 解码 + runner 注入）×3
    - _stream（None 安全取 stdout/stderr）×3
    - _readback_tr（/Query /XML 回读 Command+Arguments）×2
      （digest_task v3.36 自 hotlist_watch_task v3.35 移植所致）
    - register 内回读验证块（warn/ERROR/pass 三态）×2
    - unregister「不存在」幂等匹配（does not exist/不存在/找不到 三措辞）×3
    - /TR 261 硬上限 + 超长报错 ×3
    - 非 win32 平台守卫 ×7 处
统一收口本模块；差异处**参数化不硬统一**：
    - 消息前缀 tag（[digest_task]/[hotlist_watch_task]/[watchdog_task]）
    - pythonw 缺失告警的闪窗频率措辞 cadence（daily vs on each run——
      watchdog 每 N 分钟跑一次，"daily" 对它不真）
    - readback/验证的 task_name
    - unregister 的**控制流不收口**：单任务版失败即返回码；watchdog 双
      任务版循环删 + failed 聚合（任一真实失败整体 exit 1）——语义差异
      承重，只共享 is_already_gone 谓词，不硬统一成一种循环
旧引用名零漂移：各注册器以 `from _schtasks_common import run_schtasks
as _run_schtasks` 同对象直引（test_v3370 以 is 钉），签名有变的
（_python_for_task/_readback_tr）留 1 行委托包装保旧签名。

GBK 解码对 schtasks 输出是承重件（v3.28/v3.31/v3.34 三轮实机抓虫），
本模块经 tools/_subproc_decode.py 取 _decode；unregister 的幂等匹配
依赖解码正确。模块缺失响亮 ImportError 不静默降级。
"""
import re
import subprocess
import sys

from _subproc_decode import decode_out as _decode  # noqa: F401 (再导出：
# 消费方旧引用名 _decode 经本模块亦可取——主路径仍是各注册器直引
# _subproc_decode，见 test_v3360 四方 is 钉，本行不改变任何绑定)

TR_MAX = 261  # schtasks /TR 值硬上限（超出报错不截断）

__all__ = ["TR_MAX", "python_for_task", "run_schtasks", "stream",
           "readback_tr", "verify_stored_tr", "is_already_gone",
           "check_tr_length", "win32_guard"]


def python_for_task(tag: str, cadence: str = "daily") -> str:
    """计划任务用的解释器：优先 pythonw.exe（免闪窗），缺失回退并告警。

    tag 进告警前缀；cadence 是闪窗频率措辞（单任务注册器 "daily"，
    watchdog 类高频任务传 "on each run"——文案对任务真，不硬统一）。
    """
    from pathlib import Path
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if pythonw.is_file():
        return str(pythonw)
    print(f"[{tag}] warning: {pythonw} not found; "
          f"falling back to {exe} (console window will flash {cadence})",
          file=sys.stderr)
    return str(exe)


def run_schtasks(argv, runner=None):
    """跑 schtasks 并返回 stdout/stderr 已解码为 str 的结果（runner 可注入）。

    字节层收包 + 显式回退链解码（_decode，共享 tools/_subproc_decode.py）
    ——不用 text=True 的 locale 猜测（实测崩读线程）。unregister 的幂等
    匹配（「不存在」/does not exist）依赖解码正确。
    """
    if runner is None:
        proc = subprocess.run(argv, capture_output=True)
    else:
        proc = runner(argv, capture_output=True, text=True)
    proc.stdout, proc.stderr = _decode(proc.stdout), _decode(proc.stderr)
    return proc


def stream(proc, name: str) -> str:
    """None 安全取 stdout/stderr 文本。"""
    return getattr(proc, name, None) or ""


def readback_tr(task_name: str, runner=None):
    """回读任务存储的 Command+Arguments（schtasks /Query /XML）。

    返回拼接串；任务缺失/非零退出/XML 无 Command|Arguments 节点返回
    None（调用方按「无法验证」处理，不与「验证失败」混谈）。"""
    proc = run_schtasks(
        ["schtasks", "/Query", "/TN", task_name, "/XML"], runner=runner)
    if proc.returncode != 0:
        return None
    xml = stream(proc, "stdout")
    m_cmd = re.search(r"<Command>(.*?)</Command>", xml, re.S)
    m_arg = re.search(r"<Arguments>(.*?)</Arguments>", xml, re.S)
    if not (m_cmd and m_arg):
        return None
    return f"{m_cmd.group(1)} {m_arg.group(1)}"


def verify_stored_tr(task_name: str, expected: str, tag: str,
                     runner=None) -> bool:
    """注册后回读验证（v3.35 实机抓虫对策：/Create 会静默截断超长 /TR
    且仍报 SUCCESS，悬崖实测 (250, 258]——存储不一致必须响亮报错，宁
    报错不留一个不按预期运行的假任务）。

    空白不敏感比对（schtasks 拆 Command/Arguments 时空格归属有出入），
    尾部截断必现形差异逃不掉。返回值：
        True  = 验证通过，或无法回读（任务缺失/XML 解析不出——只告警
                不判失败，「无法验证」不等于「验证失败」）
        False = 存储与预期不一致（已 ERROR，调用方 exit 1）
    """
    stored = readback_tr(task_name, runner=runner)
    if stored is None:
        print(f"[{tag}] warning: 回读验证不可用（/Query XML"
              " 无法解析）——已注册但未经存储比对", file=sys.stderr)
    elif "".join(stored.split()) != "".join(expected.split()):
        print(f"[{tag}] ERROR: 回读验证失败——存储 /TR 与"
              f"预期不一致（schtasks 静默截断？预期 {len(expected)} 字符，"
              f"存得 {len(stored)} 字符）\n"
              f"  预期: {expected}\n  存储: {stored}\n"
              f"  任务可能不按预期运行——请缩短仓库路径后重注册，或手工"
              f"注册（schtasks /Create ...）",
              file=sys.stderr)
        return False
    else:
        print(f"[{tag}] 回读验证通过（存储 {len(stored)}"
              f" 字符与预期一致）")
    return True


def is_already_gone(proc) -> bool:
    """unregister 幂等匹配：删除失败但任务本就不存在 = 目标状态已达成。

    中文 schtasks 实测措辞「系统找不到指定的文件」，英文 "does not
    exist"——三个措辞都要认（三注册器逐字一致副本收口于此）。
    """
    blob = f"{stream(proc, 'stdout')}{stream(proc, 'stderr')}"
    return ("does not exist" in blob or "不存在" in blob
            or "找不到" in blob)


def check_tr_length(tr: str) -> None:
    """/TR 261 硬上限守卫：超长抛 ValueError（宁可不注册，不让
    schtasks 静默截断出一个永远跑不起来的任务）。"""
    if len(tr) > TR_MAX:
        raise ValueError(
            f"/TR too long ({len(tr)} > {TR_MAX}): {tr}\n"
            "把仓库挪到更短路径，或手工注册（schtasks /Create ...）")


def win32_guard(tag: str, suffix: str = "") -> bool:
    """非 Windows 诚实报错退出。返回 True=win32 可继续；False=非 win32
    （已 ERROR 打印，调用方 return 1）。suffix 是 Linux 替代方案提示
    （各注册器 cron 形态不同，逐字透传不硬统一）。"""
    if sys.platform != "win32":
        print(f"[{tag}] ERROR: Windows-only{suffix}", file=sys.stderr)
        return False
    return True
