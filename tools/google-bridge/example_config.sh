#!/bin/bash
# example_config.sh — 复制为 .env 后填实际值
# cp example_config.sh .env && source .env

# ===== search_helper 配置 =====
export NO1_PORT=18799

# Chrome 二进制（Linux 路径示例）
export NO1_CHROME_BIN=/path/to/chrome-linux64/chrome
export NO1_CHROMEDRIVER_BIN=/path/to/chromedriver-linux64/chromedriver

# Chrome user-data-dir（持久化 cookies / fingerprints / trust）
# 重要：每个搜索栈实例用独立 UDD，否则会互踢
export NO1_CHROME_UDD=/path/to/chrome_user_data_dir

# 代理（mihomo 走 7897 是常见配置；远程 mihomo 也行）
# 格式: socks5://host:port  或  http://host:port
export NO1_PROXY=socks5://127.0.0.1:7897

# CAPTCHA 锁指数 backoff 基数（秒）
export NO1_CAPTCHA_BACKOFF_BASE=60

# honeypot 日志（每条 query 写一行 JSON）
export NO1_HONEYPOT_LOG=/path/to/honeypot.jsonl
