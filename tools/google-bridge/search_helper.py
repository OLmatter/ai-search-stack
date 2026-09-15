"""search_helper v23.9 — undetected-chromedriver + stealth + mihomo proxy + CAPTCHA backoff + cooldown + 7d default + honeypot + query-metrics fields (engine/vendor/query_role) + faulthandler SIGUSR1 (POSIX only) + portable defaults (UDD/bind/chromedriver lookup) + vendor/role URL params + /export with vendor/role filters + JSON Lines export. v23.9: CAPTCHA/lockout answers HTTP 503 (never disguised as 200/0-results) + zero-result page dump for diagnosis.

Endpoints:
  GET /search?q=...&num=10&since=24h

v22 honeypot schema additions (search_google_stealth log_entry):
  - engine      : 'chrome_bridge' (always for this server)
  - vendor      : target AI vendor (claude / chatgpt / gemini / openai / cursor / vercel / '?')
  - query_role  : 'primary' / 'fallback' / 'verify' — drives v21 stage 5 metrics

Why: v21 stage 5.3 requires these fields. Without them, agg_query_metrics.py
cannot compute vendor coverage, fallback hit rate, or query role breakdown.

Endpoints:
  GET /search?q=...&num=10&since=24h

Returns real Google search results via undetected-chromedriver (stealth
Chrome that bypasses Google's "unusual traffic" detection).

Architecture:
  - Windows: real headed Chrome via undetected-chromedriver
  - Linux:   Xvfb + headed Chrome via undetected-chromedriver
  - Single user-data-dir persisted across runs (cookies, fingerprints, trust)
  - CDP + DevTools Protocol (no Selenium overhead for fast search)
"""
import sys, json, os, time, traceback, shutil
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs, unquote, urlencode

# Force UTF-8 stdout
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# v23.4 (2026-07-31): DISPLAY fallback for headless X server. Required on
# Linux because undetected_chromedriver creates Chrome with headless=False,
# which needs an X display to render. start_search_helper.sh normally
# exports DISPLAY=:99, but if we ever launch search_helper.py directly
# (debug, agent_runner.py, watchdog), DISPLAY is empty and Chrome exits
# silently → chromedriver 44903 connection refused. Default to :99 here.
if sys.platform != 'win32' and not os.environ.get('DISPLAY'):
    os.environ['DISPLAY'] = ':99'

# v23 (2026-07-31): enable faulthandler + register SIGUSR1 so we can dump
# Python tracebacks without killing the process. Used to debug Chrome
# bridge hangs (SIGUSR1 dumps to stderr; nohup 2>&1 routes to log file).
# NOTE: faulthandler.enable() alone only registers SIGSEGV/SIGFPE/SIGABRT/
# SIGBUS/SIGILL — SIGUSR1 must be explicitly registered or Python's default
# SIG_DFL handler terminates the process. Confirmed by 23:39 + 23:43
# incidents where SIGUSR1 silently killed search_helper.
import faulthandler
import signal
faulthandler.enable()
# v23.8 (2026-09-09): platform guard. SIGUSR1 does not exist on Windows
# (Anaconda Python has neither signal.SIGUSR1 nor faulthandler.register),
# so unconditional registration crashed with AttributeError at import time.
# Register only where the platform supports it; silently skip elsewhere.
if hasattr(signal, 'SIGUSR1') and hasattr(faulthandler, 'register'):
    faulthandler.register(signal.SIGUSR1)

# Lazy import: only load selenium when actually serving requests
_uc = None
_driver = None
_user_data_dir = None
_driver_lock = None  # threading.Lock, created lazily

# Cooldown: prevent rapid-fire queries that trigger Google CAPTCHA
# - Per-request minimum: 30s between queries
# - Post-CAPTCHA: 300s (5 min) before next attempt
# - After 2 CAPTCHAs in a rolling 10-min window: refuse (503) until the
#   window drains — the counter DECAYS, a CAPTCHA hours ago must not
#   permanently lock the service (v23.9: was an ever-growing int).
import threading as _th
import time as _time
from collections import deque as _deque
_last_query_ts = [0.0]  # thread-safe via lock
_last_captcha_ts = [0.0]
_captcha_window: list = []  # timestamps of recent CAPTCHAs (rolling 10 min)
_cooldown_lock = _th.Lock()
COOLDOWN_BETWEEN = int(os.environ.get('NO1_COOLDOWN', '30'))   # seconds
COOLDOWN_POST_CAPTCHA = 300  # 5 min after CAPTCHA
CAPTCHA_LIMIT_10M = 2  # max 2 CAPTCHAs in 10 min, then refuse
CAPTCHA_WINDOW_S = 600  # rolling window length


