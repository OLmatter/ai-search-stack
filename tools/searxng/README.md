# searxng

> **SearXNG 元搜索客户端** —— 公网元搜，作为 google-bridge 兜底。

当 google-bridge 被 CAPTCHA 锁时，用 SearXNG 兜底。**纯标准库 + HTTP，零依赖**。

## 何时用

| 场景 | 适用 |
|---|---|
| google-bridge 被 CAPTCHA 锁 | ✅ **首选兜底** |
| 想要多个搜索引擎结果合并 | ✅ SearXNG 默认聚合 |
| 没有本地 mihomo / Chrome 环境 | ✅ 公网实例即可（`searx.be` / `searx.tiekoetter.com`） |
| 想要真 Google 100% 全结果 | ❌ 改用 `google-bridge` |
| 平台特定搜索（知乎/B站/微信公众号） | ❌ 改用 `chat-scraper` |

## 快速开始

### 1. 跑 SearXNG 实例

```bash
# 方式 A：用公网实例（无需本地部署）
# 选一个 https://searx.be / https://searx.tiekoetter.com 等

# 方式 B：本地跑 Docker（推荐）
docker run -d --name searxng -p 8888:8080 \
  -e SEARXNG_SECRET=changeme \
  searxng/searxng
```

### 2. 装依赖

```bash
pip install -r requirements.txt  # 实际无依赖，跳过也行
```

### 3. 用

```python
from client import search

results = search(
    q="claude max exploit",
    num=10,
    since="7d",
    vendor="claude",
    role="fallback",
    instance="http://127.0.0.1:8888",  # 或公网
)
for r in results:
    print(r["title"], r["url"])
```

或 CLI：

```bash
python3 client.py "claude max exploit" --since 7d --vendor claude --role fallback
```

## 配套文档

- `SOP.md` — 部署 SearXNG + 调客户端
- `SKILL.md` — 调用技巧 + CAPTCHA 兜底链

## 关联

- ↔️ `google-bridge`（首选，被锁时用 searxng 兜底）
- ↔️ `hackernews`（更轻的兜底）
- ↔️ `github`（代码 / CVE 验证）