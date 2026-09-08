"""离线单元测试：不发外部请求，任何机器/CI 都能跑。

覆盖三类回归：
1. v3.0.0 修复过的 bug（时区漂移、null points 崩溃、since 双默认…）
2. v2 空壳事故的防回归（NUL 文件检测）
3. toolbox 组合的前提（同进程多工具 import 不撞名）

运行：python -m unittest discover -s tests -p "test_*.py" -v
"""
import pathlib
import subprocess
import sys
import time
import unittest
from contextlib import redirect_stderr
from io import StringIO

REPO = pathlib.Path(__file__).resolve().parent.parent
for d in ("hackernews", "github", "searxng", "chat-scraper", "google-bridge"):
    sys.path.insert(0, str(REPO / "tools" / d))


class TestNulRegression(unittest.TestCase):
    """v2 的 chat-scraper 曾以"保留大小、内容全 NUL"的空壳入库且 CI 假绿。"""

    def test_no_nul_only_py_files(self):
        bad = []
        for p in sorted((REPO / "tools").rglob("*.py")):
            data = p.read_bytes()
            if data and data.replace(b"\x00", b"") == b"":
                bad.append(str(p))
        self.assertEqual(bad, [], f"NUL 空壳文件（v2 事故防回归）: {bad}")

    def test_no_empty_py_files(self):
        empty = [str(p) for p in sorted((REPO / "tools").rglob("*.py"))
                 if p.read_bytes() == b""]
        self.assertEqual(empty, [])


class TestImportCollisionRegression(unittest.TestCase):
    """v2 三客户端同名 client.py，同进程 import 第二个命中 sys.modules
    缓存被静默劫持（审计实测）。v3 模块名唯一，此测试锁死该前提。"""

    def test_unique_module_names_coexist(self):
        import hackernews_client
        import searxng_client

        self.assertIsNot(hackernews_client.search, searxng_client.search)
        # 本进程从未 import 过任何 client.py shim——模块名唯一化的前提
        self.assertNotIn("client", sys.modules)

    def test_legacy_shim_warns_and_forwards(self):
        """旧用法 from client import search 仍工作，但必须打 DeprecationWarning。"""
        code = (
            "import warnings, sys\n"
            "sys.path.insert(0, r'{dir}')\n"
            "warnings.simplefilter('error', DeprecationWarning)\n"
            "try:\n"
            "    from client import search\n"
            "except DeprecationWarning:\n"
            "    print('WARNED'); sys.exit(0)\n"
            "print('NO_WARN'); sys.exit(1)\n"
        ).format(dir=REPO / "tools" / "hackernews")
        r = subprocess.run([sys.executable, "-c", code],
                           capture_output=True, text=True, timeout=30)
        self.assertIn("WARNED", r.stdout,
                      f"shim 未打 DeprecationWarning: {r.stdout} {r.stderr}")


class TestHackernews(unittest.TestCase):
    def test_since_timestamp_is_utc_now_based(self):
        # v3 修复前：naive utcnow 按本地时区解释，UTC+8 机器漂移 -28800s
        import hackernews_client as hn
        got = hn._since_to_timestamp("7d")
        expect = time.time() - 7 * 86400
        self.assertLess(abs(got - expect), 120,
                        f"7d 截止戳偏差 {got - expect:.0f}s（时区漂移回归？）")

    def test_null_points_coerced_to_int(self):
        # v3 修复前：comment 模式 points 为 JSON null，`hit.get("points", 0)`
        # 拿到 None，调用方 `points >= 50` 直接 TypeError（审计实测）
        import hackernews_client as hn
        row = hn._row_from_hit({"title": None, "points": None,
                                "num_comments": None, "author": None},
                               vendor="t", role="verify", since="7d")
        self.assertEqual(row["points"], 0)
        self.assertIsInstance(row["points"], int)
        self.assertEqual(row["comments"], 0)
        self.assertEqual(row["title"], "")

    def test_search_end_to_end_null_points(self):
        # 端到端锁死：mock 掉 urlopen，返回 points=null 的真实 hit 形状
        import io
        import json
        from unittest import mock
        import urllib.request  # noqa: F401  (hackernews_client 引用其命名空间)
        import hackernews_client as hn
        payload = json.dumps({"hits": [{"objectID": "1", "title": "t",
                                        "points": None, "num_comments": None}]}).encode()
        fake_resp = io.BytesIO(payload)
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = lambda s, *a: False
        with mock.patch("urllib.request.urlopen", return_value=fake_resp):
            results = hn.search("q", on_error="raise")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["points"], 0)


