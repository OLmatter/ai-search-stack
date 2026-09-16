"""MCP server（tools/mcp_server.py）离线单测：零真实网络、零浏览器。

覆盖：
1. 工具注册表完整性（14 个工具、名称/描述/schema 合法）
2. 参数透传到模块函数（mock 捕获，含固定 on_error="report"）
3. 错误报告形态（异常兜底成统一错误协议 JSON，server 不炸）
4. stdout 卫兵（库代码往 stdout 打印被重定向 stderr——MCP stdio 协议保命）
5. googlebridge 服务未启动的可读错误（连 127.0.0.1 死端口，回环不出网）

协议级自测（真 stdio spawn + 真网络）在仓库外 .scratch/mcp/test_mcp_stdio.py，
不入库（临时产物）。本文件只做可离线复现的部分，与 test_offline.py 同套
discover 运行；mcp SDK 未安装的环境（如部分 CI）整类跳过。

运行：python -m unittest discover -s tests -p "test_*.py" -v
"""
import asyncio
import contextlib
import io
import json
import os
import pathlib
import sys
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

try:
    import mcp_server  # noqa: E402
except ImportError:  # mcp SDK 未安装（离线 CI 等）——本文件全部跳过
    mcp_server = None

EXPECTED_TOOLS = {
    "china_search", "read_page", "zhihu_question", "zhihu_answers",
    "zhihu_article", "zhihu_comments", "bilibili_video",
    "bilibili_subtitles", "hn_search", "github_releases",
    "github_advisories", "searxng_search", "googlebridge_search", "doctor",
}


def _schema(tool):
    """mcp 1.x/2.x 字段名兼容（inputSchema vs input_schema）。"""
    return getattr(tool, "input_schema", None) or getattr(tool, "inputSchema")


@unittest.skipUnless(mcp_server, "mcp SDK 未安装，跳过 MCP server 离线测试")
class TestRegistry(unittest.TestCase):
    """工具注册表完整性：MCP 客户端 tools/list 能看到的全集。"""

    def test_all_tools_registered_with_valid_schema(self):
        tools = asyncio.run(mcp_server.mcp.list_tools())
        names = {t.name for t in tools}
        self.assertEqual(names, EXPECTED_TOOLS,
                         "注册表与预期工具集不一致（多/少都要查）")
        for t in tools:
            self.assertTrue(t.description and len(t.description) > 50,
                            f"{t.name}: 描述缺失或过短——MCP 的工具描述就是"
                            f"给模型的路由提示，不允许空")
            schema = _schema(t)
            self.assertIn("type", schema, f"{t.name}: schema 缺 type")
            self.assertIn("properties", schema, f"{t.name}: schema 缺 properties")
        # 必填参数抽查：search 门面的 q 必填
        by_name = {t.name: t for t in tools}
        self.assertIn("q", _schema(by_name["china_search"]).get("required", []))
        self.assertIn("url", _schema(by_name["read_page"]).get("required", []))
        # doctor 唯一可选参数 mode（v3.15：full|cookie|sogou，默认 full）
        doctor_props = _schema(by_name["doctor"]).get("properties") or {}
        self.assertEqual(set(doctor_props), {"mode"})
        self.assertNotIn("mode", _schema(by_name["doctor"]).get("required", []))


@unittest.skipUnless(mcp_server, "mcp SDK 未安装，跳过 MCP server 离线测试")
class TestPassthrough(unittest.TestCase):
    """设计约束「不做内部 API 统一」：参数原样透传到模块函数。"""

    def test_hn_search_passthrough_and_json_roundtrip(self):
        calls = {}

        def fake_search(q, **kw):
            calls.update(q=q, **kw)
            return [{"title": "t1", "url": "u1", "query": q}]

        with mock.patch.object(mcp_server._hn, "search", fake_search):
            out = mcp_server.hn_search(q="rust", num=3, since="24h",
                                       tags="comment", vendor="test",
                                       role="verify")
        # 透传保真：位置参数 q + 全部 kwargs 原样，on_error 固定 report
        self.assertEqual(calls, {"q": "rust", "num": 3, "since": "24h",
                                 "tags": "comment", "vendor": "test",
                                 "role": "verify", "on_error": "report"})
        # 返回是合法 JSON 文本，内容与模块返回一致
        parsed = json.loads(out)
        self.assertEqual(parsed, [{"title": "t1", "url": "u1", "query": "rust"}])

    def test_china_search_platforms_list_passthrough(self):
        calls = {}

        def fake_search(q, **kw):
            calls.update(q=q, **kw)
            return []

        with mock.patch.object(mcp_server._chat, "search", fake_search):
            mcp_server.china_search(q="测试", platforms=["zhihu", "bilibili"],
                                    num=5, since="7d", vendor="v", role="r")
        self.assertEqual(calls["platforms"], ["zhihu", "bilibili"])
        self.assertEqual(calls["num"], 5)
        self.assertEqual(calls["on_error"], "report")

    def test_zhihu_comments_passthrough(self):
        calls = {}

        def fake_fetch_comments(target, **kw):
            calls.update(target=target, **kw)
            return [{"id": "c1", "author": "甲", "content": "hi"}]

        with mock.patch.object(mcp_server._zhihu, "fetch_comments",
                               fake_fetch_comments):
            out = mcp_server.zhihu_comments(target="12202014", num=5,
                                            order_by="ts")
        # 透传保真：target + 默认参数原样，on_error 固定 report
        self.assertEqual(calls, {"target": "12202014", "num": 5,
                                 "order_by": "ts", "kind": "answer",
                                 "expand_children": True,
                                 "on_error": "report"})
        self.assertEqual(json.loads(out)[0]["id"], "c1")


