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

### 0. （可选）配 token 提升 rate limit

```bash
export GITHUB_TOKEN=ghp_xxxxx
```

不配也能用，但匿名 60/h，认证 5000/h。

### 1. 看 release

```bash
python3 client.py releases "anthropics/claude-code"
```

### 2. 查 advisory

```bash
python3 client.py advisories --ecosystem pip
```

### 3. 搜仓库

```bash
python3 client.py search "claude mcp server"
```

或 Python：

```python
from client import get_releases, get_advisories, search_repos

releases = get_releases("anthropics/claude-code", num=5, vendor="claude", role="verify")
advisories = get_advisories("pip", num=10, vendor="pip", role="verify")
repos = search_repos("claude mcp", num=10, vendor="claude", role="primary")
```

## 配套文档

- `SOP.md` — 部署 + 调用
- `SKILL.md` — 何时用 + 怎么用

## 关联

- ↔️ `google-bridge`（找到仓库后用 GitHub 看 release）
- ↔️ `hackernews`（社区反应）
- ↔️ `searxng`（兜底）