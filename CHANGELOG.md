# Changelog

## [3.8.2] - 2026-09-16

### 🎯 小批次收尾优化：README 徽章修复 + cookie 寿命标定工具 + v3.8.1 审计确认

### Added
- `tools/doctor.py`：**`--cookie-probe` 寿命标定模式**——真实调用一次知乎
  questions API（复用 `chat-scraper/zhihu_content.py` 的 `fetch_question`，
  探 bootstrap 同款问题 19550227），把读数（valid / expired / missing /
  error 四态 + 探活时间戳 + cookie 文件 `fetched_at` + cookie 龄小时数）
  追加写入 `tools/chat-scraper/state/cookie_lifetime_log.jsonl`（state/ 已
  gitignore，标定数据只留本地）。标定纪律：探活期间 monkeypatch 掉
  `_try_self_heal`——标定要的是 cookie 真实寿命读数，若过期即自愈刷新，
  每条 expired 都会被"续命"污染，寿命分布永远测不出来（评估员共识：
  产出决定自愈策略）。本模式只观测不判故障：expired/valid 都算成功观测
  （exit 0），日志写不进等本地故障才 exit 1。missing（cookie 文件缺/无
  d_c0）与 expired 分开记——前者是"没戴表"，后者才是"表停了"
- `tests/test_v382.py`（8 个测试，全离线零真实请求）：cookie_probe 四分支
  mock + jsonl 日志格式/追加语义 + 探活期间自愈禁用与恢复断言 +
  v3.8.1 Host 白名单边界复核补强（首尾空白 Host、前导零端口、空端口段、
  裸 IPv6）+ README 徽章版本与 `__version__` 一致性锁

### Fixed
- `README.md`：版本徽章残留 v3.7.0（上一轮 v3.8.1 替换失败——实际文本
  `Release: v3.7.0` 与预期模式不符）→ 更正为与 `__version__` 一致，badge
  文本与链接同步；Tests 徽章 111 → 实际测试数。新增一致性锁测试，徽章
  再滞后会直接红

### Changed
- 版本号 3.8.1 → 3.8.2（`tools/chat-scraper/__init__.py`、`tools/mcp_server.py`）

### 测试
- 全量 132 passed（v3.8.1 基线 124 + 本轮 8）；v3.8.1 Host 白名单审计确认：
  test_v381 主干覆盖（合法/伪造/前缀伪装/端口不匹配/缺失 fail-closed + 双
  服务真实 TCP 403）质量合格，本轮补 4 类刁钻边界全部符合 fail-closed 预期

## [3.8.1] - 2026-09-16

### 🎯 安全审计残留低危项收尾 + 运维优化（v3.8 安全加固的收尾轮）

### Security
- `tools/chat-scraper/server.py`：**Host 白名单校验**——仅接受
  `127.0.0.1:<port>` / `localhost:<port>`（port=实际监听端口），其余 Host 一律
  403；Host 头缺失按拒绝处理（fail closed）。防恶意网页借 DNS rebinding
  （攻击者域名解析到 127.0.0.1）跨源 CSRF 式驱动百度查询。补 3 个回归测试
  （合法 Host 过 / 伪造 Host 403 / 端口不匹配 403）
- `tools/google-bridge/search_helper.py`：同款 Host 白名单（双保险，叠加在
  v3.8 已删 CORS 之上），实现在 `SearchHandler._host_ok`
- `tools/google-bridge/start_mihomo.sh` + `start_search_helper.sh`：代理健康
  探针域名 `api.minimaxi.com/anthropic`（非预期第三方）→ 换中性连通性探针
  `http://connect.rom.miui.com/generate_204`（3 处）

### Fixed
- `search_helper.py` Linux Chrome 查找链残留的 `/home/yuliu/chrome/...`
  个人路径回退值删除（有 isfile 守卫但仍是别人机器的路径；PATH 查找链
  已覆盖，找不到时交给 undetected-chromedriver 自行处理）
- `mcp_server.py` china_search 工具描述的 platforms 帮助文本补 `wenxin`
  （v3.7.0 已注册进 `list_platforms` 但描述漏记，LLM 调用方看不到该选项）

### 小账（复审轮补记）
- CHANGELOG 各版测试计数段间差额（29/30、39/41、74/79、97/100 四处）为
  复审轮补充测试未逐版记帐所致，非测试丢失；本轮全量 116 全过对齐。

### Changed
- 版本号 3.7.0 → 3.8.1（`tools/chat-scraper/__init__.py`、`tools/mcp_server.py`）

## [3.7.0] - 2026-09-10

### 🎯 新增 wenxin 平台：文心 AI 搜索低频线（AI 认可度 + 引用发现信号）

