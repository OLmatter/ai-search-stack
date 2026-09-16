# ai-search-stack

> **AI agent 搜索工具箱**：5 个独立工具 + 1 个 MCP 接入层 + 1 个统一 SOP + 1 个统一 SKILL。**不强行统一 API**，按任务路由。

[![Release: v3.29.0](https://img.shields.io/badge/release-v3.29.0-brightgreen.svg)](https://github.com/OLmatter/ai-search-stack/releases/tag/v3.29.0)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python: 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/)
[![Tests: 491 passing](https://img.shields.io/badge/tests-491%20passing-success.svg)](tests/)

**v3.29.0（2026-09-17）**：v3.0 全面审计大修之后连续三十轮迭代——
**A2 热榜聚合**：hotlist_engine.py（bilibili 热门/微博热搜/知乎诚实上限）
+ 门面 search.hot() 路由 + MCP china_hotlist 工具（第 15 个工具，无查询词
的监控原语：vendor 官宣/事件首发地/舆情雷达）。实测（逻辑探测 8 发）：
B 站 popular API 裸调即通（连 buvid3 都不需要）；微博 hotSearch 走
passport 访客 incarnate 流（纯 HTTP 两请求换 SUB/SUBP，无浏览器，cookie
缓存复用，is_ad 广告位剔除）；知乎热榜端点访客线实测死刑（裸调 401 +
签名线 401 code=101，需登录态——平台位保留恒报 zhihu_hotlist_needs_login，
零网络不烧引导，凭据线归主人），
详见 [CHANGELOG.md](CHANGELOG.md)。
此前
二十九轮：**三轴批次**：A1 掘金官方搜索 API 专用引擎（juejin_engine.py，实测裸调免
cookie + 结构化字段 + cursor 翻页，接管百度 site: 路由）+ B1 google-bridge
常驻看门狗（watchdog.py + 计划任务注册器，服务死了自动拉起——实机取证
杀进程后 1 秒恢复、调度链全通）+ C1 zhihu_content 通用阅读线拆分
read_page.py（1109 行双关注点解耦、AST 级零知乎依赖、兼容层保引用不变），
详见 [CHANGELOG.md](CHANGELOG.md)。
此前
二十八轮：症状漂移观察轮（第九轮采样，预算 3/3）：brave gate-1 fail
"brave: too many requests" **逐字回摆**（v3.26 timeout 漂移单轮即止）、
ddg gate-1 fail "duckduckgo: CAPTCHA" **逐字复发**（九轮中第八轮，
漂移确认未持续）——双 streak 维持 0，a) fail 一票否决 + c) 跨度
~0.5h << 24h 双拦 **gate-2 不烧**；漂移轮结论：v3.26 双 timeout 与
v3.25 收官聚合 0 行同构，**实例级/瞬时窗口假设再获证据**，逐字症状
仍是主导态；聚合确认 20 行实例级健康无降级窗，三引擎维持全禁；
**CLI --probe 退出码契约钉**（gate-1 班次实际入口的「0=有效观测/
1=无有效观测」契约此前只活在 help 文本，test_v3270 runpy+mock 离线
钉三态），
详见 [CHANGELOG.md](CHANGELOG.md)。
此前
二十七轮：判据 v2 第二次实战（brave gate-1 fail，01:23:10 "brave: timeout"
rows=0 → **streak 4→0 诚实归零**；a) fail 一票否决 + c) 跨度 ~3.5h
<< 24h 双拦 **gate-2 不烧**——4 连 streak 在跨度未满时一发即断，
「3h 窗口运气」风险实测成立，c) 条拿到反向证据）、ddg gate-1 fail
**症状变异首录**（v3.15~v3.25 七轮逐字 CAPTCHA → 本轮 timeout，
归零后第 4 fail，维持禁用）、实例级降级窗口闭环（v3.25 收官 0 行 →
本轮 20 行全 google cse，行数地板活体案例）、**search(engines=)
语义统一落地**（v3.25 立项项取证后实施：engines= 显式点名弃
categories 换严格收窄，与 probe() 同语义；取证 MCP 不暴露 engines、
生产调用方为零 → 零回归面；默认路径 categories=general 行为不变），
详见 [CHANGELOG.md](CHANGELOG.md)。
此前
二十六轮：判据 v2 首次实战（brave gate-1 过 streak 3→4 四连，但 streak 跨度
≤2.9h << 24h → 复合资格未齐 **gate-2 不烧**——c) 条件按设计拦下 3h
窗口内的提前烧关，正是 v3.20 烧关复发的教训）、gate-1.5 实网首验未过
不进库（**engines= 语义两形态分裂**：search() 恒传 categories =
「默认集 ∪ 点名」实测 google cse 混入、probe() 无 categories 严格
收窄——受控对照单变量钉死，文档钉 + 请求形状回归钉落库；行为级变更
立项留下轮）、ddg CAPTCHA 逐字复发 streak 维持 0、brave 4.5 分钟第 3
发 timeout（限流第三数据点）、默认聚合 0 行实例级降级窗口实录（行数
地板活体案例），
详见 [CHANGELOG.md](CHANGELOG.md)。
此前
二十五轮：doctor 实例级健康下限（`SEARXNG_MIN_ROWS=3` 行数地板：聚合
<3 行亮 ⚠️「默认引擎集整体哑火，非单引擎问题」，破 v3.23 实证的
「wikipedia 1 行也报引擎全健康」盲区）、probe() 实网首用（brave
streak 2→3 + 背靠背连发不限流首点、ddg CAPTCHA streak 维持 0、聚合
20 行全 google cse）、brave 恢复判据 v2 定标（N=3 + 连发 K=2 全过 +
跨度 ≥24h 三条全满足才烧第二关；聚合小样本试探评估为可选 gate-1.5），
详见 [CHANGELOG.md](CHANGELOG.md)。
此前
二十四轮：clean-worktree 收工检查固化（`scripts/clean_worktree_test.sh`：
HEAD 全新
worktree checkout 跑全量测试，破「本机绿≠fresh 绿」假象；stash 对
gitignore 产物无效故走 worktree）、SearXNG 第五轮采样（brave streak=2
继续积累、ddg CAPTCHA streak 归零、startpage 两轮三观测止损禁用——
三引擎全禁）、探活机制进库（searxng_client `engines=` 参数 + `probe()`
第一关函数，终结六轮 ad-hoc 裸探活），
详见 [CHANGELOG.md](CHANGELOG.md)。
此前
二十二维：cookie 寿命标定首批数据分析（7 读数/唯一死亡实测 47.38h，36h 续期阈值
维持：n=1 不够调参；renew 实战首例 1/1 成功零误触发）、续期入口现状
如实入档（无 cron 部署，MCP cookie 模式恒为纯标定）、doctor GBK 控制
台加固（cron 实录 UnicodeEncodeError 不再崩报告）、stop_wake 部署副本
字节级核验一致（接线+sidecar 实迹），
详见 [CHANGELOG.md](CHANGELOG.md)。
此前
二十一轮：duckduckgo 两关双过回滚生效【已修正：该判定为假阳性——
settings 重复条目使 ddg 实际未参排，诚实重跑第二关 CAPTCHA 复发，
维持禁用，见 c938d69】（聚合无 ddg，与 brave 同场对照
实证"单发可信度因引擎而异"）、brave 四轮数据实证其单发可信度不可靠
（恢复判据升级观察继续）、mojeek 首探 access denied 排除、stop_wake
强制条款版实战首验（本班次即被钩子唤醒）、claim 固化进领活入口（根因
修复），详见 [CHANGELOG.md](CHANGELOG.md)。
此前
二十轮：claim
固化进领活入口（worker_queue.acquire() 认领+读队列一步完成，
skipped 不泄漏活内容；hooks/stop_wake.py 仓库真源，唤醒层收口互踩预防，
已部署并备份旧版）、SearXNG 回滚判据细化到单引擎粒度（每引擎独立两关：
startpage 首例单独回滚成功，duckduckgo 第一关恢复待下轮第二关、brave
第三轮复发均维持禁用，详见 [CHANGELOG.md](CHANGELOG.md)）。
此前
十九轮：doctor
值班巡检趋势检查统计口径重做（shift_log.md 近 7 天：记录条数/覆盖天数/
每日分布/关键事件计数[restart/处置/❌/恶化 纯字面]/最近一条摘要；
缺文件/空/全坏行=可选观测未启用不报警，7 天零记录亮 ⚠️ 连续性中断）、
doctor GitHub 检查可选 GITHUB_TOKEN 认证（缓解匿名 60 req/h 共享配额
的限流窗口误报，详见 [CHANGELOG.md](CHANGELOG.md)）。
此前
十八轮：worker_queue
派工队列认领机制（多 worker 并行领同一队列互踩的修复，O_EXCL 原子
认领）、SearXNG 禁用引擎恢复复跑（三引擎单发探活全部复发，第一关即
未过，维持禁用，详见 [CHANGELOG.md](CHANGELOG.md)）。
此前
十七轮：doctor
新增值班巡检趋势检查（v3.16 初版：疑似异常口径）+ SearXNG 禁用引擎
恢复观察（单发探活全过但回滚启用后聚合搜索即复发——单发探活通过
≠ 可回滚，维持禁用并记录再评估方法，详见 [CHANGELOG.md](CHANGELOG.md)）。
此前
十六轮：doctor
标定钩子活性扩展覆盖搜狗恢复曲线日志、mcp doctor 工具 mode 子模式
（full|cookie|sogou）、SearXNG 实例上游引擎调优（实测不健康引擎清零，
详见 [CHANGELOG.md](CHANGELOG.md)）。
此前
十五轮：搜狗
恢复曲线标定机制（doctor --sogou-probe 单发探活，读数自带距上次风控秒
数）、wenxin 声明对齐复查修复（详见 [CHANGELOG.md](CHANGELOG.md)）。
此前
十四轮：搜狗连发
风控阈值标定（实测连发阈值 4 发）、B站多 P 展开、百度搜索
翻页、截断可见化扫尾、B站搜索翻页、doctor GitHub 检查修复、zhihu_content
截断可见化、
错误协议统一、
知乎官方 API 读取线 + 认证自愈、通用阅读器、微信/B站读取、全箱体检 doctor、
MCP stdio 接入层（14 工具）、文心 AI 搜索、cookie 寿命标定 + 定时续期、
B站字幕链路（实测未登录恒空，如实声明）、知乎回答列表登录门修复 + cursor
翻页（实测 403 现场复现，见 [CHANGELOG.md](CHANGELOG.md)）。本文档所有能力
声明以实测为准（依据见 [CHANGELOG.md](CHANGELOG.md)）。

