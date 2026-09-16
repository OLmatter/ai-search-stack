# Changelog

## [3.29.0] - 2026-09-17

### 🎯 热榜聚合批次：hotlist_engine（A2）——B站热门/微博热搜/知乎诚实上限

- **A2 热榜聚合（`tools/chat-scraper/hotlist_engine.py` + 门面
  `search.hot()` 路由 + MCP `china_hotlist` 工具，第 15 个工具）**：
  无查询词的监控原语（vendor 官宣/事件首发地监控、舆情雷达），与
  search(q) 语义不同构，故独立引擎 + 独立动词（bilibili_video 与
  search 分工具同款先例）。实测（2026-09-17，逻辑探测预算 8 发实耗 8：
  评估 6 发 + 微博 incarnate 全链实跑 1 发 + 聚合验收实跑 1 发）：
  - **bilibili 热门线**：`/x/web-interface/popular` API **裸调即通**
    （连 buvid3 都不需要——对照搜索接口必须有；探测 #3 HTTP 200 +
    code=0，20 条全结构化字段）。ps=20/pn=N 分页（no_more=true 或空页
    即停，护栏 5 页约 100 条，跨页去重 v3.12 同款）；会话/节流复用
    bilibili_engine 进程级单例（不重复领 buvid3）；输出 author/views/
    danmaku/likes/category/pubdate；**热门页无热度值字段——如实不造
    hot_value**
  - **微博热搜线**：`ajax/side/hotSearch` 需访客身份（裸 UA 403 探测
    #2、m.weibo.cn container API ok=-100 弹 passport 登录墙探测
    #5/#6 均实测排除）——实现 passport **访客 incarnate 流**：
    genvisitor POST 领 tid → incarnate GET 换 SUB/SUBP（纯 HTTP 两
    请求，无浏览器；JSONP 壳实测为 `window.gen_callback &&
    gen_callback({...})` 形态）。cookie 缓存
    `state/weibo_visitor_cookies.json` 复用；HTTP 级（401/403）与
    信封级（ok!=1）失效均自动重领一次，重领后仍失败如实抛；is_ad=1
    广告位剔除（宁缺勿错）；输出 hot_value 热度值 + label
    （爆/热/新/沸）+ s.weibo.com 检索 URL
  - **知乎热榜线：访客不可用（诚实上限非故障）**——官方端点
    `/api/v3/feed/topstory/hot-lists/total` 裸调 401（探测 #1）；
    zhihu_content cookie+签名线（自愈引导刚刷新的全套新访客 cookie +
    x-zse-96 签名）仍 **401 code=101「身份未经过验证」**（探测 #4）——
    端点需登录态。平台位保留恒报 `zhihu_hotlist_needs_login`，
    **零网络请求**（不烧引导）；凭据线归主人，本引擎不带登录态
  - 错误协议统一（report/raise/empty 三态）；错误记录带 platform 无
    query（热榜无查询词）；`CHAT_SCRAPER_WEIBO_MIN_INTERVAL` 微博节流
    （默认 5s）；门面 `search.py` 新增 `hot()` + CLI `--hot`（q 省略）
- test_v3290 23 新钉（bilibili 线 7 + weibo 线 6 + zhihu 诚实上限 2 +
  聚合路由/门面/CLI/MCP 5 + 版本锁/诚实文档证据链 3，全部离线零榜单
  请求）；test_v3280 精确版本锁降常青下限交接（v3.26→v3.27→v3.28
  先例）；468→491 tests 连续两轮绿
- **同批：ONLOGON 管理员重试成功**（2026-09-17，PowerShell
  Start-Process -Verb RunAs 重跑 register，ExitCode=0）——
  `ai-search-gbridge-boot` 已落地（schtasks /Query /TN exit=0 就绪，
  ONLOGON 触发器下次运行 N/A 属正常显示），v3.28 的 DEGRADED 降级补齐；
  承重 MINUTE 任务 /F 覆盖重注册不受影响。C1 扫尾观察（只评估不动）：
  comments 聚簇 ~204 行（占 23%），zhihu_content 893 vs
  bilibili_engine 592 = 1.51x < 2x 拆分判据，且本轮 zhihu_content
  零改动——未到二次拆分点，继续观察


## [3.28.0] - 2026-09-17

### 🎯 三轴批次：掘金官方 API 专用引擎（A1）+ google-bridge 常驻看门狗（B1）+ 通用阅读线拆分 read_page（C1）

- **A1 juejin 专用引擎（`tools/chat-scraper/juejin_engine.py`，仿 bilibili
  「官方 API 优先于搜索引擎曲线」模式）**：实测（2026-09-16，探测预算
  8 发实耗 2）裸调免 cookie，信封 `{err_no, err_msg, data[直接列表],
  count, cursor, has_more}`——data 是直接列表不是 `{result:[]}` 包装；
  条目 `result_type=2` + `result_model` dict（article_info/
  author_user_info/category）；分页沿顶层不透明游标串（如
  `"20_20260917..."`），`has_more=False` 或游标缺失即停。结构化输出
  title/url/snippet/author/views/diggs/comments/category/pubdate；类型
  显式过滤（result_type=2 + article_id 非空，其余形态宁缺勿错如实暴露）
  + 跨页去重（v3.12 审查 A1 同款）+ since 客户端 ctime 过滤
  （24h/7d/30d/90d）；num>20 自动翻页（护栏 5 页约 100 条，页间引擎级
  `_wait_turn` 节流，`CHAT_SCRAPER_JUEJIN_MIN_INTERVAL` 默认 2s）；错误
  协议统一（`juejin_api_error`）。门面接管：`platforms=["juejin"]` 不再
  落百度 site:juejin.cn（zhihu 先例）；mcp china_search 描述、README
  覆盖表、list_platforms 同步（juejin 升 ✅ 实测行）
- **B1 google-bridge 常驻看门狗（服务死了自动拉起，「真 Google」通道常亮；
  `tools/google-bridge/watchdog.py` + `watchdog_task.py`）**：
  - watchdog.py：`/health` 检查（任何 HTTP 应答=活，503 语义态也算；
    连接拒绝/超时=死）→ 不可达即分离进程拉起 search_helper.py
    （Windows DETACHED_PROCESS|CREATE_NEW_PROCESS_GROUP；POSIX
    start_new_session），宽限 20s 轮询恢复（helper 先绑端口后懒加载
    Chrome，恢复是秒级）；决策流水 `state/watchdog.log` append-only；
    .env setdefault 兜底加载（永不覆盖已导出变量，:= 语义）
  - 退出码契约钉死：0=健康无动作 / 1=拉起且宽限内恢复 / 2=拉起但宽限
    未达（进程层看门狗只保进程，代理断/Chrome 坏走 /chrome_ready 与
    自愈）/ 3=--check-only 且不健康
  - watchdog_task.py 计划任务注册器：承重任务 `ai-search-gbridge-watchdog`
    （MINUTE 默认 15 分钟，死亡恢复上限=间隔）+ 增强任务
    `ai-search-gbridge-boot`（ONLOGON 开机即拉）；**实测普通权限令牌
    注册 ONLOGON 被系统拒绝（「拒绝访问」，限当前用户+/IT 亦然）→
    降级语义**：承重成败定退出码，开机任务缺失只响亮告警（管理员重跑
    register 可补）
  - 实机取证（2026-09-17）：check-only 健康路径 exit=0 + 决策日志落行；
    杀掉手动进程（pid 32240 含子树）→ watchdog exit=1，02:33:55
    `restarting pid=36944` → 02:33:56 `restart OK`（1 秒恢复）；
    `schtasks /Run` 强制执行计划任务 → 02:34:13 决策日志落行（调度链
    全通）；服务自此以分离进程常驻，会话结束不再死
  - 实机抓虫两枚（当轮修复）：中文 Windows schtasks 输出为 GBK 字节，
    `text=True` 的 utf-8 读线程直接崩（stdout/stderr 变 None）→ 字节层
    utf-8→gbk 回退链解码（doctor v3.21 GBK 加固同款教训）；unregister
    幂等匹配漏中文措辞「系统**找不到**指定的文件」→ 中英三措辞全认
  - 配套：google-bridge README 新增「Windows 常驻：看门狗」节；
    mcp `googlebridge_unreachable` 错误提示补看门狗部署指引
- **C1 zhihu_content 通用阅读线拆分（1109 行双关注点解耦，真重构非搬家）**：
  - 评估裁决：到拆分点——通用阅读线（SSRF 护栏/错误页判据/HTTP+浏览器
    双线，六轮叠加 v3.4→v3.11）与知乎 API 线（cookie/签名/自愈/fetch_*）
    依赖集零交集（bs4/camoufox vs zhihu_sign/zhihu_bootstrap），且 MCP
    read_page 工具名与新模块天然对齐；全仓最大文件 2 倍于次大者
  - `read_page.py`（新，273 行）：公开入口 `read_generic`/`check_http_url`/
    `ReadError`；**AST 级零知乎依赖**钉进测试（边界铁律防回焊）
  - `zhihu_content.py`（1109→893 行）：保留知乎 API 线 + read() 分流器
    （知乎 API 分流 + bilibili 特化 + 外域委托 read_generic）+ read_via_browser
    SEO 线（知乎特有）；按名重导出 ReadError/_check_http_url/CONTENT_LIMIT
    等（`zc.<name>` 引用路径不变，兼容层同体性钉进测试）；死 import
    （ipaddress/socket）随迁出清除
  - 测试适配最小化：requests/socket 模块单例的 patch 天然免疫拆分；
    仅 3 处 `zc._generic_read` patch 点改 `zc.read_generic` + 5 处 SSRF
    钉改真源 `rp.socket`（v3.12/v3.18 过时钉适配先例，历史结论钉原样保留）
- 测试 425→468 通过（test_v3280 共 43 钉：juejin 引擎 12 + 门面路由 3 +
  watchdog 10 + watchdog_task 10 + C1 拆分 5 + 版本锁 3；test_v3270
  精确锁降常青移交 test_v3280——v3.24→v3.25→v3.26→v3.27 先例延续），
  连续两轮全绿 + clean-worktree 收工检查

## [3.27.0] - 2026-09-17

### 🎯 症状漂移观察轮：双引擎回摆逐字症状（v3.26 timeout 漂移未持续）+ CLI --probe 退出码契约钉

- **第九轮采样（预算 3/3，同题 q="python"，全程走 CLI --probe 入口）=
  症状漂移观察轮 + 双引擎 gate-1 重积累第 1 发（双 streak 自 0 起算）**：
  brave gate-1 未过（01:52:34，rows=0，unresponsive "brave: too many
  requests"——v3.17/18/19 同款逐字限流症状）→ **v3.26 timeout 漂移单轮
  即止未持续**，streak 维持 0（重积累第 1 发 fail）；判据 v2 裁决
  a) ✗（gate-1 fail 一票否决）c) ✗（streak 起点 v3.26 01:23 距本次
  ~0.5h << 24h，派工预注册「24h 跨度锚 09-18 前不烧关」兑现）→
  **gate-2 不烧**。ddg gate-1 未过（01:52:52，rows=0，
  "duckduckgo: CAPTCHA" **逐字复发**——v3.15 起九轮中第八轮逐字）
  streak 维持 0（归零后连续第 5 fail），逐字复发判据（v3.22 审计更正
  口径）恢复适配。**漂移轮结论**：v3.26 双引擎 timeout 与 v3.25 收官
  聚合 0 行同构——实例级/瞬时窗口假设再获证据；逐字症状（brave too
  many requests / ddg CAPTCHA）仍是主导态，timeout 降级为窗口内偶发，
  「逐字复发」口径恢复为可靠判读依据。startpage 止损期跳过；聚合确认
  （01:53:10，~3s）20 行 = google cse 19 + wikipedia 1，实例级健康
  无降级窗（对比 v3.25 收官 0 行 / v3.26 20 行）；三引擎维持全禁
  （逐字复发即上游封锁持续的直接证据），实例级波动不触发单引擎状态调整
- **CLI --probe 退出码契约钉（自评立项，先取证后落地）**：gate-1 机制化
  的班次实际入口（本轮探活即用其退出码 0×2 实测与「有效观测」语义
  一致），其「0=有效观测（ok 真假均算，判读看 JSON）/1=传输解析故障
  无有效观测」契约此前只活在 help 文本、零测试钉（test_v3230 钉
  probe() 函数体、test_v3130 钉搜狗 --probe 工具字段，searxng CLI
  包装层无人钉）——test_v3270 runpy+mock urlopen 离线钉三态（过 /
  上游复发=有效观测 / 传输故障），过路径顺带钉 probe 严格收窄请求形状
- 测试 418→425 通过（test_v3270：CLI --probe 退出码三态钉 ×3 +
  settings.yml v3.27 段与三引擎维持全禁钉 ×2 + 版本锁 3.27.0 双
  __version__ + CHANGELOG/README ×2；test_v3260 精确版本锁降常青移交
  test_v3270——v3.24→v3.25→v3.26 先例延续），连续两轮全绿 +
  clean-worktree 收工检查

## [3.26.0] - 2026-09-17

### 🎯 判据 v2 第二次实战（brave gate-1 fail + 跨度双拦，gate-2 不烧）+ search(engines=) 语义统一（严格收窄落地）

- **第八轮采样（预算 3/5，同题 q="python"；余 2 发未烧）= 判据 v2
  第二次实战**：brave gate-1 未过（01:23:10，rows=0，unresponsive
  "brave: timeout"，有效观测非传输故障）→ **streak 4→0 诚实归零**
  （v3.20/23/24/25 四连断于首发起）；裁决 a) ✗（gate-1 fail 一票
  否决）c) ✗（streak 起点 v3.20 09-16 21:53 收工前，距本次探活
  ~3.5h << 24h，上轮预注册「09-18 前不足 24h」继续兑现）→
  **gate-2 不烧**。意外强化：4 连 streak 在跨度未满时被一发打破——
  「3h 窗口运气」风险实测成立，c) 条设计正确性拿到反向证据（若上轮
  仅按 a)+b) 烧关，本轮 brave 恰处 timeout 态；示意性而非判词，
  gate-2 路径与单发探活不同构）。ddg gate-1 未过（01:23:37，rows=0，
  "duckduckgo: timeout"）streak 维持 0 归零后第 4 fail——**症状变异
  首录**（v3.15~v3.25 七轮逐字 CAPTCHA → 本轮 timeout；逐字复发
  口径首次失配，单观测不定性，处置不变维持禁用）；startpage 止损期
  跳过；三引擎维持全禁
- **实例级降级窗口闭环**：默认聚合（01:24:19，~2s）20 行全部
  google cse——v3.25 收官 00:55:41 的 0 行降级窗口已恢复（行数地板
  活体案例闭环：降级窗 0 行 → 本轮 20 行，SEARXNG_MIN_ROWS=3 若在
  降级窗口跑 doctor 会亮 ⚠️）；实例级波动不调整三引擎禁用状态
