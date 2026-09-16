"""v3.21.0 回归：cookie 寿命标定首批数据分析落账（36h 阈值维持裁决）+
doctor GBK 控制台加固 + 版本锁 3.21.0。

三块内容（全部离线，零真实请求、零浏览器、零 cookie 状态改写）：
1. GBK 控制台加固：_make_stdout_robust() 把 stdout 流切成 errors=
   "replace" 后，GBK 严格管道下打印 ✅ 不再 UnicodeEncodeError（2026-09-16
   sogou cron 部署调试期实录故障，读数由 probe_once 先落账未丢，但报告与
   退出码被杀）；StringIO（MCP 重定向路径）无 reconfigure 原样放行；
   main() 入口确实先加固再探活（patch 探活入口、严格 GBK 流下打 emoji
   验证）。
2. 标定数据结论的行为面钉死：MCP doctor cookie 模式恒为纯标定——
   mcp_server 调 _doctor.cmd_cookie_probe() 不传阈值（renew 只存在于
   显式 CLI --renew-if-older-than，MCP 探活绝不改写 cookie 状态，真实
   寿命数据流不被续期污染）；阈值语义正反路径 test_v390 已全覆盖，此处
   不重复。数据裁决本身（36h 维持）以 docstring/CHANGELOG 落账，n=1
   不钉行为。
3. 版本下限（原 3.21.0 精确锁降常青，精确锁已移交 test_v3220——
   v3.17/v3.18 先例）+ CHANGELOG 3.21.0 小节存在。
"""
import io
import pathlib
import re
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import doctor                       # noqa: E402

try:
    import mcp_server               # noqa: E402
except ImportError:                 # mcp SDK 未安装（部分 CI）——版本锁降级源码断言
    mcp_server = None


# ---- 1. GBK 控制台加固 ---------------------------------------------------------------


class TestGbkHardening(unittest.TestCase):
    def test_replaced_stdout_prints_emoji_under_gbk(self):
        """✅ 在 GBK 严格管道下退化为 '?'，不再 UnicodeEncodeError。"""
        raw = io.BytesIO()
        gbk = io.TextIOWrapper(raw, encoding="gbk", errors="strict")
        old = sys.stdout
        sys.stdout = gbk
        try:
            out = doctor._make_stdout_robust()
            self.assertIs(out, gbk)
            print("✅ ok")          # 加固前此处必炸：'gbk' codec can't encode '\u2705'
        finally:
            sys.stdout = old
        gbk.flush()                 # TextIOWrapper 有缓冲，先刷进 raw 再验字节
        self.assertIn(b"?", raw.getvalue())

    def test_stringio_without_reconfigure_passes_through(self):
        """MCP 路径（print 进 StringIO）无 reconfigure——原样放行不抛。"""
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            self.assertIs(doctor._make_stdout_robust(), buf)
        finally:
            sys.stdout = old

    def test_main_entry_applies_hardening_before_probe(self):
        """main() 先加固再探活：严格 GBK 流下探活报告的 emoji 不崩。"""
        raw = io.BytesIO()
        gbk = io.TextIOWrapper(raw, encoding="gbk", errors="strict")
        old = sys.stdout
        sys.stdout = gbk
        calls = {}
        orig = doctor.cmd_cookie_probe

        def fake_probe(renew_hours=None):
            calls["renew_hours"] = renew_hours
            print("✅ 探活报告（若未加固，strict GBK 此处必炸）")
            return 0

        doctor.cmd_cookie_probe = fake_probe
        try:
            code = doctor.main(["--cookie-probe"])
        finally:
            doctor.cmd_cookie_probe = orig
            sys.stdout = old
        gbk.flush()                 # TextIOWrapper 有缓冲，先刷进 raw 再验字节
        self.assertEqual(code, 0)
        self.assertIsNone(calls["renew_hours"])   # cookie 模式 CLI 不带阈值=纯标定
        self.assertIn(b"?", raw.getvalue())


# ---- 2. MCP cookie 模式纯标定钉 ------------------------------------------------------


class TestMcpCookieModePurity(unittest.TestCase):
    def test_mcp_doctor_cookie_mode_never_renews(self):
        """cookie 模式探活调用必须无参：renew 只存在于显式 CLI 阈值。

        v3.21 标定裁决的行为面：真实寿命数据流不可被 MCP 侧续期污染
        （标定纪律——每条 expired 都被续命，寿命分布永远测不出来）。
        """
        src = (REPO / "tools" / "mcp_server.py").read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"_doctor\.cmd_cookie_probe\(", src)),
                         1, "cookie 探活调用点应恰好一处")
        self.assertIn("code = _doctor.cmd_cookie_probe()", src,
                      "cookie 模式必须无参调用（纯标定，不传 renew 阈值）")


# ---- 3. 版本锁 3.21.0 ---------------------------------------------------------------


class TestVersionSyncV321(unittest.TestCase):
    def test_versions_3210(self):
        if mcp_server is None:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            ver = re.search(r'__version__ = "([^"]+)"', src).group(1)
        else:
            ver = mcp_server.__version__
        parts = tuple(int(x) for x in ver.split("."))
        self.assertGreaterEqual(parts, (3, 22, 0))   # 常青下限（原 3.21.0 精确锁，v3.22 移交）
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        self.assertIn(f'__version__ = "{ver}"', init_src)
        self.assertIn(f"chat-scraper v{ver}", init_src)   # docstring 首行同步

    def test_changelog_has_3210(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.21.0] - 2026-09-16", changelog)
        self.assertIn("36h 续期阈值维持", changelog)
        self.assertIn("_make_stdout_robust", changelog)


if __name__ == "__main__":
    unittest.main()
