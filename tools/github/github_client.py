#!/usr/bin/env python
"""GitHub 客户端 —— Releases / Advisories / Search

GitHub API 用于：
- 看项目最新 release（v0.8.0 → v0.8.1 包含什么）
- 看安全 advisory（CVE 详情）
- 搜索仓库 / 代码（精确匹配）

用法（唯一模块名，可与 hackernews_client / searxng_client 同进程组合）:
    from github_client import get_releases, get_advisories, search_repos
    releases = get_releases("anthropics/claude-code", num=10)

错误协议:
    所有函数默认 on_error="report"：出错返回
    [{"error": "HTTPError: 403 ...", "tool": "github", "query": ..., "action": ...}]
    调用方检查 result[0].get("error") 即可区分「故障」与「真空（0 结果）」。
    on_error="raise" 直接抛异常；on_error="empty" 兼容旧行为返回 []。
"""
import json
import os
import sys
import urllib.parse
import urllib.request
from typing import List, Dict

__all__ = ["get_releases", "get_advisories", "search_repos"]

_TOOL = "github"


def _github_request(url: str) -> object:
    """发起 GitHub API GET 并返回解析后的 JSON（异常交给调用方的错误协议处理）"""
    req = urllib.request.Request(url, headers={
        "User-Agent": "ai-search-stack/2.0",
        "Accept": "application/vnd.github+json",
    })
    if token := os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", f"token {token}")
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _handle_error(e: Exception, on_error: str, action: str, query) -> List[Dict]:
    """统一错误协议：raise / report / empty"""
    if on_error == "raise":
        raise
    if on_error == "report":
        return [{"error": f"{type(e).__name__}: {e}", "tool": _TOOL,
                 "query": query, "action": action}]
    return []  # on_error == "empty"：兼容旧行为


def get_releases(
    repo: str,
    num: int = 10,
    vendor: str = "?",
    role: str = "verify",
    on_error: str = "report",
) -> List[Dict]:
    """获取项目 release 列表

    Args:
        repo: owner/repo（如 "anthropics/claude-code"），拼 URL path 前会做转义
        num: 返回数量
        vendor: 主题分类
        role: primary / fallback / verify
        on_error: "report"（默认）/ "raise" / "empty"（旧行为 []）
    """
    try:
        # repo 直接拼进 URL path，必须转义（防注入/防特殊字符破坏 URL）
        repo_path = urllib.parse.quote(repo, safe="/")
        url = f"https://api.github.com/repos/{repo_path}/releases?per_page={num}"
        data = _github_request(url)

        results = []
        for r in data[:num]:
            results.append({
                "title": r.get("name") or r.get("tag_name", ""),
                "url": r.get("html_url", ""),
                "content": (r.get("body") or "")[:500],
                "tag": r.get("tag_name", ""),
                "ts": r.get("published_at", ""),
                "prerelease": r.get("prerelease", False),
                "vendor": vendor,
                "role": role,
                "since": "all",
            })
        return results
    except Exception as e:
        return _handle_error(e, on_error, action="releases", query=repo)


def get_advisories(
    ecosystem: str = "npm",
    num: int = 10,
    vendor: str = "?",
    role: str = "verify",
    on_error: str = "report",
) -> List[Dict]:
    """获取 GitHub Security Advisories

    Args:
        ecosystem: npm / pip / rubygems / composer / etc.（会做 URL 参数转义）
        num: 返回数量
        vendor: 主题分类
        role: primary / fallback / verify
        on_error: "report"（默认）/ "raise" / "empty"（旧行为 []）
    """
    try:
        params = urllib.parse.urlencode({"ecosystem": ecosystem, "per_page": str(num)})
        url = f"https://api.github.com/advisories?{params}"
        data = _github_request(url)

        results = []
        for a in data[:num]:
            results.append({
                "title": a.get("summary", ""),
                "url": a.get("html_url", ""),
                "content": (a.get("description") or "")[:500],
                "cve": a.get("cve_id", ""),
                "severity": a.get("severity", ""),
                "ts": a.get("published_at", ""),
                "vendor": vendor,
                "role": role,
                "since": "all",
            })
        return results
    except Exception as e:
        return _handle_error(e, on_error, action="advisories", query=ecosystem)


def search_repos(
    q: str,
    num: int = 10,
    vendor: str = "?",
    role: str = "verify",
    on_error: str = "report",
) -> List[Dict]:
    """搜索仓库

    Args:
        q: 搜索关键词
        num: 返回数量
        vendor: 主题分类
        role: primary / fallback / verify
        on_error: "report"（默认）/ "raise" / "empty"（旧行为 []）
    """
    try:
        params = {"q": q, "per_page": str(num)}
        url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(params)
        data = _github_request(url)

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
    except Exception as e:
        return _handle_error(e, on_error, action="search", query=q)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    def _add_common_args(sp):
        sp.add_argument("--num", type=int, default=10)
        sp.add_argument("--vendor", default=None,
                        help="主题分类；不传则用函数默认值 '?'")
        sp.add_argument("--role", default=None,
                        help="primary / fallback / verify；不传则用函数默认值 'verify'")

    p_rel = sub.add_parser("releases")
    p_rel.add_argument("repo")
    _add_common_args(p_rel)

    p_adv = sub.add_parser("advisories")
    p_adv.add_argument("--ecosystem", default="npm")
    _add_common_args(p_adv)

    p_search = sub.add_parser("search")
    p_search.add_argument("q")
    _add_common_args(p_search)

    args = p.parse_args()

    kwargs = {"num": args.num}
    if args.vendor is not None:
        kwargs["vendor"] = args.vendor
    if args.role is not None:
        kwargs["role"] = args.role

    try:
        if args.cmd == "releases":
            results = get_releases(args.repo, on_error="raise", **kwargs)
        elif args.cmd == "advisories":
            results = get_advisories(args.ecosystem, on_error="raise", **kwargs)
        elif args.cmd == "search":
            results = search_repos(args.q, on_error="raise", **kwargs)
    except Exception as e:
        print(f"[github/{args.cmd}] error: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(results, ensure_ascii=False, indent=2))
