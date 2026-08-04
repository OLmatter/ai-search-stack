# 工具组合模式（workflow）

> 怎么把多个工具组合起来用。本文档给 4 个最常见的工作流。

## 模式 1：找 + 验

**场景**：先在 google-bridge 找候选，再用其他工具验证。

```python
from google_bridge.client import search as google_search
from hackernews.client import search as hn_search
from github.client import get_advisories

# 1. google-bridge 找候选
candidates = google_search("claude exploit", num=10, since="7d", vendor="claude", role="primary")

# 2. hackernews 验证
for c in candidates[:3]:
    hn = hn_search(c["title"], since="7d", vendor="claude", role="verify")
    if any(r["points"] >= 50 for r in hn):
        # HN 高赞 = 真信号
        ...

# 3. github 看 advisory 详情
advisories = get_advisories("pip", num=20, vendor="pip", role="verify")
```

## 模式 2：跨语言对比

**场景**：同一事件国际 vs 国内反应对比。

```python
from google_bridge.client import search as google_search
from chat_scraper.search import search as china_search

# 国际
intl = google_search("claude SEPA vulnerability", since="7d", vendor="claude", role="primary")
# 国内
china = china_search(q="Claude SEPA 漏洞", platforms=["zhihu", "weibo"])
# 合并去重
```

## 模式 3：CAPTCHA 兜底链

**场景**：google-bridge 被 CAPTCHA 锁，自动切 searxng。

```python
import time
from google_bridge.client import search as google_search
from searxng.client import search as searxng_search

def robust_search(q, vendor, since="7d"):
    # 1. 先 google-bridge
    results = google_search(q, num=10, since=since, vendor=vendor, role="primary")
    if results and not any("captcha" in r.get("error", "") for r in results):
        return results

    # 2. 切 searxng
    time.sleep(1)
    return searxng_search(q, num=10, since=since, vendor=vendor, role="fallback")
```

## 模式 4：监控 + 验证

**场景**：cron 周期监控 + 异常时用多源验证。

```python
# cron 30min 跑一次
# 1. 监控：找新信号
new = google_search("...", role="primary")

# 2. dedup：去重
known = load_dedup_db()
fresh = [n for n in new if n["url"] not in known]

# 3. 验证：≥2 源
verified = []
for f in fresh:
    sources = [f["url"]]
    hn = hn_search(f["title"], role="verify")
    if hn and hn[0]["points"] >= 20:
        sources.append(hn[0]["url"])
    gh = get_releases(...)  # 如适用
    if len(sources) >= 2:
        verified.append({**f, "sources": sources})

# 4. 推 / 记
push(verified)
```

## 失败回滚

- 工具 1 失败 → 工具 2 兜底（按工具选择矩阵）
- 工具 2 也失败 → 工具 3 兜底
- 全失败 → 写"信号沉默"报告

## 反面案例

- ❌ 一次跑 5 工具并行 → 慢 + 限流
- ❌ 不用 role 区分 → 主搜/验证混淆，指标失真
- ❌ 不去重 → 同一事件推 3 次