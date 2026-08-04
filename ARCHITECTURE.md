# Architecture

> ai-search-stack v2.0 toolbox 设计理念。

## 核心论点

**不强行统一 API** —— 5 个独立工具 + 4 个元文档，按需选 + 按 SOP+Skill 用。

## 为什么 toolbox 而不是 monolith

| 维度 | Monolith（统一 API） | Toolbox（独立工具）|
|---|---|---|
| 维护成本 | 🟢 一处改 | 🟡 多处改 |
| 部署灵活 | ❌ 必须全装 | ✅ 按需装 |
| 工具替换 | ❌ 改 API 破坏兼容 | ✅ 换工具不动其他 |
| 故障隔离 | ❌ 一处挂全挂 | ✅ 单工具坏不影响其他 |
| 升级周期 | 🟡 同步 | ✅ 各工具独立升级 |
| 入门门槛 | 🟡 复杂 | 🟢 简单（按需学）|

**用户原话**："我知道要做一个统一的api很难，而且维护更难。所以我才想做成一套带sop和skill的工具"

## 5 个独立工具

| 工具 | 解决 | 状态 |
|---|---|---|
| `tools/google-bridge/` | WebSearch 100% CAPTCHA | v23.7（从 v1.0 移入）|
| `tools/searxng/` | CAPCHA 兜底 / 不想装 Chrome | 新增 |
| `tools/hackernews/` | 社区反应验证 | 新增 |
| `tools/github/` | Release / CVE | 新增 |
| `tools/chat-scraper/` | 32+ 中国平台 | 从 OLmatter/chat-scraper 合并入 |

## 4 个元文档

| 文档 | 用途 |
|---|---|
| `docs/choosing-tool.md` | 选工具 SOP（决策树 + 矩阵）|
| `docs/composition-patterns.md` | 工具组合 workflow（4 模式）|
| `docs/quality-gate.md` | 3 维信号过滤（来源/完整性/时效）|
| `docs/query-design.md` | query 怎么写（5 类模板 + 4 反模式）|

## 工具独立性的体现

| 维度 | 怎么独立 |
|---|---|
| 部署 | 每个工具有自己的 `requirements.txt` + `SOP.md` |
| 接口 | 每个工具有自己的 client / API（不一定统一）|
| 失败 | 工具 A 挂了不影响 B / C / D / E |
| 升级 | 各工具独立 commit / version |
| 学习 | 按需看 1 个工具的 SKILL，不用全学 |

## 依赖关系

```
docs/                    ← 无依赖
├── 纯 markdown，元 SOP/Skill

tools/google-bridge/     ← 依赖：Chrome + mihomo
tools/searxng/           ← 依赖：SearXNG 实例（本地 Docker 或公网）
tools/hackernews/        ← 依赖：零（公网 API）
tools/github/            ← 依赖：零（公网 API）
tools/chat-scraper/      ← 依赖：requests + bs4 + markdownify
```

工具之间**不互相依赖**。但 workflow 可组合（见 `docs/composition-patterns.md`）。

## 设计原则

1. **每个工具有完整 SOP**（5 要素：触发/步骤/失败回滚/自动化检查/反面）
2. **每个工具有完整 SKILL**（4 要素：场景/做法/原因/案例）
3. **不抽象"统一"工具**——强行抽象会损失每个工具的特色
4. **用元文档串联**——choosing-tool / composition-patterns / quality-gate / query-design
5. **可单独发布**——每个工具有自己的版本号（如 search_helper v23.7 独立升级）

## 复用边界

什么**包含**：
- 5 个独立工具 + 4 个元文档
- 每个工具的 SOP / SKILL / README
- 一键启动脚本

什么**不包含**（用户自己加）：
- Agent 调度框架
- Push 通知（TG / webhook）
- Dedup 库
- 监控告警

**理由**：ai-search-stack 是搜索工具箱，组合使用时自己选周边。
