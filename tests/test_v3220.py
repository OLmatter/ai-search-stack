"""v3.22.0 回归：stop_wake append-only 决策日志（消除 v3.21 声明的观察
盲区）+ 收工必写 shift_log 纪律固化（含 v3.19/v3.20 补记）+ 版本锁 3.22.0。

三块内容（全部离线，零真实请求、零浏览器、不碰真实 ~/.zcode/worker_queue.json
与真实 ~/.zcode/stop_wake_decisions.jsonl——所有文件 IO 走临时目录）：
1. stop_wake 决策日志：main 每次触发追加一行 JSONL（ts/decision/reason）
   到 ~/.zcode/stop_wake_decisions.jsonl（仓库外，gitignore 不适用）；
   block 记完整注入文本、pass 记归因标签；append-only（只追加不改写）；
   写日志任何异常吞掉（从属职责绝不影响决策与退出码）；should_block
   v3.19 语义不变（兼容层）。
2. 收工必写 shift_log：CONTRIBUTING.md 版本发布检查点固化 + v3.19/v3.20
   历史条目已补记（标注补记，时间戳格式保持 doctor 可解析）。
3. 版本锁 3.22.0（mcp_server + chat-scraper __init__ 双同步）+ CHANGELOG
   3.22.0 小节存在（test_v3210 精确锁同步降常青下限，v3.17→v3.19 先例）。
"""
import io
import json
import os
import pathlib
import re
import sys
import tempfile
import unittest
from datetime import datetime

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "chat-scraper"))
sys.path.insert(0, str(REPO / "tools" / "chat-scraper" / "hooks"))

import worker_queue as wq          # noqa: E402
import stop_wake                   # noqa: E402

try:
    import mcp_server              # noqa: E402
except ImportError:                # mcp SDK 未安装（部分 CI）——版本锁降级源码断言
    mcp_server = None


# ---- 1. 决策日志：append-only JSONL ---------------------------------------------------


class TestDecisionLog(unittest.TestCase):
    """_log_decision：一行一 JSON（ts/decision/reason），只追加，异常吞掉。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = os.path.join(self.tmp.name, "stop_wake_decisions.jsonl")

    def _lines(self):
        with open(self.log, encoding="utf-8") as f:
            return [json.loads(ln) for ln in f.read().splitlines()]

    def test_block_decision_logged_with_iso_ts(self):
        stop_wake._log_decision(True, "[派工队列] 拦截文本", log_path=self.log)
        (rec,) = self._lines()
        self.assertEqual(rec["decision"], "block")
        self.assertEqual(rec["reason"], "[派工队列] 拦截文本")
        ts = datetime.fromisoformat(rec["ts"])      # ISO 可解析
        self.assertIsNotNone(ts.tzinfo)             # 带时区（本地时间可追溯）

    def test_pass_decision_logged(self):
        stop_wake._log_decision(False, "valid_claim", log_path=self.log)
        (rec,) = self._lines()
        self.assertEqual(rec["decision"], "pass")
        self.assertEqual(rec["reason"], "valid_claim")

    def test_append_only_two_calls_keep_history(self):
        # append-only 铁律：第二次触发只追加，绝不改写/截断已有行
        stop_wake._log_decision(True, "第一触发", log_path=self.log)
        with open(self.log, encoding="utf-8") as f:
            first = f.read()
        stop_wake._log_decision(False, "第二触发", log_path=self.log)
        with open(self.log, encoding="utf-8") as f:
            second = f.read()
        self.assertTrue(second.startswith(first))   # 历史字节原样保留
        recs = self._lines()
        self.assertEqual([r["reason"] for r in recs], ["第一触发", "第二触发"])
        self.assertEqual([r["decision"] for r in recs], ["block", "pass"])

    def test_log_failure_swallowed(self):
        # 从属职责：日志路径不可写（目录不存在模拟磁盘/权限故障）→
        # 不抛异常（决策与退出码不受影响——hook 主职责优先）
        bad = os.path.join(self.tmp.name, "no", "such", "dir", "x.jsonl")
        stop_wake._log_decision(True, "写不进去也不能炸", log_path=bad)
        self.assertFalse(os.path.exists(bad))

    def test_default_log_path_resolved_at_call_time(self):
        # None=运行期取模块级 LOG（main 路径），monkeypatch 可见——
        # 离线测试由此不污染真实 ~/.zcode/stop_wake_decisions.jsonl
        old = stop_wake.LOG
        stop_wake.LOG = self.log
        try:
            stop_wake._log_decision(False, "no_queue")
        finally:
            stop_wake.LOG = old
        (rec,) = self._lines()
        self.assertEqual(rec["reason"], "no_queue")


# ---- 2. _decide 归因标签 + should_block 兼容层 ----------------------------------------


class TestDecideAttribution(unittest.TestCase):
    """_decide：pass 带归因标签（no_queue/empty_queue/module_unreachable/
    valid_claim），block 带完整注入文本。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.queue = os.path.join(self.tmp.name, "worker_queue.json")

    def _write_queue(self, instructions):
        with open(self.queue, "w", encoding="utf-8") as f:
            json.dump({"instructions": instructions}, f)

    def test_no_queue_label(self):
        self.assertEqual(stop_wake._decide(self.queue, wq=wq),
                         (False, "no_queue"))

    def test_empty_queue_label(self):
        self._write_queue("")
        self.assertEqual(stop_wake._decide(self.queue, wq=wq),
                         (False, "empty_queue"))

    def test_corrupt_queue_reads_as_empty_label(self):
        # 损坏队列如实视为无活（v3.19 语义）→ 归因 empty_queue
        with open(self.queue, "w", encoding="utf-8") as f:
            f.write("{broken")
        self.assertEqual(stop_wake._decide(self.queue, wq=wq),
                         (False, "empty_queue"))

    def test_module_unreachable_label(self):
        self._write_queue("有活但探测失败")
        self.assertEqual(stop_wake._decide(self.queue, wq=None),
                         (False, "module_unreachable"))

    def test_valid_claim_label(self):
        self._write_queue("已有主人的活")
        wq.claim(self.queue, worker_id="worker-A")
        self.assertEqual(stop_wake._decide(self.queue, wq=wq),
                         (False, "valid_claim"))

    def test_unclaimed_block_full_text(self):
        self._write_queue("无人认领的活")
        block, reason = stop_wake._decide(self.queue, wq=wq)
        self.assertTrue(block)
        self.assertIn("无人认领的活", reason)       # 完整注入文本（含 instructions）
        self.assertIn("acquire()", reason)          # 强制条款原样保留


