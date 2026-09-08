# chat-scraper (v3)

中国平台聚合搜索：**bilibili 官方 API**（结构化字段）+ **百度 `site:` 站内过滤路由**（16 个站点 + 任意域名透传 + 无 `site:` 通用搜索）。

## 版本与诚实声明（先读这段）

- **v3.0.0 是从零重写**。旧版（宣称 "32+ 平台"）的代码已损失为纯 NUL 字节空壳，不可考；旧 README 的平台覆盖表全部作废。本文件只承诺下表实测过或明确标注 best-effort 的内容。
- 覆盖是**分层的**：`bilibili` 和 `zhihu` 有本机实测证据；其余平台走同一引擎路由，**未逐一实测**，标注 best-effort。不要按平台数量估算本工具能力。

## 实测覆盖表（2026-09-09，本机 Windows + Git Bash + Python 3.12）

| 平台 | 引擎 | 状态 | 证据 |
|---|---|---|---|
| bilibili | 官方 API `search/type`（buvid3 + wbi 兜底） | ✅ 实测 | 3 次真实查询共 18 条结构化结果（title/author/play/pubdate/url 全带），广告卡已过滤 |
| zhihu | **专用引擎链 v3.1**：本机 SearXNG → 搜狗 → 百度 `site:`（`zhihu_engine.py`） | ✅ 实测 | 降级链实测 5 条知乎直链（searxng 路径）；搜狗路径解析器对真实页面（存证 .scratch/r2/）离线复验通过 |
| general（无 site:） | 百度通用（失败自动切搜狗） | ⚠️ 真空当日未验证成功过；故障降级链已实测接线 | — |
| csdn / juejin / jianshu / douban / weibo / v2ex / segmentfault / cnblogs / oschina / 51cto / gitee / weixin / toutiao / baidu_tieba | 百度 `site:<域名>` | ⚠️ best-effort：与 zhihu 百度保底同一引擎同一解析法，未逐一实测 | — |
| 任意 `<域名>` | 百度 `site:<域名>` 透传 | ⚠️ best-effort | platforms 里传形如 `example.com` 的字符串即启用 |

### zhihu 专用引擎链（v3.1）为什么长这样

- **知乎官方 API 纯 HTTP 不可用**（2026-09-09 实测）：x-zse-96（`101_3_3.0`）签名算法已移植且**服务器验签通过**（非搜索端点错误码 10003→40353 跃迁为证），但 search_v3 入口有边缘 WAF（`400 {"HitLabels":null}`，与签名对错无关），且访客 cookie `d_c0`/`__zse_ck` 由 zse-ck VMP **浏览器挑战**签发，纯 HTTP 拿不到。除非加无头浏览器引导 cookie，否则此路不通——别再花时间。
- **主路径 SearXNG**：`tools/searxng/docker` 起的本机实例。`site:` 的尊重是**聚合后端层的行为**（实测 brave 与 google cse 都严格尊重且返回直链、零验证码；本机实例聚合哪些后端随引擎健康度浮动，以结果里的 engine 字段为准）。弱点：上游后端常年在验证码/超期间摇摆，实例没起会报 `searxng_unavailable` 自动降级。
- **搜狗**：尊重 `site:`（腾讯系收录知乎好），结果包在 `/link?url=` 跳转里——引擎默认解跳转（间隔 ≥2s 节流，`CHAT_SCRAPER_SOGOU_RESOLVE=0` 可关），解不开保留搜狗跳转链。风控页报 `sogou_blocked`。
- **百度 site: 保底**：IP 软风控时好时坏（见下条），链里最后一环。
- 降级语义：单引擎**报错或 0 结果都触发降级**（site: 限定下 0 结果常是引擎索引弱而非真空）；全链失败才报错（error 里带 `chain` 字段记录每环结局），全链成功但 0 结果才是真真空。

## 已知风险与限制（硬要求：诚实）

