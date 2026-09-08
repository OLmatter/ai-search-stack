# chat-scraper (v3)

中国平台聚合搜索：**bilibili 官方 API**（结构化字段）+ **百度 `site:` 站内过滤路由**（16 个站点 + 任意域名透传 + 无 `site:` 通用搜索）。

## 版本与诚实声明（先读这段）

- **v3.0.0 是从零重写**。旧版（宣称 "32+ 平台"）的代码已损失为纯 NUL 字节空壳，不可考；旧 README 的平台覆盖表全部作废。本文件只承诺下表实测过或明确标注 best-effort 的内容。
- 覆盖是**分层的**：`bilibili` 和 `zhihu` 有本机实测证据；其余平台走同一引擎路由，**未逐一实测**，标注 best-effort。不要按平台数量估算本工具能力。

## 实测覆盖表（2026-09-09，本机 Windows + Git Bash + Python 3.12）

| 平台 | 引擎 | 状态 | 证据 |
|---|---|---|---|
| bilibili | 官方 API `search/type`（buvid3 + wbi 兜底） | ✅ 实测 | 3 次真实查询共 18 条结构化结果（title/author/play/pubdate/url 全带），广告卡已过滤 |
| zhihu | 百度 `site:zhihu.com` | ✅ 实测 | 前序侦察首请求 19/19 命中 zhuanlan.zhihu.com 真实直链；v3 解析器对该真实页面离线复验 19/19 + 19/19 带摘要 |
| general（无 site:） | 百度通用 | ⚠️ 代码就绪，当日未验证成功（见风控段） | — |
| csdn / juejin / jianshu / douban / weibo / v2ex / segmentfault / cnblogs / oschina / 51cto / gitee / weixin / toutiao / baidu_tieba | 百度 `site:<域名>` | ⚠️ best-effort：与 zhihu 同一引擎同一解析法，未逐一实测 | — |
| 任意 `<域名>` | 百度 `site:<域名>` 透传 | ⚠️ best-effort | platforms 里传形如 `example.com` 的字符串即启用 |

## 已知风险与限制（硬要求：诚实）

1. **百度软风控是现实约束，不是理论**。实测（2026-09-09）：当日第一次百度搜索成功（19/19），之后同 IP 的请求**全部**返回 HTTP 200 占位页（1488 字节、含 `timeout`），持续数小时未解封。v3 的行为：占位页 ≠ 0 结果，而是报错 `baidu_soft_blocked`（默认重试 2 次带指数退避，仍败走错误协议）。**缓解**：requests.Session 复用、请求间隔默认 20s（生产建议 ≥15s）、低频使用。风控触发后的冷却时间未知，请换 IP 或等待。
2. **bilibili 风控可能升级**。当前裸调（带 buvid3 cookie）即通；一旦官方要求 wbi 签名，引擎收到 code=-403/-412 会自动签名重试一次（wbi 完整实现已内置，key 缓存 1h）。若签名后仍 -412/-403，说明风控再加码（如负一层数据加密），需重新逆向。
3. **weixin（微信公众号）**：百度 `site:mp.weixin.qq.com` 只能搜到被百度收录的文章；公众号历史上有反爬更强的专门方案（sogou 微信搜索等），v3 **未实现**。
4. **百度时间过滤是 best-effort**：`since=24h/7d/30d` 映射为 `gpc=stf`（stftype 1/2/3，滚动窗口），百度对它的执行并不严格；其他取值不生效（stderr 告警）。bilibili 的 `since` 是客户端按 pubdate 过滤（API 不支持服务端过滤），过滤后可能少于 num 条。
5. **单页上限**：百度 rn=20（未登录稳定上限），bilibili 单页约 30 条；num 超出不做翻页。
6. **本地代理会污染结果**：引擎强制直连（`trust_env=False`）。本机实测系统代理（如 Clash 7897 端口）半死不活时会伪造 ProxyError 或 timeout 页。如需经代理访问百度/bilibili，请自行改代码。
7. cn.bing.com 对纯 HTTP 客户端**会剥离 `site:` 操作符**（前序侦察 4 组对照全部复现），故 v3 不用 bing 做 `site:` 引擎；`format=rss` 备胎通道也未启用（百度可用时无必要）。

## 安装

```bash
pip install -r requirements.txt   # requests, beautifulsoup4, lxml
```

本机注意：`python` 是 3.12（anaconda），没有 `python3`。

## 用法

### 库调用

