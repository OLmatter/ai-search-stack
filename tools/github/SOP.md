# github SOP

> GitHub API 公网直连，**零部署**。设个 token 提升 rate limit 即可。

## 触发

任何时候需要查 GitHub release / advisory / repo。

## 步骤

### 1. （可选）设 token

```bash
# https://github.com/settings/tokens
export GITHUB_TOKEN=ghp_xxxxx
```

匿名 60/h，配 token 5000/h。

### 2. 调

```bash
python3 client.py releases "owner/repo"
python3 client.py advisories --ecosystem pip
python3 client.py search "query"
```

## 失败回滚

| 失败现象 | 原因 | 回滚 |
|---|---|---|
| `403 rate limit exceeded` | 匿名 60/h 用完 | 配 `GITHUB_TOKEN` |
| `404 Not Found` | repo 名错 | 检查 owner/repo |
| `401 Bad credentials` | token 失效 | 重新生成 |

## 自动化检查

- [ ] `python3 client.py releases "anthropics/claude-code"` 返回 ≥1 release
- [ ] 响应时间 < 3s

## 反面案例

- ❌ 不配 token + 高频调用 → 1h 内被限
- ❌ 用 `https://api.github.com/...` 而非 `Accept: application/vnd.github+json` → 老 API 字段少
- ❌ `releases?per_page=100` 一次拉太多 → 触发限流