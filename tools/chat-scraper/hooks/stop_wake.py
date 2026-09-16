#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stop 钩子：worker 想收工时检查派工队列——有活就拦截停止、唤醒 worker
继续；没活放行（正常收工）。派工文件：~/.zcode/worker_queue.json
（{"instructions": "要继续做的事"}）。

v3.19.0 领活固定入口强制条款（三轮互踩实证后的根因修复）：
- 被本钩子唤醒后，领活只此一法：调 ``worker_queue.acquire()``（认领 +
  读队列一步完成）。返回 skipped = 活归别人（owner 可见），直接收工、
  不要碰队列；claimed 才有 instructions 可干，干完 complete()+clear()。
- 禁止绕过入口直接读 worker_queue.json 干活——v3.16 / v3.17 / v3.18
  三轮并行互踩实证（848065c 与并行班次工作树编辑逐字一致为铁证）：
  机制在库里、调用路径在各 worker 的习惯里，等于没修。
- 已被有效认领的活不再唤醒第二个 worker——互踩预防在唤醒层收口；
  持有者异常死亡由认领超时（30 分钟无 complete）自然解封，解封后
  本钩子恢复拦截、下一个 worker 走 acquire() 接管。

v3.22.0 append-only 决策日志（消除 v3.21 声明的观察盲区）：
- 每次触发（main 入口）追加一行 JSONL 到 ``~/.zcode/stop_wake_decisions.jsonl``：
  {"ts": 本地 ISO 时间, "decision": "block"|"pass", "reason": 原因}——
  block 时 reason 为注入收工的完整文本；pass 时为归因标签
  （no_queue / empty_queue / module_unreachable / valid_claim）。
- 日志从属职责：append-only（只追加不改写不轮转）、任何写日志异常
  （磁盘满/权限/路径失效）一律吞掉，绝不影响决策与退出码——hook 的
  主职责是收工决策，日志写不出来不能把收工也卡死。
- 日志文件在 ~/.zcode（仓库外），gitignore 不适用；上游证据链从此
  不再被迫全走间接推断（v3.21 审计遗留项）。

真源与部署：本文件真源在 ai-search-stack 仓库
``tools/chat-scraper/hooks/stop_wake.py``（改动先改真源再部署副本到
``~/.zcode/hooks/stop_wake.py``，旧版先备份）。worker_queue 模块从仓库
探测 import（环境变量 AI_SEARCH_STACK_CHAT_SCRAPER 优先，常见位置
glob 兜底）；探测失败 → 放行 + stderr 警告（可见降级：hook 静默阻断
收工是更严重故障，且此时强制条款文档同样不可达，保守放行）。

