#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""shift_log 班次行格式单一真源（v3.38 自四方副本收口）——`[YYYY-MM-DD
HH:MM]` 前缀的时间戳格式、行构造与行解析同住一处。

病灶同源（副本漂移是潜伏病，v3.36 解码链收口同款教训）：班次日志格式
此前以**逐字节等价**形态散落四处——
    - tools/doctor.py                _SHIFT_ENTRY_RE / _SHIFT_TIME_ONLY_RE
                                     （解析端：值班巡检趋势 _shift_log_stats）
    - tools/digest.py                _WATCH_LINE_RE（消费端解析：晨报取今日
                                     hotlist_watch 行）+ render_log_line
                                     （写入端：digest 班次摘要行）
    - tools/chat-scraper/hotlist_watch.py  render_log_line（写入端：监控
                                     环 diff 行）
统一收口本模块，四方改 import；旧引用名以别名保零漂移（doctor 的
_SHIFT_* 正则名、digest 的 _WATCH_LINE_RE 名仍按原名可用且是同一对象）。

跨解析器契约（供方/消费方都钉在本模块）:
    行 = `[YYYY-MM-DD HH:MM] 内容`（分钟级；前缀后方括号与内容间
    恰一空格）。写入端 make_line 固定该形态；解析端 ENTRY_RE 额外容忍
    `\s?`（零或一空格——append-only 手写流水，人工当场省空格也算数）。
    `仅时间` 变体 `[HH:MM]`（值班省写日期）只存在于人工行，由
    TIME_ONLY_RE 承接，机器行永不产出——doctor _shift_log_stats 用它
    继承上一条带日期条目的日期。
"""
import re
from datetime import datetime

__all__ = ["STAMP_FMT", "STAMP_RE", "ENTRY_RE", "TIME_ONLY_RE",
           "stamp", "make_line"]

# 分钟级时间戳 strftime 格式（写入端唯一来源）
STAMP_FMT = "%Y-%m-%d %H:%M"

# 前缀正则片段（未编译 str，供消费方合成工具专属行正则；日期捕获组
# =group 1）。digest._WATCH_LINE_RE 以它合成：rf"^{STAMP_RE} (hotlist_watch: .*)$"
STAMP_RE = r"\[(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}\]"

# 完整条目解析（doctor._shift_log_stats 主形态）：group 1=日期
# 2=HH:MM 3=内容；`\s?` 容忍方括号后零或一空格
ENTRY_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})\]\s?(.*)$")

# 仅时间条目解析（doctor._shift_log_stats 人工省写形态）：group 1=HH:MM
# 2=内容；日期继承上一条带日期条目（解析方职责，见 doctor）
TIME_ONLY_RE = re.compile(r"^\[(\d{2}:\d{2})\]\s?(.*)$")


def stamp(dt: datetime = None) -> str:
    """分钟级时间戳 "YYYY-MM-DD HH:MM"（dt 缺省=当前时刻）。"""
    return (dt or datetime.now()).strftime(STAMP_FMT)


def make_line(ts: str, body: str, max_len: int) -> str:
    """班次日志一行：`[YYYY-MM-DD HH:MM] 内容`。

    ts 取前 16 字符（写入方源时间戳可带秒，如 hotlist_watch 快照
    "%Y-%m-%d %H:%M:%S"，截到分钟对齐契约）；body 截 max_len（班次
    流水不刷屏——明细在快照文件与 stdout JSON 里）。
    """
    return f"[{ts[:16]}] {body[:max_len]}"
