# google-bridge SKILL（使用技巧）

> 调用技巧：什么时候调、怎么调、怎么判断结果真假。

## 场景

agent 需要做"通用主题搜索"时——任何主题、任何语言。**最广覆盖**的搜索工具。

## 做法

### 1. 必传 vendor + role

```bash
# ❌ 错（实测 100% agent 这么干）
curl "http://127.0.0.1:18799/search?q=test&num=10&since=7d"

# ✅ 对
curl "http://127.0.0.1:18799/search?q=test&num=10&since=7d&vendor=claude&role=primary"
```

**为什么必传**：
- `vendor` = 主题分类（自定义，如 `claude` / `chatgpt` / `<任何>`）。不传 → 指标归类为 "?"，vendor coverage 失真
- `role` = `primary`（主搜）/ `fallback`（兜底）/ `verify`（验证）。不传 → 无法区分主搜效率和验证质量

### 2. since 默认 7d，不是 24h

| 场景 | since | 原因 |
|---|---|---|
| 实时故障（CVE / status） | 24h | 事件一过没价值 |
| 通用情报 | **7d** | 漏洞/exploit 信号 2-3 天才稳定 |
| 历史分析 | 30d / 90d | 按需 |

**反模式**：默认 24h → 漏 2 天前的真信号。

### 3. query 越简单越准

```bash
# ❌ 错（99% 返 0）
curl "...search?q=site:reddit.com+r/X+claude+max+20x+exploit+2026+july&..."

# ✅ 对
curl "...search?q=claude+max+白嫖&since=7d&..."
```

**反模式**：
- ❌ `site:...`（限制引擎去索引别的域，命中率低）
- ❌ 引号（精确匹配但召回率低）
- ❌ 具体日期（Google 算法已做时间过滤）
- ❌ 4+ token 组合

### 4. CAPTCHA 锁 → 立即切其他工具

**触发**：连续 2 个 query 返回 CAPTCHA lockout 或 0 命中

**动作**：
- ❌ **不要**在 google-bridge 继续 retry 5+ 变体（实测浪费 162s）
- ✅ 立即切到 `searxng`（公网元搜）或 `hackernews` / `github`

### 5. 结果真假判断

3 维 Quality Gate（详见 `../../docs/quality-gate.md`）：
- **来源**：官方域 / 技术社区 / 主流媒体 / 带 PoC（vs 个人博客 / 营销聚合）
- **完整性**：5 步可复现 + 附代码 / 截图（vs 标题党 / 纯吐槽）
- **时效**：24h 硬事件 / 7d 稳定信号（vs > 7d 旧闻）

## 原因

google-bridge 之所以是通用主力：
- 真 Google 结果（不是元搜索的污染版）
- 任何语言 / 任何主题
- 配合 mihomo 几乎不会 CAPTCHA
- 唯一缺点：CAPTCHA 锁时切换慢（要换节点 1-2s）

## 案例

### 案例 1：找最新 Claude 漏洞

```bash
curl "http://127.0.0.1:18799/search?q=claude+max+白嫖&num=10&since=7d&vendor=claude&role=primary"
```

### 案例 2：找 ChatGPT 8 月 outage

```bash
# 中文
curl "...search?q=ChatGPT+宕机&since=24h&vendor=openai&role=primary"
# 英文
curl "...search?q=ChatGPT+outage+status&since=24h&vendor=openai&role=verify"
```

### 案例 3：找国内厂商动态

```bash
curl "...search?q=智谱+GLM+新模型&since=7d&vendor=zhipu&role=primary"
curl "...search?q=文心一言+漏洞&since=7d&vendor=wenxin&role=primary"
```

### 案例 4：CAPTCHA 锁时切 fallback

```bash
# google-bridge 锁 → 切 searxng
curl "http://127.0.0.1:8888/search?q=ENCODED&format=json&categories=general"
```

## 配套工具

- ↗️ `searxng` —— google-bridge 锁时的兜底
- ↗️ `hackernews` —— 社区反应验证
- ↗️ `github` —— CVE / 代码验证
- ↗️ `chat-scraper` —— 32+ 中国平台（替代 google-bridge 搜特定平台时）