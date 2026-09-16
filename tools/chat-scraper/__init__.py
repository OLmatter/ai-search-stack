"""chat-scraper v3.10.0 —— 中国平台聚合搜索（bilibili 官方 API + 百度 site: 路由
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
"""
from .search import list_platforms, search

__version__ = "3.11.0"
__all__ = ["search", "list_platforms", "__version__"]