def _prune_captcha_window() -> int:
    """Caller must hold _cooldown_lock. Returns CAPTCHAs still in window."""
    cutoff = _time.time() - CAPTCHA_WINDOW_S
    while _captcha_window and _captcha_window[0] < cutoff:
        _captcha_window.pop(0)
    return len(_captcha_window)
# v23.8 (2026-09-09): tunable via env so tests/slow links can adjust without
# editing code. Sleep is always taken OUTSIDE _cooldown_lock so concurrent
# requests are not serialised behind a sleeper.
CAPTCHA_SLEEP = int(os.environ.get('NO1_CAPTCHA_SLEEP', '60'))  # wait after CAPTCHA before retry
# Heuristic: a real Google SERP is a large page (>100KB). A tiny HTML that
# does NOT contain "did not match any documents" is almost always a
# CAPTCHA / sorry page, not a genuine zero-result page. This threshold is a
# HEURISTIC, not a contract — tune via NO1_MIN_HTML_LEN if Google changes
# page sizes (e.g. for very sparse result layouts).
MIN_HTML_LEN = int(os.environ.get('NO1_MIN_HTML_LEN', '10000'))

def _ensure_lock():
    global _driver_lock
    import threading as _th
    if _driver_lock is None:
        _driver_lock = _th.Lock()
    return _driver_lock


def _chrome_quick_check():
    """Lightweight Chrome liveness probe — does NOT trigger rebuild.

    Returns (alive: bool, info: str, driver_state: str).
    Uses current_url (faster than .title which renders DOM).
    - Driver None + last error recent (<60s) → (False, err, 'broken')     — Chrome startup just failed
    - Driver None + no recent error          → (False, 'no_driver', 'uninitialized')
    - Driver set, probe ok                   → (True, 'ok', 'ready')
    - Driver set, probe err                  → (False, error[:80], 'broken')  — Chrome crashed mid-run
    """
    if _driver is None:
        # v16: distinguish "never tried" vs "tried and failed"
        last_err_ts = _chrome_last_error_ts[0]
        if last_err_ts > 0 and (_time.time() - last_err_ts) < 60:
            return False, _chrome_last_error_msg[0] or 'startup_failed', 'broken'
        return False, 'no_driver', 'uninitialized'
    try:
        # current_url is a simple attribute fetch, no network/DOM work
        _ = _driver.current_url
        return True, 'ok', 'ready'
    except Exception as e:
        return False, str(e)[:80], 'broken'


def _honeypot_skip(query, num, since, reason):
    """Log a skipped search to honeypot."""
    try:
        honeypot = os.path.join(os.path.dirname(__file__) or '.', 'state', 'honeypot.jsonl')
        with open(honeypot, 'a', encoding='utf-8') as _hf:
            _hf.write(json.dumps({
                'ts': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                'kind': 'search_skipped', 'q': query, 'num': num, 'since': since,
                'reason': reason,
                'engine': 'chrome_bridge',
            }, ensure_ascii=False) + '\n')
    except Exception:
        pass

_chrome_last_error_ts = [0.0]  # v16: track last Chrome startup failure
_chrome_last_error_msg = ['']


def _find_chromedriver():
    """v23.8: locate a chromedriver binary without hardcoding machine paths.

    Priority:
      1. NO1_CHROMEDRIVER_BIN env var (explicit, wins)
      2. <this script's dir>/state/bin/chromedriver(.exe)  — drop-in location
      3. shutil.which('chromedriver')                      — system PATH
      4. None → caller lets undetected-chromedriver auto-download
    """
    env_bin = os.environ.get('NO1_CHROMEDRIVER_BIN')
    if env_bin:
        return env_bin
    here = os.path.dirname(os.path.abspath(__file__))
    exe_name = 'chromedriver.exe' if sys.platform == 'win32' else 'chromedriver'
    cand = os.path.join(here, 'state', 'bin', exe_name)
    if os.path.isfile(cand):
        return cand
    return shutil.which('chromedriver')


