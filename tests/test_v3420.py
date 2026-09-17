"""v3.42.0 回归：doctor 探活盲区修复 + MCP 单份输出 + 环境脆弱缓解。

背景（真实使用验证暴露的摩擦点清单，按影响排序）：
- doctor GitHub 检查此前查 `/` 只证「可达」——匿名配额耗尽时可达 ≠ 可用
  （github_* 下一个调用必 403）。v3.42 改查 /rate_limit（匿名可达、不消耗
  配额）拿 resources.core.remaining；remaining=0 抛 Warn 亮 ⚠️ 不翻退出码。
- doctor google-bridge 检查此前 /health ok 即 ✅「在跑」——Chrome 自动升级
  后本地 chromedriver major 错配，首次 /search 才炸 session not created。
  v3.42 helper /health 带版本诊断字段，doctor 不匹配亮 ⚠️。
- MCP 输出双份（mcp 2.1.1 func_metadata.convert_result：`-> str` 注解触发
  wrap_output，CallToolResult 同时带 content=[TextContent(整份 JSON)] 与
  structured_content={"result": 整份 JSON}——客户端两份都喂 LLM，上下文
  翻倍）。v3.42 全 15 工具 structured_output=False 关停，wire 上单份。
- doctor CLI 只有三个 flag、MCP doctor 是 mode 四态——v3.42 补 --mode 对齐。
- HN Algolia 不解析布尔语法（OR 被当普通词，结果跑偏）——docstring/MCP
  description 如实声明，LLM 调用方读描述即会拆查。
- china_search 门面 since 默认 None（不过滤）与 hn/searxng/googlebridge
  各引擎默认 7d 不齐——监控场景忘传 since 混入旧闻。v3.42 门面默认 7d，
  显式 None/"" 仍可不过滤（旧调用方兼容）。

八块内容（全部离线——mock 探活/引擎、tmp 假二进制树、源码钉，零真实
网络零浏览器；google-bridge 只 import + 纯函数诊断，不启动服务器）：
1. doctor Warn 软警告机制（⚠️ 不翻退出码，统计行独立计数）。
2. check_github /rate_limit（配额读数/耗尽 Warn/无字段诚实/UA+Bearer 不回退）。
3. check_google_bridge 版本自检（匹配/错配 Warn/旧 helper 未验/单边未验）。
4. doctor --mode 与旧 flag 并存语义（等价/冗余合法/冲突报错/full 路径）。
5. MCP 单份输出（15 工具 output_schema 全 None + wire 级 content 单块
   structured_content None；mcp SDK 未装整类跳过）。
6. search_helper version_diagnostics（同 major/错配/无 driver uc 自动下载
   分支/单边未知/NO1_CHROME_BIN 覆盖/Windows 版本子目录提取）。
7. china_search since 默认 7d（门面透传/MCP 签名/CLI 默认/显式 None 兼容）。
8. HN 布尔语法声明 + 版本锁 3.42.0（mcp_server/CHANGELOG/README 三点）。
"""
import asyncio
import contextlib
import inspect
import io
import json
import os
import pathlib
import re
import sys
import tempfile
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tools" / "chat-scraper"))
sys.path.insert(0, str(REPO / "tools" / "hackernews"))
sys.path.insert(0, str(REPO / "tools" / "google-bridge"))

import doctor as doctor_mod         # noqa: E402
import search as cs                 # noqa: E402  (chat-scraper/search.py)
import search_helper as sh          # noqa: E402  (google-bridge，import 即回归)

try:
    import mcp_server               # noqa: E402
except ImportError:                 # mcp SDK 未安装（离线 CI 等）
    mcp_server = None

import hackernews_client as hn      # noqa: E402


# ---- 1. doctor Warn 软警告机制 ----------------------------------------------


