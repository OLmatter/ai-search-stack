"""v3.30.0 回归：热榜监控闭环 + 微博 cookie 寿命标定起步。

四块内容（全部离线，零真实榜单/标定请求——真实演练走独立两轮采样落
state/hotlist_drill_20260917/，回归钉全部走 mock / tmp 文件 / 源码钉）：
1. hot_diff 纯函数：new/gone/kept 与分平台 summary/排序与原引用返回/
   error 记录剔除 + 单侧无有效榜单平台整侧剔除（宁缺勿错）/身份键 url
   回退 title + hot_value 变化不算新增/空与 None 输入/输入零 mutation。
2. weibo_probe_once：valid 落账/incarnate 禁令（被调即断言失败）/
   WeiboHotlistAuthRejected -> expired/信封 ok!=1 -> expired/missing
   零网络/non-JSON -> error/log_path=None 只测不落账/坏 saved_at 龄
   None 不炸。
3. doctor：check_hotlist 四态语义（valid 带龄/expired ⚠️ 非通道故障/
   missing 不报警/error ⚠️）+ 读数落账路径显式传参/cmd_hotlist_probe
   退出码契约/--hotlist-probe CLI 派发/标定钩子活性覆盖 weibo 流
   （缺文件不报警、有读数后 >48h 报警，sogou 同款）。
4. MCP doctor mode=hotlist 派发 + 非法 mode 错误协议 + 版本锁（v3.31
   起精确锁降常青移交 test_v3310，双 __version__ 同步钉保留）+ CHANGELOG
   + README 徽章 + 诚实文档证据链钉（docstring 演练日期/标定纪律）。
"""
import io
import json
import pathlib
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "chat-scraper"))
sys.path.insert(0, str(REPO / "tools"))

import hotlist_engine as hl    # noqa: E402
import doctor                  # noqa: E402

try:
    import mcp_server              # noqa: E402
except ImportError:                # mcp SDK 未安装（部分 CI）——降级源码断言
    mcp_server = None


def _row(platform, title, rank, url=None, **extra):
    r = {"rank": rank, "title": title, "platform": platform,
         "url": url or f"u-{platform}-{title}"}
    r.update(extra)
    return r


# ---------------------------------------------------------------------------
# 1. hot_diff 纯函数（零网络）
# ---------------------------------------------------------------------------
class TestHotDiff(unittest.TestCase):
    def test_new_gone_kept_summary_and_order(self):
        before = [_row("bilibili", "A", 1), _row("bilibili", "B", 2),
                  _row("weibo", "W1", 1, hot_value=100)]
        after = [_row("bilibili", "B", 1), _row("bilibili", "C", 2),
                 _row("weibo", "W1", 1, hot_value=222),
                 _row("weibo", "W2", 2, hot_value=90)]
        d = hl.hot_diff(before, after)
        # new 按 (platform, rank) 升序：bilibili 在前
        self.assertEqual([(r["platform"], r["title"]) for r in d["new"]],
                         [("bilibili", "C"), ("weibo", "W2")])
        self.assertEqual([(r["platform"], r["title"]) for r in d["gone"]],
                         [("bilibili", "A")])
        self.assertEqual(d["kept"], 2)   # B + W1
        self.assertEqual(d["platforms"], {
            "bilibili": {"new": 1, "gone": 1, "kept": 1},
            "weibo": {"new": 1, "gone": 0, "kept": 1}})
        self.assertEqual(d["skipped_platforms"], {})

    def test_error_rows_excluded_one_sided_skipped(self):
        # 前轮 weibo 报错、后轮有效 -> 整侧剔除，不产全榜"新增"假信号
        before = [{"error": "weibo_hotlist_error: 403",
                   "platform": "weibo"}]
        after = [_row("weibo", "W1", 1), _row("weibo", "W2", 2)]
        d = hl.hot_diff(before, after)
        self.assertEqual(d["new"], [])
        self.assertEqual(d["platforms"], {})
        self.assertIn("前轮该平台报错", d["skipped_platforms"]["weibo"])
        self.assertIn("整侧剔除不产信号", d["skipped_platforms"]["weibo"])
        # 反向：前轮有效、后轮报错
        d2 = hl.hot_diff(after, before)
        self.assertEqual(d2["gone"], [])
        self.assertIn("后轮该平台报错", d2["skipped_platforms"]["weibo"])
        # 单侧未采样（无 error 也无 rows）
        d3 = hl.hot_diff([_row("bilibili", "A", 1)], [])
        self.assertIn("后轮未采样", d3["skipped_platforms"]["bilibili"])

    def test_zhihu_error_both_sides_never_enters_output(self):
        err = {"error": "zhihu_hotlist_needs_login: x", "platform": "zhihu"}
        d = hl.hot_diff([err], [dict(err)])
        self.assertEqual(d["new"], [])
        self.assertEqual(d["gone"], [])
        self.assertEqual(d["platforms"], {})
        self.assertEqual(d["skipped_platforms"], {})   # 双侧都无有效榜单

    def test_identity_url_stable_hot_value_change_not_new(self):
        before = [_row("weibo", "W1", 1, hot_value=100)]
        after = [_row("weibo", "W1", 3, hot_value=999)]   # rank/热度全变
        d = hl.hot_diff(before, after)
        self.assertEqual(d["new"], [])
        self.assertEqual(d["gone"], [])
        self.assertEqual(d["kept"], 1)
        # url 缺失回退 title 作身份
        d2 = hl.hot_diff([{"rank": 1, "title": "T", "platform": "weibo"}],
                         [{"rank": 2, "title": "T", "platform": "weibo"}])
        self.assertEqual(d2["kept"], 1)

    def test_empty_and_none_inputs(self):
        empty = {"new": [], "gone": [], "kept": 0, "platforms": {},
                 "skipped_platforms": {}}
        self.assertEqual(hl.hot_diff([], []), empty)
        self.assertEqual(hl.hot_diff(None, None), empty)
        self.assertEqual(hl.hot_diff([_row("weibo", "W", 1)], None),
                         hl.hot_diff([_row("weibo", "W", 1)], []))

    def test_inputs_not_mutated(self):
        before = [_row("bilibili", "A", 1)]
        after = [_row("bilibili", "B", 1), _row("weibo", "W", 1)]
        snap_b, snap_a = json.dumps(before), json.dumps(after)
        hl.hot_diff(before, after)
        self.assertEqual(json.dumps(before), snap_b)
        self.assertEqual(json.dumps(after), snap_a)


