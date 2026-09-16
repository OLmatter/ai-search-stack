"""v3.35.0 回归：toast 通道提取公用模块 + hotlist_watch --toast 即时弹窗。

五块内容（全部离线，零真实网络/零真实弹窗——真实链路走实跑落
CHANGELOG v3.35.0；回归钉全走 mock / runner 注入 / tmp 目录 / 源码钉）：
1. toast.py 公用通道：send_toast（EncodedCommand argv 形态 / POPUP_RET
   解析 / 非 win32 skipped / runner 抛异常与非零退出 fault 不抛 / 保险丝
   20s > 弹窗 12s 承重关系 / _ps_quote 转义与截断 / _decode_out 链）+
   源码钉零网络 import（通道不碰网络）。
2. digest 兼容 re-export：旧引用名（dg.send_toast/dg._decode_out/
   dg.TOAST_* 等）与 toast 模块同源同值；源码钉 digest 不再定义通道
   函数、dead import（base64/os/subprocess）已清、toast_text 未随迁。
3. hotlist_watch --toast：watch_toast_text 文案（新增计数标题 / 前 3 条
   平台#rank 标题 / 消失数 / 240 上限 / 空行不炸）；_maybe_toast 接线
   （diff+新增才弹 / baseline / fault / 零新增不弹 / 通道 fault 只
   warn 不翻码）；_cycle 端到端（注入 sampler + mock 通道）；CLI 旗标
   端到端（mock hl.hot + tmp 快照目录）；toast 模块缺失降级工厂源码钉。
4. hotlist_watch_task register --toast：/TR 追加 --toast（261 上限仍
   执法）；无旗标不含 --toast；**v3.35 实机抓虫双对策钉**——回读验证
   （/Query XML 比对存储与预期，截断/不一致响亮 exit 1，无法回读只
   warn，空白不敏感比对）+ 相对 --log 锚定脚本目录（_main 内）。
5. 版本锁 3.35.0（双 __version__ + digest，自 test_v3340 接管精确锁，
   v3340 同批降常青）+ CHANGELOG + README 徽章 + 诚实文档钉（通道选型
   证据词在 toast.py docstring；监控环弹窗语义/零漂移承诺在
   hotlist_watch.py docstring）。
"""
import base64
import io
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "chat-scraper"))
sys.path.insert(0, str(REPO / "tools"))

import toast as toast_mod           # noqa: E402
import digest as dg                 # noqa: E402
import hotlist_watch as hw          # noqa: E402
import hotlist_watch_task as task   # noqa: E402


class _Proc:
    """subprocess.CompletedProcess 形态的离线替身。"""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _decoded_ps(argv):
    """从注入 runner 捕获的 argv 解出内联 PowerShell 明文。"""
    return base64.b64decode(
        argv[argv.index("-EncodedCommand") + 1]).decode("utf-16-le")