## ✨ 特性

- 🔍 **中国平台聚合搜索**：16 站一个门面——bilibili 官方 API、知乎专用降级链
  （SearXNG → 搜狗 → 百度 site:）、百度桌面/移动双桶 + 搜狗第三环、
  文心 AI 搜索（AI 认可度 + 引用发现，低频线）
- 📖 **通用阅读器 `read(url)`**：知乎问题/回答/文章/评论走官方 API（含认证
  过期自愈），B站视频结构化读取（含 cid）+ 字幕读取链路（实测：未登录
  访客字幕列表恒为空，如实报告），外域 HTTP 直读 + 无头浏览器兜底
- 🌐 **国际搜索双通道**：google-bridge 真 Google（需 Chrome + 代理）、
  SearXNG 本地聚合（compose 一条命令起实例，JSON 已启用）
- 🐙 **开发者信号**：GitHub Releases / 安全通告（Advisories）、Hacker News
  社区反应验证，零部署
- 🔌 **MCP 接入层**：整个工具箱挂成 stdio MCP server，15 个工具任何 MCP
  客户端（ZCode / Claude Desktop）零代码直接调用
- 🩺 **doctor 一条命令体检**：巡检全部通道健康（SearXNG / 知乎 cookie /
  标定钩子 / bilibili / 百度 / google-bridge / GitHub / 值班巡检趋势），
  故障退出码 1；GitHub 检查可选配 `GITHUB_TOKEN`（5000/h，免匿名
  60 req/h 限流窗口）
