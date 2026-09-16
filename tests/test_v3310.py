"""v3.31.0 回归：热榜监控环组合脚本 + 每日班次接线 + server /hot 接口奇偶。

四块内容（全部离线，零真实热榜请求——真实链路走 schtasks /Run 实据落
CHANGELOG v3.31.0；回归钉全走 mock / tmp 文件 / runner 注入 / 源码钉）：
1. hotlist_watch（调用方层监控环，引擎零改动——toolbox 复用边界）：
   run_once 建基线/diff/fault 三态、采样异常与零有效行不落快照、快照
   写失败归 fault、告警渲染、班次日志行格式与 doctor _shift_log_stats
   跨解析器兼容钉（每日 diff 进班次日志的承重契约）、快照同秒冲突、
   损坏快照跳读、滚动清理、CLI 单发/自轮询参数。
2. hotlist_watch_task（schtasks 注册器，watchdog_task v3.28 先例）：
   register argv 形态（DAILY/ST/TN/TR 嵌入引号 + --log 班次日志绝对
   路径）/失败退出码/TR 超长不注册/status/unregister 幂等/非 win32
   诚实报错/GBK 解码回退链。
3. server /hot 端点（接口奇偶补齐：facade/CLI/MCP 均有 hot 唯 HTTP
   服务缺）：真实回环 TCP + mock facade.hot，参数透传与 num 非法 400。
4. 版本锁 3.31.0（双 __version__，自 test_v3300 接管精确锁）+ CHANGELOG
   + README 徽章 + 诚实文档钉（接线推导/复用边界/退出码契约）。
"""
import io
import json
import pathlib
import re
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from http.server import HTTPServer
from pathlib import Path
from unittest import mock

import requests

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "chat-scraper"))
sys.path.insert(0, str(REPO / "tools"))

import hotlist_engine as hl         # noqa: E402
import hotlist_watch as hw          # noqa: E402
import hotlist_watch_task as task   # noqa: E402
import doctor                       # noqa: E402
import server as chat_server        # noqa: E402


def _row(platform, title, rank, url=None, **extra):
    r = {"rank": rank, "title": title, "platform": platform,
         "url": url or f"u-{platform}-{title}"}
    r.update(extra)
    return r


def _sampler(rows):
    """把静态 rows 包成 hot(platforms, num, on_error) 形态的假采样器，
    并记录调用参数（透传钉用）。"""
    calls = []

    def fn(platforms, num, on_error):
        calls.append({"platforms": list(platforms), "num": num,
                      "on_error": on_error})
        return [dict(r) for r in rows]
    fn.calls = calls
    return fn


NOW = datetime(2026, 9, 17, 9, 45)


