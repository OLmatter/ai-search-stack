# ai-search-stack

> AI agent 搜索栈：undetected-chromedriver 桥 + SearXNG fallback + 3 维 Quality Gate + 多源验证。
> 配合 [`eventsys.npl.agent.场景SOPSkill.web_search`](https://github.com/OLmatter) SOP+Skill 使用。

## 这是什么

一套**通用 Web 搜索基础设施**，专治"agent 用 WebSearch 100% CAPTCHA 0 命中"。

提供：
- **Chrome 桥**（`search_helper.py`）：undetected-chromedriver 跑真 Google，绕开数据中心 IP 封锁
- **SearXNG fallback**（公网元搜）：主工具被 CAPTCHA 锁时的兜底
- **HN Algolia / GitHub API** 兜底：技术社区和开源项目信号
- **mihomo 节点选择**（`auto_select_node.py`）：自动选最快 mihomo 节点绕开 IP 黑名单
- **3 维 Quality Gate**（来源 / 完整性 / 时效）：过滤信号 vs 噪音

## 适用场景

- ✅ 实时事件监控（cron 周期，发现 24h-7d 内的 exploit / outage / pricing 变化）
- ✅ 单次调研（"最近 ChatGPT / Claude / 国内厂商有什么漏洞"）
- ✅ 竞品分析 / 行业研究
- ✅ 任何需要"搜得到 + 搜得准 + 验得真"的 Web 任务

不适用：
- ❌ 用户给具体 URL 的抓取（用 curl 即可）
- ❌ 内部数据查询（用 SQL / API）
- ❌ 非搜索任务

## 架构

```
┌────────────────┐         ┌──────────────────┐
│  你的 agent    │ ──HTTP─→│  search_helper    │ (port 18799)
│ (cron/手动)    │         │  Chrome 桥        │
└────────────────┘         └──────────────────┘
                                     │
                                     ↓
                          ┌──────────────────┐
                          │  undetected-     │
                          │  chromedriver    │
                          │  + mihomo 代理    │
                          └──────────────────┘
                                     │
                                     ↓
                          ┌──────────────────┐
                          │  Google 真实结果  │
                          └──────────────────┘

fallback 链（CAPTCHA 锁时）：
SearXNG → HN Algolia → GitHub API → 官方 Status
```

## 快速开始

### 1. 前置依赖

```bash
# Chrome（Linux）
# https://googlechromelabs.github.io/chrome-for-testing/
CHROME_BIN=/path/to/chrome

# chromedriver
CHROMEDRIVER=/path/to/chromedriver

# Python 3.8+
pip install -r requirements.txt
```

### 2. 启动 Chrome 桥

```bash
# 配置环境变量
export NO1_CHROME_BIN=$CHROME_BIN
export NO1_CHROMEDRIVER_BIN=$CHROMEDRIVER
export NO1_CHROME_UDD=/path/to/chrome_user_data_dir
export NO1_PROXY=socks5://127.0.0.1:7897   # 或 http://your-proxy:port
export NO1_PORT=18799

# 启动（Linux 需要 Xvfb）
bash start_search_helper.sh

# 测试
curl -sS "http://127.0.0.1:18799/search?q=ENCODED&num=10&since=7d&vendor=test&role=primary"
```

### 3. 配 mihomo 代理（绕开数据中心 IP 封锁）

mihomo 是必须的——Google/Bing 把所有数据中心 IP 都封了。

```bash
# 装 mihomo（参考 mihomo 官方文档）
# https://github.com/MetaCubeX/mihomo

# 启动 mihomo
bash start_mihomo.sh   # 假设你已配好 config.yaml

# 测试
curl -x http://127.0.0.1:7897 https://www.google.com/ -I
```

### 4. 配 Quality Gate（信号 vs 噪音过滤）

`search_helper.py` 已经支持 3 维过滤：
- **来源**：官方域 / 技术社区 / 主流媒体 / 带 PoC 的安全研究（vs 个人博客 / 营销聚合）
- **完整性**：5 步可复现 + 附代码 / 截图 / PoC（vs 标题党 / 纯吐槽）
- **时效**：24h 硬事件 / 7d 稳定信号（vs > 7d 旧闻）

调用时通过 URL 参数控制（`vendor` / `role` 必传，详见 search_helper.py 顶部注释）。

## API

### `GET /search`

| 参数 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `q` | ✅ | - | URL-encoded 关键词 |
| `num` | - | 10 | 返回条数（10-20 推荐） |
| `since` | - | `7d` | 时间窗：`24h` / `7d` / `30d` / `90d` |
| `vendor` | ✅ | - | 主题分类（自定义，如 `claude` / `chatgpt` / `<任意>`） |
| `role` | ✅ | - | `primary` / `fallback` / `verify` |

**示例**：
```bash
# 主搜
curl "http://127.0.0.1:18799/search?q=ENCODED&num=10&since=7d&vendor=claude&role=primary"

# 兜底
curl "http://127.0.0.1:18799/search?q=ENCODED&num=10&since=7d&vendor=claude&role=fallback"

# 验证
curl "http://127.0.0.1:18799/search?q=ENCODED&num=5&since=24h&vendor=claude&role=verify"
```

### `GET /health`

```bash
curl "http://127.0.0.1:18799/health"
# {"ok": true}
```

### `GET /export?vendor=...&role=...`

导出 honeypot 日志（按 vendor / role 过滤）。

## URL 参数必传原则

**不传 `vendor` / `role` 是最常见错误**：
- 100% agent 跑通一段时间后发现没传
- 指标聚合时全归类为 "?"，白白浪费搜索算力
- 无法计算 vendor coverage / fallback hit rate / query role breakdown

**正确**：每次 search 都必传，agent 自己定义 vendor 分类。

## Query 设计原则

- ✅ **简单直接**：人话化，不要工程化组合
- ✅ **时间窗内**：用 since=7d 配合，不要在 query 里嵌日期
- ✅ **关键词具体到动作**：bug / 漏洞 / 涨价 / outage / 报错 / 复盘
- ✅ **多角度**：同一事件用 2-3 种说法搜（中文/英文/缩写/全称）
- ❌ `site:reddit.com/r/X Y Z 2026-07-29`（过度精确）
- ❌ `site:x.com "exact phrase" 2026`（带引号 + 日期）
- ❌ 任何 4+ token + site: 组合

## CAPTCHA 收敛规则

**触发**：连续 2 个 query 返回 CAPTCHA lockout 或 0 命中

**动作**：
- ❌ **不要**在主工具继续 retry 5+ 变体（实测浪费 60-180s 后 max-turns）
- ✅ **立即**切换到 fallback 链：SearXNG → HN Algolia → GitHub API → 官方 Status
- 每个 fallback 引擎最多 1 query
- 总 fallback 查询 ≤ 5

## 配置

所有配置走环境变量（不写死在代码里）：

| Env Var | 默认 | 说明 |
|---|---|---|
| `NO1_PORT` | `18799` | search_helper 监听端口 |
| `NO1_CHROME_BIN` | `/path/to/chrome` | Chrome 二进制路径 |
| `NO1_CHROMEDRIVER_BIN` | `/path/to/chromedriver` | chromedriver 路径 |
| `NO1_CHROME_UDD` | `/path/to/udd` | Chrome user-data-dir（持久化 cookies） |
| `NO1_PROXY` | `socks5://127.0.0.1:7897` | 代理 URL |
| `NO1_CAPTCHA_BACKOFF_BASE` | `60` | CAPTCHA 锁指数 backoff 基数（秒） |
| `NO1_HONEYPOT_LOG` | `/path/to/honeypot.jsonl` | 搜索日志（每条 query 一行） |

## 实测数据

**在 7×24 cron 跑 30+ 天的战绩**（来自 no1_agent 实例 A）：
- 27 条真事件已推送（OpenAI 40min outage、DS V4-Flash 29min 中断、Qwen3.8-Max 发布、Cursor CVE-2026-63093 等）
- 0 CAPTCHA 永久锁（auto_select_node 切 mihomo 节点解决）
- 命中率 ~60%（按 30+ 个搜索 / 周）

## 配套

| 资源 | 链接 |
|---|---|
| Web 搜索 SOP+Skill | eventsys `npl.agent.场景SOPSkill.web_search` |
| 历史教训 | no1_agent `DESIGN.md` / `CLAUDE.md`（内部） |

## License

MIT

## Credits

7×24 跑通的真实经验沉淀自 no1_agent（2026-07~08）。
提炼为通用工具后开源，方便其他 agent 复用。