- 🛡️ **统一错误协议**：出错返回带 `error` 字段的记录（slug 可诊断），永远
  不用静默 `[]` 把故障伪装成"没搜到"；模块名唯一，同进程组合不撞名

## 🚀 快速开始（3 步）

**第 1 步：克隆 + 装依赖**

```bash
git clone https://github.com/OLmatter/ai-search-stack.git
cd ai-search-stack
pip install "mcp>=2.1"        # MCP 接入层（只用 CLI 可跳过）
```

可选依赖按需装：知乎引导/文心/浏览器兜底线需 `pip install camoufox[geoip]`
（缺失时报错带安装指引）。

**第 2 步：挂进你的 MCP 客户端**（不想写代码，让 agent 直接调）

```json
{
  "mcpServers": {
    "ai-search-stack": {
      "command": "python",
      "args": ["<仓库路径>/ai-search-stack/tools/mcp_server.py"]
    }
  }
}
```

> Windows 下 `command` 建议用 python 绝对路径。重启客户端会话生效。

**第 3 步：体检 + 学路由**

```bash
python tools/doctor.py         # 全通道体检，确认环境就绪
```

然后读 [SOP.md](SOP.md)（怎么选工具）和 [SKILL.md](SKILL.md)（怎么组合）。
命令行用法见各 `tools/<tool>/README.md`。命令用 `python`（Windows 常见发行版
无 `python3`）。