# ---------------------------------------------------------------------------
# 1. toast.py 公用通道
# ---------------------------------------------------------------------------
class TestToastChannel(unittest.TestCase):
    def test_constants_load_bearing(self):
        self.assertEqual(toast_mod.TOAST_TIMEOUT_S, 12)
        self.assertEqual(toast_mod.TOAST_BOX_TYPE, 64 + 4096)
        # 子进程保险丝必须大于弹窗自动超时——否则正常弹窗被误杀
        self.assertGreater(toast_mod.TOAST_SUBPROC_TIMEOUT,
                           toast_mod.TOAST_TIMEOUT_S)
        self.assertEqual(toast_mod.TOAST_BODY_MAX, 240)

    def test_send_toast_argv_shape_and_popup_ret(self):
        seen = []

        def runner(argv):
            seen.append(argv)
            return _Proc(stdout="POPUP_RET=-1\n")

        r = toast_mod.send_toast("标题T", "正文B", runner=runner,
                                 platform="win32")
        self.assertEqual(r["status"], "sent")
        self.assertEqual(r["return"], -1)          # 超时自关的返回值
        argv = seen[0]
        self.assertEqual(argv[0], "powershell")
        self.assertIn("-NoProfile", argv)
        self.assertIn("-NonInteractive", argv)
        self.assertIn("-EncodedCommand", argv)
        ps = _decoded_ps(argv)
        self.assertIn("WScript.Shell", ps)
        self.assertIn(".Popup(", ps)
        self.assertIn(str(toast_mod.TOAST_BOX_TYPE), ps)
        self.assertIn("标题T", ps)
        self.assertIn("正文B", ps)

    def test_send_toast_timeout_passthrough(self):
        seen = []

        def runner(argv):
            seen.append(argv)
            return _Proc(stdout="POPUP_RET=-1")

        toast_mod.send_toast("t", "b", timeout_s=7, runner=runner,
                             platform="win32")
        self.assertIn(", 7,", _decoded_ps(seen[0]))

    def test_non_win32_skipped_runner_never_called(self):
        called = []

        def runner(argv):
            called.append(argv)
            return _Proc()

        r = toast_mod.send_toast("t", "b", runner=runner, platform="linux")
        self.assertEqual(r["status"], "skipped")
        self.assertEqual(called, [])

    def test_runner_raise_fault_not_raise(self):
        def runner(argv):
            raise subprocess.TimeoutExpired(cmd="powershell", timeout=20)

        r = toast_mod.send_toast("t", "b", runner=runner, platform="win32")
        self.assertEqual(r["status"], "fault")
        self.assertIn("TimeoutExpired", r["error"])

    def test_nonzero_exit_fault_with_stderr_head(self):
        r = toast_mod.send_toast(
            "t", "b", platform="win32",
            runner=lambda argv: _Proc(returncode=1, stderr="boom"))
        self.assertEqual(r["status"], "fault")
        self.assertIn("powershell exit 1", r["error"])
        self.assertIn("boom", r["error"])

    def test_ps_quote_escape_fold_and_cap(self):
        self.assertEqual(toast_mod._ps_quote("it's\n标'题"),
                         "it''s 标''题")           # ' -> ''，\n 折叠
        long = "x" * 500
        self.assertEqual(len(toast_mod._ps_quote(long)),
                         toast_mod.TOAST_BODY_MAX)
        self.assertEqual(toast_mod._ps_quote(None), "")

    def test_decode_out_gbk_fallback_chain(self):
        self.assertEqual(
            toast_mod._decode_out("str passthrough"), "str passthrough")
        self.assertEqual(toast_mod._decode_out(b"POPUP_RET=-1"),
                         "POPUP_RET=-1")
        self.assertEqual(toast_mod._decode_out(b"\xc4\xe3\xba\xc3"), "你好")
        self.assertIn("\ufffd", toast_mod._decode_out(b"\xff bad"))
        self.assertEqual(toast_mod._decode_out(None), "")

    def test_channel_source_zero_network_imports(self):
        # 通道不碰网络：源码钉 import 面只许标准库非网络件
        src = (REPO / "tools" / "toast.py").read_text(encoding="utf-8")
        for banned in ("requests", "urllib", "socket", "http.client"):
            self.assertNotIn(banned, src)


# ---------------------------------------------------------------------------
# 2. digest 兼容 re-export（旧引用名零漂移）
# ---------------------------------------------------------------------------
class TestDigestReExport(unittest.TestCase):
    def test_reexport_same_objects(self):
        self.assertIs(dg.send_toast, toast_mod.send_toast)
        self.assertIs(dg._decode_out, toast_mod._decode_out)
        self.assertIs(dg._default_toast_runner,
                      toast_mod._default_toast_runner)
        self.assertIs(dg._ps_quote, toast_mod._ps_quote)
        self.assertEqual(dg.TOAST_TIMEOUT_S, toast_mod.TOAST_TIMEOUT_S)
        self.assertEqual(dg.TOAST_BOX_TYPE, toast_mod.TOAST_BOX_TYPE)
        self.assertEqual(dg.TOAST_SUBPROC_TIMEOUT,
                         toast_mod.TOAST_SUBPROC_TIMEOUT)
        self.assertEqual(dg._TOAST_BODY_MAX, toast_mod.TOAST_BODY_MAX)

    def test_digest_source_channel_extracted(self):
        src = (REPO / "tools" / "digest.py").read_text(encoding="utf-8")
        self.assertNotIn("def send_toast", src)      # 通道函数不再定义
        self.assertNotIn("def _ps_quote", src)
        self.assertIn("from toast import", src)      # 改为 import
        # dead import 清理（base64/os/subprocess 只被通道段使用）
        for gone in ("import base64", "import os\n", "import subprocess"):
            self.assertNotIn(gone, src)

    def test_toast_text_stays_in_digest(self):
        # 弹窗文案是晨报语义（段状态/新增摘要），留在 digest 不随通道迁
        src = (REPO / "tools" / "digest.py").read_text(encoding="utf-8")
        self.assertIn("def toast_text", src)
        title, body = dg.toast_text({
            "overall": "ok", "ts": "2026-09-17 10:00:00",
            "sections": {"hotlist": "ok", "hn": "ok", "releases": "ok",
                         "toolbox": "ok"},
            "new_entries": {"count": 2, "titles": ["甲", "乙"]}})
        self.assertIn("晨报完成", title)
        self.assertIn("热榜新增 2 条", body)
        self.assertIn("甲 / 乙", body)


