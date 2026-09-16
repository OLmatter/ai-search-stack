#!/usr/bin/env python
"""searxng 客户端 —— 通用元搜索客户端

SearXNG 是一个开源元搜索引擎（聚合 Google/Bing/DuckDuckGo 等）。
当 google-bridge 被 CAPTCHA 锁时，用 searxng 兜底。

用法（唯一模块名，可与 hackernews_client / github_client 同进程组合）:
    from searxng_client import search
    results = search(q="claude max exploit", num=10, since="7d")

错误协议:
    search(..., on_error="report")  # 默认
    出错时返回 [{"error": "URLError: ...", "tool": "searxng", "query": "..."}]，
    调用方检查 result[0].get("error") 即可区分「故障」与「真空（0 结果）」。
    on_error="raise" 直接抛异常；on_error="empty" 兼容旧行为返回 []。

引擎选择与探活（v3.23 固化）:
    search(..., engines="brave")   # 透传 SearXNG engines= 参数（逗号分隔
                                   # 可多引擎；None=默认引擎集不动）
    probe(q, "brave")              # 单引擎两关判据「第一关」的库固化：
                                   # engines=E 单发，返回
                                   # {engine, rows, unresponsive, ok, ...}，
                                   # ok = rows>0 且 unresponsive 空（判据原文）。
                                   # v3.16~v3.23 六轮探活全是 ad-hoc 裸 HTTP
                                   # （判据在 settings.yml、调用在习惯里，
                                   # v3.19 acquire 根因同构）——本轮起第一关
                                   # 只准走 probe()。注意：engines= 显式点名
                                   # 可调度 disabled: true 的引擎（探活依赖
                                   # 此语义，实测 v3.19 startpage 禁用期
                                   # 单发 10 行即证）。

    engines= 语义两形态（v3.25 实网受控对照钉，判词在 settings.yml v3.25 段）:
        search(engines=X)  # 恒传 categories → 「默认集 ∪ 点名」：默认引擎
                           # 照常调度（实测 google cse 混入同场返回）
        probe(q, X)        # 不传 categories → engines= 严格收窄，只调度
                           # 点名引擎（单发探活的可比性依赖此语义）

注意:
    实例必须允许 JSON 输出（settings.yml: search.formats 含 json），
    否则返回 HTML 导致解析失败并走错误协议（实测 searx.be 的 JSON 未启用）。
"""
import json
import sys
import urllib.parse
import urllib.request
from typing import List, Dict, Optional

__all__ = ["search", "probe"]

_TOOL = "searxng"


def search(
    q: str,
    num: int = 10,
    since: Optional[str] = "7d",
    vendor: str = "?",
    role: str = "fallback",
    instance: str = "http://127.0.0.1:8888",
    categories: str = "general",
    on_error: str = "report",
    engines: Optional[str] = None,
) -> List[Dict]:
    """SearXNG 搜索

    Args:
        q: 搜索关键词
        num: 返回数量
        since: 时间窗 (24h / 7d / 30d / 90d)，默认 "7d"；
            传 None 或 "" 表示不过滤时间
        vendor: 主题分类（指标用）
        role: primary / fallback / verify
        instance: SearXNG 实例 URL（默认本地 8888；公网可填自建实例等）
        categories: 搜索类别（general / it / news / science 等）
        on_error: 错误协议
            - "report"（默认）: 出错返回 [{"error": ..., "tool": ..., "query": ...}]
            - "raise": 直接抛异常
            - "empty": 兼容旧行为，出错返回 []
        engines: SearXNG engines= 参数（逗号分隔引擎名；None=默认引擎集）。
            追加在 on_error 之后（v3.23）：既有调用方按位置传参不断链。
            探活/诊断用；常规搜索留 None。单引擎探活优先用 probe()。
            注意（v3.25 实测）：本函数恒传 categories，engines= 在这里是
            「默认集 ∪ 点名」语义（默认引擎照常调度）；要严格只调度点名
            引擎（不含默认集）用 probe()。行为级变更（engines= 时弃
            categories 换严格收窄）立项未决，改前本注释即契约。

    Returns:
        [{title, url, content, engine, category, vendor, role, since}, ...]
    """
    try:
        params = {
            "q": q,
            "format": "json",
            "categories": categories,
        }
        if since:
            time_range = _since_to_time_range(since)
            if time_range:          # 未知 since 映射为空串：不加参数（URL 干净）
                params["time_range"] = time_range
        if engines:                 # None/空串不加参数（URL 干净）
            params["engines"] = engines

        url = f"{instance}/search?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={"User-Agent": "ai-search-stack/2.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))

        results = []
        for item in data.get("results", [])[:num]:
            results.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
                "engine": item.get("engine", "searxng"),
                "category": item.get("category", ""),
                "vendor": vendor,
                "role": role,
                "since": since or "all",
            })
        return results
    except Exception as e:
        if on_error == "raise":
            raise
        if on_error == "report":
            return [{"error": f"{type(e).__name__}: {e}", "tool": _TOOL, "query": q}]
        return []  # on_error == "empty"：兼容旧行为


