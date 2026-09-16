"""v3.33.0 回归：每日晨报聚合 digest.py + digest_task.py 班次接线。

四块内容（全部离线，零真实网络请求——真实链路走 digest 实测落
CHANGELOG v3.33.0；回归钉全走 mock / tmp 文件 / runner 注入 / 源码钉）：
1. digest（tools/ 顶层跨工具组合层——hotlist_watch v3.31 调用方层先例，
   引擎/MCP 零改动）：配置缺失/坏/键类型错落回默认并注明、HN/GitHub
   段 error 行与 fetcher 抛异常双路降级、热榜段消费监控环产物（快照 +
   shift_log 今日 hotlist_watch 行）零网络、快照缺失诚实 empty 不代采、
   --sample-hotlist 注入采样、toolbox 段 doctor 本地状态（不跑全量巡检
   ——5+ 发网络会爆晨报预算）、全段 fault 才 overall=fault、班次日志行
   被 doctor._shift_log_stats 解析（跨解析器承重契约）。
2. digest_task（schtasks 注册器，hotlist_watch_task v3.31 同款）：register
   argv 形态（DAILY/TN/TR 嵌入引号 + --log）/失败退出码/TR 超长不注册/
   非 win32 诚实报错/status/unregister 幂等/GBK 解码回退链/10:00 错峰
   推导进 docstring。
3. 版本锁 3.33.0（双 __version__，自 test_v3310 接管精确锁）+ CHANGELOG
   + README 徽章 + 诚实文档钉（组合层归属推导/退出码契约/网络预算
   承重值）。
"""
import io
import json
import pathlib
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "chat-scraper"))
sys.path.insert(0, str(REPO / "tools"))

import digest as dg                 # noqa: E402
import digest_task as task          # noqa: E402
import hotlist_watch as hw          # noqa: E402
import doctor                       # noqa: E402

NOW = datetime(2026, 9, 17, 10, 0)


def _hn_row(title, points=100, comments=40):
    return {"title": title, "url": f"http://x/{title}", "content": "",
            "points": points, "comments": comments, "author": "a",
            "ts": "2026-09-17T00:00:00Z", "vendor": "?", "role": "verify",
            "since": "24h"}


def _rel_row(tag="v1.0.0", title="v1", content="notes here"):
    return {"title": title, "url": f"http://r/{tag}", "content": content,
            "tag": tag, "ts": "2026-09-17T00:00:00Z", "prerelease": False,
            "vendor": "?", "role": "verify", "since": "all"}


def _snap_rows():
    return [{"platform": "bilibili", "rank": 1, "title": "A", "url": "ua"},
            {"platform": "weibo", "rank": 1, "title": "W", "url": "uw"},
            {"platform": "weibo", "rank": 2, "title": "W2", "url": "uw2"},
            {"platform": "weibo", "rank": 3, "error": "HTTPError: 403"}]


