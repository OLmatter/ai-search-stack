# ai-search-stack SOP（统一路由：怎么选 + 怎么用）

> **本文件是 ai-search-stack 唯一的 SOP**。按任务路由到 5 个工具。
> 各工具的部署 / 启动 细节见 `tools/<tool>/README.md`。

## 触发

任何 agent 需要"做 Web 搜索 / 抓取 / 验证"任务时。

## 步骤

### 步骤 0：识别任务类型（路由）

根据任务需求，对照下表选 1 个或多个工具：

| 任务类型 | 选工具 | 备选 |
|---|---|---|
| 通用主题搜索（任何语言） | `google-bridge` | `searxng` |
| 中国平台特定内容（知乎/B站/小红书/微信公众号）| `chat-scraper` | （无） |
| GitHub release / advisory / 仓库搜索 | `github` | （无） |
| 验证社区反应（高赞 = 真信号）| `hackernews` | （无） |
| CAPCHA 兜底 / 不想装 Chrome | `searxng` | （无） |

**不知道怎么选**？默认 `google-bridge`（最广覆盖）。

### 步骤 1：部署工具

每个工具有自己的部署流程。详见 `tools/<tool>/README.md`：

```bash
# 例：部署 google-bridge
cd tools/google-bridge
cat README.md  # 必读
pip install -r requirements.txt
cp example_config.sh .env
vim .env  # 填 Chrome / chromedriver / mihomo 路径
source .env
bash start_search_helper.sh
curl http://127.0.0.1:18799/health
```

### 步骤 2：调用工具

各工具调用方式：

```bash
# google-bridge (HTTP)
curl "http://127.0.0.1:18799/search?q=ENCODED&num=10&since=7d&vendor=claude&role=primary"

# searxng (Python)
python3 tools/searxng/client.py "claude max exploit" --since 7d --vendor claude --role fallback

# hackernews (Python)
python3 tools/hackernews/client.py "claude SEPA" --since 7d --vendor claude --role verify

# github (Python)
python3 tools/github/client.py releases "anthropics/claude-code"
python3 tools/github/client.py advisories --ecosystem pip

# chat-scraper (Python)
python3 -c "import sys; sys.path.insert(0, 'tools/chat-scraper'); from search import search; print(search(q='Claude 漏洞', platforms=['zhihu']))"
```

详见 `tools/<tool>/README.md` 的"快速开始"段。

### 步骤 3：URL 参数（所有工具通用）

任何 search 调用必传：

- `vendor`：主题分类（自定义，如 `claude` / `chatgpt` / `pip`）
- `role`：`primary`（主搜）/ `fallback`（兜底）/ `verify`（验证）
- `since`：`24h`（实时故障）/ `7d`（默认，2-3 天稳定信号）/ `30d`（月度回顾）

不传 → 指标归类为 "?"，无法算 vendor coverage / fallback 命中率。

### 步骤 4：3 维 Quality Gate（过滤信号）

任何结果都要过 3 维过滤：

| 维度 | 拒绝 | 接受 |
|---|---|---|
| 来源 | 个人博客无源 / 营销聚合 / 第三方中转 | 官方域 / 技术社区 / 主流媒体 / 带 PoC |
| 完整性 | 标题党 / 纯吐槽 / 无复现步骤 | 5 步可复现 + 附代码 / 截图 / PoC |
| 时效 | > 7d 旧闻（除非深度研究）| 24h 硬事件 / 7d 稳定信号 |

任一维不过 → 丢弃。

### 步骤 5：≥2 源验证（可选但推荐）

找到候选信号后，用其他工具验证（详见步骤 0 的"备选"列）：

- ≥2 个不同平台 / 工具的结果
- 至少 1 个是技术拆解
- 排除：单源 / 单平台 / 单 X 用户

## 失败回滚

| 失败现象 | 回滚 |
|---|---|
| 工具 A 没启 | 启动工具 A（`tools/<tool>/README.md`）|
| 工具 A 调用失败 | 切备选（步骤 0 表格）|
| 所有工具都失败 | 写"信号沉默"报告 + 退出 |
| 工具 A 输出 0 结果 | 改 query / 改 since / 换工具 |
| CAPTCHA 锁 | 工具 A 自身有 backoff + 切工具 B |

## 自动化检查

- [ ] 任务类型 → 工具映射（步骤 0 表格）已对照
- [ ] 工具部署完成（`curl /health` 200 或 Python import 成功）
- [ ] URL 参数 3 个（vendor / role / since）必传
- [ ] 3 维 Quality Gate 过滤完成
- [ ] ≥2 源验证（如需要）

## 反面案例

- ❌ 任务类型不清晰就硬上 google-bridge → 漏中国平台 / 漏 GitHub
- ❌ 选错工具（如找中国平台用 google-bridge）→ 索引差质量低
- ❌ 不传 vendor/role → 指标失真
- ❌ 单维判断（只看标题党）→ 误信营销
- ❌ 单源就推 → spam 风险
- ❌ 强行统一工具调用方式 → 失去每个工具的特色（**ai-search-stack 的核心理念是 toolbox，不是 monolith**）