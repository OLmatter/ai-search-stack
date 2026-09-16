#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ai-search-stack 工具箱体检（doctor）—— 一条命令巡检全部通道健康。

巡检项（8 = 5 网络探活 + 3 本地状态）：
    - 本地 SearXNG 实例（zhihu 链第一环）：存活 + unresponsive_engines
    - 知乎 cookie：文件存在性 + 年龄（v3.4 起过期可自愈，但仍值得观测）
    - 标定钩子活性（v3.8.2，v3.15 扩展）：周期探活的最后读数 >48h = 钩子
      疑似断线——覆盖 cookie_lifetime_log（缺文件报警）与 sogou_recovery_log
      （v3.15；缺文件=可选观测项未启用不报警，有读数后 >48h 报警）
    - bilibili 官方 API：用一个知名 bvid 探活（只读、无风控压力）
    - 百度直连：首页探活（搜索风控与首页可达是两回事，这里只测通道）
    - google-bridge 服务：/health（通常按需启动，未起不算故障）
    - GitHub API：可达性（v3.11 起走 UA+直连通道，裸 urlopen 的默认
      UA 会被 GitHub 按 IP 强限流成永久 403；v3.18 起可选 GITHUB_TOKEN，
      设置后带 Bearer 认证头，见 check_github 注释）
    - 值班巡检趋势（v3.16 引入，v3.18 统计口径重做）：shift_log.md 近 7
      天记录条数/覆盖天数/每日分布/关键事件计数/最近一条摘要——让值班
      连续性与异常趋势在 doctor 输出可见（可选观测：缺文件/空/全坏行
      不报警，7 天零记录亮 ⚠️）

用法:
    python tools/doctor.py                  # 全量巡检，逐项 ✅/❌/⚠️
    python tools/doctor.py --cookie-probe   # 只跑知乎 cookie 寿命标定探活
    python tools/doctor.py --cookie-probe --renew-if-older-than 36
                                            # 探活 + 过期超龄顺带续期（cron 友好）
    python tools/doctor.py --sogou-probe    # 只跑搜狗单发探活（v3.14 恢复
                                            # 曲线标定，读数追加
                                            # state/sogou_recovery_log.jsonl）
退出码: 0=全绿或仅可选服务未启动（--cookie-probe / --sogou-probe 单项
        标定模式只观测不判故障，expired/valid/blocked 均为成功读数）;
        1=有核心通道故障（--cookie-probe --renew-if-older-than 时续期失败
        也 1；--sogou-probe 本地故障也 1）。
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta

_TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
SEARXNG = os.environ.get("SEARXNG_INSTANCE", "http://127.0.0.1:8888")
COOKIE_PATH = os.path.join(_TOOL_DIR, "chat-scraper", "state",
                           "zhihu_cookies.json")
PROBE_BVID = "BV1GJ411x7h7"   # 知名视频，仅作 API 探活
TIMEOUT = 8

# v3.8.2: cookie 寿命标定（--cookie-probe）。cookie 文件的 fetched_at 只记
# "何时签发"，不记"何时失效"——寿命分布得靠周期性探活积累读数（评估员
# 共识：产出决定自愈策略）。日志在 state/ 下（已 gitignore，只留本地）。
COOKIE_LOG_PATH = os.path.join(_TOOL_DIR, "chat-scraper", "state",
                               "cookie_lifetime_log.jsonl")
PROBE_QUESTION_ID = "19550227"   # bootstrap 同款知名问题，仅作 API 探活

# v3.14: 搜狗恢复曲线标定（--sogou-probe）。连发标定（v3.13，
# sogou_engine --probe）测的是"多快触发风控"；"风控后多久恢复"无法一次
# 测出，只能靠风控后周期性单发探活积累读数（引擎侧 probe_once，判定与
# search 同判据）。日志在 state/ 下（已 gitignore，只留本地）。
SOGOU_RECOVERY_LOG_PATH = os.path.join(_TOOL_DIR, "chat-scraper", "state",
                                       "sogou_recovery_log.jsonl")

# v3.18: 值班巡检趋势统计口径重做（check_shift_log 于 v3.16 引入）。
# shift_log.md 是值班会话的巡检/处置流水（人工+会话写入），doctor 只读
# 不写。语义沿 sogou_recovery_log 先例（可选观测项，缺省静默）：缺文件/
# 空文件/全坏行 = 可选观测项未启用，不报警不判故障；有记录但近 7 天
# 零记录 = 值班连续性中断，亮 ⚠️（optional，不判核心故障）。
SHIFT_LOG_PATH = os.path.join(_TOOL_DIR, "chat-scraper", "state",
                              "shift_log.md")