# ---------------------------------------------------------------------------
# 1a. 配置（缺失/坏 -> 内置默认 + 注明；配置问题不炸整体）
# ---------------------------------------------------------------------------
class TestConfig(unittest.TestCase):
    def test_missing_file_falls_back_with_note(self):
        with tempfile.TemporaryDirectory() as td:
            r = dg.load_config(str(Path(td) / "nope.json"))
        self.assertEqual(r["config"]["watch_repos"], dg.DEFAULT_REPOS)
        self.assertIn("配置未找到", r["note"])

    def test_bad_json_falls_back(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.json"
            p.write_text("{not json", encoding="utf-8")
            r = dg.load_config(str(p))
        self.assertIn("配置解析失败", r["note"])
        self.assertEqual(r["config"]["watch_queries"], dg.DEFAULT_QUERIES)

    def test_non_object_falls_back(self):
        r = dg.load_config(loader=lambda p: "[1,2,3]")
        self.assertIn("顶层不是", r["note"])
        self.assertEqual(r["config"]["watch_repos"], dg.DEFAULT_REPOS)

    def test_key_type_wrong_falls_back_per_key(self):
        r = dg.load_config(loader=lambda p: json.dumps(
            {"watch_repos": "not-a-list", "watch_queries": [1, 2]}))
        self.assertEqual(r["config"]["watch_repos"], dg.DEFAULT_REPOS)
        self.assertEqual(r["config"]["watch_queries"], dg.DEFAULT_QUERIES)
        self.assertIn("类型不对", r["note"])

    def test_valid_config_loaded(self):
        cfg = {"watch_repos": ["a/b"], "watch_queries": ["q1", "q2"],
               "watch_platforms": ["bilibili"]}
        r = dg.load_config(loader=lambda p: json.dumps(cfg))
        self.assertEqual(r["config"], cfg)
        self.assertEqual(r["note"], "")

    def test_blank_entries_filtered(self):
        r = dg.load_config(loader=lambda p: json.dumps(
            {"watch_queries": ["q1", "  "]}))
        self.assertEqual(r["config"]["watch_queries"], ["q1"])


# ---------------------------------------------------------------------------
# 1b. HN 段（error 行 + fetcher 抛异常双路降级）
# ---------------------------------------------------------------------------
class TestHnSection(unittest.TestCase):
    def test_ok_rows(self):
        def fn(q, num):
            return [_hn_row(f"t-{q}")]
        r = dg.fetch_hn(["q1"], fetcher=fn)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["queries"][0]["rows"][0]["title"], "t-q1")

    def test_error_row_degrades_to_query_error(self):
        def fn(q, num):
            return [{"error": "URLError: timeout", "tool": "hackernews"}]
        r = dg.fetch_hn(["q1", "q2"], fetcher=fn)
        self.assertEqual(r["status"], "fault")
        self.assertIn("URLError", r["queries"][0]["error"])

    def test_fetcher_raise_degrades_not_raises(self):
        def fn(q, num):
            raise RuntimeError("boom")
        r = dg.fetch_hn(["q1"], fetcher=fn)
        self.assertEqual(r["status"], "fault")
        self.assertIn("RuntimeError: boom", r["queries"][0]["error"])

    def test_partial_fault_section_still_ok(self):
        calls = {"n": 0}

        def fn(q, num):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("first dies")
            return [_hn_row("second-ok")]
        r = dg.fetch_hn(["a", "b"], fetcher=fn)
        self.assertEqual(r["status"], "ok")      # 单查询挂 = 段内降级非段 fault
        self.assertIn("error", r["queries"][0])
        self.assertEqual(r["queries"][1]["rows"][0]["title"], "second-ok")


# ---------------------------------------------------------------------------
# 1c. GitHub 段（同款双路降级）
# ---------------------------------------------------------------------------
class TestReleasesSection(unittest.TestCase):
    def test_ok_rows(self):
        r = dg.fetch_releases(["a/b"], fetcher=lambda repo, num: [_rel_row()])
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["repos"][0]["rows"][0]["tag"], "v1.0.0")

    def test_error_row_degrades(self):
        def fn(repo, num):
            return [{"error": "HTTPError: 403 rate limit", "tool": "github"}]
        r = dg.fetch_releases(["a/b", "c/d"], fetcher=fn)
        self.assertEqual(r["status"], "fault")
        self.assertIn("403", r["repos"][0]["error"])

    def test_fetcher_raise_degrades_not_raises(self):
        def fn(repo, num):
            raise OSError("net down")
        r = dg.fetch_releases(["a/b"], fetcher=fn)
        self.assertEqual(r["status"], "fault")
        self.assertIn("OSError", r["repos"][0]["error"])

    def test_partial_fault_section_still_ok(self):
        def fn(repo, num):
            if repo == "bad/repo":
                return [{"error": "HTTPError: 404"}]
            return [_rel_row()]
        r = dg.fetch_releases(["bad/repo", "good/repo"], fetcher=fn)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["repos"][1]["rows"][0]["tag"], "v1.0.0")


