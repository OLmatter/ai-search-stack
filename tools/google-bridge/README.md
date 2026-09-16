# google-bridge

> **undetected-chromedriver Chrome 桥** —— 真 Google 结果，绕开数据中心 IP 封锁。

通用搜索主力。**任何主题、任何语言**的广度搜索首选。配合 mihomo 节点切换几乎不会 CAPTCHA。

## 何时用

| 场景 | 适用 |
|---|---|
| 通用主题搜索 | ✅ 真 Google 结果，无平台限制 |
| 实时事件（24h） | ✅ 配合 since=24h |
| 中文 / 英文 / 任何语言 | ✅ 全部支持 |
| 任意 vendor（claude/chatgpt/...） | ✅ URL 参数 vendor 自由定义 |
| **特定中国平台内容（知乎/B站/小红书/微信公众号）** | ❌ 改用 `chat-scraper` |
| **GitHub 项目/release/CVE** | ❌ 改用 `github` 工具 |
| **社区反应/讨论（HN/Reddit）** | ❌ 改用 `hackernews` 工具 |

## 快速开始（通用）

```bash
# 1. 装依赖
pip install -r requirements.txt

# 2. 配环境（可选——所有变量都有合理默认值，模板里逐个有注释）
cp example_config.sh .env
vim .env
source .env

# 3. 启动（见下方 Windows / Linux 分节）
# 4. 测试
curl "http://127.0.0.1:18799/health"
curl "http://127.0.0.1:18799/search?q=ENCODED&num=10&since=7d&vendor=claude&role=primary"
```

## Windows 部署（Git Bash / PowerShell）

前置条件：

1. **Chrome 浏览器**：默认找 `C:\Program Files\Google\Chrome\Application\chrome.exe`，不同位置用 `NO1_CHROME_BIN` 指定。
2. **chromedriver 自备**（Windows 上自动下载经常连不上 Google 存储）：下载与 Chrome 大版本一致的 `chromedriver-win64.zip`，任选其一放置：
   - 放到本目录 `state/bin/chromedriver.exe`（drop-in，推荐）；
   - 或 `export NO1_CHROMEDRIVER_BIN=/path/to/chromedriver.exe`；
   - 或放进 PATH。
   下载源：国内镜像 `https://registry.npmmirror.com/-/binary/chrome-for-testing/<版本>/win64/chromedriver-win64.zip`（实测可用），或官方 <https://googlechromelabs.github.io/chrome-for-testing/>。
   查找优先级：`NO1_CHROMEDRIVER_BIN` → `state/bin/chromedriver(.exe)` → `PATH` → 让 undetected-chromedriver 自动下载。
3. **代理必须有**：无代理 google.com 直连不通。先起 mihomo（`bash start_mihomo.sh`，需 `NO1_MIHOMO_BIN`），确认 `NO1_PROXY`（默认 `socks5://127.0.0.1:7897`）可达。

启动（前台运行，Ctrl-C 停止）：

```bash
python search_helper.py          # Git Bash / cmd 通用；默认监听 127.0.0.1:18799
```

`bash start_search_helper.sh` 在 Git Bash 下也能用：识别 MINGW 后自动跳过 Xvfb/pkill 流程，直接前台拉起 `python search_helper.py`。注意 Windows 侧脚本不做守护、不做进程清理。

## Windows 常驻：看门狗（v3.28）

`search_helper.py` 是前台/手动后台进程——**会话结束就死**，此后
`googlebridge_search` 一直报 `googlebridge_unreachable` 直到有人手动重启。
看门狗把「服务死了 → 拉起」闭环自动化：

```bash
python watchdog_task.py register      # 注册计划任务（幂等，/F 覆盖）
python watchdog_task.py status        # 查询
python watchdog_task.py unregister    # 一键回滚
python watchdog.py --check-only       # 只观测不拉起（手动诊断用）
```

工作方式：
- 周期计划任务 `ai-search-gbridge-watchdog`（默认每 15 分钟）跑
  `watchdog.py`：`GET /health` 可达即秒退（零动作）；不可达就分离进程
  拉起 `search_helper.py`，宽限 20s 内等 /health 恢复（helper 先绑端口
  后懒加载 Chrome，恢复是秒级）
- 决策流水：`state/watchdog.log`（每次观测一行）；子进程输出：
  `state/service.log`
- 退出码契约（测试钉死）：0=健康无动作；1=已拉起且恢复；2=拉起了但
  宽限期内未恢复（进程层看门狗只保进程——代理断/Chrome 坏属于
  /chrome_ready 与自愈的领域，看服务日志）；3=`--check-only` 且不健康
