#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""chat-scraper v3 门面 —— 中国平台聚合搜索

路由:
    "bilibili"                     -> bilibili 官方 API（结构化字段）
    SITE_MAP 里的平台名（zhihu 等） -> 百度 + site: 站内过滤
    未知但形如域名的字符串          -> 百度 + site:<该域名>（透传）
    "general" / platforms=None     -> 百度无 site: 通用搜索

用法:
    from search import search, list_platforms
    results = search("claude", platforms=["zhihu", "bilibili"], num=10)

CLI:
    python search.py "claude" --platforms zhihu,bilibili --num 10

错误协议（与仓库其他工具一致）:
    search(..., on_error="report")  # 默认
    某平台出错时聚合结果里出现
        {"error": "baidu_soft_blocked: ...", "tool": "chat-scraper",
         "query": q, "platform": p}
    调用方检查 item.get("error") 区分「故障」与「真空（0 结果）」。
    on_error="raise" 直接抛出; on_error="empty" 兼容旧行为静默跳过故障平台。

注意:
    覆盖率是诚实的、分层的（实测 / best-effort），见 README.md 实测覆盖表。
    百度引擎有强制请求间隔（默认 20s），多平台串行搜索会按平台数放大耗时。
"""
import argparse
import json
import sys
from typing import Dict, List, Optional

try:
    from . import baidu_engine, bilibili_engine, zhihu_engine  # 包内导入
except ImportError:  # 直接把本目录加进 sys.path 的扁平导入
    import baidu_engine  # type: ignore
    import bilibili_engine  # type: ignore
    import zhihu_engine  # type: ignore

__all__ = ["search", "list_platforms"]

_TOOL = "chat-scraper"
GENERAL = "general"

# 平台名 -> 站点域名（site: 过滤用）。实测覆盖状态见 README.md 实测覆盖表。
SITE_MAP: Dict[str, str] = {
    "zhihu": "zhihu.com",
    "zhuanlan": "zhuanlan.zhihu.com",
    "csdn": "csdn.net",
    "juejin": "juejin.cn",
    "jianshu": "jianshu.com",
    "douban": "douban.com",
    "weibo": "weibo.com",
    "v2ex": "v2ex.com",
    "segmentfault": "segmentfault.com",
    "cnblogs": "cnblogs.com",
    "oschina": "oschina.net",
    "51cto": "51cto.com",
    "gitee": "gitee.com",
    "weixin": "mp.weixin.qq.com",
    "toutiao": "toutiao.com",
    "baidu_tieba": "tieba.baidu.com",
}


def list_platforms() -> Dict[str, str]:
    """返回 {平台名: 引擎说明}，含 "general" 与 "bilibili"。"""
    out: Dict[str, str] = {
        GENERAL: "baidu (no site:, general web search)",
        "bilibili": "bilibili official API (structured fields)",
        # 专用引擎链（非裸百度）：路由见 search()
        "zhihu": "dedicated chain: searxng -> sogou -> baidu site:zhihu.com",
        "zhuanlan": "dedicated chain: searxng -> sogou -> baidu "
                    "site:zhuanlan.zhihu.com",
    }
    for name, domain in sorted(SITE_MAP.items()):
        if name in ("zhihu", "zhuanlan"):
            continue    # 已由专用引擎链接管，避免误导消费者
        out[name] = f"baidu site:{domain}"
    return out


def _normalize(platforms: Optional[List[str]]) -> List[str]:
    """None/空 -> ["general"]；去空白、去重、保序（general 也是一等平台）。"""
    if not platforms:
        return [GENERAL]
    out: List[str] = []
    for p in platforms:
        name = str(p).strip().lower()
        if name and name not in out:
            out.append(name)
    return out or [GENERAL]


def _error_record(e: Exception, q: str, platform: str) -> Dict:
    """统一错误条目（slug 异常优先用 slug，否则用异常类名；
    引擎链异常可带 chain 属性，一并透传）。"""
    slug = getattr(e, "slug", None) or type(e).__name__
    record = {"error": f"{slug}: {e}", "tool": _TOOL,
              "query": q, "platform": platform}
    chain = getattr(e, "chain", None)
    if chain:
        record["chain"] = chain
    return record


def search(
    q: str,
    platforms: Optional[List[str]] = None,
    num: int = 10,
    since: Optional[str] = None,
    vendor: str = "?",
    role: str = "primary",
    on_error: str = "report",
) -> List[Dict]:
    """聚合搜索：按平台路由到 bilibili API 或百度 site: 过滤。

    Args:
        q: 搜索关键词
        platforms: 平台名列表（见 list_platforms()）。
            None / 空 / 含 "general" -> 百度无 site: 通用搜索；
            未知但形如域名的字符串按 site: 透传，其余报 unknown platform。
        num: 每个平台的返回条数上限
        since: 时间窗（24h/7d/30d；bilibili 另支持 90d），None/"" 不过滤。
            百度侧为 best-effort（gpc=stf），bilibili 侧为客户端 pubdate 过滤。
        vendor: 主题分类（指标用，透传）
        role: primary / fallback / verify（透传）
        on_error: "report"（默认）/ "raise" / "empty"（见模块 docstring）

    Returns:
        各平台结果顺序聚合；出错平台按 on_error 协议处理。
    """
    results: List[Dict] = []
    for name in _normalize(platforms):
        try:
            if name == "bilibili":
                results.extend(bilibili_engine.search(
                    q, num=num, since=since, vendor=vendor, role=role,
                    on_error="raise"))
            elif name in ("zhihu", "zhuanlan"):
                # 知乎走专用降级链（SearXNG→搜狗→百度 site:），不用裸百度：
                # 知乎官方 API 纯 HTTP 不可用（见 zhihu_engine docstring），
                # 单靠百度时 IP 软风控期直接没结果
                results.extend(zhihu_engine.search(
                    q, num=num, since=since, vendor=vendor, role=role,
                    site=SITE_MAP.get(name, "zhihu.com"), on_error="raise"))
            elif name == GENERAL:
                results.extend(baidu_engine.search(
                    q, num=num, since=since, vendor=vendor, role=role,
                    site=None, platform=GENERAL, on_error="raise"))
            else:
                site = SITE_MAP.get(name)
                if site is None:
                    if "." in name:
                        site = name  # 任意域名透传为 site: 过滤
                    else:
                        raise ValueError(
                            f"unknown platform {name!r}; see list_platforms()")
                results.extend(baidu_engine.search(
                    q, num=num, since=since, vendor=vendor, role=role,
                    site=site, platform=name, on_error="raise"))
        except Exception as e:
            if on_error == "raise":
                raise
            if on_error == "report":
                results.append(_error_record(e, q, name))
            # on_error == "empty": 静默跳过故障平台
    return results


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="chat-scraper: 中国平台聚合搜索（bilibili API + 百度 site:）")
    parser.add_argument("q", nargs="?", default=None, help="query")
    parser.add_argument("--platforms", default=None,
                        help="逗号分隔平台名，如 zhihu,bilibili；省略为通用搜索")
    parser.add_argument("--num", type=int, default=10)
    parser.add_argument("--since", default=None,
                        help="24h/7d/30d（best-effort），省略不过滤")
    parser.add_argument("--vendor", default="?")
    parser.add_argument("--role", default="primary")
    parser.add_argument("--on-error", default="report",
                        choices=["report", "raise", "empty"])
    parser.add_argument("--list-platforms", action="store_true",
                        help="列出支持的平台后退出")
    args = parser.parse_args()

    if args.list_platforms:
        print(json.dumps(list_platforms(), ensure_ascii=False, indent=2))
        return 0
    if not args.q:
        parser.error("the following arguments are required: q")

    platforms = ([p for p in args.platforms.split(",") if p.strip()]
                 if args.platforms else None)
    results = search(args.q, platforms=platforms, num=args.num,
                     since=args.since, vendor=args.vendor, role=args.role,
                     on_error=args.on_error)
    errors = [r for r in results if "error" in r]
    if errors:
        # 任一平台故障即 stderr + exit 1（与仓库统一错误协议一致）；
        # 半成功聚合的数据仍可经库调用 on_error="report" 获取
        for r in errors:
            print(f"[chat-scraper] error ({r.get('platform', '?')}): {r['error']}",
                  file=sys.stderr)
        return 1
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(_main())
