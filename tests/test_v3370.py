"""v3.37.0 回归：注册器公共层二次提炼 tools/_schtasks_common.py。

四块内容（全部离线，零真实网络/零真实注册——全走 runner 注入）：
1. 公共层行为钉：python_for_task（pythonw 优先/缺失回退告警 + tag/cadence
   参数化——watchdog 高频闪窗措辞 "on each run" 与单任务 "daily" 不硬统
   一）/ run_schtasks（解码链 + runner 注入）/ stream / readback_tr
   （task_name 进 /Query argv——参数化承重证据）/ verify_stored_tr 三态
   （一致 pass / 不一致 ERROR / 无法回读 warn）/ is_already_gone 三措辞 /
   check_tr_length / win32_guard。
2. 三方同源 is 钉 + 委托包装零漂移（v3.36 解码链收口同思路：别名断链 =
   收口失败；签名有变的 _python_for_task/_readback_tr 留 1 行委托，旧引用
   名不断）+ 副本不再生源码钉（机械件特征串只许存在于公共层一处）。
3. unregister 语义差异承重钉（v3.37 立项取证结论，参数化不硬统一）：
   单任务版（digest/hotlist）本任务成败即返回值；watchdog 双任务版循环
   删 + failed 聚合（任一真实失败整体 exit 1、循环不中断、顺序 boot ->
   watchdog）——控制流留在各注册器，公共层只共享 is_already_gone 谓词。
4. 版本锁 3.37.0（自 test_v3360 接管精确锁）+ CHANGELOG/README 徽章 +
   诚实文档钉（公共层收口史随 docstring 走）。
"""
import io
import pathlib
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "chat-scraper"))
sys.path.insert(0, str(REPO / "tools" / "google-bridge"))
sys.path.insert(0, str(REPO / "tools"))

import _subproc_decode as sd         # noqa: E402
import _schtasks_common as sc        # noqa: E402
import digest as dg                  # noqa: E402
import digest_task as dtask          # noqa: E402
import hotlist_watch_task as hwtask  # noqa: E402
import watchdog_task as wtask        # noqa: E402


class _Proc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def _task_xml(cmd, arg):
    """schtasks /Query /XML 的最小可解析形态（正则消费目标）。"""
    return ('<?xml version="1.0" encoding="UTF-16"?><Tasks>'
            f"<Commands><Command>{cmd}</Command>"
            f"<Arguments>{arg}</Arguments></Commands></Tasks>")


