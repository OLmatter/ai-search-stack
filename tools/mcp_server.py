#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ai-search-stack MCP server（stdio）—— 把工具箱原样包成 MCP tools。

定位：**接入层，不是统一层**。每个 tool 委托现有模块函数、参数原样透传
（toolbox 理念是"路由层统一，内部各留特色"，见 README/SOP）。本文件不含
任何业务逻辑，只做三件事：路由提示（docstring）、错误协议映射、stdout 卫兵。

启动:
    python tools/mcp_server.py          # stdio transport，挂在 MCP 客户端下用

ZCode / Claude Desktop 配置（stdio server）示例:
    {
      "mcpServers": {
        "ai-search-stack": {
          "command": "python",
          "args": ["<仓库路径>/ai-search-stack/tools/mcp_server.py"]
        }
      }
    }
    依赖：pip install "mcp>=2.1"（1.x SDK 亦兼容，见下方双版本导入）。

工具清单（15）:
    china_search        中国平台聚合搜索（知乎/B站/微信/百度16站）
    china_hotlist       中国平台热榜聚合（B站热门/微博热搜；知乎实测需登录态）
    read_page           通用阅读器（知乎 API 线 + 外域 HTTP/浏览器兜底）
    zhihu_question      知乎问题详情（官方 API）
    zhihu_answers       知乎回答列表（官方 API）
    zhihu_article       知乎专栏文章（官方 API）
    zhihu_comments      知乎评论读取（官方 comment_v5 API，含子评论展开）
    bilibili_video      B 站视频结构化详情（官方 view API）
    bilibili_subtitles  B 站字幕链路（cid 补全 + player/wbi/v2；未登录实测恒空列表）
    hn_search           Hacker News Algolia 搜索
    github_releases     GitHub release 列表
    github_advisories   GitHub Security Advisories
    searxng_search      SearXNG 聚合搜索（本地实例默认 127.0.0.1:8888）
    googlebridge_search 真 Google（转发本地 search_helper HTTP 18799）
    doctor              工具箱体检（文本报告；mode: full|cookie|sogou|hotlist）

耗时预期（客户端请据此设 read_timeout，建议 ≥120s 覆盖 read_page/googlebridge）:
    read_page        可能触发无头浏览器（10-15s）；知乎 cookie 过期自动引导更久
    china_search     bilibili 1-3s；百度有强制 ~20s 请求间隔，多平台串行按平台数放大
    googlebridge_search 隐身 Chrome 真搜 Google，数十秒级
    hn/github/searxng 秒级

并发模型（mcp 2.x 实测）：同步工具经 anyio.to_thread.run_sync 在工作线程执行，
慢调用不阻塞事件循环与其他调用（并发上限 = anyio 默认线程池 40）。stdin/stdout
单连接模型下，客户端串行 await 则天然串行——卡顿感知通常在客户端超时设置。

错误协议（与仓库统一错误协议一致）:
    模块 on_error 固定 "report"：错误作为正常返回内容嵌在 JSON 里
    （{"error": "<slug>: <详情>", "tool": ..., "query": ...}），区分「故障」与
    「真空（0 结果）」；任何未预期异常也被本层兜底成同形态 JSON，绝不炸 server。
