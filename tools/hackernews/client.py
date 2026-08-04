#!/usr/bin/env python3
"""hackernews Algolia 客户端 —— 社区反应信号

HN Algolia 是 HackerNews 公开 API（https://hn.algolia.com/api）。
适合验证：技术社区对某事件 / 工具 / 漏洞 的反应。

用法:
    from client import search
    results = search(q="claude max exploit", since="7d")
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import List, Dict, Optional


def search(
    q: str,
    num: int = 10,
    since: Optional[str] = "7d",
    vendor: str = "?",
    role: str = "verify",
    tags: str = "story",
) -> List[Dict]:
    """HN Algolia 搜索

    Args:
        q: 搜索关键词
        num: 返回数量
        since: 时间窗 (24h / 7d / 30d)
        vendor: 主题分类
        role: primary / fallback / verify
        tags: story / comment / poll（默认 story）

    Returns:
        [{title, url, content, points, comments, author, ts}, ...]
    """
    # HN Algolia 使用 created_at_i 时间戳过滤
    ts = _since_to_timestamp(since) if since else 0

    params = {
        "query": q,
        "tags": tags,
        "hitsPerPage": str(num),
    }
    if ts:
        params["numericFilters"] = f"created_at_i>{ts}"

    url = "https://hn.algolia.com/api/v1/search?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "ai-search-stack/2.0"})

    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        print(f"[hackernews] error: {e}", file=sys.stderr)
        return []

    results = []
    for hit in data.get("hits", []):
        results.append({
            "title": hit.get("title", "") or hit.get("story_title", ""),
            "url": hit.get("url") or hit.get("story_url", f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"),
            "content": hit.get("story_text", "") or hit.get("comment_text", ""),
            "points": hit.get("points", 0),
            "comments": hit.get("num_comments", 0),
            "author": hit.get("author", ""),
            "ts": hit.get("created_at", ""),
            "vendor": vendor,
            "role": role,
            "since": since or "all",
        })
    return results


def _since_to_timestamp(since: str) -> int:
    """将 since 转换为 Unix timestamp"""
    now = datetime.utcnow()
    mapping = {
        "24h": now - timedelta(hours=24),
        "7d": now - timedelta(days=7),
        "30d": now - timedelta(days=30),
        "90d": now - timedelta(days=90),
    }
    dt = mapping.get(since)
    return int(dt.timestamp()) if dt else 0


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("q", help="query")
    p.add_argument("--num", type=int, default=10)
    p.add_argument("--since", default="7d")
    p.add_argument("--vendor", default="?")
    p.add_argument("--role", default="verify")
    p.add_argument("--tags", default="story")
    args = p.parse_args()

    results = search(args.q, args.num, args.since, args.vendor, args.role, args.tags)
    print(json.dumps(results, ensure_ascii=False, indent=2))
