# ai-search-stack SOP（统一路由：怎么选 + 怎么用）

> **本文件是 ai-search-stack 唯一的 SOP**。按任务路由到 5 个工具。
> 各工具的部署 / 启动细节见 `tools/<tool>/README.md`。
> v3.0.0：经全面审计后重写——统一错误协议、模块名唯一化、chat-scraper 从零重建（v2 代码损失不可考）。

## 触发

任何 agent 需要"做 Web 搜索 / 抓取 / 验证"任务时。

## 步骤 0：识别任务类型（路由）

| 任务类型 | 选工具 | 备选 |
|---|---|---|
| 通用主题搜索（任何语言，国际内容） | `google-bridge` | `searxng`（本地实例） |
| 中国平台内容（知乎/B站/CSDN/豆瓣…16 站 + 任意域名） | `chat-scraper` | — |
| GitHub release / advisory / 仓库搜索 | `github` | — |
| 验证社区反应（高赞 = 真信号） | `hackernews` | — |
| CAPTCHA 兜底 / 不想装 Chrome | `searxng` | — |

**不知道怎么选**？默认 `google-bridge`（最广覆盖，需代理）。

引擎实测备忘：cn.bing 对纯 HTTP 客户端剥离 `site:`（勿用作站内搜索）；百度尊重 `site:` 但有软风控（chat-scraper 已内置节流+检测）；bilibili 有官方搜索 API（chat-scraper 专用通道）。 知乎有专用引擎链（官方 API 纯 HTTP 不可用，SearXNG→搜狗→百度自动降级，报错带 chain 字段）。 百度的软风控开关是请求头指纹（完整 Chrome Accept 必须保留，勿改回 */*）；百度双桶被锁时 14 平台自动切搜狗第三环。

## 步骤 1：部署工具

命令一律用 `python`（Windows 常见发行版无 `python3`）。

```bash
# google-bridge：真 Google，需 Chrome + 代理（mihomo 或任何 http/socks 代理）
cd tools/google-bridge
pip install -r requirements.txt
cp example_config.sh .env && vim .env   # 填 NO1_PROXY 等
source .env                             # 必须加载：search_helper 自己不读 .env
python search_helper.py                 # 默认已绑 127.0.0.1:18799
curl http://127.0.0.1:18799/health      # {"ok": true, ...}

# searxng：一条命令起本地实例（已配好 JSON 格式，公网实例默认禁 JSON 勿用）
cd tools/searxng/docker && docker compose up -d
curl "http://127.0.0.1:8888/search?q=test&format=json" | head -c 200

# hackernews / github：零部署，纯标准库，直接跑
# chat-scraper：pip install requests beautifulsoup4 后直接跑
```

## 步骤 2：调用工具

```bash
# google-bridge (HTTP；q 已 urlencode)
curl "http://127.0.0.1:18799/search?q=claude%20exploit&num=10&since=7d&vendor=claude&role=primary"

# searxng（本地实例）
python tools/searxng/searxng_client.py "claude exploit" --since 7d --vendor claude --role fallback

# hackernews
python tools/hackernews/hackernews_client.py "claude exploit" --since 7d --vendor claude --role verify

# github（CLI 已支持 --num/--vendor/--role；匿名 60 req/h，配 GITHUB_TOKEN 解除）
python tools/github/github_client.py releases "anthropics/claude-code" --num 5 --vendor claude --role verify
python tools/github/github_client.py advisories --ecosystem pip

# chat-scraper（CLI）
python tools/chat-scraper/bilibili_engine.py "机器学习 入门" --num 5
python tools/chat-scraper/search.py "Claude 漏洞" --platforms zhihu --vendor claude --role primary
# chat-scraper（库）
python -c "import sys; sys.path.insert(0, 'tools/chat-scraper'); from search import search; print(search('Claude 漏洞', platforms=['zhihu']))"
```

**模块名（v3 起唯一化，同进程可任意组合）**：`hackernews_client` / `github_client` / `searxng_client` / `search`（chat-scraper）。hackernews / github / searxng 三个轻客户端的旧 `from client import ...` 仍可用（各自 `client.py` 兼容 shim，打 DeprecationWarning）；**chat-scraper 无 client shim**——v3 从零重写，旧 `from client import search` 对 chat-scraper 不可用（实测 ModuleNotFoundError），用 `from search import search`。**同一进程禁止 import 多个不同工具的 `client`**——第二个会命中 sys.modules 缓存被静默劫持（v2 实测事故，详见 SKILL.md）。

## 步骤 3：统一参数与错误协议（所有工具）

任何 search 调用必传：

- `vendor`：主题分类（自定义，如 `claude` / `chatgpt` / `pip`）
- `role`：`primary`（主搜）/ `fallback`（兜底）/ `verify`（验证）
- `since`：`24h`（实时故障）/ `7d`（默认）/ `30d`（月度回顾）
  - 例外：`github` 工具无时间语义（release/advisory 按 API 全量返回，输出 `since: "all"`），必传的是 vendor/role

不传 → 指标归类为 "?"，无法算 vendor coverage / fallback 命中率。

**统一错误协议**（库默认 `on_error="report"`；CLI 出错向 stderr 打印并 exit 1）：

```python
results = search(q, ..., on_error="report")   # 默认
if results and "error" in results[0]:
    ...   # 这是故障（网络/风控/配置），不是"没搜到"
```

- `"report"`：返回 `[{"error": "...", "tool": ..., "query": ...}]`（风控类错误带 slug，如 `baidu_soft_blocked`）
- `"raise"`：抛异常
- `"empty"`：返回 `[]`（仅兼容旧脚本时用）

## 步骤 4：3 维 Quality Gate（过滤信号）

任何结果都要过 3 维过滤：

| 维度 | 拒绝 | 接受 |
|---|---|---|
| 来源 | 个人博客无源 / 营销聚合 / 第三方中转 | 官方域 / 技术社区 / 主流媒体 / 带 PoC |
| 完整性 | 标题党 / 纯吐槽 / 无复现步骤 | 5 步可复现 + 附代码 / 截图 / PoC |
| 时效 | > 7d 旧闻（除非深度研究） | 24h 硬事件 / 7d 稳定信号 |

任一维不过 → 丢弃。（先滤掉带 `error` 的记录再过滤。）

## 步骤 5：≥2 源验证（可选但推荐）

找到候选信号后，用其他工具验证（详见步骤 0 的"备选"列）：

- ≥2 个不同平台 / 工具的结果
- 至少 1 个是技术拆解
- 排除：单源 / 单平台 / 单 X 用户

## 失败回滚

| 失败现象 | 判别 | 回滚 |
|---|---|---|
| 结果带 `error`（或 CLI exit 1） | **故障**，不是没搜到 | 看报错：连接拒绝→起服务；`baidu_soft_blocked`/连接被 RST→等冷却/换工具；403 rate limit→配 token/等待 |
| google-bridge 返回 HTTP 503 `captcha_blocked` | Google 对出口 IP 风控（CAPTCHA 持续/锁定/限速） | 等 `NO1_COOLDOWN`~5 分钟冷却；切 searxng 兜底；低频使用 |
| google-bridge 返回 HTTP 502 `page_load_failed` | 页面没加载出来（网络/代理死） | 查代理（`NO1_PROXY`）、查 Chrome/chromedriver |
| 工具 A 没启 | /health 不通 | 启动工具 A（`tools/<tool>/README.md`） |
| 真 0 结果（无 error 字段，HTTP 200） | 查询真空 | 改 query（见 SKILL.md 模板）/ 改 since / 换工具 |
| 所有工具都失败 | 全部 error | 写"信号沉默"报告 + 退出 |

## 自动化检查

- [ ] 任务类型 → 工具映射（步骤 0 表格）已对照
- [ ] 工具部署完成（`curl /health` 200 或 import 成功）
- [ ] URL 参数 3 个（vendor / role / since）必传
- [ ] 错误记录（`error` 字段）与真空（0 结果）已区分
- [ ] 3 维 Quality Gate 过滤完成
- [ ] ≥2 源验证（如需要）

## 反面案例

- ❌ 把 `error` 记录当"0 结果"去改 query → 故障被掩盖（v2 的设计病，v3 已修复）
- ❌ 同进程 import 多个工具的 `client` shim → 静默劫持（用 `*_client` 真名）
- ❌ 高频连打百度 → 软风控占位页（chat-scraper 已内置 20s 节流，别绕过）
- ❌ 用公网 SearXNG 实例 → 默认禁 JSON，必失败（用 tools/searxng/docker 自建）
- ❌ 选错工具（找中国平台用 google-bridge）→ 索引差质量低
- ❌ 不传 vendor/role → 指标失真
- ❌ 单维判断（只看标题党）→ 误信营销
- ❌ 单源就推 → spam 风险
- ❌ 强行统一工具调用方式 → 失去每个工具的特色（**核心理念是 toolbox，不是 monolith**）