# ---------------------------------------------------------------------------
# 1d. 热榜段（消费监控环产物零网络；empty 诚实；sample 备用路径）
# ---------------------------------------------------------------------------
class TestHotlistSection(unittest.TestCase):
    def _fixture(self, td):
        snap_dir = Path(td) / "snaps"
        shift_log = Path(td) / "shift_log.md"
        hw.save_snapshot(str(snap_dir), _snap_rows(),
                         ["bilibili", "weibo"], 20, now=NOW)
        shift_log.write_text(
            "[2026-09-17 09:45] hotlist_watch: diff（bilibili+weibo）"
            "新增 2 消失 1 保留 37\n"
            "[2026-09-16 08:00] hotlist_watch: diff（bilibili+weibo）"
            "新增 0 消失 0 保留 40\n", encoding="utf-8")
        return str(snap_dir), str(shift_log)

    def test_consumes_snapshot_and_today_watch_lines(self):
        with tempfile.TemporaryDirectory() as td:
            sd, sl = self._fixture(td)
            r = dg.fetch_hotlist(snapshots_dir=sd, shift_log=sl, today=NOW)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(len(r["watch_lines"]), 1)      # 只取今日行
        self.assertIn("新增 2", r["watch_lines"][0])
        self.assertTrue(r["snapshot_ts"].startswith("2026-09-17"))
        # error 行不进 top（宁缺勿错，hot_diff 同款剔除）
        self.assertTrue(all("error" not in x for x in r["top"]))

    def test_platform_filter(self):
        with tempfile.TemporaryDirectory() as td:
            sd, sl = self._fixture(td)
            r = dg.fetch_hotlist(snapshots_dir=sd, shift_log=sl, today=NOW,
                                 platforms=["weibo"])
        self.assertEqual({x["platform"] for x in r["top"]}, {"weibo"})

    def test_snapshot_missing_empty_honest_not_fault(self):
        with tempfile.TemporaryDirectory() as td:
            r = dg.fetch_hotlist(snapshots_dir=str(Path(td) / "nope"),
                                 shift_log=str(Path(td) / "n.log"),
                                 today=NOW)
        self.assertEqual(r["status"], "empty")
        self.assertIn("监控环未启用", r["error"])
        self.assertIn("hotlist_watch.py", r["error"])   # 指路建基线

    def test_sample_mode_uses_injected_sampler(self):
        calls = []

        def sampler(platforms, num):
            calls.append((list(platforms), num))
            return [{"platform": "bilibili", "rank": 1, "title": "S",
                     "url": "us"}]
        with tempfile.TemporaryDirectory() as td:
            r = dg.fetch_hotlist(snapshots_dir=str(Path(td) / "nope"),
                                 shift_log=str(Path(td) / "n.log"),
                                 today=NOW, sample=True, sampler=sampler)
        self.assertEqual(r["status"], "ok")
        self.assertEqual(calls, [(["bilibili", "weibo"], 20)])
        self.assertIn("现场采样", r["snapshot_ts"])

    def test_sample_zero_valid_fault(self):
        def sampler(platforms, num):
            return [{"error": "HTTPError: 412", "platform": "bilibili"}]
        with tempfile.TemporaryDirectory() as td:
            r = dg.fetch_hotlist(snapshots_dir=str(Path(td) / "nope"),
                                 today=NOW, sample=True, sampler=sampler)
        self.assertEqual(r["status"], "fault")
        self.assertIn("零有效行", r["error"])

    def test_sample_partial_error_note(self):
        def sampler(platforms, num):
            return [{"platform": "bilibili", "rank": 1, "title": "S",
                     "url": "us"},
                    {"error": "HTTPError: 403", "platform": "weibo"}]
        with tempfile.TemporaryDirectory() as td:
            r = dg.fetch_hotlist(snapshots_dir=str(Path(td) / "nope"),
                                 today=NOW, sample=True, sampler=sampler)
        self.assertEqual(r["status"], "ok")
        self.assertIn("部分平台异常", r["platforms_note"])

    def test_sample_sampler_raise_degrades(self):
        def sampler(platforms, num):
            raise RuntimeError("net down")
        with tempfile.TemporaryDirectory() as td:
            r = dg.fetch_hotlist(snapshots_dir=str(Path(td) / "nope"),
                                 today=NOW, sample=True, sampler=sampler)
        self.assertEqual(r["status"], "fault")
        self.assertIn("RuntimeError", r["error"])


