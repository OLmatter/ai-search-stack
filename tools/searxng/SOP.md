# searxng SOP（部署 + 调用）

> 标准操作流程：怎么部署 SearXNG + 怎么调客户端。

## 触发

需要部署 SearXNG 作为搜索兜底时。

## 步骤

### 1. 部署 SearXNG

**方式 A：Docker（推荐）**

```bash
docker run -d --name searxng -p 8888:8080 \
  -e SEARXNG_SECRET=$(openssl rand -hex 32) \
  searxng/searxng
```

**方式 B：公网实例**

```python
# 选一个公网实例（不推荐生产，公网可能限流）
results = search(q, instance="https://searx.be", ...)
```

公网实例（2026-08 可用性）：
- https://searx.be
- https://searx.tiekoetter.com
- https://search.disroot.org

### 2. 测试连通

```bash
curl -sS "http://127.0.0.1:8888/search?q=test&format=json" | head -c 500
```

应返回 JSON 含 `results` 数组。

### 3. 调客户端

```python
from client import search
results = search("claude max exploit", num=10, since="7d", vendor="claude", role="fallback")
```

## 失败回滚

| 失败现象 | 原因 | 回滚 |
|---|---|---|
| `Connection refused` | SearXNG 没启 | `docker ps` + `docker logs searxng` |
| 返回 0 结果 | 实例被限流 | 换公网实例 / 自建本地 |
| 慢（>5s） | 实例过载 | 换实例 / 启用 rate limit |
| `JSONDecodeError` | 实例坏了 / 不是 SearXNG | 换实例 |

## 自动化检查

- [ ] `curl http://127.0.0.1:8888/search?q=test&format=json` 返回有效 JSON
- [ ] 实际搜索返回 ≥1 结果
- [ ] 响应时间 < 5s

## 反面案例

- ❌ 用公网实例做高并发 → 限流 / 封 IP
- ❌ `https://` 公网实例在企业内网 → 防火墙 / 证书
- ❌ 不带 `format=json` → 返回 HTML 无法解析
- ❌ 不带 `time_range` → SearXNG 默认不限时间，可能返陈旧结果