class TestWarnMechanism(unittest.TestCase):
    """Warn = 探活通过但可用性降级：⚠️ 显示、不进故障数、不翻退出码。"""

    def setUp(self):
        doctor_mod._results.clear()

    @staticmethod
    def _all_checks_off(warn_fn=None):
        """9 项 check 全部离线替身：默认恒 ok；warn_fn 替换 bilibili 项。"""
        names = ("check_searxng", "check_cookie", "check_hook_liveness",
                 "check_bilibili", "check_baidu", "check_hotlist",
                 "check_google_bridge", "check_github", "check_shift_log")
        stack = contextlib.ExitStack()
        for name in names:
            fn = warn_fn if (warn_fn and name == "check_bilibili") \
                else (lambda: "ok")
            stack.enter_context(mock.patch.object(doctor_mod, name, fn))
        return stack

    def test_warn_shown_and_not_counted_as_failure(self):
        with self._all_checks_off(
                warn_fn=lambda: (_ for _ in ()).throw(
                    doctor_mod.Warn("配额耗尽"))):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = doctor_mod.main([])
        out = buf.getvalue()
        self.assertIn("⚠️ bilibili 官方 API: 配额耗尽", out)
        # Warn 是 ok=True：不进核心故障，退出码不翻
        self.assertIn("核心故障 0", out)
        self.assertEqual(code, 0)

    def test_warn_counted_in_summary_line(self):
        with self._all_checks_off(
                warn_fn=lambda: (_ for _ in ()).throw(
                    doctor_mod.Warn("x"))):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = doctor_mod.main([])
        self.assertIn("软警告 1", buf.getvalue())
        self.assertEqual(code, 0)

    def test_hard_failure_still_exits_1(self):
        def boom():
            raise RuntimeError("网络炸了")

        with self._all_checks_off(warn_fn=boom):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = doctor_mod.main([])
        self.assertEqual(code, 1)
        self.assertIn("❌ bilibili 官方 API", buf.getvalue())


# ---- 2. check_github /rate_limit ---------------------------------------------

_RATE_OK = json.dumps({"resources": {"core": {"limit": 60, "remaining": 47,
                                              "reset": 9}}})
_RATE_ZERO = json.dumps({"resources": {"core": {"limit": 60, "remaining": 0,
                                                "reset": 0}}})


class TestCheckGithubRateLimit(unittest.TestCase):
    """v3.42 探活盲区修复：/ 只证可达，/rate_limit 才能看见配额。"""

    def _run(self, body, env=None):
        calls = {}

        def fake_get(url, timeout=doctor_mod.TIMEOUT, headers=None):
            calls["url"] = url
            calls["headers"] = headers
            return body

        with mock.patch.dict(os.environ, env or {}, clear=True), \
             mock.patch.object(doctor_mod, "_get", side_effect=fake_get):
            detail = doctor_mod.check_github()
        return calls, detail

    def test_queries_rate_limit_endpoint_with_auth_headers(self):
        calls, detail = self._run(_RATE_OK,
                                  {"GITHUB_TOKEN": "ghp_x"})
        self.assertIn("https://api.github.com/rate_limit", calls["url"])
        self.assertEqual(calls["headers"]["Authorization"], "Bearer ghp_x")
        self.assertEqual(calls["headers"]["User-Agent"],
                         "ai-search-stack-doctor")   # v3.11 UA 修复不回退

    def test_positive_remaining_reports_quota_readout(self):
        _, detail = self._run(_RATE_OK)
        self.assertIn("200", detail)                 # v3110 形态锚兼容
        self.assertIn("remaining=47/60", detail)
        self.assertNotIn("配额耗尽", detail)

    def test_zero_remaining_raises_warn_with_reset_hint(self):
        with self.assertRaises(doctor_mod.Warn) as cm:
            self._run(_RATE_ZERO)
        msg = str(cm.exception)
        self.assertIn("配额耗尽", msg)
        self.assertIn("remaining=0/60", msg)
        self.assertIn("GITHUB_TOKEN", msg)           # 可操作提示

    def test_missing_core_fields_reports_honestly(self):
        # 端点 200 但无 resources.core（响应形态变化）——可达性结论保留，
        # 配额读数如实标「不可得」，不假装有读数（本仓库反假装纪律）
        _, detail = self._run("{}")
        self.assertIn("200", detail)
        self.assertIn("配额读数不可得", detail)

    def test_http_error_propagates_unchanged(self):
        # v3110 既有锚：HTTPError 照常上抛由 _check 包装成 ❌（通道故障）
        import urllib.error
        err = urllib.error.HTTPError("https://api.github.com/rate_limit",
                                     403, "rate limit exceeded", None, None)
        with mock.patch.object(doctor_mod, "_get", side_effect=err):
            with self.assertRaises(urllib.error.HTTPError):
                doctor_mod.check_github()


# ---- 3. check_google_bridge 版本自检 -----------------------------------------