# ---------------------------------------------------------------------------
# 1e. 工具箱状态段（doctor 本地状态零网络；不跑全量巡检）
# ---------------------------------------------------------------------------
class TestToolboxSection(unittest.TestCase):
    def test_reads_shift_stats_cookie_snapshots(self):
        with tempfile.TemporaryDirectory() as td:
            sl = Path(td) / "shift_log.md"
            sl.write_text("[2026-09-17 08:00] 值班巡检: ok\n",
                          encoding="utf-8")
            sd = Path(td) / "snaps"
            hw.save_snapshot(str(sd), _snap_rows(), ["bilibili"], 20, now=NOW)
            r = dg.fetch_toolbox(now=NOW, shift_log=str(sl),
                                 snapshots_dir=str(sd))
        self.assertEqual(r["status"], "ok")
        self.assertIn("近 7 天", r["shift_stats"])
        self.assertEqual(r["snapshots_n"], 1)
        self.assertEqual(r["snapshots_latest"], NOW.strftime("%Y%m%d_%H%M%S"))

    def test_missing_files_ok_with_none_semantics(self):
        # 隔离真实 state（本机有真实 cookie/标定日志）：路径 patch 到
        # tmp 不存在文件，验证「缺失=可选观测常态」语义
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(doctor, "COOKIE_PATH",
                                   str(Path(td) / "no_cookie.json")), \
                 mock.patch.object(doctor, "WEIBO_LIFETIME_LOG_PATH",
                                   str(Path(td) / "no_weibo.jsonl")):
                r = dg.fetch_toolbox(now=NOW, shift_log=str(Path(td) / "n"),
                                     snapshots_dir=str(Path(td) / "nope"))
        self.assertEqual(r["status"], "ok")
        self.assertIsNone(r["shift_stats"])
        self.assertIsNone(r["cookie_age_h"])
        self.assertIsNone(r["weibo_reading"])

    def test_internal_error_degrades_to_fault(self):
        with mock.patch.object(doctor, "_shift_log_stats",
                               side_effect=RuntimeError("boom")):
            r = dg.fetch_toolbox(now=NOW, shift_log="x", snapshots_dir="y")
        self.assertEqual(r["status"], "fault")
        self.assertIn("boom", r["error"])

    def test_no_full_doctor_sweep_network_budget_pin(self):
        # 网络预算承重钉：digest 的 toolbox 段只读本地状态，绝不调
        # doctor.main()/check_*（那是 5+ 发网络探活，嵌进晨报会爆预算）。
        src = (REPO / "tools" / "digest.py").read_text(encoding="utf-8")
        self.assertNotIn("dr.main(", src)
        self.assertNotIn("check_searxng", src)
        self.assertNotIn("check_bilibili", src)
        self.assertIn("不跑 doctor 全量巡检", src)     # 推导进 docstring