# ---------------------------------------------------------------------------
# 1. 公共层行为钉
# ---------------------------------------------------------------------------
class TestSchtasksCommon(unittest.TestCase):
    def test_python_for_task_prefers_pythonw(self):
        with tempfile.TemporaryDirectory() as td:
            pythonw = Path(td) / "pythonw.exe"
            pythonw.write_text("", encoding="utf-8")
            with mock.patch.object(sys, "executable",
                                   str(Path(td) / "python.exe")):
                self.assertEqual(sc.python_for_task("x"), str(pythonw))

    def test_python_for_task_fallback_warns_tag_and_cadence(self):
        # 缺 pythonw -> 回退 sys.executable + stderr 告警；tag 进前缀；
        # cadence 措辞参数化（watchdog "on each run" vs 单任务 "daily"
        # ——文案对任务真，参数化不硬统一）
        with tempfile.TemporaryDirectory() as td:
            exe = Path(td) / "python.exe"
            with mock.patch.object(sys, "executable", str(exe)):
                err = io.StringIO()
                with redirect_stderr(err):
                    got = sc.python_for_task("digest_task")
                self.assertEqual(got, str(exe))
                blob = err.getvalue()
                self.assertIn("[digest_task] warning:", blob)
                self.assertIn("flash daily", blob)
                err2 = io.StringIO()
                with redirect_stderr(err2):
                    sc.python_for_task("watchdog_task", cadence="on each run")
                self.assertIn("flash on each run", err2.getvalue())

    def test_run_schtasks_runner_injected_and_decoded(self):
        # runner 注入形态：runner 被以 capture_output+text 调用；GBX 字节
        # 流经 decode_out 双链（str 原样透传；bytes 走 utf-8->gbk 链）
        seen = {}

        def runner(argv, **kw):
            seen.update(kw)
            return _Proc(stdout="成功".encode("gbk"), stderr=b"raw")

        proc = sc.run_schtasks(["schtasks"], runner=runner)
        self.assertTrue(seen.get("capture_output"))
        self.assertTrue(seen.get("text"))
        self.assertEqual(proc.stdout, "成功")
        self.assertEqual(proc.stderr, "raw")

    def test_stream_none_safe(self):
        self.assertEqual(sc.stream(_Proc(), "stdout"), "")
        self.assertEqual(sc.stream(_Proc(stdout="x"), "stdout"), "x")

    def test_readback_tr_task_name_parameterized(self):
        # v3.37 立项承重点：_readback_tr 两副本唯一实质差异是 TASK_NAME
        # ——公共层参数化后 task_name 必须真实进 /Query argv
        seen = []

        def runner(argv, **kw):
            seen.append(argv)
            return _Proc(stdout=_task_xml("C:\\p.exe", "--flag"))

        got = sc.readback_tr("ai-search-digest", runner=runner)
        self.assertEqual(got, "C:\\p.exe --flag")
        self.assertIn("/TN", seen[0])
        self.assertEqual(seen[0][seen[0].index("/TN") + 1],
                         "ai-search-digest")
        self.assertIn("/XML", seen[0])

    def test_readback_tr_contract(self):
        # 非零退出（任务缺失）/非 XML 形态 -> None（「无法验证」与
        # 「验证失败」分离，不混谈）
        self.assertIsNone(sc.readback_tr(
            "t", runner=lambda a, **k: _Proc(returncode=1)))
        self.assertIsNone(sc.readback_tr(
            "t", runner=lambda a, **k: _Proc(stdout="SUCCESS")))

    def test_verify_stored_tr_match_ok(self):
        xml = _task_xml('"C:\\p\\pythonw.exe"', '"C:\\r\\d.py" --log x')

        def runner(argv, **kw):
            if "/Query" in argv:
                return _Proc(stdout=xml)
            return _Proc(stdout="SUCCESS")

        out = io.StringIO()
        with redirect_stdout(out):
            ok = sc.verify_stored_tr("t", '"C:\\p\\pythonw.exe" '
                                        '"C:\\r\\d.py" --log x',
                                     "digest_task", runner=runner)
        self.assertTrue(ok)
        self.assertIn("回读验证通过", out.getvalue())

    def test_verify_stored_tr_mismatch_error(self):
        # 截断形态回放（v3.35 实机同款）：/Create 报成功但存储被削尾
        # ——响亮 ERROR False，调用方 exit 1
        expected = '"C:\\p\\pythonw.exe" "C:\\r\\d.py" --log x --toast'
        xml = _task_xml('"C:\\p\\pythonw.exe"', '"C:\\r\\d.py" --log x --')

        def runner(argv, **kw):
            if "/Query" in argv:
                return _Proc(stdout=xml)
            return _Proc(stdout="SUCCESS")

        err = io.StringIO()
        with redirect_stderr(err):
            ok = sc.verify_stored_tr("t", expected, "digest_task",
                                     runner=runner)
        self.assertFalse(ok)
        blob = err.getvalue()
        self.assertIn("回读验证失败", blob)
        self.assertIn("静默截断", blob)
        self.assertIn("[digest_task] ERROR:", blob)

    def test_verify_stored_tr_unavailable_warns_not_fails(self):
        # 「无法验证」不等于「验证失败」：回读不出只告警，返回 True
        err = io.StringIO()
        with redirect_stderr(err):
            ok = sc.verify_stored_tr(
                "t", "anything", "hotlist_watch_task",
                runner=lambda a, **k: _Proc(stdout="SUCCESS"))
        self.assertTrue(ok)
        blob = err.getvalue()
        self.assertIn("回读验证不可用", blob)
        self.assertIn("[hotlist_watch_task] warning:", blob)

    def test_verify_stored_tr_whitespace_insensitive(self):
        # 空白不敏感比对（schtasks 拆 Command/Arguments 时空格归属有出入）
        def runner(argv, **kw):
            return _Proc(stdout=_task_xml("C:\\p.exe", "a  b"))

        ok = sc.verify_stored_tr("t", "C:\\p.exe a b", "x", runner=runner)
        self.assertTrue(ok)

    def test_is_already_gone_three_wordings(self):
        # 三措辞逐字收口自三注册器逐字一致副本：英文 does not exist /
        # 中文 不存在 / 找不到（「系统找不到指定的文件」实测形态）
        for wording in ("ERROR: The specified task name \"x\" does not "
                        "exist in the system.",
                        "错误: 系统不存在指定的任务。",
                        "错误: 系统找不到指定的文件。"):
            self.assertTrue(sc.is_already_gone(
                _Proc(returncode=1, stderr=wording)), wording)
        self.assertFalse(sc.is_already_gone(
            _Proc(returncode=1, stderr="拒绝访问。")))
        self.assertFalse(sc.is_already_gone(_Proc(returncode=1)))

    def test_check_tr_length_ok_and_raises(self):
        self.assertIsNone(sc.check_tr_length("x" * 261))
        with self.assertRaises(ValueError) as cm:
            sc.check_tr_length("x" * 262)
        blob = str(cm.exception)
        self.assertIn("/TR too long", blob)
        self.assertIn("262 > 261", blob)

    def test_win32_guard_true_and_false_suffix(self):
        with mock.patch.object(sys, "platform", "win32"):
            self.assertTrue(sc.win32_guard("x"))
        with mock.patch.object(sys, "platform", "linux"):
            err = io.StringIO()
            with redirect_stderr(err):
                self.assertFalse(sc.win32_guard("x", " (Linux: cron)"))
            blob = err.getvalue()
            self.assertIn("Windows-only", blob)
            self.assertIn("[x] ERROR:", blob)
            self.assertIn("(Linux: cron)", blob)   # suffix 逐字透传


