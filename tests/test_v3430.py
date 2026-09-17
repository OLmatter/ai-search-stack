"""v3.43.0 回归：全箱精修批次（完美主义质量工程，逐项钉死）。

背景（v3.42.0 全量复审发现的四类不完美，逐项修复+钉）：
1. doctor 软警告只在末行报数不点名，cron 日志要上翻找 ⚠️ 行；TTY 直连时
   无强调——v3.43 末行点名软警告项（如「软警告 1（GitHub API）」）+ TTY
   下整行 ANSI 加粗；重定向（cron/MCP/测试的 StringIO）不加转义码。
2. 三个旧版兼容 shim（github/searxng 的 client.py）自入库起零测试覆盖
   （hackernews 那个只测了警告没测转发等价）——本批补齐警告+转发等价钉。
3. google-bridge/auto_select_node.py（看门狗拉起的选节点脚本）零测试覆盖
   ——本批补候选过滤/上限截断/预算早停/最优切换四条关键路径（全 mock）。
4. 文档计数漂移：README/SOP/SKILL/mcp_server/chat-scraper README 还写着
   「16 站」（v3.8 时代的数），实际 list_platforms()=19 平台（百度 site:
   路由 13 站）；README 目录树 search_helper v23.10 / ARCHITECTURE v23.9
   过时（实际 v23.11）；chat-scraper __init__ 版本史 v3.22→v3.21→v3.20
   乱序——全部修正并加反漂移钉。

六块内容（全部离线——mock/stdin 子进程/tmp 文本钉，零真实网络零浏览器）：
1. doctor 软警告 cron 可见性（点名/非 TTY 无 ANSI/TTY 加粗/多项点名）。
2. 兼容 shim 全覆盖（github/searxng 警告+转发等价子进程钉；hackernews
   转发等价补钉——与既有警告钉互补）。
3. auto_select_node 关键路径（skip 集过滤 + MAX_CANDIDATES 截断 +
   TIME_BUDGET 早停 + 最优切换 + 全败保现状）。
4. 平台计数钉（19 平台/13 站拆解 + 四文档无「16 站」残留）。
5. 文档版本引用钉（README v23.11 / ARCHITECTURE v23.11）+ chat-scraper
   __init__ 版本史乱序修复钉（升序单调）。
6. 错误路径离线钉（bilibili 坏 code report 协议 / hotlist 未知平台 raise
   文案含合法集 / china_search 未知平台 report 文案）+ 版本锁 3.43.0。
"""
import contextlib
import io
import json
import pathlib
import re
import subprocess
import sys
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tools" / "chat-scraper"))
sys.path.insert(0, str(REPO / "tools" / "google-bridge"))

import doctor as doctor_mod         # noqa: E402
import bilibili_engine as be        # noqa: E402
import hotlist_engine as he         # noqa: E402
import search as cs                 # noqa: E402
import auto_select_node as asn      # noqa: E402


# ---- 1. doctor 软警告 cron 可见性 --------------------------------------------


class _TTYBuf:
    """isatty()=True 的 stdout 替身（写透到内层 buf）。"""

    def __init__(self, buf):
        self._buf = buf

    def isatty(self):
        return True

    def write(self, s):
        return self._buf.write(s)

    def flush(self):
        pass


