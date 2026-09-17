"""v3.44.0 回归：正主客户端行为钉批（v3.43 覆盖缺口线的正主遗漏项收尾）。

背景（v3.44 评估取证：coverage 7.16.1 `--source=tools` 在 839 全绿基线上
全量跑，`coverage report --sort=cover` 读数）：
1. tools/github/github_client.py 22%（87 stmts 68 miss，全仓最低——仅高于
   3 行的包 __init__）。v3.43 的覆盖缺口补钉落在 client.py 兼容 shim
   （警告+转发等价子进程钉）与 auto_select_node 六关键路径上；正主模块
   三个主函数（get_releases / get_advisories / search_repos）的解析、
   repo URL path 转义（防注入语义）、错误协议接线、GITHUB_TOKEN 请求头、
   CLI exit 1 全部零行为钉——test_offline 仅直调 _handle_error 本体三态
   （不经过任何主函数的 try/except 接线），test_v3180 的 token 钉在
   doctor.check_github 侧（Bearer 格式），client 自己的 `token <tok>`
   格式无人钉。
2. tools/hackernews/hackernews_client.py 57%（49 stmts 21 miss）：
   search() 的错误协议接线（report 行结构 / raise 重抛 / empty 返回）
   与 CLI（argparse→search 映射 + exit 1）零钉——test_offline 的 e2e
   只走成功路径。

评估不立项（裁决留痕，详见 CHANGELOG v3.44.0「不做的」段）：
wenxin_engine 304-398（camoufox 浏览器层+配额纪律相邻，mock 测试=测
mock）/ zhihu_engine 搜狗/百度 fallback 取数体（v3.10 钉群已在）/
auto_select_node 25-60（网络测速核，v3.43 已钉六关键路径）/ 凭据线与
google-bridge 敏感件与 wenxin 配额纪律（主人边界，零触碰）。

全部离线，两套手法：
- mock urllib.request.urlopen（进程内，捕获 Request 断言 URL 与头）；
- 死代理子进程（https_proxy/HTTPS_PROXY 指向 127.0.0.1:9 必关闭端口，
  urlopen 秒拒=确定性 URLError，零真实网络零外联）。
"""
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import unittest
import urllib.error
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tools" / "github"))
sys.path.insert(0, str(REPO / "tools" / "hackernews"))

import github_client as gh          # noqa: E402
import hackernews_client as hn      # noqa: E402


def _fake_resp(payload: bytes):
    """urlopen 返回值的 context-manager 形态（with urlopen() as r: 语法）。"""
    fake = io.BytesIO(payload)
    fake.__enter__ = lambda s: s
    fake.__exit__ = lambda s, *a: False
    return fake


def _capture_urlopen(captured: list, payload: bytes):
    """side_effect 工厂：记录 Request（URL+headers）并返回假响应。"""
    def _side(req, *a, **kw):
        captured.append(req)
        return _fake_resp(payload)
    return _side


