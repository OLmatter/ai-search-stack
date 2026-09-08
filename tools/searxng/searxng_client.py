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

注意:
    实例必须允许 JSON 输出（settings.yml: search.formats 含 json），
    否则返回 HTML 导致解析失败并走错误协议（实测 searx.be 的 JSON 未启用）。
"""
import json
import sys
import urllib.parse
import urllib.request
from typing import List, Dict, Optional

__all__ = ["search"]

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
            params["time_range"] = _since_to_time_range(since)

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
    args = p.parse_args()

    try:
        results = search(args.q, args.num, args.since, args.vendor, args.role,
                         args.instance, on_error="raise")
    except Exception as e:
        print(f"[searxng] error: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(results, ensure_ascii=False, indent=2))