# ---------------------------------------------------------------------------
# 1f. 整体聚合 + 班次日志（跨解析器承重契约）
# ---------------------------------------------------------------------------
class TestRunDigest(unittest.TestCase):
    def _deps(self, td):
        snap_dir = Path(td) / "snaps"
        shift_log = Path(td) / "shift_log.md"
        hw.save_snapshot(str(snap_dir), _snap_rows(),
                         ["bilibili", "weibo"], 20, now=NOW)
        shift_log.write_text(
            "[2026-09-17 09:45] hotlist_watch: diff（bilibili+weibo）"
            "新增 1 消失 1 保留 38\n", encoding="utf-8")
        return (dict(
            hn_fetcher=lambda q, num: [_hn_row(f"t-{q}")],
            releases_fetcher=lambda repo, num: [_rel_row()],
            shift_log=str(shift_log), snapshots_dir=str(snap_dir), now=NOW))

    def test_overall_ok_markdown_four_sections(self):
        with tempfile.TemporaryDirectory() as td:
            r = dg.run_digest(**self._deps(td))
        self.assertEqual(r["overall"], "ok")
        self.assertEqual(r["sections"],
                         {"hotlist": "ok", "hn": "ok",
                          "releases": "ok", "toolbox": "ok"})
        md = r["markdown"]
        for head in ("# 晨报 2026-09-17 10:00",
                     "## 热榜动态", "## 技术社区信号",
                     "## 关注项目发布", "## 工具箱状态"):
            self.assertIn(head, md)
        self.assertIn("digest v3.33.0", md)

    def test_single_section_fault_renders_warn_not_crash(self):
        def bad_rel(repo, num):
            return [{"error": "HTTPError: 403", "tool": "github"}]
        with tempfile.TemporaryDirectory() as td:
            kw = self._deps(td)
            kw["releases_fetcher"] = bad_rel
            r = dg.run_digest(**kw)
        self.assertEqual(r["overall"], "ok")            # 单段挂不炸整体
        self.assertEqual(r["sections"]["releases"], "fault")
        self.assertIn("⚠️ 通道异常: HTTPError: 403", r["markdown"])

    def test_network_sections_fault_but_toolbox_keeps_overall_ok(self):
        # 单段/多段 fault 是观测内容；只有四段全 fault 才 overall fault。
        # 本例：三网段全 fault + toolbox 本地状态 ok = 晨报仍有效。
        def boom(*a, **k):
            raise RuntimeError("all down")
        r = dg.run_digest(
            config_loader=lambda p: json.dumps(
                {"watch_repos": ["a/b"], "watch_queries": ["q"]}),
            hn_fetcher=boom, releases_fetcher=boom,
            hotlist_sampler=boom, sample_hotlist=True,
            shift_log=str(Path(tempfile.gettempdir()) / "no_such_dg.log"),
            snapshots_dir="no_such_dir_dg", now=NOW)
        self.assertEqual(r["sections"]["toolbox"], "ok")
        self.assertEqual(r["overall"], "ok")

    def test_all_four_fault_overall_fault(self):
        def boom(*a, **k):
            raise RuntimeError("all down")
        with mock.patch.object(doctor, "_shift_log_stats",
                               side_effect=RuntimeError("local too")):
            r = dg.run_digest(
                config_loader=lambda p: json.dumps(
                    {"watch_repos": ["a/b"], "watch_queries": ["q"]}),
                hn_fetcher=boom, releases_fetcher=boom,
                hotlist_sampler=boom, sample_hotlist=True,
                shift_log="no_such_dg.log", snapshots_dir="no_such_dir_dg",
                now=NOW)
        self.assertEqual(r["sections"]["toolbox"], "fault")
        self.assertEqual(r["overall"], "fault")          # cron 侧可报警

    def test_log_line_parseable_by_doctor_shift_stats(self):
        # 承重契约（v3.31 hotlist_watch 同款）：digest 班次行必须能被
        # doctor._shift_log_stats 解析进值班趋势（fixture 基线行 1 条 +
        # digest 行 1 条 = 窗口内 2 条；last = digest 行）
        with tempfile.TemporaryDirectory() as td:
            sl = Path(td) / "shift_log.md"
            r = dg.run_digest(**self._deps(td))
            with open(sl, "a", encoding="utf-8") as f:
                f.write(dg.render_log_line(NOW, r["sections"]) + "\n")
            stats = doctor._shift_log_stats(str(sl), NOW)
        self.assertEqual(stats["count"], 2)
        self.assertIn("digest:", stats["last"][1])

    def test_render_hotlist_empty_honest(self):
        md = dg.render({"status": "empty", "error": "监控环未启用（无快照）",
                        "top": [], "watch_lines": []},
                       {"status": "ok", "queries": []},
                       {"status": "ok", "repos": []},
                       {"status": "ok", "shift_stats": None,
                        "cookie_age_h": None, "weibo_reading": None,
                        "snapshots_n": 0, "snapshots_latest": None},
                       "", now=NOW)
        self.assertIn("（未启用）监控环未启用", md)
        self.assertIn("➖", md)                          # empty ≠ fault


