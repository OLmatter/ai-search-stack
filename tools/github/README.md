# github

> **GitHub 客户端** —— Releases / Advisories / Repo 搜索。

GitHub API 用于：看项目最新 release / 安全 advisory / 精确搜索仓库。

## 何时用

| 场景 | 适用 |
|---|---|
| 看项目最新 release 内容 | ✅ **首选** |
| 查 CVE / Security Advisory | ✅ 权威源 |
| 搜仓库（精确匹配） | ✅ 比 Google 准 |
| 搜代码片段 | ✅ 用 GitHub Code Search |
| 中文内容 | ❌ 改用 `chat-scraper` |
| 社区反应 | ❌ 改用 `hackernews` |

## 快速开始

本机用 `python`（不是 `python3`；本机 python = 3.12 anaconda）。

### 0. （可选）配 token 提升 rate limit

```bash
export GITHUB_TOKEN=ghp_xxxxx
```

不配也能用，但匿名 60/h，认证 5000/h。匿名限额撞上会 403，走错误协议。

### 1. 看 release

```bash
python github_client.py releases "anthropics/claude-code"
```

### 2. 查 advisory

```bash
python github_client.py advisories --ecosystem pip
```

### 3. 搜仓库

```bash
python github_client.py search "claude mcp server"
```

所有子命令都支持 `--num` / `--vendor` / `--role`（顶层 SOP 要求任何调用必传 vendor/role）：

```bash
python github_client.py releases "anthropics/claude-code" --num 3 --vendor claude --role verify
```

或 Python（**模块名是 `github_client`，不是 `client`**）：

```python
from github_client import get_releases, get_advisories, search_repos

releases = get_releases("anthropics/claude-code", num=5, vendor="claude", role="verify")
advisories = get_advisories("pip", num=10, vendor="pip", role="verify")
repos = search_repos("claude mcp", num=10, vendor="claude", role="primary")
```

## 错误协议（on_error）

三个函数默认 `on_error="report"`：**出错绝不返回 `[]` 伪装成功**，而是返回单元素列表：

```python
[{"error": "HTTPError: HTTP Error 403: rate limit exceeded",
  "tool": "github", "query": "anthropics/claude-code", "action": "releases"}]
```

调用方检查 `results[0].get("error")` 即可区分**故障**与**真空（0 结果）**。

| on_error | 出错行为 |
|---|---|
| `"report"`（默认） | 返回 `[{"error": ..., "tool": "github", "query": ..., "action": ...}]` |
| `"raise"` | 直接抛异常 |
| `"empty"` | 兼容旧行为：返回 `[]`（故障与真空不可区分，不推荐） |

CLI 出错时向 stderr 打印 error 并 `sys.exit(1)`。三个工具（hackernews / github /
searxng）协议一致，组合时统一用 `result[0].get("error")` 判故障。

## 模块名与兼容 shim

- 唯一模块名是 **`github_client.py`**，与 `hackernews_client` / `searxng_client` 同进程组合不会撞名。
- 旧的 `from client import get_releases` 仍可用（`client.py` 是兼容 shim，会触发 `DeprecationWarning`）。
- 但**禁止在同进程 import 多个工具目录的 `client`**——三个目录模块同名，
  第二次 import 会命中 `sys.modules` 缓存返回错误模块。

## 配套文档

- [`../../SOP.md`](../../SOP.md) — 工具箱路由 + 部署 + 错误协议
- [`../../SKILL.md`](../../SKILL.md) — 组合模式 + 3 维过滤

## 关联

- ↔️ `google-bridge`（找到仓库后用 GitHub 看 release）
- ↔️ `hackernews`（社区反应）
- ↔️ `searxng`（兜底）
