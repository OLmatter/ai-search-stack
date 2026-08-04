# hackernews SKILL

> 调用技巧：什么时候用 HN 验证、用什么 query、怎么判断信号。

## 场景

找到可疑信号后，**用 HN 验证** 社区是否讨论。高赞 + 高评论 = 真信号。

## 做法

### 1. 作为 verify（主用法）

```python
from client import search

# google-bridge 找到疑似信号 → 用 HN 验证
results = search(
    q="claude max exploit 0 PHP",
    since="7d",
    vendor="claude",
    role="verify",  # ← 关键
)
```

### 2. 看 points + comments 判断信号强度

```python
for r in results:
    if r["points"] >= 100 and r["comments"] >= 50:
        # 高赞高评论 = 真信号
        ...
```

| points | comments | 信号强度 |
|---|---|---|
| <10 | <5 | 弱信号，可能是单人转推 |
| 10-100 | 5-50 | 中等 |
| 100-500 | 50-200 | **强信号** |
| >500 | >200 | 爆款事件，必跟 |

### 3. 选合适的 since

| 场景 | since |
|---|---|
| 24h 内的硬事件 | 24h |
| 7d 内的稳定信号 | 7d |
| 月度回顾 | 30d |

## 原因

- HN 用户是开发者，质量高，反营销
- 高赞 = 真信号（人工筛选）
- 公网 API，零依赖
- 缺点：纯英文 / 偏技术 / 中文内容少

## 案例

### 案例 1：验证 Claude 漏洞是否真

```python
# google-bridge 找到 "Claude SEPA 漏洞"
# → HN 验证
results = search("claude SEPA vulnerability", since="7d", vendor="claude", role="verify")
# 看 points >= 50 确认真信号
```

### 案例 2：找新模型社区反应

```python
results = search("Qwen3.8-Max", since="7d", vendor="qwen", role="verify")
# 国内模型，HN 可能讨论少 → 考虑降权或换工具
```

## 配套工具

- ↗️ `google-bridge`（找候选）
- ↗️ `searxng`（CAPTCHA 兜底）
- ↗️ `github`（代码验证）