# chat-scraper (v3)

中国平台聚合搜索：**bilibili 官方 API**（结构化字段）+ **百度 `site:` 站内过滤路由**（16 个站点 + 任意域名透传 + 无 `site:` 通用搜索）+ **文心 AI 搜索低频线**（AI 认可度 + 引用发现）+ **通用阅读器 `read()`**（知乎结构化线 + 任意 URL 的 HTTP/浏览器兜底线）。

## 版本与诚实声明（先读这段）

- **v3.0.0 是从零重写**。旧版（宣称 "32+ 平台"）的代码已损失为纯 NUL 字节空壳，不可考；旧 README 的平台覆盖表全部作废。本文件只承诺下表实测过或明确标注 best-effort 的内容。
- 覆盖是**分层的**：`bilibili` 和 `zhihu` 有本机实测证据；其余平台走同一引擎路由，**未逐一实测**，标注 best-effort。不要按平台数量估算本工具能力。

## 实测覆盖表（2026-09-09/10，本机 Windows + Git Bash + Python 3.12）

| 平台 | 引擎 | 状态 | 证据 |
|---|---|---|---|
| bilibili | 官方 API `search/type`（buvid3 + wbi 兜底） | ✅ 实测 | 3 次真实查询共 18 条结构化结果（title/author/play/pubdate/url 全带），广告卡已过滤 |
| zhihu | **专用引擎链 v3.1**：本机 SearXNG → 搜狗 → 百度 `site:`（`zhihu_engine.py`） | ✅ 实测 | 降级链实测 5 条知乎直链（searxng 路径）；搜狗路径解析器对真实页面（存证 .scratch/r2/）离线复验通过 |
| zhihu 内容读取（问题/回答/文章） | 官方 API（无头 camoufox 引导 cookie + 纯签名 HTTP + 认证自愈 v3.4） | ✅ 实测 | question 19550227 → HTTP 200 真实 JSON；answers 用 web 同款 /feeds 端点；articles 端点 2026-09-10 实测 200 |
| zhihu 评论（v3.6，回答/问题） | 官方 comment_v5 API（签名 HTTP + paging.next 翻页 + 子评论展开） | ✅ 实测 | answers/12202014 与 questions 端点、child_comment 子评论端点 2026-09-10 实测 200（含翻页） |
| wenxin（v3.7 文心 AI 搜索） | camoufox 无头提交 + 截获 chat.baidu.com conversation SSE | ✅ 实测（配额纪律下低频用） | 2026-09-10 真实一发成功：`"智谱 GLM Coding Plan"` → 754 字 AI 答案 markdown + 23 条引用（证据 .scratch/r7_wenxin_engine/）；协议级侦察存证 .scratch/r6/ |
| 任意 URL（通用阅读器 v3.4） | `read()`：知乎分流 API 线；外域 HTTP 直连 → 无头浏览器兜底 | ✅/⚠️ | 知乎线实测见上；外域 HTTP 线与浏览器兜底见 v3.4 节 |
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
5. **单页上限**：bilibili 单页约 30 条，bilibili 的 num>30 自 v3.11 起自动翻页（护栏 5 页，有效上限约 150 条；页间走引擎内置 `_wait_turn` 节流，服务端空页即停），护栏耗尽安静返回已收集条数。百度 rn=20（未登录稳定上限），num>20 自 v3.12 起同样自动翻页（护栏 3 页，有效上限约 60 条——百度风控敏感且节流 20s/请求，护栏更保守；半途被风控时如实抛 `baidu_soft_blocked` 含已收集数，0 收获才切移动桶）。两引擎翻页均带跨页去重（v3.12），整页重复 = 排序已穷尽信号，如实停。搜狗与知乎链保持单页如实截断，不做翻页——搜狗连发风控阈值已标定（v3.13，读数 `state/sogou_throttle_log.jsonl`）：**连发阈值 = 4 发**（探测 sleep 2s/发、实测请求节奏 2~4s/发，第 5 发即 antispider 页；风控后 ~171s 冷却恢复），翻页必然触发，`python sogou_engine.py --probe N --probe-interval S` 可复测累积。
6. **本地代理会污染结果**：引擎强制直连（`trust_env=False`）。本机实测系统代理（如 Clash 7897 端口）半死不活时会伪造 ProxyError 或 timeout 页。如需经代理访问百度/bilibili，请自行改代码。
7. cn.bing.com 对纯 HTTP 客户端**会剥离 `site:` 操作符**（前序侦察 4 组对照全部复现），故 v3 不用 bing 做 `site:` 引擎；`format=rss` 备胎通道也未启用（百度可用时无必要）。
8. **SearXNG 主路径的启动依赖**：zhihu 引擎的 searxng 环节需要本机实例在跑（`tools/searxng/docker`）。实例没起不会卡死——自动降级搜狗/百度，但那是质量更低的路径，生产用请把实例跑起来。
9. **降级链的最坏成本要心里有数**：zhihu 链（searxng→搜狗→百度双桶→再搜狗）最坏约 3-4 分钟/次；普通平台（百度双桶→搜狗）桌面故障场景最坏约 150 秒（3 次尝试 + 40s/80s 指数退避 + 移动端请求）。低频使用是所有中国平台路径的共同前提。
10. **wenxin（v3.7）不可当关键路径**：三条硬风险见下方 v3.7 节——配额极紧（每浏览器身份约 1 次）、IP 热度持久（触码后新身份首次即 1005）、SSE 格式随前端版本漂移。内置熔断器只能保护 IP，不能提升可用性。

