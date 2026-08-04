# chat-scraper SOP

> 部署 + 启动 + 维护流程。

## 触发

需要部署 chat-scraper 或重启服务时。

## 步骤

### 1. 装依赖

```bash
pip install -r requirements.txt
```

依赖：requests / beautifulsoup4 / markdownify。

### 2. （可选）配 cookies

部分平台（知乎/微博）需要登录态 cookies 才能搜深内容。

```bash
# 复制 cookies 模板
cp /path/to/chat-scraper/cookies_store.json.template cookies_store.json
vim cookies_store.json  # 填 zhihu / weibo 等 cookies
```

### 3. 启动

**方式 A：MCP server（推荐用于 Claude Code）**

```bash
python3 -m server
# 监听 stdio，等 Claude Code 通过 mcp__chat-scraper__* 调用
```

**方式 B：作为 Python 模块**

```python
import sys
sys.path.insert(0, '/path/to/tools/chat-scraper')
from search import search
results = search(q="Claude 漏洞", platforms=["zhihu", "bilibili"])
```

### 4. 验证

```python
# 跑个简单搜索
from search import search
results = search(q="test", platforms=["zhihu"])
assert len(results) > 0
```

## 失败回滚

| 失败现象 | 原因 | 回滚 |
|---|---|---|
| 某平台返 0 | 平台 API 变了 / 限流 | 切其他平台 / 更新 scraper |
| `ImportError` | 路径错 | `sys.path.insert(0, ...)` |
| cookies 失效 | 平台登录态过期 | 重新登录 + 更新 cookies_store.json |
| MCP server 起不来 | 端口冲突 / 路径错 | 查 `~/.claude.json` 的 cwd |

## 自动化检查

- [ ] 至少 3 个平台能正常返回结果
- [ ] 响应时间 < 10s（多平台聚合）
- [ ] cookies 未过期（如有登录态需求）

## 反面案例

- ❌ 一次 query 跑 32 平台全选 → 慢 + 触发限流
- ❌ 用过期的 cookies 调需要登录的平台 → 返 0
- ❌ 平台 API 变了不更新 scraper → 静默失败（无错误，只返 0）