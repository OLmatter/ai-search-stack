"""v3.34.0 回归：digest 配置模板入库 + --toast 本机通知通道。

四块内容（全部离线，零真实网络/零真实弹窗——真实链路走 digest 实测落
CHANGELOG v3.34.0；回归钉全走 mock / runner 注入 / 源码钉）：
1. 配置模板：digest_config.example.json 入库（示例值与内置常量双向钉死
   + _readme 注释键被忽略）；load_config 三层回退——用户配置**缺失** →
   仓库模板 → 内置常量，坏 JSON/键类型错保持 v3.33 语义落内置默认
   （配置写坏不该被模板静默掩盖），落回层级 note 如实注明。
2. --toast：send_toast（EncodedCommand argv 形态 / Popup 参数与超时 /
   单引号转义 / POPUP_RET 解析 / 非 win32 skipped / runner 抛异常与
   非零退出 fault 不抛 / 保险丝 20s > 弹窗超时 12s 承重关系）、
   extract_new_entries（新增计数求和 + [NEW] 标题去重 + 标题含内嵌
   括号取最后一个 " (" 定界）、toast_text（段状态图标 / 新增摘要 /
   fault 标题 / 240 上限）、CLI --toast（调用一次 / toast 失败与异常
   均不翻晨报退出码 / 无旗标零调用）。
3. digest_task register --toast：/TR 追加 --toast（261 上限仍执法）；
   无旗标 /TR 与 v3.33 形态逐字节一致（已注册任务零漂移）。
4. 版本锁 3.34.0（双 __version__，自 test_v3330 接管精确锁，v3330 同批
   降常青）+ CHANGELOG + README 徽章 + 诚实文档钉（通道选型活体取证
   在场：WinRT 双闸 / BurntToast 拒因 / popup 采用理由）。
   —— v3.35 起：第 4 块精确锁移交 test_v3350（同批降常青，只保双
   __version__ 同步与徽章单调下限）；test_v3330 降常青交接先例。
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

import digest as dg                 # noqa: E402
import digest_task as task          # noqa: E402

TEMPLATE_PATH = REPO / "tools" / "digest_config.example.json"


class _Proc:
    """subprocess.CompletedProcess 形态的离线替身。"""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _loader_user_missing(template_text):
    """用户配置路径抛 FileNotFoundError、模板路径返回文本的注入 loader
    （load_config 三层回退的承重仿真）。"""

    def _l(f):
        if Path(f) == dg.EXAMPLE_CONFIG:
            return template_text
        raise FileNotFoundError("config missing")

    return _l


# ---------------------------------------------------------------------------
# 1a. 模板入库（文件存在 + 示例值与内置常量双向钉死 + 注释键被忽略）
# ---------------------------------------------------------------------------
class TestTemplate(unittest.TestCase):
    def test_template_exists_valid_json_matches_defaults(self):
        # 零配置可跑的根基：模板在库、可解析、示例值与内置常量一致
        self.assertTrue(TEMPLATE_PATH.is_file())
        data = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(data["watch_repos"], dg.DEFAULT_REPOS)
        self.assertEqual(data["watch_queries"], dg.DEFAULT_QUERIES)
        self.assertEqual(data["watch_platforms"], dg.DEFAULT_PLATFORMS)
        # v3.40 起模板第四键 watch_feeds 双向钉（模板只收实测验证过的源）
        self.assertEqual(data["watch_feeds"], dg.DEFAULT_FEEDS)

    def test_template_has_readme_comment_key(self):
        data = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))
        # JSON 无注释，说明以 _readme 锁在文件里（小白可读——文件即文档）
        self.assertIn("_readme", data)
        self.assertIn("digest_config.json", data["_readme"])
        self.assertIn("watch_platforms", data["_readme"])

    def test_load_config_ignores_unknown_keys(self):
        # _readme 走正常解析路径也不污染配置（未知键一律忽略）
        raw = json.dumps({"_readme": "说明", "watch_queries": ["q1"]})
        r = dg.load_config(loader=lambda p: raw)
        self.assertEqual(r["config"],
                         {"watch_repos": dg.DEFAULT_REPOS,
                          "watch_queries": ["q1"],
                          "watch_platforms": dg.DEFAULT_PLATFORMS,
                          "watch_feeds": dg.DEFAULT_FEEDS})
        self.assertEqual(r["note"], "")


# ---------------------------------------------------------------------------
# 1b. 三层回退（缺失 -> 模板 -> 内置；坏/类型错保持 v3.33 语义）
# ---------------------------------------------------------------------------
class TestConfigThreeTier(unittest.TestCase):
    def test_missing_user_config_falls_to_template(self):
        raw = json.dumps({"watch_repos": ["x/y"], "watch_queries": ["tq"],
                          "watch_platforms": ["bilibili"]})
        with tempfile.TemporaryDirectory() as td:
            r = dg.load_config(str(Path(td) / "nope.json"),
                               loader=_loader_user_missing(raw))
        self.assertEqual(r["config"]["watch_repos"], ["x/y"])
        self.assertEqual(r["config"]["watch_queries"], ["tq"])
        self.assertIn("配置未找到", r["note"])
        self.assertIn("仓库模板", r["note"])

    def test_missing_user_and_template_falls_to_builtin(self):
        def _l(f):
            raise FileNotFoundError("gone")

        with tempfile.TemporaryDirectory() as td:
            r = dg.load_config(str(Path(td) / "nope.json"), loader=_l)
        self.assertEqual(r["config"]["watch_repos"], dg.DEFAULT_REPOS)
        self.assertIn("配置未找到", r["note"])
        self.assertIn("使用内置默认", r["note"])
        self.assertNotIn("模板", r["note"])

    def test_real_repo_missing_config_uses_committed_template(self):
        # 不注入 loader 直读仓库模板——零配置实跑形态（离线只读）
        with tempfile.TemporaryDirectory() as td:
            r = dg.load_config(str(Path(td) / "nope.json"))
        self.assertEqual(r["config"]["watch_repos"], dg.DEFAULT_REPOS)
        self.assertIn("仓库模板", r["note"])

    def test_bad_json_still_builtin_not_template(self):
        # v3.33 语义保持：配置**写坏**落内置默认，不被模板静默掩盖
        r = dg.load_config(loader=lambda p: "{not json")
        self.assertIn("配置解析失败", r["note"])
        self.assertNotIn("模板", r["note"])
        self.assertEqual(r["config"]["watch_queries"], dg.DEFAULT_QUERIES)

    def test_key_type_wrong_still_builtin_not_template(self):
        r = dg.load_config(loader=lambda p: json.dumps(
            {"watch_repos": "not-a-list"}))
        self.assertIn("类型不对", r["note"])
        self.assertNotIn("模板", r["note"])
        self.assertEqual(r["config"]["watch_repos"], dg.DEFAULT_REPOS)


# ---------------------------------------------------------------------------
# 2a. send_toast（WScript.Shell Popup 通道；选型取证见 digest docstring）
# ---------------------------------------------------------------------------
class TestSendToast(unittest.TestCase):
    def test_argv_shape_encoded_command_contains_popup(self):
        seen = []

        def runner(argv):
            seen.append(argv)
            return _Proc(stdout="POPUP_RET=-1\n")

        r = dg.send_toast("标题T", "正文B", runner=runner, platform="win32")
        self.assertEqual(r["status"], "sent")
        self.assertEqual(r["return"], -1)          # 超时自关的返回值
        argv = seen[0]
        self.assertEqual(argv[0], "powershell")
        self.assertIn("-NoProfile", argv)
        self.assertIn("-NonInteractive", argv)
        self.assertIn("-EncodedCommand", argv)
        ps = base64.b64decode(
            argv[argv.index("-EncodedCommand") + 1]).decode("utf-16-le")
        self.assertIn("WScript.Shell", ps)
        self.assertIn(".Popup(", ps)
        self.assertIn(str(dg.TOAST_BOX_TYPE), ps)   # 64+4096 承重值
        self.assertIn("标题T", ps)
        self.assertIn("正文B", ps)

    def test_popup_timeout_seconds_passed_through(self):
        seen = []

        def runner(argv):
            seen.append(argv)
            return _Proc(stdout="POPUP_RET=-1")

        dg.send_toast("t", "b", timeout_s=7, runner=runner, platform="win32")
        ps = base64.b64decode(
            seen[0][seen[0].index("-EncodedCommand") + 1]).decode("utf-16-le")
        self.assertIn(", 7,", ps)

    def test_single_quote_escaped_and_newline_folded(self):
        seen = []

        def runner(argv):
            seen.append(argv)
            return _Proc(stdout="POPUP_RET=1")

        dg.send_toast("it's\n标题", "bo'dy", runner=runner, platform="win32")
        ps = base64.b64decode(
            seen[0][seen[0].index("-EncodedCommand") + 1]).decode("utf-16-le")
        self.assertIn("it''s 标题", ps)              # ' -> ''，\n 折叠
        self.assertIn("bo''dy", ps)
        self.assertNotIn("\n", ps)                   # 命令单行形态

    def test_non_win32_skipped_runner_never_called(self):
        called = []

        def runner(argv):
            called.append(argv)
            return _Proc()

        r = dg.send_toast("t", "b", runner=runner, platform="linux")
        self.assertEqual(r["status"], "skipped")
        self.assertEqual(called, [])

    def test_runner_raise_fault_not_raise(self):
        def runner(argv):
            raise subprocess.TimeoutExpired(cmd="powershell", timeout=20)

        r = dg.send_toast("t", "b", runner=runner, platform="win32")
        self.assertEqual(r["status"], "fault")
        self.assertIn("TimeoutExpired", r["error"])

    def test_nonzero_exit_fault_with_stderr_head(self):
        r = dg.send_toast("t", "b", platform="win32",
                          runner=lambda argv: _Proc(returncode=1,
                                                    stderr="boom"))
        self.assertEqual(r["status"], "fault")
        self.assertIn("powershell exit 1", r["error"])
        self.assertIn("boom", r["error"])

    def test_fuse_margin_load_bearing(self):
        # 子进程保险丝必须大于弹窗自动超时——否则正常弹窗被误杀
        self.assertGreater(dg.TOAST_SUBPROC_TIMEOUT, dg.TOAST_TIMEOUT_S)
        self.assertEqual(dg.TOAST_BOX_TYPE, 64 + 4096)

    def test_decode_out_gbk_fallback_chain(self):
        # v3.34 自审实抓（CHANGELOG 在案）：中文 Windows powershell 输出
        # 含 GBK 字节，text=True 的 utf-8 读管线线程直接崩（v3.28 schtasks
        # 同款病灶）——字节捕获 + utf-8->gbk->replace 链在此钉死
        self.assertEqual(dg._decode_out("str passthrough"), "str passthrough")
        self.assertEqual(dg._decode_out(b"POPUP_RET=-1"), "POPUP_RET=-1")
        self.assertEqual(dg._decode_out(b"\xc4\xe3\xba\xc3"), "你好")
        self.assertIn("\ufffd", dg._decode_out(b"\xff bad"))
        self.assertEqual(dg._decode_out(None), "")


# ---------------------------------------------------------------------------
# 2b. extract_new_entries（watch_lines -> {count, titles}）
# ---------------------------------------------------------------------------
def _diff_line(new, gone, kept, alerts):
    body = (f"hotlist_watch: diff（bilibili+weibo）新增 {new} "
            f"消失 {gone} 保留 {kept}")
    if alerts:
        body += " | " + "；".join(alerts)
    return body


class TestExtractNewEntries(unittest.TestCase):
    def test_count_summed_and_titles_deduped(self):
        lines = [
            _diff_line(3, 2, 29, ["[NEW] [bilibili#2] iPhone 18 Pro (https://x/1)",
                                  "[GONE] [weibo#1] 旧热搜 (https://x/2)"]),
            _diff_line(2, 1, 30, ["[NEW] [weibo#5] 某某上线 (https://x/3)",
                                  "[NEW] [weibo#5] 某某上线 (https://x/3)"]),
        ]
        out = dg.extract_new_entries(lines)
        self.assertEqual(out["count"], 5)            # 多轮求和 3+2
        self.assertEqual(out["titles"], ["iPhone 18 Pro", "某某上线"])

    def test_title_with_inner_ascii_parens(self):
        # 标题自含括号：取**最后一个** " (" 才是 url 起界（跨解析器消费钉）
        lines = [_diff_line(1, 0, 9, [
            "[NEW] [bilibili#1] Beta (rc1) 上线 (https://x/9)"])]
        self.assertEqual(dg.extract_new_entries(lines)["titles"],
                         ["Beta (rc1) 上线"])

    def test_baseline_and_empty_honest(self):
        self.assertEqual(dg.extract_new_entries([]),
                         {"count": 0, "titles": []})
        self.assertEqual(
            dg.extract_new_entries([
                "hotlist_watch: 建基线（bilibili+weibo，有效 40 行）"
                "——下一轮起产 diff 信号"]),
            {"count": 0, "titles": []})

    def test_titles_capped_at_three(self):
        alerts = [f"[NEW] [bilibili#{i}] 标题{i} (https://x/{i})"
                  for i in range(6)]
        self.assertEqual(len(dg.extract_new_entries(
            [_diff_line(6, 0, 0, alerts)])["titles"]), 3)


# ---------------------------------------------------------------------------
# 2c. toast_text（弹窗文案）
# ---------------------------------------------------------------------------
class TestToastText(unittest.TestCase):
    def _result(self, overall="ok", sections=None, new_entries=None,
                ts="2026-09-17 10:00:00"):
        # v3.40 起五段形态：默认 sections 含 feeds=ok
        return {"markdown": "# 晨报\n", "overall": overall,
                "sections": sections or {"hotlist": "ok", "hn": "ok",
                                         "releases": "ok", "feeds": "ok",
                                         "toolbox": "ok"},
                "ts": ts, "new_entries": new_entries}

    def test_ok_with_new_entries_summary(self):
        title, body = dg.toast_text(self._result(
            new_entries={"count": 2, "titles": ["甲事件", "乙事件"]}))
        self.assertTrue(title.startswith("晨报完成"))
        # v3.40 图标序翻转：热榜 HN GitHub RSS 状态（钉翻转：段数 4->5）
        self.assertIn("热榜✅ HN✅ GitHub✅ RSS✅ 状态✅", body)
        self.assertIn("热榜新增 2 条：甲事件 / 乙事件", body)

    def test_fault_title_and_body(self):
        title, body = dg.toast_text(self._result(
            overall="fault",
            sections={"hotlist": "fault", "hn": "fault",
                      "releases": "fault", "toolbox": "fault"}))
        self.assertTrue(title.startswith("晨报故障"))
        self.assertIn("零有效内容", body)

    def test_empty_section_icon_and_no_new_key_safe(self):
        # CLI mock 形态可能没有 new_entries 键——toast_text 不许 KeyError
        title, body = dg.toast_text(
            {"overall": "ok", "ts": "2026-09-17 10:00:00",
             "sections": {"hotlist": "empty", "hn": "ok",
                          "releases": "ok", "toolbox": "ok"}})
        self.assertIn("热榜➖", body)
        self.assertNotIn("热榜新增", body)

    def test_body_capped(self):
        big = {"count": 1,
               "titles": ["很" * 300]}
        _, body = dg.toast_text(self._result(new_entries=big))
        self.assertLessEqual(len(body), dg._TOAST_BODY_MAX)


# ---------------------------------------------------------------------------
# 2d. CLI --toast 接线（尽力而为：失败/异常都不翻退出码）
# ---------------------------------------------------------------------------
class TestCliToast(unittest.TestCase):
    def _fake_result(self, overall="ok"):
        return {"markdown": "# 晨报\n", "overall": overall,
                "sections": {"hotlist": "ok", "hn": "ok",
                             "releases": "ok", "toolbox": "ok"},
                "ts": "2026-09-17 10:00:00"}

    def test_toast_called_once_and_exit0(self):
        with mock.patch.object(dg, "run_digest",
                               return_value=self._fake_result()), \
             mock.patch.object(dg, "send_toast",
                               return_value={"status": "sent"}) as st:
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(dg._main(["--toast"]), 0)
        st.assert_called_once()
        self.assertIn("晨报完成", st.call_args[0][0])

    def test_toast_fault_does_not_flip_exit_code(self):
        with mock.patch.object(dg, "run_digest",
                               return_value=self._fake_result()), \
             mock.patch.object(dg, "send_toast",
                               return_value={"status": "fault",
                                             "error": "x"}):
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                self.assertEqual(dg._main(["--toast"]), 0)
        self.assertIn("toast 弹窗失败", err.getvalue())
        self.assertIn("不翻码", err.getvalue())

    def test_toast_raise_swallowed(self):
        with mock.patch.object(dg, "run_digest",
                               return_value=self._fake_result()), \
             mock.patch.object(dg, "send_toast",
                               side_effect=RuntimeError("boom")):
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                self.assertEqual(dg._main(["--toast"]), 0)
        self.assertIn("toast 弹窗异常", err.getvalue())

    def test_no_flag_no_toast_call(self):
        with mock.patch.object(dg, "run_digest",
                               return_value=self._fake_result()), \
             mock.patch.object(dg, "send_toast") as st:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(dg._main([]), 0)
        st.assert_not_called()

    def test_help_mentions_toast_channel(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            with self.assertRaises(SystemExit):
                dg._main(["--help"])
        self.assertIn("--toast", out.getvalue())


# ---------------------------------------------------------------------------
# 3. digest_task register --toast（opt-in；默认形态与 v3.33 逐字节一致）
# ---------------------------------------------------------------------------
class TestRegistrarToast(unittest.TestCase):
    def _ok_proc(self):
        return _Proc(stdout="SUCCESS")

    def test_register_toast_appends_flag(self):
        seen = []

        def runner(argv, **kw):
            seen.append(argv)
            return self._ok_proc()

        self.assertEqual(task.register(runner=runner, toast=True), 0)
        tr = seen[0][seen[0].index("/TR") + 1]
        self.assertTrue(tr.endswith(" --toast"))
        self.assertLessEqual(len(tr), task.TR_MAX)

    def test_register_default_tr_unchanged_v333(self):
        seen = []

        def runner(argv, **kw):
            seen.append(argv)
            return self._ok_proc()

        self.assertEqual(task.register(runner=runner), 0)
        tr = seen[0][seen[0].index("/TR") + 1]
        self.assertNotIn("--toast", tr)              # 已注册任务零漂移

    def test_tr_cap_enforced_with_toast(self):
        long_py = "P:\\" + "x" * 300 + "pythonw.exe"
        with self.assertRaises(ValueError):
            task._tr_value(long_py, toast=True)

    def test_register_toast_message_mentions_notification(self):
        out = io.StringIO()

        def runner(argv, **kw):
            return self._ok_proc()

        with redirect_stdout(out):
            self.assertEqual(task.register(runner=runner, toast=True), 0)
        self.assertIn("Windows 通知", out.getvalue())


# ---------------------------------------------------------------------------
# 4. 版本锁（自 test_v3330 接管；v3.35 起精确锁移交 test_v3350，此处降
#    常青下限——v3.27→v3.28→v3.29→v3.30→v3.31→v3.33→v3.34 先例）
# ---------------------------------------------------------------------------
class TestVersionSyncV334(unittest.TestCase):
    def test_versions_evergreen(self):
        # v3.35 起精确锁移交 test_v3350，此处降常青下限（交接先例）：
        # 双 __version__ 同步本身不许破，只放开具体版本号
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        m = re.search(r'__version__ = "([^"]+)"', init_src)
        self.assertIsNotNone(m)
        ver = m.group(1)
        self.assertGreaterEqual(
            tuple(int(x) for x in ver.split(".")), (3, 34, 0))
        try:
            import mcp_server              # noqa: F401
            self.assertEqual(mcp_server.__version__, ver)
        except ImportError:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            self.assertIn(f'__version__ = "{ver}"', src)

    def test_changelog_and_readme_evergreen(self):
        # v3.35 起精确徽章/状态行锁移交 test_v3350，此处降常青：
        # 3.34 批次的 CHANGELOG 事实行（模板入库/--toast）永久在场
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("digest_config.example.json", changelog)
        self.assertIn("WScript.Shell", changelog)
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        # 测试徽章数 v3.35 起移交 test_v3350 精确锁，此处降常青单调下限：
        # 638（v3.34 基线 = 601 + 本批 37 钉），回归只许增不许缩
        m = re.search(r"tests-(\d+)%20passing", readme)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(int(m.group(1)),
                                601 + self._batch_pins())

    @staticmethod
    def _batch_pins():
        src = (REPO / "tests" / "test_v3340.py").read_text(encoding="utf-8")
        # 数真实 test 方法定义形态；本函数注释与正则字面量一律不得写成
        # 可被下方正则命中的形态（自引用虚增——v3.33 首跑抓到过）
        return len(re.findall(r"def (test_\w+)\(", src))

    def test_honest_doc_channel_evidence_chain(self):
        # 通道选型活体取证必须留在 docstring（架构原则 8：诚实文档）
        doc = dg.__doc__ or ""
        self.assertIn("BurntToast", doc)             # 拒因：要装模块
        self.assertIn("msg.exe", doc)                # 拒因：无超时/Home 缺失
        self.assertIn("QN_QUIET_TIME", doc)          # WinRT 双闸实锤之一
        self.assertIn("WScript.Shell Popup", doc)    # 采用通道
        self.assertIn("digest_config.example.json", doc)  # 模板层级在场
        # 例证常量承重值
        self.assertEqual(dg.EXAMPLE_CONFIG.name, "digest_config.example.json")
        self.assertEqual(dg.TOAST_TIMEOUT_S, 12)

    def test_config_semantics_doc_updated(self):
        doc = dg.__doc__ or ""
        self.assertIn("文件缺失", doc)               # 仅缺失走模板层
        self.assertIn("v3.34", doc)


if __name__ == "__main__":
    unittest.main()