## 🧰 工具矩阵

| 工具 | 解决什么 | 何时不用 |
|---|---|---|
| [`tools/chat-scraper/`](tools/chat-scraper/) | 中国平台内容：16 站搜索门面 + 知乎官方 API 读取（问题/回答/文章/评论）+ B站/微信读取 + 文心 AI 搜索 | 国际主题 |
| [`tools/google-bridge/`](tools/google-bridge/) | 真 Google（WebSearch 100% CAPTCHA），需 Chrome + 代理 | 找中国平台 / GitHub release |
| [`tools/searxng/`](tools/searxng/) | 兜底聚合搜索；`tools/searxng/docker` 一条命令起本地实例（已启用 JSON，公网实例默认禁 JSON 勿用） | 默认主搜 |
| [`tools/hackernews/`](tools/hackernews/) | 验证社区反应（高赞 = 真信号），零部署 | 中文 / 非技术 |
| [`tools/github/`](tools/github/) | Release / Advisory / 仓库，零部署（匿名 60 req/h，可选配 `GITHUB_TOKEN` 提额至 5000/h，doctor 同款） | 非 GitHub |
| [`tools/mcp_server.py`](tools/mcp_server.py) | 全工具箱暴露成 15 个 MCP tools（stdio） | 不用 MCP 客户端时 |
| [`tools/doctor.py`](tools/doctor.py) | 一条命令巡检全部通道健康 | — |

**实测状态**（详见各 README 与 CHANGELOG）：hackernews / github /
searxng(本地实例) / bilibili 引擎 / 掘金引擎（2 发探测实测信封）/
知乎官方 API 读取线 / 文心引擎（1 发实测成功）/ google-bridge（有代理时；
v3.28 看门狗实机取证常驻闭环）均端到端实测出真实结果；百度引擎因软
风控按错误协议上报（`baidu_soft_blocked`），解析器经真实页面离线复验 19/19；
微信读取当前自动化环境受限（验证页如实上报，环境友好时可读）。

### 知乎 cookie 生命周期运维（v3.9）

实测标定（`state/cookie_lifetime_log.jsonl`，doctor --cookie-probe 周期探活）：
**知乎访客 cookie 寿命 <48h**（47.4h 即 403）。自愈链路：用时触发（API 遇
认证拒绝自动无头引导一次，~15s 延迟）。要让白天首次使用零延迟，用 cron 在
低峰窗口顺带续期：

```bash
# crontab：每日 9 点探活 + 标定；cookie 已过期且龄 >36h 时顺带无头续期一次
0 9 * * *  cd /path/to/ai-search-stack && python tools/doctor.py --cookie-probe --renew-if-older-than 36
```

- 不加 `--renew-if-older-than` = 纯标定观测（现行行为，expired 也 exit 0，
  不污染寿命分布数据）
