# searxng

> **SearXNG 元搜索客户端** —— 公网元搜，作为 google-bridge 兜底。

当 google-bridge 被 CAPTCHA 锁时，用 SearXNG 兜底。**纯标准库 + HTTP，零依赖**。

## 何时用

| 场景 | 适用 |
|---|---|
| google-bridge 被 CAPTCHA 锁 | ✅ **首选兜底** |
| 想要多个搜索引擎结果合并 | ✅ SearXNG 默认聚合 |
| 有本地 Docker / 自建实例 | ✅ 本地 8888 最稳 |
| 想要真 Google 100% 全结果 | ❌ 改用 `google-bridge` |
| 平台特定搜索（知乎/B站/微信公众号） | ❌ 改用 `chat-scraper` |

> ⚠️ **实例必须允许 JSON 输出**：SearXNG 默认 settings 只允许 HTML，
> 需在 `settings.yml` 的 `search.formats` 里加 `json`，否则请求 `format=json`
> 会失败/返回 HTML，解析走错误协议。实测公网 `searx.be` 的 JSON 未启用（返回 HTML），
> 公网实例请自建或挑选确认开了 JSON 的。

## 快速开始

本机用 `python`（不是 `python3`；本机 python = 3.12 anaconda）。

### 1. 跑 SearXNG 实例

```bash
# 本地 Docker（推荐）
docker run -d --name searxng -p 8888:8080 \
  -e SEARXNG_SECRET=changeme \
  searxng/searxng
# 记得给该实例开 JSON 输出（settings.yml: search.formats: [html, json]）
```

### 2. 装依赖

```bash
pip install -r requirements.txt  # 实际无依赖，跳过也行
```

### 3. 用

Python（**模块名是 `searxng_client`，不是 `client`**）：

```python
from searxng_client import search

results = search(
    q="claude max exploit",
    num=10,
    since="7d",                        # 默认 "7d"；传 None 或 "" 表示不过滤时间
    vendor="claude",
    role="fallback",
    instance="http://127.0.0.1:8888",
)
for r in results:
    print(r["title"], r["url"])
```

或 CLI：

```bash
python searxng_client.py "claude max exploit" --since 7d --vendor claude --role fallback
# 不过滤时间：
python searxng_client.py "claude max exploit" --since ""
```

`since` 函数默认与 CLI 默认已统一为 `"7d"`；未知值（如 `3w`）会向 stderr 打一行警告
并按不过滤时间处理。

## 错误协议（on_error）

默认 `on_error="report"`：**出错绝不返回 `[]` 伪装成功**，而是返回单元素列表：

```python
[{"error": "URLError: <urlopen error [Errno 111] Connection refused>",
  "tool": "searxng", "query": "claude max exploit"}]
```

调用方检查 `results[0].get("error")` 即可区分**故障**与**真空（0 结果）**。

| on_error | 出错行为 |
|---|---|
| `"report"`（默认） | 返回 `[{"error": ..., "tool": "searxng", "query": ...}]` |
| `"raise"` | 直接抛异常 |
| `"empty"` | 兼容旧行为：返回 `[]`（故障与真空不可区分，不推荐） |

CLI 出错时向 stderr 打印 error 并 `sys.exit(1)`。三个工具（hackernews / github /
searxng）协议一致，组合时统一用 `result[0].get("error")` 判故障。

## 模块名与兼容 shim

- 唯一模块名是 **`searxng_client.py`**，与 `hackernews_client` / `github_client` 同进程组合不会撞名。
- 旧的 `from client import search` 仍可用（`client.py` 是兼容 shim，会触发 `DeprecationWarning`）。
- 但**禁止在同进程 import 多个工具目录的 `client`**——三个目录模块同名，
  第二次 import 会命中 `sys.modules` 缓存返回错误模块。

## 配套文档

- `SOP.md` — 部署 SearXNG + 调客户端
- `SKILL.md` — 调用技巧 + CAPTCHA 兜底链

## 关联

- ↔️ `google-bridge`（首选，被锁时用 searxng 兜底）
- ↔️ `hackernews`（更轻的兜底）
- ↔️ `github`（代码 / CVE 验证）