class TestShouldBlockCompat(unittest.TestCase):
    """should_block 兼容层：v3.19 对外语义逐字不变（None=放行/str=block）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.queue = os.path.join(self.tmp.name, "worker_queue.json")

    def _write_queue(self, instructions):
        with open(self.queue, "w", encoding="utf-8") as f:
            json.dump({"instructions": instructions}, f)

    def test_pass_cases_return_none(self):
        self.assertIsNone(stop_wake.should_block(self.queue, wq=wq))
        self._write_queue("")
        self.assertIsNone(stop_wake.should_block(self.queue, wq=wq))
        self._write_queue("活有主")
        wq.claim(self.queue, worker_id="worker-A")
        self.assertIsNone(stop_wake.should_block(self.queue, wq=wq))

    def test_block_case_returns_str_with_clause(self):
        self._write_queue("无人认领的活")
        r = stop_wake.should_block(self.queue, wq=wq)
        self.assertIsInstance(r, str)
        self.assertIn("acquire()", r)


# ---- 3. main 端到端：决策与日志同圈落账 ------------------------------------------------


class TestMainDecisionAndLog(unittest.TestCase):
    """main()：每次触发一条日志；block 打 stdout JSON、pass 静默 exit 0。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.queue = os.path.join(self.tmp.name, "worker_queue.json")
        self.log = os.path.join(self.tmp.name, "decisions.jsonl")
        self.old_queue, self.old_log = stop_wake.QUEUE, stop_wake.LOG
        stop_wake.QUEUE, stop_wake.LOG = self.queue, self.log

    def tearDown(self):
        stop_wake.QUEUE, stop_wake.LOG = self.old_queue, self.old_log

    def _run_main(self):
        """跑 main()，返回 (stdout 文本, 退出码)。"""
        buf = io.StringIO()
        old_out = sys.stdout
        sys.stdout = buf
        try:
            stop_wake.main()
        except SystemExit as e:
            code = e.code
        finally:
            sys.stdout = old_out
        return buf.getvalue(), code

    def _log_lines(self):
        with open(self.log, encoding="utf-8") as f:
            return [json.loads(ln) for ln in f.read().splitlines()]

    def test_block_writes_stdout_and_log(self):
        with open(self.queue, "w", encoding="utf-8") as f:
            json.dump({"instructions": "v3.22 决策日志实战钉"}, f)
        out, code = self._run_main()
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["decision"], "block")
        self.assertIn("v3.22 决策日志实战钉", payload["reason"])
        (rec,) = self._log_lines()                  # 决策与日志同圈落账
        self.assertEqual(rec["decision"], "block")
        self.assertIn("v3.22 决策日志实战钉", rec["reason"])

    def test_pass_writes_log_only_no_stdout(self):
        with open(self.queue, "w", encoding="utf-8") as f:
            json.dump({"instructions": "活有主"}, f)
        wq.claim(self.queue, worker_id="worker-A")
        out, code = self._run_main()
        self.assertEqual(code, 0)
        self.assertEqual(out, "")                   # 放行不打 stdout
        (rec,) = self._log_lines()
        self.assertEqual(rec["decision"], "pass")
        self.assertEqual(rec["reason"], "valid_claim")


