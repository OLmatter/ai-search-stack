"""v3.39.0 回归：parse_today_lines() 消费端语义下沉 + worker_queue 边界审计。

三块内容（全部离线——tmp 文件 + 源码钉，零网络零弹窗）：
1. _logfmt.parse_today_lines() 原语：「解析 + 今日过滤」双条件语义自
   digest 消费端下沉单一真源（v3.38 收口线的下一环，上轮任务清单明记
   项）：今日行收 group(2)、昨日形态合规行剔除、strip 容忍、顺序保持、
   前缀留在消费方合成（通用性——任意 STAMP_RE 合成正则都可用）。
2. digest 消费端接线：collect_hotlist 端到端（tmp shift_log 今日行进
   watch_lines / 非今日剔除 / 截断展示策略留在消费端 / 日志缺失空列表
   原行为不变）+ 源码钉（内联双条件消费实现清零、委托 parse_today_lines）
   + v3.38 旧钉延续自证（_WATCH_LINE_RE pattern 逐字节不变）。
3. worker_queue 双队列语义审计判词入账（取证=现状即稳态）：机制-数据
   同名是配对不是混用（worker_queue.py docstring 钉 ~/.zcode/worker_queue.json
   + stop_wake 真源强制条款「禁止绕过入口直接读」+ 部署副本一致性——
   部署副本存在时才比对，跨机可跑）。+ 版本锁 3.39.0（自 test_v3380
   接管精确锁）+ CHANGELOG/README 徽章。
"""
import os
import pathlib
import re
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "chat-scraper"))
sys.path.insert(0, str(REPO / "tools"))

import _logfmt                      # noqa: E402
import digest as dg                 # noqa: E402
import hotlist_watch as hw          # noqa: E402


def _watch_line(ts, body=None):
    # 供方真实形态：body=None 走 hotlist_watch.render_log_line 完整路径
    # （默认 diff 摘要体）；指定 body 走 _logfmt.make_line 等价形态
    if body is None:
        return hw.render_log_line(
            {"ts": ts, "status": "ok", "platforms": ["bilibili"],
             "summary": {"new": 2, "gone": 1, "kept": 17},
             "alerts": [], "rows_valid": 20})
    return _logfmt.make_line(ts, f"hotlist_watch: {body}", 500)


# ---------------------------------------------------------------------------
# 1. parse_today_lines 原语（双条件语义下沉单一真源）
# ---------------------------------------------------------------------------
class TestParseTodayLines(unittest.TestCase):
    LINE_RE = re.compile(rf"^{_logfmt.STAMP_RE} (hotlist_watch: .*)$")

    def test_double_condition_today_kept_yesterday_dropped(self):
        # 双条件钉迁移：形态合规 且 日期==today 才收（v3.31 跨解析器钉 /
        # v3.38 test_watch_line_to_digest_consumer 钉的语义随函数收口）
        today = "2026-09-17"
        text = "\n".join([
            _watch_line(f"{today} 08:30:59"),
            _watch_line("2026-09-16 08:30:00"),   # 昨日：形态合规但非今日
            _watch_line(f"{today} 12:05:00", "新增 3"),
        ])
        got = _logfmt.parse_today_lines(text, today, self.LINE_RE)
        self.assertEqual(len(got), 2)             # 昨日剔除、顺序保持文件序
        for s in got:
            self.assertTrue(s.startswith("hotlist_watch: "))

    def test_strip_and_unprefixed_and_bad_rows(self):
        today = "2026-09-17"
        text = "\n".join([
            f"  {_watch_line(f'{today} 08:30:59')}  ",   # 行首尾空白容忍
            "2026-09-17 08:31 无括号前缀行",             # 无前缀：不匹配
            "[2026-9-17 08:32] hotlist_watch: 短位数日期",  # 坏形态：不匹配
            f"[{today} 08:33] digest: 别前缀机器行",      # 前缀不符：不匹配
        ])
        got = _logfmt.parse_today_lines(text, today, self.LINE_RE)
        self.assertEqual(len(got), 1)             # 仅供方真实行存活
        self.assertTrue(got[0].startswith("hotlist_watch: diff（bilibili）"))

    def test_empty_text_no_lines(self):
        self.assertEqual(_logfmt.parse_today_lines("", "2026-09-17",
                                                   self.LINE_RE), [])
        self.assertEqual(_logfmt.parse_today_lines("no lines at all",
                                                   "2026-09-17",
                                                   self.LINE_RE), [])

    def test_generic_line_re_prefix_stays_with_consumer(self):
        # 通用性：前缀留在消费方合成——digest 班次行正则同走一函数
        digest_re = re.compile(rf"^{_logfmt.STAMP_RE} (digest: .*)$")
        text = "[2026-09-17 10:00] digest: 热榜=ok HN=ok\n" \
               "[2026-09-16 10:00] digest: 昨日行"
        got = _logfmt.parse_today_lines(text, "2026-09-17", digest_re)
        self.assertEqual(got, ["digest: 热榜=ok HN=ok"])