- 加 `--renew-if-older-than H`：探活发现 expired 且龄 >H 才动用一次无头
  引导（36h 窗口配合每日一次 cron，续期必命中过期窗口）；续期结果记进
  标定日志同一读数行（`renew` / `renew_result` 字段），续期失败 exit 1
- `--renew-if-older-than` 只动 expired 读数：missing（没戴表）/ error
  （网络风控）不触发；探活期间自愈仍禁用，标定数据不被续期污染
- `zhihu_engine` 的知乎搜索链走 SearXNG 降级（不用 cookie），不受影响

### B站字幕读取：实测上限（v3.9，如实声明）

`fetch_subtitles(bvid)` / MCP `bilibili_subtitles` 已实现完整链路：
view API 拿 cid → `player/wbi/v2`（wbi 签名）→ 字幕 JSON 正文解析。
**但实测（2026-09-16，3 个视频验证，含标题自带"CC字幕更新完毕"、确有
CC 字幕的视频）：未登录访客请求字幕列表恒为空**——B 站仅向登录态
（SESSDATA）下发 `subtitle.subtitles`，手动上传 CC 亦不豁免。本工具不带
登录态，故当前 `subtitles` 恒为 `[]`（`has_subtitles=false` + note 说明）
——这是真实上限，不是故障；`cid` 补全（`fetch_video` 返回）照常可用，
接入 SESSDATA 后该链路可直接出数据（mock 全测）。

### 知乎回答列表：登录门修复 + 访客配额墙（v3.10，如实声明）

实测（2026-09-16，403 现场复现 + 同 cookie 对照实验）：知乎已把
**`include=data[*].content` 形态的 /feeds 回答列表请求整单拦截**——访客
一律 HTTP 403 code=40353（"请您登录后查看更多专业优质内容"），**全新
cookie 亦然**（自愈+重试无法救回，v3.4 起的旧形态已死）。v3.10 改用
**无 include 形态**（实测 200）：`author/excerpt/voteup/url` 输出契约
不变（excerpt 本就是主来源）。同 cookie 对照实测还发现**访客配额墙**：
部分问题服务端只放行前几条回答即 `is_end`（13 答问题实测仅回 3 条）——
按 is_end 如实返回，不报错、不伪装完整；要更多/全文走 `read_page`
（浏览器线）。新增服务端 cursor 翻页（num 上限 20→500，paging.next
字节一致直调，max_pages=50 护栏）。

### 百度搜索翻页 + 截断可见化扫尾（v3.12，如实声明）

- **百度 num>20 自动翻页**：此前单页 20 条到顶、多要的静默蒸发（与 v3.11
  修掉的 bilibili 同一架构病）。现按 `pn` 偏移翻页：护栏 `MAX_PAGES=3` 页
  （有效上限约 60 条；百度风控实测敏感且引擎级节流默认 20s/请求，护栏比
  bilibili 的 5 页保守），服务端空页如实停；页间节流走引擎内置 `_wait_turn`。
  **半途被风控（已收集 >0 条）时如实抛 `baidu_soft_blocked`**（message 含
  已收集页数/条数，门面按既有协议降级搜狗），不伪装部分结果为完整，也绝不
  再烧移动桶；**0 收获时才切移动桶兜底**（v3.2 语义原样，移动桶保持单页）。
  翻页耗时按页数线性放大（3 页 ≈ 40s+）。**跨页去重**：页间重叠条目不再
  重复进返回集；整页全是重复 = 排序已穷尽信号，如实停（bilibili v3.11
  翻页同构病本轮一并扫出修复）。
- **截断可见化扫尾**：v3.11 只扫了 zhihu_content 四处，本轮把剩余三个输出
  截断口扫完——wenxin `answer`（截 4000 标 `truncated=true`）与
  `citations[].abstract`（截 500 每条标 `truncated`）、bilibili
  `fetch_video` 的 `desc`（截 2000 标 `truncated`）。全部增量字段，向后
  兼容。搜狗（降级环）与知乎链保持单页如实截断，不做翻页——搜狗连发
  风控阈值已标定（v3.13）：连发阈值 4 发，翻页必然触发，维持单页。

## 路由速查（详细见 SOP.md）

