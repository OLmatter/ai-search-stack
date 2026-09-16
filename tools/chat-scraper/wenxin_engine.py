#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""文心 AI 搜索引擎（wenxin.baidu.com / chat.baidu.com）—— 低频高质量 AI 信号源。

定位（v3.7）:
    返回的是「文心一言对 query 的 AI 回答（markdown）+ 它引用了哪些网页」，
    用于两类信号：AI 认可度（答案里怎么评价 query 主体）与引用发现
    （referenceList 是百度搜索后端给出的来源页，常含常规搜索引擎漏掉的直链）。
    一次 search() = 一条聚合结果行（不是列表）。

协议（2026-09-10 侦察实测，证据存 .scratch/r6/，p2 脚本为移植蓝本）:
    - 页面是纯 SPA 壳，真正端点：POST https://chat.baidu.com/aichat/api/conversation，
      JSON 体（query 在 message.query[0].data.text.query），响应为 SSE 流。
    - SSE 解析：event:basedata（lid/baiduid/chatHitKunlun）→ 增量 event:message：
      * component=="markdown-yiyan" 的 data.value 顺序拼接 = AI 答案 markdown
      * component=="thinkingSteps" 的 data.referenceList[] = 引用
        （url / text=标题 / abstract / source=站名）
      * metaData.state=="generate-complete" 且 endTurn:true = 结束
    - 风控（如实信号，绝不伪装真空）:
      * SSE 首块 status:1005 + basedata chatHitKunlun:"kunlun_popup" = 配额/风控
        熔断（页面会 302 到 wappass 图形验证码）→ WenxinQuotaError(slug=wenxin_quota)
      * status:1001 + hints.parts[].type="tokenFail" = token 失败 →
        WenxinTokenError(slug=wenxin_token_fail)——文心 token 绑定浏览器运行时
        （hector 反爬链现算，纯 HTTP 无法自造合法 token，5 连复现全败为证），
        报此错说明当前前端版本下 token 机制已变，需重新逆向前端 bundle。

为什么必须走浏览器（camoufox 无头）:
    chat_token 由页面内 JS（hector 反爬链）结合会话身份现算、服务端校验，
    st/lid 与浏览器会话深度绑定——纯 HTTP 复现 5 连败（repro1-5 全 token check
    fail）。camoufox 无头提交搜索即可：token 在浏览器内自动合法。

配额纪律（硬约束，实测：新身份第 1 次搜索成功、第 2 次起 1005；IP 热度累积后
新身份第 1 次即 1005）:
    1. 每个浏览器身份约只够 1 次搜索——每次调用都用全新 context，身份用完即弃；
    2. 两次调用间隔保持小时级，不要连续调用；
    3. 见 1005 立即熔断：本 IP 的全部文心调用进入长冷却（默认 6 小时，env
       CHAT_SCRAPER_WENXIN_COOLDOWN_H 可调），冷却期内直接报 wenxin_quota，
       不再起浏览器。熔断状态落盘 state/wenxin_breaker.json（进程重启也生效）。
    因此本引擎不可当关键路径依赖：熔断是常态而非异常。

用法:
    from wenxin_engine import search
    row = search("智谱 GLM Coding Plan")   # 单条聚合行（出错时见 on_error）

    CLI:
    python wenxin_engine.py "智谱 GLM Coding Plan"

错误协议（与仓库其他工具一致）:
    on_error="report"（默认）: 返回错误记录 dict
        {"error": "wenxin_quota: ...", "tool": "chat-scraper",
         "query": q, "platform": "wenxin"}
    on_error="raise" 抛出（门面路由走这条，由门面统一兜错误记录）;
    on_error="empty" 返回 {}（兼容旧行为；注意 {} 不是真空证据）。

离线测试边界: camoufox 浏览器交互（起浏览器/提交/截流）不进离线测试——
    真浏览器 + 真配额 + 时序不确定，离线环境不可复现；离线测试只覆盖纯函数
    （SSE 解析、熔断器状态机、on_error 三态、环境变量解析）。
