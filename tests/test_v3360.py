"""v3.36.0 回归：digest_task 回读验证移植 + 解码链四方副本收口。

三块内容（全部离线，零真实网络/零真实注册——回读验证全走 runner 注入，
真注册路径与 hotlist_watch_task v3.35 实测同款，证据在 CHANGELOG）：
1. tools/_subproc_decode.py（新公用模块）：utf-8 严格 -> gbk 严格 ->
   replace 兜底链行为钉 + **四方同一函数对象身份钉**（toast/digest_task/
   hotlist_watch_task/watchdog_task 以 is 钉同源——别名 re-export 保旧
   引用名，身份断链 = 收口失败）+ 副本不再生源码钉（链身 for-loop 只许
   存在于共享模块一处）。
2. digest_task 回读验证（hotlist_watch_task v3.35 实机抓虫对策移植；
   v3.35 CHANGELOG 明记 digest_task 同病种潜伏、下一环建议即本批）：
   /Query /XML 存储与预期不一致响亮 exit 1（静默截断不留假任务）；一致
   exit 0 打印通过；无法回读（非 XML 形态）只告警不判失败——「无法验
   证」不等于「验证失败」。/TR 仍为绝对 --log 形态（v3.34 零漂移承诺，
   本机 238 字符余量 23 暂离悬崖 (250, 258]，回读是兜底不是装饰）。
3. 版本锁 3.36.0（双 __version__ + mcp_server，自 test_v3350 接管精确
   锁）+ CHANGELOG/README 徽章 + 诚实文档钉（共享模块收口史随
   docstring 走）。
"""
import io
import pathlib
import re
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "chat-scraper"))
sys.path.insert(0, str(REPO / "tools" / "google-bridge"))
sys.path.insert(0, str(REPO / "tools"))

import _subproc_decode as sd         # noqa: E402
import toast as toast_mod            # noqa: E402
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
# 1. 共享解码模块：行为链 + 四方身份 + 副本不再生
# ---------------------------------------------------------------------------
class TestSharedDecodeModule(unittest.TestCase):
    def test_decode_out_chain_behavior(self):
        # None->"" / str 透传 / utf-8 严格 / gbk 严格（中文 Windows 实测
        # 主路径）/ 双败 replace 兜底（\ufffd 可见化不抛）
        self.assertEqual(sd.decode_out(None), "")
        self.assertEqual(sd.decode_out("str passthrough"), "str passthrough")
        self.assertEqual(sd.decode_out("成功".encode("utf-8")), "成功")
        self.assertEqual(sd.decode_out("成功".encode("gbk")), "成功")
        self.assertIn("\ufffd", sd.decode_out(b"\xff\xfe"))

    def test_four_sites_same_function_object(self):
        # 四方旧引用名全部 is 钉到共享模块同一函数对象——别名 re-export
        # 断链（谁又复制了一份函数体）在此响亮翻红
        self.assertIs(toast_mod._decode_out, sd.decode_out)
        self.assertIs(dg._decode_out, sd.decode_out)
        self.assertIs(dtask._decode, sd.decode_out)
        self.assertIs(hwtask._decode, sd.decode_out)
        self.assertIs(wtask._decode, sd.decode_out)

    def test_no_local_decode_copies_left(self):
        # 副本不再生源码钉：链身 for-loop 只许存在于 _subproc_decode.py
        # 一处；四个消费方一律改 import（v3.28/v3.31/v3.34 同病灶三轮
        # 复发史——副本漂移改一处漏三处）
        shared_src = (REPO / "tools" / "_subproc_decode.py"
                      ).read_text(encoding="utf-8")
        self.assertIn('for codec in ("utf-8", "gbk")', shared_src)
        for rel in ("tools/toast.py", "tools/digest_task.py",
                    "tools/chat-scraper/hotlist_watch_task.py",
                    "tools/google-bridge/watchdog_task.py"):
            src = (REPO / rel).read_text(encoding="utf-8")
            self.assertNotIn("for codec in", src, rel)
            self.assertIn("from _subproc_decode import", src, rel)


