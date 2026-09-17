#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""chat-scraper v3 门面 —— 中国平台聚合搜索

路由:
    "bilibili"                     -> bilibili 官方 API（结构化字段）
    "juejin"                       -> 掘金官方搜索 API（结构化字段，v3.28）
    "wenxin"                       -> 文心 AI 搜索（camoufox 无头 + SSE；
                                      低频 AI 信号源，单条聚合行）
    SITE_MAP 里的平台名（zhihu 等） -> 百度 + site: 站内过滤
    未知但形如域名的字符串          -> 百度 + site:<该域名>（透传）
    "general" / platforms=None     -> 百度无 site: 通用搜索

热榜（v3.29，无查询词的监控原语）:
    hot(platforms=["bilibili", "weibo"])  -> bilibili 热门/微博热搜
    （独立 hotlist_engine.py；知乎热榜实测需登录态，平台位保留但恒报
    zhihu_hotlist_needs_login——详见 hotlist_engine docstring）

用法:
    from search import search, list_platforms, hot
    results = search("claude", platforms=["zhihu", "bilibili"], num=10)
    rows = hot(platforms=["bilibili", "weibo"], num=20)

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
    from . import baidu_engine, bilibili_engine, hotlist_engine, juejin_engine
    from . import sogou_engine
    from . import wenxin_engine, zhihu_engine
except ImportError:  # 直接把本目录加进 sys.path 的扁平导入
    import baidu_engine  # type: ignore
    import bilibili_engine  # type: ignore
    import hotlist_engine  # type: ignore
    import juejin_engine  # type: ignore
    import sogou_engine  # type: ignore
    import wenxin_engine  # type: ignore
    import zhihu_engine  # type: ignore

__all__ = ["search", "list_platforms", "hot"]

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


def _baidu_then_sogou(q: str, num: int, since: Optional[str],
                      vendor: str, role: str, site: Optional[str], name: str):
    """百度 → 搜狗 降级：百度双桶（桌面/移动）被风控时第三环兜底。

    只在百度「异常」时降级；百度 0 结果不降——那是真空，多打一次搜狗
    纯属浪费。两环都失败抛百度原异常（保留 baidu slug），搜狗失败信息
    并入 message（不静默丢弃）。
    """
    try:
        return baidu_engine.search(q, num=num, since=since, vendor=vendor,
                                   role=role, site=site, platform=name,
                                   on_error="raise")
    except Exception as baidu_err:
        try:
            return sogou_engine.search(q, num=num, since=since, vendor=vendor,
                                       role=role, site=site, platform=name,
                                       on_error="raise")
        except Exception as sogou_err:
            baidu_err.args = (
                f"{baidu_err}; sogou fallback also failed: "
                f"{type(sogou_err).__name__}: {sogou_err}",)
            raise baidu_err


