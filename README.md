# ai-search-stack

> **AI agent 搜索工具箱**：5 个独立工具 + 1 个统一 SOP + 1 个统一 SKILL。**不强行统一 API**，按任务路由。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tools: 5](https://img.shields.io/badge/tools-5-blue.svg)](tools/)
[![v3.0.0](https://img.shields.io/badge/v3.0.0-audited%20%26%20rewritten-brightgreen.svg)](CHANGELOG.md)

> **v3.0.0（2026-09-09）**：经全面审计后大修——统一错误协议、跨平台修复（Windows 不再 import 即崩）、chat-scraper 从零重写（v2 代码以 NUL 空壳入库、不可恢复）、searxng 提供开箱即用的本地实例。本文档所有能力声明以实测为准。

## 30 秒上手

1. **读 [SOP.md](SOP.md)** —— 唯一 SOP：怎么选工具 + 怎么用 + 错误协议
2. **读 [SKILL.md](SKILL.md)** —— 唯一 SKILL：路由 + 组合模式 + 3 维信号过滤
3. **按 SOP 选工具** → 看 `tools/<tool>/README.md` 部署
4. **按 SKILL 调** → 选 1 个或组合多个

命令用 `python`（Windows 常见发行版无 `python3`）。

## 5 个独立工具

| 工具 | 解决什么 | 何时不用 |
|---|---|---|
| [`tools/google-bridge/`](tools/google-bridge/) | 真 Google（WebSearch 100% CAPTCHA），需 Chrome + 代理 | 找中国平台 / GitHub release |
| [`tools/searxng/`](tools/searxng/) | 兜底聚合搜索；`tools/searxng/docker` 一条命令起本地实例（已启用 JSON，公网实例默认禁 JSON 勿用） | 默认主搜 |
| [`tools/hackernews/`](tools/hackernews/) | 验证社区反应（高赞 = 真信号），零部署 | 中文 / 非技术 |
| [`tools/github/`](tools/github/) | Release / Advisory / 仓库，零部署（匿名 60 req/h） | 非 GitHub |
| [`tools/chat-scraper/`](tools/chat-scraper/) | 中国平台内容：bilibili 官方 API + 知乎专用引擎链（SearXNG→搜狗→百度）+ 百度双桶（桌面/移动端）+搜狗兜底路由 16 站（低频） | 国际主题 |

**实测状态**（详见各 README 与 CHANGELOG）：hackernews / github / searxng(本地实例) / bilibili 引擎 / google-bridge（有代理时）均已端到端实测出真实结果；百度引擎因软风控按错误协议上报（`baidu_soft_blocked`），解析器经真实页面离线复验 19/19。

## 路由速查（详细见 SOP.md）

| 任务类型 | 选 | 备选 |
|---|---|---|
| 通用主题（任何语言） | google-bridge | searxng（本地实例） |
| 中国平台内容 | chat-scraper | — |
| GitHub release/CVE | github | — |
| 社区反应验证 | hackernews | — |
| CAPTCHA 兜底 | searxng | — |

**不会选？** 默认 `google-bridge`（最广覆盖，需代理）。

## 设计哲学

**toolbox，不是 monolith**。5 工具独立 + 1 SOP + 1 SKILL：

- 5 工具独立：可单独装 / 升级 / 替换
- 1 SOP 统一：路由 + 怎么选 + 怎么用 + 统一错误协议
- 1 SKILL 统一：组合模式 + 3 维信号过滤

**为什么不做统一 API**：
- 统一 API 难维护（用户原话）
- 每个工具有自己的部署 / 配置 / 优化方式
- 强行统一会丢失每个工具的特色
- 学习曲线低（按需看 1 个工具）

**v3 新增的两条底线**：
- **统一错误协议**：出错返回带 `error` 字段的记录（或 exit 1），永远不用静默 `[]` 把故障伪装成"没搜到"
- **模块名唯一**：`hackernews_client` / `github_client` / `searxng_client`，同进程组合不撞名（v2 同名 `client.py` 会静默劫持，实测事故）

详见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 目录

```
ai-search-stack/
├── SOP.md                ← 唯一 SOP（怎么选 + 怎么用 + 错误协议）
├── SKILL.md              ← 唯一 SKILL（路由 + 组合 + 3 维过滤）
├── README.md             ← 本文件
├── ARCHITECTURE.md       ← 设计理念 + 引擎选型实测记录
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── tests/                ← 离线单测（含 NUL 空壳/撞名防回归）+ 真冒烟
├── tools/
│   ├── google-bridge/    # Chrome 桥（search_helper v23.9，Windows/Linux 可用）
│   │   ├── search_helper.py
│   │   ├── start_*.sh
│   │   ├── requirements.txt
│   │   └── README.md
│   ├── searxng/          # 客户端 + docker/（compose + settings，JSON 已启用）
│   ├── hackernews/       # hackernews_client.py（+ client.py 兼容 shim）
│   ├── github/           # github_client.py（+ client.py 兼容 shim）
│   └── chat-scraper/     # v3 从零重写：baidu_engine + bilibili_engine + search 门面
└── .github/workflows/test.yml   # 编译/NUL 检测/离线单测/服务健康/真冒烟
```

## 文档层次

| 文件 | 读谁 | 解决什么 |
|---|---|---|
| **SOP.md** | 任何 agent | **怎么选工具**（路由）+ **怎么用**（5 步流程）+ 错误协议 |
| **SKILL.md** | 任何 agent | **怎么组合**（4 模式）+ **3 维过滤** + **query 模板** |
| `tools/<tool>/README.md` | 部署该工具的人 | 工具自己的部署 / 启动 / 失败回滚 |
| `ARCHITECTURE.md` | 维护者 | 工具箱设计理念 + 引擎选型实测依据 |
| `CHANGELOG.md` | 任何 agent | 版本历史 |
| `CONTRIBUTING.md` | 贡献者 | 提 PR 流程 |

## 配套资源

- **方法论**：eventsys `npl.agent.场景SOPSkill.web_search`（Web 搜索通用 SOP+Skill）
- **实战案例**：no1_agent `DESIGN.md` / `CLAUDE.md`（内部）

## License

MIT