@unittest.skipUnless(mcp_server, "mcp SDK 未安装，跳过 MCP server 离线测试")
class TestErrorProtocol(unittest.TestCase):
    """错误处理：异常兜底成统一错误协议 JSON，server 进程不炸。"""

    def test_exception_becomes_error_payload_and_server_survives(self):
        def boom(q, **kw):
            raise RuntimeError("socket exploded")

        with mock.patch.object(mcp_server._hn, "search", boom):
            out = mcp_server.hn_search(q="x")
        parsed = json.loads(out)
        self.assertIsInstance(parsed, list)
        item = parsed[0]
        self.assertIn("RuntimeError: socket exploded", item["error"])
        self.assertEqual(item["tool"], "hackernews")
        self.assertEqual(item["query"], "x")
        # 兜底后 server 仍正常服务下一个请求
        with mock.patch.object(mcp_server._hn, "search",
                               lambda q, **kw: [{"title": "ok"}]):
            out2 = json.loads(mcp_server.hn_search(q="y"))
        self.assertEqual(out2[0]["title"], "ok")

    def test_zhihu_slug_preserved_in_error(self):
        """zhihu_content 的异常带 slug（如 zhihu_auth_expired）——错误串保留它。"""

        class FakeAuthExpired(Exception):
            slug = "zhihu_auth_expired"

        def boom(question_id):
            raise FakeAuthExpired("cookie 过期")

        with mock.patch.object(mcp_server._zhihu, "fetch_question", boom):
            out = json.loads(mcp_server.zhihu_question("123"))
        self.assertIn("zhihu_auth_expired", out[0]["error"])


@unittest.skipUnless(mcp_server, "mcp SDK 未安装，跳过 MCP server 离线测试")
class TestStdoutGuard(unittest.TestCase):
    """stdout 卫兵：MCP stdio 下 stdout 只归协议，库代码的 print 必须让路。"""

    def test_library_stdout_redirects_to_stderr(self):
        def chatty_search(q, **kw):
            print("[fake_engine] progress line to stdout")  # 会毁协议的写法
            return [{"title": "t"}]

        err = io.StringIO()
        with mock.patch.object(mcp_server._hn, "search", chatty_search):
            with contextlib.redirect_stderr(err):
                out = mcp_server.hn_search(q="x")
        self.assertNotIn("[fake_engine]", out, "stdout 内容混进了工具返回")
        self.assertIn("[fake_engine]", err.getvalue(), "stdout 应被重定向到 stderr")
        self.assertEqual(json.loads(out), [{"title": "t"}])


@unittest.skipUnless(mcp_server, "mcp SDK 未安装，跳过 MCP server 离线测试")
class TestGooglebridgeUnreachable(unittest.TestCase):
    """googlebridge 服务未启动：返回可读错误（连死端口，回环不出外网）。"""

    def test_dead_port_gives_readable_error(self):
        with mock.patch.dict(os.environ, {"SEARCH_HELPER_PORT": "1"}):
            out = json.loads(mcp_server.googlebridge_search(q="test"))
        item = out[0]
        self.assertIn("googlebridge_unreachable", item["error"])
        self.assertIn("127.0.0.1:1", item["error"], "错误里应指认实际探测的端口")
        self.assertIn("start_search_helper", item["error"], "应给出启动指引")
        self.assertEqual(item["tool"], "google-bridge")
        self.assertEqual(item["query"], "test")


if __name__ == "__main__":
    unittest.main()
