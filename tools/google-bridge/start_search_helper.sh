#!/bin/bash
# start_search_helper.sh — start the google-bridge HTTP helper (search_helper.py).
#
# v23.8 (2026-09-09) rewrite:
#   - Locates the repo files via THIS SCRIPT'S OWN DIRECTORY (was hardcoded
#     /home/yuliu/no1_agent/*, which pointed at a different machine's home).
#   - Env vars use  : "${VAR:=default}"  so user-exported values are NEVER
#     overwritten (previously the script clobbered NO1_CHROME_BIN etc.).
#   - Platform-aware: on Windows Git Bash there is no Xvfb/pkill/ss — the
#     script prints a hint and runs `python search_helper.py` in the
#     foreground. On Linux it does the full Xvfb + proxy-check + nohup dance.
#
# Usage:
#   bash start_search_helper.sh                 # Linux: daemonise + health check
#                                               # Windows: run in foreground
#   SEARCH_HELPER_FOREGROUND=1 bash start_search_helper.sh   # force foreground on Linux too
#
# Idempotent on Linux: kills any existing instance first, then starts fresh.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

IS_WINDOWS=0
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) IS_WINDOWS=1 ;;
esac

# --- pick a python (python3 preferred, fall back to python for Anaconda/Windows)
PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
    if command -v python >/dev/null 2>&1; then
        PYTHON=python
    else
        echo "[start_search_helper] ERROR: neither python3 nor python found in PATH" >&2
        exit 1
    fi
fi

# --- defaults: `:=` only assigns when unset/empty, never overrides user exports
: "${SEARCH_HELPER_PORT:=18799}"
: "${SEARCH_HELPER_BIND:=127.0.0.1}"
: "${NO1_PROXY:=http://127.0.0.1:7897}"
: "${NO1_CHROME_UDD:=$HOME/.no1_chrome_udd}"
: "${NO1_COOLDOWN:=30}"
: "${NO1_CAPTCHA_SLEEP:=60}"
# NOTE: NO1_CHROME_BIN / NO1_CHROMEDRIVER_BIN intentionally have NO default
# here — search_helper.py auto-detects them (env → state/bin → PATH → uc
# auto-download). Only set them if auto-detection picks wrong.
export SEARCH_HELPER_PORT SEARCH_HELPER_BIND NO1_PROXY NO1_CHROME_UDD \
       NO1_COOLDOWN NO1_CAPTCHA_SLEEP

LOG_DIR="$SCRIPT_DIR/state"
LOG="$LOG_DIR/search_helper.log"
mkdir -p "$LOG_DIR"

echo "[start_search_helper] SCRIPT_DIR=$SCRIPT_DIR python=$PYTHON"
echo "[start_search_helper] port=$SEARCH_HELPER_PORT bind=$SEARCH_HELPER_BIND proxy=$NO1_PROXY udd=$NO1_CHROME_UDD"
echo "[start_search_helper] chrome_bin=${NO1_CHROME_BIN:-<auto-detect>} chromedriver=${NO1_CHROMEDRIVER_BIN:-<auto-detect>}"

if [ "$IS_WINDOWS" -eq 1 ]; then
    echo "[start_search_helper] Windows Git Bash detected: no Xvfb/pkill/ss here."
    echo "[start_search_helper] 如需手动启动，请直接:  python \"$SCRIPT_DIR/search_helper.py\""
    echo "[start_search_helper] Windows 无 Linux 的 Xvfb/pkill，跳过守护流程，前台启动..."
    # Foreground is the sane default on Windows (no nohup/disown semantics);
    # chromedriver must be provided by the user (see README Windows section).
    exec "$PYTHON" -u "$SCRIPT_DIR/search_helper.py"
fi

# ===================== Linux flow below =====================

# 1. Xvfb (Linux only): headed Chrome needs an X display. Use the Xvfb from
#    PATH when available; if neither PATH-Xvfb nor a running display exists,
#    warn but continue (search_helper defaults DISPLAY=:99 itself).
if [ -z "${DISPLAY:-}" ]; then
    export DISPLAY=:99
fi
if command -v Xvfb >/dev/null 2>&1; then
    if ! (command -v pgrep >/dev/null 2>&1 && pgrep -f "Xvfb $DISPLAY" >/dev/null); then
        echo "[$(date)] starting Xvfb $DISPLAY"
        nohup Xvfb "$DISPLAY" -screen 0 1280x1024x24 -nolisten tcp >/dev/null 2>&1 &
        sleep 2
    fi
else
    echo "[$(date)] WARN: Xvfb not in PATH and DISPLAY=${DISPLAY:-<unset>} — Chrome needs a display"
fi

# 2. mihomo proxy health (warn only — search_helper still starts without it,
#    searches will just fail until a proxy is up)
PROXY_CODE=$(curl -sS --max-time 3 -x "$NO1_PROXY" http://connect.rom.miui.com/generate_204 -o /dev/null -w '%{http_code}' 2>/dev/null || true)
if [ -z "$PROXY_CODE" ] || [ "$PROXY_CODE" = "000" ]; then
    echo "[$(date)] WARN: mihomo $NO1_PROXY not reachable (probe=$PROXY_CODE) — continuing; /search will fail until proxy is up"
fi

# 2b. auto-pick lowest-latency mihomo node (optional; only if mihomo REST is up)
if curl -sS --max-time 2 http://127.0.0.1:9097/proxies -o /dev/null 2>/dev/null; then
    echo "[$(date)] auto-selecting best mihomo node..."
    "$PYTHON" -u "$SCRIPT_DIR/auto_select_node.py" 2>&1 | tail -5
fi

# 3. kill stale instances (Linux only; also orphaned chrome/chromedriver)
if command -v pkill >/dev/null 2>&1; then
    pkill -9 -f "search_helper.py" 2>/dev/null || true
    pkill -9 -x chromedriver 2>/dev/null || true
    pkill -9 -f "chrome-linux64/chrome" 2>/dev/null || true
    sleep 1
fi

echo "[$(date)] starting search_helper on :$SEARCH_HELPER_PORT (proxy=$NO1_PROXY)"
if [ "${SEARCH_HELPER_FOREGROUND:-0}" = "1" ]; then
    exec "$PYTHON" -u "$SCRIPT_DIR/search_helper.py"
fi
nohup "$PYTHON" -u "$SCRIPT_DIR/search_helper.py" >"$LOG" 2>&1 </dev/null &
if command -v disown >/dev/null 2>&1; then disown; fi
sleep 2

# 4. health check
if curl -sS --max-time 5 "http://127.0.0.1:$SEARCH_HELPER_PORT/health" | grep -q ok; then
    echo "[$(date)] search_helper OK (log: $LOG)"
    exit 0
else
    echo "[$(date)] search_helper health check FAILED"
    tail -20 "$LOG" || true
    exit 1
fi