def get_driver():
    """Lazy-init undetected-chromedriver (one per process, lock-protected)."""
    global _uc, _driver, _user_data_dir
    lock = _ensure_lock()
    with lock:
        if _driver is not None:
            try:
                _driver.title  # health-check
                return _driver
            except Exception:
                _driver = None
    import undetected_chromedriver as uc  # noqa: E402
    _uc = uc

    # Persistent user-data-dir: keep cookies, fingerprint, trust between runs.
    # v23.8 (2026-09-09): portable default. Previously hardcoded per-machine
    # paths (a former maintainer's home dir on Windows, /home/yuliu/... on
    # Linux) which broke on any other account/host. Now defaults to
    # ~/.no1_chrome_udd on every platform; override with NO1_CHROME_UDD.
    from pathlib import Path
    _default_udd = str(Path.home() / '.no1_chrome_udd')
    _user_data_dir = os.environ.get('NO1_CHROME_UDD', _default_udd)
    os.makedirs(_user_data_dir, exist_ok=True)

    options = uc.ChromeOptions()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-gpu')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--lang=en-US,en')
    options.add_argument(f'--user-data-dir={_user_data_dir}')
    options.add_argument('--disable-blink-features=AutomationControlled')

    # Proxy: on Windows use 127.0.0.1:7897 (mihomo local);
    # on Linux, use mihomo via NO1_PROXY env var (e.g. http://your-mihomo-host:7897)
    if sys.platform == 'win32':
        proxy_url = os.environ.get('NO1_PROXY', 'socks5://127.0.0.1:7897')
    else:
        proxy_url = os.environ.get('NO1_PROXY', 'http://127.0.0.1:7897')
    options.add_argument(f'--proxy-server={proxy_url}')

    with lock:
        # On Linux, undetected-chromedriver defaults to /usr/bin/google-chrome.
        # Override via browser_executable_path if NO1_CHROME_BIN is set.
        # Also pass driver_executable_path to skip chromedriver download
        # (servers often can't reach Google's storage directly).
        kwargs = dict(
            options=options,
            headless=False,
            use_subprocess=True,
            suppress_welcome=True,
        )
        chrome_bin = os.environ.get('NO1_CHROME_BIN')
        # v23.1 (2026-07-31): default fallback path so get_driver() works even
        # if start_search_helper.sh never ran (e.g. agent_runner.py launched
        # search_helper directly). Without this fallback, uc.Chrome() looks
        # for /usr/bin/google-chrome (not present on this server), and
        # selenium raises "TypeError: Binary Location Must be a String" at
        # line 372 of undetected_chromedriver/__init__.py.
        if not chrome_bin:
            if sys.platform == 'win32':
                chrome_bin = r'C:\Program Files\Google\Chrome\Application\chrome.exe'
            else:
                # v23.8: portable Linux default — look on PATH only
                # (google-chrome / chromium). No per-user legacy fallbacks.
                # Override with NO1_CHROME_BIN if Chrome lives elsewhere.
                chrome_bin = (shutil.which('google-chrome')
                              or shutil.which('google-chrome-stable')
                              or shutil.which('chromium')
                              or shutil.which('chromium-browser'))
        kwargs['browser_executable_path'] = chrome_bin
        driver_bin = _find_chromedriver()
        if driver_bin:
            print(f'[get_driver] chromedriver: {driver_bin}', flush=True)
            kwargs['driver_executable_path'] = driver_bin
        else:
            print('[get_driver] no chromedriver found (env/state/bin/PATH); '
                  'letting undetected-chromedriver auto-download', flush=True)
        try:
            _driver = uc.Chrome(**kwargs)
            _chrome_last_error_ts[0] = 0.0
            _chrome_last_error_msg[0] = ''
        except Exception as _start_exc:
            # v16: record failure so _chrome_quick_check can surface it
            _chrome_last_error_ts[0] = _time.time()
            _chrome_last_error_msg[0] = str(_start_exc)[:120]
            print(f'[get_driver] Chrome startup FAILED: {_start_exc}', flush=True)
            raise
    return _driver


class CaptchaBlocked(RuntimeError):
    """v23.9: Google CAPTCHA/consent page persisted after backoff.

    Raised instead of silently returning [] — a CAPTCHA block must be
    distinguishable (HTTP 503) from genuinely zero results (HTTP 200).
    """
    pass


class PageLoadError(RuntimeError):
    """v23.8: Google page failed to LOAD at all (network dead / Chrome dead).

    Raised instead of silently returning [] so the HTTP layer can answer
    502 + {"error": ...} and callers can distinguish "no results" from
    "network is dead". Previously a load failure returned HTTP 200 with
    count=0, which callers misread as a genuinely empty result set.
    """


