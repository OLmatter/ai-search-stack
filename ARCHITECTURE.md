# Architecture

> ai-search-stack v2.1 toolbox 设计理念。

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
| `google-bridge` | WebSearch 100% CAPTCHA | 找中国平台 / GitHub release |
| `searxng` | CAPCHA 兜底 / 不想装 Chrome | 默认（性能不如 google-bridge）|
| `hackernews` | 验证社区反应 | 中文 / 非技术 |
| `github` | Release / Advisory / 仓库 | 非 GitHub |
| `chat-scraper` | 32+ 中国平台 | 国际主题 |

## 依赖关系

```
SOP.md / SKILL.md       ← 顶层路由（无依赖）

tools/google-bridge/    ← 依赖 Chrome + mihomo
tools/searxng/          ← 依赖 SearXNG 实例
tools/hackernews/       ← 依赖：零（公网 API）
tools/github/           ← 依赖：零（公网 API）
tools/chat-scraper/     ← 依赖 requests + bs4 + markdownify
```

工具之间**不互相依赖**。但组合模式可叠加（见 SKILL.md 的 4 模式）。

## 设计原则

1. **1 SOP + 1 SKILL 路由**——避免分散，让 agent 一处看全
2. **每个工具有完整 README**——只部署 1 个工具时不被全局文档干扰
3. **不抽象"统一"工具**——强行抽象会损失每个工具的特色
4. **可单独发布**——每个工具有自己的版本号（如 search_helper v23.7）
5. **可组合**——SKILL.md 给 4 个组合模式（找+验 / 跨语言 / 兜底链 / 监控+验证）

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
| v2.1.0 | 5 工具 + 1 顶层 SOP + 1 顶层 SKILL | 当前 |