# ---------------------------------------------------------------------------
# 2. 三方同源 is 钉 + 委托包装零漂移 + 副本不再生
# ---------------------------------------------------------------------------
class TestSameFunctionObject(unittest.TestCase):
    def test_run_schtasks_three_sites_same_object(self):
        # 三注册器旧引用名 is 钉到公共层同一函数对象——谁又复制一份函数
        # 体（或包装了一层断开身份）在此响亮翻红
        self.assertIs(dtask._run_schtasks, sc.run_schtasks)
        self.assertIs(hwtask._run_schtasks, sc.run_schtasks)
        self.assertIs(wtask._run_schtasks, sc.run_schtasks)

    def test_stream_three_sites_same_object(self):
        self.assertIs(dtask._stream, sc.stream)
        self.assertIs(hwtask._stream, sc.stream)
        self.assertIs(wtask._stream, sc.stream)

    def test_decode_binding_still_alive(self):
        # v3.36 四方 is 钉延续：_run_schtasks 收口公共层后注册器不再直接
        # 消费 _decode，但绑定必须存活（test_v3360 同款断言仍独立在跑）
        self.assertIs(dtask._decode, sd.decode_out)
        self.assertIs(hwtask._decode, sd.decode_out)
        self.assertIs(wtask._decode, sd.decode_out)

    def test_wrappers_delegate_with_injection(self):
        # 签名有变的件留 1 行委托包装（旧引用名零漂移）：_readback_tr 注
        # 入本注册器 TASK_NAME，_python_for_task 注入本注册器 TAG——注入
        # 真实生效（不是摆设）
        seen = []
        xml = _task_xml("C:\\p.exe", "--flag")
        for mod, name in ((dtask, dtask.TASK_NAME),
                          (hwtask, hwtask.TASK_NAME)):
            seen.clear()

            def runner(argv, **kw):
                seen.append(argv)
                return _Proc(stdout=xml)

            got = mod._readback_tr(runner=runner)
            self.assertEqual(got, "C:\\p.exe --flag")
            self.assertIn(name, seen[0])
        self.assertEqual(dtask._python_for_task(),
                         sc.python_for_task(dtask.TAG))
        self.assertEqual(hwtask._python_for_task(),
                         sc.python_for_task(hwtask.TAG))
        self.assertEqual(wtask._python_for_task(),
                         sc.python_for_task(wtask.TAG, cadence="on each run"))


