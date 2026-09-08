#!/bin/bash
# start_mihomo.sh — start the mihomo proxy used by google-bridge.
#
# v23.8 (2026-09-09) rewrite:
#   - Locates the mihomo binary via env override or this script's own
#     directory (was hardcoded /home/yuliu/proxy/mihomo — someone else's home).
#   - Env vars use  : "${VAR:=default}"  / ${VAR:-default}  so user-exported
#     values are never overwritten.
#   - Missing binary → clear error message + graceful exit 1 (no crash,
#     works on Windows Git Bash where pkill/ss don't exist).
#
# Env overrides:
#   NO1_MIHOMO_BIN  path to the mihomo executable
#   NO1_MIHOMO_DIR  mihomo working/config dir (default: binary's dir)
#   NO1_MIHOMO_LOG  log file path
#   NO1_PROXY       proxy endpoint used for the health probe (default 127.0.0.1:7897)
#
# Idempotent: if 7897 is already forwarding, skips restart.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MIHOMO_BIN="${NO1_MIHOMO_BIN:-$SCRIPT_DIR/state/bin/mihomo}"
MIHOMO_DIR="${NO1_MIHOMO_DIR:-$(dirname "$MIHOMO_BIN")}"
LOG="${NO1_MIHOMO_LOG:-$SCRIPT_DIR/state/mihomo.log}"
PROXY_URL="${NO1_PROXY:-http://127.0.0.1:7897}"
CONTROL_PORT="${NO1_MIHOMO_CONTROL_PORT:-9097}"

if ! command -v curl >/dev/null 2>&1; then
    echo "[start_mihomo] ERROR: curl is required but not in PATH" >&2
    exit 1
fi

mkdir -p "$(dirname "$LOG")"

# Kill any existing mihomo first (pkill is absent on Windows Git Bash — skip)
if command -v pkill >/dev/null 2>&1; then
    pkill -9 -x mihomo 2>/dev/null || true
    sleep 1
fi

# Quick health check: if the proxy already forwards, skip restart
PROBE=$(curl -sS --max-time 3 -x "$PROXY_URL" https://api.minimaxi.com/anthropic -o /dev/null -w '%{http_code}' 2>/dev/null || true)
if [ -n "$PROBE" ] && [[ "$PROBE" =~ ^[1-5][0-9][0-9]$ ]]; then
    echo "[$(date)] mihomo already healthy on $PROXY_URL (probe=$PROBE), skip restart"
    exit 0
fi

# Binary must exist — fail with a clear, actionable message
if [ ! -x "$MIHOMO_BIN" ]; then
    echo "[$(date)] ERROR: mihomo binary not found or not executable:" >&2
    echo "    $MIHOMO_BIN" >&2
    echo "  Fix: install mihomo (https://github.com/MetaCubeX/mihomo) and either" >&2
    echo "    - place it at tools/google-bridge/state/bin/mihomo (chromedriver-style drop-in), or" >&2
    echo "    - export NO1_MIHOMO_BIN=/path/to/mihomo and NO1_MIHOMO_DIR=/path/to/config" >&2
    exit 1
fi

echo "[$(date)] starting mihomo (binary=$MIHOMO_BIN config=$MIHOMO_DIR)"
cd "$MIHOMO_DIR"
nohup "$MIHOMO_BIN" -d "$MIHOMO_DIR" > "$LOG" 2>&1 </dev/null &
if command -v disown >/dev/null 2>&1; then disown; fi
sleep 3

# Verify it came up: ss is Linux-only; fall back to probing the control port,
# then to an actual proxied request.
if command -v ss >/dev/null 2>&1 && ss -lntp 2>/dev/null | grep -q ":7897"; then
    echo "[$(date)] mihomo OK on 7897"
    exit 0
fi
if curl -sS --max-time 2 "http://127.0.0.1:$CONTROL_PORT/version" -o /dev/null 2>/dev/null; then
    echo "[$(date)] mihomo OK (control port $CONTROL_PORT answering)"
    exit 0
fi
PROBE=$(curl -sS --max-time 3 -x "$PROXY_URL" https://api.minimaxi.com/anthropic -o /dev/null -w '%{http_code}' 2>/dev/null || true)
if [ -n "$PROBE" ] && [[ "$PROBE" =~ ^[1-5][0-9][0-9]$ ]]; then
    echo "[$(date)] mihomo OK (proxy $PROXY_URL forwarding, probe=$PROBE)"
    exit 0
fi

echo "[$(date)] mihomo FAILED to come up (log: $LOG)"
tail -20 "$LOG" || true
exit 1