# ---- 4. 收工必写 shift_log 纪律固化 ----------------------------------------------------


class TestShiftLogDiscipline(unittest.TestCase):
    """收工必写 shift_log：CONTRIBUTING 检查点 + v3.19/v3.20 补记在案。

    shift_log.md 在 state/（.gitignore 忽略的运行态文件，机器本地）——
    内容钉按 doctor 同款语义 skipUnless 文件存在（缺文件=可选观测未启用
    不是故障，fresh clone 不误报）；CONTRIBUTING 检查点钉无条件（真源）。
    """

    @classmethod
    def setUpClass(cls):
        cls.shift_log = (REPO / "tools" / "chat-scraper" / "state"
                         / "shift_log.md")

    def test_contributing_has_shift_log_checkpoint(self):
        src = (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertIn("收工必写 shift_log", src)
        self.assertIn("shift_log.md", src)
        self.assertIn("补记", src)                  # 漏写必须标注补记，无声补=伪造实时

    @unittest.skipUnless(
        (REPO / "tools" / "chat-scraper" / "state" / "shift_log.md").exists(),
        "shift_log.md 不存在（可选观测未启用，doctor 同语义不判故障）")
    def test_shift_log_backfills_v319_v320_marked(self):
        log = self.shift_log.read_text(encoding="utf-8")
        # 补记条目：标注「补记」，时间戳格式 [YYYY-MM-DD HH:MM]（doctor
        # _shift_log_stats 可解析，坏行不计数）
        for ver, token in (("v3.19", "acquire"), ("v3.20", "ddg")):
            m = re.search(
                rf"\[\d{{4}}-\d{{2}}-\d{{2}} \d{{2}}:\d{{2}}\][^\n]*{ver}"
                rf"[^\n]*补记[^\n]*{token}", log)
            self.assertIsNotNone(m, f"{ver} 补记条目缺失或不含 {token}")

    @unittest.skipUnless(
        (REPO / "tools" / "chat-scraper" / "state" / "shift_log.md").exists(),
        "shift_log.md 不存在（可选观测未启用，doctor 同语义不判故障）")
    def test_shift_log_v322_entry_present(self):
        log = self.shift_log.read_text(encoding="utf-8")
        self.assertIn("v3.22", log)
        self.assertIn("stop_wake_decisions.jsonl", log)


# ---- 5. 版本锁 3.22.0 -------------------------------------------------------------------


class TestVersionSyncV322(unittest.TestCase):
    def test_versions_3220(self):
        # 精确锁当前版本（先例：上一版 test_v3210 精确锁同步降常青）
        if mcp_server is None:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            ver = re.search(r'__version__ = "([^"]+)"', src).group(1)
        else:
            ver = mcp_server.__version__
        self.assertEqual(ver, "3.22.0")
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        self.assertIn(f'__version__ = "{ver}"', init_src)
        self.assertIn(f"chat-scraper v{ver}", init_src)   # docstring 首行同步

    def test_changelog_has_3220(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.22.0] - 2026-09-16", changelog)
        self.assertIn("stop_wake_decisions.jsonl", changelog)
        self.assertIn("收工必写 shift_log", changelog)

    def test_hook_source_pins_decision_log(self):
        # 决策日志写进 hook 真源（v3.19 的 repo-canonical pin 延续）
        src = (REPO / "tools" / "chat-scraper" / "hooks" / "stop_wake.py"
               ).read_text(encoding="utf-8")
        for token in ("stop_wake_decisions.jsonl", "_log_decision",
                      "append-only", "_decide"):
            self.assertIn(token, src)


if __name__ == "__main__":
    unittest.main()
