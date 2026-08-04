# ai-search-stack

> **AI agent 搜索工具箱**：5 个独立工具 + 1 个统一 SOP + 1 个统一 SKILL。**不强行统一 API**，按任务路由。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tools: 5](https://img.shields.io/badge/tools-5-blue.svg)](tools/)
[![Tested 30+ days](https://img.shields.io/badge/tested-30%2B_days-brightgreen.svg)](CHANGELOG.md)

## 30 秒上手

1. **读 [SOP.md](SOP.md)** —— 唯一 SOP：怎么选工具 + 怎么用
2. **读 [SKILL.md](SKILL.md)** —— 唯一 SKILL：路由 + 组合模式 + 3 维信号过滤
3. **按 SOP 选工具** → 看 `tools/<tool>/README.md` 部署
4. **按 SKILL 调** → 选 1 个或组合多个

## 5 个独立工具

| 工具 | 解决什么 | 何时不用 |
|---|---|---|
| [`tools/google-bridge/`](tools/google-bridge/) | WebSearch 100% CAPTCHA（真 Google） | 找中国平台 / GitHub release |
| [`tools/searxng/`](tools/searxng/) | CAPCHA 兜底 / 不想装 Chrome | 默认（性能不如 google-bridge） |
| [`tools/hackernews/`](tools/hackernews/) | 验证社区反应（高赞 = 真信号）| 中文 / 非技术 |
| [`tools/github/`](tools/github/) | Release / Advisory / 仓库 | 非 GitHub |
| [`tools/chat-scraper/`](tools/chat-scraper/) | 32+ 中国平台（知乎/B站/小红书/微信公众号）| 国际主题 |

## 路由速查（详细见 SOP.md）

| 任务类型 | 选 | 备选 |
|---|---|---|
| 通用主题（任何语言） | google-bridge | searxng |
| 中国平台内容 | chat-scraper | — |
| GitHub release/CVE | github | — |
| 社区反应验证 | hackernews | — |
| CAPCHA 兜底 | searxng | — |

**不会选？** 默认 `google-bridge`（最广覆盖）。

## 设计哲学

**toolbox，不是 monolith**。5 工具独立 + 1 SOP + 1 SKILL：

- 5 工具独立：可单独装 / 升级 / 替换
- 1 SOP 统一：路由 + 怎么选 + 怎么用
- 1 SKILL 统一：组合模式 + 3 维信号过滤

**为什么不做统一 API**：
- 统一 API 难维护（用户原话）
- 每个工具有自己的部署 / 配置 / 优化方式
- 强行统一会丢失每个工具的特色
- 学习曲线低（按需看 1 个工具）

详见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 目录

```
ai-search-stack/
├── SOP.md                ← 唯一 SOP（怎么选 + 怎么用）
├── SKILL.md              ← 唯一 SKILL（路由 + 组合 + 3 维过滤）
├── README.md             ← 本文件
├── ARCHITECTURE.md       ← 设计理念
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── tools/
│   ├── google-bridge/    # Chrome 桥
│   │   ├── search_helper.py
│   │   ├── start_*.sh
│   │   ├── requirements.txt
│   │   └── README.md     # 工具自己的说明（不是 SOP）
│   ├── searxng/...
│   ├── hackernews/...
│   ├── github/...
│   └── chat-scraper/...
└── .github/workflows/test.yml
```

## 文档层次

| 文件 | 读谁 | 解决什么 |
|---|---|---|
| **SOP.md** | 任何 agent | **怎么选工具**（路由）+ **怎么用**（5 步流程）|
| **SKILL.md** | 任何 agent | **怎么组合**（4 模式）+ **3 维过滤** + **query 模板** |
| `tools/<tool>/README.md` | 部署该工具的人 | 工具自己的部署 / 启动 / 失败回滚 |
| `ARCHITECTURE.md` | 维护者 | 工具箱设计理念 |
| `CHANGELOG.md` | 任何 agent | 版本历史 |
| `CONTRIBUTING.md` | 贡献者 | 提 PR 流程 |

## 配套资源

- **方法论**：eventsys `npl.agent.场景SOPSkill.web_search`（Web 搜索通用 SOP+Skill）
- **实战案例**：no1_agent `DESIGN.md` / `CLAUDE.md`（内部）

## License

MIT