"""
import contextlib
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional

__version__ = "3.33.0"

_TOOL_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# 工具箱模块导入：与 search.py 同款 try/except 双模式。tools/ 不是包（无
# __init__.py 且子目录名带连字符），所以实际生效路径是扁平导入 + sys.path 注入；
# 子目录已在 sys.path 的进程（如测试）则第一段直接命中。
# ---------------------------------------------------------------------------
try:
    import bilibili_engine as _bilibili
    import doctor as _doctor
    import github_client as _github
    import hackernews_client as _hn
    import searxng_client as _searxng
    import zhihu_content as _zhihu
    import search as _chat
except ImportError:  # 常规启动：把各工具子目录注入 sys.path 后扁平导入
    for _d in ("chat-scraper", "hackernews", "github", "searxng"):
        _p = os.path.join(_TOOL_DIR, _d)
        if _p not in sys.path:
            sys.path.insert(0, _p)
    import bilibili_engine as _bilibili
    import doctor as _doctor
    import github_client as _github
    import hackernews_client as _hn
    import searxng_client as _searxng
    import zhihu_content as _zhihu
    import search as _chat

# ---------------------------------------------------------------------------
# mcp SDK 双代兼容：2.x 把 FastMCP 改名 MCPServer（mcp.server.mcpserver），
# 1.x 仍叫 FastMCP（mcp.server.fastmcp）。按实际安装版本取用。
# ---------------------------------------------------------------------------
def _make_server():
    kwargs = {"name": "ai-search-stack", "instructions": _INSTRUCTIONS}
    try:
        from mcp.server.mcpserver import MCPServer as _S  # mcp >= 2
        kwargs["version"] = __version__
        return _S(**kwargs)
    except ImportError:
        from mcp.server.fastmcp import FastMCP as _S  # mcp < 2
        return _S(**kwargs)


_INSTRUCTIONS = """ai-search-stack 工具箱路由：
- 中国平台内容/社区（知乎、B站、微信公众号、百度16站）-> china_search / read_page / zhihu_* / bilibili_video / bilibili_subtitles
- 中国平台热榜监控（vendor 官宣/事件首发地/舆情雷达）-> china_hotlist
- 国际技术社区反应验证 -> hn_search
- GitHub release / 安全通告 -> github_releases / github_advisories
- 通用网页兜底聚合 -> searxng_search（本地实例）/ googlebridge_search（本地服务+Chrome 代理，真 Google）
- 通道体检 -> doctor

