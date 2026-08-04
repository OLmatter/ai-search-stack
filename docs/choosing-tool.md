# 怎么选工具（SOP）

> ai-search-stack v2.0 提供 5 个独立搜索工具。怎么选？本 SOP 教。

## 决策树

```
需要搜索什么？
├─ 通用主题（任何语言）
│   └─ 用 google-bridge（首选）
│
├─ 中国平台特定内容（知乎/B站/小红书/微信公众号）
│   └─ 用 chat-scraper
│
├─ 找 GitHub 项目 / release / CVE
│   └─ 用 github
│
├─ 验证社区反应（高赞 = 真信号）
│   └─ 用 hackernews
│
└─ CAPTCHA 锁 / 不想装 mihomo+Chrome
    └─ 用 searxng（公网元搜）
```

## 决策矩阵

| 需求 | 首选 | 备选 |
|---|---|---|
| 任何主题的"广度"搜索 | google-bridge | searxng |
| 中国平台"深度"内容 | chat-scraper | （无备选） |
| 找 GitHub release / advisory | github | （无备选） |
| 验证社区讨论强度 | hackernews | google-bridge |
| 找最新 status 故障 | google-bridge (since=24h) | github status API |
| 找 CVE 详情 | github advisories | searxng |
| 找 ChatGPT/Gemini 分享对话 | chat-scraper | （无备选） |
| 找 HackerNews 评论 | hackernews (tags=comment) | （无备选） |

## 反面案例

- ❌ 搜"知乎"内容用 google-bridge → Google 索引差，不如 chat-scraper
- ❌ 搜 GitHub release 用 google-bridge → 不如 github 直接
- ❌ 找社区反应用 searxng → 看不到 points/comments
- ❌ 一次 query 跑所有 5 个工具 → 太慢 + 限流

## 完整工作流（多工具组合）

详见 [`composition-patterns.md`](composition-patterns.md)。