SHIFT_LOG_WINDOW_DAYS = 7
# 关键事件关键词：纯字面计数（大小写敏感子串匹配，不做 NLP）——统计窗口
# 内含该字样的行数，一行可同时命中多个关键词、各自独立计数。（从
# 2026-09-16 真实 shift_log 归纳：restart=引擎/容器重启动作、处置=运维
# 处置动作、❌=检查失败标记、恶化=健康度转差描述。）
SHIFT_LOG_EVENT_KEYWORDS = ("restart", "处置", "❌", "恶化")

_results = []


def _check(name, fn, optional=False):
    try:
        detail = fn()
        _results.append((name, True, detail, optional))
        print(f"✅ {name}: {detail}")
    except Exception as e:
        _results.append((name, False, str(e)[:120], optional))
        print(f"{'⚠️' if optional else '❌'} {name}: {str(e)[:120]}")


_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}))   # 绕系统代理：代理半死会伪造全红（v3.4 注释同款）


def _get(url, timeout=TIMEOUT, headers=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent":
                                 "ai-search-stack-doctor"})
    with _OPENER.open(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def check_searxng():
    body = _get(f"{SEARXNG}/search?q=ping&format=json")
    data = json.loads(body)
    dead = data.get("unresponsive_engines") or []
    n = len(data.get("results", []))
    return (f"{n} 条结果, {TIMEOUT}s 探活"
            + (f", 不健康引擎: {dead}" if dead else ", 引擎全健康"))


def check_cookie():
    if not os.path.exists(COOKIE_PATH):
        raise RuntimeError("cookie 文件不存在（read 会自动引导自愈，"
                           "或手动跑 zhihu_bootstrap.py）")
    with open(COOKIE_PATH, encoding="utf-8") as f:
        meta = json.load(f)
    age_h = (time.time() - os.path.getmtime(COOKIE_PATH)) / 3600
    has = all(k in (meta.get("cookies") or {})
              for k in ("d_c0", "__zse_ck"))
    if not has:
        raise RuntimeError("cookie 缺少 d_c0/__zse_ck（重跑 zhihu_bootstrap.py）")
    return (f"存在, 龄 {age_h:.1f}h"
            f"{'（>24h 建议跑一次 zhihu_bootstrap.py 续期）' if age_h > 24 else ''}")


def _last_valid_entry(path):
    """jsonl 最后一条可解析为 dict 的读数（坏行跳过）；文件缺失/空/全坏返回 None。

    与 sogou_engine 探活读数解析同款防御：标定日志是 append-only 观测
    产物，个别坏行不应让钩子活性检查对"其实活着"的钩子误报断线。
    """
    try:
        with open(path, encoding="utf-8") as f:
            lines = [ln for ln in f if ln.strip()]
    except OSError:
        return None
    for ln in reversed(lines):
        try:
            entry = json.loads(ln)
        except ValueError:
            continue
        if isinstance(entry, dict):
            return entry
    return None


def _reading_age_h(entry):
    """读数距今的小时数（坏时间戳原样抛 ValueError，由 _check 包装显示）。"""
    ts = entry.get("ts") or entry.get("time") or ""
    return (time.time() - datetime.fromisoformat(ts).timestamp()) / 3600


def check_hook_liveness():
    """标定钩子活性（v3.15 扩展：覆盖两个标定日志）：周期探活的最后读数
    超过 ~48h = 钩子疑似断线（定时任务没跑/机器没开/自动化被禁）。断线时
    标定数据流静默死亡，这里是唯一的报警点。

    - cookie_lifetime_log：文件缺失 = 每日探活从未执行 → 报警
      （v3.8.2 既有行为，cookie 寿命标定是自愈策略的数据基座）
    - sogou_recovery_log（v3.15）：文件缺失/无读数 = 可选观测项未启用
      → **不报警**（恢复曲线标定是增值观测，没人跑不算钩子断线）；
      但有读数后最后一条 >48h → 同样报警（开了就必须活着，静默断线
      同样会让恢复曲线数据流死亡）
    """
    if not os.path.exists(COOKIE_LOG_PATH):
        raise RuntimeError("标定日志不存在（每日探活从未执行："
                           "python tools/doctor.py --cookie-probe）")
    entry = _last_valid_entry(COOKIE_LOG_PATH)
    if entry is None:
        raise RuntimeError("标定日志存在但无有效读数（检查日志内容/磁盘写入）")
    age_h = _reading_age_h(entry)
    if age_h > 48:
        raise RuntimeError(
            f"cookie 标定最后读数已是 {age_h:.0f}h 前——每日探活钩子疑似断线"
            f"（定时任务没跑？检查自动化/机器开关机）")
    parts = [f"cookie 最后读数 {age_h:.1f}h 前（{entry.get('status', '?')}）"]

    sogou = _last_valid_entry(SOGOU_RECOVERY_LOG_PATH)
    if sogou is None:
        parts.append("sogou 无读数（可选观测项未启用，不报警；"
                     "python tools/doctor.py --sogou-probe 可启用）")
    else:
        sogou_age_h = _reading_age_h(sogou)
        if sogou_age_h > 48:
            raise RuntimeError(
                f"sogou 恢复曲线最后读数已是 {sogou_age_h:.0f}h 前——搜狗探活"
                f"钩子疑似断线（--sogou-probe 定时任务没跑？）")
        parts.append(f"sogou 最后读数 {sogou_age_h:.1f}h 前"
                     f"（{'blocked' if sogou.get('blocked') else 'ok'}）")
    return "; ".join(parts)


_SHIFT_ENTRY_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})\]\s?(.*)$")
_SHIFT_TIME_ONLY_RE = re.compile(r"^\[(\d{2}:\d{2})\]\s?(.*)$")


