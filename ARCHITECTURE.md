# Architecture

> ai-search-stack v3.0 toolbox 设计理念（2026-09-09 全面审计后重写）。

## 核心论点

**toolbox 模式**：5 个独立工具 + 1 个统一 SOP + 1 个统一 SKILL。

## 为什么 toolbox 而不是 monolith

| 维度 | Monolith（统一 API） | Toolbox（独立工具 + 1 SOP/SKILL 路由）|
|---|---|---|
| 维护成本 | 🟢 一处改 | 🟡 多处改 |
| 部署灵活 | ❌ 必须全装 | ✅ 按需装 |
| 工具替换 | ❌ 改 API 破坏兼容 | ✅ 换工具不动 SOP |
| 故障隔离 | ❌ 一处挂全挂 | ✅ 单工具坏不影响其他 |
| 学习曲线 | 🟡 复杂 | 🟢 简单（看 1 SOP + 1 SKILL）|
| **路由清晰度** | 🟡 隐式在 API 里 | 🟢 **显式在 SOP 里** |

**用户原话**："不是一个工具一个sop，是只有一个sop和skill当做路由。根据任务把他们引导到不同工具。"

## 文档结构

```
ai-search-stack/
├── SOP.md                ← ⭐ 唯一 SOP（路由 + 怎么用）
├── SKILL.md              ← ⭐ 唯一 SKILL（组合 + 过滤 + query）
├── README.md
├── ARCHITECTURE.md       ← 本文件
├── CHANGELOG.md
├── tools/
│   ├── google-bridge/
│   │   ├── search_helper.py
│   │   ├── start_*.sh
│   │   ├── requirements.txt
│   │   └── README.md     ← 工具说明（不是 SOP/SKILL）
│   ├── searxng/...
│   ├── hackernews/...
│   ├── github/...
│   └── chat-scraper/...
```

**关键设计**：
- **1 SOP + 1 SKILL 在 root**：任何 agent 看完就能用整个工具箱
- **每个工具有自己的 README**：只读 1 个工具的部署细节时不被全局文档干扰
- **没有 per-tool SOP/SKILL**：路由只在 1 个地方，避免分散

## 5 个工具

| 工具 | 解决 | 何时不用 |
|---|---|---|
| `google-bridge` | WebSearch 100% CAPTCHA（真 Google，需代理） | 找中国平台 / GitHub release |
| `searxng` | 兜底聚合搜索（`docker/` 一条命令起本地实例，JSON 已启用） | 默认主搜 |
| `hackernews` | 验证社区反应 | 中文 / 非技术 |
| `github` | Release / Advisory / 仓库 | 非 GitHub |
| `chat-scraper` | 中国平台内容（bilibili 官方 API + 百度 site: 路由） | 国际主题 |

## 依赖关系

```
SOP.md / SKILL.md       ← 顶层路由（无依赖）

tools/google-bridge/    ← 依赖 Chrome + 代理；chromedriver：NO1_CHROMEDRIVER_BIN
                          → state/bin/ → PATH → uc 自动下载（四级回退）
tools/searxng/          ← 依赖 SearXNG 实例（tools/searxng/docker 一条命令自建）
tools/hackernews/       ← 依赖：零（公网 API）
tools/github/           ← 依赖：零（公网 API；可选 GITHUB_TOKEN 解除 60/h 限额）
tools/chat-scraper/     ← 依赖 requests + bs4
```

工具之间**不互相依赖**。但组合模式可叠加（见 SKILL.md 的 4 模式）。

## 设计原则

1. **1 SOP + 1 SKILL 路由**——避免分散，让 agent 一处看全
2. **每个工具有完整 README**——只部署 1 个工具时不被全局文档干扰
3. **不抽象"统一"工具**——强行抽象会损失每个工具的特色
4. **可单独发布**——每个工具有自己的版本号（如 search_helper v23.8）
5. **可组合**——SKILL.md 给 4 个组合模式（找+验 / 跨语言 / 兜底链 / 监控+验证）
6. **统一错误协议**（v3）——库 `on_error="report"/"raise"/"empty"`，出错带 `error` 字段或 exit 1；故障永远不伪装成"0 结果"（v2 的静默 `[]` 曾把网络故障误导成查询问题）
7. **模块名唯一**（v3）——轻客户端真名为 `*_client.py`，旧 `client.py` 只作 3 行兼容 shim；同名模块同进程 import 会被 sys.modules 缓存静默劫持（v2 实测事故）
8. **诚实文档**（v3）——能力声明以实测为准，未实测的明确标 best-effort；v2 的"32+ 平台"宣传无工件支撑，是教训

## 引擎选型实测记录（2026-09-09，重写 chat-scraper 的依据）

- **cn.bing 对纯 HTTP 客户端剥离 `site:` 操作符**：4 组对照实验（zhihu/zhuanlan/bilibili/douban/v2ex）全部复现，换 cookie/参数/RSS 格式均无效 → 不能做站内搜索引擎。bing 的 `format=rss` 通道本身可用，仅可作无 site: 的备胎
- **百度尊重 `site:`**：zhihu 组实测 19/19 真实直链（`div.result` 的 `mu` 属性即直链）；但有软风控——短间隔连发返回 1488 字节占位页 → 引擎内置会话复用 + ≥15s 节流 + 占位页检测 + 指数退避，风控时按错误协议上报 `baidu_soft_blocked`
- **bilibili 官方搜索 API**：buvid3 一个 cookie 裸调即 code=0，返回搜索引擎给不了的结构化字段（author/play/pubdate/bvid）；风控升级时自动带 wbi 签名重试（已内置完整实现）；必须过滤 bvid 为空的广告条目

## 复用边界

什么**包含**：
- 5 个独立工具
- 1 SOP + 1 SKILL（路由 + 组合）
- 工具自己的 README（部署 / 启动 / 失败回滚）

什么**不包含**：
- Agent 调度框架
- Push 通知
- Dedup 库
- 监控告警

**理由**：ai-search-stack 是搜索工具箱，组合使用时自己选周边。

## 演进

| 版本 | 模式 | 状态 |
|---|---|---|
| v1.0.0 | 单工具（search_helper）+ 顶层 docs/ | 已发布 |
| v2.0.0 | 5 工具 + 4 per-tool SOP/SKILL + docs/ 元 | 已发布（**用户说分散了**）|
| v2.1.0 | 5 工具 + 1 顶层 SOP + 1 顶层 SKILL | 已发布（chat-scraper 空壳入库、多处平台/文档缺陷，2026-09-09 审计暴露）|
| v3.0.0 | 同 v2.1 + 统一错误协议 + chat-scraper 从零重写 + Windows 可用 + tests/ + 真冒烟 CI | 当前 |