# ---------------------------------------------------------------------------
# 2. digest 消费端接线（行为不变证据 + 源码钉）
# ---------------------------------------------------------------------------
class TestDigestConsumerWiring(unittest.TestCase):
    def test_collect_hotlist_end_to_end(self):
        # 端到端：tmp shift_log 今日+昨日 → watch_lines 只含今日；截断
        # _DIFF_LINE_MAX 展示策略留在消费端
        today = "2026-09-17"
        long_body = "x" * 600
        text = "\n".join([
            _watch_line(f"{today} 08:30:59"),
            _watch_line("2026-09-16 20:00:00"),
            _logfmt.make_line(f"{today} 09:00:00",
                              f"hotlist_watch: {long_body}", 500),
        ])
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "shift_log.md"
            log.write_text(text + "\n", encoding="utf-8")
            r = dg.fetch_hotlist(
                today=datetime(2026, 9, 17, 10, 0), shift_log=str(log),
                snapshots_dir=str(Path(td) / "no_snaps"))
        self.assertEqual(len(r["watch_lines"]), 2)        # 昨日剔除
        self.assertTrue(r["watch_lines"][0].startswith("hotlist_watch: "))
        self.assertTrue(all(len(s) <= dg._DIFF_LINE_MAX
                            for s in r["watch_lines"]))   # 截断仍在消费端

    def test_collect_hotlist_log_missing_empty_lines(self):
        # 日志缺失：watch_lines == [] 原行为不变（v3.31 语义，不算 fault）
        with tempfile.TemporaryDirectory() as td:
            r = dg.fetch_hotlist(
                today=datetime(2026, 9, 17, 10, 0),
                shift_log=str(Path(td) / "no_such.log"),
                snapshots_dir=str(Path(td) / "no_snaps"))
        self.assertEqual(r["watch_lines"], [])

    def test_digest_source_delegates_not_inline(self):
        # 源码钉：digest.py 内联双条件消费实现清零（`m.group(1) ==` 形态
        # 不再出现），委托 _logfmt.parse_today_lines
        src = (REPO / "tools" / "digest.py").read_text(encoding="utf-8")
        self.assertNotIn("m.group(1) ==", src)
        self.assertNotIn("_WATCH_LINE_RE.match", src)
        self.assertIn("_logfmt.parse_today_lines", src)
        # 消费端实现体与 _logfmt 原语同一语义（行级契约单一真源）：
        # digest.py 不再有 splitlines 行循环消费形态
        self.assertNotIn("for ln in text.splitlines()", src)

    def test_v338_watch_line_pin_unchanged(self):
        # v3.38 旧钉延续自证：下沉不碰正则——pattern 逐字节等价 +
        # STAMP_RE 片段合成同源
        self.assertEqual(
            dg._WATCH_LINE_RE.pattern,
            r"^\[(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}\] (hotlist_watch: .*)$")
        self.assertEqual(dg._WATCH_LINE_RE.pattern,
                         rf"^{_logfmt.STAMP_RE} (hotlist_watch: .*)$")

    def test_logfmt_doc_carries_sink_history(self):
        # 诚实文档：下沉史随 docstring 走（v3.38 收口 + v3.39 下沉）
        doc = _logfmt.__doc__ or ""
        self.assertIn("v3.39", doc)
        self.assertIn("parse_today_lines", doc)

    def test_compile_zero_syntax_warning_repo_wide(self):
        # 顺手修的自动检查（v3.38 潜伏病：_logfmt docstring 裸 `\s?` 非
        # raw 前缀在 compile 期报 SyntaxWarning，-W error 下即
        # SyntaxError——全 tools 源码 compile 期零警告，防再生；
        # google-bridge 敏感件不在范围）
        import warnings as _w
        for p in sorted((REPO / "tools").rglob("*.py")):
            if "__pycache__" in str(p) or "google-bridge" in str(p):
                continue
            with _w.catch_warnings(record=True) as ws:
                _w.simplefilter("always")
                compile(p.read_text(encoding="utf-8"), str(p), "exec")
            self.assertEqual(
                [str(x.message) for x in ws], [], str(p))