# ---------------------------------------------------------------------------
# 1. hotlist_watch 监控环（调用方层，全离线）
# ---------------------------------------------------------------------------
class TestRunOnceChain(unittest.TestCase):
    def test_baseline_first_round(self):
        s = _sampler([_row("bilibili", "A", 1), _row("weibo", "W1", 1)])
        with tempfile.TemporaryDirectory() as td:
            r = hw.run_once(platforms=["bilibili", "weibo"], num=20,
                            snapshots_dir=td, sampler=s, now=NOW)
            self.assertEqual(r["status"], "baseline")
            self.assertEqual(r["summary"],
                             {"new": 0, "gone": 0, "kept": 2})
            self.assertEqual(r["alerts"], [])
            self.assertIsNone(r["prev_snapshot"])
            snaps = list(Path(td).glob("*.json"))
            self.assertEqual(len(snaps), 1)      # 基线快照落盘
            payload = json.loads(snaps[0].read_text(encoding="utf-8"))
            self.assertEqual(payload["tool"], "hotlist_watch")
            self.assertEqual(payload["platforms"], ["bilibili", "weibo"])
            self.assertEqual(len(payload["rows"]), 2)
            self.assertEqual(r["removed_snapshots"], 0)

    def test_diff_second_round_alerts_and_summary(self):
        s1 = _sampler([_row("bilibili", "A", 1), _row("bilibili", "B", 2),
                       _row("weibo", "W1", 1)])
        s2 = _sampler([_row("bilibili", "B", 1),
                       _row("weibo", "W2", 1), _row("weibo", "W3", 2)])
        with tempfile.TemporaryDirectory() as td:
            hw.run_once(platforms=["bilibili", "weibo"], num=20,
                        snapshots_dir=td, sampler=s1, now=NOW)
            r = hw.run_once(platforms=["bilibili", "weibo"], num=20,
                            snapshots_dir=td, sampler=s2,
                            now=datetime(2026, 9, 17, 9, 55))
            self.assertEqual(r["status"], "diff")
            self.assertEqual(r["summary"]["new"], 2)
            self.assertEqual(r["summary"]["gone"], 2)
            self.assertEqual(r["summary"]["kept"], 1)
            self.assertEqual(r["summary"]["platforms"]["weibo"],
                             {"new": 2, "gone": 1, "kept": 0})
            self.assertIn("[NEW] [weibo#1] W2 (u-weibo-W2)", r["alerts"])
            self.assertIn("[GONE] [bilibili#1] A (u-bilibili-A)", r["alerts"])
            self.assertEqual(len(list(Path(td).glob("*.json"))), 2)

    def test_sampler_passthrough(self):
        s = _sampler([_row("bilibili", "A", 1)])
        with tempfile.TemporaryDirectory() as td:
            hw.run_once(platforms=["bilibili"], num=7, snapshots_dir=td,
                        sampler=s, now=NOW)
            self.assertEqual(s.calls, [{"platforms": ["bilibili"], "num": 7,
                                        "on_error": "report"}])

    def test_sampler_exception_fault_no_snapshot(self):
        def boom(platforms, num, on_error):
            raise OSError("net down")
        with tempfile.TemporaryDirectory() as td:
            r = hw.run_once(platforms=["bilibili"], num=20,
                            snapshots_dir=td, sampler=boom, now=NOW)
            self.assertEqual(r["status"], "fault")
            self.assertIn("OSError", r["error"])
            self.assertEqual(list(Path(td).glob("*.json")), [])  # 不落快照

    def test_all_error_rows_fault_no_snapshot(self):
        # 全平台 error（如只采 zhihu——needs_login）：宁缺勿错不落快照
        s = _sampler([{"error": "zhihu_hotlist_needs_login: 需登录态",
                       "tool": "chat-scraper", "platform": "zhihu"}])
        with tempfile.TemporaryDirectory() as td:
            r = hw.run_once(platforms=["zhihu"], num=20, snapshots_dir=td,
                            sampler=s, now=NOW)
            self.assertEqual(r["status"], "fault")
            self.assertIn("零有效行", r["error"])
            self.assertEqual(list(Path(td).glob("*.json")), [])

    def test_empty_rows_fault(self):
        s = _sampler([])
        with tempfile.TemporaryDirectory() as td:
            r = hw.run_once(platforms=["bilibili"], num=20,
                            snapshots_dir=td, sampler=s, now=NOW)
            self.assertEqual(r["status"], "fault")

    def test_snapshot_write_failure_fault(self):
        # snapshots_dir 指向一个已存在文件 -> mkdir 失败归 fault 不炸
        with tempfile.TemporaryDirectory() as td:
            blocker = Path(td) / "not-a-dir"
            blocker.write_text("x", encoding="utf-8")
            r = hw.run_once(platforms=["bilibili"], num=20,
                            snapshots_dir=str(blocker),
                            sampler=_sampler([_row("bilibili", "A", 1)]),
                            now=NOW)
            self.assertEqual(r["status"], "fault")
            self.assertIn("快照写失败", r["error"])

    def test_partial_error_rows_still_diff_valid_side(self):
        # 半成功（bilibili 有效 + zhihu error 记录）：有效侧照常落盘 diff，
        # error 行随快照如实保存（hot_diff 自会剔除）
        rows1 = [_row("bilibili", "A", 1),
                 {"error": "zhihu_hotlist_needs_login: x",
                  "tool": "chat-scraper", "platform": "zhihu"}]
        rows2 = [_row("bilibili", "A", 1), _row("bilibili", "C", 2),
                 {"error": "zhihu_hotlist_needs_login: x",
                  "tool": "chat-scraper", "platform": "zhihu"}]
        with tempfile.TemporaryDirectory() as td:
            hw.run_once(platforms=["bilibili", "zhihu"], num=20,
                        snapshots_dir=td, sampler=_sampler(rows1), now=NOW)
            r = hw.run_once(platforms=["bilibili", "zhihu"], num=20,
                            snapshots_dir=td, sampler=_sampler(rows2),
                            now=datetime(2026, 9, 17, 9, 55))
            self.assertEqual(r["status"], "diff")
            # zhihu 两轮都只有 error 记录（零有效榜单）：hot_diff 语义下
            # 该平台压根不进 platforms/skipped——恒错平台既不产信号也不报
            # skipped（skipped 只给「单侧有有效榜单」的平台，v3.30 语义）
            self.assertNotIn("zhihu", r["summary"]["platforms"])
            self.assertNotIn("zhihu", r["summary"]["skipped_platforms"])
            self.assertEqual(r["summary"]["platforms"]["bilibili"]["new"], 1)

    def test_log_line_parseable_by_doctor_shift_stats(self):
        # 承重契约：--log 追加的行是 doctor _shift_log_stats 可解析的
        # 班次日志格式（每日 diff 进班次日志）
        s1 = _sampler([_row("bilibili", "A", 1)])
        s2 = _sampler([_row("bilibili", "A", 1), _row("bilibili", "C", 2)])
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "shift_log.md"
            hw.run_once(platforms=["bilibili"], num=20, snapshots_dir=td,
                        sampler=s1, now=NOW, log_path=str(log))
            hw.run_once(platforms=["bilibili"], num=20, snapshots_dir=td,
                        sampler=s2, now=datetime(2026, 9, 17, 9, 55),
                        log_path=str(log))
            lines = log.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            for ln in lines:
                self.assertRegex(
                    ln, r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\] hotlist_watch: ")
            # doctor 解析器交叉验证：两条都进统计，最后一条含 diff 摘要
            stats = doctor._shift_log_stats(log, datetime(2026, 9, 17, 10))
            self.assertEqual(stats["total"], 2)
            self.assertIn("hotlist_watch:", stats["last_any"][1])
            self.assertIn("新增 1", stats["last_any"][1])

    def test_fault_also_logged(self):
        def boom(platforms, num, on_error):
            raise OSError("down")
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "shift_log.md"
            hw.run_once(platforms=["bilibili"], num=20, snapshots_dir=td,
                        sampler=boom, now=NOW, log_path=str(log))
            ln = log.read_text(encoding="utf-8").strip()
            self.assertIn("hotlist_watch: 故障未落快照", ln)
            self.assertIn("down", ln)

    def test_log_write_failure_swallowed(self):
        # 日志是观测副本：写失败只 stderr，绝不反过来打成监控环 fault
        s = _sampler([_row("bilibili", "A", 1)])
        with tempfile.TemporaryDirectory() as td:
            err = io.StringIO()
            with redirect_stderr(err):
                r = hw.run_once(platforms=["bilibili"], num=20,
                                snapshots_dir=td, sampler=s, now=NOW,
                                log_path=str(Path(td)))   # 指向目录必炸
            self.assertEqual(r["status"], "baseline")     # 监控环不受影响
            self.assertIn("log 写失败", err.getvalue())

    def test_log_line_truncated(self):
        long_title = "超" * 900
        s1 = _sampler([_row("bilibili", "A", 1)])
        s2 = _sampler([_row("bilibili", "A", 1), _row("bilibili", long_title, 2)])
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "shift_log.md"
            hw.run_once(platforms=["bilibili"], num=20, snapshots_dir=td,
                        sampler=s1, now=NOW, log_path=str(log))
            hw.run_once(platforms=["bilibili"], num=20, snapshots_dir=td,
                        sampler=s2, now=datetime(2026, 9, 17, 9, 55),
                        log_path=str(log))
            lines = log.read_text(encoding="utf-8").splitlines()
            self.assertLessEqual(len(lines[-1]), 500 + 20)  # 内容上限+时间戳头