class TestWarnCronVisibility(unittest.TestCase):
    """v3.43：软警告末行点名 + TTY 加粗；cron 重定向路径零转义码。"""

    def setUp(self):
        doctor_mod._results.clear()

    @staticmethod
    def _all_checks_off(warn_names=()):
        """9 项 check 全离线替身；warn_names 里的项抛 Warn。"""
        names = ("check_searxng", "check_cookie", "check_hook_liveness",
                 "check_bilibili", "check_baidu", "check_hotlist",
                 "check_google_bridge", "check_github", "check_shift_log")
        stack = contextlib.ExitStack()
        for name in names:
            if name in warn_names:
                def fn(_n=name):
                    raise doctor_mod.Warn("降级")
            else:
                fn = lambda: "ok"   # noqa: E731
            stack.enter_context(mock.patch.object(doctor_mod, name, fn))
        return stack

    def _run(self, tty=False, warn_names=("check_bilibili",)):
        buf = io.StringIO()
        out = _TTYBuf(buf) if tty else buf
        with self._all_checks_off(warn_names=warn_names):
            with contextlib.redirect_stdout(out):
                code = doctor_mod.main([])
        return code, buf.getvalue()

    def test_warn_summary_names_the_degraded_item(self):
        # 末行点名：cron 日志只看末行即知哪个通道降级，不必上翻 ⚠️ 行
        code, out = self._run()
        self.assertIn("⚠️ bilibili 官方 API: 降级", out)
        self.assertIn("软警告 1（bilibili 官方 API）", out)
        self.assertEqual(code, 0)

    def test_multi_warn_lists_all_in_order(self):
        doctor_mod._results.clear()
        buf = io.StringIO()
        with self._all_checks_off(
                warn_names=("check_github", "check_google_bridge")):
            with contextlib.redirect_stdout(buf):
                code = doctor_mod.main([])
        # 点名顺序 = 巡检项声明顺序（google-bridge 在 GitHub 之前）
        self.assertIn("软警告 2（google-bridge 服务；GitHub API）",
                      buf.getvalue())
        self.assertEqual(code, 0)

    def test_nontty_output_has_no_ansi_escape(self):
        # cron 常态（重定向到日志文件）：\033 转义码会污染 grep/告警解析
        _, out = self._run(tty=False)
        self.assertNotIn("\033[", out)
        self.assertIn("软警告 1", out)

    def test_tty_output_bold(self):
        # TTY 直连（人眼看）：整行 ANSI 加粗
        _, out = self._run(tty=True)
        self.assertIn("\033[1m== 结果:", out)
        self.assertIn("软警告 1（bilibili 官方 API）", out)
        self.assertIn("\033[0m", out)

    def test_all_green_summary_unchanged(self):
        # 无软警告：末行与 v3.42 形态一致（无「软警告」段、无 ANSI）
        doctor_mod._results.clear()
        buf = io.StringIO()
        with self._all_checks_off():
            with contextlib.redirect_stdout(buf):
                code = doctor_mod.main([])
        out = buf.getvalue()
        self.assertNotIn("软警告", out)
        self.assertNotIn("\033[", out)
        self.assertIn("核心故障 0", out)
        self.assertEqual(code, 0)


# ---- 2. 兼容 shim 全覆盖 ------------------------------------------------------


class TestDeprecatedShims(unittest.TestCase):
    """三个 client.py 兼容 shim（hackernews/github/searxng）警告+转发等价。

    同名 client.py 同进程会 sys.modules 劫持（v2 实测事故）——转发等价
    断言必须在子进程里做（test_offline 既有警告钉的同款纪律）。
    """

    def _run_shim_probe(self, tool_dir, probe_body):
        code = (
            "import warnings, sys\n"
            "sys.path.insert(0, r'{dir}')\n"
            "with warnings.catch_warnings(record=True) as w:\n"
            "    warnings.simplefilter('always')\n"
            + probe_body + "\n"
            "dep = [x for x in w if issubclass(x.category, DeprecationWarning)]\n"
            "print('DEP' if dep else 'NODEP')\n"
        ).format(dir=REPO / "tools" / tool_dir)
        r = subprocess.run([sys.executable, "-c", code],
                           capture_output=True, text=True, timeout=60)
        return r

    def test_github_shim_warns_and_forwards_identity(self):
        r = self._run_shim_probe("github", (
            "    import github_client\n"
            "    from client import get_releases, get_advisories, search_repos\n"
            "    assert get_releases is github_client.get_releases\n"
            "    assert get_advisories is github_client.get_advisories\n"
            "    assert search_repos is github_client.search_repos\n"
            "    print('FWD')"))
        self.assertIn("DEP", r.stdout, r.stdout + r.stderr)
        self.assertIn("FWD", r.stdout, r.stdout + r.stderr)

    def test_searxng_shim_warns_and_forwards_identity(self):
        r = self._run_shim_probe("searxng", (
            "    import searxng_client\n"
            "    from client import search\n"
            "    assert search is searxng_client.search\n"
            "    print('FWD')"))
        self.assertIn("DEP", r.stdout, r.stdout + r.stderr)
        self.assertIn("FWD", r.stdout, r.stdout + r.stderr)

    def test_hackernews_shim_forwards_identity(self):
        # 警告钉已在 test_offline（WARNED）；这里补转发等价半边
        r = self._run_shim_probe("hackernews", (
            "    import hackernews_client\n"
            "    from client import search\n"
            "    assert search is hackernews_client.search\n"
            "    print('FWD')"))
        self.assertIn("DEP", r.stdout, r.stdout + r.stderr)
        self.assertIn("FWD", r.stdout, r.stdout + r.stderr)


# ---- 3. auto_select_node 关键路径 ---------------------------------------------


