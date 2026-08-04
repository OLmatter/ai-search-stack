#!/usr/bin/env python3
"""auto_select_node — pick lowest-latency healthy proxy, switch GLOBAL to it.

Tests each candidate via mihomo REST, picks the one with lowest latency
to https://www.google.com/generate_204, then switches GLOBAL selector.

v17: added time-budget + max-candidates safeguards. Original loop tested
ALL 54 nodes with 8s timeout each = worst case 432s (7+ min). The
no1_agent_continue.sh watchdog calls this script when CAPTCHA is locked;
hanging 7+ minutes blocked the whole loop. Now: default 60s budget,
20 candidates max, returns whatever the best so far was.
"""
import sys, os, json, time, urllib.request, urllib.error

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

MIHOMO = 'http://127.0.0.1:9097'
PROXY = 'http://127.0.0.1:7897'
TEST_URL = 'https://www.google.com/generate_204'
TIMEOUT = int(os.environ.get('NO1_NODE_TIMEOUT', '5'))  # was 8s
MAX_CANDIDATES = int(os.environ.get('NO1_NODE_MAX', '20'))  # was 54
TIME_BUDGET = int(os.environ.get('NO1_NODE_BUDGET', '60'))  # v17: hard cap seconds

def list_proxies():
    with urllib.request.urlopen(f'{MIHOMO}/proxies', timeout=5) as r:
        return json.load(r)['proxies']

def switch_global(name):
    body = json.dumps({'name': name}, ensure_ascii=False).encode('utf-8')
    req = urllib.request.Request(f'{MIHOMO}/proxies/GLOBAL',
                                 data=body, method='PUT',
                                 headers={'Content-Type': 'application/json; charset=utf-8'})
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.read().decode('utf-8', errors='replace')

def get_now():
    with urllib.request.urlopen(f'{MIHOMO}/proxies/GLOBAL', timeout=5) as r:
        return json.load(r)['now']

def test_latency_via(name):
    """Temporarily switch GLOBAL to `name`, test latency, switch back."""
    original = get_now()
    try:
        switch_global(name)
        time.sleep(0.5)  # let mihomo apply
        t0 = time.time()
        try:
            proxy_h = urllib.request.ProxyHandler({'http': PROXY, 'https': PROXY})
            opener = urllib.request.build_opener(proxy_h)
            with opener.open(TEST_URL, timeout=TIMEOUT) as r:
                code = r.status
            elapsed = time.time() - t0
            return elapsed, code
        except Exception as e:
            return None, str(e)[:80]
    finally:
        try:
            switch_global(original)
        except Exception:
            pass


def main():
    print(f'reading proxies... (timeout={TIMEOUT}s max_candidates={MAX_CANDIDATES} budget={TIME_BUDGET}s)')
    # candidates: all under GLOBAL selector (not GLOBAL itself)
    with urllib.request.urlopen(f'{MIHOMO}/proxies/GLOBAL', timeout=5) as r:
        global_data = json.load(r)
    candidates = global_data.get('all', [])
    # filter out non-proxy entries (DIRECT, REJECT, etc.)
    skip = {'DIRECT', 'REJECT', 'REJECT-DROP', 'PASS', 'GLOBAL', 'COMPATIBLE'}
    candidates = [c for c in candidates if c not in skip]
    # v17: cap candidate count to avoid 7+ min hangs on slow networks
    candidates = candidates[:MAX_CANDIDATES]
    print(f'  testing {len(candidates)} candidates')

    started = time.time()
    results = []
    for c in candidates:
        # v17: time budget — if we've used too much time, stop early
        elapsed_so_far = time.time() - started
        if elapsed_so_far > TIME_BUDGET:
            print(f'  budget exceeded ({elapsed_so_far:.0f}s > {TIME_BUDGET}s), stopping early')
            break
        latency, code = test_latency_via(c)
        if latency is not None and code in (200, 204):
            results.append((c, latency))
            print(f'  {c}: {latency*1000:.0f}ms HTTP {code} OK')
        else:
            print(f'  {c}: FAIL ({code})')
    if not results:
        print('all failed, keeping current')
        return
    results.sort(key=lambda x: x[1])
    best, best_latency = results[0]
    print(f'\nbest: {best} ({best_latency*1000:.0f}ms)')
    print(f'switching GLOBAL to {best}...')
    switch_global(best)
    time.sleep(1)
    print(f'now: {get_now()}')
    print(f'(total elapsed: {time.time()-started:.1f}s)')


if __name__ == '__main__':
    main()