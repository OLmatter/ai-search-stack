# chat-scraper SKILL

> 调用技巧：什么时候用、怎么选平台、怎么解读结果。

## 场景

需要中国平台（知乎/B站/小红书/微信公众号）特定内容时。比 Google 搜这些平台更准。

## 做法

### 1. 选平台

```python
from search import search

# 指定平台（推荐：避免一次 32 平台聚合慢 + 限流）
results = search(
    q="Claude 漏洞",
    platforms=["zhihu", "bilibili", "weibo"],  # ← 选 2-3 个相关平台
)
```

| 主题 | 推荐平台 |
|---|---|
| 技术讨论 | zhihu, juejin, csdn, v2ex |
| 视频内容 | bilibili |
| 生活 / 消费 | xiaohongshu, douban, dazhibo |
| 新闻 / 资讯 | weibo, zhihu |
| AI 对话分享 | chatgpt_share, gemini_share |
| 微信公众号 | weixin (需 API 凭证) |

### 2. 跨语言

```python
# 英文 query 也能搜中国平台（结果可能少）
results = search(q="Claude vulnerability", platforms=["zhihu"])
# 中文 query 命中率高
results = search(q="Claude 漏洞", platforms=["zhihu"])
```

### 3. 与其他工具组合

```python
# 组合 1：找跨平台话题
google_results = google_search("claude exploit")  # 国际讨论
china_results = chat_scraper_search("Claude 漏洞", platforms=["zhihu"])  # 国内讨论
# 合并去重

# 组合 2：找特定作者
google_results = google_search("site:zhihu.com 某某 回答")
zhihu_results = chat_scraper_search(q="", author="某某", platforms=["zhihu"])
```

## 原因

- 中国平台内容 Google 索引差（反爬 + 中文 SEO 不友好）
- 平台定制 scraper 拿真实数据（不是 SEO 摘要）
- 32 平台一站式（不用分别写 scraper）
- 缺点：单平台可能限流 / cookies 失效

## 案例

### 案例 1：找知乎 Claude 漏洞讨论

```python
results = search(q="Claude SEPA 漏洞", platforms=["zhihu"])
# 返回知乎问题列表
```

### 案例 2：找 B站 AI 教程

```python
results = search(q="Claude Code 教程", platforms=["bilibili"])
# 返回视频列表
```

### 案例 3：抓 chatgpt 分享链接

```python
# 抓 https://chatgpt.com/share/xxx
result = scrape_url("https://chatgpt.com/share/xxx", platform="chatgpt_share")
```

## 配套工具

- ↗️ `google-bridge`（国际/通用主题）
- ↔️ `searxng`（CAPTCHA 兜底，但中国平台搜不到）
- ↔️ `hackernews`（英文社区）