class TestCheckGoogleBridgeVersion(unittest.TestCase):
    """/health ok 之后读版本诊断字段：错配 Warn、旧 helper 如实「未验」。"""

    def _run(self, payload):
        with mock.patch.object(doctor_mod, "_get",
                               return_value=json.dumps(payload)):
            return doctor_mod.check_google_bridge()

    def test_match_true_shows_versions(self):
        detail = self._run({"ok": True, "chrome_version": "152.0.1.1",
                            "chromedriver_version": "152.0.2.2",
                            "version_match": True})
        self.assertIn("版本匹配", detail)
        self.assertIn("152.0.1.1", detail)

    def test_mismatch_raises_warn_with_fix_hint(self):
        with self.assertRaises(doctor_mod.Warn) as cm:
            self._run({"ok": True, "chrome_version": "152.0.1.1",
                       "chromedriver_version": "141.0.2.2",
                       "version_match": False})
        msg = str(cm.exception)
        self.assertIn("版本错配", msg)
        self.assertIn("--check-versions", msg)       # 落地诊断命令指路

    def test_legacy_helper_reports_unverified(self):
        # 旧版 helper 无版本字段——「版本未验」，不假装验过
        detail = self._run({"ok": True})
        self.assertIn("版本未验", detail)

    def test_match_none_reports_partial(self):
        detail = self._run({"ok": True, "chrome_version": "152.0.1.1",
                            "chromedriver_version": None,
                            "version_match": None})
        self.assertIn("匹配性未验", detail)


# ---- 4. doctor --mode CLI 对齐 -----------------------------------------------


class TestDoctorModeFlag(unittest.TestCase):
    """--mode 与旧 flag 并存：等价映射、冗余合法、冲突报错、full 全量。"""

    def setUp(self):
        doctor_mod._results.clear()

    def test_mode_cookie_dispatches_probe(self):
        with mock.patch.object(doctor_mod, "cmd_cookie_probe",
                               return_value=0) as m:
            code = doctor_mod.main(["--mode", "cookie"])
        m.assert_called_once_with(renew_hours=None)
        self.assertEqual(code, 0)

    def test_legacy_flag_still_dispatches(self):
        # 向后兼容锚：--cookie-probe 语义不变（v3.42 前唯一入口）
        with mock.patch.object(doctor_mod, "cmd_sogou_probe",
                               return_value=0) as m:
            doctor_mod.main(["--sogou-probe"])
        m.assert_called_once_with()

    def test_mode_accepts_renew_combo(self):
        # --mode cookie 与 --renew-if-older-than 组合（cron 运维路径）
        with mock.patch.object(doctor_mod, "cmd_cookie_probe",
                               return_value=0) as m:
            doctor_mod.main(["--mode", "cookie",
                             "--renew-if-older-than", "36"])
        m.assert_called_once_with(renew_hours=36.0)

    def test_conflicting_mode_and_flag_errors(self):
        with self.assertRaises(SystemExit):
            doctor_mod.main(["--mode", "cookie", "--sogou-probe"])

    def test_redundant_matching_mode_and_flag_ok(self):
        with mock.patch.object(doctor_mod, "cmd_cookie_probe",
                               return_value=0) as m:
            doctor_mod.main(["--mode", "cookie", "--cookie-probe"])
        m.assert_called_once()

    def test_mode_full_runs_full_sweep_zero_network(self):
        # 全量路径 9 项 check 全 mock：--mode full 与默认无参等价
        with TestWarnMechanism._all_checks_off():
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = doctor_mod.main(["--mode", "full"])
        self.assertEqual(code, 0)
        self.assertIn("核心 3/3 正常", buf.getvalue())


# ---- 5. MCP 单份输出 ----------------------------------------------------------


@unittest.skipUnless(mcp_server, "mcp SDK 未安装，跳过 MCP server 离线测试")
class TestMcpSingleCopyOutput(unittest.TestCase):
    """mcp 2.1.1 双份输出机制关停：structured_output=False 全 15 工具生效。"""

    def test_all_tools_output_schema_none(self):
        # 根因钉：`-> str` 注解会派生 output_schema → wire 上 content 与
        # structured_content 双份。关停后 schema 必须全 None。
        tools = asyncio.run(mcp_server.mcp.list_tools())
        self.assertEqual(len(tools), 15)
        offenders = [t.name for t in tools if t.output_schema is not None]
        self.assertEqual(offenders, [],
                         "这些工具仍在发布 output_schema（wire 双份输出）")

    def test_call_tool_single_content_no_structured(self):
        # wire 级：真走 convert_result 路径——content 单块 + 无 structured
        def fake_search(q, **kw):
            return [{"title": "t1", "url": "u1"}]

        with mock.patch.object(mcp_server._hn, "search", fake_search):
            res = asyncio.run(
                mcp_server.mcp.call_tool("hn_search", {"q": "rust"}))
        self.assertEqual(len(res.content), 1, "明文应恰一份")
        self.assertIsNone(res.structured_content, "structured 应整体缺席")
        self.assertEqual(json.loads(res.content[0].text),
                         [{"title": "t1", "url": "u1"}])


