#!/bin/bash
# no1_agent — start_mihomo.sh
# Idempotent: kills any existing mihomo instance first, then starts fresh.
# Use from @reboot cron or manual invocation.

set -e

MIHOMO=/home/yuliu/proxy/mihomo
CONFIG=/home/yuliu/proxy
LOG=/home/yuliu/proxy/mihomo.log

mkdir -p "$(dirname "$LOG")"

# Kill any existing mihomo (port 7897 / 9097)
pkill -9 -x mihomo 2>/dev/null || true
sleep 1

# Quick health check: if 7897 already listening AND forwarding, skip restart
if curl -sS --max-time 3 -x http://127.0.0.1:7897 https://api.minimaxi.com/anthropic -o /dev/null -w "%{http_code}" 2>/dev/null | grep -qE "^[1-5][0-9][0-9]$"; then
    echo "[$(date)] mihomo already healthy on 7897, skip restart"
    exit 0
fi

echo "[$(date)] starting mihomo (config=$CONFIG)"
cd "$CONFIG"
nohup "$MIHOMO" -d "$CONFIG" > "$LOG" 2>&1 </dev/null &
disown
sleep 3

# Verify it came up
if ss -lntp 2>/dev/null | grep -q ":7897"; then
    echo "[$(date)] mihomo OK on 7897"
    exit 0
else
    echo "[$(date)] mihomo FAILED to bind 7897"
    tail -20 "$LOG"
    exit 1
fi