```python
import sys; sys.path.insert(0, r"<仓库>/tools/chat-scraper")
from search import search, list_platforms

results = search("python 教程", platforms=["bilibili"], num=10)
results = search("claude", platforms=["zhihu"], num=10)
results = search("python 教程")                          # platforms=None -> 百度通用
results = search("q", platforms=["zhihu", "bilibili"])   # 多平台聚合
# 出错条目形如 {"error": "baidu_soft_blocked: ...", "tool": "chat-scraper",
#              "query": q, "platform": "zhihu"} —— 检查 item.get("error")
```

结果字段：`title / url / snippet / platform / engine / vendor / role / since`；bilibili 额外 `author / play / pubdate`。`vendor`、`role`、`since` 为透传参数（指标用）。

### CLI（各引擎独立 + 门面）

```bash
python bilibili_engine.py "python 教程" --num 10
python baidu_engine.py "claude" --site zhihu.com --num 10
python search.py "claude" --platforms zhihu,bilibili --num 10
python search.py --list-platforms
```

### HTTP 服务

```bash
python server.py --port 8765     # 或环境变量 CHAT_SCRAPER_PORT；只监听 127.0.0.1
curl http://127.0.0.1:8765/health
curl -G "http://127.0.0.1:8765/search" \
     --data-urlencode "q=python tutorial" \
     --data-urlencode "platforms=bilibili" \
     --data-urlencode "num=5"
```

注意：Windows cmd/PowerShell 的 curl 会按 GBK 编码中文参数，导致 mojibake 查询；Git Bash 下先 `export LANG=zh_CN.UTF-8`，或查询词用英文/拼音。服务端 `/search` 恒返回 200 + JSON 数组（错误内嵌），缺 `q` 返回 400。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `CHAT_SCRAPER_BAIDU_MIN_INTERVAL` | `20` | 两次百度请求最小间隔（秒）。测试可调小，**生产 ≥15** |
| `CHAT_SCRAPER_BILIBILI_MIN_INTERVAL` | `3` | 两次 bilibili 请求最小间隔（秒） |
| `CHAT_SCRAPER_PORT` | `8765` | server 监听端口 |

## 错误协议（与仓库 hackernews/searxng/github 工具一致）

`search(..., on_error="report")`（默认）：出错返回
`[{"error": "<slug>: <msg>", "tool": "chat-scraper", "query": q, "platform": p}]`，调用方检查 `result[0].get("error")` 区分「故障」与「真空（0 结果）」。
`on_error="raise"` 抛出；`on_error="empty"` 兼容旧行为返回 []（故障平台静默跳过）。
常见 slug：`baidu_soft_blocked`（占位/验证页）、`bilibili_api_error`（非 0 code/非 JSON）。

## 本机实测记录（2026-09-09）

| # | 命令 | 结果 |
|---|---|---|
| 1 | 门面 `search("python 教程", platforms=["bilibili"], num=10)` | 10/10 结构化、全 BV 直链、无广告卡、字段齐全 |
| 2 | 门面 `search("claude", platforms=["zhihu"])` 等 3 连 | 全部 `baidu_soft_blocked`（IP 已被百度风控，见风险段）——错误协议按设计工作，未静默返 [] |
| 3 | 解析器离线复验（前序侦察保存的真实结果页 `diag_baidu.html`） | 19/19 zhihu.com 命中、19/19 带摘要 |
| 4 | CLI `python bilibili_engine.py "机器学习 入门" --num 5` | 5/5 结构化，exit 0 |
| 5 | server /health、/search(bilibili)、缺 q | 200+版本与平台表、200+真实结果、400，进程杀净 |

当日对外请求账目：baidu 13（其中约 8 次为风控占位页/退避重试，无真实搜索负载）、bilibili 6、bing 0。超出预算的部分全部由百度软风控触发的重试造成，已如实记录。

## 设计与历史

- 引擎与门面分离：`baidu_engine.py`（会话复用/节流/占位页检测/指数退避，`mu` 属性即真实直链免跳转解析）、`bilibili_engine.py`（buvid3 + wbi 签名兜底 + 广告卡过滤）、`search.py`（平台注册表 + 统一错误协议）、`server.py`（stdlib http.server，无额外依赖）。
- 前身 `OLmatter/chat-scraper`（2026-08-05 并入 ai-search-stack 作为 v2 中国平台 expert）；v2 代码 NUL 损失后，v3 于 2026-09-09 依据当日实测情报从零重写，旧文件软删除于 `.trash/chat-scraper-v2-nul-20260909/`。

## 关联

- `google-bridge`（国际/通用，CAPTCHA 时换 searxng）
- `hackernews` / `github`（英文社区 / release）