1. **百度软风控的两个现实形态与真正的开关变量**（2026-09-09 同 IP 对照实测）：
   - 形态一：HTTP 200 占位页（1488B 含 timeout）；形态二：302 → wappass 图形验证码页。现有 len+timeout 判据两档都能抓（别用「安全验证」中文标记——验证码页编码错乱时匹配不上）。
   - **头指纹是直接开关**：Chrome UA 配 requests 默认 `Accept: */*` 是机器人指纹，实测被封；补完整 Chrome Accept 四件套后 2/2 直连过审。v3.2 已内置，别改回三件套。
   - 首页预热 cookie **不解决** IP 级封禁（实测带全 cookie 照样 302）。
   - 移动端 m.baidu.com 是**独立风控桶**：桌面被锁时移动端照常出结果（v3.2 已做自动备选，engine=baidu-mobile）。注意此为单日观测，两桶随时可能合并风控，不承诺 SLA；移动端页面内联 JS 含 wappass 字样，桌面版 wappass 判据在移动端会全量误报（已隔离）。
   - `CHAT_SCRAPER_BAIDU_PROXY` 可显式走代理，但**仅在代理真的为 baidu.com 换出口时有效**——Clash 规则分流把国内域名判直连时换了等于没换（实测）。
   - 软风控期降级语义：百度双桶穷尽后报错 → 门面自动切**搜狗第三环**（data-url 直链，免解跳转）→ 搜狗也挂才报错（保留 baidu slug 与双端结局信息）。
2. **bilibili 风控可能升级**。当前裸调（带 buvid3 cookie）即通；一旦官方要求 wbi 签名，引擎收到 code=-403/-412 会自动签名重试一次（wbi 完整实现已内置，key 缓存 1h）。若签名后仍 -412/-403，说明风控再加码（如负一层数据加密），需重新逆向。
3. **weixin（微信公众号）**：百度 `site:mp.weixin.qq.com` 只能搜到被百度收录的文章；公众号历史上有反爬更强的专门方案（sogou 微信搜索等），v3 **未实现**。
4. **百度时间过滤是 best-effort**：`since=24h/7d/30d` 映射为 `gpc=stf`（stftype 1/2/3，滚动窗口），百度对它的执行并不严格；其他取值不生效（stderr 告警）。bilibili 的 `since` 是客户端按 pubdate 过滤（API 不支持服务端过滤），过滤后可能少于 num 条。
5. **单页上限**：百度 rn=20（未登录稳定上限），bilibili 单页约 30 条；num 超出不做翻页。
6. **本地代理会污染结果**：引擎强制直连（`trust_env=False`）。本机实测系统代理（如 Clash 7897 端口）半死不活时会伪造 ProxyError 或 timeout 页。如需经代理访问百度/bilibili，请自行改代码。
7. cn.bing.com 对纯 HTTP 客户端**会剥离 `site:` 操作符**（前序侦察 4 组对照全部复现），故 v3 不用 bing 做 `site:` 引擎；`format=rss` 备胎通道也未启用（百度可用时无必要）。
8. **SearXNG 主路径的启动依赖**：zhihu 引擎的 searxng 环节需要本机实例在跑（`tools/searxng/docker`）。实例没起不会卡死——自动降级搜狗/百度，但那是质量更低的路径，生产用请把实例跑起来。
9. **降级链的最坏成本要心里有数**：searxng 挂/真空 → 搜狗（5s 节流 + 每条跳转解析 2s×num）→ 百度（20s 节流 + 退避重试），最坏一次 `platforms=['zhihu']` 调用可耗时约 1 分钟。低频使用是所有中国平台路径的共同前提。

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
python zhihu_engine.py "claude 教程" --num 10   # 知乎降级链（SearXNG→搜狗→百度）
python sogou_engine.py "claude" --site csdn.net --num 10   # 搜狗（百度不可用时的第三环）
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
常见 slug：`baidu_soft_blocked`（占位/验证页）、`bilibili_api_error`（非 0 code/非 JSON）、`searxng_unavailable`（本机实例没起/返回异常）、`sogou_blocked`（搜狗验证码）。zhihu 引擎链的报错额外带 `chain` 字段（如 `searxng(失败:SearxngUnavailable)→sogou(0条)→baidu(失败:...)`）记录每一环结局。风控也会以其他形态出现——实测（2026-09-09）同 IP 长期风控期百度直接 RST 连接，此时上报的是 `ConnectionError: ...RemoteDisconnected...`，按同类故障处理（换 IP/等待/切工具）。

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