class TestGithub(unittest.TestCase):
    def test_error_protocol_modes(self):
        import github_client as gh
        err = RuntimeError("boom")
        rep = gh._handle_error(err, "report", "releases", "q")
        self.assertIn("error", rep[0])
        self.assertEqual(rep[0]["action"], "releases")
        self.assertEqual(gh._handle_error(err, "empty", "releases", "q"), [])
        with self.assertRaises(RuntimeError):
            gh._handle_error(err, "raise", "releases", "q")


class TestSearxng(unittest.TestCase):
    def test_unknown_since_warns_not_silent(self):
        import searxng_client as sx
        err = StringIO()
        with redirect_stderr(err):
            self.assertEqual(sx._since_to_time_range("3w"), "")
        self.assertIn("warning", err.getvalue().lower())

    def test_known_since_windows(self):
        import searxng_client as sx
        self.assertNotEqual(sx._since_to_time_range("7d"), "")
        self.assertEqual(sx._since_to_time_range(""), "")


class TestChatScraper(unittest.TestCase):
    def test_baidu_placeholder_detection(self):
        import baidu_engine as bd
        self.assertIsNotNone(bd._looks_soft_blocked("<html>timeout hide</html>"))
        self.assertIsNotNone(bd._looks_soft_blocked("xxx wappass yyy"))
        self.assertIsNone(bd._looks_soft_blocked(
            "<html>" + "x" * (bd.PLACEHOLDER_MAX_LEN + 10) + "timeout</html>"))

    def test_baidu_parse_uses_mu_direct_link(self):
        # 百度 mu 属性即真实直链（侦察实证），跳转解析都省了——锁死该解析契约
        import baidu_engine as bd
        html = (
            '<div class="result" mu="https://zhuanlan.zhihu.com/p/1">'
            '<h3><a href="#">标题A</a></h3>'
            '<div class="summary-text_1">摘要A</div></div>'
            '<div class="result-op" mu="https://www.zhihu.com/question/2">'
            '<h3>标题B</h3></div>'
            '<div class="result" mu="https://zhuanlan.zhihu.com/p/1">'
            '<h3>重复mu应去重</h3></div>'
            '<div class="result"><h3>无mu应跳过</h3></div>')
        out = bd._parse_results(html)
        self.assertEqual([r["url"] for r in out],
                         ["https://zhuanlan.zhihu.com/p/1",
                          "https://www.zhihu.com/question/2"])
        self.assertEqual(out[0]["title"], "标题A")
        self.assertEqual(out[0]["snippet"], "摘要A")

    def test_bilibili_clean_title(self):
        import bilibili_engine as bl
        self.assertEqual(bl._clean_title('<em class="keyword">python</em> 教程'),
                         "python 教程")
        self.assertEqual(bl._clean_title("A &amp; B"), "A & B")
        self.assertEqual(bl._clean_title(None), "")

    def test_bilibili_mixin_key_length(self):
        import bilibili_engine as bl
        # 真实输入 img_key+sub_key = 64 hex；测试串取 70 字符覆盖重排表最大索引
        key = bl._mixin_key("0123456789" * 7)
        self.assertEqual(len(key), 32)

    def test_platform_registry(self):
        import search as cs
        plats = cs.list_platforms()
        self.assertIn("zhihu", plats)
        self.assertIn("bilibili", plats)

    def test_unknown_platform_reports_not_crashes(self):
        import search as cs
        out = cs.search("q", platforms=["nonexistent_platform"],
                        on_error="report")
        self.assertEqual(len(out), 1)
        self.assertIn("unknown platform", out[0]["error"])

    def test_error_protocol_modes(self):
        import search as cs
        out = cs.search("q", platforms=["nonexistent_platform"],
                        on_error="empty")
        self.assertEqual(out, [])
        with self.assertRaises(ValueError):
            cs.search("q", platforms=["nonexistent_platform"],
                      on_error="raise")


