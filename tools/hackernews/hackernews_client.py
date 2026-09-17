#!/usr/bin/env python
"""hackernews Algolia 客户端 —— 社区反应信号

HN Algolia 是 HackerNews 公开 API（https://hn.algolia.com/api）。
适合验证：技术社区对某事件 / 工具 / 漏洞 的反应。

用法（唯一模块名，可与 github_client / searxng_client 同进程组合）:
    from hackernews_client import search
    results = search(q="claude max exploit", since="7d")

错误协议:
    search(..., on_error="report")  # 默认
    出错时返回 [{"error": "URLError: ...", "tool": "hackernews", "query": "..."}]，
    调用方检查 result[0].get("error") 即可区分「故障」与「真空（0 结果）」。
    on_error="raise" 直接抛异常；on_error="empty" 兼容旧行为返回 []。
"""
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

__all__ = ["search"]

_TOOL = "hackernews"


def search(
    q: str,
    num: int = 10,
    since: Optional[str] = "7d",
    vendor: str = "?",
    role: str = "verify",
    tags: str = "story",
    on_error: str = "report",
) -> List[Dict]:
    """HN Algolia 搜索

    Args:
        q: 搜索关键词。**不支持布尔语法**（v3.42 如实声明）：Algolia 把
            AND/OR/NOT 当普通词参与匹配、不解析引号短语——`"a OR b"` 会
            搜"同时含 a、OR、b 的帖子"，结果跑偏。要多词任一命中请拆成
            多次调用。
        num: 返回数量
        since: 时间窗 (24h / 7d / 30d / 90d)；None/"" 表示不过滤时间
        vendor: 主题分类
        role: primary / fallback / verify
        tags: story / comment / poll（默认 story）
        on_error: 错误协议
            - "report"（默认）: 出错返回 [{"error": ..., "tool": ..., "query": ...}]
            - "raise": 直接抛异常
            - "empty": 兼容旧行为，出错返回 []

    Returns:
        [{title, url, content, points, comments, author, ts, vendor, role, since}, ...]
    """
    try:
        # HN Algolia 使用 created_at_i 时间戳过滤（UTC，避免本地时区漂移）
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
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))

        results = [_row_from_hit(hit, vendor=vendor, role=role, since=since)
                   for hit in data.get("hits", [])]
        return results
    except Exception as e:
        if on_error == "raise":
            raise
        if on_error == "report":
            return [{"error": f"{type(e).__name__}: {e}", "tool": _TOOL, "query": q}]
        return []  # on_error == "empty"：兼容旧行为


def _row_from_hit(hit: Dict, vendor: str, role: str, since: Optional[str]) -> Dict:
    """Algolia hit -> 统一结果行。

    comment 模式下 points/num_comments 为 JSON null，`hit.get("points", 0)`
    会拿到 None（key 存在时默认值不生效），调用方 `points >= 50` 就 TypeError——
    这里统一 `or 0` + int() 兜底（v3 回归测试锁死：tests/test_offline.py）。
    """
    return {
        "title": hit.get("title") or hit.get("story_title") or "",
        "url": hit.get("url") or hit.get("story_url")
               or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}",
        "content": hit.get("story_text") or hit.get("comment_text") or "",
        "points": int(hit.get("points") or 0),
        "comments": int(hit.get("num_comments") or 0),
        "author": hit.get("author") or "",
        "ts": hit.get("created_at") or "",
        "vendor": vendor,
        "role": role,
        "since": since or "all",
    }


def _since_to_timestamp(since: str) -> int:
    """将 since 转换为 Unix timestamp（必须用 aware UTC 时间，naive utcnow 会被按本地时区解释）"""
    now = datetime.now(timezone.utc)
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

    try:
        results = search(args.q, args.num, args.since, args.vendor, args.role,
                         args.tags, on_error="raise")
    except Exception as e:
        print(f"[hackernews] error: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(results, ensure_ascii=False, indent=2))
