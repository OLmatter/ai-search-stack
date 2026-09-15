#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""chat-scraper 极简 HTTP 服务（stdlib http.server，无额外依赖）

端点:
    GET /health  -> {"status": "ok", "tool": "chat-scraper", "version": "3.0.0",
                     "platforms": {...}}
    GET /search?q=...&platforms=zhihu,bilibili&num=10&since=&vendor=&role=
                 -> JSON 数组（平台级错误按统一错误协议内嵌在数组里）

platforms 省略 / general -> 百度无 site: 通用搜索。
服务端始终用 on_error="report"：单平台故障不会把整个请求打成 500。

启动:
    python server.py [--port 8765]        # 端口也可用环境变量 CHAT_SCRAPER_PORT
    curl -G "http://127.0.0.1:8765/search" --data-urlencode "q=python 教程" \
         --data-urlencode "platforms=bilibili" --data-urlencode "num=5"
"""
import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

try:
    from . import search as _facade
    from . import __version__
except ImportError:  # 直接把本目录加进 sys.path 的扁平导入
    import re
    import search as _facade  # type: ignore
    # 不能在这里 import __init__（其中的相对导入在扁平模式下会炸），
    # 用正则读版本号保持 __init__.py 单一来源
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "__init__.py"), encoding="utf-8") as f:
        _m = re.search(r'__version__\s*=\s*"([^"]+)"', f.read())
    __version__ = _m.group(1) if _m else "unknown"

DEFAULT_PORT = 8765
ENV_PORT = "CHAT_SCRAPER_PORT"
_BIND = "127.0.0.1"  # 只监听回环：本工具无鉴权，不应对外网暴露

# v3.8.1: Host 白名单——恶意网页可借 DNS rebinding（把攻击者域名解析到
# 127.0.0.1）跨源驱动本服务的百度查询；校验 Host 头只认回环名+本端口，
# 其余一律 403。Host 缺失（HTTP/1.0 裸请求）按拒绝处理（fail closed）。
_ALLOWED_HOST_NAMES = ("127.0.0.1", "localhost")


def _host_allowed(host_header: Optional[str], port: int) -> bool:
    """Host 头必须为 127.0.0.1/localhost 且端口等于本服务实际端口。"""
    if not host_header:
        return False
    host = host_header.strip().lower()
    name, sep, port_part = host.rpartition(":")
    if not sep:
        return False  # 无端口或裸 IPv6 一律不认（本服务端口非 80，Host 必带）
    return name in _ALLOWED_HOST_NAMES and port_part == str(port)


class _Handler(BaseHTTPRequestHandler):

    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (http.server 命名约定)
        if not _host_allowed(self.headers.get("Host"),
                             self.server.server_address[1]):
            self._send_json(
                {"error": "Forbidden: Host header not in loopback whitelist",
                 "tool": "chat-scraper"}, status=403)
            return
        url = urlparse(self.path)
        if url.path == "/health":
            self._send_json({
                "status": "ok",
                "tool": "chat-scraper",
                "version": __version__,
                "platforms": _facade.list_platforms(),
            })
            return
        if url.path == "/search":
            self._handle_search(parse_qs(url.query))
            return
        self._send_json({"error": "NotFound: use /search or /health",
                         "tool": "chat-scraper"}, status=404)

    def _handle_search(self, qs: dict) -> None:
        q = (qs.get("q") or [""])[0].strip()
        if not q:
            self._send_json({"error": "ValueError: missing required param 'q'",
                             "tool": "chat-scraper"}, status=400)
            return
        raw_platforms = (qs.get("platforms") or [""])[0]
        platforms: Optional[List[str]] = (
            [p for p in raw_platforms.split(",") if p.strip()] or None)
        try:
            num = int((qs.get("num") or ["10"])[0])
        except ValueError:
            self._send_json({"error": "ValueError: 'num' must be an integer",
                             "tool": "chat-scraper"}, status=400)
            return
        since = (qs.get("since") or [""])[0].strip() or None
        vendor = (qs.get("vendor") or ["?"])[0]
        role = (qs.get("role") or ["primary"])[0]
        results = _facade.search(q, platforms=platforms, num=num, since=since,
                                 vendor=vendor, role=role, on_error="report")
        self._send_json(results)

    def log_message(self, fmt: str, *args) -> None:  # 收敛默认的逐请求 stderr 噪音
        print(f"[chat-scraper-server] {self.address_string()} {fmt % args}",
              file=sys.stderr)


def _port() -> int:
    raw = os.environ.get(ENV_PORT, "")
    try:
        return int(raw) if raw else DEFAULT_PORT
    except ValueError:
        return DEFAULT_PORT


def _main() -> int:
    parser = argparse.ArgumentParser(description="chat-scraper HTTP 服务")
    parser.add_argument("--port", type=int, default=None,
                        help=f"默认取环境变量 {ENV_PORT}，再退 {DEFAULT_PORT}")
    args = parser.parse_args()
    port = args.port if args.port is not None else _port()
    server = ThreadingHTTPServer((_BIND, port), _Handler)
    print(f"[chat-scraper-server] listening on http://{_BIND}:{port} "
          f"(v{__version__}); Ctrl+C to stop", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