| 任务类型 | 选 | 备选 |
|---|---|---|
| 通用主题（任何语言） | google-bridge | searxng（本地实例） |
| 中国平台内容 | chat-scraper | — |
| GitHub release/CVE | github | — |
| 社区反应验证 | hackernews | — |
| CAPTCHA 兜底 | searxng | — |

**不会选？** 默认 `google-bridge`（最广覆盖，需代理）。

## MCP 接入

`tools/mcp_server.py` 把整个工具箱包装成一个 **stdio MCP server**：任何 MCP
客户端（ZCode / Claude Desktop / 任何 agent 框架）无需写代码即可直接调用 15 个
工具。它只是**接入层**——每个工具原样透传参数给现有模块函数，不做内部 API 统一。

依赖：`pip install "mcp>=2.1"`（1.x SDK 亦兼容）。Windows 下 `command` 可用
anaconda python 的绝对路径。

**工具清单（15）**：

| MCP 工具 | 委托的模块函数 | 用途 | 耗时预期 |
|---|---|---|---|
| `china_search` | `chat-scraper/search.search` | 中国平台聚合搜索（知乎/B站/掘金/微信/百度16站） | bilibili/juejin 1-3s；百度有 ~20s 强制间隔，多平台串行按平台数放大 |
| `china_hotlist` | `chat-scraper/search.hot` | 热榜聚合：B站热门/微博热搜（知乎实测需登录态，恒报诚实错误） | 秒级（微博首调约 10s，含访客 incarnate 与节流间隔） |
| `read_page` | `zhihu_content.read` | 通用阅读器：知乎 API 线 + B站/微信特化 + 外域 HTTP/无头浏览器兜底 | 可能起无头浏览器 10-15s |
| `zhihu_question` | `zhihu_content.fetch_question` | 知乎问题详情（官方 API） | 秒级 |
| `zhihu_answers` | `zhihu_content.fetch_answers` | 知乎回答列表（官方 API；cursor 翻页，num≤500；访客配额墙按 is_end 如实截断，见下） | 秒级~数秒（翻页按需） |
| `zhihu_article` | `zhihu_content.fetch_article` | 知乎专栏文章（官方 API） | 秒级 |
| `zhihu_comments` | `zhihu_content.fetch_comments` | 知乎评论（官方 comment_v5 API，含子评论展开、自动翻页） | 秒级~十秒级（评论多时翻页） |
| `bilibili_video` | `bilibili_engine.fetch_video` | B站视频结构化数据（官方 view API，含 cid） | 秒级 |
| `bilibili_subtitles` | `bilibili_engine.fetch_subtitles` | B站字幕链路（cid 补全 + player/wbi/v2；实测未登录恒空列表，见下） | 秒级（2 个请求） |
| `hn_search` | `hackernews_client.search` | Hacker News 搜索 | 秒级 |
| `github_releases` | `github_client.get_releases` | 项目 release 列表 | 秒级（匿名 60 req/h） |
| `github_advisories` | `github_client.get_advisories` | 安全通告（按生态） | 秒级 |
| `searxng_search` | `searxng_client.search` | SearXNG 聚合搜索（默认本地 8888） | 秒级；实例未起返回可读错误 |
| `googlebridge_search` | HTTP 转发 `127.0.0.1:18799/search` | 真 Google（需先起 search_helper + Chrome 代理） | 数十秒级；服务未起返回可读错误 |
| `doctor` | `tools/doctor.py` check/探活体系 | 全通道体检 + 标定探活子模式（mode: full\|cookie\|sogou，默认 full） | full 5-10s；cookie/sogou 单发秒级~十几秒 |

**GitHub 为何拆两个工具**：MCP 的工具描述就是模型的路由提示。两个正交参数集
（`repo` vs `ecosystem`）合成一个带 `kind` 判别参数的工具，模型更容易填错参数；
分开后各自 schema 单一、描述聚焦，且与模块函数 1:1（零胶水）。

**耗时与超时（如实评估）**：
- 请给 `read_page` / `googlebridge_search` 设 **read_timeout ≥ 120s**（无头
  浏览器 / 隐身 Chrome 真搜 Google 都在这个量级）。