- **search(engines=) 语义统一（v3.25 立项项，本轮取证后落地）**：
  engines= 显式点名时弃 categories → 严格收窄，与 probe() 同语义。
  取证链：v3.25 受控对照实证旧「默认集 ∪ 点名」混入 google cse
  （实害：gate-1.5 不可靠）+ 本轮取证 MCP searxng_search 不暴露
  engines、search(engines=) 生产调用方为零（仅测试钉）→ 零回归面。
  默认路径（engines=None）categories=general 生产行为不变
- 测试 408→418 通过（test_v3260：统一语义行为钉 ×4 + 代码机制落点钉
  + settings v3.26 段与三引擎维持全禁钉 ×2 + 版本锁 3.26.0 ×2 共
  9 钉；test_v3250 union 语义钉随契约翻转为严格收窄 + 新增默认路径
  不变钉 + 精确版本锁降常青移交 test_v3260——v3.24→v3.25 先例延续），
  连续两轮全绿 + clean-worktree 收工检查

[3.26.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.26.0

## [3.25.0] - 2026-09-17

### 🎯 判据 v2 首次实战（c) 跨度未达标，gate-2 不烧）+ gate-1.5 实网首验未过 + engines= 语义两形态钉

- **第七轮采样（预算 5/5，同题 q="python"）= 判据 v2 首次实战**：brave
  gate-1 过（00:51:24，20 行 unresponsive 空）streak 3→4（v3.20/23/24/25
  四连；派工书「当前 streak=2、过则 3」系 v3.23 时刻陈旧计数，以
  settings.yml v3.24 段实录为准）；复合三条裁决 a) ✅ streak=4≥3、
  b) ✅ v3.24 背靠背连发 K=2 在案、**c) ✗ 跨度不足——streak 起点
  v3.20（09-16 21:53 收工前）距本次探活 ≤2.9h，v3.23 锚 ≈1.1h，均
  << 24h**（上轮预注册「09-18 之前不足 24h」兑现）→ **gate-2 不烧**：
  c) 条件按设计拦下一次 3h 窗口内的提前烧关（v3.20 正是 ~3h 窗口单发
  过、烧关即复发——判据 v2 的 c) 从那次失败长出，复合判据首次实战
  拦截成功）。ddg gate-1 未过（00:51:26，CAPTCHA rows=0 逐字复发）
  streak 维持 0 归零后第 3 fail；startpage 止损期跳过；三引擎维持全禁
- **gate-1.5 实网首验：未通过，不进库**（v3.24「实网验证前不进库」被
  实网证据加强）：① search(engines="brave,wikipedia")（00:51:54）
  25 行 = brave 18 + wikipedia 1 + **google cse 6 混入**——根因受控
  对照钉死（单变量 = categories 有无）：search() 恒传 categories=
  general → engines= 是「默认集 ∪ 点名」；probe() 无 categories →
  engines= 严格收窄（00:55:03 同 engines= 参数仅 brave+wikipedia 被
  调度）；/config 旁证 "google cse" 系实例独立启用引擎（goc）。
  v3.23「engines= 透传」两条路径语义不同此前无文档——本轮文档钉 +
  请求形状回归钉落库；行为级变更（engines= 时弃 categories）涉 MCP
  工具契约，立项留下轮。② probe 同形态多引擎（00:55:03）0 行 +
  brave/wikipedia 双 timeout——距 brave 上一发过仅 3 分钟，单观测噪声
  压倒信号，gate-1.5 作判据不可靠
- **限流第三数据点 + 实例级降级窗口实录**：brave 4.5 分钟窗口第 3 发
  timeout（00:51:24 过 → 00:51:54 过 → 00:55:03 timeout；v3.24 二发
  秒级连发全过）——限流器容忍边界或在 2~3 发/短窗附近（单点不定标）；
  默认聚合（00:55:41）0 行无错误，对比 v3.24 同口径 20 行全 google cse
  （与双 timeout 同窗口）——SEARXNG_MIN_ROWS=3 行数地板的活体案例，
  预算耗尽未复测，下班次 doctor 兜底 ⚠️
- 测试 401→408 通过（test_v3250：engines= 语义两形态请求形状钉 ×2 +
  契约注释源钉 + settings v3.25 段与三引擎维持全禁钉 ×2 + 版本锁
  3.25.0 ×2 共 7 钉；test_v3240 精确版本锁/徽章锁降常青移交
  test_v3250——v3.17→v3.19、v3.21→v3.22、v3.22→v3.23、v3.23→v3.24
  先例），连续两轮全绿 + clean-worktree 收工检查

[3.25.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.25.0

## [3.24.0] - 2026-09-17

### 🎯 doctor 实例级健康下限（聚合行数地板）+ probe() 实网首用 + N 定标（brave 恢复判据 v2）

- **doctor 实例级健康下限（上轮评估遗留项落地）**：`check_searxng` 新增
  `SEARXNG_MIN_ROWS = 3` 行数地板——v3.23 第五轮采样同场实录的盲区：
  聚合仅 wikipedia 1 行（默认引擎集整体哑火）时 doctor 仍报 ✅「引擎全
  健康」（原检查只看连通 + unresponsive 列表，逐引擎各有说辞、实例级
  降级无人报警）。低于地板走 optional 检查异常路径 = ⚠️ 且不翻退出码
  （实例活着只是聚合枯竭，是降级不是核心故障——main 只看 core_fail）；
  告警文本明确「非单引擎问题」与单引擎止损判据（v3.15 unresponsive
  列表 + 逐引擎禁用）互不替代。test_v3140 两处夹具（1 行/0 行）升到
  地板之上——旧夹具在新语义下恰是降级态，钉的本意（unresponsive 必须
  出现在输出里/全健康表述）原样保留
- **probe() 实网首用（v3.23 机制进库后的首次实网调用，六轮 ad-hoc 裸
  探活技术债清偿）**：预算 4/4 全走 `searxng_client.probe()`/CLI
  `--probe`，四发同题 q="python" 同法逐字可比——brave 两发（gate-1
  streak 2→3；背靠背连发第二发占 startpage 跳过腾出的名额，秒级间隔
  仍 20 行全过=限流器至少容忍 2 快速请求，首个非「1 发/轮」粒度的限流
  数据点）、ddg 一发（CAPTCHA rows=0 逐字复发，streak 维持 0）、
  startpage 跳过（v3.23 止损禁用无待验 streak）+ 默认聚合一发（20 行
  全部 google cse，实例级健康，v3.23 降级态未复现）
- **N 定标（「连续 N 轮单发过才烧第二关」证据链定稿，判据 v2）**：
  brave gate-1 全史（v3.16 过→烧→聚合复发；v3.17/18/19 三连 fail；
  v3.20 过→烧→聚合 timeout；v3.23/24 过）定标 **N=3 + 复合三条**：
  a) 连续 3 轮单发过（streak=1 烧 gate-2 实证 2/2 全失败，N=1 被否决；
  streak≥2 无 gate-2 数据点，N=3 是首个未被否决的最小值）；b) streak
  内至少一轮背靠背连发 K=2 全过（gate-2 失败症状是限流，单发 1 发/轮
  采不到限流窗口行为，连发是对失败模式的直接采样）；c) streak 跨度
  ≥24h（六个 brave 数据点全落 ~3h 窗口内——一夜多班次使「轮」时间
  稀释，而 v3.15~v3.19 封锁持续一天以上，24h 下限让采样超出封锁时间
  尺度）。brave 现状 a/b ✅ c ✗——资格未齐下轮不烧；「聚合小样本
  试探」（engines= 显式多引擎）评估为可选 gate-1.5，缺 restart 初始化
  路径不替代 gate-2，实网验证前不进库。判据全文落 settings.yml 观察注释
- 测试 393→401 通过（test_v3240：行数地板三态钉 + 地板常量/optional
  注册源钉 + settings v3.24 采样段与 N 定标钉 + 三引擎维持全禁钉 +
  版本锁 3.24.0 共 8 钉；v3230 精确版本锁降常青下限、精确锁移交
  test_v3240——v3.17→v3.19、v3.21→v3.22、v3.22→v3.23 先例），连续
  两轮全绿 + clean-worktree 收工检查

