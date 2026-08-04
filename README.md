# ai-search-stack

> **AI agent 搜索工具箱**：5 个独立工具 + 4 个元文档。**不强行统一 API**，按需选工具，按 SOP+Skill 用。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tools: 5](https://img.shields.io/badge/tools-5-blue.svg)](tools/)
[![Tested 30+ days](https://img.shields.io/badge/tested-30%2B_days-brightgreen.svg)](CHANGELOG.md)

## 痛点

> "我让 agent 用 WebSearch 找点信息，结果 100% CAPTCHA，0 命中"
> "我让 agent 找知乎/B站内容，结果 google 索引差"
> "我让 agent 看 GitHub release，结果搜不到 changelog"

`ai-search-stack` v2.0 提供 **5 个独立工具** 解决不同问题，每个带自己的 SOP+Skill：

| 工具 | 解决什么 |
|---|---|
| [`google-bridge`](tools/google-bridge/) | WebSearch 100% CAPTCHA |
| [`searxng`](tools/searxng/) | 不想装 mihomo+Chrome 时的兜底 |
| [`hackernews`](tools/hackernews/) | 验证社区反应（高赞 = 真信号）|
| [`github`](tools/github/) | 找 release / advisory / 仓库 |
| [`chat-scraper`](tools/chat-scraper/) | 32+ 中国平台（Google 索引差）|

**设计哲学**：

- ❌ **不**强行统一 API（API 难维护）
- ✅ **每个工具独立**：有自己的 SOP（怎么部署）和 SKILL（怎么用）
- ✅ **可单独用**：不需要装全部，按需选
- ✅ **可单独换**：工具坏了换一个，其他不受影响
- ✅ **可组合用**：参考 `docs/composition-patterns.md` 的 4 个工作流

## 30 秒上手

```bash
# 选你需要的工具，按 SOP 装
# 例：装 google-bridge
cd tools/google-bridge
pip install -r requirements.txt
cp example_config.sh .env && vim .env  # 填 Chrome / chromedriver / mihomo 路径
source .env
bash start_search_helper.sh

# 例：装 searxng（公网元搜，零依赖）
cd tools/searxng
python3 client.py "claude max exploit" --since 7d --vendor claude --role fallback
```

详见各工具的 `README.md` / `SOP.md` / `SKILL.md`。

## 4 个元文档

- [`docs/choosing-tool.md`](docs/choosing-tool.md) —— **怎么选工具**（决策树 + 决策矩阵）
- [`docs/composition-patterns.md`](docs/composition-patterns.md) —— **怎么组合用**（4 个工作流：找+验、跨语言、兜底链、监控+验证）
- [`docs/quality-gate.md`](docs/quality-gate.md) —— **3 维信号过滤**（来源/完整性/时效）
- [`docs/query-design.md`](docs/query-design.md) —— **query 怎么写**（5 类模板 + 4 反模式）

## 工具对比

| 工具 | 解决 | 部署成本 | 适用 |
|---|---|---|---|
| google-bridge | WebSearch CAPTCHA | 🟡 中（Chrome + mihomo）| 通用主题（任何语言）|
| searxng | 不装本地 Chrome | 🟢 低（公网实例即可）| CAPCHA 兜底 |
| hackernews | 社区反应验证 | 🟢 零 | 英文技术社区 |
| github | Release / CVE | 🟢 零（公网 API）| GitHub 项目 |
| chat-scraper | 中国平台 | 🟡 中（Python + cookies）| 知乎/B站/小红书/微信公众号 |

## 架构

```
docs/                            ← 元文档（横切）
├── choosing-tool.md              # 选工具 SOP
├── composition-patterns.md       # 组合 workflow
├── quality-gate.md               # 信号过滤
└── query-design.md               # query 设计

tools/                            ← 独立工具箱
├── google-bridge/                # Chrome 桥
│   ├── search_helper.py          # 核心代码
│   ├── start_*.sh                # 启动器
│   ├── README.md / SOP.md / SKILL.md
│   └── example_config.sh
├── searxng/                      # 公网元搜
├── hackernews/                   # HN Algolia
├── github/                       # GitHub API
└── chat-scraper/                 # 32+ 中国平台
```

详见 [`ARCHITECTURE.md`](ARCHITECTURE.md)。

## 配套资源

- **方法论**：eventsys `npl.agent.场景SOPSkill.web_search`（Web 搜索通用 SOP+Skill）
- **实战案例**：no1_agent `DESIGN.md` / `CLAUDE.md`（内部）

## 适用 vs 不适用

✅ 适用：
- 任何"搜索 / 调研 / 抓取"任务
- 实时事件监控
- 多源验证

❌ 不适用：
- 用户给具体 URL 的抓取（用 curl）
- 内部数据查询（用 SQL / API）
- 非搜索任务

## License

MIT —— 任意使用 / 修改 / 商用 / 二次发布，保留版权声明即可。

## Credits

7×24 跑通的真实经验沉淀自 no1_agent（2026-07~08）。
v2.0 toolbox 设计：每个工具独立 + 自带 SOP/Skill，**避免统一 API 维护噩梦**。