# ---- 6. search_helper 版本诊断 ------------------------------------------------


class TestSearchHelperVersionDiagnostics(unittest.TestCase):
    """v23.11 版本自检：只诊断不下载；三态 match（True/False/None）。"""

    def test_same_major_matches(self):
        with mock.patch.object(sh, "_extract_chrome_version",
                               return_value="152.0.7977.83"), \
             mock.patch.object(sh, "_extract_driver_version",
                               return_value="152.0.8000.9"), \
             mock.patch.object(sh, "_find_chromedriver", return_value="d"), \
             mock.patch.object(sh, "_default_chrome_bin", return_value="c"):
            diag = sh.version_diagnostics()
        self.assertIs(diag["version_match"], True)
        self.assertIn("匹配", diag["note"])

    def test_major_mismatch_is_false_with_fix_hint(self):
        with mock.patch.object(sh, "_extract_chrome_version",
                               return_value="152.0.7977.83"), \
             mock.patch.object(sh, "_extract_driver_version",
                               return_value="141.0.7399.110"), \
             mock.patch.object(sh, "_find_chromedriver", return_value="d"), \
             mock.patch.object(sh, "_default_chrome_bin", return_value="c"):
            diag = sh.version_diagnostics()
        self.assertIs(diag["version_match"], False)
        self.assertIn("错配", diag["note"])
        self.assertIn("不自动下载", diag["note"])     # 纪律写进指引

    def test_no_driver_means_uc_autodownload_match_none(self):
        # driver 未定位 = uc 自动下载分支：无法本地判定，如实 None
        with mock.patch.object(sh, "_find_chromedriver", return_value=None):
            diag = sh.version_diagnostics(chrome_bin="c")
        self.assertIsNone(diag["chromedriver_bin"])
        self.assertIsNone(diag["version_match"])
        self.assertIn("自动下载", diag["note"])

    def test_one_side_unknown_is_none_not_fake(self):
        # 单边有版本（如 driver 文件不在）——match=None，不编造结论
        with mock.patch.object(sh, "_extract_chrome_version",
                               return_value="152.0.1.1"), \
             mock.patch.object(sh, "_extract_driver_version",
                               return_value=None), \
             mock.patch.object(sh, "_find_chromedriver",
                               return_value="ghost"), \
             mock.patch.object(sh, "_default_chrome_bin", return_value="c"):
            diag = sh.version_diagnostics()
        self.assertIsNone(diag["version_match"])
        self.assertIn("未验", diag["note"])

    def test_no1_chrome_bin_env_wins(self):
        with mock.patch.dict(os.environ,
                             {"NO1_CHROME_BIN": r"X:\custom\chrome.exe"},
                             clear=True):
            self.assertEqual(sh._default_chrome_bin(),
                             r"X:\custom\chrome.exe")

    @unittest.skipUnless(sys.platform == "win32",
                         "版本子目录布局提取是 Windows 路径")
    def test_windows_version_subdir_extraction(self):
        with tempfile.TemporaryDirectory() as td:
            fake_bin = os.path.join(td, "chrome.exe")
            open(fake_bin, "wb").close()
            os.mkdir(os.path.join(td, "141.0.7399.109"))
            os.mkdir(os.path.join(td, "152.0.7977.83"))
            self.assertEqual(sh._extract_chrome_version(fake_bin),
                             "152.0.7977.83")   # 多版本目录取最高

    def test_extract_chrome_version_missing_file_is_none(self):
        self.assertIsNone(sh._extract_chrome_version(None))
        self.assertIsNone(sh._extract_chrome_version(r"Z:\nope\chrome.exe"))

    def test_extract_driver_version_missing_file_is_none(self):
        self.assertIsNone(sh._extract_driver_version(None))

    def test_cmd_check_versions_exit_codes(self):
        for match, want in ((True, 0), (None, 0), (False, 1)):
            with mock.patch.object(sh, "version_diagnostics",
                                   return_value={"version_match": match,
                                                 "note": "n"}):
                self.assertEqual(sh._cmd_check_versions(), want)

    def test_main_check_versions_flag_routes_to_diagnostic(self):
        # --check-versions 进诊断分支即 sys.exit——不绑端口不起服务器
        with mock.patch.object(sys, "argv",
                               ["search_helper", "--check-versions"]), \
             mock.patch.object(sh, "_cmd_check_versions",
                               return_value=0) as m:
            with self.assertRaises(SystemExit):
                sh.main()
        m.assert_called_once()

    def test_health_payload_uses_helper_version_constant(self):
        # 源码钉：/health version 字样与 main 启动横幅同走 _HELPER_VERSION
        # （main 打印曾停在 v23.9 而实际 v23.10——字样漂移先例）
        src = (REPO / "tools" / "google-bridge" / "search_helper.py"
               ).read_text(encoding="utf-8")
        self.assertIn("'version': _HELPER_VERSION", src)
        self.assertIn("search_helper {_HELPER_VERSION}", src)
        self.assertNotIn("'version': 'v23.10'", src)
        self.assertIn("v23.11", sh._HELPER_VERSION)