"""
import argparse
import json
import math
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional

__all__ = ["search", "parse_sse", "WenxinError", "WenxinQuotaError",
           "WenxinTokenError"]

_TOOL = "chat-scraper"
_PLATFORM = "wenxin"
_HOME_URL = "https://wenxin.baidu.com/"
_CONVERSATION_URL = "chat.baidu.com/aichat/api/conversation"
_WAPPASS_MARK = "wappass.baidu.com"
ANSWER_MAX_CHARS = 4000     # answer 截断上限（完整答案通常 1-2k 字符）
ABSTRACT_MAX_CHARS = 500    # 单条引用摘要截断上限（原始可到 ~1k）
TIMEOUT_POLL_S = 2.0        # 页面文本稳定轮询间隔（秒）
TIMEOUT_STABLE_ROUNDS = 4   # 连续 N 轮文本长度不变视为流结束（p2 实测参数）
HOME_SETTLE_S = 5.0         # 首页加载后等 SPA 挂载输入框的时间

ENV_COOLDOWN_H = "CHAT_SCRAPER_WENXIN_COOLDOWN_H"
DEFAULT_COOLDOWN_H = 6.0

_STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
BREAKER_PATH = os.path.join(_STATE_DIR, "wenxin_breaker.json")


class WenxinError(Exception):
    """文心引擎错误基类（slug 进错误记录的 error 前缀）。"""

    slug = "wenxin_error"


class WenxinQuotaError(WenxinError):
    """配额/风控熔断（1005/kunlun_popup/wappass）。已触发本 IP 长冷却。"""

    slug = "wenxin_quota"


class WenxinTokenError(WenxinError):
    """token 失败（1001/tokenFail）——前端 token 机制随版本漂移，需重新逆向。"""

    slug = "wenxin_token_fail"


class WenxinDependencyError(WenxinError):
    """camoufox 未安装。"""

    slug = "wenxin_dependency_missing"


class WenxinTimeoutError(WenxinError):
    """流式回答在 timeout_s 内未完成。"""

    slug = "wenxin_timeout"


# ---------------------------------------------------------------- 熔断器
# 模块级状态（进程内权威）；另落盘 state/wenxin_breaker.json 让 CLI 一次性
# 调用与 MCP 常驻进程共享冷却期——见 1005 熔断的是「本 IP」，不是本进程。
_breaker_open_until = 0.0


def _cooldown_seconds() -> float:
    """env CHAT_SCRAPER_WENXIN_COOLDOWN_H（小时，可小数），非法值回退默认。"""
    raw = os.environ.get(ENV_COOLDOWN_H, "")
    try:
        hours = float(raw) if raw else DEFAULT_COOLDOWN_H
    except ValueError:
        return DEFAULT_COOLDOWN_H * 3600.0
    if not math.isfinite(hours) or hours < 0:   # inf 会写出非 RFC JSON 且=永久熔断
        return DEFAULT_COOLDOWN_H * 3600.0
    return hours * 3600.0


def _breaker_is_open() -> bool:
    """冷却期内返回 True。进程内状态优先；为 0 时尝试读盘上状态。"""
    global _breaker_open_until
    if _breaker_open_until > time.time():
        return True
    if _breaker_open_until:      # 已过期：清零（审查 v3.7 #2：先取盘上 max，
        # 防本进程的短冷却清掉其他进程刚写入的更长冷却）
        persisted = _breaker_load()
        _breaker_open_until = 0.0
        if persisted > time.time():
            _breaker_open_until = persisted
            return True
        _breaker_persist(0.0)
        return False
    persisted = _breaker_load()
    if persisted > time.time():
        _breaker_open_until = persisted
        return True
    return False


def _breaker_remaining_s() -> float:
    return max(0.0, (_breaker_open_until or _breaker_load()) - time.time())


def _breaker_load() -> float:
    try:
        with open(BREAKER_PATH, encoding="utf-8") as f:
            return float(json.load(f).get("open_until") or 0.0)
    except Exception:
        return 0.0    # 没有文件/损坏 = 未熔断（fail-open；再遇 1005 会重新落盘）


def _breaker_persist(open_until: float, reason: str = "") -> None:
    """best-effort 落盘：文件系统只读等场景静默放弃（进程内状态仍然生效）。"""
    try:
        os.makedirs(_STATE_DIR, exist_ok=True)
        tmp = f"{BREAKER_PATH}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"open_until": open_until,
                       "tripped_at": datetime.now().isoformat(),
                       "reason": reason}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, BREAKER_PATH)
    except Exception:
        pass


def _trip_breaker(reason: str) -> float:
    """进入长冷却，返回冷却截止 epoch。"""
    global _breaker_open_until
    _breaker_open_until = time.time() + _cooldown_seconds()
    _breaker_persist(_breaker_open_until, reason)
    return _breaker_open_until


# ---------------------------------------------------------------- 截断可见化
# v3.12 起截断必须可见（与 zhihu_content._content_field 同一纪律：调用方
# 不再把"被剪过的 answer/abstract"误当全文）。两个输出口：answer 顶层
# truncated 字段；citations[].abstract 每条自带 truncated 字段。
def _clip(text: str, limit: int) -> "tuple[str, bool]":
    """(截断后文本, 是否发生截断)。所有截断口径统一走这里。"""
    return text[:limit], len(text) > limit


# ---------------------------------------------------------------- SSE 解析
def parse_sse(raw: str) -> Dict:
    """解析 conversation 端点的 SSE 全文（纯函数，离线测试覆盖）。

    Returns:
        {answer, citations, kunlun, status_first, token_fail, end_turn}
        answer: markdown-yiyan 增量顺序拼接；citations 已按 url 去重保序
        （abstract 超 ABSTRACT_MAX_CHARS 截断，per 条 truncated 标记）；
        status_first: 首个非 0 的 message status（无则 0）；kunlun 取自
        basedata.chatHitKunlun；token_fail 对应 hints.parts[].type=="tokenFail"。
    """
    answer_parts: List[str] = []
    citations: List[Dict] = []
    seen_urls = set()
    kunlun = ""
    status_first = 0
    token_fail = False
    end_turn = False

    # 按行解析（审查 v3.7 #4：字面 split("event:") 会把答案增量里含
    # "event:" 字样的 JSON 块拦腰截断，静默丢数据）
    name = ""
    for line in raw.splitlines():
        if line.startswith("event:"):
            name = line[len("event:"):].strip()
            continue
        if not line.startswith("data:"):
            continue
        ds = line[len("data:"):].strip()
        if not ds:
            continue          # event:ping 等无 data 块
        try:
            ev = json.loads(ds)
        except Exception:
            continue          # 坏块跳过，不让单块毁整个流
        if name == "basedata":
            kunlun = ev.get("chatHitKunlun") or kunlun
        st = ev.get("status")
        if st and not status_first:
            status_first = st
        try:
            msg = ev["data"]["message"]
            if msg.get("metaData", {}).get("endTurn"):
                end_turn = True
            for part in (msg["content"].get("hints", {}) or {}).get("parts", []) or []:
                if part.get("type") == "tokenFail":
                    token_fail = True
            gen = msg["content"].get("generator") or {}
            comp = gen.get("component", "")
            gdata = gen.get("data") or {}
            if comp == "markdown-yiyan":
                answer_parts.append(gdata.get("value", "") or "")
            elif comp == "thinkingSteps":
                for ref in gdata.get("referenceList") or []:
                    url = (ref.get("url") or "").strip()
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    abstract, abstract_truncated = _clip(
                        (ref.get("abstract") or "").strip(), ABSTRACT_MAX_CHARS)
                    citations.append({
                        "url": url,
                        "title": (ref.get("text") or "").strip(),
                        "abstract": abstract,
                        "truncated": abstract_truncated,
                        "source": (ref.get("source") or "").strip(),
                    })
        except (KeyError, TypeError):
            pass

    return {"answer": "".join(answer_parts), "citations": citations,
            "kunlun": kunlun, "status_first": status_first,
            "token_fail": token_fail, "end_turn": end_turn}


def _raise_for_risk(parsed: Dict, page_url: str = "") -> None:
    """风险信号 → 异常（1005/kunlun/wappass 先熔断再抛；1001/tokenFail 抛）。"""
    if parsed.get("kunlun") or parsed.get("status_first") == 1005 \
            or (_WAPPASS_MARK in (page_url or "")):
        until = _trip_breaker(
            f"status={parsed.get('status_first')} kunlun={parsed.get('kunlun')!r} "
            f"page={page_url[:80]!r}")
        raise WenxinQuotaError(
            f"文心配额/风控熔断（status={parsed.get('status_first')} "
            f"chatHitKunlun={parsed.get('kunlun')!r}）：游客配额极紧（实测每浏览器"
            f"身份约 1 次），本 IP 全部文心调用冷却至 "
            f"{datetime.fromtimestamp(until).isoformat(timespec='seconds')}（env "
            f"{ENV_COOLDOWN_H} 可调）。页面侧表现是 302 到 wappass 图形验证码。")
    if parsed.get("status_first") == 1001 or parsed.get("token_fail"):
        raise WenxinTokenError(
            "文心 token 失败（1001/tokenFail）：文心 token 绑定浏览器运行时"
            "（hector 反爬链现算、服务端校验），报此错说明当前前端版本下该机制"
            "已变，需按 .scratch 侦察流程重新逆向前端 bundle；这不是配额问题，"
            "不触发熔断。")


# ---------------------------------------------------------------- 浏览器层
def _search_via_browser(q: str, timeout_s: float) -> str:
    """camoufox 无头：全新身份提交搜索，截获 conversation SSE 全文返回。

    移植自侦察 p2 脚本（已验证可跑）。配额纪律：每身份约 1 次搜索，
    身份用完即弃（每次全新 context），调用间隔保持小时级。
    """
    try:
        from camoufox.sync_api import Camoufox
    except ImportError as e:
        raise WenxinDependencyError(
            "camoufox 未安装。安装：pip install \"camoufox[geoip]\" "
            "&& python -m camoufox fetch（约百余 MB，一次性）") from e

    sse_holder: Dict[str, object] = {}

    with Camoufox(headless=True, geoip=True) as browser:
        ctx = browser.new_context(locale="zh-CN", timezone_id="Asia/Shanghai")
        page = ctx.new_page()
        page.set_default_timeout(45000)

        def on_response(resp):
            # conversation SSE 由页面 JS 发起；这里只登记，流结束后再取全文
            if _CONVERSATION_URL in resp.url:
                sse_holder["resp"] = resp

        page.on("response", on_response)
        deadline = time.monotonic() + timeout_s

        page.goto(_HOME_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(int(HOME_SETTLE_S * 1000))
        _dismiss_overlays(page)

        target = None
        for sel in ("#chat-textarea", "textarea[id*=chat]", "textarea"):
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    target = loc.first
                    break
            except Exception:
                continue
        if target is None:
            raise WenxinError(
                "找不到文心输入框 #chat-textarea（SPA 未挂载或前端改版）")
        target.click()
        target.fill(q)
        page.wait_for_timeout(500)
        target.press("Enter")
        page.wait_for_timeout(4000)
        if "/search/" not in page.url:      # Enter 未触发则点发送按钮兜底
            for sel in ("button[class*=send]", "[class*=send-btn]",
                        "[class*=send]:not(textarea):not(input)"):
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible():
                        loc.first.click()
                        break
                except Exception:
                    continue

        # 等流式回答完成：页面文本长度连续 N 轮稳定 或 到 deadline（p2 参数）
        last_len, stable = -1, 0
        while time.monotonic() < deadline:
            page.wait_for_timeout(int(TIMEOUT_POLL_S * 1000))
            try:
                cur = len(page.evaluate(
                    "document.body ? document.body.innerText : ''"))
            except Exception:
                break                       # 页面跳转（如 wappass）即停止等待
            if cur == last_len:
                stable += 1
                if stable >= TIMEOUT_STABLE_ROUNDS:
                    break
            else:
                stable, last_len = 0, cur
        else:
            # 审查 v3.7 #3：deadline 耗尽且文本从未稳定=流式超时，
            # 用专属 slug 如实上报（wenxin_timeout 此前定义了却永不触发）
            raise WenxinTimeoutError(
                f"流式回答超时（timeout_s={timeout_s}）：页面文本持续变化，"
                f"未在期限内稳定。可调大 timeout_s 重试")

        page_url = page.url or ""
        resp = sse_holder.get("resp")
        if resp is None:
            # 没截到流：若已跳验证码页，同样是熔断信号（如实处理）
            if _WAPPASS_MARK in page_url:
                _raise_for_risk({"kunlun": "kunlun_popup",
                                 "status_first": 1005}, page_url)
            raise WenxinError(
                f"未截获 conversation SSE 流（final url={page_url[:100]!r}）；"
                "可能是提交失败或前端版本漂移")
        try:
            raw = resp.text()               # 流已结束，取全文（p2 同款时机）
        except Exception as e:
            # body 取不到但页面跳了验证码 → 熔断信号；否则如实报错
            if _WAPPASS_MARK in page_url:
                _raise_for_risk({"kunlun": "kunlun_popup",
                                 "status_first": 1005}, page_url)
            raise WenxinError(f"SSE body 获取失败: {e!r}") from e
        return raw


def _dismiss_overlays(page) -> None:
    """清营销弹窗/引导浮层（实测 _task-mode-guide-dialog 会挡点击；p2 同款）。"""
    try:
        page.evaluate(
            "document.querySelectorAll('.cos-dialog, [class*=guide-banner], "
            "' + '[class*=guide-dialog], [class*=login-guide]')"
            ".forEach(e => e.remove());")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass


# ---------------------------------------------------------------- 入口
def search(q: str, timeout_s: float = 90, on_error: str = "report",
           vendor: str = "?", role: str = "primary") -> Dict:
    """文心 AI 搜索：返回单条聚合行（不是列表）。

    成功行: {q, answer(markdown, 截 4000 时带 truncated=true), citations:
            [{url,title,abstract(截 500 时带 truncated=true),source}],
            engine: "wenxin-ai", count: 引用条数, platform: "wenxin",
            vendor, role}

    Args:
        q: 搜索关键词
        timeout_s: 浏览器侧总超时（含 SPA 加载 + 流式回答等待）
        on_error: "report"（默认，返回错误记录 dict）/ "raise" / "empty"（{}）
        vendor / role: 指标用透传字段

    配额纪律见模块 docstring：每浏览器身份约 1 次搜索、间隔小时级、
    1005 即熔断本 IP 长冷却（默认 6h）。冷却期内本函数不起浏览器，
    直接报 wenxin_quota——低频使用是本引擎唯一正确的用法。
    """
    try:
        if _breaker_is_open():
            remaining_h = _breaker_remaining_s() / 3600.0
            raise WenxinQuotaError(
                f"文心熔断冷却中（剩 {remaining_h:.1f}h，env {ENV_COOLDOWN_H} "
                f"可调）：此前已触发 1005/kunlun 风控，为保护本 IP 不再起浏览器。"
                "配额纪律见模块 docstring。")
        raw = _search_via_browser(q, timeout_s)
        parsed = parse_sse(raw)
        _raise_for_risk(parsed, page_url="")
        if not parsed["answer"]:
            # 审查 v3.7 #1：空答案无论流是否"正常结束"都必须报错——
            # 返回无 error 的空成功行会让调用方把故障当真空（诚实协议违规）
            if parsed["end_turn"]:
                raise WenxinError(
                    "SSE 流正常结束但答案正文为空：markdown-yiyan 结构可能随"
                    "前端版本漂移，需重新侦察（证据存 .scratch）")
            raise WenxinError(
                "SSE 流被截断且未拿到答案正文（endTurn 未到）——如实报错")
        answer, answer_truncated = _clip(parsed["answer"], ANSWER_MAX_CHARS)
        return {
            "answer": answer,
            "truncated": answer_truncated,
            "citations": parsed["citations"],
            "engine": "wenxin-ai",
            "count": len(parsed["citations"]),
            "platform": _PLATFORM,
            "vendor": vendor,
            "role": role,
        }
    except Exception as e:
        if on_error == "raise":
            raise
        if on_error == "report":
            slug = getattr(e, "slug", None) or type(e).__name__
            return {"error": f"{slug}: {e}", "tool": _TOOL,
                    "query": q, "platform": _PLATFORM}
        return {}   # on_error == "empty"：兼容旧行为（{} 不是真空证据）


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="文心 AI 搜索（低频：每浏览器身份约 1 次，1005 即熔断 6h）")
    parser.add_argument("q", help="query")
    parser.add_argument("--timeout", type=float, default=90,
                        help="浏览器侧总超时秒数（默认 90）")
    parser.add_argument("--on-error", default="report",
                        choices=["report", "raise", "empty"])
    args = parser.parse_args()
    row = search(args.q, timeout_s=args.timeout, on_error=args.on_error)
    if "error" in row:
        print(f"[wenxin_engine] error: {row['error']}", file=sys.stderr)
        return 1
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