# ---------------------------------------------------------------------------
# 2. weibo_probe_once（禁 incarnate 纪律 + 四态读数 + jsonl 落账）
# ---------------------------------------------------------------------------
class TestWeiboProbeOnce(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="v3300-")
        self.state_path = pathlib.Path(self.tmp) / "weibo_visitor_cookies.json"
        self.log_path = pathlib.Path(self.tmp) / "weibo_cookie_lifetime_log.jsonl"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _write_state(self, saved_at="2026-09-17 03:30:49",
                     cookies=None):
        payload = {"cookies": cookies if cookies is not None
                   else {"SUB": "s1", "SUBP": "p1"},
                   "user_agent": "UA", "saved_at": saved_at}
        self.state_path.write_text(json.dumps(payload), encoding="utf-8")

    def _run(self, log=True, **kw):
        with mock.patch.object(hl, "_WEIBO_STATE_PATH", str(self.state_path)), \
                mock.patch.object(hl, "_incarnate_weibo_visitor") as minc:
            entry = hl.weibo_probe_once(
                log_path=str(self.log_path) if log else None,
                tool="test", **kw)
        return entry, minc

    def test_valid_appends_log_and_never_incarnates(self):
        self._write_state()
        env = {"ok": 1, "data": {"realtime": [
            {"word": "话题A", "num": 1, "is_ad": 0},
            {"word": "广告", "num": 1, "is_ad": 1},
            {"word": "话题B", "num": 2, "is_ad": 0}]}}
        with mock.patch.object(hl, "_call_hotsearch",
                               return_value=env) as mcall:
            entry, minc = self._run()
        self.assertEqual(minc.call_count, 0)      # 禁 incarnate：被调即败
        self.assertEqual(mcall.call_args[0][0],
                         {"SUB": "s1", "SUBP": "p1"})   # 只动缓存 cookie
        self.assertEqual(entry["status"], "valid")
        self.assertEqual(entry["note"], "top1=话题A rows=2")  # 广告位剔除
        self.assertEqual(entry["tool"], "test")
        self.assertIsNotNone(entry["cookie_age_h"])
        lines = self.log_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)           # 一行一条 jsonl
        self.assertEqual(json.loads(lines[0])["status"], "valid")

    def test_auth_rejected_read_expired(self):
        self._write_state()
        with mock.patch.object(hl, "_call_hotsearch",
                               side_effect=hl.WeiboHotlistAuthRejected(
                                   "hotSearch HTTP 403（访客身份被拒）")):
            entry, _ = self._run()
        self.assertEqual(entry["status"], "expired")
        self.assertIn("HTTP 403", entry["note"])

    def test_envelope_ok_not_1_read_expired(self):
        self._write_state()
        with mock.patch.object(hl, "_call_hotsearch",
                               return_value={"ok": -100}):
            entry, _ = self._run()
        self.assertEqual(entry["status"], "expired")
        self.assertIn("禁 incarnate", entry["note"])

    def test_missing_zero_network(self):
        # 无 state 文件：missing 且零网络（_call_hotsearch 被调即断言失败）
        guard = mock.MagicMock(
            side_effect=AssertionError("missing 态不准发网络请求"))
        with mock.patch.object(hl, "_call_hotsearch", guard):
            entry, minc = self._run()
        self.assertEqual(entry["status"], "missing")
        self.assertIn("missing != 过期", entry["note"])
        self.assertEqual(guard.call_count, 0)
        self.assertEqual(minc.call_count, 0)
        self.assertEqual(self.log_path.exists(), True)   # missing 也落账

    def test_non_json_read_error_not_expired(self):
        self._write_state()
        with mock.patch.object(hl, "_call_hotsearch",
                               side_effect=hl.WeiboHotlistError(
                                   "hotSearch non-JSON HTTP 200")):
            entry, _ = self._run()
        self.assertEqual(entry["status"], "error")   # 页面形态异常 != 死亡
        with mock.patch.object(hl, "_call_hotsearch",
                               side_effect=__import__("requests")
                               .ConnectionError("reset")):
            entry2, _ = self._run(log=False)
        self.assertEqual(entry2["status"], "error")

    def test_log_path_none_no_write(self):
        self._write_state()
        with mock.patch.object(hl, "_call_hotsearch",
                               return_value={"ok": 1, "data":
                                             {"realtime": []}}):
            entry, _ = self._run(log=False)
        self.assertEqual(entry["status"], "valid")
        self.assertEqual(self.log_path.exists(), False)

    def test_bad_saved_at_age_none_still_works(self):
        self._write_state(saved_at="不是时间")
        with mock.patch.object(hl, "_call_hotsearch",
                               return_value={"ok": 1, "data":
                                             {"realtime": []}}):
            entry, _ = self._run(log=False)
        self.assertEqual(entry["status"], "valid")
        self.assertIsNone(entry["cookie_age_h"])  # 坏 saved_at 不炸判