class TestZhihuEngine(unittest.TestCase):
    """v3.1 知乎专用引擎：降级链 SearXNG→搜狗→百度。"""

    SOGOU_HTML = (
        '<div class="vrwrap"><h3 class="vr-title"><a target="_blank" '
        'href="/link?url=abc123">从零开始学<em><!--red_beg-->Python<!--red_end-->'
        '</em> - 知乎</a></h3><div class="text-layout"><p>入门教程摘要。</p></div></div>'
        '<div class="vrwrap"><h3 class="vr-title"><a href="/link?url=dup">重复</a></h3></div>'
        '<div class="vrwrap"><h3 class="vr-title"><a href="/link?url=dup">重复</a></h3></div>'
        '<div class="rb"><h3><a href="https://zhuanlan.zhihu.com/p/9">直链文章</a></h3>'
        '<div class="space-txt">直链摘要</div></div>')

    def test_sogou_parse(self):
        import zhihu_engine as zg
        rows = zg._sogou_parse(self.SOGOU_HTML)
        self.assertEqual(len(rows), 3)  # 重复 href 去重掉一条
        self.assertEqual(rows[0]["title"], "从零开始学Python - 知乎")
        self.assertTrue(rows[0]["link_href"].startswith("https://www.sogou.com/link"))
        self.assertEqual(rows[0]["snippet"], "入门教程摘要。")
        self.assertTrue(rows[2]["link_href"].startswith("https://zhuanlan."))

    def test_resolve_link_regex(self):
        import zhihu_engine as zg
        page = '<script>window.location.replace("https://zhuanlan.zhihu.com/p/1")</script>'
        self.assertEqual(zg._LOCATION_RE.search(page).group(1),
                         "https://zhuanlan.zhihu.com/p/1")

    def test_searxng_filters_to_zhihu(self):
        # 后端偶尔漏进无关域，引擎层二次过滤锁死
        import zhihu_engine as zg
        import types
        fake_rows = {"results": [
            {"title": "知乎问题", "url": "https://www.zhihu.com/question/1",
             "content": "c1", "engine": "brave"},
            {"title": "CSDN 文章", "url": "https://blog.csdn.net/x", "engine": "brave"},
        ]}
        class FakeResp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return fake_rows
        from unittest import mock
        with mock.patch.object(zg.requests, "get", return_value=FakeResp()):
            with mock.patch.object(zg, "_wait_turn"):
                rows = zg._searxng_search("q", 10, None, "t", "verify")
        self.assertEqual(len(rows), 1)
        self.assertIn("question/1", rows[0]["url"])
        self.assertEqual(rows[0]["engine"], "searxng:brave")

    def test_chain_degrades_on_engine_error(self):
        import zhihu_engine as zg
        from unittest import mock
        good = [{"title": "t", "url": "https://www.zhihu.com/q/1",
                 "snippet": "", "platform": "zhihu", "engine": "sogou",
                 "vendor": "t", "role": "verify", "since": "all"}]
        with mock.patch.object(zg, "_searxng_search",
                               side_effect=zg.SearxngUnavailable("down")), \
             mock.patch.object(zg, "_sogou_search", return_value=good), \
             mock.patch.object(zg, "_baidu_fallback") as baidu:
            rows = zg.search("q", on_error="raise")
        self.assertEqual(rows[0]["engine"], "sogou")
        baidu.assert_not_called()   # 前一环成功就不再降级

    def test_chain_all_fail_reports_with_chain_log(self):
        import zhihu_engine as zg
        from unittest import mock
        with mock.patch.object(zg, "_searxng_search",
                               side_effect=zg.SearxngUnavailable("down")), \
             mock.patch.object(zg, "_sogou_search",
                               side_effect=zg.SogouBlocked("captcha")), \
             mock.patch.object(zg, "_baidu_fallback",
                               side_effect=ConnectionError("RST")):
            rows = zg.search("q", on_error="report")
        self.assertEqual(len(rows), 1)
        self.assertIn("ConnectionError", rows[0]["error"])
        self.assertEqual(rows[0]["chain"], "searxng(失败:SearxngUnavailable)"
                                          "→sogou(失败:SogouBlocked)"
                                          "→baidu(失败:ConnectionError)")
        with mock.patch.object(zg, "_searxng_search",
                               side_effect=zg.SearxngUnavailable("down")), \
             mock.patch.object(zg, "_sogou_search", return_value=[]), \
             mock.patch.object(zg, "_baidu_fallback", return_value=[]):
            # searxng 挂过一环：报错保留链条日志（诊断信息优先），
            # 不允许伪装成真空 []
            rows = zg.search("q", on_error="report")
            self.assertEqual(len(rows), 1)
            self.assertIn("chain", rows[0])
            # 三环全部成功但都 0 结果 —— 这才是真真空
            with mock.patch.object(zg, "_searxng_search", return_value=[]), \
                 mock.patch.object(zg, "_sogou_search", return_value=[]), \
                 mock.patch.object(zg, "_baidu_fallback", return_value=[]):
                self.assertEqual(zg.search("q", on_error="report"), [])
        # raise 路径：chain 挂在异常对象上，门面 _error_record 必须透传
        # （审查发现：chain 曾在标准调用路径丢失）
        with mock.patch.object(zg, "_searxng_search",
                               side_effect=zg.SearxngUnavailable("down")), \
             mock.patch.object(zg, "_sogou_search", return_value=[]), \
             mock.patch.object(zg, "_baidu_fallback", return_value=[]):
            with self.assertRaises(zg.SearxngUnavailable) as cm:
                zg.search("q", on_error="raise")
            self.assertIn("sogou(0条)", cm.exception.chain)
            import search as cs
            rec = cs._error_record(cm.exception, "q", "zhihu")
            self.assertIn("chain", rec)

    def test_site_param_reaches_engines(self):
        # zhuanlan 的 site 限定必须贯穿三环（v3.1.0 曾是死参数，审查修正）
        import zhihu_engine as zg
        from unittest import mock
        captured = {}

        def fake_searxng(q, num, since, vendor, role, site):
            captured["searxng"] = site
            raise zg.SearxngUnavailable("skip")

        with mock.patch.object(zg, "_searxng_search", side_effect=fake_searxng), \
             mock.patch.object(zg, "_sogou_search",
                               side_effect=lambda q, num, vendor, role, since, site:
                               captured.__setitem__("sogou", site) or []), \
             mock.patch.object(zg, "_baidu_fallback",
                               side_effect=lambda q, num, since, vendor, role, site:
                               captured.__setitem__("baidu", site) or []):
            zg.search("q", site="zhuanlan.zhihu.com", on_error="report")
        self.assertEqual(captured, {"searxng": "zhuanlan.zhihu.com",
                                    "sogou": "zhuanlan.zhihu.com",
                                    "baidu": "zhuanlan.zhihu.com"})

    def test_routing_intercepts_zhihu(self):
        import search as cs
        from unittest import mock
        with mock.patch.object(cs.zhihu_engine, "search",
                               return_value=[{"title": "x"}]) as zf:
            cs.search("q", platforms=["zhihu"], on_error="raise")
            self.assertEqual(
                zf.call_args.kwargs.get("site"), "zhihu.com")
            cs.search("q", platforms=["zhuanlan"], on_error="raise")
            self.assertEqual(
                zf.call_args.kwargs.get("site"), "zhuanlan.zhihu.com")


class TestGoogleBridgeImport(unittest.TestCase):
    """v2 在 Windows import 即崩（SIGUSR1 无守卫）。能 import 本身就是回归测试。"""

    def test_import_on_any_platform(self):
        import search_helper  # noqa: F401


if __name__ == "__main__":
    unittest.main(verbosity=2)