def list_platforms() -> Dict[str, str]:
    """返回 {平台名: 引擎说明}，含 "general" 与 "bilibili"。"""
    out: Dict[str, str] = {
        GENERAL: "baidu (no site:, general web search)",
        "bilibili": "bilibili official API (structured fields)",
        # 专用引擎链（非裸百度）：路由见 search()
        "juejin": "juejin official search API (structured fields, v3.28)",
        "zhihu": "dedicated chain: searxng -> sogou -> baidu site:zhihu.com",
        "zhuanlan": "dedicated chain: searxng -> sogou -> baidu "
                    "site:zhuanlan.zhihu.com",
        # 低频 AI 信号源（camoufox 无头；配额极紧，1005 即熔断 6h）
        "wenxin": "wenxin AI search (chat.baidu.com SSE via camoufox; "
                  "low-frequency, quota-gated)",
    }
    for name, domain in sorted(SITE_MAP.items()):
        if name in ("juejin", "zhihu", "zhuanlan"):
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
    since: Optional[str] = "7d",
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
        since: 时间窗（24h/7d/30d；bilibili 另支持 90d）。v3.42 起默认
            "7d"——与 hn/searxng/googlebridge 各引擎统一：监控场景忘传
            since 不再静默混入旧闻。显式传 None/"" 仍为不过滤（旧调用方
            兼容）。百度侧为 best-effort（gpc=stf），bilibili 侧为客户端
            pubdate 过滤。
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
            elif name == "juejin":
                # 掘金官方搜索 API（v3.28）：裸调即通、结构化字段
                # （作者/浏览/点赞/评论/分类），接管原百度 site:juejin.cn 路由
                results.extend(juejin_engine.search(
                    q, num=num, since=since, vendor=vendor, role=role,
                    on_error="raise"))
            elif name in ("zhihu", "zhuanlan"):
                # 知乎走专用降级链（SearXNG→搜狗→百度 site:），不用裸百度：
                # 知乎官方 API 纯 HTTP 不可用（见 zhihu_engine docstring），
                # 单靠百度时 IP 软风控期直接没结果
                results.extend(zhihu_engine.search(
                    q, num=num, since=since, vendor=vendor, role=role,
                    site=SITE_MAP.get(name, "zhihu.com"), on_error="raise"))
            elif name == "wenxin":
                # 文心 AI 搜索：低频高质量 AI 信号源（AI 认可度 + 引用发现），
                # 返回单条聚合行而非列表；配额极紧（每浏览器身份约 1 次），
                # 引擎见 1005 即熔断本 IP 长冷却——冷却期内不起浏览器直接报
                # wenxin_quota。不可当关键路径，见 wenxin_engine docstring。
                results.append(wenxin_engine.search(
                    q, vendor=vendor, role=role, on_error="raise"))
            elif name == GENERAL:
                results.extend(_baidu_then_sogou(
                    q, num=num, since=since, vendor=vendor, role=role,
                    site=None, name=GENERAL))
            else:
                site = SITE_MAP.get(name)
                if site is None:
                    if "." in name:
                        site = name  # 任意域名透传为 site: 过滤
                    else:
                        raise ValueError(
                            f"unknown platform {name!r}; see list_platforms()")
                results.extend(_baidu_then_sogou(
                    q, num=num, since=since, vendor=vendor, role=role,
                    site=site, name=name))
        except Exception as e:
            if on_error == "raise":
                raise
            if on_error == "report":
                results.append(_error_record(e, q, name))
            # on_error == "empty": 静默跳过故障平台
    return results


def hot(
    platforms: Optional[List[str]] = None,
    num: int = 10,
    vendor: str = "?",
    role: str = "primary",
    on_error: str = "report",
) -> List[Dict]:
    """热榜聚合（v3.29，无查询词的监控原语）——委托 hotlist_engine。

    平台：bilibili 热门/微博热搜（实测可用）+ zhihu（实测需登录态，
    恒报 zhihu_hotlist_needs_login，零网络请求）。None/空 -> 默认可用集。
    何时用：vendor 官宣/事件首发地监控、舆情雷达——榜单是「正在发生」
    的信号源，与 search(q) 的「找已知词」互补。
    错误协议同 search()；错误记录带 platform 无 query（热榜无查询词）。
    """
    return hotlist_engine.hot(platforms=platforms, num=num, vendor=vendor,
                              role=role, on_error=on_error)


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="chat-scraper: 中国平台聚合搜索（bilibili API + 百度 site:）")
    parser.add_argument("q", nargs="?", default=None, help="query")
    parser.add_argument("--platforms", default=None,
                        help="逗号分隔平台名，如 zhihu,bilibili；省略为通用搜索")
    parser.add_argument("--num", type=int, default=10)
    parser.add_argument("--since", default="7d",
                        help="24h/7d/30d（best-effort）；默认 7d（v3.42 起"
                             "与各引擎统一），传空串显式不过滤")
    parser.add_argument("--hot", action="store_true",
                        help="热榜模式（无查询词）：q 省略，--platforms "
                             "为 bilibili/weibo/zhihu，省略为默认可用集")
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

    platforms = ([p for p in args.platforms.split(",") if p.strip()]
                 if args.platforms else None)
    if args.hot:
        # 热榜模式：无查询词，错误协议/退出码与搜索模式一致
        results = hot(platforms=platforms, num=args.num, vendor=args.vendor,
                      role=args.role, on_error=args.on_error)
    else:
        if not args.q:
            parser.error("the following arguments are required: q")
        results = search(args.q, platforms=platforms, num=args.num,
                         since=args.since, vendor=args.vendor,
                         role=args.role, on_error=args.on_error)
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
