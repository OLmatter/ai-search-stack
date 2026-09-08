# Changelog

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
