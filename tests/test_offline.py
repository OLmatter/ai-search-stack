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


class TestGoogleBridgeImport(unittest.TestCase):
    """v2 在 Windows import 即崩（SIGUSR1 无守卫）。能 import 本身就是回归测试。"""

    def test_import_on_any_platform(self):
        import search_helper  # noqa: F401


if __name__ == "__main__":
    unittest.main(verbosity=2)