def probe(q: str, engine: str, instance: str = "http://127.0.0.1:8888",
          timeout: int = 20) -> Dict:
    """单引擎两关判据「第一关」探活（v3.23 库固化，判据原文见 settings.yml）。

    engines=<engine> 单发一发，返回：
        {"engine": 引擎名,
         "rows": 结果行数,
         "unresponsive": [该引擎的 unresponsive 条目（"engine: 原因" 文本）],
         "ok": rows>0 且 unresponsive 空（第一关通过判据）,
         "query": 探活词,
         ...故障时另有 "error": "类型: 详情"}
    纯观测函数：不写任何状态文件；判读与记账（连续过几轮 streak）由
    使用方落 settings.yml 观察注释——探活数据与判词分离。
    """
    url = f"{instance}/search?" + urllib.parse.urlencode({
        "q": q, "format": "json", "engines": engine})
    req = urllib.request.Request(url, headers={"User-Agent": "ai-search-stack/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        # 传输/解析故障 = 本次无有效观测（与「上游复发」是两回事，
        # 后者 rows=0 + unresponsive 有条目，ok=False 但仍是有效观测）
        return {"engine": engine, "rows": 0, "unresponsive": [], "ok": False,
                "query": q, "error": f"{type(e).__name__}: {e}"}
    rows = len(data.get("results", []))
    unres = [f"{u[0]}: {u[1]}" if isinstance(u, (list, tuple)) and len(u) >= 2
             else str(u)
             for u in data.get("unresponsive_engines", [])]
    return {"engine": engine, "rows": rows, "unresponsive": unres,
            "ok": rows > 0 and not unres, "query": q}


def _since_to_time_range(since: str) -> str:
    """将 since 转换为 SearXNG time_range 参数

    未知值不再静默映射为空串，会向 stderr 打一行警告（空串 = 不过滤时间）。
    """
    mapping = {
        "24h": "day",
        "7d": "week",
        "30d": "month",
        "90d": "year",
    }
    tr = mapping.get(since)
    if tr is None:
        print(f"[searxng] warning: unknown since={since!r}, "
              f"expected 24h/7d/30d/90d; no time filter applied", file=sys.stderr)
        return ""
    return tr


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("q", help="query")
    p.add_argument("--num", type=int, default=10)
    p.add_argument("--since", default="7d",
                   help="24h/7d/30d/90d，传空串表示不过滤时间")
    p.add_argument("--vendor", default="?")
    p.add_argument("--role", default="fallback")
    p.add_argument("--instance", default="http://127.0.0.1:8888")
    p.add_argument("--engines", default=None,
                   help="SearXNG engines= 参数（逗号分隔；单引擎探活用 --probe）")
    p.add_argument("--probe", metavar="ENGINE", default=None,
                   help="第一关单引擎探活模式：engines=ENGINE 单发，打印判据 "
                        "JSON；退出码 0=有效观测（ok 真假都是有效观测，判读看 "
                        "JSON 的 ok 字段）、1=传输/解析故障无有效观测"
                        "（doctor sogou 探活同语义）")
    args = p.parse_args()

    if args.probe:
        verdict = probe(args.q, args.probe, args.instance)
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
        sys.exit(0 if "error" not in verdict else 1)

    try:
        results = search(args.q, args.num, args.since, args.vendor, args.role,
                         args.instance, on_error="raise", engines=args.engines)
    except Exception as e:
        print(f"[searxng] error: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(results, ensure_ascii=False, indent=2))