# ---- 7. china_search since 默认 7d --------------------------------------------


class TestChinaSearchSinceDefault(unittest.TestCase):
    """门面默认与各引擎统一：忘传 since = 7d；显式 None 兼容不过滤。"""

    def test_facade_default_now_7d(self):
        calls = {}

        def fake_bili(q, **kw):
            calls.update(q=q, **kw)
            return []

        with mock.patch.object(cs.bilibili_engine, "search", fake_bili):
            cs.search("测试", platforms=["bilibili"])
        self.assertEqual(calls["since"], "7d")

    def test_explicit_none_still_disables_filter(self):
        # 旧调用方兼容锚：显式 None 语义不变（不过滤）
        calls = {}

        def fake_bili(q, **kw):
            calls.update(q=q, **kw)
            return []

        with mock.patch.object(cs.bilibili_engine, "search", fake_bili):
            cs.search("测试", platforms=["bilibili"], since=None)
        self.assertIsNone(calls["since"])

    def test_mcp_signature_default_7d(self):
        sig = inspect.signature(mcp_server.china_search)
        self.assertEqual(sig.parameters["since"].default, "7d")

    def test_mcp_passthrough_keeps_explicit_value(self):
        calls = {}

        def fake_search(q, **kw):
            calls.update(q=q, **kw)
            return []

        with mock.patch.object(mcp_server._chat, "search", fake_search):
            mcp_server.china_search(q="x", since="24h")
        self.assertEqual(calls["since"], "24h")

    def test_cli_default_7d(self):
        # CLI 是门面的第二入口（值班手跑场景）——同一默认
        src = (REPO / "tools" / "chat-scraper" / "search.py"
               ).read_text(encoding="utf-8")
        self.assertIn('"--since", default="7d"', src)


# ---- 8. HN 布尔声明 + 版本锁 ---------------------------------------------------


class TestHnBooleanDeclaration(unittest.TestCase):
    """Algolia 不解析布尔语法——诚实声明给 LLM 调用方（MCP 描述即路由提示）。"""

    def test_client_docstring_declares_no_boolean(self):
        doc = hn.search.__doc__ or ""
        self.assertIn("布尔", doc)
        self.assertIn("OR", doc)
        self.assertIn("拆成", doc)

    def test_mcp_description_declares_no_boolean(self):
        # 装饰器透传原函数——MCP description 在注册表里（tools/list 载荷）
        tools = asyncio.run(mcp_server.mcp.list_tools())
        desc = {t.name: t.description for t in tools}["hn_search"]
        self.assertIn("布尔", desc)
        self.assertIn("OR", desc)


class TestVersionLock(unittest.TestCase):
    """精确锁已移交 test_v3430（v3.43 起降常青，交接先例
    v3.27→…→v3.40→v3.42 链延续）：双/三版本载体同步本身不许破，
    只放开具体版本号。"""

    def test_versions_3420(self):
        # v3.43 起精确锁移交 test_v3430，此处降常青下限
        self.assertGreaterEqual(
            tuple(int(x) for x in mcp_server.__version__.split(".")),
            (3, 42, 0))
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        m = re.search(r'__version__ = "([^"]+)"', init_src)
        self.assertIsNotNone(m)
        ver = m.group(1)
        self.assertGreaterEqual(
            tuple(int(x) for x in ver.split(".")), (3, 42, 0))
        self.assertIn(f"chat-scraper v{ver}", init_src)
        self.assertEqual(mcp_server.__version__, ver)   # 双载体同步不许破
        digest_src = (REPO / "tools" / "digest.py").read_text(
            encoding="utf-8")
        self.assertIn(f'__version__ = "{ver}"', digest_src)

    def test_changelog_and_readme_3420(self):
        # 3.42 批次的 CHANGELOG 事实行永久在场；徽章/标题行精确锁已移交
        # test_v3430，此处降常青单调下限（810 = 770 + 本批 40 钉）
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.42.0] - 2026-09-17", changelog)
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        m = re.search(r"tests-(\d+)%20passing", readme)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(int(m.group(1)), 810)


if __name__ == "__main__":
    unittest.main(verbosity=2)
