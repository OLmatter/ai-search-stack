# Changelog

## [3.0.0] - 2026-09-09

### 🎯 全面审计驱动的大修（5 工具逐一代码审查 + 本机实测 + 独立复审）

v2.1.0 审计结论：5 工具中 2 个能用、3 个不可用（chat-scraper 为 NUL 空壳、google-bridge 在 Windows import 即崩、searxng 开箱无可用实例）；另发现同进程 import 撞名、CI 必然假绿等系统性缺陷。本版本逐项修复并补齐防回归测试。

### Added

- **统一错误协议**：所有客户端库 `on_error="report"/"raise"/"empty"`（默认 report，返回带 `error` 字段的记录），CLI 出错 stderr + exit 1——故障不再伪装成"0 结果"（v2 的静默 `[]` 是设计病）
- **tests/**：16 个离线单测（含 **NUL 空壳防回归**、**同进程 import 撞名防回归**、时区/解析契约测试）+ 真冒烟脚本（HN/GitHub 公网 API，限额时自动 SKIP）
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

- **google-bridge（search_helper v23.7→v23.8，15 项）**：
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
  - 实测：本机端到端真 Google 搜索返回 14 条真实结果
- **hackernews**：`utcnow()` 时区漂移（UTC+8 实测 -28800s）→ timezone-aware；comment 模式 points=null 导致调用方 `points >= 50` TypeError 崩溃 → `or 0` 兜底（实测会崩的 bug）
- **github**：CLI 补 `--num/--vendor/--role`（v2 缺失致输出恒 vendor="?"，与 SOP"必传"自相矛盾）；repo/ecosystem URL 编码
- **searxng**：CLI 与库 `--since` 默认不一致（7d vs None）→ 统一 7d；未知 since 值静默忽略 → stderr 警告
- **文档漂移**：SKILL.md「since 不传默认无限」实为 7d；`timeout=15` 在冷却/CAPTCHA 路径必超时 → 90s；4 个工具 README 引用 v2.1 已删除的 per-tool SOP/SKILL 断链 → 清理；全部命令 `python3` → `python`

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