## 知乎无头引导 + 官方 API 内容读取（v3.3）+ 自愈与通用阅读器（v3.4）

无头隐身浏览器在本工具箱的定位是**"凭证引导器"**而非爬虫引擎（选型实测：
camoufox 无头一次通过知乎 zse-ck VMP 挑战；patchright 无头暴露
HeadlessChrome 指纹直接死，弃用）。知乎官方 API 内容线：

```bash
pip install "camoufox[geoip]" && python -m camoufox fetch   # 一次性，可选依赖
python zhihu_bootstrap.py                       # 无头领 d_c0/__zse_ck 存 state/
python zhihu_content.py question 19550227        # 官方 API 读问题（含回答数）
python zhihu_content.py answers 19550227 --num 5 # 读回答（web 同款 /feeds 端点）
python zhihu_content.py article 18589357376      # 读专栏文章（也可传完整 URL）
python zhihu_content.py comments 12202014        # 读回答评论（v3.6，comment_v5）
python zhihu_content.py comments "https://www.zhihu.com/question/19550227"   # 问题评论（URL 自动识别）
python zhihu_content.py read <任意URL>           # 通用阅读器（推荐入口，见下）
python zhihu_content.py read https://mp.weixin.qq.com/s/xxxx   # 公众号文章（⚠️ 实测：自动化环境会被微信要求验证——验证页按错误如实上报，需真人环境；机制保留供环境友好时使用）
python zhihu_content.py read https://www.bilibili.com/video/BV1xx     # B站视频结构化
python zhihu_content.py page <知乎URL>           # 免 cookie 读页面全文（无头浏览器+百度来路）
```

### 认证自愈（v3.4）

服务端认证拒绝（`zhihu_auth_expired`：401/40353/ZERR_NOT_LOGIN 形态）时自动
**无头引导刷新 cookie 并重试原请求一次**：进程级闸门 ≥600s 冷却 + 模块级锁
（并发只放一个进引导），动作打印到 stderr，引导失败如实抛原异常。注意区分：

- `zhihu_sign_rejected`（code 10003）= 签名/参数被拒，**cookie 是好的**——
  2026-09-10 实测 cookie 有效时 members/answers 也可能 403+10003；v3.3 曾把它
  误诊为 auth_expired（会诱发自愈风暴），v3.4 前置修正。
- `zhihu_not_found` = 裸 404（死端点），此前无 slug 穿透，v3.4 补协议。
- cookie 文件缺失不自动引导（跑 `zhihu_bootstrap.py`，保持显式）。
- cookie 写盘为原子写（临时文件 + os.replace，v3.4）。

### 通用阅读器 `read(url)`（v3.4，推荐的内容入口）

一个入口读任意 URL，统一返回 `{title, content, url, engine}`：

