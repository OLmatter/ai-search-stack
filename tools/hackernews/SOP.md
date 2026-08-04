# hackernews SOP

> 零部署，纯标准库。HN Algolia 是公网 API，**直接用**。

## 触发

任何时候需要社区反应验证。

## 步骤

### 1. 装依赖

```bash
pip install -r requirements.txt  # 实际无依赖，跳过即可
```

### 2. 调

```bash
python3 client.py "query" --since 7d --vendor claude --role verify
```

或 Python：

```python
from client import search
results = search(q, num=10, since="7d", vendor="claude", role="verify")
```

## 失败回滚

| 失败现象 | 原因 | 回滚 |
|---|---|---|
| `Connection refused` | 公网断了 | 等几秒重试 |
| 返回 0 hits | query 太精确 / 时间窗太短 | 改短 since / 改宽 query |
| `429 Too Many Requests` | HN Algolia 限流 | 加 `time.sleep(1)` |

## 自动化检查

- [ ] `python3 client.py "test" --since 7d` 返回 ≥1 hits
- [ ] 响应时间 < 3s

## 反面案例

- ❌ 不带 `--since` → 时间窗无限，返 1000+ 旧结果
- ❌ `--tags=comment` → 返评论而非 stories，标题可能为空
- ❌ `num=100` → 触发 HN Algolia 限流