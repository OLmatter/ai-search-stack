# ai-search-stack SKILL（统一路由：判断 + 组合）

> **本文件是 ai-search-stack 唯一的 SKILL**。5 工具的路由 + 4 组合模式。
> 配合 [`SOP.md`](SOP.md) 使用。

## 场景

agent 拿到一个"搜索 / 调研 / 验证"任务，不知道用哪个工具、怎么调、什么时候停、怎么判断信号真假。

## 做法

### 核心论点

**ai-search-stack 是 toolbox，不是 monolith**。5 个独立工具，按任务路由，按需组合。

| 工具 | 解决什么 | 何时**不**用 |
|---|---|---|
| `google-bridge` | WebSearch 100% CAPTCHA（真 Google，需代理） | 找中国平台 / GitHub release |
| `searxng` | CAPTCHA 兜底 / 不想装 Chrome（`tools/searxng/docker` 一条命令起本地实例） | 默认主搜（聚合引擎，结果质量视后端）|
| `hackernews` | 验证社区反应 | 中文内容 / 非技术 |
| `github` | Release / CVE / 仓库 | 非 GitHub |
| `chat-scraper` | 中国平台内容（bilibili 官方 API + 百度 site: 路由 13 站） | 国际主题（Google 索引更好）|

> **模块名规则（v3）**：同一 Python 进程组合多工具时，import 真名 `hackernews_client` / `github_client` / `searxng_client`。旧的 `from client import ...` 是兼容 shim，**同进程禁止 import 两个不同工具的 `client`**（sys.modules 缓存会静默劫持第二个，v2 实测事故）。

### 4 个组合模式

**模式 1：找 + 验（最常见）**

```python
# 1. google-bridge 找候选
from urllib.request import urlopen
import json
candidates = json.loads(urlopen(
    "http://127.0.0.1:18799/search?q=claude+exploit&num=10&since=7d&vendor=claude&role=primary"
).read())["results"]

# 2. hackernews 验证（points >= 50 = 真信号）
import sys; sys.path.insert(0, "tools/hackernews")
from hackernews_client import search as hn
for c in candidates[:3]:
    hn_results = hn(c["title"], since="7d", vendor="claude", role="verify")
    hn_results = [r for r in hn_results if "error" not in r]   # 先滤故障记录
    if any(r["points"] >= 50 for r in hn_results):              # points 恒为 int（v3 修复 null 崩溃）
        print(f"VERIFIED: {c['title']}")
```

**模式 2：跨语言对比（国际 vs 国内）**

```python
import json
from urllib.request import urlopen
import sys; sys.path.insert(0, "tools/chat-scraper")
from search import search as china

# 国际
intl = json.loads(urlopen(
    "http://127.0.0.1:18799/search?q=claude+SEPA+vulnerability&num=10&since=7d&vendor=claude&role=primary"
).read())["results"]

# 国内
china_results = china(q="Claude SEPA 漏洞", platforms=["zhihu", "weibo"])

# 合并去重
```

**模式 3：CAPTCHA 兜底链（自动降级）**

```python
import time
import json
from urllib.request import urlopen
from urllib.parse import quote

def robust_search(q, vendor, since="7d"):
    # 1. google-bridge（timeout 要给足：服务端有冷却/反 CAPTCHA 路径，15s 会在重负载路径必超时；
    #    q 必须 quote——带空格的裸 URL 会抛 InvalidURL，别用裸 except 吞掉它）
    try:
        r = json.loads(urlopen(
            f"http://127.0.0.1:18799/search?q={quote(q)}&num=10&since={since}"
            f"&vendor={vendor}&role=primary", timeout=90).read())
        if r.get("results"):
            return r["results"]
    except Exception as e:
        print(f"[robust_search] google-bridge failed: {e}")  # 降级要可见，别静默

    # 2. searxng 兜底（本地实例）
    time.sleep(1)
    import sys; sys.path.insert(0, "tools/searxng")
    from searxng_client import search as searxng
    return searxng(q, num=10, since=since, vendor=vendor, role="fallback")
```

**模式 4：监控 + 验证（cron 用）**

```python
# 1. 找
results = robust_search("claude exploit", vendor="claude", since="7d")

# 2. dedup（load_dedup_db 是你自己的去重库，非本工具箱提供）
known = load_dedup_db()
fresh = [r for r in results if r["url"] not in known]

# 3. 多源验证
import sys; sys.path.insert(0, "tools/hackernews")
from hackernews_client import search as hn
verified = []
for f in fresh:
    hn_results = hn(f["title"], since="7d", vendor="claude", role="verify")
    hn_results = [r for r in hn_results if "error" not in r]
    if any(r["points"] >= 20 for r in hn_results):
        verified.append(f)

# 4. 推 / 记
if verified:
    push(verified)  # 你自己的 push 函数
```

### URL 参数必传（所有 search 工具）

```bash
# ❌ 错
curl "...search?q=test&num=10&since=7d"

# ✅ 对
curl "...search?q=test&num=10&since=7d&vendor=claude&role=primary"
```