def search_google_stealth(query: str, num: int = 10, since: str = '24h',
                           vendor: str = '?', query_role: str = 'primary',
                           client_ip: str = '?'):
    """Run a Google search via undetected-chromedriver and return results.

    Returns list of {title, url, snippet, platform, date} dicts.
    Handles CAPTCHA + enforces cooldown to avoid Google rate limiting.

    Throttling:
    - 30s minimum between queries
    - 300s cooldown after CAPTCHA
    - After 2 CAPTCHAs in 10 min, refuse with empty (silently degrade)
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    import re
    from urllib.parse import unquote

    # Cooldown gate.
    # v23.8 (2026-09-09): read the remaining wait UNDER the lock, then sleep
    # OUTSIDE the lock (previously time.sleep() ran while holding
    # _cooldown_lock, serialising every concurrent request behind a 30s nap).
    # After sleeping, loop once more to re-check under the lock; hard skips
    # (post-CAPTCHA lockout, CAPTCHA rate limit) raise immediately (v23.9:
    # answered as HTTP 503 captcha_blocked, never as 200/0-results).
    while True:
        wait_s = 0
        with _cooldown_lock:
            now = _time.time()
            if _last_captcha_ts[0] > 0 and now - _last_captcha_ts[0] < COOLDOWN_POST_CAPTCHA:
                skip_s = int(COOLDOWN_POST_CAPTCHA - (now - _last_captcha_ts[0]))
                print(f'[cooldown] post-CAPTCHA lockout, {skip_s}s remaining, skip', flush=True)
                _honeypot_skip(query, num, since, f'post_captcha_lockout_{skip_s}s')
                raise CaptchaBlocked(
                    f'post-CAPTCHA lockout, {skip_s}s remaining (cooldown gate)')
            if _prune_captcha_window() >= CAPTCHA_LIMIT_10M:
                print(f'[cooldown] CAPTCHA limit ({CAPTCHA_LIMIT_10M}/10min) hit, skip', flush=True)
                _honeypot_skip(query, num, since, 'captcha_limit_10m')
                raise CaptchaBlocked(
                    f'CAPTCHA rate limit hit ({CAPTCHA_LIMIT_10M}/10min)')
            if _last_query_ts[0] > 0:
                since_last = now - _last_query_ts[0]
                if since_last < COOLDOWN_BETWEEN:
                    wait_s = max(int(COOLDOWN_BETWEEN - since_last), 1)
                    print(f'[cooldown] only {int(since_last)}s since last query, '
                          f'sleeping {wait_s}s (outside lock)', flush=True)
            if wait_s <= 0:
                # Claim the slot now so parallel callers queue behind us.
                _last_query_ts[0] = _time.time()
        if wait_s > 0:
            _time.sleep(wait_s)  # lock NOT held
            continue
        break

    driver = get_driver()
    # v23.8 (2026-09-09): build the query string with urlencode — the query was
    # previously interpolated raw, so spaces/&/CJK produced broken URLs.
    url = 'https://www.google.com/search?' + urlencode(
        {'q': query, 'hl': 'en', 'gl': 'us', 'num': num})
    # Default: no time filter (since 7d is too aggressive for most signals)
    # 支付漏洞/exploit 信号通常 2-3 天后才稳定, 24h 滤掉太多
    if since == '24h':
        url += '&tbs=qdr:d'
    elif since == '7d':
        url += '&tbs=qdr:w'
    elif since == '30d':
        url += '&tbs=qdr:m'
    # since == 'none' or unset → no filter (default)

    print(f'[search] q={query!r} num={num} since={since!r} url={url[:80]}', flush=True)

    def _do_search(url_to_load):
        start = time.time()
        try:
            driver.set_page_load_timeout(45)
            driver.get(url_to_load)
        except Exception as e:
            print(f'  load error: {e}', flush=True)
            return False, ''
        elapsed = time.time() - start
        print(f'  loaded in {elapsed:.1f}s, url={driver.current_url[:80]}', flush=True)
        time.sleep(3)
        return True, driver.page_source

    # First attempt
    ok, html = _do_search(url)
    if not ok:
        raise PageLoadError(f'Google page failed to load for q={query!r} '
                            f'(network dead / Chrome dead / timeout)')

    # Handle consent page
    if 'consent.google.com' in driver.current_url or 'Before you continue' in html:
        print('  consent page, clicking Accept all', flush=True)
        for sel in ['#L2AGLb', 'button[aria-label*="Accept"]', '//button[contains(., "Accept all")]']:
            try:
                btn = driver.find_element(By.CSS_SELECTOR if sel.startswith('#') or sel.startswith('button') else By.XPATH, sel)
                if btn.is_displayed():
                    btn.click()
                    time.sleep(5)
                    break
            except Exception:
                continue
        ok, html = _do_search(url)
        if not ok:
            raise PageLoadError(f'Google page failed to load after consent click, q={query!r}')

    # CAPTCHA detection: tiny HTML + "unusual traffic" (see MIN_HTML_LEN note:
    # the size check is a heuristic, tunable via NO1_MIN_HTML_LEN)
    is_captcha = (
        'unusual traffic' in html.lower() or
        'Our systems have detected' in html or
        '/sorry/index' in driver.current_url or
        (len(html) < MIN_HTML_LEN and 'did not match any documents' not in html)
    )
    if is_captcha:
        with _cooldown_lock:
            _last_captcha_ts[0] = _time.time()
            _captcha_window.append(_time.time())
            _prune_captcha_window()
            captcha_count = len(_captcha_window)
        # v23.8: wait is configurable (NO1_CAPTCHA_SLEEP, default 60s) and is
        # taken WITHOUT holding _cooldown_lock, so other requests are not
        # serialised behind it.
        print(f'  CAPTCHA detected (count_10m={captcha_count}), '
              f'waiting {CAPTCHA_SLEEP}s and retrying', flush=True)
        time.sleep(CAPTCHA_SLEEP)
        ok, html = _do_search(url)
        if not ok:
            raise PageLoadError(f'Google page failed to load after CAPTCHA backoff, q={query!r}')
        if 'unusual traffic' in html.lower() or '/sorry/index' in driver.current_url:
            print('  CAPTCHA persists, giving up', flush=True)
            raise CaptchaBlocked(
                f'Google CAPTCHA persisted after {CAPTCHA_SLEEP}s backoff '
                f'(sorry page), q={query!r}')

    # If still showing consent / unusual, bail
    if 'consent.google.com' in driver.current_url or 'unusual traffic' in html.lower():
        print('  blocked, no results', flush=True)
        try:
            honeypot = os.path.join(os.path.dirname(__file__) or '.', 'state', 'honeypot.jsonl')
            with open(honeypot, 'a', encoding='utf-8') as _hf:
                _hf.write(json.dumps({
                    'ts': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                    'kind': 'search', 'q': query, 'num': num, 'since': since,
                    'count': 0, 'captcha': True, 'note': 'blocked_after_captcha',
                    'engine': 'chrome_bridge', 'vendor': vendor, 'query_role': query_role,
                }, ensure_ascii=False) + '\n')
        except Exception:
            pass
        raise CaptchaBlocked(
            f'Google blocked the query (consent/unusual traffic), q={query!r}')
    # (v23.8: removed unreachable driver.get()/sleep() that used to follow the
    # return above)

    # Wait for results to render (Google loads results via JS)
    time.sleep(3)

    # Try to extract results from various Google DOM structures
    results = []

    # Method 1: Try .g, [data-hveid], .MjjYud, .kb0PBd, .hlcw0c (modern Google)
    for container_sel in ['div.g', 'div[data-hveid]', 'div.MjjYud', 'div.kb0PBd', 'div.hlcw0c']:
        try:
            for r in driver.find_elements(By.CSS_SELECTOR, container_sel):
                try:
                    title_el = None
                    for tsel in ['h3', 'div[role="heading"]']:
                        try:
                            title_el = r.find_element(By.CSS_SELECTOR, tsel)
                            if title_el.text.strip():
                                break
                        except Exception:
                            continue
                    if not title_el:
                        continue
                    title = title_el.text.strip()
                    a = r.find_element(By.CSS_SELECTOR, 'a')
                    href = a.get_attribute('href') or ''
                    if href.startswith('/url?q='):
                        href = unquote(href.split('/url?q=')[1].split('&')[0])
                    if title and href.startswith('http'):
                        snippet = ''
                        try:
                            for ssel in ['[data-content-feature]', '.VwiC3b', '.yXK7lf']:
                                try:
                                    snippet_el = r.find_element(By.CSS_SELECTOR, ssel)
                                    snippet = snippet_el.text.strip()[:200]
                                    if snippet: break
                                except Exception:
                                    continue
                        except Exception:
                            pass
                        results.append({
                            'title': title,
                            'url': href,
                            'snippet': snippet,
                            'platform': 'generic',
                            'date': '',
                        })
                except Exception:
                    continue
            if results:
                break
        except Exception:
            continue

    # Method 2: JSON embedded (AF_initDataCallback)
    if not results:
        # Look for AF_initDataCallback in page_source
        import re as _re
        for m in _re.finditer(r'AF_initDataCallback\((\{key:[^}]+\}),[^,]+,(\[[^\]]+\])', driver.page_source):
            try:
                data = json.loads(m.group(2))
                # Walk and find title/url pairs (heuristic, depends on Google)
                # This is a fallback; not always reliable
                for item in data:
                    if isinstance(item, list) and len(item) >= 3:
                        pass
            except Exception:
                continue

    # 0 结果诊断：把现场 HTML 落盘，供区分"真无结果 / Google 换布局 / 同意页 /
    # CAPTCHA 变体"。页面加载失败已走 502，能到这里说明页面加载成功了。
    if not results:
        try:
            import os as _os
            diag_dir = _os.path.join(_os.path.dirname(__file__) or '.', 'state')
            _os.makedirs(diag_dir, exist_ok=True)
            diag_path = _os.path.join(diag_dir, 'last_zero_page.html')
            html_src = driver.page_source or ''
            with open(diag_path, 'w', encoding='utf-8') as _f:
                _f.write(html_src[:2_000_000])
            print(f'  [diag] 0 results; page html ({len(html_src)} bytes) '
                  f'saved to {diag_path} — 检查是否同意页/新布局/CAPTCHA 变体',
                  flush=True)
        except Exception as _e:
            print(f'  [diag] failed to dump zero-result page: {_e}', flush=True)

    print(f'  extracted {len(results)} results', flush=True)

    # HONEYPOT: log every search to state/honeypot.jsonl
    try:
        import os as _os
        honeypot = _os.path.join(_os.path.dirname(__file__) or '.', 'state', 'honeypot.jsonl')
        _os.makedirs(_os.path.dirname(honeypot), exist_ok=True)
        log_entry = {
            'ts': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
            'kind': 'search',
            'q': query,
            'num': num,
            'since': since,
            'count': len(results),
            'captcha': False,
            'engine': 'chrome_bridge',
            'vendor': vendor,
            'query_role': query_role,
            # v23.8: real HTTP client IP (was the chromedriver session_id —
            # meaningless and misleading in the honeypot log).
            'client_ip': client_ip,
        }
        with open(honeypot, 'a', encoding='utf-8') as _hf:
            _hf.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    except Exception as _he:
        print(f'  honeypot log fail: {_he}', flush=True)

    return results


class SearchHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _host_ok(self):
        # v3.8.1: Host whitelist — loopback name + this service's port only.
        # Blocks DNS-rebinding style CSRF (a hostile page resolving an attacker
        # hostname to 127.0.0.1 and driving Google queries through this
        # bridge). Requests without a Host header fail closed.
        host_header = self.headers.get('Host')
        if not host_header:
            return False
        host = str(host_header).strip().lower()
        name, sep, port_part = host.rpartition(':')
        if not sep:
            return False
        return (name in ('127.0.0.1', 'localhost')
                and port_part == str(self.server.server_address[1]))

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def _send_csv(self, rows, filename='honeypot.csv'):
        """Stream CSV rows to client with Content-Disposition for download."""
        import csv as _csv
        import io as _io
        buf = _io.StringIO()
        if rows:
            # Union of keys across rows (since honeypot schema evolved: v22+
            # added engine/vendor/query_role; pre-v22 rows don't have them).
            keys = []
            seen = set()
            for r in rows:
                for k in r.keys():
                    if k not in seen:
                        keys.append(k)
                        seen.add(k)
            w = _csv.DictWriter(buf, fieldnames=keys, extrasaction='ignore')
            w.writeheader()
            for r in rows:
                # Stringify nested values so CSV stays flat (timestamps,
                # objects → JSON; booleans → True/False).
                row_out = {}
                for k, v in r.items():
                    if isinstance(v, (dict, list)):
                        row_out[k] = json.dumps(v, ensure_ascii=False)
                    elif v is None:
                        row_out[k] = ''
                    else:
                        row_out[k] = v
                w.writerow(row_out)
        body = buf.getvalue().encode('utf-8-sig')  # BOM so Excel opens UTF-8
        self.send_response(200)
        self.send_header('Content-Type', 'text/csv; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._host_ok():
            return self._send_json(
                {'error': 'Forbidden: Host header not in loopback whitelist'},
                403)

        try:
            path_bytes = self.path.encode('ascii', errors='replace')
            path_str = path_bytes.decode('utf-8', errors='replace')
        except Exception:
            path_str = self.path

        url = urlparse(path_str)
        if url.path == '/health':
            return self._send_json({'ok': True, 'service': 'search_helper',
                                    'version': 'v23.9', 'engine': 'undetected-chromedriver'})

        # v16 (2026-07-30): /chrome_ready — lightweight Chrome liveness probe.
        # Returns 200 with {alive, info, driver_state} so watchdog can
        # distinguish "search_helper dead" (/health fails → restart) from
        # "Chrome dead but driver_set → probe fails" (let self-heal) and
        # "first-call pending" (driver_state=uninitialized, normal startup).
        # Only 503 when driver is set AND probe fails (true Chrome crash).
        if url.path == '/chrome_ready':
            alive, info, driver_state = _chrome_quick_check()
            status = 503 if (driver_state == 'broken') else 200
            return self._send_json({
                'alive': alive, 'info': info,
                'driver_state': driver_state,
                'service': 'search_helper', 'version': 'v16',
            }, status=status)

        if url.path in ('/search', '/search_x'):
            qs = parse_qs(url.query)
            # v23.8: parse_qs already percent-decodes q — the extra unquote()
            # here double-decoded queries containing %25xx-style escapes.
            q = qs.get('q', [''])[0]
            since = qs.get('since', ['7d'])[0]  # default 7d (avoid filtering 2-3 day signals)
            # v23.3 (2026-07-31): accept vendor + query_role URL params so
            # the caller can label each search for v22 honeypot schema.
            # Falls back to '?' / 'primary' if not provided (e.g. legacy
            # ad-hoc curls). SOP for Claude agent: always pass both.
            vendor = qs.get('vendor', ['?'])[0]
            query_role = qs.get('role', qs.get('query_role', ['primary']))[0]
            if not q:
                return self._send_json({'error': 'missing q'}, 400)
            # http.server equivalent of flask's request.remote_addr
            client_ip = self.client_address[0] if self.client_address else '?'
            try:
                # v23.9: parse num inside try — a non-numeric ?num= used to
                # raise before the handler and kill the connection; now it
                # answers 500 JSON like any other bad request.
                num = int(qs.get('num', ['10'])[0])
                results = search_google_stealth(q, num=num, since=since,
                                                  vendor=vendor, query_role=query_role,
                                                  client_ip=client_ip)
                return self._send_json({
                    'q': q, 'count': len(results), 'num': num, 'since': since,
                    'vendor': vendor, 'role': query_role,
                    'results': results, 'engine': 'undetected-chromedriver'
                })
            except CaptchaBlocked as e:
                # v23.9: CAPTCHA/consent block is NOT zero results — answer 503
                # so callers can back off or switch tools (SOP 失败回滚表).
                print(f'  CAPTCHA BLOCKED: {e}', flush=True)
                return self._send_json({'error': str(e), 'kind': 'captcha_blocked'}, 503)
            except PageLoadError as e:
                # v23.8: page did not LOAD — report 502 so callers can tell
                # "network dead" apart from "genuinely zero results" (200).
                print(f'  PAGE LOAD FAILED: {e}', flush=True)
                return self._send_json({'error': str(e), 'kind': 'page_load_failed'}, 502)
            except Exception as e:
                tb = traceback.format_exc()
                print(f'  ERROR: {e}\n{tb}', flush=True)
                return self._send_json({'error': str(e), 'trace': tb[-500:]}, 500)

        # v23.5 (2026-07-31): /export — download honeypot.jsonl as CSV.
        # v23.6 (2026-08-01): added vendor + query_role filters + format=json option.
        # Filters:
        #   ?kind=search            only search entries (default: all)
        #   ?kind=search,push       comma-separated, multiple kinds
        #   ?since=YYYY-MM-DD       only rows with ts >= since (00:00 of that day, +08:00)
        #   ?until=YYYY-MM-DD       only rows with ts < until (next-day boundary)
        #   ?q=substring            only rows where q field contains substring
        #   ?vendor=claude          only rows where vendor field == value (or in set, comma)
        #   ?role=primary           only rows where query_role field == value
        #   ?format=json            return JSON lines instead of CSV (default csv)
        # Returns CSV (or JSON) with Content-Disposition: attachment.
        # UTF-8 BOM prefix in CSV so Excel opens it without garbled CJK.
        if url.path == '/export':
            qs = parse_qs(url.query)
            kind_filter = qs.get('kind', [''])[0]
            since_day = qs.get('since', [''])[0]
            until_day = qs.get('until', [''])[0]
            q_filter = qs.get('q', [''])[0]
            vendor_filter = qs.get('vendor', [''])[0]
            role_filter = qs.get('role', [''])[0]
            fmt = qs.get('format', ['csv'])[0].lower()
            kind_set = set(k.strip() for k in kind_filter.split(',') if k.strip()) if kind_filter else None
            vendor_set = set(v.strip() for v in vendor_filter.split(',') if v.strip()) if vendor_filter else None
            role_set = set(r.strip() for r in role_filter.split(',') if r.strip()) if role_filter else None
            from datetime import datetime as _dt
            from email.utils import parsedate_to_datetime as _pdt
            def _parse_ts(s):
                # ts format: '2026-08-01T00:00:47+08:00' or '+0800' (no colon)
                if not s:
                    return 0.0
                s = s.replace('+0800', '+08:00')
                try:
                    return _dt.fromisoformat(s).timestamp()
                except Exception:
                    return 0.0
            cutoff_since = _parse_ts(since_day + 'T00:00:00+08:00') if since_day else 0.0
            cutoff_until = _parse_ts(until_day + 'T00:00:00+08:00') if until_day else 1e18
            honeypot_path = os.path.join(os.path.dirname(__file__) or '.', 'state', 'honeypot.jsonl')
            rows = []
            try:
                with open(honeypot_path, 'r', encoding='utf-8', errors='replace') as _hf:
                    for ln in _hf:
                        ln = ln.strip()
                        if not ln:
                            continue
                        try:
                            d = json.loads(ln)
                        except Exception:
                            continue
                        if kind_set and d.get('kind') not in kind_set:
                            continue
                        ts_epoch = _parse_ts(d.get('ts', ''))
                        if ts_epoch < cutoff_since or ts_epoch >= cutoff_until:
                            continue
                        if q_filter and q_filter not in (d.get('q') or ''):
                            continue
                        if vendor_set and d.get('vendor') not in vendor_set:
                            continue
                        if role_set and d.get('query_role') not in role_set:
                            continue
                        rows.append(d)
            except FileNotFoundError:
                rows = []
            # filename hint
            fn_parts = ['honeypot']
            if kind_set:
                fn_parts.append('-'.join(sorted(kind_set)))
            if vendor_set:
                fn_parts.append('v-' + '-'.join(sorted(vendor_set)))
            if role_set:
                fn_parts.append('r-' + '-'.join(sorted(role_set)))
            if since_day:
                fn_parts.append(f'from{since_day}')
            if until_day:
                fn_parts.append(f'to{until_day}')
            base_name = '_'.join(fn_parts)
            if fmt == 'json':
                # v23.6: JSON Lines output for programmatic consumers (jq, etc.)
                # Returns raw jsonl — no BOM, no CSV header. Streaming friendly.
                body = '\n'.join(json.dumps(r, ensure_ascii=False) for r in rows).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/x-ndjson; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Content-Disposition', f'attachment; filename="{base_name}.jsonl"')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)
                return
            return self._send_csv(rows, filename=base_name + '.csv')

        return self._send_json({'error': 'not found'}, 404)


def main():
    port = int(os.environ.get('SEARCH_HELPER_PORT', '18799'))
    # v23.8 (2026-09-09): default to loopback only. The old default 0.0.0.0
    # exposed an unauthenticated search proxy to the whole LAN; bind publicly
    # only via explicit SEARCH_HELPER_BIND=0.0.0.0.
    bind = os.environ.get('SEARCH_HELPER_BIND', '127.0.0.1')
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer((bind, port), SearchHandler)
    print(f'search_helper v23.9 (portable paths + encoded query + load-failure 502 + '
          f'lock-free cooldowns + tunable NO1_CAPTCHA_SLEEP/NO1_MIN_HTML_LEN) listening on {bind}:{port}', flush=True)
    print('  GET /health', flush=True)
    print('  GET /search?q=...&num=10&since=24h&vendor=claude&role=primary', flush=True)
    print('  GET /export?kind=search&since=2026-07-30&q=claude  →  CSV 下载', flush=True)
    print('  GET /export                              → 全部 honeypot', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('shutting down', flush=True)
        if _driver is not None:
            try: _driver.quit()
            except Exception: pass


if __name__ == '__main__':
    main()
