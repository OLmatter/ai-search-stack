#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""知乎 cookie 引导器 —— 无头 camoufox 通过 zse-ck VMP 挑战，领访客 cookie。

背景（2026-09-09 实测，证据存 .scratch/r4/）：
    知乎官方 API 需要 d_c0 + __zse_ck 两个访客 cookie，其中 __zse_ck 由
    VMP 混淆 JS 在浏览器里现算，纯 HTTP 拿不到（这就是 zhihu_engine 走
    SearXNG 曲线的原因）。本脚本用 camoufox（定制 Firefox，反检测）无头
    开一个知乎内容页，让页面 JS 自己过挑战，把 cookie 存成文件供
    zhihu_content.py 使用。

    实测：headless=True 一次通过；**引导页必须用内容页（问题页）**——
    首页对无登录访客会 302 到 /signin，领不到。

用法:
    python zhihu_bootstrap.py                    # 默认问题页，存默认位置
    python zhihu_bootstrap.py --url https://www.zhihu.com/question/19550227
    python zhihu_bootstrap.py --out state/zhihu_cookies.json

依赖（可选安装，不影响工具箱其他功能）:
    pip install "camoufox[geoip]" && python -m camoufox fetch

产出文件结构:
    {"fetched_at": "...", "user_agent": "...", "cookies": {"d_c0": "...", ...}}
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

_TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_COOKIE_PATH = os.path.join(_TOOL_DIR, "state", "zhihu_cookies.json")
DEFAULT_BOOTSTRAP_URL = "https://www.zhihu.com/question/19550227"
TARGET_KEYS = ("d_c0", "__zse_ck")
WAIT_FIRST_MS = 8000
WAIT_RETRY_MS = 4000
MAX_ROUNDS = 4           # fetch 兜底 + reload 的总轮数上限
TIMEOUT_MS = 60000


def _page_still_on_zhihu(page) -> bool:
    return "zhihu.com" in (page.url or "")


def _cookies(ctx) -> dict:
    return {c["name"]: c["value"] for c in ctx.cookies("https://www.zhihu.com")}


def _have_targets(ctx) -> bool:
    names = _cookies(ctx)
    return all(k in names and names[k] for k in TARGET_KEYS)


def bootstrap(url: str = DEFAULT_BOOTSTRAP_URL,
              out_path: str = DEFAULT_COOKIE_PATH,
              headless: bool = True) -> dict:
    """跑一遍引导流程，返回落盘的 payload（含 cookies dict）。

    Raises:
        RuntimeError: camoufox 未安装 / 轮数用尽仍未领齐目标 cookie。
    """
    try:
        from camoufox.sync_api import Camoufox
    except ImportError as e:
        raise RuntimeError(
            "camoufox 未安装。安装：pip install \"camoufox[geoip]\" "
            "&& python -m camoufox fetch（约百余 MB，一次性）") from e

    with Camoufox(headless=headless, geoip=True) as browser:
        ctx = browser.new_context(locale="zh-CN", timezone_id="Asia/Shanghai")
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
        page.wait_for_timeout(WAIT_FIRST_MS)

        # 内容页 JS 会自行调 API；无签名 API 的 401/10003 响应通常会下发
        # __zse_ck —— 主动 fetch 一次作为兜底触发器
        for round_no in range(MAX_ROUNDS):
            if _have_targets(ctx):
                break
            try:
                page.evaluate(
                    """async () => {
                        const r = await fetch(location.pathname,
                            {credentials: 'include',
                             headers: {'x-requested-with': 'fetch'}});
                        return r.status;
                    }""")
            except Exception:
                pass
            page.wait_for_timeout(WAIT_RETRY_MS)
            if _have_targets(ctx):
                break
            if _page_still_on_zhihu(page):
                page.reload(wait_until="domcontentloaded")
                page.wait_for_timeout(WAIT_RETRY_MS)
        if not _have_targets(ctx):
            raise RuntimeError(
                f"{MAX_ROUNDS} 轮内未领齐 {TARGET_KEYS}（final url={page.url!r}）。"
                "若反复失败，试 headed 模式：--no-headless")

        cookies = _cookies(ctx)
        payload = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "user_agent": page.evaluate("navigator.userAgent"),
            "bootstrap_url": url,
            "headless": headless,
            "cookies": cookies,
        }
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"[zhihu_bootstrap] PASS: d_c0({'Y' if cookies.get('d_c0') else 'N'}) "
              f"__zse_ck(len={len(cookies.get('__zse_ck', ''))}) -> {out_path}",
              flush=True)
        return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="无头 camoufox 过知乎 VMP 挑战，领访客 cookie 存文件")
    parser.add_argument("--url", default=DEFAULT_BOOTSTRAP_URL,
                        help="引导页（必须是知乎内容页，首页会 302 到登录）")
    parser.add_argument("--out", default=DEFAULT_COOKIE_PATH,
                        help="cookie 输出路径（zhihu_content.py 默认读同一位置）")
    parser.add_argument("--no-headless", action="store_true",
                        help="有头模式兜底（无头反复失败时用）")
    args = parser.parse_args()
    try:
        bootstrap(args.url, args.out, headless=not args.no_headless)
        return 0
    except Exception as e:
        print(f"[zhihu_bootstrap] FAIL: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