| URL | 路径 | engine |
|---|---|---|
| `www.zhihu.com/question/{id}` | fetch_question（cookie+签名 API） | `zhihu-api` |
| `www.zhihu.com/question/{id}/answer/{aid}` | fetch_answers 过滤该 aid；过滤不到/API 线挂 → SEO 浏览器线 | `zhihu-api` / `zhihu-seo-browser` |
| `zhuanlan.zhihu.com/p/{id}` | fetch_article（官方 articles API） | `zhihu-api` |
| 其他知乎 URL | read_via_browser | `zhihu-seo-browser` |
| 非知乎域名 | requests 直连（trust_env=False + Chrome Accept 四件套）+ bs4 选择器提取；**403/网络异常/疑似反爬（正文<200 字）→ 无头 camoufox 兜底** | `http` / `browser` |
| 非知乎且 404/5xx | 直接抛 `read_failed`（换浏览器也一样死，不烧浏览器） | — |

```bash
python zhihu_content.py read https://zhuanlan.zhihu.com/p/18589357376
python zhihu_content.py read https://www.zhihu.com/question/19550227
python zhihu_content.py read https://blog.csdn.net/xxx   # 外域走通用线
```

正文提取选择器优先级：`article, .post-content, .article-content,
#js_content, .rich_media_content, main, #content`，body 纯文本兜底，
去 script/style，截 8000 字。

**免 cookie 兜底读法（主人提出的机制，已实测证实）**：知乎对"搜索引擎引流"
访客放行全文——无头浏览器带 `Referer: 百度搜索` 打开知乎页，回答全文可见、
无登录墙、无 VMP 挑战（Referer 的 query 用目标 URL 本身即可泛化）。
纯 HTTP 带同样 Referer 则无效（CDN zse-ck 挑战在来路逻辑之前）。
适用：cookie 文件缺失/过期时的应急读取；代价是每次起浏览器约 10s。

边界与风险：
- **搜索线不走官方 API**：search_v3 即便带有效 cookie 也强制登录
  （401 ZERR_NOT_LOGIN）——上登录账号是用户决策，本工具不碰凭据；搜索继续
  用 SearXNG→搜狗→百度 降级链，搜到 URL 后可用本模块读内容。登录线等
  z_c0 实验结论，继续搁置。
- cookie 有效期未标定（过期会自动自愈一次；自愈也失败报 `zhihu_auth_expired`）。
- 引导页必须用知乎内容页；首页对无登录访客 302 到登录页（已内置默认）。
- `/answers` 子端点会被 40362 行为限制，已固定用 `/feeds`。
- 纯 HTTP（OpenSSL 指纹）今日可过，若未来被拦兜底方案是 curl_cffi 或浏览器
  内 fetch。
- articles 端点的 include 逗号语法未静态保证真回 content：content 空回退
  excerpt，再空如实报字段缺失（不伪装正文为空）。

### 评论读取 `fetch_comments(target)`（v3.6）

官方 comment_v5 家族（2026-09-10 纯 HTTP + zhihu_sign 签名复现 200，含翻页）：

| target | 端点 |
|---|---|
| 回答 ID / 回答 URL | `/api/v4/comment_v5/answers/{aid}/root_comment?order_by=score\|ts&limit=20&offset=`（offset 首跳留空但尾随 `&offset=` 必须保留在签名串里） |
| 问题 ID（kind="question"）/ 问题 URL | `/api/v4/comment_v5/questions/{qid}/root_comment?...` |
| 子评论（自动补拉） | `/api/v4/comment_v5/comment/{cid}/child_comment`（首跳无 query） |

机制与纪律：
- **翻页**沿响应 `paging.next`（服务端下发的完整 URL）——剥掉 scheme+host 后
  **原样直调**，不重排/不重编码（签名 path?query 必须与实际请求字节一致）；
  `is_end=true` 或 next 空即停，`max_pages=50` 护栏防失控（子评论补拉限 20 页）。
- **子评论展开**按"内嵌 `child_comments` 够 `child_comment_count` 就不补拉"
  原则省请求；端点回全量子评论，直接替换内嵌列表。
- **输出**扁平列表 `[{id, author, content(纯文本≤500), like_count,
  created_time, child_comment_count, child_comments(已展开扁平子列表),
  reply_to, url}]`。
- **602 语义**：部分评论端点对纯访客 cookie 回 401+code 602（"第三方应用无
  此权限"）= **该端点需要登录态，访客不可读**——映射为 `zhihu_auth_expired`
  但 message 明写"重跑引导无用"（引导只领访客 cookie），自愈跳过不浪费。

