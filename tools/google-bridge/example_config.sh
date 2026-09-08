#!/bin/bash
# example_config.sh — 复制为 .env 后填实际值
#   cp example_config.sh .env && vim .env && source .env
# v23.8 (2026-09-09)：全部变量逐一与代码核对过（旧模板里的
# NO1_PORT / NO1_CAPTCHA_BACKOFF_BASE / NO1_HONEYPOT_LOG 代码从不读，已删）。
# 脚本用 `: "${VAR:=default}"` 读取，已 export 的值不会被启动脚本覆盖。

# ===== search_helper 服务 =====
# 监听端口与绑定地址（search_helper.py main()）
# 安全默认只绑 127.0.0.1；要给局域网用才改成 0.0.0.0
export SEARCH_HELPER_PORT=18799
export SEARCH_HELPER_BIND=127.0.0.1

# ===== Chrome / chromedriver =====
# 不设也行：search_helper.py 会自动探测
#   chromedriver 优先级：NO1_CHROMEDRIVER_BIN → 本目录 state/bin/chromedriver(.exe) → PATH → undetected-chromedriver 自动下载
#   chrome 二进制：Windows 默认 C:\Program Files\Google\Chrome\Application\chrome.exe；Linux 沿 PATH 找 google-chrome/chromium
# export NO1_CHROME_BIN=/path/to/chrome-linux64/chrome
# export NO1_CHROMEDRIVER_BIN=/path/to/chromedriver-linux64/chromedriver

# Chrome user-data-dir（持久化 cookies / fingerprints / trust）
# 默认 ~/.no1_chrome_udd；多实例务必分开，否则互踢
# export NO1_CHROME_UDD=$HOME/.no1_chrome_udd

# ===== 代理（mihomo）=====
# 格式: socks5://host:port 或 http://host:port；search_helper 无代理几乎必被 CAPTCHA/断网
export NO1_PROXY=socks5://127.0.0.1:7897

# ===== 节流 / 启发式（都有代码内默认值，按需调整）=====
# 两次搜索最小间隔秒数（默认 30）
# export NO1_COOLDOWN=30
# CAPTCHA 后重试前等待秒数（默认 60）
# export NO1_CAPTCHA_SLEEP=60
# CAPTCHA 误判启发式的 HTML 最小长度（默认 10000；小于它且无 "did not match any documents" 视为验证码页）
# export NO1_MIN_HTML_LEN=10000

# ===== mihomo 本体（start_mihomo.sh 用）=====
# mihomo 可执行文件与配置目录；默认找本目录 state/bin/mihomo
# export NO1_MIHOMO_BIN=/path/to/mihomo
# export NO1_MIHOMO_DIR=/path/to/mihomo_config

# ===== auto_select_node.py（自动选最快节点，可选）=====
# export NO1_NODE_TIMEOUT=5   # 单节点测速超时秒
# export NO1_NODE_MAX=20      # 最多测多少个候选
# export NO1_NODE_BUDGET=60   # 总时间预算秒