### Added
- **`tools/chat-scraper/wenxin_engine.py`**：文心 AI 搜索引擎（wenxin.baidu.com /
  chat.baidu.com），`search(q, timeout_s=90, on_error, vendor, role)` 返回**单条
  聚合行**——`{q, answer(markdown≤4000), citations:[{url,title,abstract,source}],
  engine:"wenxin-ai", count, platform:"wenxin"}`，两类信号：AI 认可度（答案
  正文）+ 引用发现（百度后端 referenceList，常含常规搜索漏掉的直链）：
  - 协议按 2026-09-10 侦察实测移植（证据 .scratch/r6/，p2 脚本为蓝本）：
    camoufox 无头提交搜索 + 网络层截获 `POST chat.baidu.com/aichat/api/conversation`
    的 SSE 全文；`markdown-yiyan` 的 `data.value` 顺序拼接=答案，
    `thinkingSteps` 的 `referenceList[]`=引用（url 去重保序），`endTurn:true`
    =结束。纯 HTTP 不可行（token 由页面 hector 反爬链现算并服务端校验，
    侦察 5 连复现全败为证），本引擎不做纯 HTTP 通道
  - **熔断器**：见 SSE 首块 `status:1005`/`chatHitKunlun`/页面跳 wappass 即
    进入本 IP 长冷却（默认 6h，env `CHAT_SCRAPER_WENXIN_COOLDOWN_H` 可调），
    冷却期内直接报 `wenxin_quota` 不再起浏览器；模块级状态 + 落盘
    `state/wenxin_breaker.json`（CLI 一次性调用与 MCP 常驻进程共享冷却期）
  - 错误 slug：`wenxin_quota`（配额/风控，已自动熔断）/`wenxin_token_fail`
    （1001/tokenFail——文心 token 绑定浏览器运行时，此错=当前前端版本下
    token 机制已变，需重新逆向，不触发熔断）/`wenxin_timeout`/
    `wenxin_dependency_missing`（camoufox 未安装，报错带安装指引，与
    zhihu_bootstrap 同款可选依赖）；on_error 三态与仓库协议一致
  - 配额纪律写进 docstring：每浏览器身份约 1 次搜索（fresh context 用完即弃）、
    两次调用间隔小时级、1005 即熔断——**本引擎不可当关键路径**
- `search.py` 门面：`platforms=["wenxin"]` 分流（引擎 `on_error="raise"`，
  门面统一兜错误记录）；`list_platforms()` 注册
- 测试 +11（100→111，全部离线零网络）：SSE 分块解析（**真实样本切片
  fixture**：cap_168 成功流切片 / cap2_146 的 1005+kunlun 原样 /
  p3_repro1 的 1001+tokenFail 切片，存 `tests/fixtures/`）、1005 熔断触发、
  wappass 页面 URL 兜底熔断、1001 不熔断、冷却期内不起浏览器（mock 断言）、
  熔断过期放行、冷却 env 解析、on_error 三态、门面路由与错误协议；
  camoufox 浏览器交互不进离线测试（真浏览器+真配额+时序不确定，
  浏览器层按 p2 蓝本移植 + 真实一发人工验证）

### Changed
- 版本号 3.6.0 → 3.7.0（`tools/chat-scraper/__init__.py`、`tools/mcp_server.py`）
- README：v3.7 节（定位/协议/配额纪律/三条风险：配额极紧、IP 热度持久、
  SSE 格式随前端版本漂移）、安装节补 camoufox 可选依赖、环境变量表、
  错误 slug 表、用法示例；实测覆盖表新增 wenxin 行

### 实测
- 真实一发（预算 ≤2 次实搜，用 1 次）：`python wenxin_engine.py
  "智谱 GLM Coding Plan"` → **成功**：754 字 AI 答案 markdown（套餐价格/
  计费规则/接入方式结构化输出）+ 23 条引用（z.ai、百度百科、爱企查、
  腾讯云开发者社区、智源社区等），exit 0，熔断器未触发；证据
  `.scratch/r7_wenxin_engine/selftest1_success.json`

## [3.6.0] - 2026-09-10

### 🎯 MCP 接入层：整个工具箱挂成 stdio MCP server，任何 MCP 客户端直接调用

### Added
- **知乎评论读取（comment_v5 家族，2026-09-10 实测 200 全链路含翻页）**：
  - `zhihu_content.fetch_comments(target, num, order_by, expand_children,
    on_error, kind, max_pages)`：回答/问题根评论 + `/comment/{id}/child_comment`
    子评论端点；target 接受回答 ID/问题 ID/对应 URL（正则提取，纯数字按
    kind 消歧默认回答）；沿响应 paging.next 翻页（完整 URL 剥壳原样直调——
    签名字节与请求字节必须一致，offset 首跳留空但尾随 `&offset=` 保留）；
    子评论按"内嵌够 child_comment_count 就不补拉"展开，补拉也限页；
    输出扁平列表（content 纯文本≤500）
  - 602 错误语义：401+code 602（"第三方应用无此权限"）=该端点需要登录态
    ——映射 ZhihuAuthExpired 子类（slug 同 zhihu_auth_expired），message
    注明"访客不可读、重跑引导无用"，自愈跳过（引导只领访客 cookie）
  - CLI `comments <target>` 子命令（--num/--order-by/--kind/--on-error）
  - MCP `zhihu_comments` 工具（透传 fetch_comments）
