"""chat-scraper v3.13.0 —— 中国平台聚合搜索（bilibili 官方 API + 百度 site: 路由
+ 知乎官方 API 内容线 + 文心 AI 搜索低频线 + 通用阅读器）。

诚实声明：v3 从零重写；旧版（宣称 32+ 平台）代码损失为纯 NUL 空壳，不可考。
实测覆盖与已知限制见 README.md，不要按平台数量估算本工具能力。

v3.7.0：新增 wenxin 平台——文心 AI 搜索（chat.baidu.com SSE，camoufox 无头），
低频高质量 AI 信号源（AI 认可度 + 引用发现）；配额极紧（每浏览器身份约 1 次），
见 1005 即熔断本 IP 长冷却（默认 6h），不可当关键路径。

v3.8.1：server.py 加 Host 白名单校验（防 DNS rebinding 式 CSRF）。

v3.8.2：doctor --cookie-probe cookie 寿命标定探活（本包无代码改动，版本对齐）。

v3.9.0：bilibili fetch_subtitles（字幕读取链路；实测未登录访客字幕列表
恒为空——B站仅向登录态下发字幕，如实报告为空列表非故障）+ fetch_video 补
cid；doctor --cookie-probe 配 --renew-if-older-than H（实测访客 cookie
寿命 <48h，cron 低峰窗口顺带续期，白天使用零延迟）。

v3.10.0：fetch_answers 修复+增强——实测（2026-09-16）知乎登录门已拦截
include=content 形态（403 code=40353，全新 cookie 亦然，旧 v3.4 形态已死），
改用无 include 形态（excerpt 输出契约不变）+ 新增服务端 cursor 翻页
（num 上限 20→500，沿 paging.next 字节一致直调，max_pages 护栏；访客配额
墙按 is_end 如实截断不伪装完整）。

v3.11.0：doctor GitHub 403 根因修复（漏 UA 非 配额）+ bilibili 搜索翻页
（num>30 不再静默截断）+ Method 2 死代码清理 + zhihu_content 截断可见化
（CONTENT_LIMIT=8000 + truncated 标记四处输出口统一）。

v3.12.0：百度搜索翻页（num>20 不再静默截断：pn 偏移翻页，护栏 MAX_PAGES=3
页约 60 条，空页如实停，页间走引擎级 ~20s 节流；半途被风控如实抛错含已
收集页数/条数，0 收获才切移动桶兜底）+ 截断可见化扫尾（wenxin answer/
citations[].abstract、bilibili fetch_video desc 三处输出口带 truncated
标记，与 v3.11 zhihu_content 同一诚实纪律）+ 审查 A1：两引擎翻页跨页
去重（页间重叠条目不再重复进返回集，整页重复=排序穷尽信号如实停）。

v3.13.0：搜狗连发风控阈值标定（--probe 连发探测，读数落
state/sogou_throttle_log.jsonl；2026-09-16 实测连发阈值=4 发、
第 5 发即 antispider，风控后 ~171s 冷却恢复——架构图最后一个无标定
数据的引擎补齐）+ bilibili 多 P 展开（fetch_video/fetch_subtitles 接受
URL ?p=N 或 part 参数取任意分 P，输出 page/part_title/pages_count，
分 P 超界如实报错含合法范围）。
"""
from .search import list_platforms, search

__version__ = "3.13.0"
__all__ = ["search", "list_platforms", "__version__"]