class TestAutoSelectNode(unittest.TestCase):
    """看门狗拉起的选节点脚本（v17 预算护栏此前零测试覆盖）。

    全 mock 零网络：GLOBAL 列表/切换走 Mock，测延迟直接桩 test_latency_via。
    """

    def _global_payload(self, names):
        return {"all": list(names)}

    def _run_main(self, candidates, latencies, max_candidates=20,
                  time_budget=60):
        """跑 main()；返回 (被测候选序列, 切换调用记录, stdout)。

        main() 走 json.load(r)（上下文管理器形态）——urlopen 给上下文
        Mock、json.load 直接返回 GLOBAL 列表。
        """
        tested, switched = [], []
        fake = self._global_payload(candidates)
        buf = io.StringIO()
        cm = mock.MagicMock()
        with mock.patch.object(asn, "MAX_CANDIDATES", max_candidates), \
             mock.patch.object(asn, "TIME_BUDGET", time_budget), \
             mock.patch.object(asn.urllib.request, "urlopen",
                               return_value=cm), \
             mock.patch.object(asn.json, "load", return_value=fake), \
             mock.patch.object(asn, "test_latency_via",
                               side_effect=lambda n: (
                                   tested.append(n)
                                   or latencies.get(n, (None, "skip")))), \
             mock.patch.object(asn, "switch_global",
                               side_effect=lambda n: switched.append(n)), \
             mock.patch.object(asn, "get_now", return_value="best"), \
             mock.patch.object(asn.time, "sleep"):
            with contextlib.redirect_stdout(buf):
                asn.main()
        return tested, switched, buf.getvalue()

    def test_skip_set_filters_non_proxy_entries(self):
        # DIRECT/REJECT/GLOBAL 等非代理条目不进测速
        tested, switched, _ = self._run_main(
            ["DIRECT", "REJECT", "GLOBAL", "COMPATIBLE", "node-a"],
            {"node-a": (0.1, 200)})
        self.assertEqual(tested, ["node-a"])
        self.assertEqual(switched, ["node-a"])

    def test_max_candidates_cap(self):
        # v17 护栏：候选数截断到 MAX_CANDIDATES（旧版全测 54 节点 7 分钟教训）
        cand = [f"n{i}" for i in range(30)]
        tested, _, _ = self._run_main(cand, {}, max_candidates=5)
        self.assertEqual(tested, cand[:5])

    def test_time_budget_stops_early(self):
        # 预算 -1（首行检查必超限；0 会在时钟精度内撞 elapsed==0.0 假负）：
        # 一个候选都不测，明示早停
        tested, switched, out = self._run_main(
            ["a", "b"], {}, time_budget=-1)
        self.assertEqual(tested, [])
        self.assertEqual(switched, [])
        self.assertIn("budget exceeded", out)

    def test_best_lowest_latency_switched(self):
        # 最优切换：三节点里 0.1s 最快者胜出
        tested, switched, out = self._run_main(
            ["slow", "fast", "mid"],
            {"slow": (0.3, 200), "fast": (0.1, 200), "mid": (0.2, 200)})
        self.assertEqual(tested, ["slow", "fast", "mid"])
        self.assertEqual(switched, ["fast"])
        self.assertIn("best: fast", out)

    def test_failed_candidates_excluded(self):
        # 失败候选（latency=None）不进结果集：剩下唯一成功者仍被切换
        tested, switched, out = self._run_main(
            ["dead1", "alive", "dead2"],
            {"dead1": (None, "timeout"), "alive": (0.2, 204),
             "dead2": (None, "refused")})
        self.assertEqual(switched, ["alive"])
        self.assertIn("FAIL", out)

    def test_all_fail_keeps_current(self):
        # 全败：保持现状不切换（输出明示，绝不瞎切）
        _, switched, out = self._run_main(
            ["a", "b"], {"a": (None, "x"), "b": (None, "y")})
        self.assertEqual(switched, [])
        self.assertIn("all failed, keeping current", out)


# ---- 4/5. 文档计数与版本引用反漂移钉 ------------------------------------------


