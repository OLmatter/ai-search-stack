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
| [`tools/chat-scraper/`](tools/chat-scraper/) | 中国平台内容：bilibili 官方 API + 知乎搜索链与无头引导官方 API 内容读取 + 百度双桶（桌面/移动端）+搜狗兜底路由 16 站（低频） | 国际主题 |

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

**不想写代码、让 agent 直接调？** 把工具箱挂成 MCP server——见下方 [MCP 接入](#mcp-接入)。

## MCP 接入

`tools/mcp_server.py` 把整个工具箱包装成一个 **stdio MCP server**：任何 MCP
客户端（ZCode / Claude Desktop / 任何 agent 框架）无需写代码即可直接调用 13 个
工具。它只是**接入层**——每个工具原样透传参数给现有模块函数，不做内部 API 统一。

**启动（客户端里配置，无需手动跑）**：

```json
{
  "mcpServers": {
    "ai-search-stack": {
      "command": "python",
      "args": ["<仓库路径>/ai-search-stack/tools/mcp_server.py"]
    }
  }
}
```

依赖：`pip install "mcp>=2.1"`（1.x SDK 亦兼容）。Windows 下 `command` 可用
anaconda python 的绝对路径。

**工具清单（13）**：

| MCP 工具 | 委托的模块函数 | 用途 | 耗时预期 |
|---|---|---|---|
| `china_search` | `chat-scraper/search.search` | 中国平台聚合搜索（知乎/B站/微信/百度16站） | bilibili 1-3s；百度有 ~20s 强制间隔，多平台串行按平台数放大 |
| `read_page` | `zhihu_content.read` | 通用阅读器：知乎 API 线 + B站/微信特化 + 外域 HTTP/无头浏览器兜底 | 可能起无头浏览器 10-15s |
| `zhihu_question` | `zhihu_content.fetch_question` | 知乎问题详情（官方 API） | 秒级 |
| `zhihu_answers` | `zhihu_content.fetch_answers` | 知乎回答列表（官方 API） | 秒级 |
| `zhihu_article` | `zhihu_content.fetch_article` | 知乎专栏文章（官方 API） | 秒级 |
| `zhihu_comments` | `zhihu_content.fetch_comments` | 知乎评论（官方 comment_v5 API，含子评论展开、自动翻页） | 秒级~十秒级（评论多时翻页） |
| `bilibili_video` | `bilibili_engine.fetch_video` | B站视频结构化数据（官方 view API） | 秒级 |
| `hn_search` | `hackernews_client.search` | Hacker News 搜索 | 秒级 |
| `github_releases` | `github_client.get_releases` | 项目 release 列表 | 秒级（匿名 60 req/h） |
| `github_advisories` | `github_client.get_advisories` | 安全通告（按生态） | 秒级 |
| `searxng_search` | `searxng_client.search` | SearXNG 聚合搜索（默认本地 8888） | 秒级；实例未起返回可读错误 |
| `googlebridge_search` | HTTP 转发 `127.0.0.1:18799/search` | 真 Google（需先起 search_helper + Chrome 代理） | 数十秒级；服务未起返回可读错误 |
| `doctor` | `tools/doctor.py` check 体系 | 全通道体检，文本报告 | 5-10s |

**GitHub 为何拆两个工具**：MCP 的工具描述就是模型的路由提示。两个正交参数集
（`repo` vs `ecosystem`）合成一个带 `kind` 判别参数的工具，模型更容易填错参数；
分开后各自 schema 单一、描述聚焦，且与模块函数 1:1（零胶水）。

**耗时与超时（如实评估）**：
- 请给 `read_page` / `googlebridge_search` 设 **read_timeout ≥ 120s**（无头
  浏览器 / 隐身 Chrome 真搜 Google 都在这个量级）。
- **read_page 慢会不会卡死其他调用？不会。** stdio 是单连接，但 MCP JSON-RPC
  支持按 id 并发请求；mcp 2.x 对同步工具经 `anyio.to_thread.run_sync` 跑在
  工作线程（并发上限 = anyio 默认线程池 40），`tools/list`、其他工具调用不被
  阻塞。若客户端串行 await（多数简单客户端如此），卡顿感知在客户端侧，与
  server 无关。
- 客户端超时取消请求时，server 侧的浏览器进程可能残留（camoufox/chrome 孤儿
  进程，Windows 常见）；重启 server 进程即可回收。

**错误协议**：错误不抛异常——作为 `{"error": "<slug>: <详情>", "tool": ...,
"query": ...}` 嵌在返回 JSON 里，与「真空（0 结果）」可区分；未预期异常也被
server 兜底成同形态，不会炸连接。

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
│   ├── mcp_server.py     # MCP stdio server（v3.6，全工具箱暴露成 13 个 MCP tools）
│   ├── doctor.py         # 工具箱体检（一条命令巡检全部通道）
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