# ---------------------------------------------------------------------------
# 1g. CLI（runpy + mock；pythonw null-stdout 安全）
# ---------------------------------------------------------------------------
class TestCli(unittest.TestCase):
    def _fake_result(self, overall="ok"):
        return {"markdown": "# 晨报\n", "overall": overall,
                "sections": {"hotlist": "ok", "hn": "ok",
                             "releases": "ok", "toolbox": "ok"},
                "ts": "2026-09-17 10:00:00"}

    def test_exit0_ok(self):
        with mock.patch.object(dg, "run_digest",
                               return_value=self._fake_result()):
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(dg._main([]), 0)
        self.assertIn("# 晨报", out.getvalue())

    def test_exit1_all_fault(self):
        with mock.patch.object(dg, "run_digest",
                               return_value=self._fake_result("fault")):
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                self.assertEqual(dg._main([]), 1)
        self.assertIn("零有效内容", err.getvalue())

    def test_log_write_failure_swallowed(self):
        # --log 写失败只 warn：日志是观测副本，不炸已完成的晨报轮
        with mock.patch.object(dg, "run_digest",
                               return_value=self._fake_result()), \
             mock.patch.object(dg, "open", side_effect=OSError("disk full")):
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                self.assertEqual(dg._main(["--log", "Z:/no/x.md"]), 0)
        self.assertIn("log 写失败", err.getvalue())

    def test_pythonw_null_stdout_safety(self):
        # pythonw 计划任务无控制台 sys.stdout=None——打印直接跳过，
        # 不许 AttributeError 把已完成的聚合轮打成丑死（v3.31 同款钉）
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = None
        try:
            with mock.patch.object(dg, "run_digest",
                                   return_value=self._fake_result()):
                self.assertEqual(dg._main([]), 0)
        finally:
            sys.stdout, sys.stderr = old_out, old_err

    def test_help_mentions_boundaries(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            with self.assertRaises(SystemExit):
                dg._main(["--help"])
        self.assertIn("组合层", out.getvalue())          # argparse help 走 stdout


# ---------------------------------------------------------------------------
# 2. digest_task 注册器（hotlist_watch_task v3.31 同款）
# ---------------------------------------------------------------------------
class TestRegistrar(unittest.TestCase):
    def _ok_proc(self):
        p = mock.Mock()
        p.returncode = 0
        p.stdout, p.stderr = "SUCCESS", ""
        return p

    def test_register_argv_shape(self):
        procs = []

        def runner(argv, **kw):
            procs.append(argv)
            return self._ok_proc()
        self.assertEqual(task.register(runner=runner), 0)
        argv = procs[0]
        self.assertEqual(argv[0], "schtasks")
        self.assertEqual(argv[argv.index("/TN") + 1], task.TASK_NAME)
        self.assertEqual(argv[argv.index("/SC") + 1], "DAILY")
        self.assertEqual(argv[argv.index("/ST") + 1], task.DEFAULT_AT)
        tr = argv[argv.index("/TR") + 1]
        self.assertTrue(tr.startswith('"'))               # 嵌入引号
        self.assertIn('digest.py" --log "', tr)
        self.assertIn(str(task.SHIFT_LOG), tr)

    def test_register_custom_at(self):
        procs = []

        def runner(argv, **kw):
            procs.append(argv)
            return self._ok_proc()
        task.register(at="10:30", runner=runner)
        self.assertEqual(procs[0][procs[0].index("/ST") + 1], "10:30")

    def test_register_failure_exit1(self):
        def runner(argv, **kw):
            p = mock.Mock()
            p.returncode = 1
            p.stdout, p.stderr = "", "ERROR: access denied"
            return p
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(task.register(runner=runner), 1)
        self.assertIn("register FAILED", err.getvalue())

    def test_tr_too_long_no_registration(self):
        procs = []

        def runner(argv, **kw):
            procs.append(argv)
            return self._ok_proc()
        with mock.patch.object(task, "TR_MAX", 10):
            err = io.StringIO()
            with redirect_stderr(err):
                self.assertEqual(task.register(runner=runner), 1)
        self.assertEqual(procs, [])                       # 超长不注册
        self.assertIn("/TR too long", err.getvalue())

    def test_non_win32_honest_error(self):
        with mock.patch.object(task.sys, "platform", "linux"):
            err = io.StringIO()
            with redirect_stderr(err):
                self.assertEqual(task.register(runner=lambda a, **k: None), 1)
        self.assertIn("Windows-only", err.getvalue())
        self.assertIn("cron", err.getvalue())             # 等价入口指路

    def test_status_contract(self):
        ok = mock.Mock(returncode=0, stdout="info", stderr="")
        bad = mock.Mock(returncode=1, stdout="ERROR", stderr="")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(task.status(runner=lambda a, **k: ok), 0)
            self.assertEqual(task.status(runner=lambda a, **k: bad), 1)
        self.assertIn("installed", out.getvalue())
        self.assertIn("NOT INSTALLED", out.getvalue())

    def test_unregister_idempotent_and_failure(self):
        def gone(argv, **kw):
            p = mock.Mock()
            p.returncode = 1
            p.stdout, p.stderr = "", "错误: 系统找不到指定的文件"
            return p
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(task.unregister(runner=gone), 0)
        self.assertIn("already gone", out.getvalue())
        p = mock.Mock()
        p.returncode = 1
        p.stdout, p.stderr = "", "ERROR: another failure"
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(task.unregister(runner=lambda a, **k: p), 1)
        self.assertIn("unregister FAILED", err.getvalue())

    def test_decode_gbk_fallback(self):
        raw = "成功".encode("gbk")
        self.assertEqual(task._decode(raw), "成功")
        self.assertEqual(task._decode(b"\xff\xfe"), "\ufffd\ufffd")
        self.assertEqual(task._decode(None), "")
        self.assertEqual(task._decode("already str"), "already str")

    def test_staggering_derivation_in_doc(self):
        # 错峰推导进文档（十杀第 7 条：引用必须变成可检查的在场事实）：
        # 10:00 排在 sogou-probe 09:30 / hotlist-watch 09:45 之后消费当日 diff
        doc = task.__doc__ or ""
        self.assertIn("10:00", doc)
        self.assertIn("09:45", doc)
        self.assertIn("09:30", doc)
        self.assertIn("当日", doc)


# ---------------------------------------------------------------------------
# 3. 版本锁 3.33.0 + 文档（自 test_v3310 接管精确锁）
# ---------------------------------------------------------------------------
class TestVersionSyncV333(unittest.TestCase):
    def test_versions_3330(self):
        # v3.33 起精确锁自 test_v3310 接管：双 __version__ 同步钉死
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        m = re.search(r'__version__ = "([^"]+)"', init_src)
        self.assertEqual(m.group(1), "3.33.0")
        self.assertIn("chat-scraper v3.33.0", init_src)
        try:
            import mcp_server              # noqa: F401
            self.assertEqual(mcp_server.__version__, "3.33.0")
        except ImportError:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            self.assertIn('__version__ = "3.33.0"', src)

    def test_changelog_and_readme_3330(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.33.0] - 2026-09-17", changelog)
        self.assertIn("digest.py", changelog)
        self.assertIn("digest_task", changelog)
        self.assertIn("ai-search-digest", changelog)
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("release-v3.33.0", readme)
        self.assertIn("v3.33.0（2026-09-17）", readme)
        # 测试徽章数随本批钉死（下一批交接时降常青）：
        # 552（v3.31 基线）+ 本批钉数
        m = re.search(r"tests-(\d+)%20passing", readme)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), 552 + self._batch_pins())

    @staticmethod
    def _batch_pins():
        src = (REPO / "tests" / "test_v3330.py").read_text(encoding="utf-8")
        # 数真实 test 方法定义形态；本函数注释与正则字面量一律不得写成
        # 可被下方正则命中的形态（自引用虚增——v3.33 首跑抓到过：注释
        # 里的示例方法名被当真实方法计数，badge 虚高 1）
        return len(re.findall(r"def (test_\w+)\(", src))

    def test_honest_doc_evidence_chain(self):
        # 诚实文档（架构原则 8）：组合层归属推导/退出码契约/预算承重值
        doc_d = dg.__doc__ or ""
        self.assertIn("组合层", doc_d)
        self.assertIn("mcp_server 新工具", doc_d)      # 二选一推导在场
        self.assertIn("消费者", doc_d)                  # 班次是消费者
        self.assertIn("0 = 晨报已产出", doc_d)          # 退出码契约
        self.assertIn("全部段", doc_d)                  # exit 1 语义
        self.assertIn("不落快照", doc_d)                # 不做第二个监控环
        self.assertIn("不跑 doctor 全量巡检", doc_d)    # 预算推导
        # 网络预算承重值：默认 2 查询 + 2 仓库 = 4 发（<=8 预算的核算基础）
        self.assertEqual(len(dg.DEFAULT_REPOS), 2)
        self.assertEqual(len(dg.DEFAULT_QUERIES), 2)
        self.assertEqual(dg.TOP_N, 3)
        doc_t = task.__doc__ or ""
        self.assertIn("261", doc_t)                     # /TR 硬上限
        self.assertIn("pythonw", doc_t)                 # 免闪窗

    def test_not_in_mcp_and_engine_untouched(self):
        # 组合层归属裁决的承重钉：晨报不进 MCP（被动拉取原语烧上下文），
        # mcp_server 与引擎文件零改动
        src = (REPO / "tools" / "mcp_server.py").read_text(encoding="utf-8")
        self.assertNotIn("digest", src.lower())
        engine = (REPO / "tools" / "chat-scraper" /
                  "hotlist_engine.py").read_text(encoding="utf-8")
        self.assertNotIn("digest", engine.lower())


if __name__ == "__main__":
    unittest.main()
