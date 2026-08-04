# Architecture

> 为什么这套搜索栈要这样设计。每个决策都对应一个具体失败场景。

## 设计目标

1. **真 Google 结果**（不是元搜索的污染版）
2. **绕开数据中心 IP 黑名单**（不靠 VPN 切换）
3. **可观测**（每次 query 都有日志 + vendor 分类 + role 区分）
4. **可降级**（CAPTCHA 锁时自动切 fallback，不让 agent 卡死）
5. **可复用**（任何 agent 拿过来配 3 个环境变量就能跑）

## 核心组件

```
┌─────────────────────────────────────────────────────────────┐
│  Agent (cron / 手动 / 任何语言)                              │
│  curl "http://localhost:18799/search?q=...&vendor=...&role=..."│
└─────────────────────────────────────────────────────────────┘
                          │ HTTP
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  search_helper.py (port 18799)                              │
│  - 解析 query 参数                                          │
│  - 调 undetected-chromedriver                               │
│  - honeypot 日志（每 query 一行 JSON）                       │
│  - CAPTCHA backoff（指数退避）                               │
│  - /export 端点导出日志                                     │
└─────────────────────────────────────────────────────────────┘
                          │ CDP
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  undetected-chromedriver + Chrome (headed)                  │
│  - 真人 fingerprint (canvas / webgl / audio context)        │
│  - 持久 UDD (cookies + trust)                               │
│  - Xvfb 虚拟显示 (Linux headless)                          │
└─────────────────────────────────────────────────────────────┘
                          │ SOCKS5/HTTP
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  mihomo 代理 (port 7897)                                    │
│  - 多出口节点（54+ 节点）                                   │
│  - auto_select_node.py 自动选最快                           │
│  - 切换节点绕 IP 黑名单                                     │
└─────────────────────────────────────────────────────────────┘
                          │
                          ↓
                  Google 真服务器
```

## 关键决策

### 为什么 undetected-chromedriver 而不是 Selenium

| 维度 | undetected-chromedriver | Selenium + Chrome |
|---|---|---|
| 反检测 | ✅ 改 patches bypass bot detection | ❌ 容易被识别 |
| 真 Google 结果 | ✅ | ❌ 频繁 CAPTCHA |
| 速度 | ✅ 直接 CDP，零 Selenium 开销 | 慢 |
| 维护 | 活跃 | 活跃但反检测差 |

**结论**：对 Google 真结果这一目标，undetected-chromedriver 是唯一靠谱选择。

### 为什么 mihomo 而不是 VPN / 单代理

| 维度 | mihomo 多节点 | 单 VPN / 代理 |
|---|---|---|
| IP 黑名单绕过 | ✅ 切节点秒级 | ❌ IP 死就只能换 VPN |
| 延迟 | 自动选最优 | 看运营商脸色 |
| 成本 | 开源自建 | 商用贵 |
| 可观测 | ✅ 节点级 metrics | 黑盒 |

**结论**：频繁被 CAPTCHA 时，能切节点 = 业务不中断。

### 为什么 7d 默认而不是 24h

| 场景 | 24h | 7d |
|---|---|---|
| 实时故障（CVE / status） | ✅ 命中 | ✅ 命中 |
| 漏洞复盘 | ❌ 通常 2-3 天后才稳定 | ✅ 命中 |
| 定价变化 | ❌ 慢 | ✅ 命中 |
| 总体命中率 | 30-40% | 50-60% |

**结论**：24h 太严，漏 2-3 天前的真信号。7d 是甜点。

### 为什么 URL 必传 `vendor` + `role`

**没传的后果**（实测 100% 跑通一段时间后才发现）：
- vendor 字段全归类为 "?"，vendor coverage 指标失真
- 主搜 / 兜底 / 验证 混淆，无法算 fallback 命中率
- 多 vendor 搜索时无法判断"哪个 vendor 命中率高"

**结论**：参数必传是"指标可信"的唯一保障。

### 为什么 CAPTCHA 锁要立即切 fallback 而不是 retry

**实测数据**（2026-08-04 22:03）：
- 在 Chrome 桥连续 retry 8 个变体，浪费 162s 后 max-turns
- 期间完全没有切 fallback
- 结果 1 个 search 都没完成

**结论**：CAPTCHA 锁是有状态的，retry 不会解。立即切 fallback 是唯一出路。

## 数据流（详细）

### 一次 search 调用

1. Agent 发 `GET /search?q=ENCODED&num=10&since=7d&vendor=claude&role=primary`
2. search_helper 解析 query → 调用 `search_google_stealth(q, since, vendor, role)`
3. undetected-chromedriver 调 Chrome → Chrome 通过 mihomo 出 Google
4. Google 返回 HTML → search_helper 解析 → 提取 title/url/snippet
5. 写 honeypot 日志：`{kind: search, q, num, since, vendor, role, count, captcha, ts}`
6. 返回 JSON `{ok, count, results}`

### 一次 CAPTCHA 锁 + fallback

1. Chrome 返回 "unusual traffic from your computer" → 触发 CAPTCHA 检测
2. search_helper 写 honeypot: `{kind: search_skipped, reason: post_captcha_lockout_180s}`
3. 返回 HTTP 503 + 锁定 180s（backoff 指数增长）
4. Agent 收到 503 → 切 fallback:
   - SearXNG `http://localhost:8888/search?q=...`
   - HN Algolia `http://hn.algolia.com/api/v1/search?query=...`
   - GitHub API `https://api.github.com/repos/.../releases`
5. fallback 命中 → 验证（`role=verify`）→ 推

## 模块边界

| 模块 | 职责 | 不做 |
|---|---|---|
| `search_helper.py` | HTTP 桥 + Chrome 调用 + honeypot | 不做 push（TG） / 不做 dedup / 不做 cron |
| `auto_select_node.py` | mihomo 节点选最优 | 不做代理本身（用 mihomo） |
| `start_search_helper.sh` | 启动 + 守护 | 不做 agent 调度 |
| `start_mihomo.sh` | mihomo 启动 | 不做节点选择（用 auto_select_node） |

**设计原则**：单一职责，每个文件做一件事。

## 复用边界

什么**包含**在这个项目：
- 搜索基础设施（search_helper + mihomo 控制）
- 配套脚本（auto_select_node + start）
- 配置文件模板

什么**不包含**（其他项目）：
- Agent 调度（用 nohup / cron / supervisor）
- 推送（用 tg_send / webhook）
- 去重（用 SQLite / Redis）
- 监控（用 prometheus / grafana）

**理由**：ai-search-stack 是搜索栈，不是 agent 框架。组合使用时自己选 agent 框架。