class TestSnapshotStore(unittest.TestCase):
    def test_same_second_collision_suffix(self):
        with tempfile.TemporaryDirectory() as td:
            p1 = hw.save_snapshot(td, [], ["bilibili"], 20, now=NOW)
            p2 = hw.save_snapshot(td, [], ["bilibili"], 20, now=NOW)
            self.assertNotEqual(p1, p2)
            self.assertTrue(p2.endswith("_2.json"))
            p3 = hw.save_snapshot(td, [], ["bilibili"], 20, now=NOW)
            self.assertTrue(p3.endswith("_3.json"))

    def test_latest_skips_corrupt_and_foreign_files(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            self.assertIsNone(hw.latest_snapshot(td))     # 目录不存在/空
            (d / "notes.json").write_text("{}", encoding="utf-8")
            self.assertIsNone(hw.latest_snapshot(td))     # 非本脚本命名不算
            good = Path(hw.save_snapshot(td, [_row("bilibili", "A", 1)],
                                         ["bilibili"], 20, now=NOW))
            good.write_text("{broken", encoding="utf-8")  # 弄坏最新一份
            older = Path(hw.save_snapshot(td, [_row("bilibili", "B", 1)],
                                          ["bilibili"], 20,
                                          now=datetime(2026, 9, 16, 8, 0)))
            got = hw.latest_snapshot(td)
            self.assertEqual(got[0], str(older))          # 坏快照跳过读旧的
            self.assertEqual(got[1]["rows"][0]["title"], "B")

    def test_cleanup_keeps_latest_and_spares_foreign(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            for i in range(5):
                hw.save_snapshot(td, [], ["bilibili"], 20,
                                 now=datetime(2026, 9, 17, 9, 0, i))
            foreign = d / "keep_me.json"
            foreign.write_text("{}", encoding="utf-8")
            removed = hw.cleanup_snapshots(td, keep=3)
            self.assertEqual(removed, 2)
            left = sorted(x.name for x in d.iterdir())
            self.assertEqual(len(left), 4)                # 3 快照 + 1 外来文件
            self.assertIn("keep_me.json", left)

    def test_cleanup_guard_clauses(self):
        self.assertEqual(hw.cleanup_snapshots("Z:/no/such/dir", keep=3), 0)
        with tempfile.TemporaryDirectory() as td:
            hw.save_snapshot(td, [], ["bilibili"], 20, now=NOW)
            self.assertEqual(hw.cleanup_snapshots(td, keep=0), 0)  # <1 不清理
            self.assertEqual(len(list(Path(td).glob("*.json"))), 1)


class TestCli(unittest.TestCase):
    def _run_cli(self, argv):
        import runpy
        sys.argv = ["hotlist_watch.py"] + argv
        err = io.StringIO()
        with redirect_stderr(err):
            try:
                runpy.run_path(str(REPO / "tools" / "chat-scraper"
                                   / "hotlist_watch.py"),
                               run_name="__main__")
                code = 0
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 0
        return code, err

    def test_single_shot_exit0_two_rounds_diff(self):
        with tempfile.TemporaryDirectory() as td:
            argv = ["--platforms", "bilibili", "--snapshots-dir", td]
            # 两连发：第二轮命中第一轮快照 -> diff 状态（模拟自轮询两轮，
            # 不真跑 --interval——监控节奏主权在调用方，测试不等钟）
            with mock.patch.object(
                    hl, "hot",
                    side_effect=_sampler([_row("bilibili", "A", 1)])):
                code1, _ = self._run_cli(argv)
                code2, _ = self._run_cli(argv)
            self.assertEqual((code1, code2), (0, 0))
            self.assertEqual(len(list(Path(td).glob("*.json"))), 2)

    def test_interval_guard_rejects_nonpositive(self):
        with tempfile.TemporaryDirectory() as td:
            code, err = self._run_cli(["--interval", "0",
                                       "--snapshots-dir", td])
            self.assertEqual(code, 2)                 # argparse parser.error
            self.assertIn("--interval must be > 0", err.getvalue())

    def test_pythonw_null_stdout_safety(self):
        # schtasks 跑 pythonw（无控制台）时 sys.stdout/sys.stderr 是 None：
        # print 会 AttributeError 把已完成的监控轮（快照/--log 均已落盘）
        # 打成丑死。钉 _emit/_warn 空流安全——工作照常落盘退出码正确
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "shift_log.md"
            with mock.patch.multiple(sys, stdout=None, stderr=None):
                code = hw._cycle(["bilibili"], 20, td, 50, str(log))
            self.assertEqual(code, 0)
            self.assertEqual(len(list(Path(td).glob("*.json"))), 1)
            self.assertTrue(log.exists())

    def test_help_mentions_boundaries(self):
        # 诚实文档：调用方层定位与退出码契约进 --help
        src = (REPO / "tools" / "chat-scraper" / "hotlist_watch.py"
               ).read_text(encoding="utf-8")
        self.assertIn("监控告警", src)          # 复用边界声明
        self.assertIn("不进引擎", src)
        self.assertIn("0 = 有效观测", src)      # 退出码契约
        self.assertIn("1 = 本地故障", src)


# ---------------------------------------------------------------------------
# 2. hotlist_watch_task 注册器（runner 注入，全离线）
# ---------------------------------------------------------------------------
class _FakeProc:
    def __init__(self, returncode=0, out="", err=""):
        self.returncode = returncode
        self.stdout, self.stderr = out, err


def _runner_map(responses):
    """按 argv[1]+argv[2]（如 /Create）返回预制结果的 runner。"""
    def run(argv, capture_output=True, text=True):
        key = argv[1] if len(argv) > 1 else ""
        rc, out, err = responses.get(key, (0, "", ""))
        return _FakeProc(rc, out, err)
    return run


class TestRegistrar(unittest.TestCase):
    def test_register_argv_shape(self):
        seen = {}

        def runner(argv, capture_output=True, text=True):
            seen["argv"] = list(argv)
            return _FakeProc(0, "SUCCESS", "")

        with mock.patch.object(sys, "platform", "win32"):
            code = task.register(at="09:45", runner=runner)
        self.assertEqual(code, 0)
        argv = seen["argv"]
        self.assertEqual(argv[:2], ["schtasks", "/Create"])
        self.assertIn("/F", argv)
        self.assertEqual(argv[argv.index("/TN") + 1], "ai-search-hotlist-watch")
        self.assertEqual(argv[argv.index("/SC") + 1], "DAILY")
        self.assertEqual(argv[argv.index("/ST") + 1], "09:45")
        tr = argv[argv.index("/TR") + 1]
        # 嵌入引号包脚本绝对路径 + --log 班次日志绝对路径（每日 diff 进班次日志）
        self.assertIn(f'"{task.WATCH_PY}"', tr)
        self.assertIn(f'--log "{task.SHIFT_LOG}"', tr)
        self.assertIn("hotlist_watch.py", tr)

    def test_register_failure_exit1(self):
        err = io.StringIO()
        with mock.patch.object(sys, "platform", "win32"), \
                redirect_stderr(err):
            code = task.register(
                runner=_runner_map({"/Create": (1, "", "拒绝访问")}))
        self.assertEqual(code, 1)
        self.assertIn("FAILED", err.getvalue())

    def test_register_tr_too_long_no_registration(self):
        # 261 硬上限：超长宁可报错不注册（静默截断=永远跑不起来的任务）
        with mock.patch.object(sys, "platform", "win32"), \
                mock.patch.object(task, "WATCH_PY",
                                  Path("C:/" + "x" * 300 + ".py")):
            code = task.register(runner=_runner_map({}))
        self.assertEqual(code, 1)

    def test_non_win32_honest_error(self):
        err = io.StringIO()
        with mock.patch.object(sys, "platform", "linux"), \
                redirect_stderr(err):
            self.assertEqual(task.register(runner=_runner_map({})), 1)
            self.assertEqual(task.status(runner=_runner_map({})), 1)
            self.assertEqual(task.unregister(runner=_runner_map({})), 1)
        self.assertIn("Windows-only", err.getvalue())
        self.assertIn("cron", err.getvalue())     # 给出 Linux 等价入口

    def test_status_contract(self):
        with mock.patch.object(sys, "platform", "win32"):
            self.assertEqual(
                task.status(runner=_runner_map({"/Query": (0, "就绪", "")})),
                0)
            self.assertEqual(
                task.status(runner=_runner_map({"/Query": (1, "", "找不到")})),
                1)

    def test_unregister_idempotent_and_failure(self):
        with mock.patch.object(sys, "platform", "win32"):
            # 中文/英文「任务不存在」措辞都认 = 幂等回滚成功
            for wording in ("系统找不到指定的文件。", "ERROR: The specified "
                            "task name \"x\" does not exist in the system.",
                            ""):
                rc = (1, "", wording) if wording else (0, "SUCCESS", "")
                self.assertEqual(
                    task.unregister(runner=_runner_map({"/Delete": rc})),
                    0, wording[:30])
            self.assertEqual(
                task.unregister(runner=_runner_map({"/Delete": (1, "", "在用")})),
                1)

    def test_decode_gbk_fallback(self):
        # 中文 Windows schtasks 输出是 GBK 字节（v3.28 实机抓虫同款）
        self.assertEqual(task._decode("plain"), "plain")
        self.assertEqual(task._decode(b"\xc4\xe3\xba\xc3"), "你好")
        self.assertEqual(task._decode(None), "")
        # 双编码都严格失败 -> replace 兜底不抛（0xFF 非 GBK 合法首字节，
        # 也非合法 utf-8）
        self.assertEqual(task._decode(b"\xff\xfe"), "\ufffd\ufffd")

    def test_registrar_doc_carries_derivation(self):
        # 接线二选一的架构推导必须随代码走（旧版即毒：换人接手看得懂为何
        # 是 schtasks 不是班次提示词）
        doc = task.__doc__ or ""
        self.assertIn("schtasks", doc)
        self.assertIn("CronUpdate", doc)
        self.assertIn("复用边界", doc)
        self.assertIn("shift_log", doc)


# ---------------------------------------------------------------------------
# 3. server /hot 端点（接口奇偶补齐）
# ---------------------------------------------------------------------------
class _Srv:
    def __init__(self):
        self.httpd = HTTPServer(("127.0.0.1", 0), chat_server._Handler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever,
                         daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class TestServerHot(unittest.TestCase):
    def setUp(self):
        self.srv = _Srv()

    def tearDown(self):
        self.srv.close()

    def test_hot_passthrough_and_report_protocol(self):
        rows = [_row("bilibili", "A", 1),
                {"error": "zhihu_hotlist_needs_login: x",
                 "tool": "chat-scraper", "platform": "zhihu"}]
        with mock.patch.object(chat_server._facade, "hot",
                               return_value=rows) as mh:
            resp = requests.get(
                f"http://127.0.0.1:{self.srv.port}/hot",
                params={"platforms": "bilibili,zhihu", "num": "5"},
                timeout=5)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body[0]["title"], "A")
        self.assertIn("error", body[1])           # 错误内嵌不 500（report）
        mh.assert_called_once_with(platforms=["bilibili", "zhihu"], num=5,
                                   vendor="?", role="primary",
                                   on_error="report")

    def test_hot_bad_num_400(self):
        resp = requests.get(f"http://127.0.0.1:{self.srv.port}/hot",
                            params={"num": "abc"}, timeout=5)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("must be an integer", resp.json()["error"])

    def test_404_mentions_hot(self):
        resp = requests.get(f"http://127.0.0.1:{self.srv.port}/nope",
                            timeout=5)
        self.assertEqual(resp.status_code, 404)
        self.assertIn("/hot", resp.json()["error"])

    def test_docstring_and_source_pins(self):
        src = (REPO / "tools" / "chat-scraper" / "server.py").read_text(
            encoding="utf-8")
        self.assertIn("GET /hot?platforms=", src)
        self.assertIn("接口奇偶", src)


# ---------------------------------------------------------------------------
# 4. 版本锁 3.31.0 + 文档（自 test_v3300 接管；v3.33 起降常青）
# ---------------------------------------------------------------------------
class TestVersionSyncV331(unittest.TestCase):
    def test_versions_3310(self):
        # v3.33 起精确锁移交 test_v3330，此处降常青下限（v3.27→v3.28→
        # v3.29→v3.30→v3.31 先例）：双 __version__ 同步本身不许破
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        m = re.search(r'__version__ = "([^"]+)"', init_src)
        self.assertGreaterEqual(
            [int(x) for x in m.group(1).split(".")], [3, 31, 0])
        self.assertIn(f"chat-scraper v{m.group(1)}", init_src)
        try:
            import mcp_server              # noqa: F401
            self.assertEqual(mcp_server.__version__, m.group(1))
        except ImportError:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            self.assertIn(f'__version__ = "{m.group(1)}"', src)

    def test_changelog_and_readme_3310(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.31.0] - 2026-09-17", changelog)
        self.assertIn("hotlist_watch.py", changelog)
        self.assertIn("hotlist_watch_task", changelog)
        self.assertIn("ai-search-hotlist-watch", changelog)
        self.assertIn("接口奇偶", changelog)
        # v3.33 起精确徽章/状态行锁移交 test_v3330，此处降常青：
        # 徽章/状态行与 __version__ 一致（防换版时徽章漂移回退）
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        ver = re.search(r'__version__ = "([^"]+)"', init_src).group(1)
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"release-v{ver}", readme)
        self.assertIn(f"v{ver}（", readme)
        # 测试徽章数 v3.33 起移交 test_v3330 精确锁，此处降常青单调下限：
        # 552（v3.31 基线 = 517 + 本批 35 钉），回归只许增不许缩
        m = re.search(r"tests-(\d+)%20passing", readme)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(int(m.group(1)), 552)

    def test_honest_doc_evidence_chain(self):
        # 诚实文档（架构原则 8）：复用边界/接线推导/退出码契约进 docstring
        doc_w = hw.__doc__ or ""
        self.assertIn("不进引擎", doc_w)
        self.assertIn("hot_diff", doc_w)
        self.assertIn("班次日志", doc_w)
        self.assertIn("0 = 有效观测", doc_w)   # --hotlist-probe 契约同构
        self.assertIn("不落快照", doc_w)        # 宁缺勿错：故障不污染快照链
        doc_t = task.__doc__ or ""
        self.assertIn("09:45", doc_t)
        self.assertIn("ai-search-sogou-probe", doc_t)  # 先例引用
        self.assertIn("261", doc_t)                    # /TR 硬上限
        src = (REPO / "tools" / "chat-scraper" / "server.py").read_text(
            encoding="utf-8")
        self.assertIn("china_hotlist", src)    # 接口奇偶证据链在源码注释


if __name__ == "__main__":
    unittest.main()