```python
from zhihu_content import fetch_comments
comments = fetch_comments("12202014")                       # 回答评论（默认 on_error="report"）
comments = fetch_comments("https://www.zhihu.com/question/19550227")   # 问题评论
comments = fetch_comments("19550227", kind="question", order_by="ts")  # 纯数字问题 id 消歧 + 最新序
if "error" in comments[0]: ...                              # 统一错误协议（zhihu_* slug）
```

## 文心 AI 搜索（v3.7）——低频高质量 AI 信号源

**定位**：`platforms=["wenxin"]` 返回的不是网页列表，而是**一条聚合行**——文心一言对 query 的 AI 回答（markdown，≤4000 字符）+ 它的引用来源列表。用于两类信号：

- **AI 认可度**：百度自家 AI 搜索怎么评价/描述 query 主体（答案正文）；
- **引用发现**：`referenceList` 是百度搜索后端给出的来源页（实测含 felloai、typingmind、智源社区等常规搜索引擎结果里靠后或漏掉的直链）。

### 协议与实现（2026-09-10 侦察实测，证据 .scratch/r6/，p2 脚本为移植蓝本）

- 页面是纯 SPA 壳；真正端点 `POST https://chat.baidu.com/aichat/api/conversation`，JSON 体，响应 SSE 流。
- SSE 解析：`basedata`（lid/baiduid/chatHitKunlun）→ 增量块：`component=="markdown-yiyan"` 的 `data.value` 顺序拼接=答案；`component=="thinkingSteps"` 的 `data.referenceList[]`=引用（url/text=标题/abstract/source=站名）；`metaData.state=="generate-complete"` + `endTurn:true`=结束。
- token 由页面内 JS（hector 反爬链）结合会话身份现算、服务端校验——**纯 HTTP 无法自造合法 token**（侦察 5 连复现全 `token check fail` 为证），必须 camoufox 无头提交搜索、浏览器内截获 SSE。

### 配额纪律（硬约束，写进 wenxin_engine docstring）

1. 游客配额极紧：**每浏览器身份约只够 1 次搜索**（实测新身份第 1 次成功、第 2 次起 1005）——每次调用全新 context，身份用完即弃；
2. 两次调用间隔保持**小时级**，不要连续调用；
3. 见 1005/kunlun_popup/wappass **立即熔断本 IP 全部文心调用**：长冷却默认 6 小时（`CHAT_SCRAPER_WENXIN_COOLDOWN_H` 可调），冷却期内直接报 `wenxin_quota` 不再起浏览器；熔断状态落盘 `state/wenxin_breaker.json`，进程重启也生效。

### 三条风险（诚实声明）

1. **配额极紧**：一次调用基本烧掉一个浏览器身份的配额，本引擎天生低频；
2. **IP 热度持久**：实测触码后同 IP 新身份第 1 次搜索即 1005——热度会累积，冷却期是小时级起步；
3. **SSE 格式随前端版本漂移**：`markdown-yiyan`/`thinkingSteps` 组件名、token 机制都是前端 bundle 的现状，百度改版即失效（`wenxin_token_fail`/空答案报错即此信号，需重新侦察）。

**结论：内置熔断是保护措施不是可用性承诺，wenxin 不可当关键路径依赖。**

### 用法

```bash
python wenxin_engine.py "智谱 GLM Coding Plan"     # 单条聚合行 JSON，exit 0/1
```

```python
from wenxin_engine import search
row = search("智谱 GLM Coding Plan")     # 默认 on_error="report"
# 成功行: {q, answer(markdown≤4000), citations:[{url,title,abstract,source}],
#          engine:"wenxin-ai", count, platform:"wenxin", vendor, role}
# 出错行: {"error": "wenxin_quota: ...", "tool": "chat-scraper",
#          "query": q, "platform": "wenxin"} —— 检查 row.get("error")
```

门面：`search(q, platforms=["wenxin"])` → 聚合列表里多一条 wenxin 行（走 `on_error="raise"` 由门面统一兜错误记录）。离线测试边界：camoufox 浏览器交互不进离线测试（真浏览器+真配额+时序不确定），离线覆盖 SSE 解析（真实样本切片 fixture）/熔断状态机/三态协议。

## 安装

```bash
pip install -r requirements.txt   # requests, beautifulsoup4, lxml
```

可选依赖（wenxin 线的 camoufox，缺它不影响其余平台）:

```bash
pip install "camoufox[geoip]" && python -m camoufox fetch   # 约百余 MB，一次性
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
results = search("q", platforms=["wenxin"])              # 文心 AI 信号（单条聚合行，低频！）
# 出错条目形如 {"error": "baidu_soft_blocked: ...", "tool": "chat-scraper",
#              "query": q, "platform": "zhihu"} —— 检查 item.get("error")
```

结果字段：`title / url / snippet / platform / engine / vendor / role / since`；bilibili 额外 `author / play / pubdate`；wenxin 是单条聚合行（`q / answer / citations / engine / count`，见 v3.7 节）。`vendor`、`role`、`since` 为透传参数（指标用）。

### CLI（各引擎独立 + 门面）

```bash
python bilibili_engine.py "python 教程" --num 10
python baidu_engine.py "claude" --site zhihu.com --num 10
python zhihu_engine.py "claude 教程" --num 10   # 知乎降级链（SearXNG→搜狗→百度）
python sogou_engine.py "claude" --site csdn.net --num 10   # 搜狗（百度不可用时的第三环）
python wenxin_engine.py "智谱 GLM Coding Plan"  # 文心 AI 搜索（低频！1005 即熔断 6h）
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
| `CHAT_SCRAPER_BAIDU_PROXY` | 空 | 百度引擎显式代理（默认直连；仅当代理真为 baidu.com 换出口时有效，Clash 规则分流下无效） |
| `CHAT_SCRAPER_SOGOU_PROXY` | 空 | 搜狗引擎显式代理（默认直连） |
| `CHAT_SCRAPER_SOGOU_RESOLVE` | `1` | 知乎链搜狗环是否解析 /link 跳转（0=关闭，保留搜狗跳转链） |
| `CHAT_SCRAPER_SOGOU_RESOLVE_INTERVAL` | `2.0` | 知乎链搜狗跳转解析的额外节流（秒）：相邻两次解跳转至少间隔该时长 |
| `CHAT_SCRAPER_WENXIN_COOLDOWN_H` | `6` | 文心 1005 熔断冷却时长（小时，可小数）；冷却期内直接报 `wenxin_quota` 不起浏览器 |

## 错误协议（与仓库 hackernews/searxng/github 工具一致）

`search(..., on_error="report")`（默认）：出错返回
`[{"error": "<slug>: <msg>", "tool": "chat-scraper", "query": q, "platform": p}]`，调用方检查 `result[0].get("error")` 区分「故障」与「真空（0 结果）」。
`on_error="raise"` 抛出；`on_error="empty"` 兼容旧行为返回 []（故障平台静默跳过）。
常见 slug：`baidu_soft_blocked`（占位/验证页）、`bilibili_api_error`（非 0 code/非 JSON）、`searxng_unavailable`（本机实例没起/返回异常；报错自带一条命令出路：`cd tools/searxng/docker && docker compose up -d`）、`sogou_blocked`（搜狗验证码）；zhihu 内容线的 `zhihu_auth_expired`（cookie 过期，v3.4 起自动自愈一次；v3.6 起还覆盖 401+code 602"端点需登录态"形态——message 注明访客不可读、重跑引导无用，自愈跳过）/`zhihu_behavior_limited`（40362 行为限制，降频再试）/`zhihu_sign_rejected`（10003 签名被拒，非 cookie 问题）/`zhihu_not_found`（裸 404）/`read_failed`（通用阅读器硬失败）；wenxin 线（v3.7）的 `wenxin_quota`（1005/kunlun/wappass 配额风控熔断，**已自动进入本 IP 长冷却**，冷却期内不起浏览器直接报此错）/`wenxin_token_fail`（1001/tokenFail，文心 token 绑定浏览器运行时，此错=当前前端版本下 token 机制已变，需重新逆向，不触发熔断）/`wenxin_timeout`（流式回答超时）/`wenxin_dependency_missing`（camoufox 未安装，报错自带安装命令）。zhihu 引擎链的报错额外带 `chain` 字段（如 `searxng(失败:SearxngUnavailable)→sogou(0条)→baidu(失败:...)`）记录每一环结局。风控也会以其他形态出现——实测（2026-09-09）同 IP 长期风控期百度直接 RST 连接，此时上报的是 `ConnectionError: ...RemoteDisconnected...`，按同类故障处理（换 IP/等待/切工具）。

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