# ---------------------------------------------------------------------------
# 3. doctor：热榜探活项 + CLI + 钩子活性 weibo 流
# ---------------------------------------------------------------------------
class TestDoctorHotlist(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="v3300doc-")
        self.log_path = pathlib.Path(self.tmp) / "weibo_cookie_lifetime_log.jsonl"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _popular_body(self):
        return json.dumps({"code": 0, "message": "0",
                           "data": {"list": [{"bvid": "BV1"}, {"bvid": "BV2"}],
                                    "no_more": True}})

    def _patch_probe(self, entry):
        return mock.patch.object(hl, "weibo_probe_once",
                                 return_value=entry)

    def test_check_hotlist_valid(self):
        entry = {"status": "valid", "cookie_age_h": 0.5,
                 "note": "top1=话题A rows=20", "saved_at": "2026-09-17 03:30:49"}
        with mock.patch.object(doctor, "_get",
                               return_value=self._popular_body()) as mget, \
                self._patch_probe(entry) as mprobe:
            detail = doctor.check_hotlist()
        self.assertIn("bilibili popular 2 条", detail)
        self.assertIn("weibo cookie 龄 0.5h 有效", detail)
        self.assertIn("needs_login", detail)      # zhihu 线静态说明在场
        self.assertIn("popular", mget.call_args[0][0])
        # 落账路径显式传参（默认参数 def 时绑定，patch 全局需生效）
        self.assertEqual(mprobe.call_args.kwargs["log_path"],
                         doctor.WEIBO_LIFETIME_LOG_PATH)
        self.assertIn("doctor", mprobe.call_args.kwargs["tool"])

    def test_check_hotlist_expired_optional_not_channel_fault(self):
        entry = {"status": "expired", "cookie_age_h": 47.4,
                 "note": "hotSearch HTTP 403", "saved_at": None}
        with mock.patch.object(doctor, "_get",
                               return_value=self._popular_body()), \
                self._patch_probe(entry):
            with self.assertRaises(RuntimeError) as cm:
                doctor.check_hotlist()
        self.assertIn("非通道故障", str(cm.exception))
        self.assertIn("47.4", str(cm.exception))  # 死亡龄读数可见

    def test_check_hotlist_missing_not_alarm(self):
        entry = {"status": "missing", "cookie_age_h": None,
                 "note": "无缓存访客 cookie", "saved_at": None}
        with mock.patch.object(doctor, "_get",
                               return_value=self._popular_body()), \
                self._patch_probe(entry):
            detail = doctor.check_hotlist()       # 不 raise = 不报警
        self.assertIn("missing", detail)

    def test_check_hotlist_error_raises(self):
        entry = {"status": "error", "cookie_age_h": None,
                 "note": "ConnectionError: reset", "saved_at": None}
        with mock.patch.object(doctor, "_get",
                               return_value=self._popular_body()), \
                self._patch_probe(entry):
            self.assertRaises(RuntimeError, doctor.check_hotlist)

    def test_check_hotlist_bilibili_dead_raises(self):
        with mock.patch.object(doctor, "_get",
                               return_value=json.dumps(
                                   {"code": -412, "message": "拦截"})):
            self.assertRaises(RuntimeError, doctor.check_hotlist)

    def test_cmd_hotlist_probe_exit_codes(self):
        entry = {"status": "valid", "cookie_age_h": 1.2,
                 "note": "top1=x rows=20", "saved_at": "2026-09-17 03:30:49"}
        with mock.patch.object(hl, "weibo_probe_once",
                               return_value=entry) as mprobe, \
                redirect_stdout(io.StringIO()) as buf:
            self.assertEqual(doctor.cmd_hotlist_probe(), 0)
        self.assertEqual(mprobe.call_args.kwargs["log_path"],
                         doctor.WEIBO_LIFETIME_LOG_PATH)   # 显式传全局
        self.assertIn("status=valid", buf.getvalue())
        self.assertIn("age=1.2h", buf.getvalue())
        with mock.patch.object(hl, "weibo_probe_once",
                               side_effect=OSError("log 写不进")), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(doctor.cmd_hotlist_probe(), 1)  # 本地故障

    def test_cli_flag_dispatch(self):
        with mock.patch.object(sys, "argv",
                               ["doctor.py", "--hotlist-probe"]), \
                mock.patch.object(doctor, "cmd_hotlist_probe",
                                  return_value=0) as mcmd:
            self.assertEqual(doctor.main(), 0)
        mcmd.assert_called_once_with()

    def _write_jsonl(self, path, ts, status="valid"):
        pathlib.Path(path).write_text(
            json.dumps({"ts": ts, "status": status}, ensure_ascii=False)
            + "\n", encoding="utf-8")

    def test_hook_liveness_weibo_stream(self):
        fresh = (datetime.now() - timedelta(hours=1)).astimezone()
        stale = (datetime.now() - timedelta(hours=72)).astimezone()
        # cookie+sogou 日志垫新鲜读数（隔离真实 state，weibo 分支才可单测）
        cookie_log = pathlib.Path(self.tmp) / "cookie_lifetime_log.jsonl"
        sogou_log = pathlib.Path(self.tmp) / "sogou_recovery_log.jsonl"
        weibo_log = pathlib.Path(self.tmp) / "weibo_cookie_lifetime_log.jsonl"
        self._write_jsonl(cookie_log, fresh.isoformat(timespec="seconds"))
        self._write_jsonl(sogou_log, fresh.isoformat(timespec="seconds"))
        with mock.patch.object(doctor, "COOKIE_LOG_PATH", str(cookie_log)), \
                mock.patch.object(doctor, "SOGOU_RECOVERY_LOG_PATH",
                                  str(sogou_log)), \
                mock.patch.object(doctor, "WEIBO_LIFETIME_LOG_PATH",
                                  str(weibo_log)):
            # 缺文件：可选观测未启用，不报警
            detail = doctor.check_hook_liveness()
            self.assertIn("weibo 标定无读数", detail)
            # 有新鲜读数：正常显示
            self._write_jsonl(weibo_log,
                              fresh.isoformat(timespec="seconds"))
            detail = doctor.check_hook_liveness()
            self.assertIn("weibo 最后读数", detail)
            # 最后读数 >48h：钩子疑似断线报警
            self._write_jsonl(weibo_log,
                              stale.isoformat(timespec="seconds"))
            with self.assertRaises(RuntimeError) as cm:
                doctor.check_hook_liveness()
        self.assertIn("热榜探活钩子疑似断线", str(cm.exception))


