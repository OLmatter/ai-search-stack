# searxng SKILL（使用技巧）

> 调用技巧：什么时候调、怎么调、结果怎么用。

## 场景

google-bridge 被 CAPTCHA 锁时（连续 2 个 0 命中）的**首选兜底**。也用于想要"多引擎合并结果"的场景。

## 做法

### 1. 作为 fallback（主用法）

```python
from client import search

# google-bridge 锁时切到 searxng
results = search(
    q="claude max exploit",
    num=10,
    since="7d",
    vendor="claude",
    role="fallback",  # ← 关键
    instance="http://127.0.0.1:8888",
)
```

### 2. 选合适的 instance

| 场景 | instance |
|---|---|
| 本地有 SearXNG Docker | `http://127.0.0.1:8888` |
| 临时 / 低频 | 公网 `https://searx.be` |
| 隐私要求高 | 自建 SearXNG（不记录 IP） |
| 高并发 | 自建 + nginx 限流 |

### 3. 选合适的 categories

| 类别 | 适用 |
|---|---|
| `general` | 默认，全搜 |
| `it` | IT / 技术 |
| `news` | 新闻 |
| `science` | 学术 |
| `social media` | 社交平台 |

### 4. 处理返回

SearXNG 返回 `[{title, url, content, engine, ...}, ...]`，注意：
- `engine` 字段是实际搜索的引擎（如 `bing` / `duckduckgo` / `brave`），可观察质量
- `content` 是 snippet，比 google-bridge 短
- 多引擎结果合并，**去重按 URL**

## 原因

- 公网元搜索，**无 CAPTCHA 风险**
- 多引擎结果去重 = 质量比单 Google 略高
- 轻量：纯标准库，零额外依赖
- 缺点：snippet 短；公网实例可能限流

## 案例

### 案例 1：CAPTCHA 兜底

```python
# google-bridge 返回 post_captcha_lockout_180s → 切 searxng
from searxng.client import search
results = search(q, num=10, since="7d", vendor=vendor, role="fallback")
```

### 案例 2：多引擎合并验证

```python
# 同一 query 跑 2 个不同 role
primary = search(q, role="primary", instance="http://localhost:8888")
verify = search(q, role="verify", instance="https://searx.be")
# 2 个独立 instance + 2 role = 高可信
```

## 配套工具

- ↗️ `google-bridge`（首选；被锁时切到本工具）
- ↗️ `hackernews`（更轻量兜底）
- ↗️ `github`（代码 / CVE 验证）