class TestNoLocalCopies(unittest.TestCase):
    _SITES = ("tools/digest_task.py",
              "tools/chat-scraper/hotlist_watch_task.py",
              "tools/google-bridge/watchdog_task.py")

    def test_mechanical_pieces_only_in_common(self):
        # 副本不再生源码钉（v3.36 链身先例同思路）：四类机械件特征串只许
        # 存在于公共层一处；三注册器一律 from _schtasks_common import
        common_src = (REPO / "tools" / "_schtasks_common.py").read_text(
            encoding="utf-8")
        for needle in ('with_name("pythonw.exe")',
                       "subprocess.run(argv, capture_output=True)",
                       r"<Command>(.*?)</Command",
                       '"找不到" in blob',
                       "ERROR: Windows-only"):
            self.assertIn(needle, common_src, needle)
        for rel in self._SITES:
            src = (REPO / rel).read_text(encoding="utf-8")
            for needle in ('with_name("pythonw.exe")',
                           "subprocess.run(argv, capture_output=True)",
                           r"<Command>(.*?)</Command",
                           '"找不到" in blob',
                           "ERROR: Windows-only"):
                self.assertNotIn(needle, src, f"{rel}: {needle}")
            self.assertIn("from _schtasks_common import", src, rel)

    def test_unregister_wording_match_only_in_common(self):
        # unregister「不存在」幂等匹配收口谓词：注册器侧只许调
        # is_already_gone，不许再出现内联三措辞 blob 匹配
        for rel in self._SITES:
            src = (REPO / rel).read_text(encoding="utf-8")
            self.assertNotIn('in blob or', src, rel)
            self.assertIn("is_already_gone(proc)", src, rel)


# ---------------------------------------------------------------------------
# 3. unregister 语义差异承重钉（参数化不硬统一）
# ---------------------------------------------------------------------------
class TestUnregisterSemanticsPreserved(unittest.TestCase):
    def test_single_task_unregister_semantics(self):
        # 单任务版（digest/hotlist）：恰一次 /Delete；不存在 -> 幂等 0；
        # 真实失败 -> 1（本任务成败即返回值）
        for mod in (dtask, hwtask):
            calls = []

            def runner(argv, **kw):
                calls.append(argv)
                return _Proc(returncode=1,
                             stderr="错误: 系统找不到指定的文件。")

            err = io.StringIO()
            with redirect_stderr(err):
                self.assertEqual(mod.unregister(runner=runner), 0, mod)
            self.assertEqual(len(calls), 1, mod)
            self.assertIn("/Delete", calls[0])

            calls.clear()
            err = io.StringIO()
            with redirect_stderr(err):
                self.assertEqual(mod.unregister(
                    runner=lambda a, **k: _Proc(
                        returncode=1, stderr="拒绝访问。")), 1, mod)
            self.assertIn("unregister FAILED", err.getvalue())

    def test_watchdog_unregister_loop_aggregate(self):
        # 双任务版（watchdog）：循环删 boot -> watchdog 顺序；「不存在」
        # 逐任务幂等；一个真实失败 -> 整体 1 但循环不中断（另一任务仍被
        # 删除）；两个都 gone -> 0
        calls = []
        mapping = {wtask.TASK_BOOT: (1, "", "错误: 系统找不到指定的文件。"),
                   wtask.TASK_WATCHDOG: (0, "SUCCESS", "")}

        def runner(argv, **kw):
            calls.append(argv)
            rc, so, se = mapping[argv[argv.index("/TN") + 1]]
            return _Proc(returncode=rc, stdout=so, stderr=se)

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(wtask.unregister(runner=runner), 0)
        self.assertEqual([c[c.index("/TN") + 1] for c in calls],
                         [wtask.TASK_BOOT, wtask.TASK_WATCHDOG])
        self.assertIn("already gone", out.getvalue())

        calls.clear()
        mapping = {wtask.TASK_BOOT: (0, "SUCCESS", ""),
                   wtask.TASK_WATCHDOG: (1, "", "在用，无法删除")}
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(wtask.unregister(runner=runner), 1)
        self.assertEqual(len(calls), 2)     # 循环不中断：两任务都被尝试
        self.assertIn("unregister FAILED", err.getvalue())

    def test_loop_control_flow_not_hard_unified(self):
        # 语义差异承重的源码钉：watchdog 的 failed 聚合循环留在本注册器
        # （公共层只共享谓词）——单任务注册器没有循环与聚合
        wsrc = (REPO / "tools" / "google-bridge" / "watchdog_task.py"
                ).read_text(encoding="utf-8")
        self.assertIn("for name in (TASK_BOOT, TASK_WATCHDOG):", wsrc)
        self.assertIn("failed.append(name)", wsrc)
        self.assertIn("return 1 if failed else 0", wsrc)
        for rel in ("tools/digest_task.py",
                    "tools/chat-scraper/hotlist_watch_task.py"):
            src = (REPO / rel).read_text(encoding="utf-8")
            self.assertNotIn("failed.append", src, rel)