# ---------------------------------------------------------------------------
# 4. MCP doctor mode=hotlist + 版本锁 3.30.0 + 文档
# ---------------------------------------------------------------------------
class TestMcpDoctorHotlist(unittest.TestCase):
    def test_mode_hotlist_dispatch(self):
        if mcp_server is not None:
            with mock.patch.object(mcp_server._doctor, "cmd_hotlist_probe",
                                   return_value=0) as mcmd:
                out = mcp_server.doctor(mode="hotlist")
            mcmd.assert_called_once_with()
            self.assertIn("退出码: 0", out)
            self.assertIn("成功观测", out)
        else:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            self.assertIn("cmd_hotlist_probe", src)

    def test_invalid_mode_error_mentions_hotlist(self):
        if mcp_server is not None:
            out = mcp_server.doctor(mode="nope")
            self.assertIn("full|cookie|sogou|hotlist", out)
        else:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            self.assertIn("full|cookie|sogou|hotlist", src)


class TestVersionSyncV330(unittest.TestCase):
    def test_versions_3300(self):
        # v3.31 起精确锁移交 test_v3310，此处降常青下限（v3.27→v3.28→
        # v3.29→v3.30 先例）：双 __version__ 同步本身不许破
        if mcp_server is None:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            ver = re.search(r'__version__ = "([^"]+)"', src).group(1)
        else:
            ver = mcp_server.__version__
        self.assertGreaterEqual(
            [int(x) for x in ver.split(".")], [3, 30, 0])
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        self.assertIn(f'__version__ = "{ver}"', init_src)
        self.assertIn(f"chat-scraper v{ver}", init_src)

    def test_changelog_and_readme_3300(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.30.0] - 2026-09-17", changelog)
        self.assertIn("hot_diff", changelog)
        self.assertIn("weibo_probe_once", changelog)
        self.assertIn("weibo_cookie_lifetime_log", changelog)
        # v3.31 起精确徽章/状态行锁移交 test_v3310，此处降常青：
        # 徽章/状态行与 __version__ 一致（防止换版时徽章漂移回退）
        if mcp_server is None:
            src2 = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            ver = re.search(r'__version__ = "([^"]+)"', src2).group(1)
        else:
            ver = mcp_server.__version__
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"release-v{ver}", readme)
        self.assertIn(f"v{ver}（", readme)   # 状态行「vX.Y.Z（日期）」头部在场
        # 测试徽章数随本批移交 test_v3310 精确锁，此处降常青单调下限：
        # 517（v3.30 基线 = 491 + 本批 26 钉），回归只许增不许缩
        m = re.search(r"tests-(\d+)%20passing", readme)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(int(m.group(1)), 517)

    def test_honest_doc_evidence_chain(self):
        # 诚实文档（架构原则 8）：演练日期/标定纪律/标定流进 docstring
        doc = hl.__doc__ or ""
        self.assertIn("2026-09-17", doc)
        self.assertIn("hot_diff", doc)
        self.assertIn("禁 incarnate", doc)
        self.assertIn("weibo_cookie_lifetime_log", doc)
        self.assertIn("监控告警", doc)          # toolbox 复用边界声明
        doc_d = doctor.__doc__ or ""
        self.assertIn("热榜通道", doc_d)
        self.assertIn("--hotlist-probe", doc_d)
        self.assertIn("非故障", doc_d)          # zhihu needs_login 非故障
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        self.assertIn("v3.30.0", init_src)
        self.assertIn("hot_diff", init_src)
        # MCP doctor 描述带 hotlist 子模式
        src = (REPO / "tools" / "mcp_server.py").read_text(
            encoding="utf-8")
        self.assertIn("mode 四态", src)
        self.assertIn("hotlist=只跑微博访客 cookie 寿命标定", src)


if __name__ == "__main__":
    unittest.main()