class TestGithubClientBehavior(unittest.TestCase):
    """正主 github_client 三主函数行为钉（v3.43 只钉了 shim 转发等价）。"""

    RELEASES = json.dumps([
        {"name": None, "tag_name": "v1.2.3", "html_url": "https://x/r1",
         "body": "b" * 600, "published_at": "2026-09-17T00:00:00Z",
         "prerelease": True},
        {"name": "named release", "tag_name": "v1.2.2",
         "html_url": "https://x/r2", "body": "short", "prerelease": False},
        {"name": "capped-out", "tag_name": "v1.2.1", "html_url": "https://x"},
    ]).encode()

    def test_get_releases_parses_fallback_truncation_cap(self):
        # name 缺失回退 tag_name / body 截 500 / prerelease 透传 / num 截断
        with mock.patch("urllib.request.urlopen",
                        return_value=_fake_resp(self.RELEASES)):
            rows = gh.get_releases("o/r", num=2, vendor="v", role="primary")
        self.assertEqual(len(rows), 2)                      # num 截断（3 进 2）
        self.assertEqual(rows[0]["tag"], "v1.2.3")
        self.assertEqual(rows[0]["title"], "v1.2.3")        # name=None → tag_name
        self.assertEqual(len(rows[0]["content"]), 500)      # body 截 500
        self.assertTrue(rows[0]["prerelease"])
        self.assertEqual(rows[1]["title"], "named release")  # name 在先
        self.assertFalse(rows[1]["prerelease"])
        self.assertEqual((rows[0]["vendor"], rows[0]["role"],
                          rows[0]["since"]), ("v", "primary", "all"))

    def test_get_releases_escapes_repo_path_and_sends_per_page(self):
        # repo 直接拼 URL path：空格/?# 必须转义（safe="/"，防注入语义）；
        # per_page=num 必须在 query 上。此语义 v3.44 前零钉。
        captured = []
        with mock.patch("urllib.request.urlopen",
                        side_effect=_capture_urlopen(captured, b"[]")):
            gh.get_releases("own er/in ject?x=1#frag", num=7)
        url = captured[0].full_url
        path = url.split("?")[0]
        for bad in (" ", "?", "#", "ject?"):
            self.assertNotIn(bad, path)
        self.assertIn("own%20er/in", path)                  # quote safe="/"
        self.assertIn("per_page=7", url)

    def test_get_advisories_parses_and_urlencodes_ecosystem(self):
        payload = json.dumps([{
            "summary": "s", "html_url": "https://x/a",
            "description": "d" * 600, "cve_id": "CVE-2026-0001",
            "severity": "high", "published_at": "2026-09-17T00:00:00Z",
        }]).encode()
        captured = []
        with mock.patch("urllib.request.urlopen",
                        side_effect=_capture_urlopen(captured, payload)):
            rows = gh.get_advisories(ecosystem="npm", num=5)
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["title"], rows[0]["cve"],
                          rows[0]["severity"]), ("s", "CVE-2026-0001", "high"))
        self.assertEqual(len(rows[0]["content"]), 500)      # description 截 500
        self.assertIn("ecosystem=npm", captured[0].full_url)
        self.assertIn("per_page=5", captured[0].full_url)

    def test_search_repos_parses_and_missing_items_key_is_empty(self):
        payload = json.dumps({"items": [{
            "full_name": "o/r", "html_url": "https://x", "description": "d",
            "stargazers_count": 42, "language": "Py", "updated_at": "t",
        }]}).encode()
        with mock.patch("urllib.request.urlopen",
                        return_value=_fake_resp(payload)):
            rows = gh.search_repos("q", num=3)
        self.assertEqual(rows[0]["title"], "o/r")
        self.assertEqual(rows[0]["stars"], 42)
        self.assertEqual(rows[0]["language"], "Py")
        # 响应无 items 键：真空（0 结果）不是故障，返回 [] 不炸
        with mock.patch("urllib.request.urlopen",
                        return_value=_fake_resp(b"{}")):
            self.assertEqual(gh.search_repos("q"), [])

    def test_error_wiring_report_default_on_http_403(self):
        # 主函数 try/except 接线端到端：HTTPError 403 → report 默认行
        # 含 tool=github / action=releases / query=repo 三要素（值班
        # 2026-09-16 两班 403 的现实病形状）
        err = urllib.error.HTTPError(
            "https://api.github.com/repos/o/r/releases", 403,
            "rate limit exceeded", None, None)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            rows = gh.get_releases("o/r")                   # 默认 report
        self.assertEqual(len(rows), 1)
        self.assertIn("HTTPError", rows[0]["error"])
        self.assertIn("403", rows[0]["error"])
        self.assertEqual((rows[0]["tool"], rows[0]["action"],
                          rows[0]["query"]), ("github", "releases", "o/r"))

    def test_error_wiring_raise_and_empty_modes(self):
        err = urllib.error.HTTPError("https://x", 500, "boom", None, None)
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(urllib.error.HTTPError):
                gh.get_releases("o/r", on_error="raise")
            self.assertEqual(gh.get_releases("o/r", on_error="empty"), [])
            # advisory/search 两条接线也走同一协议（action/query 各自正确）
            rows = gh.get_advisories(on_error="report")
            self.assertEqual(rows[0]["action"], "advisories")
            rows = gh.search_repos("q", on_error="report")
            self.assertEqual((rows[0]["action"], rows[0]["query"]),
                             ("search", "q"))

    def test_token_header_token_format_and_anonymous(self):
        # client 的格式是 `token <tok>`（RFC 老式）——doctor 是
        # `Bearer <tok>`，两套并存各自钉死，防互相"纠正"成对方
        captured = []
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_TOKEN"}
        with mock.patch.dict(os.environ, {**env, "GITHUB_TOKEN": "ghp_x"},
                             clear=True):
            with mock.patch("urllib.request.urlopen",
                            side_effect=_capture_urlopen(captured, b"[]")):
                gh.get_releases("o/r")
        headers = {k.lower(): v for k, v in captured[0].headers.items()}
        self.assertEqual(headers["authorization"], "token ghp_x")
        self.assertIn("ai-search-stack", headers["user-agent"])
        self.assertIn("application/vnd.github+json", headers["accept"])
        captured.clear()                                    # 匿名：无 Authorization
        with mock.patch.dict(os.environ,
                             {k: v for k, v in os.environ.items()
                              if k != "GITHUB_TOKEN"}, clear=True):
            with mock.patch("urllib.request.urlopen",
                            side_effect=_capture_urlopen(captured, b"[]")):
                gh.get_releases("o/r")
        headers = {k.lower(): v for k, v in captured[0].headers.items()}
        self.assertNotIn("authorization", headers)
        self.assertIn("ai-search-stack", headers["user-agent"])

    def test_cli_dead_proxy_exit1_with_stderr_prefix(self):
        # 死代理（127.0.0.1:9 必拒绝）→ urlopen 秒拒 → CLI 打
        # [github/releases] error: 并 exit 1（子进程纪律+确定性离线）
        env = {k: v for k, v in os.environ.items()
               if k.lower() not in ("http_proxy", "https_proxy", "no_proxy")}
        env["https_proxy"] = env["HTTPS_PROXY"] = "http://127.0.0.1:9"
        r = subprocess.run(
            [sys.executable, str(REPO / "tools" / "github"
                                 / "github_client.py"),
             "releases", "o/r", "--num", "1"],
            capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("[github/releases] error:", r.stderr)


class TestHackernewsErrorWiring(unittest.TestCase):
    """search() 错误接线 + CLI exit 1（成功路径已有 test_offline e2e）。"""

    def test_search_report_protocol_on_urlerror(self):
        err = urllib.error.URLError("conn refused")
        with mock.patch("urllib.request.urlopen", side_effect=err):
            rows = hn.search("q")                           # 默认 report
        self.assertEqual(len(rows), 1)
        self.assertIn("URLError", rows[0]["error"])
        self.assertEqual((rows[0]["tool"], rows[0]["query"]),
                         ("hackernews", "q"))

    def test_search_raise_and_empty_modes(self):
        err = urllib.error.URLError("conn refused")
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(urllib.error.URLError):
                hn.search("q", on_error="raise")
            self.assertEqual(hn.search("q", on_error="empty"), [])

    def test_cli_dead_proxy_exit1_with_stderr_prefix(self):
        env = {k: v for k, v in os.environ.items()
               if k.lower() not in ("http_proxy", "https_proxy", "no_proxy")}
        env["https_proxy"] = env["HTTPS_PROXY"] = "http://127.0.0.1:9"
        r = subprocess.run(
            [sys.executable, str(REPO / "tools" / "hackernews"
                                 / "hackernews_client.py"), "q", "--num", "1"],
            capture_output=True, text=True, timeout=60, env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("[hackernews] error:", r.stderr)


class TestVersionLock3440(unittest.TestCase):
    """精确锁（自 test_v3430 接管，v3.27→…→v3.40→v3.42→v3.43 交接链延续）：
    三版本载体（mcp_server / chat-scraper __init__ / digest）+ docstring
    首行 + CHANGELOG/README 徽章与标题行。下一批发布时本类降常青交接。"""

    def test_mcp_server_version(self):
        import mcp_server
        self.assertEqual(mcp_server.__version__, "3.44.0")

    def test_chat_scraper_package_version(self):
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        self.assertIn('__version__ = "3.44.0"', init_src)
        self.assertIn("chat-scraper v3.44.0", init_src)   # docstring 首行同步

    def test_digest_version(self):
        digest_src = (REPO / "tools" / "digest.py").read_text(
            encoding="utf-8")
        self.assertIn('__version__ = "3.44.0"', digest_src)

    def test_readme_headline_mentions_3440(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("release-v3.44.0", readme)
        self.assertIn("v3.44.0（2026-09-17）", readme)

    def test_changelog_has_3440_entry(self):
        cl = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.44.0] - ", cl)

    def test_readme_badge_count(self):
        # 徽章数 = 全仓真实测试数：正则 `^    def (test_\w+)\(` 数遍
        # tests/test_*.py（v3.44 起公式升级——旧公式「基线+本批钉数」
        # 在同批含降常青坍缩时会虚报[839+17 vs 实际 851 的 5 钉差]，
        # 全仓计数与 pytest 收集数已对账一致 851==851）；本函数注释与
        # 正则字面量不得写成可命中形态（自引用虚增——v3.33 先例）
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        m = re.search(r"tests-(\d+)%20passing", readme)
        self.assertIsNotNone(m)
        real = 0
        for f in (REPO / "tests").glob("test_*.py"):
            real += len(re.findall(r"^    def (test_\w+)\(",
                                   f.read_text(encoding="utf-8"), re.M))
        self.assertGreater(real, 800)
        self.assertEqual(int(m.group(1)), real)


if __name__ == "__main__":
    unittest.main()
