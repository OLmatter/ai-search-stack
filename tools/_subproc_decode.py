#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""子进程输出解码公用模块（v3.36 自四方副本收口）——utf-8 严格 ->
gbk 严格 -> replace 兜底，不做 locale 猜测。

病灶同源（v3.28/v3.31/v3.34 三轮实机抓虫，同一链条反复复发）：中文
Windows 的子进程输出（schtasks/powershell）是 GBK 字节；Anaconda
python 在 Git Bash 下 locale 首选编码报 utf-8，text=True 直接按它解
会崩读线程——字节层收包 + 显式回退链解码是唯一稳态。

v3.36 收口史（副本漂移是潜伏病：改一处漏三处）：同一链条此前在四个
文件各有一份**逐字节等价**副本——
    - tools/toast.py                    _decode_out（v3.34 自 digest.py 提取）
    - tools/digest_task.py              _decode
    - tools/chat-scraper/hotlist_watch_task.py  _decode
    - tools/google-bridge/watchdog_task.py      _decode
统一收口本模块，四方改 import；各处旧引用名以别名保零漂移
（toast._decode_out / 各注册器 task._decode 仍按原名调用，且是同一
函数对象——test_v3360 以 is 身份钉四方同源）。
"""

__all__ = ["decode_out"]


def decode_out(raw) -> str:
    """子进程输出解码：utf-8 严格 -> gbk 严格 -> replace 兜底。

    - None -> ""（空流安全，pythonw/console-less 场景）
    - 已是 str 原样透传（runner 注入 text=True 形态）
    - bytes 先按 utf-8 严格解，失败再按 gbk 严格解（中文 Windows
      实测主路径），双败 replace 兜底（\\ufffd 可见化，不抛不崩）
    """
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