- `register` 会先注册承重的巡检任务，再尝试 `ai-search-gbridge-boot`
  （ONLOGON 开机即拉）。**普通权限令牌注册 ONLOGON 会被系统拒绝**
  （实测 2026-09-17「拒绝访问」）——此时降级不失败：开机后由巡检任务
  在 ≤interval 分钟内兜底恢复；管理员会话重跑 `register` 可补上开机任务
- 中文 Windows 的 schtasks 输出按 GBK 解码（utf-8→gbk 回退链），
  `unregister` 幂等（任务已不存在视为回滚完成）

Linux 常驻见上节 cron `@reboot`；看门狗本身跨平台（POSIX 走
`start_new_session`），但 `watchdog_task.py` 注册器 Windows-only。

## Linux 部署

```bash
pip install -r requirements.txt
# 自备 chromedriver（同上三种方式）与 mihomo
bash start_mihomo.sh      # 需 NO1_MIHOMO_BIN 指向 mihomo 可执行文件（默认找 state/bin/mihomo）
bash start_search_helper.sh   # 自动：Xvfb :99 → 代理健康检查 → 选最快节点 → 清理旧实例 → nohup 启动 → 健康检查
```

- 需要 `python3`、`curl`；Xvfb/pkill/ss 缺失时跳过对应步骤并告警（Chrome 需要显示服务，无 X 桌面的服务器装 `Xvfb`）。
- 日志在 `state/search_helper.log`。
- 开机自启：cron `@reboot bash /path/to/google-bridge/start_search_helper.sh`。

## 工具链

- `search_helper.py` — HTTP 桥（默认 127.0.0.1:18799；要对外用 `SEARCH_HELPER_BIND=0.0.0.0`）
  - `GET /health`、`GET /chrome_ready`、`GET /search?q=...&num=&since=&vendor=&role=`、`GET /export?...`
  - 失败语义（与"真 0 结果"的 200 区分）：页面没加载出来 → 502 `page_load_failed`；CAPTCHA 持续/锁定/限速 → 503 `captcha_blocked`（等冷却或切 searxng）；缺 `q` → 400
- `start_search_helper.sh` — 跨平台启动器（Linux 守护流程；Windows 前台拉起）
- `start_mihomo.sh` — mihomo 代理启动（二进制缺失时明确报错退出）
- `auto_select_node.py` — 自动选最快 mihomo 节点
- `example_config.sh` — 环境变量模板（全部与代码逐一核对）

## 可调环境变量（代码真实读取）

| 变量 | 默认 | 作用 |
|---|---|---|
| `SEARCH_HELPER_PORT` | `18799` | 监听端口 |
| `SEARCH_HELPER_BIND` | `127.0.0.1` | 绑定地址（勿随意 0.0.0.0，服务无鉴权） |
| `NO1_CHROME_BIN` | 平台自动探测 | Chrome 可执行文件 |
| `NO1_CHROMEDRIVER_BIN` | 自动探测链 | chromedriver 可执行文件 |
| `NO1_CHROME_UDD` | `~/.no1_chrome_udd` | 持久化 user-data-dir（多实例必须分开） |
| `NO1_PROXY` | win: `socks5://127.0.0.1:7897` / linux: `http://127.0.0.1:7897` | 代理 |
| `NO1_COOLDOWN` | `30` | 两次搜索最小间隔（秒） |
| `NO1_CAPTCHA_SLEEP` | `60` | CAPTCHA 后重试等待（秒） |
| `NO1_MIN_HTML_LEN` | `10000` | CAPTCHA 启发式页长阈值 |
| `NO1_MIHOMO_BIN` / `NO1_MIHOMO_DIR` | `state/bin/mihomo` | mihomo 本体（start_mihomo.sh） |
| `NO1_NODE_TIMEOUT` / `NO1_NODE_MAX` / `NO1_NODE_BUDGET` | `5` / `20` / `60` | auto_select_node 限流 |

## 关联

- ↔️ `mihomo`（必须）— 绕数据中心 IP 封锁
- ↔️ `searxng`（可选）— 主工具 CAPTCHA 锁时的兜底
- ↔️ `hackernews`（可选）— 社区反应验证
- ↔️ `github`（可选）— 代码/CVE 验证
- ↔️ `chat-scraper`（替代）— 中国平台（bilibili API + 百度 site: 路由 16 站）