# ---------------------------------------------------------------------------
# 3. worker_queue 双队列语义审计判词入账 + 版本锁
# ---------------------------------------------------------------------------
class TestWorkerQueueBoundaryAudit(unittest.TestCase):
    def test_module_doc_pins_data_file_pairing(self):
        # 审计判词=现状即稳态的证据链钉①：机制层 docstring 钉数据文件
        # 对应关系（同名是机制-数据配对，扩展名区分，不混用）
        src = (REPO / "tools" / "chat-scraper" / "worker_queue.py"
               ).read_text(encoding="utf-8")
        self.assertIn("~/.zcode/worker_queue.json", src)
        self.assertIn("O_EXCL", src)          # 硬互斥原语仍在位

    def test_stop_wake_forced_entry_clause(self):
        # 证据链钉②：hooks 真源强制条款——领活唯一入口 acquire()，禁止
        # 绕过入口直接读 worker_queue.json（三轮互踩实证条款在位）
        src = (REPO / "tools" / "chat-scraper" / "hooks" / "stop_wake.py"
               ).read_text(encoding="utf-8")
        self.assertIn("禁止绕过入口直接读", src)
        self.assertIn("worker_queue.acquire()", src)
        self.assertIn('.zcode", "worker_queue.json"', src)

    def test_deploy_copy_matches_repo_source(self):
        # 证据链钉③：部署副本与仓库真源字节级一致（v3.20 核验线延续；
        # 副本不存在=非部署机，跳过不装绿——跨机可跑）
        repo_src = REPO / "tools" / "chat-scraper" / "hooks" / "stop_wake.py"
        deploy = Path(os.path.expanduser("~")) / ".zcode" / "hooks" / \
            "stop_wake.py"
        if not deploy.is_file():
            self.skipTest("非部署机（~/.zcode/hooks/stop_wake.py 缺失）")
        self.assertEqual(repo_src.read_bytes(), deploy.read_bytes())

    def test_only_one_queue_writer_in_repo(self):
        # 证据链钉④：仓库内直接以字面量拼 ~/.zcode/worker_queue.json 路径
        # 的只有 stop_wake.py（钩子只读探活）；机制层写路径全部经
        # worker_queue.py 原语——单一写方成立（防混用静默再生）
        hits = []
        for p in (REPO / "tools").rglob("*.py"):
            if "__pycache__" in str(p):
                continue
            s = p.read_text(encoding="utf-8")
            if '".zcode", "worker_queue.json"' in s:
                hits.append(p.name)
        self.assertEqual(sorted(hits), ["stop_wake.py"])


class TestVersionSyncV339(unittest.TestCase):
    def test_versions_3390(self):
        # 自 test_v3380 接管过精确锁；v3.40 起精确锁交接 test_v3400，
        # 本钉降常青（>= 3.39，v3.33->v3.34->…降常青交接链延续）
        self.assertGreaterEqual(
            tuple(int(x) for x in dg.__version__.split(".")), (3, 39, 0))
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        m = re.search(r'__version__ = "(\d+)\.(\d+)\.(\d+)"', init_src)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(tuple(map(int, m.groups())), (3, 39, 0))
        self.assertRegex(init_src, r"chat-scraper v3\.\d+\.\d+")
        try:
            import mcp_server              # noqa: F401
            self.assertGreaterEqual(
                tuple(int(x) for x in mcp_server.__version__.split(".")),
                (3, 39, 0))
        except ImportError:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            m2 = re.search(r'__version__ = "(\d+)\.(\d+)\.(\d+)"', src)
            self.assertIsNotNone(m2)
            self.assertGreaterEqual(tuple(map(int, m2.groups())), (3, 39, 0))

    def test_changelog_and_readme_3390(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.39.0] - 2026-09-17", changelog)
        self.assertIn("parse_today_lines", changelog)
        self.assertIn("worker_queue", changelog)   # 审计判词入账
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        # v3.40 起徽章/状态行精确值交接 test_v3400，此处降常青形态钉
        self.assertRegex(readme, r"release-v\d+\.\d+\.\d+")
        self.assertRegex(readme, r"v3\.\d+\.\d+（2026-09-17）")
        # 测试徽章数精确锁随 v3.40 交接 test_v3400（746+本批钉），此处
        # 只钉形态（防止徽章漂移消失）
        self.assertRegex(readme, r"tests-\d+%20passing")


if __name__ == "__main__":
    unittest.main()
