# github SKILL

> 调用技巧：什么时候用 GitHub、怎么选 API、怎么解读。

## 场景

需要权威代码 / release / CVE 信息时。

## 做法

### 1. releases() —— 看项目最新版本

```python
from client import get_releases
releases = get_releases("anthropics/claude-code", num=5, vendor="claude", role="verify")
# 看 tag_name + body（changelog）判断是否真更新
```

**何时用**：
- 监控特定项目更新（如 claude-code / mcp-server / langchain）
- 找 `body` 里含 `security` / `cve` / `vulnerability` 的 release

### 2. advisories() —— 查 CVE

```python
from client import get_advisories
advisories = get_advisories("pip", num=20, vendor="pip", role="verify")
# 按 severity 过滤
critical = [a for a in advisories if a["severity"] == "critical"]
```

**何时用**：
- 找特定 ecosystem 的最新漏洞（npm / pip / rubygems）
- 找 CVE 编号（`a["cve"]`）

### 3. search_repos() —— 搜仓库

```python
from client import search_repos
repos = search_repos("claude mcp server", num=10, vendor="claude", role="primary")
# 按 stars 排序
top = sorted(repos, key=lambda r: r["stars"], reverse=True)[:3]
```

**何时用**：
- 找特定工具的官方/社区实现
- 找 stars >= 1000 的高质量项目

## 原因

- GitHub API 是**权威源**（不是元搜索）
- 精确匹配（不像 Google 模糊）
- 信息结构化（releases / advisories 有 schema）
- 缺点：仅 GitHub 内容，其他平台看不到

## 案例

### 案例 1：监控 claude-code 更新

```python
releases = get_releases("anthropics/claude-code", num=3, vendor="claude", role="verify")
for r in releases:
    if "security" in r["content"].lower() or "cve" in r["content"].lower():
        # 推送告警
        ...
```

### 案例 2：找最新 npm 高危漏洞

```python
advisories = get_advisories("npm", num=30, vendor="npm", role="verify")
critical = [a for a in advisories if a["severity"] in ("critical", "high")]
```

## 配套工具

- ↗️ `google-bridge`（找仓库名）
- ↗️ `hackernews`（社区对 release 的反应）
- ↗️ `searxng`（兜底）