# ---------------------------------------------------------------------------
# 3. hotlist_watch --toast
# ---------------------------------------------------------------------------
def _row(plat, rank, title, url="http://u"):
    return {"platform": plat, "rank": rank, "title": title, "url": url}


class TestWatchToastText(unittest.TestCase):
    def test_title_count_and_top3_titles(self):
        result = {"ts": "2026-09-17 12:34:56", "status": "diff",
                  "summary": {"new": 4, "gone": 2, "kept": 30},
                  "new": [_row("bilibili", 1, "信号A"),
                          _row("weibo", 2, "信号B"),
                          _row("bilibili", 3, "信号C"),
                          _row("weibo", 4, "信号D")]}
        title, body = hw.watch_toast_text(result)
        self.assertEqual(title, "热榜新增 4 条 12:34:56")
        self.assertIn("[bilibili#1] 信号A", body)
        self.assertIn("[weibo#2] 信号B", body)
        self.assertIn("[bilibili#3] 信号C", body)
        self.assertNotIn("信号D", body)              # 只取前 3 条
        self.assertIn("消失 2", body)

    def test_body_capped_at_toast_body_max(self):
        result = {"ts": "2026-09-17 12:00:00", "status": "diff",
                  "summary": {"new": 1, "gone": 0},
                  "new": [_row("bilibili", 1, "长" * 500)]}
        _, body = hw.watch_toast_text(result)
        self.assertLessEqual(len(body), hw._TOAST_BODY_MAX)

    def test_empty_new_rows_no_crash(self):
        title, body = hw.watch_toast_text(
            {"ts": "2026-09-17 12:00:00", "status": "diff",
             "summary": {"new": 0, "gone": 0}, "new": []})
        self.assertIn("热榜新增 0 条", title)
        self.assertEqual(body, "")


class TestMaybeToastWiring(unittest.TestCase):
    def _diff_result(self, new=1):
        rows = [_row("bilibili", i + 1, f"信号{i}") for i in range(new)]
        return {"tool": "hotlist_watch", "mode": "once", "status": "diff",
                "ts": "2026-09-17 12:00:00", "platforms": ["bilibili"],
                "summary": {"new": new, "gone": 0, "kept": 19},
                "new": rows, "gone": [], "alerts": []}

    def test_diff_with_new_calls_channel_once(self):
        calls = []
        with mock.patch.object(hw, "_toast_send_impl",
                               lambda t, b: calls.append((t, b)) or
                               {"status": "sent", "return": -1}):
            hw._maybe_toast(self._diff_result(2))
        self.assertEqual(len(calls), 1)
        self.assertIn("热榜新增 2 条", calls[0][0])

    def test_baseline_fault_zero_new_never_call(self):
        calls = []
        with mock.patch.object(hw, "_toast_send_impl",
                               lambda t, b: calls.append(1)):
            hw._maybe_toast({"status": "baseline", "ts": "t",
                             "summary": {"new": 0}, "new": []})
            hw._maybe_toast({"status": "fault", "ts": "t",
                             "summary": {"new": 3},
                             "new": [_row("b", 1, "x")]})
            hw._maybe_toast(self._diff_result(0))
        self.assertEqual(calls, [])                  # 无事件信号不弹

    def test_channel_fault_warns_not_raises(self):
        err = io.StringIO()
        with mock.patch.object(hw, "_toast_send_impl",
                               lambda t, b: {"status": "fault",
                                             "error": "powershell exit 1"}):
            with redirect_stderr(err):
                hw._maybe_toast(self._diff_result(1))
        self.assertIn("toast 弹窗失败", err.getvalue())

    def test_send_toast_wrapper_swallows_raise(self):
        def boom(title, body):
            raise RuntimeError("通道炸了")

        with mock.patch.object(hw, "_toast_send_impl", boom):
            r = hw._send_toast("t", "b")
        self.assertEqual(r["status"], "fault")
        self.assertIn("RuntimeError", r["error"])

    def test_channel_import_identity_dual_mode(self):
        # 父目录注入后取到的就是 toast 模块本体（双模式导入零复制）
        self.assertIs(hw._toast_send_impl, toast_mod.send_toast)

    def test_missing_toast_module_fallback_source_pin(self):
        # toast 模块缺失降级为 fault 工厂——弹窗是观测副本，缺了只许
        # 少弹不许多炸（源码钉 ImportError 分支在场）
        src = (REPO / "tools" / "chat-scraper" / "hotlist_watch.py"
               ).read_text(encoding="utf-8")
        self.assertIn("except ImportError", src)
        self.assertIn("toast 模块缺失", src)