- `tools/mcp_server.py`：stdio transport 的 MCP server（单文件，零业务逻辑），
  把工具箱暴露成 **13 个 MCP tools**——每个工具原样透传参数给现有模块函数，
  不做内部 API 统一（toolbox「路由层统一，内部各留特色」理念不变）：
  - `china_search`（chat-scraper search 门面）/ `read_page`（通用阅读器）/
    `zhihu_question` / `zhihu_answers` / `zhihu_article` / `zhihu_comments`
    （官方 API 结构化读取，评论走 comment_v5）/ `bilibili_video`（官方 view API）
  - `hn_search` / `github_releases` / `github_advisories`（GitHub 拆两工具：
    工具描述就是模型的路由提示，正交参数集分开比 `kind` 判别参数更不易填错，
    且与模块函数 1:1）/ `searxng_search` / `googlebridge_search`（转发
    18799 HTTP，服务未启动报可读错误含启动指引）/ `doctor`（复用 check 体系
    捕获 stdout 出文本报告，非 subprocess）
- 协议保命细节：
  - **stdout 卫兵**：工具执行期间 stdout 重定向 stderr（MCP stdio 下 stdout
    只归 JSON-RPC 协议；知乎自愈引导等库代码会往 stdout 打进度）
  - **错误协议映射**：模块 on_error 固定 "report"，错误作为正常返回内容嵌在
    JSON（`{"error": "<slug>: ...", "tool", "query"}`）；未预期异常由 server
    层兜底成同形态，绝不炸连接；zhihu_* slug（auth_expired 等）原样保留
- 耗时预期写进每个工具描述（read_page 无头浏览器 10-15s；百度 ~20s 强制间隔
  多平台串行放大；googlebridge 数十秒），建议客户端 read_timeout ≥ 120s
- 并发模型实测：mcp 2.x 同步工具经 `anyio.to_thread.run_sync` 跑工作线程，
  read_page 慢调用不阻塞 `tools/list` 与其他调用（评估结论已写入 README）
- README 新增「MCP 接入」节：客户端配置示例（ZCode / Claude Desktop）、
  13 工具清单表（名称→委托函数→用途→耗时）、超时与并发如实评估
- 测试 +18（79→97，全部离线零网络）：注册表完整性（13 工具+schema）、参数
  透传 mock 验证（含 on_error="report" 固定）、异常兜底错误形态（含
  zhihu slug 保留）、stdout 卫兵、googlebridge 死端口可读错误；
  知乎评论线 10 项（comment_v5 首跳 path/offset 字节、target URL 提取、
  沿 paging.next 原样翻页、is_end/空 next 终止、num 够数即停、子评论
  展开条件与补拉翻页、602 映射+自愈跳过、max_pages 护栏、非法 target）
- `zhihu_content._api_get`/`_api_request` 增 referer 参数（comment_v5 用
  问题页 Referer；默认值不变，原调用零影响）
- 协议级自测（仓库外 .scratch，不入库）：真 stdio spawn → initialize →
  tools/list（13 工具 schema 合法）→ 实调 doctor / hn_search（真实网络）/
  read_page + zhihu_answers（知乎 cookie 线，正文非空）/ searxng_search
  （实例未起→可读错误），10/10 PASS

### Changed
- `tools/chat-scraper/__init__.py` 版本号 3.5.0 → 3.6.0
- 依赖：server 需 `mcp>=2.1`（本机实测 2.1.1，FastMCP 已改名 MCPServer；
  文件内双版本导入兼容 1.x `mcp.server.fastmcp`）

