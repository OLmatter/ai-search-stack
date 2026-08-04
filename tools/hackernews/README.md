# hackernews

> **HackerNews Algolia 客户端** —— 验证社区反应。

HackerNews 是开发者社区，**反应 = 信号**：高赞 / 高评论 = 真实值得关注的事件。

## 何时用

| 场景 | 适用 |
|---|---|
| 验证社区是否讨论某事件 | ✅ **首选** |
| 找权威开发者观点 | ✅ HN 用户质量高 |
| 找技术新闻（不是营销） | ✅ HN 反营销 |
| 找中文社区 | ❌ 改用 `chat-scraper` |
| 找最新模型发布 | ⚠️ 部分会讨论，但 github 更全 |

## 快速开始

```bash
# 零依赖，标准库即可
python3 client.py "claude max exploit" --since 7d --vendor claude --role verify
```

或 Python：

```python
from client import search
results = search(q="claude max exploit", since="7d", vendor="claude", role="verify")
for r in results:
    print(f"[{r['points']}↑ {r['comments']}💬] {r['title']}")
    print(f"  {r['url']}")
```

## 配套文档

- `SOP.md` — 零依赖部署 + 调用
- `SKILL.md` — 何时用 + 怎么用

## 关联

- ↔️ `google-bridge`（找到信号后用 HN 验证）
- ↔️ `searxng`（CAPTCHA 兜底链）
- ↔️ `github`（代码 / CVE 验证）