# ---------------------------------------------------------------------------
# 4. 版本锁 3.37.0 + 文档（自 test_v3360 接管精确锁）
# ---------------------------------------------------------------------------
class TestVersionSyncV337(unittest.TestCase):
    def test_versions_3370(self):
        self.assertEqual(dg.__version__, "3.37.0")
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        m = re.search(r'__version__ = "([^"]+)"', init_src)
        self.assertEqual(m.group(1), "3.37.0")
        self.assertIn("chat-scraper v3.37.0", init_src)
        try:
            import mcp_server              # noqa: F401
            self.assertEqual(mcp_server.__version__, "3.37.0")
        except ImportError:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            self.assertIn('__version__ = "3.37.0"', src)

    def test_changelog_and_readme_3370(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.37.0] - 2026-09-17", changelog)
        self.assertIn("_schtasks_common", changelog)
        self.assertIn("参数化不硬统一", changelog)
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("release-v3.37.0", readme)
        self.assertIn("v3.37.0（2026-09-17）", readme)
        # 测试徽章数随本批钉死（下一批交接时降常青）：
        # 687（v3.36 基线）+ 本批钉数
        m = re.search(r"tests-(\d+)%20passing", readme)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), 687 + self._batch_pins())

    @staticmethod
    def _batch_pins():
        src = (REPO / "tests" / "test_v3370.py").read_text(encoding="utf-8")
        # 数真实 test 方法定义形态；本函数注释与正则字面量一律不得写成
        # 可被下方正则命中的形态（自引用虚增——v3.33 首跑抓到过）
        return len(re.findall(r"def (test_\w+)\(", src))

    def test_honest_doc_pins(self):
        # 诚实文档（架构原则 8）：公共层收口史（副本漂移病灶/参数化不硬
        # 统一/GBK 承重）随 docstring 走；注册器 docstring 记出处
        sc_doc = sc.__doc__ or ""
        self.assertIn("三注册器", sc_doc)           # 收口范围
        self.assertIn("副本", sc_doc)               # 病灶（副本漂移）
        self.assertIn("参数化不硬统一", sc_doc)     # 差异处置原则
        self.assertIn("is_already_gone", sc_doc)    # unregister 只共享谓词
        self.assertIn("GBK", sc_doc)                # 解码承重
        dt_doc = dtask.__doc__ or ""
        self.assertIn("_schtasks_common", dt_doc)   # 机械件出处
        hw_doc = hwtask.__doc__ or ""
        self.assertIn("_schtasks_common", hw_doc)
        wt_doc = wtask.__doc__ or ""
        self.assertIn("_schtasks_common", wt_doc)


if __name__ == "__main__":
    unittest.main()