def _shift_log_stats(path, now, window_days=SHIFT_LOG_WINDOW_DAYS):
    """解析值班流水，返回统计 dict；文件缺失返回 None。

    返回字段（count/days/per_day/events/last 只统计窗口内条目；
    total/last_any 是全文件口径，供 check 层区分"未启用"与"连续性中断"）：
        total:     全文件可解析条数
        count:     窗口内条目数
        days:      窗口内覆盖天数
        per_day:   [(date, 条数), ...] 每天条数分布，按日期升序
        events:    {关键词: 含该字样的行数}（SHIFT_LOG_EVENT_KEYWORDS，
                   纯字面计数，一行可命中多个关键词、各自独立计数）
        last:      (时间戳字符串, 首 80 字摘要) 窗口内文件顺序最后一条
        last_any:  同 last 形态但不限窗口（全文件最后一条，连续性报警
                   消息里引用，让"断了多久"可见）

    条目格式：`[YYYY-MM-DD HH:MM] 内容`；`[HH:MM] 内容`（值班当场省写
    日期，继承上一条带日期条目的日期——文件头部无日期可继承时跳过，
    测试钉死）。无 `[…]` 前缀的行、日期非法的行均跳过不计数（append-only
    手写流水，坏行不应让统计崩溃，与 _last_valid_entry 同款防御）。

    窗口 = now.date() 往前共 window_days 个自然日（含今天）。班次边界
    无法从流水可靠识别（无固定班次开始标记），故口径为"记录条数 + 覆盖
    天数"，不假装能数出"班次次数"。
    """
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return None
    today = now.date()
    cutoff = today - timedelta(days=window_days - 1)
    total = 0
    count = 0
    per_day_counter = {}
    events = {k: 0 for k in SHIFT_LOG_EVENT_KEYWORDS}
    last = None
    last_any = None
    last_date = None
    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        m = _SHIFT_ENTRY_RE.match(s)
        if m:
            try:
                d = date.fromisoformat(m.group(1))
            except ValueError:
                continue
            last_date, ts, text = d, f"{m.group(1)} {m.group(2)}", m.group(3)
        else:
            m = _SHIFT_TIME_ONLY_RE.match(s)
            if not m or last_date is None:
                continue
            d, text = last_date, m.group(2)
            ts = f"{d.isoformat()} {m.group(1)}"
        total += 1
        last_any = (ts, text[:80])
        if not (cutoff <= d <= today):
            continue
        count += 1
        per_day_counter[d] = per_day_counter.get(d, 0) + 1
        for k in events:
            if k in text:
                events[k] += 1
        last = (ts, text[:80])
    return {"total": total, "count": count,
            "days": len(per_day_counter),
            "per_day": sorted(per_day_counter.items()),
            "events": events, "last": last, "last_any": last_any}


