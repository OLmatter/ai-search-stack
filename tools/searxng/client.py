#!/usr/bin/env python3
"""searxng 客户端 —— 通用元搜索客户端

SearXNG 是一个开源元搜索引擎（聚合 Google/Bing/DuckDuckGo 等）。
当 google-bridge 被 CAPTCHA 锁时，用 searxng 兜底。

用法:
    from searxng_client import search
    results = search(q="claude max exploit", num=10, since="7d")
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from typing import List, Dict, Optional


def search(
    q: str,
    num: int = 10,
    since: Optional[str] = None,
    vendor: str = "?",
    role: str = "fallback",
    instance: str = "http://127.0.0.1:8888",
    categories: str = "general",
) -> List[Dict]:
    """SearXNG 搜索

    Args:
        q: 搜索关键词
        num: 返回数量
        since: 时间窗 (7d / 24h / 30d)
        vendor: 主题分类（指标用）
        role: primary / fallback / verify
        instance: SearXNG 实例 URL（默认本地 8888；公网可填 https://searx.be 等）
        categories: 搜索类别（general / it / news / science 等）

    Returns:
        [{title, url, content, engine, category}, ...]
    """
    params = {
        "q": q,
        "format": "json",
        "categories": categories,
    }
    if since:
        params["time_range"] = _since_to_time_range(since)

    url = f"{instance}/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "ai-search-stack/2.0"})

    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        print(f"[searxng] error: {e}", file=sys.stderr)
        return []

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


def _since_to_time_range(since: str) -> str:
    """将 since 转换为 SearXNG time_range 参数"""
    mapping = {
        "24h": "day",
        "7d": "week",
        "30d": "month",
        "90d": "year",
    }
    return mapping.get(since, "")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("q", help="query")
    p.add_argument("--num", type=int, default=10)
    p.add_argument("--since", default="7d")
    p.add_argument("--vendor", default="?")
    p.add_argument("--role", default="fallback")
    p.add_argument("--instance", default="http://127.0.0.1:8888")
    args = p.parse_args()

    results = search(args.q, args.num, args.since, args.vendor, args.role, args.instance)
    print(json.dumps(results, ensure_ascii=False, indent=2))