class TestDocCountDrift(unittest.TestCase):
    """「16 站」是 v3.8 时代的数，实际 19 平台（百度 site: 路由 13 站）
    ——v3.43 全文修正并钉死，防再漂。"""

    def test_platform_total_is_19(self):
        lp = cs.list_platforms()
        self.assertEqual(len(lp), 19)

    def test_baidu_site_routed_count_is_13(self):
        # 与各文档「百度 site: 路由 13 站」声明的单一真源
        site = [k for k, v in cs.list_platforms().items()
                if v.startswith("baidu site:")]
        self.assertEqual(len(site), 13)

    def test_no_stale_16_station_claim_in_docs(self):
        for rel in ("README.md", "SOP.md", "SKILL.md", "ARCHITECTURE.md",
                    "tools/mcp_server.py", "tools/chat-scraper/README.md",
                    "tools/google-bridge/README.md"):
            text = (REPO / rel).read_text(encoding="utf-8")
            self.assertNotIn("16 站", text, rel)
            self.assertNotIn("16站", text, rel)
            self.assertNotIn("16 个站", text, rel)

    def test_readme_carries_current_counts(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("19 平台", readme)
        self.assertIn("search_helper v23.11", readme)

    def test_architecture_carries_current_helper_version(self):
        arch = (REPO / "ARCHITECTURE.md").read_text(encoding="utf-8")
        self.assertIn("search_helper v23.11", arch)
        self.assertNotIn("search_helper v23.9", arch)

    def test_changelog_history_in_package_docstring_monotonic(self):
        # chat-scraper __init__ 版本史曾乱序（v3.22→v3.21→v3.20）——
        # 钉死单调升序，防历史再被写乱
        text = (REPO / "tools" / "chat-scraper" / "__init__.py").read_text(
            encoding="utf-8")
        vers = [int(v) for v in
                re.findall(r"^v3\.(\d+)\.0：", text, re.M)]
        self.assertGreaterEqual(len(vers), 10)
        self.assertEqual(vers, sorted(vers), "版本史乱序")


# ---- 6. 错误路径离线钉 + 版本锁 ------------------------------------------------


class TestErrorPathPins(unittest.TestCase):
    """v3.43 错误路径遍测（低预算实测 + 离线复核）的离线固化钉。"""

    def test_bilibili_bad_api_code_report_protocol(self):
        # 真实遍测（坏 BV → code=-400）的离线等价：report 协议带 slug 与 query
        fake = mock.Mock(status_code=200)
        fake.json.return_value = {"code": -400, "message": "请求错误"}
        with mock.patch.object(be, "_wait_turn"), \
             mock.patch.object(be.requests.Session, "get",
                               return_value=fake):
            out = be.fetch_video("BV1invalidZZZZZZ", on_error="report")
        self.assertIn("error", out[0])
        self.assertIn("bilibili_api_error", out[0]["error"])
        self.assertIn("-400", out[0]["error"])
        self.assertEqual(out[0]["tool"], "chat-scraper")
        self.assertEqual(out[0]["query"], "BV1invalidZZZZZZ")

    def test_hotlist_unknown_platform_message_lists_supported(self):
        # 引擎 raise（MCP 层转错误 JSON）——文案必须自含合法平台集
        with self.assertRaises(ValueError) as cm:
            he.hot(platforms=["bogus_platform"])
        self.assertIn("bogus_platform", str(cm.exception))
        for supported in ("bilibili", "weibo", "zhihu"):
            self.assertIn(supported, str(cm.exception))

    def test_china_search_unknown_platform_report_mentions_list_platforms(self):
        out = cs.search("ping", platforms=["not_a_platform"])
        self.assertIn("error", out[0])
        self.assertIn("not_a_platform", out[0]["error"])
        self.assertIn("list_platforms()", out[0]["error"])


class TestVersionLock3430(unittest.TestCase):
    """精确锁已移交 test_v3440（v3.44 起降常青，交接先例
    v3.27→…→v3.40→v3.42→v3.43 链延续）：三版本载体同步本身不许破，
    只放开具体版本号。"""

    def test_versions_3430(self):
        # v3.44 起精确锁移交 test_v3440，此处降常青下限
        import mcp_server
        self.assertGreaterEqual(
            tuple(int(x) for x in mcp_server.__version__.split(".")),
            (3, 43, 0))
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        m = re.search(r'__version__ = "([^"]+)"', init_src)
        self.assertIsNotNone(m)
        ver = m.group(1)
        self.assertGreaterEqual(
            tuple(int(x) for x in ver.split(".")), (3, 43, 0))
        self.assertIn(f"chat-scraper v{ver}", init_src)
        self.assertEqual(mcp_server.__version__, ver)   # 双载体同步不许破
        digest_src = (REPO / "tools" / "digest.py").read_text(
            encoding="utf-8")
        self.assertIn(f'__version__ = "{ver}"', digest_src)


if __name__ == "__main__":
    unittest.main()
