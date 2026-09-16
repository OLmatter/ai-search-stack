#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Windows 本机弹窗通知公用模块（v3.35 自 digest.py 提取）——一条通道、
多个调用方消费。

通道选型（活体取证定案，2026-09-17 本机 win32 19045，v3.34 完整证据链
在 CHANGELOG 与 digest.py docstring，此处留承重结论）:
    * BurntToast：要 PSGallery 装模块=外部服务，拒；
    * msg.exe：对话框无自动超时（无人值守会堆积）+ Home 版缺失，拒；
    * WinRT toast（PowerShell 投影）：API 成功但实机双闸不可见——全局
      ToastEnabled=0 + SHQueryUserNotificationState=QN_QUIET_TIME（专
      注助手开，WNF 会话态不可靠改），三发零 banner 只进操作中心，不作
      主通道；
    * **WScript.Shell Popup（采用）**：powershell COM 内联单进程，
      64(信息图标)+4096(系统模态置顶)+自动超时——零模块零外部服务零凭
      据零临时文件，不受通知设置/专注助手任何影响（实机截图证据在案，
      超时自关 POPUP_RET=-1）。

契约（消费方各自拥有自己的弹窗文案构建，本模块只管通道）:
    send_toast(title, body) 尽力而为：任何失败只返回 fault dict 不抛
    ——通知是观测副本，绝不炸调用方已完成的产出轮。非 Windows 诚实
    skipped（Linux 自行接 notify-send，未实现）。子进程保险丝
    TOAST_SUBPROC_TIMEOUT(20s) > 弹窗自动超时 TOAST_TIMEOUT_S(12s)，
    承重关系由回归钉死——保险丝小于弹窗超时会误杀正常弹窗。

消费方:
    - digest.py（v3.34 起晨报 --toast；v3.35 起通道改由本模块供给，
      re-export 保旧引用名零漂移）
    - chat-scraper/hotlist_watch.py（v3.35 起 --toast：监控环 diff 出
      新增条目即时弹窗，不等 10:00 晨报）

实现纪律：send_toast 用 -EncodedCommand（UTF-16LE base64）内联
PowerShell——标题/正文任意中文引号零转义事故；子进程输出字节捕获 +
utf-8->gbk->replace 解码链（v3.28/v3.31/v3.34 三轮实机抓虫同款病灶：
中文 Windows 子进程输出含 GBK 字节，text=True 直接崩读线程；v3.36 起
链身共享 tools/_subproc_decode.py，四方副本收口，_decode_out 为别名
re-export 保旧引用名与身份一致）。
"""
import base64
import os
import re
import subprocess
import sys
from typing import Callable, Dict, List, Optional

from _subproc_decode import decode_out as _decode_out  # noqa: E402

__all__ = ["send_toast", "_ps_quote", "_decode_out", "_default_toast_runner",
           "TOAST_TIMEOUT_S", "TOAST_BOX_TYPE", "TOAST_SUBPROC_TIMEOUT",
           "TOAST_BODY_MAX"]

# 弹窗通道常量（v3.34 定案值原样迁移；承重关系见模块 docstring）
TOAST_TIMEOUT_S = 12     # 弹窗自动关闭秒数（无人值守不堆积对话框）
TOAST_BOX_TYPE = 64 + 4096   # 64=信息图标 + 4096=系统模态置顶
TOAST_SUBPROC_TIMEOUT = 20   # powershell 子进程保险丝（弹窗超时 12s + 裕量）
TOAST_BODY_MAX = 240     # 弹窗正文上限（弹窗不是数据转储）


def _ps_quote(text: str) -> str:
    """PowerShell 单引号字面量转义（' → ''，换行折叠空格，截断上限）。"""
    t = (text or "").replace("\r", " ").replace("\n", " ")
    return t[:TOAST_BODY_MAX].replace("'", "''")


def _default_toast_runner(argv: List[str]):
    proc = subprocess.run(
        argv, capture_output=True,
        timeout=TOAST_SUBPROC_TIMEOUT,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    proc.stdout, proc.stderr = _decode_out(proc.stdout), _decode_out(proc.stderr)
    return proc


def send_toast(title: str, body: str, timeout_s: Optional[int] = None,
               runner: Optional[Callable] = None,
               platform: Optional[str] = None) -> Dict:
    """弹一个 Windows 系统模态通知框（WScript.Shell Popup，自动超时）。

    返回 {status: sent|skipped|fault, return?, error?}。尽力而为：任何
    失败都只返回 fault 不抛——通知是观测副本，绝不炸调用方已完成的轮。
    非 Windows 平台诚实 skipped（Linux 自行接 notify-send，未实现）。
    """
    if (platform if platform is not None else sys.platform) != "win32":
        return {"status": "skipped",
                "error": "非 Windows——弹窗通道不可用（观察者自接通知）"}
    secs = TOAST_TIMEOUT_S if timeout_s is None else int(timeout_s)
    # -EncodedCommand（UTF-16LE base64）：标题/正文任意中文引号零转义事故
    ps = ("$w = New-Object -ComObject WScript.Shell; "
          f"$r = $w.Popup('{_ps_quote(body)}', {secs}, "
          f"'{_ps_quote(title)}', {TOAST_BOX_TYPE}); "
          "Write-Output ('POPUP_RET=' + $r)")
    enc = base64.b64encode(ps.encode("utf-16-le")).decode("ascii")
    argv = ["powershell", "-NoProfile", "-NonInteractive",
            "-EncodedCommand", enc]
    try:
        proc = (runner or _default_toast_runner)(argv)
    except Exception as e:                       # noqa: BLE001 —— 尽力而为
        return {"status": "fault",
                "error": f"{type(e).__name__}: {e}"[:200]}
    if proc.returncode != 0:
        err = (getattr(proc, "stderr", "") or "")[:160]
        return {"status": "fault",
                "error": f"powershell exit {proc.returncode}: {err}"}
    ret = None
    m = re.search(r"POPUP_RET=(-?\d+)", getattr(proc, "stdout", "") or "")
    if m:
        ret = int(m.group(1))
    return {"status": "sent", "return": ret}