- **read_page 慢会不会卡死其他调用？不会。** stdio 是单连接，但 MCP JSON-RPC
  支持按 id 并发请求；mcp 2.x 对同步工具经 `anyio.to_thread.run_sync` 跑在
  工作线程（并发上限 = anyio 默认线程池 40），`tools/list`、其他工具调用不被
  阻塞。若客户端串行 await（多数简单客户端如此），卡顿感知在客户端侧，与
  server 无关。
- 客户端超时取消请求时，server 侧的浏览器进程可能残留（camoufox/chrome 孤儿
  进程，Windows 常见）；重启 server 进程即可回收。

**错误协议**：错误不抛异常——作为 `{"error": "<slug>: <详情>", "tool": ...,
"query": ...}` 嵌在返回 JSON 里，与「真空（0 结果）」可区分；未预期异常也被
server 兜底成同形态，不会炸连接。

## 设计哲学

**toolbox，不是 monolith**。5 工具独立 + 1 SOP + 1 SKILL：

- 5 工具独立：可单独装 / 升级 / 替换
- 1 SOP 统一：路由 + 怎么选 + 怎么用 + 统一错误协议
- 1 SKILL 统一：组合模式 + 3 维信号过滤

**为什么不做统一 API**：
- 统一 API 难维护（用户原话）
- 每个工具有自己的部署 / 配置 / 优化方式
- 强行统一会丢失每个工具的特色
- 学习曲线低（按需看 1 个工具）

**v3 新增的两条底线**：
- **统一错误协议**：出错返回带 `error` 字段的记录（或 exit 1），永远不用静默 `[]` 把故障伪装成"没搜到"
- **模块名唯一**：`hackernews_client` / `github_client` / `searxng_client`，同进程组合不撞名（v2 同名 `client.py` 会静默劫持，实测事故）

详见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 目录

```
ai-search-stack/
├── SOP.md                ← 唯一 SOP（怎么选 + 怎么用 + 错误协议）
├── SKILL.md              ← 唯一 SKILL（路由 + 组合 + 3 维过滤）
├── README.md             ← 本文件
├── ARCHITECTURE.md       ← 设计理念 + 引擎选型实测记录
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
├── tests/                ← 离线单测（含 NUL 空壳/撞名防回归）+ 真冒烟
├── tools/
│   ├── mcp_server.py     # MCP stdio server（全工具箱暴露成 15 个 MCP tools）
│   ├── doctor.py         # 工具箱体检（一条命令巡检全部通道）
│   ├── google-bridge/    # Chrome 桥（search_helper v23.10，Windows/Linux 可用）
│   │   ├── search_helper.py
│   │   ├── start_*.sh
│   │   ├── requirements.txt
│   │   └── README.md
│   ├── searxng/          # 客户端 + docker/（compose + settings，JSON 已启用）
│   ├── hackernews/       # hackernews_client.py（+ client.py 兼容 shim）
│   ├── github/           # github_client.py（+ client.py 兼容 shim）
│   └── chat-scraper/     # v3 从零重写：baidu/bilibili/搜狗/知乎/文心引擎 + search 门面
└── .github/workflows/test.yml   # 编译/NUL 检测/离线单测/服务健康/真冒烟
```

## 文档层次

| 文件 | 读谁 | 解决什么 |
|---|---|---|
| **SOP.md** | 任何 agent | **怎么选工具**（路由）+ **怎么用**（5 步流程）+ 错误协议 |
| **SKILL.md** | 任何 agent | **怎么组合**（4 模式）+ **3 维过滤** + **query 模板** |
| `tools/<tool>/README.md` | 部署该工具的人 | 工具自己的部署 / 启动 / 失败回滚 |
| `ARCHITECTURE.md` | 维护者 | 工具箱设计理念 + 引擎选型实测依据 |
| `CHANGELOG.md` | 任何 agent | 版本历史 |
| `CONTRIBUTING.md` | 贡献者 | 提 PR 流程 |

## 配套资源

- **方法论**：eventsys `npl.agent.场景SOPSkill.web_search`（Web 搜索通用 SOP+Skill）
- **实战案例**：no1_agent `DESIGN.md` / `CLAUDE.md`（内部）

## License

MIT