def check_shift_log():
    """值班巡检趋势（v3.16 引入，v3.18 统计口径重做；可选观测）：近 7 天
    记录条数/覆盖天数/每日分布/关键事件计数/最近一条摘要，让值班连续性
    与异常趋势在 doctor 一眼可见。

    语义沿 sogou_recovery_log 先例（可选观测项，缺省静默）：
    - 缺文件 / 空文件 / 全坏行（无可解析记录）→ 返回"未启用"说明，
      **不报警不判故障**（shift_log 是人工/会话产物，没人写不算故障）
    - 有记录但近 7 天零记录 → ⚠️（值班连续性中断的可观测报警，optional
      不判核心故障）
    - 事件计数 = 含 SHIFT_LOG_EVENT_KEYWORDS 字样的行数（纯字面启发式，
      趋势观测不是精确审计）
    """
    stats = _shift_log_stats(SHIFT_LOG_PATH, datetime.now())
    if stats is None:
        return ("shift_log.md 不存在——可选观测未启用，不报警"
                "（值班流水写入后本项自动显示）")
    if stats["total"] == 0:
        return ("shift_log.md 无可解析记录（空/全坏行）——"
                "可选观测未启用，不报警")
    if stats["count"] == 0:
        last_ts = stats["last_any"][0] if stats["last_any"] else "?"
        raise RuntimeError(f"shift_log 近 {SHIFT_LOG_WINDOW_DAYS} 天零记录"
                           f"（最近一条 {last_ts}）——值班连续性中断？")
    per_day = "，".join(f"{d.isoformat()}:{n}"
                        for d, n in stats["per_day"])
    events = " ".join(f"{k}×{v}" for k, v in stats["events"].items())
    last_ts, last_text = stats["last"]
    return (f"近 {SHIFT_LOG_WINDOW_DAYS} 天记录 {stats['count']} 条，"
            f"覆盖 {stats['days']} 天（{per_day}）；"
            f"事件计数: {events}；最近一条 [{last_ts}] {last_text}")


def check_bilibili():
    body = _get(f"https://api.bilibili.com/x/web-interface/view?"
                f"bvid={PROBE_BVID}")
    code = json.loads(body).get("code")
    if code != 0:
        raise RuntimeError(f"view API code={code}")
    return "官方 API code=0"


def check_baidu():
    body = _get("https://www.baidu.com/")
    return f"首页 200, {len(body)} 字节（注意：搜索风控另行判定）"


def check_google_bridge():
    body = _get("http://127.0.0.1:18799/health", timeout=3)
    ok = json.loads(body).get("ok")
    if not ok:
        raise RuntimeError("health ok=false")
    return "服务在跑"


def check_github():
    # v3.11: 走 _get（UA 头 + 绕代理 opener），与其余检查同款通道。
    # 实测（2026-09-16）：裸 urlopen 的默认 UA（Python-urllib/3.x）被 GitHub
    # 按 IP 强限流，长期稳定 403 "rate limit exceeded for <IP>"；同 IP 同
    # 分钟带 UA 直连即 200。root cause 是漏 UA，不是配额真耗尽。
    # v3.18: 可选 GITHUB_TOKEN（tools/github/github_client.py 同款约定）——
    # 匿名 60 req/h 是本 IP 全部 GitHub 调用共享的配额，值班日志
    # 2026-09-16 08:52/09:03 两班连续撞限流窗口（doctor 403、同刻独立
    # curl 直连全 200）；设置后本检查带 Authorization: Bearer（5000/h），
    # 不再吃匿名配额。未设置时维持匿名可达性观测（可选配置缺失不是故障）。
    headers = {"User-Agent": "ai-search-stack-doctor"}
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    _get("https://api.github.com/", headers=headers)
    return f"API 可达 (200, {'Bearer 认证' if token else '匿名'})"


# ---- v3.8.2: --cookie-probe（cookie 寿命标定，独立于全量巡检） ----


def _sys_path_chat_scraper():
    cs = os.path.join(_TOOL_DIR, "chat-scraper")
    if cs not in sys.path:
        sys.path.insert(0, cs)


def _cookie_meta():
    """(cookie 文件 fetched_at, cookie 龄小时)；文件缺失/字段坏返回 (None, None)。"""
    try:
        with open(COOKIE_PATH, encoding="utf-8") as f:
            fetched_at = (json.load(f) or {}).get("fetched_at")
    except (OSError, ValueError):
        return None, None
    age_h = None
    if fetched_at:
        try:
            age_h = round(
                (time.time() - datetime.fromisoformat(fetched_at).timestamp())
                / 3600, 2)
        except (ValueError, TypeError, OSError):
            pass
    return fetched_at, age_h


