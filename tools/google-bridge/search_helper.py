"""search_helper v23.7 — undetected-chromedriver + stealth + mihomo proxy + CAPTCHA backoff + cooldown + 7d default + honeypot + query-metrics fields (engine/vendor/query_role) + faulthandler SIGUSR1 + Linux UDD fallback + vendor/role URL params + /export with vendor/role filters + JSON Lines export.

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
from urllib.parse import urlparse, parse_qs, unquote

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
faulthandler.register(signal.SIGUSR1)

# Lazy import: only load selenium when actually serving requests
_uc = None
_driver = None
_user_data_dir = None
_driver_lock = None  # threading.Lock, created lazily

# Cooldown: prevent rapid-fire queries that trigger Google CAPTCHA
# - Per-request minimum: 30s between queries
# - Post-CAPTCHA: 300s (5 min) before next attempt
# - After 2 CAPTCHAs in 10 min: refuse and return empty
import threading as _th
import time as _time
_last_query_ts = [0.0]  # thread-safe via lock
_last_captcha_ts = [0.0]
_captcha_count_10m = [0]
_cooldown_lock = _th.Lock()
COOLDOWN_BETWEEN = int(os.environ.get('NO1_COOLDOWN', '30'))   # seconds
COOLDOWN_POST_CAPTCHA = 300  # 5 min after CAPTCHA
CAPTCHA_LIMIT_10M = 2  # max 2 CAPTCHAs in 10 min, then refuse

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
    # v23.7 (2026-08-01): platform-aware fallback. Previously this was a hardcoded
    # Windows path which on Linux would create a literal-named directory
    # "C:\Users\520hh\no1_chrome_udd" inside no1_agent/ — discovered when scp
    # restore warned "Server sent suspect path". Fixed by selecting platform default.
    if sys.platform == 'win32':
        _default_udd = r'C:\Users\520hh\no1_chrome_udd'
    else:
        _default_udd = '/home/yuliu/no1_chrome_udd_linux'
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
                chrome_bin = '/home/yuliu/chrome/chrome-linux64/chrome'
        kwargs['browser_executable_path'] = chrome_bin
        driver_bin = os.environ.get('NO1_CHROMEDRIVER_BIN')
        if driver_bin:
            kwargs['driver_executable_path'] = driver_bin
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


def search_google_stealth(query: str, num: int = 10, since: str = '24h',
                           vendor: str = '?', query_role: str = 'primary'):
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

    # Cooldown gate
    with _cooldown_lock:
        now = _time.time()
        if _last_captcha_ts[0] > 0 and now - _last_captcha_ts[0] < COOLDOWN_POST_CAPTCHA:
            wait_s = int(COOLDOWN_POST_CAPTCHA - (now - _last_captcha_ts[0]))
            print(f'[cooldown] post-CAPTCHA lockout, {wait_s}s remaining, skip', flush=True)
            _honeypot_skip(query, num, since, f'post_captcha_lockout_{wait_s}s')
            return []
        if _captcha_count_10m[0] >= CAPTCHA_LIMIT_10M:
            print(f'[cooldown] CAPTCHA limit ({CAPTCHA_LIMIT_10M}/10min) hit, skip', flush=True)
            _honeypot_skip(query, num, since, 'captcha_limit_10m')
            return []
        if _last_query_ts[0] > 0:
            since_last = now - _last_query_ts[0]
            if since_last < COOLDOWN_BETWEEN:
                wait_s = int(COOLDOWN_BETWEEN - since_last)
                print(f'[cooldown] only {int(since_last)}s since last query, sleeping {wait_s}s', flush=True)
                _time.sleep(wait_s)
        _last_query_ts[0] = _time.time()

    driver = get_driver()
    url = f'https://www.google.com/search?q={query}&hl=en&gl=us&num={num}'
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
        return []

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
            return []

    # CAPTCHA detection: tiny HTML + "unusual traffic"
    is_captcha = (
        'unusual traffic' in html.lower() or
        'Our systems have detected' in html or
        '/sorry/index' in driver.current_url or
        (len(html) < 10000 and 'did not match any documents' not in html)
    )
    if is_captcha:
        with _cooldown_lock:
            _last_captcha_ts[0] = _time.time()
            _captcha_count_10m[0] += 1
        print(f'  CAPTCHA detected (count_10m={_captcha_count_10m[0]}), waiting 60s and retrying', flush=True)
        time.sleep(60)
        ok, html = _do_search(url)
        if not ok:
            return []
        if 'unusual traffic' in html.lower() or '/sorry/index' in driver.current_url:
            print('  CAPTCHA persists, giving up', flush=True)
            return []

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
        return []
        driver.get(url)
        time.sleep(5)

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
            'client_ip': getattr(_driver, 'session_id', '?') if results is not None else '?',
        }
        with open(honeypot, 'a', encoding='utf-8') as _hf:
            _hf.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    except Exception as _he:
        print(f'  honeypot log fail: {_he}', flush=True)

    return results


class SearchHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
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
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            path_bytes = self.path.encode('ascii', errors='replace')
            path_str = path_bytes.decode('utf-8', errors='replace')
        except Exception:
            path_str = self.path

        url = urlparse(path_str)
        if url.path == '/health':
            return self._send_json({'ok': True, 'service': 'search_helper',
                                    'version': 'v23.7', 'engine': 'undetected-chromedriver'})

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
            q = qs.get('q', [''])[0]
            try:
                q = unquote(q, encoding='utf-8', errors='replace')
            except Exception:
                pass
            num = int(qs.get('num', ['10'])[0])
            since = qs.get('since', ['7d'])[0]  # default 7d (avoid filtering 2-3 day signals)
            # v23.3 (2026-07-31): accept vendor + query_role URL params so
            # the caller can label each search for v22 honeypot schema.
            # Falls back to '?' / 'primary' if not provided (e.g. legacy
            # ad-hoc curls). SOP for Claude agent: always pass both.
            vendor = qs.get('vendor', ['?'])[0]
            query_role = qs.get('role', qs.get('query_role', ['primary']))[0]
            if not q:
                return self._send_json({'error': 'missing q'}, 400)
            try:
                results = search_google_stealth(q, num=num, since=since,
                                                  vendor=vendor, query_role=query_role)
                return self._send_json({
                    'q': q, 'count': len(results), 'num': num, 'since': since,
                    'vendor': vendor, 'role': query_role,
                    'results': results, 'engine': 'undetected-chromedriver'
                })
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
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(body)
                return
            return self._send_csv(rows, filename=base_name + '.csv')

        return self._send_json({'error': 'not found'}, 404)


def main():
    port = int(os.environ.get('SEARCH_HELPER_PORT', '18799'))
    bind = os.environ.get('SEARCH_HELPER_BIND', '0.0.0.0')
    from http.server import ThreadingHTTPServer
    server = ThreadingHTTPServer((bind, port), SearchHandler)
    print(f'search_helper v23.7 (honeypot + 7d default + cooldown + query-metrics fields + faulthandler + Linux UDD + vendor/role URL + /export JSONL) listening on {bind}:{port}', flush=True)
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
