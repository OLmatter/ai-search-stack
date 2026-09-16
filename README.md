# ai-search-stack

> **AI agent 搜索工具箱**：5 个独立工具 + 1 个 MCP 接入层 + 1 个统一 SOP + 1 个统一 SKILL。**不强行统一 API**，按任务路由。

[![Release: v3.11.0](https://img.shields.io/badge/release-v3.11.0-brightgreen.svg)](https://github.com/OLmatter/ai-search-stack/releases/tag/v3.11.0)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python: 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Tests: 177 passing](https://img.shields.io/badge/tests-177%20passing-success.svg)](tests/)

**v3.11.0（2026-09-16）**：v3.0 全面审计大修之后连续十二轮迭代——B站搜索翻页、
doctor GitHub 检查修复、截断可见化（详见 [CHANGELOG.md](CHANGELOG.md)）。此前
十一轮：错误协议统一、
知乎官方 API 读取线 + 认证自愈、通用阅读器、微信/B站读取、全箱体检 doctor、
MCP stdio 接入层（14 工具）、文心 AI 搜索、cookie 寿命标定 + 定时续期、
B站字幕链路（实测未登录恒空，如实声明）、知乎回答列表登录门修复 + cursor
翻页（实测 403 现场复现，见 [CHANGELOG.md](CHANGELOG.md)）。本文档所有能力
声明以实测为准（依据见 [CHANGELOG.md](CHANGELOG.md)）。

## ✨ 特性

- 🔍 **中国平台聚合搜索**：16 站一个门面——bilibili 官方 API、知乎专用降级链
  （SearXNG → 搜狗 → 百度 site:）、百度桌面/移动双桶 + 搜狗第三环、
  文心 AI 搜索（AI 认可度 + 引用发现，低频线）
- 📖 **通用阅读器 `read(url)`**：知乎问题/回答/文章/评论走官方 API（含认证
  过期自愈），B站视频结构化读取（含 cid）+ 字幕读取链路（实测：未登录
  访客字幕列表恒为空，如实报告），外域 HTTP 直读 + 无头浏览器兜底
- 🌐 **国际搜索双通道**：google-bridge 真 Google（需 Chrome + 代理）、
  SearXNG 本地聚合（compose 一条命令起实例，JSON 已启用）
- 🐙 **开发者信号**：GitHub Releases / 安全通告（Advisories）、Hacker News
  社区反应验证，零部署
- 🔌 **MCP 接入层**：整个工具箱挂成 stdio MCP server，14 个工具任何 MCP
  客户端（ZCode / Claude Desktop）零代码直接调用
- 🩺 **doctor 一条命令体检**：巡检全部通道健康（SearXNG / 知乎 cookie /
  bilibili / 百度 / google-bridge / GitHub），故障退出码 1
- 🛡️ **统一错误协议**：出错返回带 `error` 字段的记录（slug 可诊断），永远
  不用静默 `[]` 把故障伪装成"没搜到"；模块名唯一，同进程组合不撞名

## 🚀 快速开始（3 步）

**第 1 步：克隆 + 装依赖**

```bash
git clone https://github.com/OLmatter/ai-search-stack.git
cd ai-search-stack
pip install "mcp>=2.1"        # MCP 接入层（只用 CLI 可跳过）
```

可选依赖按需装：知乎引导/文心/浏览器兜底线需 `pip install camoufox[geoip]`
（缺失时报错带安装指引）。

**第 2 步：挂进你的 MCP 客户端**（不想写代码，让 agent 直接调）

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

> Windows 下 `command` 建议用 python 绝对路径。重启客户端会话生效。

**第 3 步：体检 + 学路由**

```bash
python tools/doctor.py         # 全通道体检，确认环境就绪
```

然后读 [SOP.md](SOP.md)（怎么选工具）和 [SKILL.md](SKILL.md)（怎么组合）。
命令行用法见各 `tools/<tool>/README.md`。命令用 `python`（Windows 常见发行版
无 `python3`）。

## 🧰 工具矩阵

| 工具 | 解决什么 | 何时不用 |
|---|---|---|
| [`tools/chat-scraper/`](tools/chat-scraper/) | 中国平台内容：16 站搜索门面 + 知乎官方 API 读取（问题/回答/文章/评论）+ B站/微信读取 + 文心 AI 搜索 | 国际主题 |
| [`tools/google-bridge/`](tools/google-bridge/) | 真 Google（WebSearch 100% CAPTCHA），需 Chrome + 代理 | 找中国平台 / GitHub release |
| [`tools/searxng/`](tools/searxng/) | 兜底聚合搜索；`tools/searxng/docker` 一条命令起本地实例（已启用 JSON，公网实例默认禁 JSON 勿用） | 默认主搜 |
| [`tools/hackernews/`](tools/hackernews/) | 验证社区反应（高赞 = 真信号），零部署 | 中文 / 非技术 |
| [`tools/github/`](tools/github/) | Release / Advisory / 仓库，零部署（匿名 60 req/h） | 非 GitHub |
| [`tools/mcp_server.py`](tools/mcp_server.py) | 全工具箱暴露成 14 个 MCP tools（stdio） | 不用 MCP 客户端时 |
| [`tools/doctor.py`](tools/doctor.py) | 一条命令巡检全部通道健康 | — |

**实测状态**（详见各 README 与 CHANGELOG）：hackernews / github /
searxng(本地实例) / bilibili 引擎 / 知乎官方 API 读取线 / 文心引擎（1 发
实测成功）/ google-bridge（有代理时）均端到端实测出真实结果；百度引擎因软
风控按错误协议上报（`baidu_soft_blocked`），解析器经真实页面离线复验 19/19；
微信读取当前自动化环境受限（验证页如实上报，环境友好时可读）。

### 知乎 cookie 生命周期运维（v3.9）

实测标定（`state/cookie_lifetime_log.jsonl`，doctor --cookie-probe 周期探活）：
**知乎访客 cookie 寿命 <48h**（47.4h 即 403）。自愈链路：用时触发（API 遇
认证拒绝自动无头引导一次，~15s 延迟）。要让白天首次使用零延迟，用 cron 在
低峰窗口顺带续期：

```bash
# crontab：每日 9 点探活 + 标定；cookie 已过期且龄 >36h 时顺带无头续期一次
0 9 * * *  cd /path/to/ai-search-stack && python tools/doctor.py --cookie-probe --renew-if-older-than 36
```

- 不加 `--renew-if-older-than` = 纯标定观测（现行行为，expired 也 exit 0，
  不污染寿命分布数据）
- 加 `--renew-if-older-than H`：探活发现 expired 且龄 >H 才动用一次无头
  引导（36h 窗口配合每日一次 cron，续期必命中过期窗口）；续期结果记进
  标定日志同一读数行（`renew` / `renew_result` 字段），续期失败 exit 1
- `--renew-if-older-than` 只动 expired 读数：missing（没戴表）/ error
  （网络风控）不触发；探活期间自愈仍禁用，标定数据不被续期污染
- `zhihu_engine` 的知乎搜索链走 SearXNG 降级（不用 cookie），不受影响

### B站字幕读取：实测上限（v3.9，如实声明）

`fetch_subtitles(bvid)` / MCP `bilibili_subtitles` 已实现完整链路：
view API 拿 cid → `player/wbi/v2`（wbi 签名）→ 字幕 JSON 正文解析。
**但实测（2026-09-16，3 个视频验证，含标题自带"CC字幕更新完毕"、确有
CC 字幕的视频）：未登录访客请求字幕列表恒为空**——B 站仅向登录态
（SESSDATA）下发 `subtitle.subtitles`，手动上传 CC 亦不豁免。本工具不带
登录态，故当前 `subtitles` 恒为 `[]`（`has_subtitles=false` + note 说明）
——这是真实上限，不是故障；`cid` 补全（`fetch_video` 返回）照常可用，
接入 SESSDATA 后该链路可直接出数据（mock 全测）。

### 知乎回答列表：登录门修复 + 访客配额墙（v3.10，如实声明）

实测（2026-09-16，403 现场复现 + 同 cookie 对照实验）：知乎已把
**`include=data[*].content` 形态的 /feeds 回答列表请求整单拦截**——访客
一律 HTTP 403 code=40353（"请您登录后查看更多专业优质内容"），**全新
cookie 亦然**（自愈+重试无法救回，v3.4 起的旧形态已死）。v3.10 改用
**无 include 形态**（实测 200）：`author/excerpt/voteup/url` 输出契约
不变（excerpt 本就是主来源）。同 cookie 对照实测还发现**访客配额墙**：
部分问题服务端只放行前几条回答即 `is_end`（13 答问题实测仅回 3 条）——
按 is_end 如实返回，不报错、不伪装完整；要更多/全文走 `read_page`
（浏览器线）。新增服务端 cursor 翻页（num 上限 20→500，paging.next
字节一致直调，max_pages=50 护栏）。

## 路由速查（详细见 SOP.md）

| 任务类型 | 选 | 备选 |
|---|---|---|
| 通用主题（任何语言） | google-bridge | searxng（本地实例） |
| 中国平台内容 | chat-scraper | — |
| GitHub release/CVE | github | — |
| 社区反应验证 | hackernews | — |
| CAPTCHA 兜底 | searxng | — |

**不会选？** 默认 `google-bridge`（最广覆盖，需代理）。

## MCP 接入

`tools/mcp_server.py` 把整个工具箱包装成一个 **stdio MCP server**：任何 MCP
客户端（ZCode / Claude Desktop / 任何 agent 框架）无需写代码即可直接调用 14 个
工具。它只是**接入层**——每个工具原样透传参数给现有模块函数，不做内部 API 统一。

依赖：`pip install "mcp>=2.1"`（1.x SDK 亦兼容）。Windows 下 `command` 可用
anaconda python 的绝对路径。

**工具清单（14）**：

| MCP 工具 | 委托的模块函数 | 用途 | 耗时预期 |
|---|---|---|---|
| `china_search` | `chat-scraper/search.search` | 中国平台聚合搜索（知乎/B站/微信/百度16站） | bilibili 1-3s；百度有 ~20s 强制间隔，多平台串行按平台数放大 |
| `read_page` | `zhihu_content.read` | 通用阅读器：知乎 API 线 + B站/微信特化 + 外域 HTTP/无头浏览器兜底 | 可能起无头浏览器 10-15s |
| `zhihu_question` | `zhihu_content.fetch_question` | 知乎问题详情（官方 API） | 秒级 |
| `zhihu_answers` | `zhihu_content.fetch_answers` | 知乎回答列表（官方 API；cursor 翻页，num≤500；访客配额墙按 is_end 如实截断，见下） | 秒级~数秒（翻页按需） |
| `zhihu_article` | `zhihu_content.fetch_article` | 知乎专栏文章（官方 API） | 秒级 |
| `zhihu_comments` | `zhihu_content.fetch_comments` | 知乎评论（官方 comment_v5 API，含子评论展开、自动翻页） | 秒级~十秒级（评论多时翻页） |
| `bilibili_video` | `bilibili_engine.fetch_video` | B站视频结构化数据（官方 view API，含 cid） | 秒级 |
| `bilibili_subtitles` | `bilibili_engine.fetch_subtitles` | B站字幕链路（cid 补全 + player/wbi/v2；实测未登录恒空列表，见下） | 秒级（2 个请求） |
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
│   ├── mcp_server.py     # MCP stdio server（全工具箱暴露成 14 个 MCP tools）
│   ├── doctor.py         # 工具箱体检（一条命令巡检全部通道）
│   ├── google-bridge/    # Chrome 桥（search_helper v23.10，Windows/Linux 可用）
│   │   ├── search_helper.py
│   │   ├── start_*.sh
│   │   ├── requirements.txt
│   │   └── README.md
│   ├── searxng/          # 客户端 + docker/（compose + settings，JSON 已启用）
│   ├── hackernews/       # hackernews_client.py（+ client.py 兼容 shim）
│   ├── github/           # github_client.py（+ client.py 兼容 shim）
│   └── chat-scraper/     # v3 从零重写：baidu/bilibili/搜狗/知乎/文心引擎 + search 门面
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