[3.24.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.24.0

## [3.23.0] - 2026-09-17

### 🎯 clean-worktree 收工检查固化 + SearXNG 第五轮采样（startpage 止损禁用）+ 探活机制进库

- **clean-worktree 复跑固化为收工检查项（上轮遗留项落地）**：v3.22 实证的
  「本机绿 ≠ fresh 绿」盲区（state/shift_log.md 在场掩盖 fresh checkout 必炸
  的钉一整轮）固化为 `scripts/clean_worktree_test.sh`——在 HEAD 的全新
  `git worktree add --detach` checkout 里跑全量测试，完全不触碰当前工作区
  （零 stash-pop 冲突风险）。**机制裁决有据**：`git stash`（含 -u）不触碰
  gitignore 文件——state/、__pycache__ 原地保留，恰恰漏掉本检查要暴露的
  那类产物，-a 还会把 zhihu_cookies.json 卷进 stash；故检查走 worktree 而非
  stash（派工原文的 stash 方案被证据否决，目的不变、手段换对）。检查项写进
  CONTRIBUTING「版本发布」第 3 条（先提交再跑——push 的是提交）。检查器自身
  按十杀纪律盲测：微型夹具仓「本机 1 passed（假象绿）/ 脚本跑 1 failed
  exit=1（盲区暴露）」复现成功，trap 清理无残留 worktree
- **SearXNG 第五轮单发采样（预算 4/4，四发同题 q="python" 同法逐字可比）**：
  本轮按 v3.20 判据升级定位为「连续 gate-1 通过数据积累轮」，不烧第二关
  预算——**brave 第一关过**（20 行 unresponsive 空，v3.20 后连续第 2 轮，
  streak=2；「连续 N 轮」的 N 未定标，继续积累）；**duckduckgo 第一关未过**
  （CAPTCHA rows=0，逐字 v3.15~v3.18/v3.22 症状，诚实 streak 归零，维持
  禁用）；**startpage 第一关未过**（CAPTCHA rows=0）且第 4 发聚合确认生产
  路径同病（unresponsive 记 **"Suspended: CAPTCHA"**——SearXNG 调度器内部
  已自动暂停该引擎；同场聚合仅 wikipedia 1 行，google cse/wikidata timeout
  与本判据无关）——两轮三观测（v3.22 聚合 parsing error → 本轮探活 CAPTCHA
  + 聚合 Suspended）→ 按 v3.15 止损判据**禁用 startpage**（不健康引擎不拖慢
  每次搜索；恢复走单引擎两关，其 v3.19 正是经此路径回滚、机制已验证）；
  三引擎当前全禁用。全程零 settings 重启外的真实引擎干预，restart 后 /config
  核对 startpage disabled 生效（非搜索调用不计预算）
- **探活机制进库（自评立项，证据充分）**：v3.16~v3.23 六轮 gate-1 探活全是
  ad-hoc 裸 HTTP——判据写在 settings.yml、调用在各班次习惯里，与 v3.19
  acquire() 根因同构（机制在库里、路径在习惯里 = 等于没修）。固化：
  `searxng_client.search()` 新增 `engines=` 参数（**追加在 on_error 之后**，
  既有调用方位置传参不断链；None/空串不加参数 URL 干净）+ 新增
  `probe(q, engine)` 第一关函数（返回 rows/unresponsive/ok，ok = rows>0 且
  unresponsive 空=判据原文；传输故障 error 字段如实区分「无有效观测」与
  「上游复发」；纯观测不写状态文件，streak 记账归 settings.yml 观察注释）；
  CLI `--probe ENGINE`（退出码 0=有效观测、1=传输故障，doctor sogou 探活
  同语义）。下轮起第一关只准走 probe()；probe() 实网首用留待下轮（本轮
  预算已按历史同法消耗完，方法可比性优先）
- **顺手修正（本批审计发现）**：test_v3150/test_v3160 三引擎全禁元组恢复
  （v3.19 适配时移出 startpage，v3.23 起三引擎全禁状态与 v3.15 元组重新
  一致）；test_v3220 精确版本锁降常青下限（v3.17→v3.19、v3.21→v3.22 先例），
  精确锁移交 test_v3230
- **队列卫生**：接手时 worker_queue.json 已为空（`{"instructions": ""}`，
  mtime 2026-09-16 23:31:28 +0800，无 claim sidecar）——派工内容以班次命令
  原文为准，收工时保持清空；stop_wake 部署副本与仓库真源 cmp 字节一致复核
  通过（v3.22 部署未漂移）
- 测试 374→393 通过（test_v3230：clean-worktree 脚本源钉 + CONTRIBUTING
  检查项钉 + 盲区复现行为钉（本机绿/脚本红/无残留 worktree；首版红钉曾被 WSL bash 假执行虚假满足、被绿路径钉揪出——检查器自身失效教训入档）+ engines 参数
  URL 钉 + probe 三态钉（过/复发/传输故障）+ settings v3.23 采样段与三引擎
  全禁钉 + 版本锁 3.23.0 等 19 钉），连续两轮全绿 + clean-worktree 脚本实跑
  收工检查通过

[3.23.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.23.0

## [3.22.0] - 2026-09-16

### 🎯 stop_wake append-only 决策日志 + 收工必写 shift_log 纪律固化

- **stop_wake 决策日志（上轮审计遗留项落地）**：v3.21 如实声明的观察盲区（钩子无决策日志，审计被迫全走间接证据）——`main()` 每次触发追加一行 JSONL 到 `~/.zcode/stop_wake_decisions.jsonl`（在 ~/.zcode、仓库外，gitignore 不适用）：`ts`（本地 ISO 带时区）/`decision`（block|pass）/`reason`（block=注入收工的完整文本；pass=归因标签 no_queue/empty_queue/module_unreachable/valid_claim）。决策逻辑重构为 `_decide()`（返回 (block, reason)），`should_block()` 变为语义不变的兼容层（v3.19 全部行为钉原样通过）；写日志任何异常一律吞掉——从属职责，磁盘满/权限故障绝不影响决策与退出码；真源-部署纪律不变（先改仓库真源 → 部署副本旧版备份 .bak-v3.21.0 → 覆写 → cmp 字节一致验证）
- **收工必写 shift_log 纪律固化（上轮审计遗留项）**：v3.19/v3.20 批次缺 shift_log 条目的连续性缺口收口——检查点写进 CONTRIBUTING.md「版本发布」一节（漏写须标注补记，无声补=伪造实时流水）；shift_log.md 补记 v3.19/v3.20 两行历史条目（标注补记、时间戳保持 doctor `_shift_log_stats` 可解析的 `[YYYY-MM-DD HH:MM]` 格式）
- **顺手修正（本批审计发现）**：CHANGELOG 3.20.0 标题日期 2026-09-17→2026-09-16（提交 837501a 实际 2026-09-16 21:53，日期笔误）；3.19.0 标题重复日期「- 2026-09-16 - 2026-09-16」去重；CONTRIBUTING「版本发布」编号断链（1,2,…,4）修复；test_v3180 真仓 shift_log 钉补 skipUnless——clean git worktree 复跑实证 fresh checkout 上必炸（1 failed，"352 全绿"是机器本地产物 state/shift_log.md 在场的假象，v3.18 批次遗留；state/ 为 gitignore 运行态，缺文件=可选观测未启用同 doctor 语义，修复后 clean checkout 25 passed 2 skipped）
- **并行互踩记录**：本批次进行中并行班次落库 c938d69（v3.20 ddg 判定假阳性的审计修正：settings 重复条目致 ddg 实际未参排，诚实重跑第二关 CAPTCHA 复发维持禁用；改 tests/test_v3190.py + settings.yml，与本批零文件交集无冲突，其提交信息明记"v3.22.0 belongs to the parallel in-flight stop_wake-log batch"）；README 状态行按修正结论同步标注（v3.20 段"两关双过回滚生效"加假阳性修正标记）
- 测试 352→374 通过（基线 88af427 本机 352 + 并行 c938d69 +1 = 353，本批 +21 钉；两轮全绿 18.34s/17.42s；test_v3220：决策日志 5 钉 + 归因标签 6 钉 + should_block 兼容层 2 钉 + main 端到端 2 钉 + shift_log 纪律 3 钉 + 版本锁/CHANGELOG/真源 pin 3 钉），test_v3210 精确锁降常青下限（v3.17/v3.18 先例），版本锁 3.22.0

[3.22.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.22.0

## [3.21.0] - 2026-09-16

### 🎯 cookie 寿命标定首批数据分析 + doctor GBK 控制台加固 + stop_wake 部署一致性核验

- **36h 续期阈值维持（数据驱动裁决）**：`state/cookie_lifetime_log.jsonl` 全量 7 读数（探活 v3.8.2 上线以来全部样本）——唯一死亡实测 47.38h 即 403（该 cookie 09-13 21:49 UTC 签发，存活期间知乎调用零自愈记录，≈47.4h 是真实寿命而非"早死未观察"）；36h < 47.38h（余量 ≥11.4h），n=1 不够调参，维持不变；续期机制实战首例 1/1 成功（47.92h expired → renew ok: d_c0(Y) __zse_ck(len=261)），valid 读数零误触发（renew=false ×2），触发频率预期 ≈ 每 1-2 天一次随实际知乎用量浮动
- **续期入口现状如实入档**：未部署 cron（schtasks 仅 `ai-search-sogou-probe` 一项）——docstring/帮助文本原"cron 例：每日 9 点"是建议例而非部署事实，措辞已修正；MCP doctor cookie 模式恒为纯标定不续期（`cmd_cookie_probe()` 无参调用，保真实寿命数据流，测试钉死）
- **doctor GBK 控制台加固**：sogou cron 部署调试期实录 `UnicodeEncodeError: 'gbk' codec can't encode character '\u2705'`（~/.zcode/sogou_probe_cron.log）——probe_once 先落账故读数未丢，但报告与退出码被杀；新增 `_make_stdout_robust()`（errors="replace"，编码本身不动；StringIO/MCP 路径无 reconfigure 原样放行）挂 main() 入口
- **stop_wake 部署副本一致性核验**：cmp 部署副本 vs 仓库真源字节级一致（21:40 重部署未漂移）；接线确认（~/.zcode/cli/config.json hooks.Stop → 部署副本，10s 超时）；实战面：v3.20 已录今晨 8:37→8:52 钩子唤醒首验 + 本批次 21:45 认领 sidecar 实迹（worker_queue.json.claim.json）；观察盲区如实声明——钩子无决策日志（设计即无），"加 append-only 决策日志"留待下轮评估
- **队列卫生**：本批次接手时 worker_queue.json 含 v3.20 残留指令（其①②④已由 837501a 完成、③即本批次 stop_wake 核验）——收工经 worker_queue.clear() 清空；时间线存证：队列 mtime 21:44:09 早于 v3.20.0 提交 21:53:08
- 测试 346→352（test_v3210：GBK 加固 3 钉 + MCP 纯标定钉 + 版本锁 3.21.0 + CHANGELOG 钉），版本锁 3.21.0

[3.21.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.21.0

## [3.20.0] - 2026-09-16

### 🎯 SearXNG 单引擎两关制第四轮：ddg 回滚生效、brave 恢复判据升级、stop_wake 实战首验

- **duckduckgo 两关双过，回滚生效**：第二关回滚 + restart 后聚合 11 条、unresponsive 无 ddg——与 brave 同场对照实证「单发可信度因引擎而异」
- **brave 四轮数据定论其单发不可信**：第四轮单发 19 行过、聚合即 timeout——恢复判据升级观察（连续 N 轮单发过才允许第二关），维持禁用
- **mojeek 首探 access denied**：替代引擎结论作废（本环境/IP 不可用）
- **stop_wake 实战首验**：8:37 写入派工队列 → 8:52 被钩子唤醒的班次完成交接任务并清空队列（GitHub 403 取证/健康核对/收工判断全按协议）——机制从测试走进实战

[3.20.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.20.0

## [3.19.0] - 2026-09-16

### 🎯 claim 固化进领活入口（根因修复）+ SearXNG 回滚判据细化到单引擎

职业团队循环批次。上轮审计根因发现：v3.17 的 claim 机制三版被实证零
使用——并行 worker 领活时不查 sidecar 直接干活，机制在库里、调用路径
在各 worker 的习惯里，等于没修。真实网络消耗：SearXNG 本地 4 发
（startpage 单发探活 1 + 仅回滚 startpage 后聚合验证 1 + brave/ddg
单发取证 2，预算 4/4），知乎/百度/文心 0 发。

### Added
- `tools/chat-scraper/worker_queue.py`：**acquire() 领活唯一入口**——
  认领+读队列一步完成（根因修复选项 a：调用路径固化，调用方无法绕过）。
  `skipped` 时**不返回 instructions**——活的内容不经手，从机制上杜绝
  "看到活就干"的互踩形态；`claimed` 才拿得到活（含空串=队列无活，应
  complete 收工；损坏/读失败如实视为无活）；超时/损坏接管归一为
  `claimed` + `reclaimed_from`（原持有者可见）；`no_queue` = 队列文件
  不存在，不认领、不留 sidecar。全部基于 v3.17 原语（O_EXCL 创建 +
  读回校验），无新增并发面
- `tools/chat-scraper/hooks/stop_wake.py`：**Stop 钩子仓库真源**
  （根因修复选项 b：强制条款写进唤醒入口）。`should_block()` 决策：
  有活 + 无认领/超时/损坏标记 → block，理由文本自带 instructions 与
  领活固定入口强制条款（worker 被唤醒第一眼即见"先 acquire()，skipped=
  活归别人直接收工"）；有活 + 有效认领（未超时）→ 放行——互踩预防在
  唤醒层收口，不唤醒第二个 worker，持有者死亡由认领超时自然解封；
  wq 模块不可达 → 放行 + stderr 警告（可见降级，hook 不阻断收工）。
  worker_queue 模块从仓库探测 import（AI_SEARCH_STACK_CHAT_SCRAPER
  环境变量优先，常见位置 glob 兜底），单一真源+部署副本关系写入
  docstring。已部署 `~/.zcode/hooks/stop_wake.py`（旧版备份
  stop_wake.py.bak-v3.18.0）
- `tests/test_v3190.py`：24 钉——acquire 入口固定路径 10（claimed/
  空活/no_queue 无残留/**skipped 不泄漏 instructions**/生命周期/接管
  归一/入口层互斥/损坏队列容错/非 str 字段防御/队列本体不碰）+
  should_block 决策 9（无队列/空活/不可达放行/无人认领 block 带条款/
  有效他人认领放行/超时解封再 block/损坏标记 block/损坏队列放行/
  真源在库 pin）+ settings.yml 单引擎判据 pin 2 + 版本锁 3.19.0 3，
  套件 322 → 346

### Changed
- `tools/searxng/docker/searxng/settings.yml`：**回滚判据细化到单引擎
  粒度**（每引擎独立两关：第一关该引擎单发探活 rows>0 且 unresponsive
  空；第二关仅回滚启用该引擎 → restart → 聚合搜索该引擎 unresponsive
  清零且 rows 正常；双过单独放回，复发仅该引擎再禁用，不牵连其他引擎
  观察状态）。三引擎整组判据把可救的和无救的绑死——v3.18 startpage
  单发已恢复、brave/ddg 仍复发，整组判据下 startpage 只能陪禁。整组
  判据保留为退化形态（全部引擎同轮双过 = 等价整组回滚）
- `tests/test_v3180.py`：3.18.0 精确版本锁降为常青下限（v3.13→v3.14
  先例），精确锁移交 test_v3190
- `tests/test_v3150.py` + `tests/test_v3160.py`：三引擎全禁旧 pin 适配
  startpage 单独回滚（行为演进先例，v3.18 对 test_v3160 obsolete pins
  的处理同款）——brave/duckduckgo 禁用断言保留，历史结论 pin
  （v3.16"单发探活通过 ≠ 可回滚"等）不动
- 版本 bump：mcp_server + chat-scraper `__init__` → 3.19.0，README
  badge/版本行同步

### 实测记录（SearXNG 预算 4/4 发，单引擎判据首例实证）
- 第一发：startpage 单发探活（第一关）——**过**（10 行，unresponsive
  空，与 v3.18 一致）
- 第二发：仅回滚 startpage + docker compose restart 聚合搜索（第二关，
  单引擎粒度首例）——**过**（10 行全部 startpage、unresponsive 无
  startpage；google cse 自身 timeout 与本判据无关），**startpage 单独
  放回生效**；brave/duckduckgo 保持禁用不动
- 第三发：brave 单发取证——复发（too many requests，rows=0，与
  v3.17/v3.18 症状逐字一致，上游封锁第三轮持续），第一关即未过，
  第二关不做；维持禁用
- 第四发：duckduckgo 单发取证——**第一关恢复**（10 行 unresponsive
  空，CAPTCHA 未复现，较 v3.17/v3.18 转好），但第二关因预算用尽未
  执行；v3.16 已实证"单发过 ≠ 可回滚"，**维持禁用**，下轮复跑优先补
  ddg 第二关
- 替代引擎取证（零额外搜索预算，读容器内置引擎清单 + 上游文档）：
  结论与建议见下方「评估未立项」

### 评估未立项（先取证再立项，证据不足不动手）
- 替代引擎取证（零额外搜索预算：`docker exec` 读容器内置引擎模块源码
  声明头——本容器实际跑的代码，比上游文档更硬）：容器内存在
  mojeek.py/marginalia.py/wikipedia.py/qwant.py/yep.py/bing.py/yahoo.py，
  不存在 presearch/lasso（排除）。声明头取证：**mojeek
  `require_api_key: False` + 支持翻页**（独立索引通用 web，brave 封锁
  期的首选替代）；marginalia `require_api_key: True`（api_key=None 直接
  报错，需申请 key，暂排除）；wikipedia `require_api_key: False`（稳定
  但非通用 web）。**建议（不实施）**：brave 下轮复跑仍复发时，mojeek
  走单引擎两关判据启用（settings.yml engines 加条目 + 单发 + restart
  聚合验证）；当前 startpage 已单独回滚、ddg 第一关已恢复待下轮第二关，
  缺口在收敛，替代引擎引入待下轮复跑结果再定
- mcp 工具层暴露 queue_status/acquire：消费方是 ZCode worker 会话
  （hooks + 领活习惯），MCP 客户端无派工场景证据（v3.17 先例延续）

## [3.18.0] - 2026-09-16

### 🎯 doctor 值班巡检趋势统计口径重做（每日分布/事件计数/最近一条）+ GitHub 检查可选 GITHUB_TOKEN

同日双 worker 并行批次的收尾环（v3.16 值班趋势初版 + v3.17 worker_queue
之后的口径返工与声明-实现缺口补齐；实施期间与 v3.17 批次实时互踩两次，
靠 stash 让树 + 等待对方提交落库后 rebase 完成，worker_queue 的机制动
机因此三次实证）。零业务引擎改动（chat-scraper 本包零代码改动，版本
对齐 v3.8.2 先例）；真实网络消耗：0 发（全本地：doctor 口径返工纯代码
+离线取证，SearXNG 禁用引擎的两次实搜观察由 v3.16/v3.17 批次完成，
本批零新增实搜，知乎/百度/文心/GitHub 0 发）。

### Changed
- `tools/doctor.py`：**值班巡检趋势统计口径重做**（check_shift_log 于
  v3.16 引入，本版按值班需求规格返工）——汇总从"条数/覆盖天数/疑似
  异常项数"改为五项：近 7 天记录条数/覆盖天数/**每天条数分布**/
  **关键事件计数**（含「restart」「处置」「❌」「恶化」字样的行数，
  SHIFT_LOG_EVENT_KEYWORDS，纯字面大小写敏感子串计数，一行可命中多词
  各自独立计数，不做 NLP）/**最近一条时间戳+首 80 字摘要**。语义沿
  sogou_recovery_log 先例修正：**缺文件/空文件/全坏行 = 可选观测项未
  启用，不报警不判故障**（v3.16 初版缺文件即 ⚠️，与"没人写值班流水
  不算故障"的口径相悖）；有记录但近 7 天零记录仍 ⚠️ 连续性中断
  （optional 不判核心故障，消息带最近一条时间戳让"断了多久"可见）；
  [HH:MM] 省日期行继承规则与坏行防御不变（头部无日期可继承跳过的口径
  补测试钉死）；窗口 = 含今天的最近 7 个自然日不变
- `tools/mcp_server.py`：doctor 工具描述同步新统计口径（每日分布/事件
  计数/最近一条摘要）；版本 3.17.0 → 3.18.0
- 版本号 3.17.0 → 3.18.0（`tools/chat-scraper/__init__.py` 同步）；
  README 徽章/头部/版本轮链同步

### Added
- `tools/doctor.py`：**GitHub 检查可选 GITHUB_TOKEN 认证**（"发现更值
  得做的先取证再立项"：值班日志 2026-09-16 08:52/09:03 两班 GitHub 403
  限流窗口复发、同刻独立 curl 直连全 200 → 判定匿名 60 req/h 是本 IP
  全部 GitHub 调用共享的配额窗口；取证发现 MCP 侧 github_client.py
  早已读 GITHUB_TOKEN 而 doctor 检查不读——声明-实现缺口坐实）。实现：
  GITHUB_TOKEN 设置时 check_github 带 `Authorization: Bearer <token>`
  头（值去空白，UA 头保留——v3.11 UA 修复不回退），5000/h 不再吃匿名
  配额；未设置/空串维持匿名可达性观测（可选配置缺失不是故障），detail
  如实区分「匿名」/「Bearer 认证」

### Tests
- `tests/test_v3180.py` 新增 27 项钉子（全离线零网络）：shift_log 统计
  13（两种时间戳格式/短格式继承与头部无日期跳过/坏行混合/空文件/全空白
  /窗口过滤第 8 天前不计且 last 与 last_any 口径分立/每日分布/事件计数
  字面性——大写 Restart 不命中/全零键在/80 字摘要截断/缺文件 None/
  window_days 参数/真实日志可读）+ check_shift_log 6（缺文件不报警/
  空文件不报警/全坏行不报警/7 天零记录 ⚠️ 连续性中断含最近一条/正常
  汇总全字段/真实日志汇总，now 冻结消时炸弹）+ check_github token 4
  （token 设置 Bearer 头且 UA 保留/缺失匿名/值去空白/空串等同缺失）+
  注册顺序钉 1（第 8 项 optional 且排 GitHub 之后=尾部）+ 版本锁 2 +
  mcp 描述词钉 1
- `tests/test_v3160.py` 适配（行为演进，v3.12 护栏测试适配先例）：旧
  统计口径的行为钉子（疑似异常关键词表/缺文件报警/元组返回形状）随
  v3.18 重做移除，由 test_v3180 全套接管；保留仍然为真的 settings.yml
  恢复观察、main() 注册、版本常青下限、mcp 描述钉子
- `tests/test_v3170.py` 版本精确锁转常青下限（≥3.17.0，v3.13→v3.14
  先例，精确锁移交 test_v3180）
- 全量 305 → 322（test_v3160 移除 10 个被 v3.18 重做作废的旧口径钉子，
  test_v3180 新增 27 个新口径钉子）

### 评估未立项（先取证再立项，证据不足不动手）
- doctor GitHub token 提示增强（如 403 时提示配 token）：SearXNG/
  cookie 检查同样会因环境报红，统一改提示是独立需求，本批只补声明-
  实现缺口本身
- shift_log 关键词表可配置化：当前 4 词从真实日志归纳且稳定，YAGNI

## [3.17.0] - 2026-09-16

### 🎯 worker_queue 派工队列认领机制（多 worker 互踩的修复）+ SearXNG 恢复复跑（第一关未过，维持禁用）

职业团队循环批次。真实网络消耗：SearXNG 本地 3 发（brave/duckduckgo/
startpage 单发探活各 1，预算 3/5），知乎/百度/文心 0 发。

### Added
- `tools/chat-scraper/worker_queue.py`：**派工队列认领机制**——多 worker
  并行领同一 `~/.zcode/worker_queue.json` 互踩的修复（上轮实证：v3.16
  的 848065c 与并行班次工作树编辑逐字一致即互踩证据；本版实施期间工作
  树第二次实时互踩，对侧 worker 主动 stash 为 `v318-batch-wip` 让出工作
  区——机制动机两次实证）。API：`claim()` 先 `O_EXCL` 原子创建伴生认领
  标记 `<queue>.claim.json`（Windows/POSIX 双平台原子，绝不写队列文件
  本身），他人见有效认领即 `skipped`（可见持有者与 age）；认领超时
  （默认 30 分钟无 complete）或标记损坏（坏 JSON/缺字段/时间戳非数字）
  走接管——tmp + `os.replace` 原子覆盖 + **读回校验**保证并发接管单一
  赢家；`complete()` 只删自己的标记（读回校验，别人的删不掉，超时被
  接管后原持有者 complete 如实 False）；`clear()` 原子清空队列；
  `read_claim()` 诊断视图。纯标准库，全部离线可测
- `tests/test_v3170.py`：认领机制 13 钉（互斥/超时重认领/完成清空/
  损坏自愈/接管后原持有者失去删除权/标记为伴生文件不碰队列本体）+
  版本锁 3.17.0，套件 289→305

### Changed
- `tools/searxng/docker/searxng/settings.yml`：**v3.17 恢复复跑（第一关
  即未过，维持禁用）**——`engines=` 参数单发探活三发全部复发（brave
  too many requests / duckduckgo CAPTCHA / startpage parsing error，
  rows 均 0），与 v3.16 回滚后聚合复发症状逐字一致；较 v3.16 更强：
  这次连单发都不过（上游封锁持续未解除），第二关（回滚启用 + restart
  聚合）按两关判据不再执行——必败动作不做，省下预算。两关判据不变：
  单发 + restart 后聚合 unresponsive 清零，双过才回滚
- `tests/test_v3160.py`：3.16.0 精确版本锁降为常青下限（v3.13→v3.14
  先例），精确锁移交 test_v3170
- 版本 bump：mcp_server + chat-scraper `__init__` → 3.17.0，README
  badge/版本行同步

### 评估未立项（先取证再立项，证据不足不动手）
- 认领机制接入 mcp 工具层（如 queue_status 工具）：当前消费方是
  ZCode worker 会话（读 ~/.zcode/worker_queue.json），MCP 客户端无
  派工场景证据，先落模块与测试，接入待真实需求出现
- 并行 worker 的 doctor shift_log 统计 v2 + GITHUB_TOKEN（stash
  v318-batch-wip）：对侧已声明 v3.18 批次（mine only），不越权代发

## [3.16.0] - 2026-09-16

### 🎯 值班巡检趋势进 doctor + SearXNG 禁用引擎恢复观察（维持禁用）

职业团队循环批次。零业务引擎改动（chat-scraper 本包零代码改动，版本
对齐 v3.8.2 先例）；真实网络消耗：SearXNG 本地 4 发（三引擎 enabled_
engines 单发探活 3 + 回滚后 doctor 聚合实测 1），知乎/百度/文心 0 发。

### Added
- `tools/doctor.py`：**值班巡检趋势检查**（check_shift_log，第 8 项
  巡检，optional）——读 `tools/chat-scraper/state/shift_log.md` 统计
  近 7 天记录条数/覆盖天数/疑似异常项数，值班连续性与历史异常趋势在
  doctor 一眼可见；`[HH:MM]` 省日期行继承上一条带日期条目的日期，坏行/
  非法日期/头部无日期可继承均跳过不计数（append-only 手写流水的防御
  与 `_last_valid_entry` 同哲学）；缺文件/近 7 天零记录 → ⚠️（值班
  连续性中断可观测，但 shift_log 是人工产物不是自动钩子，不判核心
  故障）；疑似异常 = 内容命中关键词表（❌/异常/故障/恶化/CAPTCHA/
  限流/403/不健康/断线/风控/失败，从 2026-09-16 真实 shift_log 归纳）
  ——启发式，好转记录（如"不健康 4→1"）也会命中，输出里明确声明
  "关键词启发式"，只展示不判故障；班次边界无法从流水可靠识别，口径
  为"记录条数 + 覆盖天数"不假装数"班次次数"
- `tools/mcp_server.py`：doctor 工具描述同步 full 模式 8 项清单（含
  值班巡检趋势）；mcp doctor mode=full 复用 main()，新检查自动包含

### Changed
- `tools/searxng/docker/searxng/settings.yml`：**v3.15 禁用引擎恢复
  观察（结论：维持禁用）**——brave/duckduckgo/startpage 经 enabled_
  engines 参数单发探活全部通过（brave 21 / ddg 21 / startpage 20 条，
  unresponsive 均空），但按文件内恢复方法回滚启用 + docker compose
  restart 后首次聚合搜索三引擎即全部复发（too many requests /
  CAPTCHA / parsing error，doctor 21 条结果同场实测）；**实证结论：
  单发探活通过 ≠ 可回滚**，恢复判据必须是 restart 后聚合搜索
  unresponsive 清零；观察记录与两关再评估方法写进 settings.yml 注释，
  禁用条目原样保留

### 评估未立项（先取证再立项，证据不足不动手）
- doctor 展示禁用引擎名单：需二次 /config 请求或解析 yaml，无高频
  痛点证据（引擎名单变化以 git diff settings.yml 即可审计），不动
- shift_log 单项 CLI 模式：检查纯本地零网络，全量巡检已覆盖，不加

## [3.15.0] - 2026-09-16

### 🎯 钩子活性双日志 + mcp doctor 子模式 + SearXNG 实例引擎调优

上轮判词遗留低危项 + 运维优化批次。零业务引擎改动（chat-scraper 本包
零代码改动，版本对齐 v3.8.2 先例）；真实网络消耗：SearXNG 本地 4 发
（调优前后 doctor 各 1 + /config 侦察 2），知乎/百度/文心 0 发。

### Added
- `tools/doctor.py`：**标定钩子活性检查扩展覆盖 sogou_recovery_log**
  （v3.8.2 只看 cookie_lifetime_log）——有读数后最后一条 >48h 同样报警
  （开了就必须活着，静默断线同样让恢复曲线数据流死亡）；文件缺失/无
  有效读数 = 可选观测项未启用，**不报警**（恢复曲线是增值观测，没人跑
  不算钩子断线）；读数解析加坏行防御（`_last_valid_entry`：坏行/非 dict
  行跳过取最后一条有效读数，append-only 日志的个别坏行不误报断线）；
  cookie 侧空日志从裸 JSONDecodeError 改为可读 RuntimeError，v3.10 的
  四分支钉子（缺文件报警/坏时间戳 ValueError）不回退
- `tools/mcp_server.py`：**doctor 工具暴露 mode 子模式参数**
  （`full|cookie|sogou`，默认 full）——cookie/sogou 复用 doctor 的
  `cmd_cookie_probe` / `cmd_sogou_probe`（v3.8.2/v3.14 的 CLI 单项标定
  模式原样上 MCP）；退出码语义随模式如实变化（full：0=核心全绿或仅
  可选未起/1=核心故障；探活模式：0=成功观测（expired/blocked 均为
  有效标定读数）/1=本地故障）；非法 mode 返回统一错误协议 JSON 不炸
  server
- `tools/searxng/docker/searxng/settings.yml`：**上游引擎调优**——长期
  不健康引擎暂时禁用（2026-09-16 doctor 标定：brave too many requests /
  duckduckgo CAPTCHA / startpage parsing error，连轮不健康），不让它们
  每次搜索都拖满 timeout 才判死；`use_default_settings: true` 按名合并
  语义保留（269 引擎不缩水，禁用=默认不调度非移除，回滚零成本）；恢复
  方法写进文件注释（注释掉条目 → docker compose restart → doctor 观察）
  ；**实测**（同机同命令 `python tools/doctor.py`）：调优前「不健康引擎:
  [['brave', 'too many requests'], ['duckduckgo', 'CAPTCHA'],
  ['startpage', 'parsing error']]」→ 调优后「引擎全健康」，结果数 21 条
  前后持平，limiter:false（本机实例免 429）与 json format 基线保留

### Changed
- `tests/test_v3100.py`：TestCheckHookLiveness 补 patch
  SOGOU_RECOVERY_LOG_PATH（v3.15 起 check 会读搜狗标定日志，原 setUp
  只 patch cookie 日志会泄漏到真实 repo state——真实日志过期会让旧
  测试误红，属测试病非产品病）
- `tests/test_v3140.py`：版本精确锁转常青下限（≥3.14.0，3.15 起精确锁
  是 test_v3150 的职责，v3.13→v3.14 先例）

### Tests
- `tests/test_v3150.py` 新增 22 项钉子（全离线）：钩子活性扩展 10 +
  mcp doctor mode 6 + settings.yml 调优 5 + 版本锁 1；全量 249→271

## [3.14.0] - 2026-09-16

### 🎯 恢复曲线标定机制 + wenxin 声明对齐复查

上轮下一环建议落地：搜狗恢复曲线标定机制（连发标定测"多快触发"之后的
另一半——"多久恢复"）。wenxin 对齐复查零真实文心调用（纯代码审查扫法），
真实网络消耗仅搜狗探活 2 发（预算 ≤3）。

### Added
- `tools/chat-scraper/sogou_engine.py`：**恢复曲线单发探活**
  `probe_once()`——真实一发搜索，判定与 `search()` 逐字同判据
  （`_blocked` / 0 行 + `_soft_blocked`），走引擎默认节流 `_wait_turn`
  （探活不是攻击，与 `probe_burst` 的绕节流连发相反）；读数
  {ts, tool, http, rows, blocked, since_last_block_s, note} 一行追加
  `state/sogou_recovery_log.jsonl`，其中 `since_last_block_s` =
  距连发标定日志（`sogou_throttle_log.jsonl`）末条 blocked 读数的秒数，
  是恢复曲线的 x 轴（无记录/文件缺失/坏行如实 null，best-effort 不阻塞
  探活本体）；网络异常也记读数落账（风控期 RST/超时是真实数据点）；
  `log_path=None` 只测不落账（测试用）
- `tools/doctor.py`：`--sogou-probe` 模式——只跑搜狗恢复曲线单发探活
  （独立于全量巡检，参照 `--cookie-probe` 的单项标定模式），读数追加
  `state/sogou_recovery_log.jsonl`；观测不判故障：blocked/正常均为成功
  数据点 exit 0，本地故障 exit 1。恢复阈值以 jsonl 实测读数为准
  （v3.13 单点：风控后 ~171s 单发即恢复，待周期性探活积累读数收敛）

### Fixed
- **wenxin 声明对齐复查**（逐条对照 wenxin_engine docstring / README
  v3.7 节 / mcp_server 描述与实现，零真实文心调用）：
  - README v3.7 用法节输出契约滞后失实——v3.12 给 answer 顶层与
    citations[].abstract 加的 `truncated` 字段未同步进文档，已补
    （"answer(markdown, 截 4000 时带 truncated=true)"、
    "abstract(截 500 时带 truncated=true)"，与 `ANSWER_MAX_CHARS`/
    `ABSTRACT_MAX_CHARS` 实现常量一致，测试钉死）
  - mcp `china_search` 描述缺 wenxin 输出形态声明——补"返回单条聚合行
    （AI 答案 answer + 引用 citations），不是网页列表"，防调用方按网页
    列表误读
  - 其余逐条核对一致（配额纪律三条、熔断语义 1005/kunlun/wappass→
    wenxin_quota 落盘 6h、tokenFail→wenxin_token_fail 不熔断、
    wenxin_timeout 触发条件、slug 表五项、on_error 三态、每身份约 1 次
    的全新 context 实现），无失实

### Confirmed
- `tools/doctor.py` `check_searxng` 的 unresponsive_engines 输出（上一
  轮发现项收尾确认）：实现已如实输出（"不健康引擎: [...]" / "引擎全健
  康"），此前零测试覆盖，本轮补钉子测试防回退

### Changed
- 版本号 3.13.0 → 3.14.0（`tools/mcp_server.py`、
  `tools/chat-scraper/__init__.py`）；README 徽章同步
- `tests/test_v3130.py` 版本锁改常青下限（≥3.13.0，v3.12 先例）：精确锁
  当前版本是当轮 test_v3140 的职责

### 测试
- `tests/test_v3140.py`（22 个测试，全离线零真实请求/零浏览器）：搜狗
  probe_once（正常读数落账 / antispider 重定向 / 0 行软风控 / 网络异常
  记读数不炸 / log_path=None 不落账 / 走引擎默认节流不绕过（与
  probe_burst 相反语义）/ tool 字段透传）+ since_last_block_s（末条
  blocked 起算 / 无风控记录 null / 文件缺失 null / 坏行跳过 / 合法
  JSON 非对象行跳过（审计轮修复钉死）/ probe_once 自带该字段）+
  doctor --sogou-probe（正常 exit 0 落账 / blocked 仍 exit 0 观测语义 /
  本地故障 exit 1）+ check_searxng 引擎健康输出钉死（unresponsive 如实
  列出 / 全健康明说）+ wenxin 对齐钉子（README 契约含 truncated / 声明
  上限与实现常量一致 / mcp 单条聚合行声明）+ 版本锁 3.14.0
- 全量 249 passed（227 → 249）

### 实测记录
- 真实网络消耗：搜狗探活 2 发（预算 ≤3），均过审——`doctor --sogou-probe`
  2026-09-16 19:12/19:13（+08:00）连测两发：HTTP 200 + 9 行真结果、
  blocked=false，since_last_block = 27106.0s / 27122.8s（≈7.5h，距
  v3.13 连发标定的末次风控读数 11:41:13）；两发间隔 16s 顺带证实探活
  走引擎 8s 默认节流。当前恢复曲线 = v3.13 单点（~171s）+ 本轮两点
  （7.5h 已完全恢复），样本仍少，待周期性探活（cron 侧可挂
  `--sogou-probe`）积累收敛；知乎 0、文心 0、google 0
- 读数落 `state/sogou_recovery_log.jsonl`（本地 gitignore，不入库）

## [3.13.0] - 2026-09-16

### 🎯 标定补齐批：搜狗连发风控阈值标定（架构图最后一个无标定引擎）+ B站多 P 展开

上轮下一环建议两项全部落地。全程实测取证：搜狗探测 6 请求（预算 ≤8）、
bilibili 多 P 验证 8 请求（预算 ≤8），均为单进程/低成本探测模式。

### Added
- `tools/chat-scraper/sogou_engine.py`：**连发风控阈值标定**（参照 doctor
  `--cookie-probe` 的低成本标定模式）——新增 `probe_burst()` + CLI
  `--probe N --probe-interval S`：短间隔连发探测（绕过引擎默认 8s 节流，
  但逐请求如实更新引擎级时间戳），每请求读数一行追加
  `state/sogou_throttle_log.jsonl`（{ts, seq, interval, http, rows,
  blocked, note}），首个风控读数即停（证据到手不烧多余请求），网络异常
  记 error 读数即停，`log_path=None` 只测不落账（测试用）。
  **实测标定（2026-09-16 本机，读数见 jsonl）**：短间隔连发（探测
  sleep 2s/发，含请求自身耗时的实测请求节奏 2~4s/发、全程 ~12s 窗口）
  第 1~4 发
  全过审（HTTP 200、9 行真结果），第 5 发即 302 到
  `antispider/?m=1&antip=web_sh2`——**连发阈值 = 4 发**；风控后
  ~171s 冷却单发恢复。引擎默认 8s 间隔据此确认有余量、维持不变；搜狗
  维持单页不翻页的定位由"阈值未测"升级为"翻页必然触发阈值"的实证结论。
  判据抽 helper（`_blocked`/`_soft_blocked`）与 `search()` 逐字共用，
  search 行为零漂移（回归钉死）；会话构造抽 `_new_session()` 复用
- `tools/chat-scraper/bilibili_engine.py`：**多 P 展开**——`fetch_video`
  /`fetch_subtitles` 新增 `part` 参数，且 URL 带 `?p=N` 自动提取（显式
  part 优先，默认 P1）：输出新增 `page`（解析到的分 P 号）、
  `part_title`（该分 P 标题）、`pages_count`（总 P 数），cid 为该分 P 的
  cid（v3.9 起的"本工具不展开 pages"声明就此作废）；分 P>1 时 url 带
  `?p=N` 便于回跳。分 P 超界如实抛 `BilibiliApiError` 含合法范围
  （"分 P 99 不存在（共 3 个分 P，合法范围 1~3）"），不静默回退 P1。
  `_resolve_cid()`：无 pages 的旧形态 view 响应回退 `data.cid`（v3.4/
  v3.9 fixture 行为原样）；**live 验证（BV1EW411u7th，40P 课程）**：P1
  cid=38442945 / P2 cid=35533224 正确区分，subtitles 的 P2 cid 与
  fetch_video 交叉一致，超界报错含范围。同进程 8 请求完成全部验证
  （home 1 + search 1 + view 4 + nav 1 + player 1）

### Changed
- `tools/mcp_server.py`：`bilibili_video`/`bilibili_subtitles` 描述如实
  化（多 P 展开 + 超界报错语义）并透传新增可选 `part` 参数（默认 None
  行为不变）；`china_search` 描述的搜狗声明由"连发风控阈值未测"升级为
  实测结论（连发阈值 4 发，不做翻页）
- 版本号 3.12.0 → 3.13.0（`tools/mcp_server.py`、
  `tools/chat-scraper/__init__.py`）；README 徽章同步
- 文档标定回写：`ARCHITECTURE.md` 引擎选型实测记录补搜狗阈值条目（架构
  图上最后一个无标定数据的引擎补齐）；`README.md`、
  `tools/chat-scraper/README.md` 的"阈值未测"声明全部更新为实测数据

### 测试
- `tests/test_v3130.py`（26 个测试，全离线零真实请求/零浏览器）：搜狗
  probe（全过审逐请求落账 / antispider 即停不烧多余请求 / 0 行软风控
  即停 / 正常结果含风险词不误杀（审查 B2）/ 网络异常记读数即停 /
  log_path=None 不落账 / sleep 用显式间隔而非引擎默认节流且更新时间戳 /
  _blocked·_soft_blocked 判据单元 / search 主风控·软风控·正常解析三路
  回归钉死重构零漂移）+ bilibili 多 P（?p=N 提取六形态 / _resolve_cid
  四路径 / fetch_video 默认 P1·URL 提取·显式参数优先·超界 report 协议 /
  fetch_subtitles 用分 P cid 签 player（参数级验证）·超界报错）+ 版本锁
  （mcp_server 与 chat-scraper __init__ 同步 3.13.0）+ MCP part 透传
  （显式/默认 None）
- 适配：`test_v3120` 版本锁改常青下限（≥3.12.0，精确锁移交 test_v3130）；
  `test_v390` MCP 透传断言补 `part=None`（增量参数，行为不变）
- 独立审计（headless 子代理，只读）判词 FAIL 扫出两新病，本轮修复：
  ① 标定间隔声明 "@2s" 与 jsonl 实测请求节奏（4.0/2.0/3.0/3.0s，含请求
  自身耗时）不符——证据链断裂，全部文档改为实测表述（"探测 sleep 2s/发、
  实测请求节奏 2~4s/发"，阈值=4 发结论不变；不重跑探测——搜狗预算
  6/8 不足以再凑一次到块探测）；② README 测试徽章 201 未随 227 更新
- 全量 227 passed 连续两轮（v3.12.0 基线 201 + 本轮 26）；搜狗标定另附
  当天真实探测读数（见 Added 节），B站多 P 附同日 live 验证

## [3.12.0] - 2026-09-16

### 🎯 架构病扫尾批：百度搜索翻页（num>20 不再静默截断）+ 截断可见化扫尾（wenxin / bilibili desc）

v3.11 修的两个架构病（num 超单页上限静默截断、截断无标记）各只扫了一个
引擎/模块；本轮按架构图把同构残留扫完。

### Added
- `tools/chat-scraper/baidu_engine.py`：**搜索翻页**——num>20 不再静默
  截断（此前 rn=20 单页到顶，多要的条数无声蒸发；docstring 虽声明了单页
  上限，但门面/MCP 描述未把上限传给调用方，与 v3.11 修掉的 bilibili 同一
  架构病）。实现与 bilibili 同款纪律：`pn` 偏移翻页、护栏 `MAX_PAGES=3`
  页（有效上限约 60 条——百度软风控实测敏感且引擎级节流默认 20s/请求，
  护栏比 bilibili 的 5 页保守；页数越多风控压力与耗时线性放大）、服务端
  空页如实停（不发多余请求）、页间节流复用引擎内置 `_wait_turn`；num≤20
  的单页快路径请求次数与 v3.11 完全一致；`page` 起始页参数（库能力，与
  bilibili 对称）；`since` gpc 逐页携带。**翻页中途风控的诚实语义**：已
  收集 >0 条后桌面桶病了（占位页/验证码/网络异常退避穷尽）→ 如实抛
  `BaiduSoftBlocked`（message 含已收集页数/条数），不伪装部分结果为完整，
  也绝不切移动桶（移动桶单页 20 条补不齐还多烧一个风控桶；门面按既有
  协议降级搜狗）；**0 收获时才走移动桶兜底**（v3.2 语义原样保留，移动桶
  保持单页）。`search()` docstring 同步

### Fixed
- **跨页去重缺失（审查 A1，独立审计发现）**：两引擎翻页的页内去重
  （`_parse_results` 的 `seen` / bilibili 页内循环）都是局部集合——翻页
  后页间重叠条目会重复进返回集（百度 pn 翻页页间重叠是常态）。修复：
  - `baidu_engine._search_impl`：跨页 `seen_urls` 集合，重复 url 不再进
    返回集；整页全是重复 = 排序已穷尽信号，如实停（同空页语义，不发
    多余请求）
  - `bilibili_engine._search_impl`：跨页 `seen_bvids` 同款修复（v3.11
    翻页引入的同构病，本轮审计扫出）
- **截断可见化扫尾**（v3.11 只扫了 zhihu_content 四处，本轮把剩余输出
  截断口扫完，全部增量字段向后兼容）：
  - `tools/chat-scraper/wenxin_engine.py`：`answer` 截 4000 时输出带
    `truncated=true`；`citations[].abstract` 截 500 时每条自带 `truncated`
    ——统一走新增 `_clip(text, limit)` helper，源代码级断言不再有裸
    `[:ANSWER_MAX_CHARS]`/`[:ABSTRACT_MAX_CHARS]` 切片
  - `tools/chat-scraper/bilibili_engine.py` `fetch_video`：`desc` 截
    2000 时输出带 `truncated=true`（新增 `DESC_LIMIT=2000` 常量）

### Changed
- `tools/mcp_server.py` 描述如实化：`china_search` 补百度系 num>20 自动
  翻页（护栏 3 页约 60 条、页间 ~20s 节流按页数放大）与 sogou/知乎链
  单页如实截断声明（搜狗是降级环、连发风控阈值未测，不做翻页——与引擎
  定位一致）；`bilibili_video` 补 desc 截 2000 带 truncated 说明
- 版本号 3.11.0 → 3.12.0（`tools/mcp_server.py`、
  `tools/chat-scraper/__init__.py`）；README 徽章同步；顺修
  `__init__.py` docstring 首行版本串残留 v3.10.0 的漂移

### 测试
- `tests/test_v3120.py`（24 个测试，全离线零真实请求/零浏览器）：百度
  翻页（单页快路径 1 请求 / num=45 三页 pn=0/20/40 / 空页如实停 /
  MAX_PAGES 护栏 / num=0 零请求 / page 起始页 pn 偏移 / gpc 逐页携带 /
  半途风控如实抛错含已收集数且不烧移动桶 / 0 收获切移动桶兜底 / report
  模式错误记录包装 / 跨页去重+整页重复早停）+ wenxin 截断（`_clip` 边界 /
  parse_sse abstract per 条标记 / search answer 顶层标记长短两态）+
  bilibili desc 截断（超限 / 短文 / 恰好 2000 边界）+ bilibili 跨页去重
  （混合页去重 / 整页重复早停）+ 源码级裸切片清零断言 + mcp_server
  版本锁
- v3.11 护栏测试适配早停语义（护栏用例改每页不同数据；页间重复早停由
  test_v3120 单独钉死）
- 全量 201 passed 连续两轮（v3.11.0 基线 177 + 本轮 24）；百度翻页另附
  当天真实翻页实验（num=45 三页实测，见 Added 节）

## [3.11.0] - 2026-09-16

### 🎯 v3.10 暂缓项复评落地：doctor GitHub 403 根因修复（实测对照）+ B站搜索翻页 + Method 2 死代码清理 + 截断可见化

### Fixed
- `tools/doctor.py` `check_github`：**长期 403 的根因是漏 UA，不是配额耗尽**。
  实测对照（2026-09-16，同 IP 同分钟）：裸 `urllib.request.urlopen`（默认
  UA=Python-urllib/3.x，即 v3.10 及之前的代码形态）→ GitHub 稳定返回
  403 "rate limit exceeded for <IP>"；带 `User-Agent` 头 + 绕代理 opener
  → 200。修复=与其余 6 项检查同款走 `_get()`（UA 头 + `ProxyHandler({})`
  直连通道）。顺修文档漂移：模块 docstring 巡检项清单补上 v3.8.2 就存在
  的"标定钩子活性"，mcp doctor 描述同步（7 项 = 5 网络探活 + 2 本地状态，
  原文"6 项网络探活"计数错误）
- `tools/mcp_server.py` doctor 工具描述：同上计数与清单修正

### Added
- `tools/chat-scraper/bilibili_engine.py`：**搜索翻页**——num>30 不再静默
  截断（v3.10 及之前单页 30 条到顶，多要的 20 条无声蒸发，违背仓库"不伪装
  完整"纪律）。实现：`_search_impl` 循环取页直到 num 满足 / 服务端空页
  （如实停，不发多余请求）/ `MAX_PAGES=5` 护栏（有效上限约 150 条，护栏
  耗尽安静返回已收集条数，语义与 v3.10 answers 的护栏一致）；页间节流走
  引擎内置 `_wait_turn`（默认 3s，风控压力与页数线性可控），无新增 sleep；
  wbi 签名重试逐页生效；num≤30 的默认路径请求次数与 v3.10 完全一致
  （单页快路径）。`search()` docstring 同步
- `tools/chat-scraper/zhihu_content.py`：**截断可见化**——新增
  `CONTENT_LIMIT=8000` + `_content_field(text) -> (content, truncated)`
  统一helper，四处 `text[:8000]` 输出口（fetch_article / zhihu-seo 浏览器
  线 / read HTTP 线 / read 浏览器线）全部改走，输出新增 `truncated` 布尔
  字段（增量字段，向后兼容）——调用方不再把"被剪过的 content"误当全文。
  相关 docstring（含 mcp zhihu_article / read_page 描述）同步

### Removed
- `tools/google-bridge/search_helper.py`：**Method 2（AF_initDataCallback
  JSON 提取）死代码删除**（v3.10 复评后落地）——可证惰性：循环体只有
  `pass`，从不 append 结果，整块是白烧一遍 page_source 正则扫描的 no-op；
  删除不触碰任何活代码路径（0 结果诊断落盘逻辑原样保留）。/health 版本串
  v23.9 → v23.10（README 工具树同步），便于区分在跑实例

### Changed
- `tools/mcp_server.py` `china_search` 描述：bilibili num>30 自动翻页说明
  （护栏 5 页 / 约 150 条）；`tools/chat-scraper/README.md` 已知限制第 5 条
  同步；版本号 3.10.0 → 3.11.0（`tools/mcp_server.py`、
  `tools/chat-scraper/__init__.py`）；README 徽章同步

### 测试
- 全量 177 passed 连续两轮（v3.10.0 基线 160 + 本轮 17，全部离线零真实
  请求；doctor GitHub 修复另附当天真实对照实验记录，见本条 Fixed 节）

## [3.10.0] - 2026-09-16

### 🎯 知乎回答列表登录门修复（实测 403 现场复现）+ cursor 翻页；doctor 钩子活性检查补测；去重清理

### Fixed
- `tools/chat-scraper/zhihu_content.py` `fetch_answers`：**v3.4 形态已死，
  实测修复**。2026-09-16 实测（403 现场复现）：知乎登录门已把
  `include=data[*].content;data[*].author` 形态的 /feeds 请求**整单拦截**
  ——访客一律 HTTP 403 code=40353（"请您登录后查看更多专业优质内容"），
  **全新 cookie 亦然**（自愈引导刷新 + 重试无法救回，线上 zhihu_answers
  实际已不可用）。同 cookie 对照实验：去掉 include 即 200，
  `author/excerpt/voteup/url` 字段齐全（excerpt 288 字实测在列）——输出
  契约不变（excerpt 本就是主来源，content 剥 HTML 兜底仅为未来登录态保留）。
  顺修：删除 `_raise_if_error_page` 重复定义（第二处遮蔽第一处，双处
  漂移隐患）；`tools/doctor.py` `check_hook_liveness` 函数内冗余
  `from datetime import datetime` 清理（顶部已 import）

### Added
- `fetch_answers` **服务端 cursor 翻页**：num 上限 20 → **500**（输入侧
  硬上限），首跳 `limit=min(num, 20)`，沿响应 `paging.next`（cursor 形态，
  实测 `?cursor=...&limit=` 尾随空 limit）剥壳**字节一致直调**（与评论
  翻页同款纪律，`_strip_api_base` 复用），`max_pages=50` 护栏防失控。
  设计差异（审计确认）：answers 的 `max_pages` 耗尽**安静返回已收集
  数据**（50 页是护栏不是异常信号）；评论线耗尽即抛错（语义是"疑似
  分页异常"）——两者各自成立，非不一致。
  **访客配额墙如实降级**：同一对照实测发现部分问题服务端只放行前几条
  回答即 `is_end`（13 答问题实测仅回 3 条，响应自带
  `force_login_when_click_read_more`）——按 is_end 如实返回，不报错、
  不伪装完整；要更多/全文走 read_page 浏览器线
- `tools/mcp_server.py` `zhihu_answers` 工具描述同步（num≤500、翻页、
  登录门/配额墙实测上限如实声明）；README 徽章/头部/工具矩阵/
  已知限制节同步
- `tests/test_v3100.py`（14 个测试，全离线零真实请求）：fetch_answers
  直测（首跳无 include 断言 / 单跳投影 / cursor 翻页字节一致 /
  num 截断不再发第二跳 / max_pages 护栏 / excerpt→content 兜底 /
  非法问题 id / num≤0 零请求）+ doctor `check_hook_liveness` 四分支
  （日志缺失 / 新鲜读数 / >48h 断线报警 / 坏时间戳）

### Changed
- 版本号 3.9.0 → 3.10.0（`tools/chat-scraper/__init__.py`、
  `tools/mcp_server.py`）；README 徽章/Tests 数同步

### 测试
- 全量 160 passed（v3.9.0 基线 146 + 本轮 14）

## [3.9.0] - 2026-09-16

### 🎯 cookie 定时续期策略（基于 <48h 实测标定）+ bilibili 字幕读取链路（实测未登录恒空，如实降级）

### Added
- `tools/doctor.py`：**`--cookie-probe --renew-if-older-than H`**——探活发现
  cookie 已 expired 且龄 >H 小时时，顺手动用一次无头引导续期（直接调
  `zhihu_bootstrap.bootstrap`，不走 `_try_self_heal` 的 600s 冷却闸门）。
  依据：实测标定知乎访客 cookie 寿命 **<48h**（47.4h 即 403，见
  `state/cookie_lifetime_log.jsonl`），现行"用时触发自愈"白天首用要吃 ~15s
  无头引导延迟；cron 每日 9 点 `--renew-if-older-than 36` 在低峰窗口把续期
  做掉，白天使用零延迟。默认关闭=现行纯标定行为不变。纪律：标定读数先落定、
  续期在其后（不污染寿命分布数据）；续期结果记进同一读数行新增的
  `renew`（None=未启用/False=启用未触发/True=已续期）与 `renew_result`
  字段；只动 expired 读数——missing（没戴表）与 error（网络/风控）不触发；
  续期失败 exit 1（运维动作失败，cron 侧可报警），纯观测仍 expired/valid
  均 exit 0。顺修隐患：`cmd_cookie_probe` 改为显式传
  `entry_path=COOKIE_LOG_PATH`（默认参数在 def 时绑定，测试 patch 全局
  会失效、把假读数写进真实标定日志）
- `tools/chat-scraper/bilibili_engine.py`：**`fetch_subtitles(video)`**——
  B 站字幕读取链路：view API 拿 cid → `player/wbi/v2`（复用引擎内置 wbi
  签名 + 密钥 TTL 缓存）拿 `subtitle.subtitles` → 字幕逐个拉 JSON 正文
  （`{from,to,content}` 行列表）。**实测上限（如实降级声明）**：未登录
  访客请求字幕列表**恒为空**——3 个视频实测（BV1GJ411x7h7 Rick Astley MV、
  BV1hs411j76f TED_Talks、BV1JE411N7UD 迪士尼扭曲仙境剧情片——后者标题
  自带"CC字幕更新完毕"、确有 CC 字幕，访客列表仍为空），B 站仅向登录态
  （SESSDATA）下发字幕，手动上传 CC 亦不豁免。本工具不带登录态，故当前
  `subtitles` 恒为 `[]`（`has_subtitles=false` + note 讲明原因，非故障、
  不伪装成"没搜到"）；请求链路按登录态可用形态实现并全量 mock 测试，未来
  接入 SESSDATA 直接出数据。取 P1（view 响应 `data.cid`）；顺带实测确认
  `player/wbi/v2` 必须带 cid（bvid-only 报 code=-400）
- `tools/chat-scraper/bilibili_engine.py`：`fetch_video` 返回补 `cid` 字段
  （字幕链路前置；多 P 视频为 P1 的 cid）
- `tools/mcp_server.py`：新增 **`bilibili_subtitles`** MCP 工具（委托
  `fetch_subtitles`，on_error 固定 report），工具总数 13 → 14
- `tests/test_v390.py`（14 个测试，全离线零真实请求/零浏览器）：renew 分支
  全覆盖（expired+超龄→bootstrap 调用且 out_path 正确；valid/未超龄/龄未知/
  missing/error→不调；未启用→不调且 renew=None；续期成功 exit 0、失败
  exit 1、纯观测 expired exit 0）+ fetch_subtitles（非法 bvid 错误协议、
  空字幕如实报告且只烧 2 请求、字幕正文解析 + https: 前缀 + Referer、
  CDN 失败走统一错误协议、cid 透传断言）+ fetch_video cid 补全 +
  bilibili_subtitles MCP 透传与错误兜底

### Changed
- 版本号 3.8.2 → 3.9.0（`tools/chat-scraper/__init__.py`、
  `tools/mcp_server.py`）；README 徽章/Tests 数同步；工具计数 13→14 全处
  同步（mcp_server docstring、README 特性/工具矩阵/MCP 清单、
  test_mcp_server 注册表锁）

### 测试
- 全量 146 passed（v3.8.2 基线 132 + 本轮 14）

## [3.8.2] - 2026-09-16

### 🎯 小批次收尾优化：README 徽章修复 + cookie 寿命标定工具 + v3.8.1 审计确认

### Added
- `tools/doctor.py`：**`--cookie-probe` 寿命标定模式**——真实调用一次知乎
  questions API（复用 `chat-scraper/zhihu_content.py` 的 `fetch_question`，
  探 bootstrap 同款问题 19550227），把读数（valid / expired / missing /
  error 四态 + 探活时间戳 + cookie 文件 `fetched_at` + cookie 龄小时数）
  追加写入 `tools/chat-scraper/state/cookie_lifetime_log.jsonl`（state/ 已
  gitignore，标定数据只留本地）。标定纪律：探活期间 monkeypatch 掉
  `_try_self_heal`——标定要的是 cookie 真实寿命读数，若过期即自愈刷新，
  每条 expired 都会被"续命"污染，寿命分布永远测不出来（评估员共识：
  产出决定自愈策略）。本模式只观测不判故障：expired/valid 都算成功观测
  （exit 0），日志写不进等本地故障才 exit 1。missing（cookie 文件缺/无
  d_c0）与 expired 分开记——前者是"没戴表"，后者才是"表停了"
- `tests/test_v382.py`（8 个测试，全离线零真实请求）：cookie_probe 四分支
  mock + jsonl 日志格式/追加语义 + 探活期间自愈禁用与恢复断言 +
  v3.8.1 Host 白名单边界复核补强（首尾空白 Host、前导零端口、空端口段、
  裸 IPv6）+ README 徽章版本与 `__version__` 一致性锁

### Fixed
- `README.md`：版本徽章残留 v3.7.0（上一轮 v3.8.1 替换失败——实际文本
  `Release: v3.7.0` 与预期模式不符）→ 更正为与 `__version__` 一致，badge
  文本与链接同步；Tests 徽章 111 → 实际测试数。新增一致性锁测试，徽章
  再滞后会直接红

### Changed
- 版本号 3.8.1 → 3.8.2（`tools/chat-scraper/__init__.py`、`tools/mcp_server.py`）

### 测试
- 全量 132 passed（v3.8.1 基线 124 + 本轮 8）；v3.8.1 Host 白名单审计确认：
  test_v381 主干覆盖（合法/伪造/前缀伪装/端口不匹配/缺失 fail-closed + 双
  服务真实 TCP 403）质量合格，本轮补 4 类刁钻边界全部符合 fail-closed 预期

## [3.8.1] - 2026-09-16

### 🎯 安全审计残留低危项收尾 + 运维优化（v3.8 安全加固的收尾轮）

### Security
- `tools/chat-scraper/server.py`：**Host 白名单校验**——仅接受
  `127.0.0.1:<port>` / `localhost:<port>`（port=实际监听端口），其余 Host 一律
  403；Host 头缺失按拒绝处理（fail closed）。防恶意网页借 DNS rebinding
  （攻击者域名解析到 127.0.0.1）跨源 CSRF 式驱动百度查询。补 3 个回归测试
  （合法 Host 过 / 伪造 Host 403 / 端口不匹配 403）
- `tools/google-bridge/search_helper.py`：同款 Host 白名单（双保险，叠加在
  v3.8 已删 CORS 之上），实现在 `SearchHandler._host_ok`
- `tools/google-bridge/start_mihomo.sh` + `start_search_helper.sh`：代理健康
  探针域名 `api.minimaxi.com/anthropic`（非预期第三方）→ 换中性连通性探针
  `http://connect.rom.miui.com/generate_204`（3 处）

### Fixed
- `search_helper.py` Linux Chrome 查找链残留的 `/home/yuliu/chrome/...`
  个人路径回退值删除（有 isfile 守卫但仍是别人机器的路径；PATH 查找链
  已覆盖，找不到时交给 undetected-chromedriver 自行处理）
- `mcp_server.py` china_search 工具描述的 platforms 帮助文本补 `wenxin`
  （v3.7.0 已注册进 `list_platforms` 但描述漏记，LLM 调用方看不到该选项）

### 小账（复审轮补记）
- CHANGELOG 各版测试计数段间差额（29/30、39/41、74/79、97/100 四处）为
  复审轮补充测试未逐版记帐所致，非测试丢失；本轮全量 116 全过对齐。

### Changed
- 版本号 3.7.0 → 3.8.1（`tools/chat-scraper/__init__.py`、`tools/mcp_server.py`）

## [3.7.0] - 2026-09-10

### 🎯 新增 wenxin 平台：文心 AI 搜索低频线（AI 认可度 + 引用发现信号）

### Added
- **`tools/chat-scraper/wenxin_engine.py`**：文心 AI 搜索引擎（wenxin.baidu.com /
  chat.baidu.com），`search(q, timeout_s=90, on_error, vendor, role)` 返回**单条
  聚合行**——`{q, answer(markdown≤4000), citations:[{url,title,abstract,source}],
  engine:"wenxin-ai", count, platform:"wenxin"}`，两类信号：AI 认可度（答案
  正文）+ 引用发现（百度后端 referenceList，常含常规搜索漏掉的直链）：
  - 协议按 2026-09-10 侦察实测移植（证据 .scratch/r6/，p2 脚本为蓝本）：
    camoufox 无头提交搜索 + 网络层截获 `POST chat.baidu.com/aichat/api/conversation`
    的 SSE 全文；`markdown-yiyan` 的 `data.value` 顺序拼接=答案，
    `thinkingSteps` 的 `referenceList[]`=引用（url 去重保序），`endTurn:true`
    =结束。纯 HTTP 不可行（token 由页面 hector 反爬链现算并服务端校验，
    侦察 5 连复现全败为证），本引擎不做纯 HTTP 通道
  - **熔断器**：见 SSE 首块 `status:1005`/`chatHitKunlun`/页面跳 wappass 即
    进入本 IP 长冷却（默认 6h，env `CHAT_SCRAPER_WENXIN_COOLDOWN_H` 可调），
    冷却期内直接报 `wenxin_quota` 不再起浏览器；模块级状态 + 落盘
    `state/wenxin_breaker.json`（CLI 一次性调用与 MCP 常驻进程共享冷却期）
  - 错误 slug：`wenxin_quota`（配额/风控，已自动熔断）/`wenxin_token_fail`
    （1001/tokenFail——文心 token 绑定浏览器运行时，此错=当前前端版本下
    token 机制已变，需重新逆向，不触发熔断）/`wenxin_timeout`/
    `wenxin_dependency_missing`（camoufox 未安装，报错带安装指引，与
    zhihu_bootstrap 同款可选依赖）；on_error 三态与仓库协议一致
  - 配额纪律写进 docstring：每浏览器身份约 1 次搜索（fresh context 用完即弃）、
    两次调用间隔小时级、1005 即熔断——**本引擎不可当关键路径**
- `search.py` 门面：`platforms=["wenxin"]` 分流（引擎 `on_error="raise"`，
  门面统一兜错误记录）；`list_platforms()` 注册
- 测试 +11（100→111，全部离线零网络）：SSE 分块解析（**真实样本切片
  fixture**：cap_168 成功流切片 / cap2_146 的 1005+kunlun 原样 /
  p3_repro1 的 1001+tokenFail 切片，存 `tests/fixtures/`）、1005 熔断触发、
  wappass 页面 URL 兜底熔断、1001 不熔断、冷却期内不起浏览器（mock 断言）、
  熔断过期放行、冷却 env 解析、on_error 三态、门面路由与错误协议；
  camoufox 浏览器交互不进离线测试（真浏览器+真配额+时序不确定，
  浏览器层按 p2 蓝本移植 + 真实一发人工验证）

### Changed
- 版本号 3.6.0 → 3.7.0（`tools/chat-scraper/__init__.py`、`tools/mcp_server.py`）
- README：v3.7 节（定位/协议/配额纪律/三条风险：配额极紧、IP 热度持久、
  SSE 格式随前端版本漂移）、安装节补 camoufox 可选依赖、环境变量表、
  错误 slug 表、用法示例；实测覆盖表新增 wenxin 行

### 实测
- 真实一发（预算 ≤2 次实搜，用 1 次）：`python wenxin_engine.py
  "智谱 GLM Coding Plan"` → **成功**：754 字 AI 答案 markdown（套餐价格/
  计费规则/接入方式结构化输出）+ 23 条引用（z.ai、百度百科、爱企查、
  腾讯云开发者社区、智源社区等），exit 0，熔断器未触发；证据
  `.scratch/r7_wenxin_engine/selftest1_success.json`

## [3.6.0] - 2026-09-10

### 🎯 MCP 接入层：整个工具箱挂成 stdio MCP server，任何 MCP 客户端直接调用

### Added
- **知乎评论读取（comment_v5 家族，2026-09-10 实测 200 全链路含翻页）**：
  - `zhihu_content.fetch_comments(target, num, order_by, expand_children,
    on_error, kind, max_pages)`：回答/问题根评论 + `/comment/{id}/child_comment`
    子评论端点；target 接受回答 ID/问题 ID/对应 URL（正则提取，纯数字按
    kind 消歧默认回答）；沿响应 paging.next 翻页（完整 URL 剥壳原样直调——
    签名字节与请求字节必须一致，offset 首跳留空但尾随 `&offset=` 保留）；
    子评论按"内嵌够 child_comment_count 就不补拉"展开，补拉也限页；
    输出扁平列表（content 纯文本≤500）
  - 602 错误语义：401+code 602（"第三方应用无此权限"）=该端点需要登录态
    ——映射 ZhihuAuthExpired 子类（slug 同 zhihu_auth_expired），message
    注明"访客不可读、重跑引导无用"，自愈跳过（引导只领访客 cookie）
  - CLI `comments <target>` 子命令（--num/--order-by/--kind/--on-error）
  - MCP `zhihu_comments` 工具（透传 fetch_comments）
- `tools/mcp_server.py`：stdio transport 的 MCP server（单文件，零业务逻辑），
  把工具箱暴露成 **13 个 MCP tools**——每个工具原样透传参数给现有模块函数，
  不做内部 API 统一（toolbox「路由层统一，内部各留特色」理念不变）：
  - `china_search`（chat-scraper search 门面）/ `read_page`（通用阅读器）/
    `zhihu_question` / `zhihu_answers` / `zhihu_article` / `zhihu_comments`
    （官方 API 结构化读取，评论走 comment_v5）/ `bilibili_video`（官方 view API）
  - `hn_search` / `github_releases` / `github_advisories`（GitHub 拆两工具：
    工具描述就是模型的路由提示，正交参数集分开比 `kind` 判别参数更不易填错，
    且与模块函数 1:1）/ `searxng_search` / `googlebridge_search`（转发
    18799 HTTP，服务未启动报可读错误含启动指引）/ `doctor`（复用 check 体系
    捕获 stdout 出文本报告，非 subprocess）
- 协议保命细节：
  - **stdout 卫兵**：工具执行期间 stdout 重定向 stderr（MCP stdio 下 stdout
    只归 JSON-RPC 协议；知乎自愈引导等库代码会往 stdout 打进度）
  - **错误协议映射**：模块 on_error 固定 "report"，错误作为正常返回内容嵌在
    JSON（`{"error": "<slug>: ...", "tool", "query"}`）；未预期异常由 server
    层兜底成同形态，绝不炸连接；zhihu_* slug（auth_expired 等）原样保留
- 耗时预期写进每个工具描述（read_page 无头浏览器 10-15s；百度 ~20s 强制间隔
  多平台串行放大；googlebridge 数十秒），建议客户端 read_timeout ≥ 120s
- 并发模型实测：mcp 2.x 同步工具经 `anyio.to_thread.run_sync` 跑工作线程，
  read_page 慢调用不阻塞 `tools/list` 与其他调用（评估结论已写入 README）
- README 新增「MCP 接入」节：客户端配置示例（ZCode / Claude Desktop）、
  13 工具清单表（名称→委托函数→用途→耗时）、超时与并发如实评估
- 测试 +18（79→97，全部离线零网络）：注册表完整性（13 工具+schema）、参数
  透传 mock 验证（含 on_error="report" 固定）、异常兜底错误形态（含
  zhihu slug 保留）、stdout 卫兵、googlebridge 死端口可读错误；
  知乎评论线 10 项（comment_v5 首跳 path/offset 字节、target URL 提取、
  沿 paging.next 原样翻页、is_end/空 next 终止、num 够数即停、子评论
  展开条件与补拉翻页、602 映射+自愈跳过、max_pages 护栏、非法 target）
- `zhihu_content._api_get`/`_api_request` 增 referer 参数（comment_v5 用
  问题页 Referer；默认值不变，原调用零影响）
- 协议级自测（仓库外 .scratch，不入库）：真 stdio spawn → initialize →
  tools/list（13 工具 schema 合法）→ 实调 doctor / hn_search（真实网络）/
  read_page + zhihu_answers（知乎 cookie 线，正文非空）/ searxng_search
  （实例未起→可读错误），10/10 PASS

### Changed
- `tools/chat-scraper/__init__.py` 版本号 3.5.0 → 3.6.0
- 依赖：server 需 `mcp>=2.1`（本机实测 2.1.1，FastMCP 已改名 MCPServer；
  文件内双版本导入兼容 1.x `mcp.server.fastmcp`）

[3.6.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.6.0

## [3.5.0] - 2026-09-10

### 🎯 第三批（评估共识）：微信/B站读取接入 + 全箱体检 doctor

### Added
- `read()` 分流扩展：
  - `mp.weixin.qq.com`（微信公众号文章，国内 AI vendor 官宣主渠道）→ 通用
    HTTP 线直读（`#js_content`/`.rich_media_content` 选择器已加入），反爬自动
    切无头浏览器兜底
    - ⚠️ 实测更正：当前自动化环境下微信返回「环境异常」验证页（HTTP 线 36
      字空壳、浏览器线验证码页）——分流与兜底机制保留（环境友好时可读），
      验证页现已按错误如实上报；微信的可靠读取需 headed 接管真 Chrome
      （评估观察单触发条件不变）
  - `bilibili.com/video/BVxx` → `bilibili_engine.fetch_video()`：官方 view API
    （公开免 wbi），结构化 title/desc/owner/view/danmaku/like/favorite/pubdate
- `tools/doctor.py`：一条命令巡检全部通道——SearXNG 实例存活+引擎健康
  （unresponsive_engines）、知乎 cookie 存在性/年龄、bilibili API、百度直连、
  google-bridge /health（可选项未起不算故障）、GitHub API；核心故障退出码 1
- 实测：B站视频 1.05 亿播放真实结构化数据；doctor 六项巡检全通过
- 测试 +4（70→74：fetch_video bvid 提取/错误协议、read B站分流、微信选择器在列）

- 复审轮（独立审计）修复：read() bilibili 分支错误逃逸+兜底目标错误双失效
  （现仅 /video/BV 走 API，任何失败回通用线）；微信/B站错误页守卫改
  「短文本 + 标记」判据（环境异常/参数错误/内容删除等家族，长文不误杀）；
  fetch_video tool 字段统一、412/5xx raise_for_status、_fmt_pubdate(0)
  不再伪造 1970；doctor cookie 缺失改 ⚠️ 不再永绿、绕系统代理、计数修正

[3.5.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.5.0

## [3.4.0] - 2026-09-09 - 2026-09-10

### 🎯 两评估代理共识批次：错误协议修正前置 + 认证自愈 + 文章 API + 通用阅读器

### Fixed（必修前置：错误协议，不修会诱发自愈风暴）

- **10003 误诊修正**：`zhihu_content.py::_raise_for_api_error` 此前把
  403+任意 code 判成 auth_expired——实测 cookie 有效时 members/answers
  返回 403+code 10003（签名被拒）也被误诊。现 `error.code==10003` →
  新异常 `ZhihuSignRejected`（slug `zhihu_sign_rejected`，提示"签名被拒/
  参数异常——非 cookie 问题，勿重跑引导"），且**先于认证检查分流**
- **404 协议缺口**：死端点返回裸 404（无 error body）此前以无 slug 的
  HTTPError 穿透。现 404 → `ZhihuNotFound`（slug `zhihu_not_found`），
  在 JSON 解析前判定（裸 404 常进不了 json()）

### Added

- **认证过期自愈**：`_api_get` 捕获 `ZhihuAuthExpired`（仅服务端拒绝：
  401/40353/ZERR_NOT_LOGIN 形态）→ 进程级闸门（模块级时间戳+锁，
  ≥600s 冷却，冷却内置位防并发重复引导）→ import `zhihu_bootstrap` →
  `bootstrap(headless=True)` 无人值守刷新 cookie → 重试原请求**一次**；
  重试直接调 `_api_request` 天然防递归。引导失败打印 stderr 后抛原异常，
  绝不吞错。本地 cookie 文件缺失**不**触发自愈（引导保持显式，也保证
  离线单测零浏览器）
- **cookie 原子落盘**（`zhihu_bootstrap.py`）：临时文件 + fsync +
  `os.replace`——半截 cookie 文件比没有更坑（自愈会拿它重试到死）
- **专栏文章 API** `fetch_article(id_or_url)`：`GET /api/v4/articles/{id}
  ?include=title,created,updated,voteup_count,comment_count,content`
  （端点 2026-09-10 实测 HTTP 200 存在）；接受纯数字 id 或
  `zhuanlan.zhihu.com/p/{id}` URL；content 空回退 excerpt，再空**如实报
  字段缺失**不伪装正文为空（include 逗号语法是否真回 content 以实测为准）
- **通用阅读器 `read(url)`**（价值评估员共识：搜索线覆盖 16 站但阅读线
  只有知乎，通用阅读器服务所有搜索产出）：知乎问题→fetch_question；
  question/{id}/answer/{aid}→fetch_answers 过滤该 aid，过滤不到或 API 线
  挂→read_via_browser；zhuanlan /p/{id}→fetch_article；其他知乎 URL→
  read_via_browser；**非知乎域名**→`_generic_read_http`（requests 直连
  trust_env=False + 完整 Chrome Accept 四件套 + 20s 超时 + bs4 选择器
  article/.post-content/.article-content/main/#content 提取、body 兜底、
  ≤8000 字）；403/网络异常/疑似反爬（正文<200 字）→ `_generic_read_browser`
  （无头 camoufox 直开，无需 Referer 技巧，engine="browser"）；404/5xx
  硬失败直接抛 `ReadError`（slug `read_failed`）不烧浏览器。统一返回
  {title, content, url, engine}
- CLI：`python zhihu_content.py read <url>`（另有 `article <id_or_url>`）
- `zhihu_engine.py` 的 searxng_unavailable 报错追加一条出路：
  「本机实例未起？cd tools/searxng/docker && docker compose up -d」
- 测试 41→66（+25：10003/404 映射、自愈触发/失败/防递归/冷却/缺失不触发、
  article id 提取与字段兜底、read 分流路由、_generic_read_http 解析
  fixture 与反爬短正文判定、searxng 提示行）

### 搁置清单（如实记录，两评估员共识未做项）

- **知乎登录线**：等主人的 z_c0 实验结论，本工具不主动碰登录凭据
- **微信/小红书专门方案**：搜狗微信搜索、小红书反爬均未实现，继续搁置
- **MCP 触发条件**：read/search 何时机被 MCP 调用未定义，搁置
- **组件化（YAGNI）**：引擎/阅读器抽象基类暂不抽取，等第三条阅读线出现
  再说

- 复审轮（独立审计）修复：read() 三分支浏览器兜底一致化（question/zhuanlan API 失败不再逃逸）；_generic_read_http 增 Content-Type 护栏（>200 字 JSON/二进制不再假成功）；浏览器线短正文如实返回（<200 字一票否决仅限 HTTP 反爬检测线）；403 无结构化错误体不再误诊 auth 并白烧引导；article title URL 解码；并发自愈单次性 + 上述各项测试锁死（测试 66→70）

[3.4.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.4.0

## [3.3.0] - 2026-09-09

### 🎯 知乎无头引导 + 官方 API 内容读取（定制浏览器组件落地）

无头隐身浏览器选型实测（camoufox / patchright / DrissionPage）：**camoufox
无头一次通过知乎 zse-ck VMP 挑战**（patchright 无头暴露 HeadlessChrome 指纹
即死、弃用；DrissionPage 价值在 headed 接管真 Chrome，留作硬目标兜底）。
定位：隐身浏览器=凭证引导器，不是爬虫引擎。

### Added
- `tools/chat-scraper/zhihu_sign.py`：x-zse-96（101_3_3.0，SM4 变种+自定义
  base64）纯 Python 签名，移植自开源 zhihu_sign_rs；服务器验签已验证（此前
  侦察：错误码 10003→40353 跃迁；本轮：真 cookie+签名 → questions API
  HTTP 200 真实 JSON）
- `tools/chat-scraper/zhihu_bootstrap.py`：无头 camoufox 引导器——开知乎
  内容页（首页会 302 登录，已避开）让 VMP JS 现算 `__zse_ck`，领
  `d_c0+__zse_ck` 存 state/zhihu_cookies.json；fetch 兜底+reload 多轮；
  camoufox 为可选依赖（缺失时给安装指引）
- `tools/chat-scraper/zhihu_content.py`：官方 API 内容读取——question
  （include 补 answer_count）/answers（web 同款 /feeds 端点，/answers 子
  端点实测被 40362 行为限制）；401/403/40353 → `zhihu_auth_expired`
  （提示重跑引导，绝不伪装真空）
- 测试 +3（32→35：签名形状/确定性、cookie 缺失与过期的错误映射；复审轮再 +4 至 39，见下）
- 实测：引导十几秒；question 19550227 → 200（answer_count=13）；answers
  → 周源/极客公园真实回答（赞 61/38）
- `read_via_browser()` + CLI `page <url>`：**免 cookie 兜底读取**——无头
  camoufox 带百度搜索 Referer 打开知乎页（搜索引擎引流放行，主人提出并
  实测证实：全文可见/无登录墙/Referer query 用 URL 本身可泛化；纯 HTTP
  带同 Referer 无效，CDN 挑战在来路逻辑之前）

### 边界（如实声明）
- **知乎搜索线不走官方 API**：search_v3 带有效 cookie 仍强制登录
  （401 ZERR_NOT_LOGIN），上登录账号属用户决策、本工具不碰凭据；搜索继续
  用引擎链，搜到 URL 后用本模块读内容
- cookie 有效期未标定；纯 HTTP TLS 指纹今日可过（兜底：curl_cffi/浏览器内
  fetch）；无头能过是当下事实非永久保证（headed camoufox 作二档）

[3.3.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.3.0

## [3.2.0] - 2026-09-09

### 🎯 百度引擎稳定化（头指纹 + 移动端桶 + 搜狗第三环）

百度是 14 个中国平台的主力引擎，软风控曾把整个工具箱打瘫（当日首请求 19/19、之后全占位页/RST）。五组对照实验（同 IP、间隔 ≥8s，证据存档 .scratch/r3/）找到了真正的开关变量：

### Fixed

- **头指纹修复（决定性）**：Chrome UA 配 requests 默认 `Accept: */*` 是机器人指纹——实测三件套组合被封、补完整 Chrome Accept 后同 IP 直连 2/2 过审（无需 cookie 无需预热）。桌面/移动会话均已内置，实测百度直连复活（csdn 查询 5 条真实结果）
- 预热 cookie 不解决 IP 级封禁（带全 cookie 照样 302 验证码）——文档如实更正

### Added

- **移动端备选桶**：m.baidu.com 与桌面端是独立风控桶（桌面被锁时移动端实测照常出结果）。桌面双退避穷尽后自动切换：iPhone UA + `div.c-result` → `data-log` JSON → `mu` 直链解析，丢弃 *.baidu.com 自家内容卡；移动端页内联 JS 含 wappass 字样，桌面版 wappass 判据已在移动路径隔离（防全量误报）；结果 engine=baidu-mobile
- **搜狗第三环**（`tools/chat-scraper/sogou_engine.py`）：百度双桶穷尽后门面自动降级搜狗（`div.vrwrap` 的 `data-url` 属性即直链，免解跳转）；搜狗 web 无时间参数，since 仅透传；CLI `python sogou_engine.py "q" --site csdn.net`
- `CHAT_SCRAPER_BAIDU_PROXY`：显式代理支持（默认空=直连；**仅在代理真的为 baidu.com 换出口时有效，Clash 规则分流国内域名时无效——实测**）
- `CHAT_SCRAPER_SOGOU_PROXY`：搜狗引擎显式代理（默认直连）
- 测试 +5（Accept 头指纹、移动端 data-log 解析、搜狗 data-url 解析、门面"百度故障→搜狗、百度真空→不降级"语义），共 30 个

[3.2.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.2.0

## [3.1.0] - 2026-09-09

### 🎯 知乎专用搜索引擎链（chat-scraper）

知乎是国内反爬最严的平台之一，五路路径全部实测后定架构（证据存档 .scratch/r2/）：

### Added

- `tools/chat-scraper/zhihu_engine.py`：降级链 **本机 SearXNG → 搜狗 → 百度 site:**
  - 主路径 SearXNG：`site:` 交给聚合后端（实测 brave / google cse 均严格尊重且返回直链、零验证码；后端随健康度浮动，engine 字段可观测），支持 since→time_range
  - 搜狗：尊重 site: 但结果包在 `/link?url=` 跳转里——默认解跳转（302 Location / `location.replace` 双模式，≥2s 节流，`CHAT_SCRAPER_SOGOU_RESOLVE=0` 可关，解不开保留跳转链）；验证码报 `sogou_blocked`
  - 百度 site: 保底（复用 baidu_engine，IP 软风控时报 `baidu_soft_blocked`）
  - 降级语义：单引擎**报错或 0 结果都降级**；全链失败报错带 `chain` 字段（每环结局可诊断），全链成功 0 结果才是真真空
- `search.py` 门面：`platforms=["zhihu"/"zhuanlan"]` 路由到专用引擎链（不再裸走百度）
- CLI：`python zhihu_engine.py "query" --num 10`（错误走 stderr + exit 1，与全仓协议一致）
- 测试：+6 个知乎引擎离线测试（搜狗解析含高亮清理/去重/直链保留、跳转解析正则、searxng 域过滤、链条降级、全链失败 chain 日志、门面路由拦截），共 24 个

### 实测结论（为什么不是直连知乎 API）

- 知乎网页直爬：zse-ck VMP 风控盾，403（与登录无关）
- 知乎官方 API：x-zse-96（`101_3_3.0`，SM4 变种+自定义 base64，算法来自开源 zhihu_sign_rs）**已移植且服务器验签通过**（非搜索端点错误码 10003→40353 跃迁为证），但 search_v3 入口有边缘 WAF（`400 {"HitLabels":null}`，与签名无关）、访客 cookie `d_c0/__zse_ck` 由 VMP 浏览器挑战签发纯 HTTP 拿不到 → 除非未来加无头浏览器引导 cookie，此路不通
- cn.bing：剥离 `site:`（前序 4/4 对照复现），不可用
- 最终：SearXNG 主路径实测 5 条知乎直链；SearXNG 单引擎依赖（brave）与搜狗跳转成本已写进 README 风险段

[3.1.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.1.0

## [3.0.0] - 2026-09-09

### 🎯 全面审计驱动的大修（5 工具逐一代码审查 + 本机实测 + 独立复审）

v2.1.0 审计结论：5 工具中 2 个能用、3 个不可用（chat-scraper 为 NUL 空壳、google-bridge 在 Windows import 即崩、searxng 开箱无可用实例）；另发现同进程 import 撞名、CI 必然假绿等系统性缺陷。本版本逐项修复并补齐防回归测试。

### Added

- **统一错误协议**：所有客户端库 `on_error="report"/"raise"/"empty"`（默认 report，返回带 `error` 字段的记录），CLI 出错 stderr + exit 1——故障不再伪装成"0 结果"（v2 的静默 `[]` 是设计病）
- **tests/**：18 个离线单测（含 **NUL 空壳防回归**、**同进程 import 撞名防回归**、时区/解析契约测试）+ 真冒烟脚本（HN/GitHub 公网 API，限额时自动 SKIP）
- **CI 重写**（.github/workflows/test.yml）：v2 只做 py_compile 且带 `|| true`（NUL 文件也假绿）；v3 改为编译无豁免 + NUL 检测 + 离线单测（ubuntu/windows 双矩阵）+ google-bridge 服务健康与可读失败验证 + 公网冒烟（continue-on-error）
- `tools/searxng/docker/`：docker-compose + settings.yml（`search.formats` 启用 JSON——公网实例默认禁 JSON，这是 v2 README 推荐公网实例却必然失败的根因），一条命令起本地实例（实测 JSON API 返回真实结果）
- `tools/chat-scraper/` **从零重写 v3**（旧版 12 个 .py 中 11 个为纯 NUL 空壳、上游仓库已 404、代码不可恢复，自 v2.0.0 入库起即无代码）：
  - `baidu_engine.py`：百度 `site:` 通用引擎——会话复用、默认 20s 节流、软风控占位页检测、指数退避、`mu` 属性直链解析（真实页面离线复验 19/19）、`since`→gpc 映射
  - `bilibili_engine.py`：官方搜索 API——buvid3 获取、风控升级自动 wbi 签名重试、广告条目过滤、结构化字段（author/play/pubdate）
  - `search.py` 门面：16 站 SITE_MAP + 任意域名透传 + 统一错误协议；引擎选型依据（bing 剥离 site: 实测 4/4 复现 → 弃用；百度/官方 API 实测有效）记录于 ARCHITECTURE.md
  - `server.py`：stdlib HTTP 服务（/search、/health，仅绑 127.0.0.1）
  - README 按实测诚实分层：✅ 实测 / best-effort 未逐一实测 / 已知风险，废除 v2 无工件支撑的"32+ 平台"宣传
- `tests/smoke_live.py` + ARCHITECTURE「引擎选型实测记录」节

### Fixed

- **google-bridge（search_helper v23.7→v23.9，17 项）**：
  - Windows import 即崩：`faulthandler.register(signal.SIGUSR1)` 加平台守卫（高）
  - UDD 硬编码他人家目录 `C:\Users\520hh\` → `~/.no1_chrome_udd`（高）
  - query 未 URL 编码 + 双重解码 → urlencode 构造、删除二次 unquote（中）
  - 默认绑定 0.0.0.0 → 127.0.0.1（中，README 原本宣称 127.0.0.1）
  - 持锁 sleep 30s 串行阻塞并发 → 锁外等待（中）
  - 页面加载失败静默 200+count=0 → HTTP 502 + error JSON（中）
  - `.sh` 硬编码 `/home/yuliu/*`、无条件覆盖用户环境变量、指向错误脚本路径 → SCRIPT_DIR 化 + `: "${VAR:=default}"`（高）
  - example_config.sh 三个幽灵变量（代码从不读）→ 换为代码真实读取的变量（中）
  - chromedriver 查找：仅环境变量 → env → state/bin/ → PATH → uc 自动下载 四级回退
  - 其余：CAPTCHA sleep 可配置（NO1_CAPTCHA_SLEEP）、CAPTCHA 启发式阈值可配（NO1_MIN_HTML_LEN）、honeypot client_ip 用真实客户端地址、删除不可达代码、Linux chrome 路径去硬编码
  - **CAPTCHA/锁定不再伪装成 0 结果（v23.9）**：CAPTCHA 持续、post-CAPTCHA 锁定、CAPTCHA 限速三种路径原 `return []` → 抛 `CaptchaBlocked`，HTTP 层答 503 + `{"kind": "captcha_blocked"}`；0 结果时自动落盘现场 HTML 到 `state/last_zero_page.html` 供诊断
  - 实测：本机端到端真 Google 搜索返回 14 条真实结果（v23.8 时点）；随后测试出口 IP 被 Google 风控，503 行为按上述实测确认
- **hackernews**：`utcnow()` 时区漂移（UTC+8 实测 -28800s）→ timezone-aware；comment 模式 points=null 导致调用方 `points >= 50` TypeError 崩溃 → `or 0` 兜底（实测会崩的 bug）
- **github**：CLI 补 `--num/--vendor/--role`（v2 缺失致输出恒 vendor="?"，与 SOP"必传"自相矛盾）；repo/ecosystem URL 编码
- **searxng**：CLI 与库 `--since` 默认不一致（7d vs None）→ 统一 7d；未知 since 值静默忽略 → stderr 警告
- **文档漂移**：SKILL.md「since 不传默认无限」实为 7d；`timeout=15` 在冷却/CAPTCHA 路径必超时 → 90s；4 个工具 README 引用 v2.1 已删除的 per-tool SOP/SKILL 断链 → 清理；全部命令 `python3` → `python`
- **独立复审轮修复**（两路审查代理挑毛病后逐条落实，复审验收 PASS）：
  - SKILL 兜底链示例 q 未编码，带空格 query 抛 InvalidURL 被裸 except 吞掉——google-bridge 被静默跳过（示例自身犯了 v3 要消灭的"故障伪装"）→ `quote(q)` + 降级日志可见
  - tools/searxng/README.md 仍推荐裸 `docker run`（产出的实例 JSON 未启用，客户端必失败）→ compose 定为唯一推荐部署
  - SOP google-bridge 部署缺 `source .env`（search_helper 自身不读 .env，改了不生效）→ 已补
  - CAPTCHA 限速计数器永不衰减（进程生命周期内累计 2 次 CAPTCHA 即永久 503）→ 滚动 10 分钟窗口，出窗衰减（端点级实测）
  - chat-scraper 三个 CLI 错误输出统一为 stderr + exit 1 + stdout 空，且按任一平台故障判
  - /health 与启动横幅版本号 v23.8 → v23.9 对齐；hackernews null-points 兜底补 2 个回归测试（含 mock 端到端）；bilibili num<=0 边界、nav 非 JSON 包装、searxng 空 time_range 不再拼 URL；.gitignore 补 state/；compose 密钥标注示例值仅限本机；文档死链与 "32+ 平台" 残留清理；SKILL 案例 1 改为可运行纯 python

### Changed

- 轻客户端模块唯一化：`hackernews_client.py` / `github_client.py` / `searxng_client.py`（旧 `client.py` 变 3 行兼容 shim，打 DeprecationWarning）。v2 三个同名 `client.py` 同进程 import 第二个被 sys.modules 缓存静默劫持（SKILL 模式 4 的"多源验证"实测无声失效）
- 顶层 SOP/SKILL/README/ARCHITECTURE 全面同步 v3 现实（错误协议、新模块名、新部署命令、诚实状态表）

### 兼容

- 旧 `from client import search` 用法仍可用（shim），但同进程禁止 import 多个工具的 `client`
- 各 CLI 的既有参数不变；github CLI 为新增参数

[3.0.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.0.0

## [2.1.0] - 2026-08-05

### 🎯 重大调整：从分散 SOP+SKILL 到 1 顶层 SOP+SKILL

**用户原话**："不是一个工具一个sop。是只有一个sop和skill当做路由。根据任务把他们引导到不同工具。"

### Changed

- ❌ 删除 `tools/*/SOP.md`（5 份分散 SOP）
- ❌ 删除 `tools/*/SKILL.md`（5 份分散 SKILL）
- ❌ 删除 `docs/` 目录（choosing-tool / composition-patterns / quality-gate / query-design）
- ✅ 新增顶层 `SOP.md` —— 唯一 SOP：怎么选工具（路由）+ 怎么用（5 步流程）
- ✅ 新增顶层 `SKILL.md` —— 唯一 SKILL：4 个组合模式 + 3 维信号过滤 + query 模板
- ✅ `tools/<tool>/README.md` 保留（工具自己的部署 / 启动 / 失败回滚）
- ✅ README + ARCHITECTURE 重新设计（强调 1 SOP + 1 SKILL 路由）

### 设计变化

| v2.0.0 | v2.1.0 |
|---|---|
| 4 元文档（choosing / composition / quality-gate / query-design）| **1 顶层 SOP + 1 顶层 SKILL** |
| 5 per-tool SOP.md | 0 per-tool SOP.md（合并到顶层 SOP）|
| 5 per-tool SKILL.md | 0 per-tool SKILL.md（合并到顶层 SKILL）|
| 路由分散在 5 处 | **路由集中在 1 处** |

### 兼容

- 工具代码 / 启动脚本 / 客户端 / 部署流程：**完全不变**
- 用户只读 `SOP.md` + `SKILL.md` 就能用整个工具箱
- 想了解某个工具细节时，单独看 `tools/<tool>/README.md`

[2.1.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v2.1.0

## [2.0.0] - 2026-08-05

### Added
- 5 个独立工具：google-bridge / searxng / hackernews / github / chat-scraper
- 4 元文档 + 5 per-tool SOP/SKILL（**已被 v2.1 取代**）

[2.0.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v2.0.0

## [1.0.0] - 2026-08-05

### Added
- 首个稳定版
- `search_helper.py` v23.7
- README + ARCHITECTURE + CHANGELOG + .github CI
- MIT License

[1.0.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v1.0.0
[3.7.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.7.0
[3.8.1]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.8.1
