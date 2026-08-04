# ai-search-stack

> **AI agent 搜索基础设施**：undetected-chromedriver Chrome 桥 + mihomo 节点切换 + CAPTCHA 收敛 + 多引擎 fallback。
> 一行命令起服务，`curl` 就能用，**任何 agent 都能集成**。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![Search Quality: 3D Gate](https://img.shields.io/badge/quality-3D_gate-green.svg)](ARCHITECTURE.md#quality-gate)
[![Tested 30+ days](https://img.shields.io/badge/tested-30%2B_days-brightgreen.svg)](CHANGELOG.md)

## 痛点

> "我让 agent 用 WebSearch 找点信息，结果 100% CAPTCHA，0 命中"

几乎所有 agent 跑搜索都栽这个跟头——**Google/Bing 把所有数据中心 IP 都封了**。WebSearch / WebFetch 工具走的是 Claude Code 自己的 IP，弹 CAPTCHA 是必然的。

`ai-search-stack` 解决这个问题：跑**真 Google 真实结果**（不是元搜索的污染版），自动绕 IP 黑名单，CAPTCHA 锁时立即切 fallback。

## 30 秒上手

```bash
git clone https://github.com/OLmatter/ai-search-stack
cd ai-search-stack
pip install -r requirements.txt
cp example_config.sh .env
# 编辑 .env 填你的 Chrome / chromedriver / mihomo 路径
source .env
bash start_search_helper.sh

# 另一终端测试
curl "http://127.0.0.1:18799/search?q=ENCODED&num=10&since=7d&vendor=claude&role=primary"
```

## 核心能力

- **真 Google 结果** —— undetected-chromedriver + 住宅代理，零 CAPTCHA（默认）
- **mihomo 节点切换** —— 54+ 节点轮换，CAPTCHA 锁时自动选最优
- **CAPTCHA 收敛** —— 锁时立即切 fallback，不让 agent 卡死
- **3 维 Quality Gate** —— 来源 / 完整性 / 时效过滤信号 vs 噪音
- **多源验证** —— 任意 query 都能做 ≥2 独立源确认
- **可观测** —— 每 query 一行 JSON 日志（vendor / role / 耗时 / 结果数）
- **零外部依赖** —— 只需 Chrome + chromedriver + mihomo（都在你本地）

## 架构

```
Agent → search_helper.py (port 18799)
              ↓
      undetected-chromedriver + Chrome (headed, persistent UDD)
              ↓
          mihomo 代理 (port 7897, 54+ nodes)
              ↓
          Google 真结果
```

详见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## API

### `GET /search`

| 参数 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `q` | ✅ | - | URL-encoded 关键词 |
| `num` | - | 10 | 返回条数 |
| `since` | - | `7d` | `24h` / `7d` / `30d` / `90d` |
| `vendor` | ✅ | - | 主题分类（自定义） |
| `role` | ✅ | - | `primary` / `fallback` / `verify` |

```bash
# 主搜
curl "http://127.0.0.1:18799/search?q=ENCODED&num=10&since=7d&vendor=claude&role=primary"

# 兜底（CAPTCHA 锁时）
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

导出 honeypot 日志（按 vendor / role 过滤），用于指标聚合。

## 集成示例（任何语言）

### Python

```python
import requests
r = requests.get('http://localhost:18799/search', params={
    'q': 'claude max 白嫖',
    'num': 10,
    'since': '7d',
    'vendor': 'claude',
    'role': 'primary',
})
results = r.json()['results']
```

### Bash

```bash
results=$(curl -sS "http://localhost:18799/search?q=claude%20max%20%E7%99%BD%E5%AB%96&num=10&since=7d&vendor=claude&role=primary")
```

### Node.js

```javascript
const axios = require('axios');
const r = await axios.get('http://localhost:18799/search', {
  params: {q: 'claude max exploit', num: 10, since: '7d', vendor: 'claude', role: 'primary'}
});
```

## 实战数据

7×24 cron 跑了 30+ 天的战绩（来自 no1_agent 实例 A）：

| 指标 | 数值 |
|---|---|
| 真事件推送数 | 27 条 |
| CAPTCHA 永久锁 | 0 次 |
| 命中率 | ~60% |
| 平均单次 search 耗时 | 5-15s |
| 实例内存占用 | ~500MB |

代表性事件：OpenAI 40min outage、DS V4-Flash 29min 中断、Qwen3.8-Max 发布、Cursor CVE-2026-63093 等。

## 文档

- [ARCHITECTURE.md](ARCHITECTURE.md) —— 架构 + 设计决策
- [CHANGELOG.md](CHANGELOG.md) —— 版本历史
- [CONTRIBUTING.md](CONTRIBUTING.md) —— 贡献指南
- [LICENSE](LICENSE) —— MIT

## 配套资源

- **方法论**：eventsys `npl.agent.场景SOPSkill.web_search`（Web 搜索通用 SOP+Skill）

## 适用 vs 不适用

✅ 适用：
- 实时事件监控（cron 周期，发现 24h-7d 内的 exploit / outage / pricing）
- 单次调研（"最近有什么漏洞"）
- 竞品分析 / 行业研究
- 任何需要"搜得到 + 搜得准 + 验得真"的 Web 任务

❌ 不适用：
- 用户给具体 URL 的抓取（用 curl）
- 内部数据查询（用 SQL / API）
- 非搜索任务

## License

MIT —— 任意使用 / 修改 / 商用 / 二次发布，保留版权声明即可。

## Credits

7×24 跑通的真实经验沉淀自 no1_agent（2026-07~08）。
提炼为通用工具后开源，方便其他 agent 复用。