错误协议：错误不抛异常，作为 {"error": "...", "tool": ...} 嵌在返回 JSON 里，与「真空（0 结果）」可区分。
耗时：read_page 可能起无头浏览器（10-15s）；百度有 ~20s 强制间隔（多平台串行放大）；googlebridge 数十秒。
建议客户端 read_timeout >= 120s。"""

mcp = _make_server()


# ---------------------------------------------------------------------------
# 执行卫兵：stdout 卫兵 + 错误协议兜底 + JSON 序列化
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def _stdout_to_stderr():
    """工具库内的 stdout 打印重定向到 stderr。

    MCP stdio 下 stdout 只归 JSON-RPC 协议（zhihu 自愈引导等库代码会往
    stdout 打进度，混入即毁协议）。注意 redirect_stdout 是进程全局态，
    并发工具调用极端情况下可能短暂互串 stderr——只影响日志归属，不影响协议。
    """
    with contextlib.redirect_stdout(sys.stderr):
        yield


def _dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


def _err(tool: str, query: str, exc: BaseException) -> dict:
    slug = getattr(exc, "slug", None) or type(exc).__name__
    return {"error": f"{slug}: {exc}", "tool": tool, "query": query}


def _run(tool: str, query: str, fn, *args, **kwargs) -> str:
    """统一执行：任何异常兜底成统一错误协议 JSON（report 形态），不炸 server。"""
    try:
        with _stdout_to_stderr():
            result = fn(*args, **kwargs)
    except Exception as e:  # noqa: BLE001 —— 兜底即本层职责
        return _dumps([_err(tool, query, e)])
    if isinstance(result, str):
        return result
    return _dumps(result)


# ---------------------------------------------------------------------------
# 15 个 MCP tools —— 每个都是对现有模块函数的透传委托
# ---------------------------------------------------------------------------
@mcp.tool(description=(
    "中国平台聚合搜索：知乎/B站/掘金官方 API + 百度 site: 路由 16 站"
    "（CSDN/简书/豆瓣/微博/V2EX/SegmentFault/博客园/开源中国/51CTO/"
    "Gitee/微信公众号/头条/百度贴吧等）。\n"
    "何时用：找中文社区内容、验证国内舆论/资料。何时不用：英文技术讨论"
    "（用 hn_search）、GitHub release/通告（用 github_*）、通用英文搜索"
    "（用 searxng_search/googlebridge_search）。\n"
    "platforms 可选 bilibili、juejin（掘金官方搜索 API，结构化字段："
    "作者/浏览/点赞/评论/分类，裸调免登录）、wenxin（文心 AI 搜索，低频配额"
    "受限；返回单条聚合行：AI 答案 answer + 引用 citations，不是网页列表）、"
    "16 个站名、general（百度无 site 通用）、或任意"
    "形如域名的字符串（透传 site: 过滤）；省略=general。\n"
    "num 与单页上限（如实声明）：bilibili num>30 自动翻页（护栏 5 页，有效"
    "上限约 150 条）；juejin num>20 自动翻页（护栏 5 页，有效上限约 100 条）；"
    "百度系（general/16站/任意域名）num>20 自动翻页（护栏"
    "3 页，有效上限约 60 条，页间走引擎级 ~20s 节流，翻页耗时按页数放大）；"
    "sogou（百度降级环）与知乎链（SearXNG→搜狗→百度）单页到顶如实截断"
    "——搜狗连发风控阈值实测 4 发（v3.13 标定），不做翻页。\n"
    "耗时：bilibili/juejin 1-3s；知乎走 SearXNG→搜狗→百度降级链数秒；百度引擎有"
    "强制 ~20s 请求间隔，多平台串行按平台数放大（2 平台可能 40s+），请耐心。\n"
    "错误在返回 JSON 内（{\"error\": ...} 项），区分故障与 0 结果。"))
def china_search(q: str,
                 platforms: Optional[List[str]] = None,
                 num: int = 10,
                 since: Optional[str] = None,
                 vendor: str = "?",
                 role: str = "primary") -> str:
    """委托 chat-scraper search 门面（on_error 固定 report）。"""
    return _run("chat-scraper", q, _chat.search, q, platforms=platforms,
                num=num, since=since, vendor=vendor, role=role,
                on_error="report")


@mcp.tool(description=(
    "中国平台热榜聚合（无查询词的监控原语）：bilibili 热门 + 微博热搜的"
    "结构化榜单（rank/title/url），知乎热榜实测需登录态（平台位保留，恒报 "
    "zhihu_hotlist_needs_login，零网络请求）。\n"
    "bilibili 行：author/views/danmaku/likes/category/pubdate（官方 "
    "popular API，裸调即通，num>20 自动翻页护栏 5 页）；微博行：hot_value"
    "（热度值）+ label（爆/热/新/沸）（ajax/side/hotSearch + passport "
    "访客 incarnate 流，纯 HTTP 无浏览器，cookie 缓存复用；首调多 2 个 "
    "passport 请求）。\n"
    "何时用：vendor 官宣/事件首发地监控、舆情雷达——榜单是「正在发生」的"
    "信号源，与 china_search(q) 的「找已知词」互补。何时不用：找具体内容"
    "用 china_search；国际热点用 hn_search。\n"
    "platforms 可选 bilibili/weibo/zhihu，省略=默认可用集（bilibili+weibo）。"
    "耗时：秒级（微博首调约 10s，含节流间隔）。错误在返回 JSON 内"
    "（{\"error\": ..., \"platform\": ...} 项，无 query——热榜无查询词），"
    "区分故障与空榜。"))
def china_hotlist(platforms: Optional[List[str]] = None,
                  num: int = 10,
                  vendor: str = "?",
                  role: str = "primary") -> str:
    """委托 chat-scraper search 门面 hot()（on_error 固定 report）。"""
    return _run("chat-scraper", "", _chat.hot, platforms=platforms, num=num,
                vendor=vendor, role=role, on_error="report")


@mcp.tool(description=(
    "通用阅读器：读任意 URL 的正文，返回 {title, content, truncated, url, "
    "engine}（content 截 8000 时 truncated=true）。\n"
    "智能分流：知乎问题/回答/专栏走官方 API 线；B 站 /video/BVxx 走官方 "
    "view API；微信公众号文章走 HTTP 直读 + 浏览器兜底；其余域名 HTTP 直连、"
    "反爬时自动切无头浏览器。\n"
    "何时用：拿到一个 URL 需要正文（搜索结果页、知乎/B站/微信链接、普通网页）。"
    "何时不用：只需要知乎回答列表结构（用 zhihu_answers）、B 站数据字段"
    "（用 bilibili_video）。\n"
    "耗时：普通网页秒级；**可能触发无头浏览器 10-15s**；知乎 cookie 过期时"
    "自动无头引导刷新（额外十几秒）。请设 read_timeout >= 120s。\n"
    "错误（反爬验证页/网络失败）在返回 JSON 的 error 字段里如实上报。"))
def read_page(url: str) -> str:
    """委托 zhihu_content.read 通用阅读器。"""
    return _run("chat-scraper", url, _zhihu.read, url)


@mcp.tool(description=(
    "知乎问题详情（官方 API，结构化）：{id, title, detail, answer_count, url}。\n"
    "何时用：已知知乎问题 ID/链接，要问题标题与题干。要回答内容用 "
    "zhihu_answers；要专栏文章用 zhihu_article；懒得分辨时直接用 read_page。\n"
    "question_id 接受纯数字 ID 或完整问题 URL（自动提取）。\n"
    "耗时：秒级（走 cookie+签名 API，无浏览器）。cookie 过期会自动无头引导"
    "刷新一次（十几秒）。错误按 zhihu_* slug 如实上报。"))
def zhihu_question(question_id: str) -> str:
    """委托 zhihu_content.fetch_question。"""
    return _run("chat-scraper", question_id, _zhihu.fetch_question,
                question_id)


@mcp.tool(description=(
    "知乎回答列表（官方 API，结构化）：[{author, excerpt, voteup, url}]。\n"
    "何时用：已知知乎问题 ID/链接，要高赞回答摘要与作者。只要题干用 "
    "zhihu_question；要单个回答全文用 read_page。\n"
    "question_id 接受纯数字 ID 或完整问题 URL；num 上限 500（服务端 cursor "
    "翻页，is_end 即停）。\n"
    "实测上限（如实报告，v3.10）：v3.4 的 include=content 形态已被知乎登录"
    "门拦截（403 code=40353，全新 cookie 亦然），本工具改用无 include 形态"
    "——excerpt 摘要照常可用；部分问题服务端只放行前几条回答即 is_end"
    "（访客配额墙，13 答问题实测仅回 3 条），按 is_end 如实返回不伪装完整；"
    "要更多/全文走 read_page（浏览器线）。\n"
    "耗时：秒级~数秒（翻页按需）。错误按 zhihu_* slug 如实上报（如 "
    "zhihu_behavior_limited=行为风控临时限制，稍后再试）。"))
def zhihu_answers(question_id: str,
                  num: int = 10,
                  sort_by: str = "default") -> str:
    """委托 zhihu_content.fetch_answers。"""
    return _run("chat-scraper", question_id, _zhihu.fetch_answers,
                question_id, num=num, sort_by=sort_by)


@mcp.tool(description=(
    "知乎专栏文章（官方 API，结构化）：{id, title, content(纯文本, 截 8000 "
    "时带 truncated=true), "
    "created, updated, voteup, comment_count, url}。\n"
    "何时用：已知 zhuanlan.zhihu.com/p/<id> 文章链接或 ID。问题/回答用 "
    "zhihu_question / zhihu_answers；任意 URL 兜底用 read_page。\n"
    "耗时：秒级。错误按 zhihu_* slug 如实上报。"))
def zhihu_article(article_or_url: str) -> str:
    """委托 zhihu_content.fetch_article。"""
    return _run("chat-scraper", article_or_url, _zhihu.fetch_article,
                article_or_url)


@mcp.tool(description=(
    "知乎评论读取（官方 comment_v5 API，结构化）：[{id, author, "
    "content(纯文本≤500), like_count, created_time, child_comment_count, "
    "child_comments(已展开扁平子列表), reply_to, url}]。\n"
    "何时用：已知知乎回答/问题，要看评论区在说什么（舆情/反馈/多角度验证）。"
    "回答/问题/文章本体用 zhihu_question / zhihu_answers / zhihu_article；"
    "任意 URL 兜底用 read_page。\n"
    "target 格式：接受回答 ID（如 12202014）、问题 ID、或对应 URL（"
    "https://www.zhihu.com/question/111/answer/12202014 / "
    ".../question/19550227，自动提取）。纯数字默认按回答处理，问题需传 URL "
    "或 kind=\"question\"。\n"
    "order_by: score（默认/热门）| ts（最新）；num=根评论条数上限（评论多时"
    "自动沿服务端分页翻页，秒级~十秒级）。\n"
    "注意：部分评论端点需要知乎登录态，纯访客 cookie 会报 "
    "zhihu_auth_expired 并注明\"需登录、访客不可读、重跑引导无用\"。错误按"
    "统一协议上报（on_error 固定 report）。"))
def zhihu_comments(target: str,
                   num: int = 20,
                   order_by: str = "score",
                   kind: str = "answer",
                   expand_children: bool = True) -> str:
    """委托 zhihu_content.fetch_comments（on_error 固定 report）。"""
    return _run("chat-scraper", target, _zhihu.fetch_comments, target,
                num=min(int(num), 200), order_by=order_by, kind=kind,
                expand_children=expand_children, on_error="report")


@mcp.tool(description=(
    "B 站视频结构化详情（官方 view API，公开免签名）：{title, desc(截 2000 "
    "时带 truncated=true), owner, cid, page, part_title, pages_count, "
    "view, danmaku, like, favorite, pubdate, url, engine}。\n"
    "何时用：已知 BV 号或视频 URL，要播放/弹幕/点赞等数据字段。搜索视频用 "
    "china_search(platforms=[\"bilibili\"])；读页面形态用 read_page。\n"
    "video 接受纯 BV 号或任意含 BV 号的 URL；URL 带 ?p=N（或配 part 参数）"
    "取第 N 个分 P（v3.13 多 P 展开，默认 P1；分 P 超界如实报错含合法"
    "范围）。耗时：秒级。\n"
    "错误在返回 JSON 内（风控/不存在按统一错误协议上报）。"))
def bilibili_video(video: str, part: Optional[int] = None) -> str:
    """委托 bilibili_engine.fetch_video（Dict 或 List[错误] 双形态归一为 JSON）。"""
    return _run("chat-scraper", video, _bilibili.fetch_video, video,
                part=part, on_error="report")


@mcp.tool(description=(
    "B 站视频字幕读取（view 拿 cid + player/wbi/v2 wbi 签名）：{bvid, cid, "
    "page, part_title, pages_count, title, has_subtitles, subtitles:"
    "[{lan, lan_doc, lines:[{from, to, content}]}], url, note}。\n"
    "实测上限（如实报告）：未登录访客请求字幕列表恒为空——B站仅向登录态"
    "（SESSDATA）下发字幕（手动 CC 亦不豁免），本工具不带登录态，故当前 "
    "subtitles 恒为 []，这是真实上限不是故障；链路已按登录态形态实现。\n"
    "何时用：cid 补全（player API 前置）、或未来接入 SESSDATA 后取字幕"
    "文稿。只要播放数据用 bilibili_video。\n"
    "video 接受纯 BV 号或任意含 BV 号的 URL；URL 带 ?p=N（或配 part 参数）"
    "取第 N 个分 P（v3.13 多 P 展开，默认 P1；分 P 超界如实报错）。耗时："
    "秒级（2 个请求）。错误在返回 JSON 内（按统一错误协议上报）。"))
def bilibili_subtitles(video: str, part: Optional[int] = None) -> str:
    """委托 bilibili_engine.fetch_subtitles（Dict 或 List[错误] 双形态归一）。"""
    return _run("chat-scraper", video, _bilibili.fetch_subtitles, video,
                part=part, on_error="report")


@mcp.tool(description=(
    "Hacker News 搜索（Algolia API）：[{title, url, content, points, "
    "comments, author, ts}]。\n"
    "何时用：验证国际技术社区对某项目/话题的真实反应（高赞=强信号）。中文/"
    "中国平台内容用 china_search；通用搜索用 searxng_search。\n"
    "tags: story（默认）/ comment / poll；since: 24h/7d/30d/90d（默认 7d，"
    "传空串不过滤）。耗时：秒级，零部署。\n"
    "错误在返回 JSON 内。"))
def hn_search(q: str,
              num: int = 10,
              since: str = "7d",
              tags: str = "story",
              vendor: str = "?",
              role: str = "verify") -> str:
    """委托 hackernews_client.search。"""
    return _run("hackernews", q, _hn.search, q, num=num, since=since,
                vendor=vendor, role=role, tags=tags, on_error="report")


@mcp.tool(description=(
    "GitHub 项目 release 列表：[{title, url, content(release notes 前500字), "
    "tag, ts, prerelease}]。\n"
    "何时用：查某项目的版本发布/更新日志/新版本验证。安全通告用 "
    "github_advisories；搜仓库本身用 GitHub 网页或 searxng_search。\n"
    "repo 形如 \"owner/repo\"（如 anthropics/claude-code）。匿名 60 req/h，"
    "秒级返回。错误在返回 JSON 内。"))
def github_releases(repo: str,
                    num: int = 10,
                    vendor: str = "?",
                    role: str = "verify") -> str:
    """委托 github_client.get_releases。"""
    return _run("github", repo, _github.get_releases, repo, num=num,
                vendor=vendor, role=role, on_error="report")


@mcp.tool(description=(
    "GitHub Security Advisories 安全通告：[{title, url, content, cve, "
    "severity, ts}]。\n"
    "何时用：查某生态（npm/pip/rubygems/composer…）近期安全通告、验证依赖"
    "CVE。项目版本发布用 github_releases。\n"
    "ecosystem 例：npm / pip（默认 npm）。匿名 60 req/h，秒级返回。错误在"
    "返回 JSON 内。"))
def github_advisories(ecosystem: str = "npm",
                      num: int = 10,
                      vendor: str = "?",
                      role: str = "verify") -> str:
    """委托 github_client.get_advisories。"""
    return _run("github", ecosystem, _github.get_advisories, ecosystem,
                num=num, vendor=vendor, role=role, on_error="report")


@mcp.tool(description=(
    "SearXNG 聚合搜索（元搜索引擎）：[{title, url, content, engine, "
    "category}]。\n"
    "何时用：通用兜底搜索（CAPTCHA/主搜不可用时）。实例固定为本地 "
    "127.0.0.1:8888（tools/searxng/docker 一条命令起），不接受调用方指定"
    "其他实例（防数据外发到任意主机）。\n"
    "categories: general/it/news/science 等；since: 24h/7d/30d/90d（默认 7d，"
    "空串不过滤）。耗时：秒级。实例未启动时返回可读错误。"))
def searxng_search(q: str,
                   num: int = 10,
                   since: str = "7d",
                   categories: str = "general",
                   vendor: str = "?",
                   role: str = "fallback") -> str:
    """委托 searxng_client.search（实例固定本地，参数不暴露给 LLM）。"""
    # v3.7 安全收权：instance 不再作为工具参数暴露（LLM 不应能指定数据
    # 外发主机）；固定默认本地实例。底层 searxng_client 的 instance 参数
    # 保留（库能力，不受影响）。
    return _run("searxng", q, _searxng.search, q, num=num, since=since,
                vendor=vendor, role=role,
                instance="http://127.0.0.1:8888",
                categories=categories, on_error="report")


@mcp.tool(description=(
    "真 Google 搜索（本地 search_helper 服务转发，undetected-chromedriver）。\n"
    "何时用：WebSearch 类工具 100% CAPTCHA 时的真 Google 结果。前置条件硬："
    "本机 127.0.0.1:18799 已起服务（tools/google-bridge/start_search_helper.sh，"
    "需 Chrome+代理）——服务未启动会返回可读错误而非挂起。\n"
    "since: 24h/7d/30d（默认 7d）。耗时：隐身 Chrome 真搜 Google，数十秒级，"
    "请设 read_timeout >= 120s。\n"
    "错误形态：googlebridge_unreachable（服务没起）/ googlebridge_http_503"
    "（CAPTCHA 风控，请退避或换工具）/ http_502（页面加载失败）。"))
def googlebridge_search(q: str,
                        num: int = 10,
                        since: str = "7d",
                        vendor: str = "?",
                        role: str = "primary") -> str:
    """转发 127.0.0.1:18799/search（SEARCH_HELPER_PORT 可覆盖）；服务未起报可读错误。"""
    port = os.environ.get("SEARCH_HELPER_PORT", "18799")
    params = urllib.parse.urlencode({"q": q, "num": num, "since": since,
                                     "vendor": vendor, "role": role})
    url = f"http://127.0.0.1:{port}/search?{params}"
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": f"ai-search-stack-mcp/{__version__}"})
        with _stdout_to_stderr():
            with urllib.request.urlopen(req, timeout=120) as r:
                body = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        # 服务端语义化 5xx：503 captcha_blocked / 502 page_load_failed / 500
        try:
            detail = json.loads(e.read().decode("utf-8", "replace"))
        except Exception:
            detail = {}
        return _dumps([{"error": f"googlebridge_http_{e.code}: "
                                 f"{detail.get('error', e.reason)}",
                         "kind": detail.get("kind", ""),
                         "tool": "google-bridge", "query": q}])
    except urllib.error.URLError as e:
        return _dumps([{"error": (
            f"googlebridge_unreachable: 127.0.0.1:{port} 连接失败（{e.reason}）"
            f"——服务未启动。先运行 tools/google-bridge/start_search_helper.sh"
            f"（需 Chrome + 代理），或 python tools/google-bridge/"
            f"watchdog_task.py register 部署常驻看门狗（v3.28，服务死了自动"
            f"拉起）；或改用 searxng_search 兜底"),
            "tool": "google-bridge", "query": q}])
    except Exception as e:  # noqa: BLE001
        return _dumps([_err("google-bridge", q, e)])
    return _dumps(body)


@mcp.tool(description=(
    "ai-search-stack 工具箱体检：巡检全部通道健康并返回文本报告。\n"
    "mode 四态（默认 full）：full=全量巡检（9 项：本地 SearXNG 实例、知乎 "
    "cookie、标定钩子活性[覆盖 cookie+sogou+weibo 三个标定日志]、bilibili 官方 "
    "API、百度直连、热榜通道[bilibili popular 烂检测+微博访客 cookie 单发探活"
    "（禁 incarnate），读数顺带落账 weibo_cookie_lifetime_log.jsonl；知乎 "
    "needs_login 诚实上限不算故障]、google-bridge 服务、GitHub API、值班巡检"
    "趋势[shift_log 近 7 天条数/覆盖天数/每日分布/事件计数/最近一条摘要]）；"
    "cookie=只跑知乎 cookie 寿命标定探活（真实调一次 questions API，读数追加 "
    "state/cookie_lifetime_log.jsonl，禁自愈保真实寿命）；sogou=只跑搜狗恢复"
    "曲线单发探活（真实发一次搜索，读数含距上次风控秒数追加 "
    "state/sogou_recovery_log.jsonl）；hotlist=只跑微博访客 cookie 寿命标定"
    "探活（v3.30，缓存 cookie 单发禁 incarnate，读数含 cookie 龄追加 "
    "state/weibo_cookie_lifetime_log.jsonl）。\n"
    "何时用：某工具连续报错时先跑一次定位是通道故障还是真空；部署后自检；"
    "标定钩子排查用 cookie/sogou/hotlist 子模式。\n"
    "耗时：full 约 5-10s（6 项网络探活）；cookie/sogou/hotlist 单发秒级~"
    "十几秒。\n"
    "返回纯文本报告，末行含退出码语义：full 0=核心全绿或仅可选服务未起/"
    "1=有核心通道故障；cookie/sogou/hotlist 0=成功观测（expired/missing/"
    "blocked 均为有效标定读数）/1=本地故障。非法 mode 返回 error JSON。"))
def doctor(mode: str = "full") -> str:
    """复用 tools/doctor.py 的 check/探活体系：捕获 stdout 得到报告文本（不 subprocess）。"""
    if mode not in ("full", "cookie", "sogou", "hotlist"):
        return _dumps([{"error": f"ValueError: mode 须为 full|cookie|sogou|"
                                 f"hotlist，收到 {mode!r}",
                         "tool": "doctor", "query": mode}])
    buf = io.StringIO()
    try:
        if hasattr(_doctor, "_results"):
            _doctor._results.clear()  # 模块级累积列表，多次调用前清空
        with _stdout_to_stderr():
            with contextlib.redirect_stdout(buf):
                if mode == "cookie":
                    code = _doctor.cmd_cookie_probe()
                elif mode == "sogou":
                    code = _doctor.cmd_sogou_probe()
                elif mode == "hotlist":
                    code = _doctor.cmd_hotlist_probe()
                else:
                    code = _doctor.main()
    except Exception as e:  # noqa: BLE001
        return _dumps([_err("doctor", mode, e)])
    if mode == "full":
        tail = "0=核心通道全绿或仅可选服务未启动; 1=有核心通道故障"
    else:
        # 探活模式只观测不判故障：expired/blocked/missing 都是成功标定读数
        tail = ("0=成功观测（expired/missing/blocked 均为有效标定读数）; "
                "1=本地故障")
    return (buf.getvalue().rstrip() + f"\n(退出码: {code} —— {tail})")


def main() -> None:
    """stdio 入口：stdout 从此只归 MCP 协议。"""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