[3.6.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.6.0

## [3.5.0] - 2026-09-10

### 🎯 第三批（评估共识）：微信/B站读取接入 + 全箱体检 doctor

### Added
- `read()` 分流扩展：
  - `mp.weixin.qq.com`（微信公众号文章，国内 AI vendor 官宣主渠道）→ 通用
    HTTP 线直读（`#js_content`/`.rich_media_content` 选择器已加入），反爬自动
    切无头浏览器兜底
    - ⚠️ 实测更正：当前自动化环境下微信返回「环境异常」验证页（HTTP 线 36
      字空壳、浏览器线验证码页）——分流与兜底机制保留（环境友好时可读），
      验证页现已按错误如实上报；微信的可靠读取需 headed 接管真 Chrome
      （评估观察单触发条件不变）
  - `bilibili.com/video/BVxx` → `bilibili_engine.fetch_video()`：官方 view API
    （公开免 wbi），结构化 title/desc/owner/view/danmaku/like/favorite/pubdate
- `tools/doctor.py`：一条命令巡检全部通道——SearXNG 实例存活+引擎健康
  （unresponsive_engines）、知乎 cookie 存在性/年龄、bilibili API、百度直连、
  google-bridge /health（可选项未起不算故障）、GitHub API；核心故障退出码 1
- 实测：B站视频 1.05 亿播放真实结构化数据；doctor 六项巡检全通过
- 测试 +4（70→74：fetch_video bvid 提取/错误协议、read B站分流、微信选择器在列）

- 复审轮（独立审计）修复：read() bilibili 分支错误逃逸+兜底目标错误双失效
  （现仅 /video/BV 走 API，任何失败回通用线）；微信/B站错误页守卫改
  「短文本 + 标记」判据（环境异常/参数错误/内容删除等家族，长文不误杀）；
  fetch_video tool 字段统一、412/5xx raise_for_status、_fmt_pubdate(0)
  不再伪造 1970；doctor cookie 缺失改 ⚠️ 不再永绿、绕系统代理、计数修正

[3.5.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.5.0

## [3.4.0] - 2026-09-09 - 2026-09-10

### 🎯 两评估代理共识批次：错误协议修正前置 + 认证自愈 + 文章 API + 通用阅读器

### Fixed（必修前置：错误协议，不修会诱发自愈风暴）

- **10003 误诊修正**：`zhihu_content.py::_raise_for_api_error` 此前把
  403+任意 code 判成 auth_expired——实测 cookie 有效时 members/answers
  返回 403+code 10003（签名被拒）也被误诊。现 `error.code==10003` →
  新异常 `ZhihuSignRejected`（slug `zhihu_sign_rejected`，提示"签名被拒/
  参数异常——非 cookie 问题，勿重跑引导"），且**先于认证检查分流**
- **404 协议缺口**：死端点返回裸 404（无 error body）此前以无 slug 的
  HTTPError 穿透。现 404 → `ZhihuNotFound`（slug `zhihu_not_found`），
  在 JSON 解析前判定（裸 404 常进不了 json()）

### Added

- **认证过期自愈**：`_api_get` 捕获 `ZhihuAuthExpired`（仅服务端拒绝：
  401/40353/ZERR_NOT_LOGIN 形态）→ 进程级闸门（模块级时间戳+锁，
  ≥600s 冷却，冷却内置位防并发重复引导）→ import `zhihu_bootstrap` →
  `bootstrap(headless=True)` 无人值守刷新 cookie → 重试原请求**一次**；
  重试直接调 `_api_request` 天然防递归。引导失败打印 stderr 后抛原异常，
  绝不吞错。本地 cookie 文件缺失**不**触发自愈（引导保持显式，也保证
  离线单测零浏览器）
- **cookie 原子落盘**（`zhihu_bootstrap.py`）：临时文件 + fsync +
  `os.replace`——半截 cookie 文件比没有更坑（自愈会拿它重试到死）
- **专栏文章 API** `fetch_article(id_or_url)`：`GET /api/v4/articles/{id}
  ?include=title,created,updated,voteup_count,comment_count,content`
  （端点 2026-09-10 实测 HTTP 200 存在）；接受纯数字 id 或
  `zhuanlan.zhihu.com/p/{id}` URL；content 空回退 excerpt，再空**如实报
  字段缺失**不伪装正文为空（include 逗号语法是否真回 content 以实测为准）
- **通用阅读器 `read(url)`**（价值评估员共识：搜索线覆盖 16 站但阅读线
  只有知乎，通用阅读器服务所有搜索产出）：知乎问题→fetch_question；
  question/{id}/answer/{aid}→fetch_answers 过滤该 aid，过滤不到或 API 线
  挂→read_via_browser；zhuanlan /p/{id}→fetch_article；其他知乎 URL→
  read_via_browser；**非知乎域名**→`_generic_read_http`（requests 直连
  trust_env=False + 完整 Chrome Accept 四件套 + 20s 超时 + bs4 选择器
  article/.post-content/.article-content/main/#content 提取、body 兜底、
  ≤8000 字）；403/网络异常/疑似反爬（正文<200 字）→ `_generic_read_browser`
  （无头 camoufox 直开，无需 Referer 技巧，engine="browser"）；404/5xx
  硬失败直接抛 `ReadError`（slug `read_failed`）不烧浏览器。统一返回
  {title, content, url, engine}
- CLI：`python zhihu_content.py read <url>`（另有 `article <id_or_url>`）
- `zhihu_engine.py` 的 searxng_unavailable 报错追加一条出路：
  「本机实例未起？cd tools/searxng/docker && docker compose up -d」
- 测试 41→66（+25：10003/404 映射、自愈触发/失败/防递归/冷却/缺失不触发、
  article id 提取与字段兜底、read 分流路由、_generic_read_http 解析
  fixture 与反爬短正文判定、searxng 提示行）

### 搁置清单（如实记录，两评估员共识未做项）

- **知乎登录线**：等主人的 z_c0 实验结论，本工具不主动碰登录凭据
- **微信/小红书专门方案**：搜狗微信搜索、小红书反爬均未实现，继续搁置
- **MCP 触发条件**：read/search 何时机被 MCP 调用未定义，搁置
- **组件化（YAGNI）**：引擎/阅读器抽象基类暂不抽取，等第三条阅读线出现
  再说

- 复审轮（独立审计）修复：read() 三分支浏览器兜底一致化（question/zhuanlan API 失败不再逃逸）；_generic_read_http 增 Content-Type 护栏（>200 字 JSON/二进制不再假成功）；浏览器线短正文如实返回（<200 字一票否决仅限 HTTP 反爬检测线）；403 无结构化错误体不再误诊 auth 并白烧引导；article title URL 解码；并发自愈单次性 + 上述各项测试锁死（测试 66→70）

[3.4.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.4.0

## [3.3.0] - 2026-09-09

### 🎯 知乎无头引导 + 官方 API 内容读取（定制浏览器组件落地）

无头隐身浏览器选型实测（camoufox / patchright / DrissionPage）：**camoufox
无头一次通过知乎 zse-ck VMP 挑战**（patchright 无头暴露 HeadlessChrome 指纹
即死、弃用；DrissionPage 价值在 headed 接管真 Chrome，留作硬目标兜底）。
定位：隐身浏览器=凭证引导器，不是爬虫引擎。

### Added
- `tools/chat-scraper/zhihu_sign.py`：x-zse-96（101_3_3.0，SM4 变种+自定义
  base64）纯 Python 签名，移植自开源 zhihu_sign_rs；服务器验签已验证（此前
  侦察：错误码 10003→40353 跃迁；本轮：真 cookie+签名 → questions API
  HTTP 200 真实 JSON）
- `tools/chat-scraper/zhihu_bootstrap.py`：无头 camoufox 引导器——开知乎
  内容页（首页会 302 登录，已避开）让 VMP JS 现算 `__zse_ck`，领
  `d_c0+__zse_ck` 存 state/zhihu_cookies.json；fetch 兜底+reload 多轮；
  camoufox 为可选依赖（缺失时给安装指引）
- `tools/chat-scraper/zhihu_content.py`：官方 API 内容读取——question
  （include 补 answer_count）/answers（web 同款 /feeds 端点，/answers 子
  端点实测被 40362 行为限制）；401/403/40353 → `zhihu_auth_expired`
  （提示重跑引导，绝不伪装真空）
- 测试 +3（32→35：签名形状/确定性、cookie 缺失与过期的错误映射；复审轮再 +4 至 39，见下）
- 实测：引导十几秒；question 19550227 → 200（answer_count=13）；answers
  → 周源/极客公园真实回答（赞 61/38）
- `read_via_browser()` + CLI `page <url>`：**免 cookie 兜底读取**——无头
  camoufox 带百度搜索 Referer 打开知乎页（搜索引擎引流放行，主人提出并
  实测证实：全文可见/无登录墙/Referer query 用 URL 本身可泛化；纯 HTTP
  带同 Referer 无效，CDN 挑战在来路逻辑之前）

### 边界（如实声明）
- **知乎搜索线不走官方 API**：search_v3 带有效 cookie 仍强制登录
  （401 ZERR_NOT_LOGIN），上登录账号属用户决策、本工具不碰凭据；搜索继续
  用引擎链，搜到 URL 后用本模块读内容
- cookie 有效期未标定；纯 HTTP TLS 指纹今日可过（兜底：curl_cffi/浏览器内
  fetch）；无头能过是当下事实非永久保证（headed camoufox 作二档）

[3.3.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.3.0

## [3.2.0] - 2026-09-09

### 🎯 百度引擎稳定化（头指纹 + 移动端桶 + 搜狗第三环）

百度是 14 个中国平台的主力引擎，软风控曾把整个工具箱打瘫（当日首请求 19/19、之后全占位页/RST）。五组对照实验（同 IP、间隔 ≥8s，证据存档 .scratch/r3/）找到了真正的开关变量：

### Fixed

- **头指纹修复（决定性）**：Chrome UA 配 requests 默认 `Accept: */*` 是机器人指纹——实测三件套组合被封、补完整 Chrome Accept 后同 IP 直连 2/2 过审（无需 cookie 无需预热）。桌面/移动会话均已内置，实测百度直连复活（csdn 查询 5 条真实结果）
- 预热 cookie 不解决 IP 级封禁（带全 cookie 照样 302 验证码）——文档如实更正

### Added

- **移动端备选桶**：m.baidu.com 与桌面端是独立风控桶（桌面被锁时移动端实测照常出结果）。桌面双退避穷尽后自动切换：iPhone UA + `div.c-result` → `data-log` JSON → `mu` 直链解析，丢弃 *.baidu.com 自家内容卡；移动端页内联 JS 含 wappass 字样，桌面版 wappass 判据已在移动路径隔离（防全量误报）；结果 engine=baidu-mobile
- **搜狗第三环**（`tools/chat-scraper/sogou_engine.py`）：百度双桶穷尽后门面自动降级搜狗（`div.vrwrap` 的 `data-url` 属性即直链，免解跳转）；搜狗 web 无时间参数，since 仅透传；CLI `python sogou_engine.py "q" --site csdn.net`
- `CHAT_SCRAPER_BAIDU_PROXY`：显式代理支持（默认空=直连；**仅在代理真的为 baidu.com 换出口时有效，Clash 规则分流国内域名时无效——实测**）
- `CHAT_SCRAPER_SOGOU_PROXY`：搜狗引擎显式代理（默认直连）
- 测试 +5（Accept 头指纹、移动端 data-log 解析、搜狗 data-url 解析、门面"百度故障→搜狗、百度真空→不降级"语义），共 30 个

[3.2.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.2.0

## [3.1.0] - 2026-09-09

### 🎯 知乎专用搜索引擎链（chat-scraper）

知乎是国内反爬最严的平台之一，五路路径全部实测后定架构（证据存档 .scratch/r2/）：

### Added

- `tools/chat-scraper/zhihu_engine.py`：降级链 **本机 SearXNG → 搜狗 → 百度 site:**
  - 主路径 SearXNG：`site:` 交给聚合后端（实测 brave / google cse 均严格尊重且返回直链、零验证码；后端随健康度浮动，engine 字段可观测），支持 since→time_range
  - 搜狗：尊重 site: 但结果包在 `/link?url=` 跳转里——默认解跳转（302 Location / `location.replace` 双模式，≥2s 节流，`CHAT_SCRAPER_SOGOU_RESOLVE=0` 可关，解不开保留跳转链）；验证码报 `sogou_blocked`
  - 百度 site: 保底（复用 baidu_engine，IP 软风控时报 `baidu_soft_blocked`）
  - 降级语义：单引擎**报错或 0 结果都降级**；全链失败报错带 `chain` 字段（每环结局可诊断），全链成功 0 结果才是真真空
- `search.py` 门面：`platforms=["zhihu"/"zhuanlan"]` 路由到专用引擎链（不再裸走百度）
- CLI：`python zhihu_engine.py "query" --num 10`（错误走 stderr + exit 1，与全仓协议一致）
- 测试：+6 个知乎引擎离线测试（搜狗解析含高亮清理/去重/直链保留、跳转解析正则、searxng 域过滤、链条降级、全链失败 chain 日志、门面路由拦截），共 24 个

### 实测结论（为什么不是直连知乎 API）

- 知乎网页直爬：zse-ck VMP 风控盾，403（与登录无关）
- 知乎官方 API：x-zse-96（`101_3_3.0`，SM4 变种+自定义 base64，算法来自开源 zhihu_sign_rs）**已移植且服务器验签通过**（非搜索端点错误码 10003→40353 跃迁为证），但 search_v3 入口有边缘 WAF（`400 {"HitLabels":null}`，与签名无关）、访客 cookie `d_c0/__zse_ck` 由 VMP 浏览器挑战签发纯 HTTP 拿不到 → 除非未来加无头浏览器引导 cookie，此路不通
- cn.bing：剥离 `site:`（前序 4/4 对照复现），不可用
- 最终：SearXNG 主路径实测 5 条知乎直链；SearXNG 单引擎依赖（brave）与搜狗跳转成本已写进 README 风险段

[3.1.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.1.0

## [3.0.0] - 2026-09-09

### 🎯 全面审计驱动的大修（5 工具逐一代码审查 + 本机实测 + 独立复审）

v2.1.0 审计结论：5 工具中 2 个能用、3 个不可用（chat-scraper 为 NUL 空壳、google-bridge 在 Windows import 即崩、searxng 开箱无可用实例）；另发现同进程 import 撞名、CI 必然假绿等系统性缺陷。本版本逐项修复并补齐防回归测试。

### Added

- **统一错误协议**：所有客户端库 `on_error="report"/"raise"/"empty"`（默认 report，返回带 `error` 字段的记录），CLI 出错 stderr + exit 1——故障不再伪装成"0 结果"（v2 的静默 `[]` 是设计病）
- **tests/**：18 个离线单测（含 **NUL 空壳防回归**、**同进程 import 撞名防回归**、时区/解析契约测试）+ 真冒烟脚本（HN/GitHub 公网 API，限额时自动 SKIP）
- **CI 重写**（.github/workflows/test.yml）：v2 只做 py_compile 且带 `|| true`（NUL 文件也假绿）；v3 改为编译无豁免 + NUL 检测 + 离线单测（ubuntu/windows 双矩阵）+ google-bridge 服务健康与可读失败验证 + 公网冒烟（continue-on-error）
- `tools/searxng/docker/`：docker-compose + settings.yml（`search.formats` 启用 JSON——公网实例默认禁 JSON，这是 v2 README 推荐公网实例却必然失败的根因），一条命令起本地实例（实测 JSON API 返回真实结果）
- `tools/chat-scraper/` **从零重写 v3**（旧版 12 个 .py 中 11 个为纯 NUL 空壳、上游仓库已 404、代码不可恢复，自 v2.0.0 入库起即无代码）：
  - `baidu_engine.py`：百度 `site:` 通用引擎——会话复用、默认 20s 节流、软风控占位页检测、指数退避、`mu` 属性直链解析（真实页面离线复验 19/19）、`since`→gpc 映射
  - `bilibili_engine.py`：官方搜索 API——buvid3 获取、风控升级自动 wbi 签名重试、广告条目过滤、结构化字段（author/play/pubdate）
  - `search.py` 门面：16 站 SITE_MAP + 任意域名透传 + 统一错误协议；引擎选型依据（bing 剥离 site: 实测 4/4 复现 → 弃用；百度/官方 API 实测有效）记录于 ARCHITECTURE.md
  - `server.py`：stdlib HTTP 服务（/search、/health，仅绑 127.0.0.1）
  - README 按实测诚实分层：✅ 实测 / best-effort 未逐一实测 / 已知风险，废除 v2 无工件支撑的"32+ 平台"宣传
- `tests/smoke_live.py` + ARCHITECTURE「引擎选型实测记录」节

### Fixed

- **google-bridge（search_helper v23.7→v23.9，17 项）**：
  - Windows import 即崩：`faulthandler.register(signal.SIGUSR1)` 加平台守卫（高）
  - UDD 硬编码他人家目录 `C:\Users\520hh\` → `~/.no1_chrome_udd`（高）
  - query 未 URL 编码 + 双重解码 → urlencode 构造、删除二次 unquote（中）
  - 默认绑定 0.0.0.0 → 127.0.0.1（中，README 原本宣称 127.0.0.1）
  - 持锁 sleep 30s 串行阻塞并发 → 锁外等待（中）
  - 页面加载失败静默 200+count=0 → HTTP 502 + error JSON（中）
  - `.sh` 硬编码 `/home/yuliu/*`、无条件覆盖用户环境变量、指向错误脚本路径 → SCRIPT_DIR 化 + `: "${VAR:=default}"`（高）
  - example_config.sh 三个幽灵变量（代码从不读）→ 换为代码真实读取的变量（中）
  - chromedriver 查找：仅环境变量 → env → state/bin/ → PATH → uc 自动下载 四级回退
  - 其余：CAPTCHA sleep 可配置（NO1_CAPTCHA_SLEEP）、CAPTCHA 启发式阈值可配（NO1_MIN_HTML_LEN）、honeypot client_ip 用真实客户端地址、删除不可达代码、Linux chrome 路径去硬编码
  - **CAPTCHA/锁定不再伪装成 0 结果（v23.9）**：CAPTCHA 持续、post-CAPTCHA 锁定、CAPTCHA 限速三种路径原 `return []` → 抛 `CaptchaBlocked`，HTTP 层答 503 + `{"kind": "captcha_blocked"}`；0 结果时自动落盘现场 HTML 到 `state/last_zero_page.html` 供诊断
  - 实测：本机端到端真 Google 搜索返回 14 条真实结果（v23.8 时点）；随后测试出口 IP 被 Google 风控，503 行为按上述实测确认
- **hackernews**：`utcnow()` 时区漂移（UTC+8 实测 -28800s）→ timezone-aware；comment 模式 points=null 导致调用方 `points >= 50` TypeError 崩溃 → `or 0` 兜底（实测会崩的 bug）
- **github**：CLI 补 `--num/--vendor/--role`（v2 缺失致输出恒 vendor="?"，与 SOP"必传"自相矛盾）；repo/ecosystem URL 编码
- **searxng**：CLI 与库 `--since` 默认不一致（7d vs None）→ 统一 7d；未知 since 值静默忽略 → stderr 警告
- **文档漂移**：SKILL.md「since 不传默认无限」实为 7d；`timeout=15` 在冷却/CAPTCHA 路径必超时 → 90s；4 个工具 README 引用 v2.1 已删除的 per-tool SOP/SKILL 断链 → 清理；全部命令 `python3` → `python`
- **独立复审轮修复**（两路审查代理挑毛病后逐条落实，复审验收 PASS）：
  - SKILL 兜底链示例 q 未编码，带空格 query 抛 InvalidURL 被裸 except 吞掉——google-bridge 被静默跳过（示例自身犯了 v3 要消灭的"故障伪装"）→ `quote(q)` + 降级日志可见
  - tools/searxng/README.md 仍推荐裸 `docker run`（产出的实例 JSON 未启用，客户端必失败）→ compose 定为唯一推荐部署
  - SOP google-bridge 部署缺 `source .env`（search_helper 自身不读 .env，改了不生效）→ 已补
  - CAPTCHA 限速计数器永不衰减（进程生命周期内累计 2 次 CAPTCHA 即永久 503）→ 滚动 10 分钟窗口，出窗衰减（端点级实测）
  - chat-scraper 三个 CLI 错误输出统一为 stderr + exit 1 + stdout 空，且按任一平台故障判
  - /health 与启动横幅版本号 v23.8 → v23.9 对齐；hackernews null-points 兜底补 2 个回归测试（含 mock 端到端）；bilibili num<=0 边界、nav 非 JSON 包装、searxng 空 time_range 不再拼 URL；.gitignore 补 state/；compose 密钥标注示例值仅限本机；文档死链与 "32+ 平台" 残留清理；SKILL 案例 1 改为可运行纯 python

### Changed

- 轻客户端模块唯一化：`hackernews_client.py` / `github_client.py` / `searxng_client.py`（旧 `client.py` 变 3 行兼容 shim，打 DeprecationWarning）。v2 三个同名 `client.py` 同进程 import 第二个被 sys.modules 缓存静默劫持（SKILL 模式 4 的"多源验证"实测无声失效）
- 顶层 SOP/SKILL/README/ARCHITECTURE 全面同步 v3 现实（错误协议、新模块名、新部署命令、诚实状态表）

### 兼容

- 旧 `from client import search` 用法仍可用（shim），但同进程禁止 import 多个工具的 `client`
- 各 CLI 的既有参数不变；github CLI 为新增参数

[3.0.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.0.0

## [2.1.0] - 2026-08-05

### 🎯 重大调整：从分散 SOP+SKILL 到 1 顶层 SOP+SKILL

**用户原话**："不是一个工具一个sop。是只有一个sop和skill当做路由。根据任务把他们引导到不同工具。"

### Changed

- ❌ 删除 `tools/*/SOP.md`（5 份分散 SOP）
- ❌ 删除 `tools/*/SKILL.md`（5 份分散 SKILL）
- ❌ 删除 `docs/` 目录（choosing-tool / composition-patterns / quality-gate / query-design）
- ✅ 新增顶层 `SOP.md` —— 唯一 SOP：怎么选工具（路由）+ 怎么用（5 步流程）
- ✅ 新增顶层 `SKILL.md` —— 唯一 SKILL：4 个组合模式 + 3 维信号过滤 + query 模板
- ✅ `tools/<tool>/README.md` 保留（工具自己的部署 / 启动 / 失败回滚）
- ✅ README + ARCHITECTURE 重新设计（强调 1 SOP + 1 SKILL 路由）

### 设计变化

| v2.0.0 | v2.1.0 |
|---|---|
| 4 元文档（choosing / composition / quality-gate / query-design）| **1 顶层 SOP + 1 顶层 SKILL** |
| 5 per-tool SOP.md | 0 per-tool SOP.md（合并到顶层 SOP）|
| 5 per-tool SKILL.md | 0 per-tool SKILL.md（合并到顶层 SKILL）|
| 路由分散在 5 处 | **路由集中在 1 处** |

### 兼容

- 工具代码 / 启动脚本 / 客户端 / 部署流程：**完全不变**
- 用户只读 `SOP.md` + `SKILL.md` 就能用整个工具箱
- 想了解某个工具细节时，单独看 `tools/<tool>/README.md`

[2.1.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v2.1.0

## [2.0.0] - 2026-08-05

### Added
- 5 个独立工具：google-bridge / searxng / hackernews / github / chat-scraper
- 4 元文档 + 5 per-tool SOP/SKILL（**已被 v2.1 取代**）

[2.0.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v2.0.0

## [1.0.0] - 2026-08-05

### Added
- 首个稳定版
- `search_helper.py` v23.7
- README + ARCHITECTURE + CHANGELOG + .github CI
- MIT License

[1.0.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v1.0.0
[3.7.0]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.7.0
[3.8.1]: https://github.com/OLmatter/ai-search-stack/releases/tag/v3.8.1
