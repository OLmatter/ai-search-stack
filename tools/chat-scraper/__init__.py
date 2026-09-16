"""chat-scraper v3.23.0 —— 中国平台聚合搜索（bilibili 官方 API + 百度 site: 路由
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

v3.14.0：搜狗恢复曲线标定机制（doctor --sogou-probe 单发探活，引擎侧
probe_once，判定与 search 同判据，读数含距上次风控秒数落
state/sogou_recovery_log.jsonl——连发标定测"多快触发"，恢复曲线靠
风控后周期性单发积累"多久恢复"）+ wenxin 声明对齐复查（README v3.7
输出契约补 v3.12 的 truncated 字段；mcp china_search 描述补 wenxin
单条聚合行声明；零真实文心调用）。

v3.15.0：doctor 钩子活性检查扩展覆盖 sogou_recovery_log（有读数后
最后一条 >48h 报警；文件缺失=可选观测项未启用不报警——恢复曲线是
增值观测，开了就必须活着）；mcp doctor 工具暴露 mode 子模式参数
（full|cookie|sogou，默认 full，cookie/sogou 复用 doctor 对应探活
函数）。本包业务代码无改动（版本对齐 v3.8.2 先例）。

v3.16.0：doctor 新增值班巡检趋势检查（shift_log.md 近 7 天记录条数/
覆盖天数/疑似异常项数，可选观测不判核心故障）+ SearXNG 禁用引擎
恢复观察（v3.15 禁用的 brave/duckduckgo/startpage 经 enabled_engines
单发探活全部通过，但回滚启用 + restart 后聚合搜索即全部复发——
单发探活通过 ≠ 可回滚，维持禁用，观察记录与再评估方法写进
settings.yml 注释）。本包业务代码无改动（版本对齐 v3.8.2 先例）。

v3.17.0：新增 worker_queue 模块——worker_queue.json 派工队列认领机制
（多 worker 并行领同一队列互踩的修复，848065c 与并行班次工作树编辑逐字
一致即互踩实证，本版实施期间工作树第二次实时互踩、对侧已 stash 为
v318-batch-wip 让出工作区）：claim 先 O_EXCL 原子建伴生标记
<queue>.claim.json（绝不写队列文件本身），他人见有效认领即 skipped
（可见持有者与 age）；超时（默认 30 分钟无 complete）或标记损坏走
接管——tmp + os.replace 原子覆盖 + 读回校验保并发接管单一赢家；
complete 只删自己的标记（别人的删不掉）；clear 原子清空队列。
Windows/POSIX 双兼容纯标准库。

v3.18.0：doctor 值班巡检趋势统计口径重做（shift_log.md 近 7 天：记录
条数/覆盖天数/每日条数分布/关键事件计数[restart/处置/❌/恶化 纯字面
大小写敏感子串，一行可命中多词]/最近一条时间戳+首 80 字摘要；缺文件/
空/全坏行=可选观测未启用不报警，有记录但 7 天零记录亮 ⚠️ 连续性中断，
optional 不判核心故障——沿 sogou_recovery_log 先例）+ doctor GitHub
检查可选 GITHUB_TOKEN 认证（设置后带 Authorization: Bearer 头，缓解
匿名 60 req/h 共享配额的限流窗口误报，tools/github/github_client.py
同款约定）。本包业务代码无改动（版本对齐 v3.8.2 先例）。

v3.22.0：stop_wake append-only 决策日志（每次触发一行 JSONL 到
~/.zcode/stop_wake_decisions.jsonl：ts/decision/pass 归因标签或完整
block 文本；写日志异常一律吞掉、绝不影响决策与退出码；消除 v3.21
声明的"钩子无决策日志"观察盲区）+ 收工必写 shift_log 纪律固化
（CONTRIBUTING 版本发布检查点；v3.19/v3.20 历史条目标注补记）。

v3.21.0：cookie 寿命标定首批数据分析落账（7 读数/唯一死亡实测 47.38h ≈47.4h，36h 续期阈值维持——n=1 不够调参；renew 实战首例 1/1 成功零误触发）+ doctor GBK 控制台加固（errors="replace"，cron 实录 UnicodeEncodeError 不再崩报告；读数本就由 probe_once 先落账）。业务行为零变更。

v3.20.0：claim 固化进领活入口（根因修复）——worker_queue 新增
acquire()：认领+读队列一步完成的唯一入口，skipped 不返回 instructions
（活内容不外泄，机制上杜绝"看到活就干"的互踩形态；v3.17 的 claim()
落地后被实证零使用——并行 worker 领活不查 sidecar 直接干活，机制在
库里、路径在习惯里等于没修）；新增 hooks/stop_wake.py 仓库真源
（Stop 钩子：有活+无有效认领 → block 且理由自带强制条款；有活+有效
认领 → 放行不唤醒第二个；部署副本 ~/.zcode/hooks/stop_wake.py 同步，
旧版先备份）。+ SearXNG 回滚判据细化到单引擎粒度（每引擎独立两关：
单发探活 + 仅回滚该引擎 restart 后聚合 unresponsive 清零；三引擎整组
判据把可救的和无救的绑死——v3.18 startpage 单发恢复只能陪禁）。
v3.23.0：searxng_client 探活机制固化——search() 新增 engines= 参数
（追加在 on_error 之后，既有调用方位置传参不断链）+ probe() 单引擎
两关判据「第一关」函数（ok = rows>0 且 unresponsive 空；纯观测不写
状态，streak 记账归 settings.yml 观察注释）——v3.16~v3.23 六轮探活
全是 ad-hoc 裸 HTTP，判据在 settings.yml、调用在习惯里（v3.19
acquire 根因同构），本轮起第一关只准走 probe()。
"""
from .search import list_platforms, search

__version__ = "3.23.0"
__all__ = ["search", "list_platforms", "__version__"]
