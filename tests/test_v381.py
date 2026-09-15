"""v3.8.1 回归：HTTP 服务 Host 白名单（安全审计残留低危项）。

背景：两个本地 HTTP 服务（chat-scraper server.py :8765、google-bridge
search_helper.py :18799）无鉴权且只绑回环。恶意网页可借 DNS rebinding
（攻击者域名解析到 127.0.0.1）跨源 CSRF 式驱动百度/Google 查询。v3.8.1
给两者加 Host 白名单：仅 127.0.0.1/localhost + 实际监听端口，其余 403，
Host 缺失 fail closed。

全部离线零外部网络：集成测试只起回环随机端口 + 打 /health（无外部依赖）。
"""
import email.message
import pathlib
import sys
import threading
import unittest
from http.server import HTTPServer

import requests

REPO = pathlib.Path(__file__).resolve().parent.parent
for d in ("chat-scraper", "google-bridge"):
    sys.path.insert(0, str(REPO / "tools" / d))

import server as chat_server  # noqa: E402  (chat-scraper/server.py)
import search_helper  # noqa: E402  (google-bridge/search_helper.py)


class TestHostAllowedUnit(unittest.TestCase):
    """chat-scraper server._host_allowed 纯函数。"""

    def test_loopback_with_matching_port_allowed(self):
        self.assertTrue(chat_server._host_allowed("127.0.0.1:8765", 8765))
        self.assertTrue(chat_server._host_allowed("localhost:8765", 8765))
        self.assertTrue(chat_server._host_allowed("LOCALHOST:8765", 8765))

    def test_forged_host_rejected(self):
        # DNS rebinding：攻击者域名指向 127.0.0.1，Host 仍是 evil.com
        self.assertFalse(chat_server._host_allowed("evil.com:8765", 8765))
        # 前缀伪装不认
        self.assertFalse(
            chat_server._host_allowed("127.0.0.1.evil.com:8765", 8765))
        self.assertFalse(chat_server._host_allowed("localhost.evil.com:8765",
                                                   8765))

    def test_port_mismatch_and_missing_rejected(self):
        # 端口不匹配（同机其他服务）不认
        self.assertFalse(chat_server._host_allowed("127.0.0.1:9999", 8765))
        # Host 缺失（HTTP/1.0 裸请求）fail closed
        self.assertFalse(chat_server._host_allowed(None, 8765))
        self.assertFalse(chat_server._host_allowed("", 8765))
        # 无端口 / 裸 IPv6 不认
        self.assertFalse(chat_server._host_allowed("127.0.0.1", 8765))
        self.assertFalse(chat_server._host_allowed("[::1]:8765", 8765))


class _Srv:
    """起一个真实 HTTP 服务在 127.0.0.1 随机端口，测完即关。"""

    def __init__(self, handler):
        self.httpd = HTTPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class TestChatScraperServerHostIntegration(unittest.TestCase):
    """chat-scraper server.py 集成：真实 TCP 请求打 /health。"""

    def setUp(self):
        self.srv = _Srv(chat_server._Handler)
        self.base = f"http://127.0.0.1:{self.srv.port}/health"

    def tearDown(self):
        self.srv.close()

    def test_default_host_passes(self):
        # requests 默认 Host: 127.0.0.1:<port> → 200（正常路径不破坏）
        r = requests.get(self.base, timeout=10)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_forged_host_403(self):
        r = requests.get(self.base, headers={"Host": "evil.com:8765"},
                         timeout=10)
        self.assertEqual(r.status_code, 403)
        self.assertIn("Forbidden", r.json()["error"])

    def test_wrong_port_host_403(self):
        r = requests.get(
            self.base,
            headers={"Host": f"127.0.0.1:{self.srv.port + 1}"}, timeout=10)
        self.assertEqual(r.status_code, 403)


class TestSearchHelperHostIntegration(unittest.TestCase):
    """search_helper.py 集成：_host_ok 单元 + 真实 TCP 请求打 /health。"""

    def _make_handler(self, host_value):
        # 不走 socket，直接实例化 handler 骨架测 _host_ok
        sh = search_helper.SearchHandler.__new__(search_helper.SearchHandler)
        msg = email.message.Message()
        if host_value is not None:
            msg["Host"] = host_value
        sh.headers = msg
        sh.server = type("S", (), {"server_address": ("127.0.0.1", 18799)})()
        return sh

    def test_host_ok_unit(self):
        self.assertTrue(self._make_handler("127.0.0.1:18799")._host_ok())
        self.assertTrue(self._make_handler("localhost:18799")._host_ok())
        self.assertFalse(self._make_handler("evil.com:18799")._host_ok())
        self.assertFalse(self._make_handler("127.0.0.1:8080")._host_ok())
        self.assertFalse(self._make_handler(None)._host_ok())

    def test_default_host_health_200_and_forged_403(self):
        srv = _Srv(search_helper.SearchHandler)
        try:
            base = f"http://127.0.0.1:{srv.port}/health"
            r = requests.get(base, timeout=10)  # 默认 Host → 200
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.json()["ok"])
            r = requests.get(base, headers={"Host": "evil.com:18799"},
                             timeout=10)
            self.assertEqual(r.status_code, 403)
        finally:
            srv.close()


if __name__ == "__main__":
    unittest.main()