ZCode Stop hook 契约：stdout 输出 {"decision": "block", "reason": ...}
即拦截收工并把 reason 作为新指令注入；任何异常都不阻断收工（exit 0）。
"""
import glob
import json
import os
import sys
from datetime import datetime

QUEUE = os.path.join(os.path.expanduser("~"), ".zcode", "worker_queue.json")
LOG = os.path.join(os.path.expanduser("~"),
                   ".zcode", "stop_wake_decisions.jsonl")

_UNSET = object()   # should_block 的 wq 哨兵：不传=自动探测；None=强制不可达
                    # （离线测试"探测失败放行"路径用，不依赖真实环境）

# pass 归因标签（决策日志用；should_block 兼容层不暴露）
_PASS_NO_QUEUE = "no_queue"                # 队列文件不存在
_PASS_EMPTY = "empty_queue"                # 队列无活（空/损坏/字段异常）
_PASS_UNREACHABLE = "module_unreachable"   # worker_queue 模块探测失败
_PASS_VALID_CLAIM = "valid_claim"          # 有活且被有效认领（不互踩）


def _chat_scraper_dirs():
    """worker_queue 模块候选目录：环境变量优先，仓库常见位置兜底。"""
    dirs = []
    env = os.environ.get("AI_SEARCH_STACK_CHAT_SCRAPER")
    if env:
        dirs.append(env)
    home = os.path.expanduser("~")
    dirs.extend(glob.glob(os.path.join(
        home, "Desktop", "项目", "ai-search-stack*", "ai-search-stack",
        "tools", "chat-scraper")))
    return dirs


def _load_wq():
    """探测 import 仓库 worker_queue 模块；失败返回 None（可见降级）。"""
    for d in _chat_scraper_dirs():
        if os.path.isdir(d) and d not in sys.path:
            sys.path.insert(0, d)
    try:
        import worker_queue as wq
        return wq
    except ImportError:
        return None


def _read_instructions(queue_path):
    """容错读队列：缺失/损坏/字段异常返回空串（读不出来 = 无活可展示）。"""
    try:
        with open(queue_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    val = data.get("instructions")
    return val.strip() if isinstance(val, str) else ""


def _decide(queue_path=QUEUE, wq=_UNSET):
    """内部决策（决策日志的归因来源）：返回 (block, reason)。

    - block=True：reason 为注入收工的完整 block 文本（含 instructions
      与领活固定入口强制条款）
    - block=False：reason 为 pass 归因标签（模块级常量，供决策日志）
    """
    if not os.path.exists(queue_path):
        return False, _PASS_NO_QUEUE
    if wq is _UNSET:
        wq = _load_wq()
    if wq is None:
        return False, _PASS_UNREACHABLE
    instructions = _read_instructions(queue_path)
    if not instructions:
        return False, _PASS_EMPTY
    marker = wq.read_claim(queue_path)
    if marker is not None and marker["age_s"] < wq.DEFAULT_CLAIM_TIMEOUT_S:
        return False, _PASS_VALID_CLAIM    # 活有主且未超时；marker None（无标记/损坏）或超时 → block
    return (True,
            f"[派工队列] {instructions}\n"
            "领活强制条款：先调 worker_queue.acquire() 认领（认领+读队列"
            "一步完成）；返回 skipped = 活归别人，直接收工不要碰队列；"
            "claimed 才可干活，干完 complete()+clear()。禁止绕过入口直接"
            "读 worker_queue.json 干活（三轮并行互踩实证）。")


def should_block(queue_path=QUEUE, wq=_UNSET):
    """决策函数（可离线测试；v3.19 语义不变的兼容层）：None=放行收工；
    str=block 理由（自带强制条款）。归因标签版决策见 ``_decide``。

    语义：
    - 队列不存在 / 无活 → 放行
    - wq 模块不可达 → 放行（调用方 main 负责 stderr 警告，此处不重复）
    - 有活 + 有效认领存在（未超时）→ 放行：活已被某个 worker 持有，
      唤醒第二个就是制造互踩；本钩子无法识别持有者身份（hook 是独立
      进程，pid 不是 worker 的），故任何有效认领一视同仁
    - 有活 + 无认领 / 超时 / 损坏标记 → block，理由文本含 instructions
      与领活固定入口强制条款（worker 被唤醒第一眼即见条款）
    """
    block, reason = _decide(queue_path, wq=wq)
    return reason if block else None


def _log_decision(block, reason, log_path=None):
    """append-only 决策日志：每次触发一行 JSONL
    {"ts", "decision": "block"|"pass", "reason"}（ts=本地 ISO 带时区）。

    从属职责：只追加、不改写、不轮转；任何异常一律吞掉——日志失败
    绝不影响决策与退出码（主职责优先，v3.22.0 纪律）。log_path 供
    离线测试注入临时路径；None=运行期取模块级 LOG（monkeypatch 可见）。
    """
    if log_path is None:
        log_path = LOG
    try:
        rec = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"),
               "decision": "block" if block else "pass",
               "reason": reason}
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def main():
    wq = _load_wq()
    block, reason = _decide(QUEUE, wq=wq)
    _log_decision(block, reason)           # 决策日志（失败吞掉，见上）
    if block:
        print(json.dumps({"decision": "block", "reason": reason},
                         ensure_ascii=False))
    elif wq is None and os.path.exists(QUEUE):
        print("stop_wake: worker_queue 模块探测失败，认领检查跳过（放行）",
              file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
