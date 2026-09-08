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

本机用 `python`（不是 `python3`；本机 python = 3.12 anaconda）。零依赖，标准库即可。

```bash
python hackernews_client.py "claude exploit" --since 7d --vendor claude --role verify

# comment 模式（points 为 JSON null 时自动兜底为 0，不会 TypeError）
python hackernews_client.py "claude exploit" --tags comment --vendor claude --role verify
```

或 Python（**模块名是 `hackernews_client`，不是 `client`**）：

```python
from hackernews_client import search
results = search(q="claude max exploit", since="7d", vendor="claude", role="verify")
for r in results:
    print(f"[{r['points']}↑ {r['comments']}💬] {r['title']}")
    print(f"  {r['url']}")
```

## 错误协议（on_error）

**默认 `on_error="report"`：出错绝不返回 `[]` 伪装成功**，而是返回单元素列表：

```python
[{"error": "URLError: <urlopen error timed out>", "tool": "hackernews", "query": "claude exploit"}]
```

调用方检查 `results[0].get("error")` 即可区分**故障**与**真空（0 结果）**。

| on_error | 出错行为 |
|---|---|
| `"report"`（默认） | 返回 `[{"error": ..., "tool": "hackernews", "query": ...}]` |
| `"raise"` | 直接抛异常 |
| `"empty"` | 兼容旧行为：返回 `[]`（故障与真空不可区分，不推荐） |

CLI 出错时向 stderr 打印 error 并 `sys.exit(1)`，不会输出伪装成功的 `[]`。

三个工具（hackernews / github / searxng）协议一致，可组合时统一用
`result[0].get("error")` 判故障。

## 模块名与兼容 shim

- 唯一模块名是 **`hackernews_client.py`**，与 `github_client` / `searxng_client` 同进程组合不会撞名。
- 旧的 `from client import search` 仍可用（`client.py` 是兼容 shim，会触发 `DeprecationWarning`）。
- 但**禁止在同进程 import 多个工具目录的 `client`**——三个目录模块同名，
  第二次 import 会命中 `sys.modules` 缓存返回错误模块（这就是模块改唯一名的原因）。

## 配套文档

- `SOP.md` — 零依赖部署 + 调用
- `SKILL.md` — 何时用 + 怎么用

## 关联

- ↔️ `google-bridge`（找到信号后用 HN 验证）
- ↔️ `searxng`（CAPTCHA 兜底链）
- ↔️ `github`（代码 / CVE 验证）
