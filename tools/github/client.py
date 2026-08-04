#!/usr/bin/env python3
"""GitHub 客户端 —— Releases / Advisories / Search

GitHub API 用于：
- 看项目最新 release（v0.8.0 → v0.8.1 包含什么）
- 看安全 advisory（CVE 详情）
- 搜索仓库 / 代码（精确匹配）

用法:
    from client import get_releases, search_repos
    releases = get_releases("anthropics/claude-code", num=10)
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from typing import List, Dict, Optional


def get_releases(
    repo: str,
    num: int = 10,
    vendor: str = "?",
    role: str = "verify",
) -> List[Dict]:
    """获取项目 release 列表

    Args:
        repo: owner/repo（如 "anthropics/claude-code"）
        num: 返回数量
        vendor: 主题分类
        role: primary / fallback / verify
    """
    url = f"https://api.github.com/repos/{repo}/releases?per_page={num}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "ai-search-stack/2.0",
        "Accept": "application/vnd.github+json",
    })
    if token := os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", f"token {token}")

    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        print(f"[github/releases] error: {e}", file=sys.stderr)
        return []

    results = []
    for r in data[:num]:
        results.append({
            "title": r.get("name") or r.get("tag_name", ""),
            "url": r.get("html_url", ""),
            "content": (r.get("body", "") or "")[:500],
            "tag": r.get("tag_name", ""),
            "ts": r.get("published_at", ""),
            "prerelease": r.get("prerelease", False),
            "vendor": vendor,
            "role": role,
            "since": "all",
        })
    return results


def get_advisories(
    ecosystem: str = "npm",
    num: int = 10,
    vendor: str = "?",
    role: str = "verify",
) -> List[Dict]:
    """获取 GitHub Security Advisories

    Args:
        ecosystem: npm / pip / rubygems / composer / etc.
        num: 返回数量
    """
    url = f"https://api.github.com/advisories?ecosystem={ecosystem}&per_page={num}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "ai-search-stack/2.0",
        "Accept": "application/vnd.github+json",
    })
    if token := os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", f"token {token}")

    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        print(f"[github/advisories] error: {e}", file=sys.stderr)
        return []

    results = []
    for a in data[:num]:
        results.append({
            "title": a.get("summary", ""),
            "url": a.get("html_url", ""),
            "content": (a.get("description", "") or "")[:500],
            "cve": a.get("cve_id", ""),
            "severity": a.get("severity", ""),
            "ts": a.get("published_at", ""),
            "vendor": vendor,
            "role": role,
            "since": "all",
        })
    return results


def search_repos(
    q: str,
    num: int = 10,
    vendor: str = "?",
    role: str = "verify",
) -> List[Dict]:
    """搜索仓库

    Args:
        q: 搜索关键词
        num: 返回数量
    """
    params = {"q": q, "per_page": str(num)}
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": "ai-search-stack/2.0",
        "Accept": "application/vnd.github+json",
    })
    if token := os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", f"token {token}")

    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        print(f"[github/search] error: {e}", file=sys.stderr)
        return []

    results = []
    for r in data.get("items", [])[:num]:
        results.append({
            "title": r.get("full_name", ""),
            "url": r.get("html_url", ""),
            "content": r.get("description", ""),
            "stars": r.get("stargazers_count", 0),
            "language": r.get("language", ""),
            "ts": r.get("updated_at", ""),
            "vendor": vendor,
            "role": role,
            "since": "all",
        })
    return results


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    p_rel = sub.add_parser("releases")
    p_rel.add_argument("repo")

    p_adv = sub.add_parser("advisories")
    p_adv.add_argument("--ecosystem", default="npm")

    p_search = sub.add_parser("search")
    p_search.add_argument("q")

    args = p.parse_args()

    if args.cmd == "releases":
        print(json.dumps(get_releases(args.repo), ensure_ascii=False, indent=2))
    elif args.cmd == "advisories":
        print(json.dumps(get_advisories(args.ecosystem), ensure_ascii=False, indent=2))
    elif args.cmd == "search":
        print(json.dumps(search_repos(args.q), ensure_ascii=False, indent=2))