| 参数 | 取值 | 不传后果 |
|---|---|---|
| `vendor` | 主题分类（自定义）| 指标归 "?"，vendor coverage 失真 |
| `role` | `primary` / `fallback` / `verify` | 主搜 / 验证混淆 |
| `since` | `24h` / `7d` / `30d` | 默认 `7d`（CLI 与库一致；传 None/"" 表示不过滤） |

### Query 设计（5 类模板 + 4 反模式）

**5 类模板**：

| 信号类型 | 中文 query | 英文 query |
|---|---|---|
| 支付漏洞 / exploit | `<产品> 白嫖 / 支付漏洞 / 油猴` | `<vendor> payment exploit / vulnerability` |
| 服务中断 / outage | `<厂商> 崩了 / 宕机 / 服务中断` | `<vendor> down / outage / incident` |
| 定价变化 | `<厂商> 涨价 / 降价 / 调价 / 改版` | `<vendor> pricing change / update` |
| 新模型 / 产品 | `<厂商> 新模型 / 发布 / 公测` | `<vendor> new model / release / launch` |
| 安全漏洞 | `<产品> CVE / RCE / 沙盒逃逸` | `<product> CVE / advisory / RCE` |

**4 反模式**：
- ❌ `site:...`（**对 google-bridge**：限制引擎去索引别的域，效果差。注：chat-scraper 的中国平台搜索内部就是靠百度 `site:` 实现的，平台路由已自动处理，无需手写）
- ❌ `site:x.com "exact phrase" 2026`（带引号 + 日期）
- ❌ `<event> july 29 2026 specific incident`（具体日期）
- ❌ 4+ token 组合

### 3 维 Quality Gate（信号过滤）

| 维度 | 拒绝 | 接受 |
|---|---|---|
| 来源 | 个人博客 / 营销聚合 / 中转 | 官方域 / 技术社区 / 带 PoC |
| 完整性 | 标题党 / 纯吐槽 | 5 步可复现 + 附代码 |
| 时效 | > 7d 旧闻 | 24h 硬事件 / 7d 稳定信号 |

任一维不过 → 丢弃。

## 原因

**为什么不统一 API**：
- 统一 API 难维护（用户原话）
- 每个工具有自己的部署 / 配置 / 优化方式
- 强行统一会丢失每个工具的特色

**为什么 toolbox 模式**：
- 按需装（不需要 Chrome 就别装 google-bridge）
- 独立升级（chat-scraper 改了不影响 google-bridge）
- 故障隔离（一个挂了不影响其他）
- 学习曲线低（按需看 1 个工具的 README）

## 案例

### 案例 1：找 Claude SEPA 漏洞 + 验证

```python
import json
from urllib.request import urlopen
from urllib.parse import quote
import sys; sys.path.insert(0, "tools/hackernews")
from hackernews_client import search as hn_search

# 1. google-bridge 找
resp = urlopen("http://127.0.0.1:18799/search?q=" + quote("claude SEPA 漏洞")
               + "&num=10&since=7d&vendor=claude&role=primary", timeout=90)
candidates = json.loads(resp.read())["results"]

# 2. hackernews 验证（过滤故障记录后再判阈值）
for c in candidates:
    hn = hn_search(c["title"], since="7d", vendor="claude", role="verify")
    hn = [r for r in hn if "error" not in r]
    if hn and hn[0]["points"] >= 50:
        # 真信号
        ...
```

### 案例 2：找 ChatGPT Plus 0 PHP 漏洞（中国平台）

```python
import sys; sys.path.insert(0, "tools/chat-scraper")
from search import search
results = search(q="ChatGPT Plus 0 PHP", platforms=["zhihu", "v2ex"])
# 直接看中国平台，不用 google-bridge
```

### 案例 3：找最新 claude-code release

```bash
python tools/github/github_client.py releases "anthropics/claude-code" --num 5
# 看 tag_name + body（changelog）判断是否真更新
```

### 案例 4：找 Qwen3.8-Max 发布（国内厂商 + 验证）

```python
import sys; sys.path.insert(0, "tools/chat-scraper"); sys.path.insert(1, "tools/github")
from search import search
from github_client import get_releases

# 1. chat-scraper 国内搜索
china = search(q="Qwen3.8-Max 发布", platforms=["zhihu", "weibo"])

# 2. github 验证
gh_releases = get_releases("QwenLM/Qwen", num=3, vendor="qwen", role="verify")
```

## 反面案例

- ❌ 任务不清晰就硬上 google-bridge → 漏中国平台 / GitHub
- ❌ 选错工具（找中国平台用 google-bridge）→ 索引差质量低
- ❌ 不传 vendor/role → 指标失真
- ❌ 强行把 5 工具封装成统一 API → 失去 toolbox 优势
- ❌ 单维判断（只看标题）→ 误信营销
- ❌ 单源就推 → spam 风险
- ❌ 不会组合（只用 1 个工具）→ 漏多角度信号

## 沉淀指引

跑通新场景后：
- 新的 query 模板 → 追加到本文件"Query 设计"段
- 新的组合模式 → 追加到本文件"4 个组合模式"段
- 新的 Quality Gate 维度 → 追加到本文件"3 维 Quality Gate"段
- 工具改动 → 改 `tools/<tool>/README.md`（不是本文件）