class TestCycleToastEndToEnd(unittest.TestCase):
    """端到端：注入 sampler + mock 通道，全离线过 _cycle。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.snap_dir = self.tmp.name

    def _sampler(self, titles):
        def fake(platforms=None, num=20, on_error="report"):
            # hot_diff 身份键=(platform, url)——url 必须绑定条目本身
            #（按 title 生成），按位置编号会在换序时身份错位、diff 失真
            return [_row("bilibili", i + 1, t, url=f"http://u/{t}")
                    for i, t in enumerate(titles)]
        return fake

    def test_diff_new_pops_and_exit0(self):
        # 第一轮建基线（结构化调用，直接进 tmp 目录）
        hw.run_once(platforms=["bilibili"], num=3,
                    snapshots_dir=self.snap_dir,
                    sampler=self._sampler(["旧1", "旧2", "旧3"]))
        calls = []
        with mock.patch.object(hw.hl, "hot",
                               self._sampler(["旧2", "旧3", "新1"])), \
                mock.patch.object(hw, "_toast_send_impl",
                                  lambda t, b: calls.append((t, b)) or
                                  {"status": "sent", "return": 1}), \
                redirect_stdout(io.StringIO()):
            code = hw._cycle(["bilibili"], 3, self.snap_dir, 50, None,
                             toast=True)
        self.assertEqual(code, 0)                    # 事件不是故障
        self.assertEqual(len(calls), 1)
        self.assertIn("热榜新增 1 条", calls[0][0])
        self.assertIn("[bilibili#3] 新1", calls[0][1])

    def test_fault_round_no_toast_exit1(self):
        def broken(platforms=None, num=20, on_error="report"):
            raise OSError("网络炸了")

        calls = []
        with mock.patch.object(hw.hl, "hot", broken), \
                mock.patch.object(hw, "_toast_send_impl",
                                  lambda t, b: calls.append(1)), \
                redirect_stdout(io.StringIO()), \
                redirect_stderr(io.StringIO()):
            code = hw._cycle(["bilibili"], 3, self.snap_dir, 50, None,
                             toast=True)
        self.assertEqual(code, 1)
        self.assertEqual(calls, [])                  # fault 不弹

    def test_cli_toast_flag_end_to_end(self):
        hw.run_once(platforms=["bilibili"], num=3,
                    snapshots_dir=self.snap_dir,
                    sampler=self._sampler(["旧1", "旧2", "旧3"]))
        calls = []
        argv = ["hotlist_watch.py", "--platforms", "bilibili", "--num", "3",
                "--snapshots-dir", self.snap_dir, "--toast"]
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(hw.hl, "hot",
                                  self._sampler(["旧1", "新9", "新8"])), \
                mock.patch.object(hw, "_toast_send_impl",
                                  lambda t, b: calls.append((t, b)) or
                                  {"status": "sent", "return": -1}), \
                redirect_stdout(io.StringIO()):
            code = hw._main()
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 1)              # --toast 进 CLI 接线

    def test_relative_log_anchored_at_script_dir(self):
        # v3.35：相对 --log 锚定本脚本所在目录（schtasks 任务工作目录
        # 不可设恒为 system32）——用假 __file__ 锚到 tmp 验证落点
        with tempfile.TemporaryDirectory() as td:
            fake_self = Path(td) / "hotlist_watch.py"
            argv = ["hotlist_watch.py", "--platforms", "bilibili",
                    "--num", "3", "--snapshots-dir", str(Path(td) / "snaps"),
                    "--log", "state/zz_anchor.md"]
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.object(hw, "__file__", str(fake_self)), \
                    mock.patch.object(hw.hl, "hot",
                                      self._sampler(["旧1"])), \
                    redirect_stdout(io.StringIO()):
                code = hw._main()
            self.assertEqual(code, 0)
            self.assertTrue(
                (Path(td) / "state" / "zz_anchor.md").exists(),
                "相对 --log 必须落在假脚本目录下")

    def test_cli_help_mentions_toast(self):
        argv = ["hotlist_watch.py", "--help"]
        out = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                redirect_stdout(out), \
                self.assertRaises(SystemExit) as cm:
            hw._main()
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("--toast", out.getvalue())


# ---------------------------------------------------------------------------
# 4. hotlist_watch_task register --toast（opt-in；v3.35 实机抓虫双对策）
# ---------------------------------------------------------------------------
def _task_xml(cmd, arg):
    """schtasks /Query /XML 的最小可解析形态（正则消费目标）。"""
    return ('<?xml version="1.0" encoding="UTF-16"?><Tasks>'
            f"<Commands><Command>{cmd}</Command>"
            f"<Arguments>{arg}</Arguments></Commands></Tasks>")


class TestWatchRegistrarToast(unittest.TestCase):
    def test_register_toast_appends_flag(self):
        seen = []

        def runner(argv, **kw):
            seen.append(list(argv))
            return _Proc(stdout="SUCCESS")

        self.assertEqual(task.register(runner=runner, toast=True), 0)
        tr = seen[0][seen[0].index("/TR") + 1]
        self.assertTrue(tr.endswith(" --toast"))
        self.assertLessEqual(len(tr), task.TR_MAX)

    def test_register_default_no_toast_flag(self):
        seen = []

        def runner(argv, **kw):
            seen.append(list(argv))
            return _Proc(stdout="SUCCESS")

        self.assertEqual(task.register(runner=runner), 0)
        tr = seen[0][seen[0].index("/TR") + 1]
        self.assertNotIn("--toast", tr)              # 无旗标不含弹窗
        self.assertTrue(tr.endswith("state/shift_log.md"))

    def test_tr_length_well_below_silent_truncation_cliff(self):
        # v3.35 实机抓虫：截断悬崖实测 (250, 258]，258 字符全串被削尾
        # 仍报 SUCCESS——TR 必须远离悬崖（相对 --log 后 ≤ 180）
        for toast in (False, True):
            tr = task._tr_value(task._python_for_task(), toast=toast)
            self.assertLessEqual(len(tr), 180)

    def test_tr_cap_enforced_with_toast(self):
        long_py = "P:\\" + "x" * 300 + "pythonw.exe"
        with self.assertRaises(ValueError):
            task._tr_value(long_py, toast=True)

    def test_register_toast_message_mentions_notification(self):
        out = io.StringIO()

        def runner(argv, **kw):
            return _Proc(stdout="SUCCESS")

        with redirect_stdout(out):
            self.assertEqual(task.register(runner=runner, toast=True), 0)
        self.assertIn("Windows 通知", out.getvalue())

    def test_verify_readback_mismatch_exit1(self):
        # 截断形态回放：/Create 报成功但存储 /TR 被削尾——回读验证必须
        # 响亮 exit 1（宁报错不留假任务，v3.35 实机抓虫根治钉）
        tr = task._tr_value(task._python_for_task(), toast=True)
        cmd, rest = tr.split(" ", 1)
        xml = _task_xml(cmd, rest[:-5])              # 削掉 'toast' 模拟截断
        err = io.StringIO()

        def runner(argv, **kw):
            if "/Query" in argv:
                return _Proc(stdout=xml)
            return _Proc(stdout="SUCCESS")

        with mock.patch.object(sys, "platform", "win32"), \
                redirect_stderr(err):
            code = task.register(runner=runner, toast=True)
        self.assertEqual(code, 1)
        self.assertIn("回读验证失败", err.getvalue())
        self.assertIn("静默截断", err.getvalue())

    def test_verify_readback_match_ok(self):
        tr = task._tr_value(task._python_for_task(), toast=True)
        cmd, rest = tr.split(" ", 1)
        xml = _task_xml(cmd, rest)
        out, err = io.StringIO(), io.StringIO()

        def runner(argv, **kw):
            if "/Query" in argv:
                return _Proc(stdout=xml)
            return _Proc(stdout="SUCCESS")

        with mock.patch.object(sys, "platform", "win32"), \
                redirect_stdout(out), redirect_stderr(err):
            code = task.register(runner=runner, toast=True)
        self.assertEqual(code, 0)
        self.assertIn("回读验证通过", out.getvalue())

    def test_verify_readback_unavailable_warns_not_fails(self):
        # 「无法验证」不等于「验证失败」：/Query 出不来 XML 只告警，
        # 注册结果不因此翻红（/Create 本身已 SUCCESS）
        out, err = io.StringIO(), io.StringIO()

        def runner(argv, **kw):
            return _Proc(stdout="SUCCESS")           # 非 XML 形态

        with mock.patch.object(sys, "platform", "win32"), \
                redirect_stdout(out), redirect_stderr(err):
            code = task.register(runner=runner, toast=True)
        self.assertEqual(code, 0)
        self.assertIn("回读验证不可用", err.getvalue())


# ---------------------------------------------------------------------------
# 5. 版本锁（自 test_v3340 接管；v3.36 起精确锁移交 test_v3360，此处降
#    常青下限——v3.27→v3.28→v3.29→v3.30→v3.31→v3.33→v3.34→v3.35 先例）
# ---------------------------------------------------------------------------
class TestVersionSyncV335(unittest.TestCase):
    def test_versions_evergreen(self):
        # v3.36 起精确锁移交 test_v3360，此处降常青下限（交接先例）：
        # 双 __version__ 同步本身不许破，只放开具体版本号
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        m = re.search(r'__version__ = "([^"]+)"', init_src)
        self.assertIsNotNone(m)
        ver = m.group(1)
        self.assertGreaterEqual(
            [int(x) for x in ver.split(".")], [3, 35, 0])
        self.assertIn(f"chat-scraper v{ver}", init_src)
        try:
            import mcp_server              # noqa: F401
            self.assertEqual(mcp_server.__version__, ver)
        except ImportError:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            self.assertIn(f'__version__ = "{ver}"', src)

    def test_changelog_and_readme_evergreen(self):
        # v3.36 起精确徽章/状态行锁移交 test_v3360，此处降常青：
        # 3.35 批次的 CHANGELOG 事实行（toast.py/回读验证/--toast）永久在场
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.35.0] - 2026-09-17", changelog)
        self.assertIn("toast.py", changelog)
        self.assertIn("--toast", changelog)
        self.assertIn("静默截断", changelog)
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        # 测试徽章数 v3.36 起移交 test_v3360 精确锁，此处降常青单调下限：
        # 638（v3.34 基线）+ 本批 38 钉 = 676（v3.35 基线），只许增不许缩
        m = re.search(r"tests-(\d+)%20passing", readme)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(int(m.group(1)),
                                638 + self._batch_pins())

    @staticmethod
    def _batch_pins():
        src = (REPO / "tests" / "test_v3350.py").read_text(encoding="utf-8")
        # 数真实 test 方法定义形态；本函数注释与正则字面量一律不得写成
        # 可被下方正则命中的形态（自引用虚增——v3.33 首跑抓到过）
        return len(re.findall(r"def (test_\w+)\(", src))

    def test_honest_doc_channel_evidence_in_toast_module(self):
        # 通道选型活体取证结论随模块走（架构原则 8：诚实文档）
        doc = toast_mod.__doc__ or ""
        self.assertIn("BurntToast", doc)             # 拒因：要装模块
        self.assertIn("msg.exe", doc)                # 拒因：无超时/Home 缺失
        self.assertIn("QN_QUIET_TIME", doc)          # WinRT 双闸实锤之一
        self.assertIn("WScript.Shell", doc)          # 采用通道

    def test_honest_doc_watch_toast_semantics(self):
        doc = hw.__doc__ or ""
        self.assertIn("--toast", doc)                # 旗标在场
        self.assertIn("尽力而为", doc)               # 失败不翻退出码承诺
        self.assertIn("tools/toast.py", doc)         # 通道出处
        # v3.35 实机抓虫证据链必须留在 docstring（架构原则 8：诚实文档）
        # ——旧的「/TR 逐字节一致零漂移」承诺随注册器形态演进失效，
        # 换成截断悬崖实测 + 双对策（诚实承诺不随版本漂移，只许换真话）
        self.assertIn("静默截断", doc)
        self.assertIn("回读验证", doc)
        self.assertIn("(250, 258]", doc)


if __name__ == "__main__":
    unittest.main()
