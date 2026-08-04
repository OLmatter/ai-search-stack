#!/bin/bash
# no1_agent v13 — start search_helper on Linux server.
# Run from cron @reboot OR manually: bash /home/yuliu/no1_agent/start_search_helper.sh
#
# Idempotent: kills any existing instance first, then starts fresh.
# Ensures Xvfb is running on :99, mihomo proxy is reachable, env is set.

set -e

XVFB=/home/yuliu/xvfb_root/usr/bin/Xvfb
CHROME_BIN=/home/yuliu/chrome/chrome-linux64/chrome
CHROMEDRIVER=/home/yuliu/chromedriver-linux64/chromedriver
HELPER=/home/yuliu/no1_agent/search_helper.py
LOG=/home/yuliu/no1_agent/search_helper.log
UDD=/home/yuliu/no1_chrome_udd_linux  # Linux path, not Windows
PROXY_URL=${NO1_PROXY:-http://127.0.0.1:7897}

mkdir -p "$UDD"

export DISPLAY=:99
export NO1_CHROME_BIN=$CHROME_BIN
export NO1_CHROMEDRIVER_BIN=$CHROMEDRIVER
export NO1_CHROME_UDD=$UDD
export NO1_PROXY=$PROXY_URL
export PATH=$HOME/node-local/bin:$PATH

# 1. Xvfb
if ! pgrep -f "Xvfb :99" >/dev/null; then
    echo "[$(date)] starting Xvfb :99"
    nohup $XVFB :99 -screen 0 1280x1024x24 -nolisten tcp >/dev/null 2>&1 &
    sleep 2
fi

# 2. mihomo proxy (use local 127.0.0.1:7897)
# v13.2: probe via minimax API instead of Google — mihomo mihomo configs may
# whitelist only specific domains, so Google requests fail even when mihomo
# is alive. minimax 401/200/403 all indicate proxy-forwarded HTTP response
# (alive); empty 000 means connection refused / timeout (truly dead).
NO1_PROXY_HEALTH=$(curl -sS --max-time 3 -x "$PROXY_URL" https://api.minimaxi.com/anthropic -o /dev/null -w '%{http_code}' 2>/dev/null)
if [ -z "$NO1_PROXY_HEALTH" ] || [ "$NO1_PROXY_HEALTH" = "000" ]; then
    echo "[$(date)] WARN: mihomo $PROXY_URL not reachable (probe=$NO1_PROXY_HEALTH), trying LAN 127.0.0.1:7897"
    export NO1_PROXY=http://127.0.0.1:7897
fi

# 2b. auto-pick lowest-latency healthy node (mihomo REST, localhost 9097)
if curl -sS --max-time 2 http://127.0.0.1:9097/proxies -o /dev/null 2>/dev/null; then
    echo "[$(date)] auto-selecting best mihomo node..."
    python3 -u /home/yuliu/no1_agent/auto_select_node.py 2>&1 | tail -5
fi

# 3. search_helper — also kill stale Chrome + chromedriver (orphans from prev runs)
# Otherwise new chromedriver binds random port but old Chrome stays on old port,
# and "cannot connect to chrome at <random>" failure.
pkill -9 -f "search_helper.py" 2>/dev/null || true
pkill -9 -x chromedriver 2>/dev/null || true
pkill -9 -f "chrome-linux64/chrome" 2>/dev/null || true
sleep 1
echo "[$(date)] starting search_helper on :18799 (proxy=$NO1_PROXY)"
cd /home/yuliu/no1_agent
nohup python3 -u $HELPER >$LOG 2>&1 </dev/null &
disown
sleep 2

# 4. health check
if curl -sS --max-time 5 http://127.0.0.1:18799/health | grep -q ok; then
    echo "[$(date)] search_helper OK"
    exit 0
else
    echo "[$(date)] search_helper health check FAILED"
    tail -20 $LOG
    exit 1
fi