def _renew_cookie() -> "tuple[bool, str]":
    """v3.9: 顺手动用一次无头引导续期 cookie（--renew-if-older-than 触发时）。

    直接调 zhihu_bootstrap.bootstrap——不走 zhihu_content._try_self_heal
    （那里有 600s 冷却闸门，且探活期间已被 monkeypatch 禁用；cron 续期是
    主动运维动作，不应被冷却闸门拦）。返回 (ok, 结果详情)。
    """
    _sys_path_chat_scraper()
    try:
        import zhihu_bootstrap
        payload = zhihu_bootstrap.bootstrap(out_path=COOKIE_PATH,
                                            headless=True)
    except Exception as e:   # camoufox 未装 / 轮数用尽 / 日志写不进等
        return False, f"{type(e).__name__}: {str(e)[:140]}"
    cookies = payload.get("cookies") or {}
    ok = all(cookies.get(k) for k in ("d_c0", "__zse_ck"))
    detail = (f"d_c0({'Y' if cookies.get('d_c0') else 'N'}) "
              f"__zse_ck(len={len(cookies.get('__zse_ck', ''))})")
    return ok, detail


def cookie_probe(entry_path=COOKIE_LOG_PATH,
                 renew_if_older_than: "float | None" = None) -> dict:
    """真实调用一次知乎 questions API 标定 cookie 活性，读数追加进 jsonl。

    复用 zhihu_content.fetch_question（签名 + 官方 API，探 PROBE_QUESTION_ID）。
    标定纪律：探活期间 monkeypatch 掉 _try_self_heal——标定要的是 cookie
    真实寿命读数；若过期即自愈刷新，每条 expired 都会被"续命"污染，
    寿命分布永远测不出来。

    v3.9 --renew-if-older-than H（默认 None=关闭，保持纯标定行为）：探活
    发现 status=expired 且 cookie 龄 > H 小时时，顺手动用一次无头引导续期
    （低峰窗口把续期做掉，白天首次使用零延迟）。v3.21 标定结论（2026-09-16
    全量 7 读数，唯一死亡实测）：访客 cookie 寿命 ≈47.4h（47.38h 即 403），
    36h 阈值与其兼容（余量 ≥11.4h），维持不变——n=1 不够调阈值，等更多
    死亡样本；renew 实战首例 1/1 成功（47.92h expired → ok，见日志 renew
    字段），valid 读数零误触发。触发频率预期 ≈ 每 1-2 天一次（随实际知乎
    用量浮动）。续期入口现状：未部署 cron（schtasks 仅 sogou 探活一项），
    由班次/agent 显式执行 `--renew-if-older-than 36`；MCP doctor cookie
    模式恒为纯标定不续期（保真实寿命数据流）。
    标定读数在本函数内先落定、续期在其后，不污染本次读数；续期结果记进
    同一读数行的 renew/renew_result 字段。只动 expired 读数：missing 是
    "没戴表"（引导也能治，但龄读数为 None 无从判超龄，且行为不同，留给
    显式引导）、error 是网络/风控（续期无用）、valid 不需要。

    读数四态：valid（API 通）/ expired（认证被拒）/ missing（cookie 文件缺
    或无 d_c0，≠ 过期，分开记）/ error（网络、行为风控等其他，不污染两类
    主读数）。返回该条读数 dict；jsonl 写失败抛 OSError 由调用方定退出码。
    """
    _sys_path_chat_scraper()
    import zhihu_content as zc

    fetched_at, age_h = _cookie_meta()
    entry = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "tool": "doctor --cookie-probe",
        "question_id": PROBE_QUESTION_ID,
        "fetched_at": fetched_at,
        "cookie_age_h": age_h,
        "status": None,
        "note": "",
        "renew": None,        # None=未启用 renew；True/False=启用后是否触发
        "renew_result": "",   # 仅 renew=True 时有意义："ok: ..." / "fail: ..."
    }
    orig_selfheal = zc._try_self_heal
    zc._try_self_heal = lambda: False   # 禁自愈：探真实寿命（见 docstring）
    try:
        info = zc.fetch_question(PROBE_QUESTION_ID)
        entry["status"] = "valid"
        entry["note"] = (f"title={str(info.get('title', ''))[:40]} "
                         f"answers={info.get('answer_count')}")
    except zc._CookieStateMissing as e:
        entry["status"] = "missing"
        entry["note"] = str(e)[:160]
    except zc.ZhihuAuthExpired as e:
        entry["status"] = "expired"
        entry["note"] = f"{getattr(e, 'slug', '')}: {e}"[:160]
    except Exception as e:
        entry["status"] = "error"
        entry["note"] = f"{type(e).__name__}: {e}"[:160]
    finally:
        zc._try_self_heal = orig_selfheal

    if renew_if_older_than is not None:
        over_age = (entry["cookie_age_h"] is not None
                    and entry["cookie_age_h"] > renew_if_older_than)
        should = entry["status"] == "expired" and over_age
        entry["renew"] = should
        if should:
            print(f"→ cookie expired 且龄 {entry['cookie_age_h']}h > "
                  f"{renew_if_older_than:g}h，顺手动用无头引导续期...")
            ok, detail = _renew_cookie()
            entry["renew_result"] = ("ok: " if ok else "fail: ") + detail

    os.makedirs(os.path.dirname(entry_path) or ".", exist_ok=True)
    with open(entry_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def cmd_cookie_probe(renew_hours: "float | None" = None) -> int:
    suffix = (f"，renew_if_older_than={renew_hours:g}h"
              if renew_hours is not None else "")
    print(f"== cookie 寿命标定探活（问题 id {PROBE_QUESTION_ID}，禁自愈"
          f"{suffix}）==")
    try:
        # entry_path 显式传全局（默认参数会在 def 时绑定，测试 patch
        # doctor.COOKIE_LOG_PATH 会失效、把假读数写进真实标定日志）
        entry = cookie_probe(entry_path=COOKIE_LOG_PATH,
                             renew_if_older_than=renew_hours)
    except Exception as e:   # import 失败/日志写不进等本地故障
        print(f"❌ cookie-probe 本地故障: {type(e).__name__}: {e}")
        return 1
    icon = {"valid": "✅", "expired": "🪦",
            "missing": "⚠️", "error": "❌"}.get(entry["status"], "❓")
    print(f"{icon} status={entry['status']} "
          f"fetched_at={entry['fetched_at']} "
          f"age={entry['cookie_age_h']}h")
    print(f"   {entry['note']}")
    if entry.get("renew"):
        ok = entry["renew_result"].startswith("ok")
        print(f"{'✅' if ok else '❌'} 续期: {entry['renew_result']}")
    try:
        with open(COOKIE_LOG_PATH, encoding="utf-8") as f:
            n = sum(1 for _ in f)
        print(f"→ 已追加 {COOKIE_LOG_PATH}（累计 {n} 条标定数据）")
    except OSError:
        print(f"→ 已追加 {COOKIE_LOG_PATH}")
    # 本模式只观测不判故障：expired/valid 都是成功读数（标定数据点），exit 0。
    # 例外：启用了续期且续期失败 → exit 1（运维动作失败，cron 侧可报警）
    if entry.get("renew") and not entry["renew_result"].startswith("ok"):
        return 1
    return 0


def cmd_sogou_probe() -> int:
    """v3.14: 搜狗恢复曲线单发探活（--sogou-probe，独立于全量巡检）。

    引擎侧 probe_once：真实一发搜狗搜索，判定与 search() 同判据，读数
    （含距上次风控的秒数 since_last_block_s）追加 SOGOU_RECOVERY_LOG_PATH。
    本模式只观测不判故障：blocked/正常都是成功读数（恢复曲线数据点），
    exit 0；本地故障（导入失败/日志写不进）exit 1。
    """
    _sys_path_chat_scraper()
    import sogou_engine as se
    print("== 搜狗恢复曲线探活（单发，判定与 search 同判据）==")
    try:
        # log_path 显式传全局（同 cookie_probe：默认参数在 def 时绑定，
        # 测试 patch doctor.SOGOU_RECOVERY_LOG_PATH 需要生效）
        entry = se.probe_once(log_path=SOGOU_RECOVERY_LOG_PATH,
                              tool="doctor --sogou-probe")
    except Exception as e:   # 读数函数自身不许炸，走到这基本是写日志失败
        print(f"❌ sogou-probe 本地故障: {type(e).__name__}: {e}")
        return 1
    icon = "🪦" if entry["blocked"] else "✅"
    since = entry["since_last_block_s"]
    print(f"{icon} http={entry['http']} rows={entry['rows']} "
          f"blocked={entry['blocked']} "
          f"since_last_block={since if since is not None else 'null'}s")
    if entry["note"]:
        print(f"   {entry['note']}")
    try:
        with open(SOGOU_RECOVERY_LOG_PATH, encoding="utf-8") as f:
            n = sum(1 for _ in f)
        print(f"→ 已追加 {SOGOU_RECOVERY_LOG_PATH}（累计 {n} 条恢复曲线读数）")
    except OSError:
        print(f"→ 已追加 {SOGOU_RECOVERY_LOG_PATH}")
    return 0


def _make_stdout_robust():
    """v3.21: GBK 控制台加固——✅/🪦/❌ 等 emoji 在 GBK 编码管道下直接
    UnicodeEncodeError 崩掉整份报告（2026-09-16 sogou cron 部署调试期实录，
    ~/.zcode/sogou_probe_cron.log；读数已由 probe_once 先落账未丢，但报告
    与退出码被杀）。errors="replace" 让不可编码字符退化为 '?'，编码本身
    不动（不假装终端是 UTF-8）。StringIO（MCP 重定向路径）无 reconfigure，
    原样放行——print 进 StringIO 本就无编码问题。加固失败不掩盖主流程。
    """
    out = sys.stdout
    if out is not None and hasattr(out, "reconfigure"):
        try:
            out.reconfigure(errors="replace")
        except (ValueError, OSError):   # 已关闭的流等极端态
            pass
    return out


def main(argv=None) -> int:
    _make_stdout_robust()
    import argparse
    p = argparse.ArgumentParser(
        description="ai-search-stack 工具箱体检（全量巡检或单项标定）")
    p.add_argument("--cookie-probe", action="store_true",
                   help="只跑知乎 cookie 寿命标定探活（真实调一次 questions "
                        "API，读数追加 state/cookie_lifetime_log.jsonl），"
                        "不跑全量巡检；expired/valid 均算成功观测，exit 0")
    p.add_argument("--renew-if-older-than", type=float, default=None,
                   metavar="H",
                   help="配合 --cookie-probe：探活发现 cookie 已 expired 且"
                        "龄 > H 小时时，顺手动用一次无头引导续期（headless，"
                        "低峰窗口把续期做掉，白天使用零延迟）。默认关闭=纯"
                        "标定观测。v3.21 标定：访客 cookie 寿命 ≈47.4h，"
                        "36h 阈值维持。可选 cron 例（当前未部署，由班次/"
                        "agent 按需执行）：`python tools/doctor.py "
                        "--cookie-probe --renew-if-older-than 36`。"
                        "续期失败 exit 1")
    p.add_argument("--sogou-probe", action="store_true",
                   help="只跑搜狗恢复曲线单发探活（v3.14，真实发一次搜索，"
                        "判定与 search 同判据，读数含距上次风控秒数追加 "
                        "state/sogou_recovery_log.jsonl），不跑全量巡检；"
                        "blocked/正常均为成功观测，exit 0")
    args = p.parse_args(argv)
    if args.cookie_probe:
        return cmd_cookie_probe(renew_hours=args.renew_if_older_than)
    if args.sogou_probe:
        return cmd_sogou_probe()
    print(f"== ai-search-stack doctor @ {time.strftime('%Y-%m-%d %H:%M')} ==")
    _check("SearXNG 本地实例", check_searxng, optional=True)
    _check("知乎 cookie", check_cookie, optional=True)
    _check("标定钩子活性", check_hook_liveness, optional=True)
    _check("bilibili 官方 API", check_bilibili)
    _check("百度直连", check_baidu)
    _check("google-bridge 服务", check_google_bridge, optional=True)
    _check("GitHub API", check_github)
    _check("值班巡检趋势", check_shift_log, optional=True)
    core = [r for r in _results if not r[3]]
    core_fail = [r for r in core if not r[1]]
    opt_fail = [r for r in _results if not r[1] and r[3]]
    print(f"== 结果: 核心 {len(core) - len(core_fail)}/{len(core)} 正常"
          f"，核心故障 {len(core_fail)}，可选异常 {len(opt_fail)} ==")
    return 1 if core_fail else 0


if __name__ == "__main__":
    sys.exit(main())