# ---------------------------------------------------------------------------
# 2. digest_task 回读验证（hotlist_watch_task v3.35 对策移植）
# ---------------------------------------------------------------------------
class TestDigestTaskReadback(unittest.TestCase):
    def test_readback_tr_contract(self):
        # XML 正常拆 Command+Arguments 拼接返回；非零退出/无节点 -> None
        # （「无法验证」与「验证失败」分离，不混谈）
        xml = _task_xml('"C:\\p\\pythonw.exe" "C:\\r\\d.py"',
                        '--log "C:\\r\\l.md"')

        def runner(argv, **kw):
            return _Proc(stdout=xml)

        self.assertEqual(
            dtask._readback_tr(runner=runner),
            '"C:\\p\\pythonw.exe" "C:\\r\\d.py" --log "C:\\r\\l.md"')
        self.assertIsNone(dtask._readback_tr(
            runner=lambda a, **k: _Proc(returncode=1)))          # 任务缺失
        self.assertIsNone(dtask._readback_tr(
            runner=lambda a, **k: _Proc(stdout="SUCCESS")))      # 非 XML

    def test_verify_readback_mismatch_exit1(self):
        # 截断形态回放（v3.35 实机同款：尾部 --toast 被削成 --）：
        # /Create 报成功但存储 /TR 被削尾——回读验证必须响亮 exit 1
        tr = dtask._tr_value(dtask._python_for_task(), toast=True)
        cmd, rest = tr.split(" ", 1)
        xml = _task_xml(cmd, rest[:-5])
        err = io.StringIO()

        def runner(argv, **kw):
            if "/Query" in argv:
                return _Proc(stdout=xml)
            return _Proc(stdout="SUCCESS")

        with mock.patch.object(sys, "platform", "win32"), \
                redirect_stderr(err):
            code = dtask.register(runner=runner, toast=True)
        self.assertEqual(code, 1)
        self.assertIn("回读验证失败", err.getvalue())
        self.assertIn("静默截断", err.getvalue())

    def test_verify_readback_match_ok(self):
        tr = dtask._tr_value(dtask._python_for_task(), toast=True)
        cmd, rest = tr.split(" ", 1)
        xml = _task_xml(cmd, rest)
        out, err = io.StringIO(), io.StringIO()

        def runner(argv, **kw):
            if "/Query" in argv:
                return _Proc(stdout=xml)
            return _Proc(stdout="SUCCESS")

        with mock.patch.object(sys, "platform", "win32"), \
                redirect_stdout(out), redirect_stderr(err):
            code = dtask.register(runner=runner, toast=True)
        self.assertEqual(code, 0)
        self.assertIn("回读验证通过", out.getvalue())

    def test_verify_readback_unavailable_warns_not_fails(self):
        # 「无法验证」不等于「验证失败」：/Query 出不来 XML 只告警，
        # 注册结果不因此翻红（/Create 本身已 SUCCESS）
        out, err = io.StringIO(), io.StringIO()

        def runner(argv, **kw):
            return _Proc(stdout="SUCCESS")

        with mock.patch.object(sys, "platform", "win32"), \
                redirect_stdout(out), redirect_stderr(err):
            code = dtask.register(runner=runner, toast=True)
        self.assertEqual(code, 0)
        self.assertIn("回读验证不可用", err.getvalue())

    def test_tr_form_absolute_log_unchanged_v334(self):
        # /TR 保持 v3.34 绝对 --log 形态（已注册任务零漂移；本机 238 字
        # 符余量 23 暂离悬崖——不学 hotlist_watch_task 改相对值，因为
        # digest.py 相对路径锚定语义不同；回读验证才是本批兜底）
        tr_plain = dtask._tr_value(dtask._python_for_task())
        self.assertNotIn("--toast", tr_plain)
        self.assertIn(str(dtask.SHIFT_LOG), tr_plain)
        tr_toast = dtask._tr_value(dtask._python_for_task(), toast=True)
        self.assertTrue(tr_toast.endswith(" --toast"))
        self.assertLessEqual(len(tr_toast), dtask.TR_MAX)


# ---------------------------------------------------------------------------
# 3. 版本锁 3.36.0 + 文档（自 test_v3350 接管精确锁）
# ---------------------------------------------------------------------------
class TestVersionSyncV336(unittest.TestCase):
    def test_versions_3360(self):
        # v3.37 起精确锁移交 test_v3370，此处降常青下限（v3.27→…→v3.33
        # 先例）：双 __version__ 同步本身不许破
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        m = re.search(r'__version__ = "([^"]+)"', init_src)
        self.assertGreaterEqual(
            [int(x) for x in m.group(1).split(".")], [3, 36, 0])
        self.assertIn(f"chat-scraper v{m.group(1)}", init_src)
        try:
            import mcp_server              # noqa: F401
            self.assertEqual(mcp_server.__version__, m.group(1))
        except ImportError:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            self.assertIn(f'__version__ = "{m.group(1)}"', src)

    def test_changelog_and_readme_3360(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.36.0] - 2026-09-17", changelog)
        self.assertIn("_subproc_decode", changelog)
        self.assertIn("回读验证", changelog)
        # v3.37 起精确徽章/状态行锁移交 test_v3370，此处降常青：
        # 徽章/状态行与 __version__ 一致（防换版时徽章漂移回退）
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        ver = re.search(r'__version__ = "([^"]+)"', init_src).group(1)
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"release-v{ver}", readme)
        self.assertIn(f"v{ver}（", readme)
        # 测试徽章数 v3.37 起移交 test_v3370 精确锁，此处降常青单调下限：
        # 676（v3.35 基线）+ 11（v3.36 本批钉），回归只许增不许缩
        m = re.search(r"tests-(\d+)%20passing", readme)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(int(m.group(1)), 687)

    def test_honest_doc_pins(self):
        # 诚实文档（架构原则 8）：收口史随共享模块 docstring 走，
        # 回读验证对策随 digest_task docstring 走
        sd_doc = sd.__doc__ or ""
        self.assertIn("四方", sd_doc)               # 四方副本收口史
        self.assertIn("GBK", sd_doc)                # 病灶（中文 Windows）
        self.assertIn("v3.34", sd_doc)              # 实机抓虫轮次
        dt_doc = dtask.__doc__ or ""
        self.assertIn("回读验证", dt_doc)
        self.assertIn("静默截断", dt_doc)
        self.assertIn("_subproc_decode", dt_doc)    # 解码链出处


if __name__ == "__main__":
    unittest.main()
