# chat-scraper

> **32+ 中国平台聚合 scraper** —— 知乎 / B站 / 小红书 / 微信公众号 / 豆瓣 / 简书 / 掘金 / CSDN / V2EX / 微博 ...

针对中国平台定制的高质量内容抓取，比 Google 搜索中国平台更准。

## 何时用

| 场景 | 适用 |
|---|---|
| 找中国平台（知乎/B站/小红书/微信公众号）特定内容 | ✅ **首选** |
| 跨平台聚合（同一 query 多平台同时搜） | ✅ 32+ 平台 |
| 抓取已分享链接（chatgpt.com/share / gemini.google.com/share）| ✅ 专门支持 |
| 通用主题搜索 | ❌ 改用 `google-bridge` |
| 找最新英文新闻 | ❌ 改用 `google-bridge` |
| 找 GitHub release | ❌ 改用 `github` |

## 平台覆盖

| 平台 | 抓取方式 | 状态 |
|---|---|---|
| 知乎 | API + HTML | ✅ |
| B站 | API | ✅ |
| 小红书 | HTML | ✅ |
| 微信公众号 | API | ✅ |
| 豆瓣 | API | ✅ |
| 简书 | HTML | ✅ |
| 掘金 | API | ✅ |
| CSDN | API | ✅ |
| V2EX | API | ✅ |
| 微博 | API | ✅ |
| ChatGPT Share | HTML 渲染 | ✅ |
| Gemini Share | HTML 渲染 | ✅ |
| 通用 HTML 文章 | HTML | ✅ |

详细测试状态见原 `chat-scraper/platform_tracker.md`（含每个平台的搜索 URL / 输出质量 / 已知问题）。

## 快速开始

### 1. 装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动 server

```bash
# server.py 是 MCP 协议入口（Claude Code / mcp client）
python3 -m server
```

或作为 Python 模块调用：

```python
from search import search as cs_search
results = cs_search(q="Claude 漏洞", platforms=["zhihu", "bilibili"])
```

### 3. （可选）MCP 集成

配 `~/.claude.json`：
```json
{
  "mcpServers": {
    "chat-scraper": {
      "command": "python3",
      "args": ["-m", "chat_scraper.server"],
      "cwd": "/path/to/ai-search-stack/tools/chat-scraper"
    }
  }
}
```

## 配套文档

- `SOP.md` — 部署 + 启动
- `SKILL.md` — 何时用 + 怎么调

## 关联

- ↔️ `google-bridge`（互补：国际/通用 vs 中国平台）
- ↔️ `searxng`（CAPTCHA 兜底，但中国平台搜不到）
- ↔️ `hackernews`（英文社区，中国内容少）

## 历史

chat-scraper 来自 `OLmatter/chat-scraper`，2026-08-05 合并入 `ai-search-stack` 作为 v2.0 的中国平台 expert。