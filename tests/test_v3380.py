"""v3.38.0 回归：shift_log 行格式单一真源 tools/_logfmt.py。

三块内容（全部离线——tmp 文件 + 注入 now + 源码钉，零网络零弹窗）：
1. _logfmt 原语：stamp（固定 datetime 逐字节格式 / None=now）；make_line
   （ts 前 16 截断——供方源时间戳可带秒、body max_len 截断、行形态
   `[YYYY-MM-DD HH:MM] 内容` 逐字节钉）；ENTRY_RE/TIME_ONLY_RE 解析语义
   （组编号 / `\\s?` 容忍零或一空格 / 无前缀行不匹配）。
2. 四方收口钉：doctor 别名与 _logfmt 正则同一对象（is 身份，v3.36 四方
   同源钉同款）；digest._WATCH_LINE_RE 由 STAMP_RE 片段合成（pattern 逐
   字节等价）；源码钉三消费文件（doctor/digest/hotlist_watch）分钟级
   strftime 字面量清零 + 逐字节正则副本清零；hotlist_watch._logfmt 与
   tools 层同一模块。
3. 往返/跨解析器契约（写入端→解析端全离线走通）：
   hotlist_watch.render_log_line → doctor._shift_log_stats（tmp 班次
   日志，count/days/last/events 读数钉）；digest.render_log_line →
   doctor._shift_log_stats；hotlist_watch 行 → digest._WATCH_LINE_RE
   消费端（供方→消费方，v3.31 跨解析器钉延续）；digest 行 →
   ENTRY_RE 直解。+ 诚实文档钉（收口史随 _logfmt docstring 走）。
4. 版本锁 3.38.0（自 test_v3370 接管；v3.39 起精确锁交接 test_v3390，
   本文件降常青 >= 形态钉）+ CHANGELOG 历史/README 徽章形态。
"""
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
import doctor                       # noqa: E402
import digest as dg                 # noqa: E402
import hotlist_watch as hw          # noqa: E402


# ---------------------------------------------------------------------------
# 1. _logfmt 原语
# ---------------------------------------------------------------------------
class TestLogfmtPrimitives(unittest.TestCase):
    def test_stamp_fixed_and_default(self):
        # 固定 datetime：逐字节分钟级格式
        self.assertEqual(_logfmt.stamp(datetime(2026, 9, 17, 8, 30)),
                         "2026-09-17 08:30")
        self.assertEqual(_logfmt.stamp(datetime(2026, 9, 17, 8, 30, 59)),
                         "2026-09-17 08:30")     # 秒不进格式
        # 缺省=当前时刻：形态钉（None 与不传同走 now 分支）
        self.assertRegex(_logfmt.stamp(),
                         r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertRegex(_logfmt.stamp(None),
                         r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")

    def test_make_line_exact_form(self):
        line = _logfmt.make_line("2026-09-17 08:30", "digest: 热榜=ok", 500)
        self.assertEqual(line, "[2026-09-17 08:30] digest: 热榜=ok")

    def test_make_line_truncations(self):
        # 供方源时间戳可带秒（hotlist_watch 快照 ts 是 %H:%M:%S），截前 16
        self.assertTrue(_logfmt.make_line(
            "2026-09-17 08:30:59", "x", 500).startswith("[2026-09-17 08:30] "))
        # body 超 max_len 截断（班次流水不刷屏）
        self.assertEqual(_logfmt.make_line("2026-09-17 08:30", "abcdef", 3),
                         "[2026-09-17 08:30] abc")
        # 恰在上限不截
        self.assertEqual(_logfmt.make_line("2026-09-17 08:30", "abcdef", 6),
                         "[2026-09-17 08:30] abcdef")

    def test_entry_re_semantics(self):
        m = _logfmt.ENTRY_RE.match("[2026-09-17 08:30] hotlist_watch: diff")
        self.assertEqual((m.group(1), m.group(2), m.group(3)),
                         ("2026-09-17", "08:30", "hotlist_watch: diff"))
        # `\s?` 容忍零空格（人工手写行），也吃标准单空格
        m0 = _logfmt.ENTRY_RE.match("[2026-09-17 08:30]no-space body")
        self.assertEqual(m0.group(3), "no-space body")
        # 无前缀行 / 日期非法位數不匹配（坏行由解析方跳过）
        self.assertIsNone(_logfmt.ENTRY_RE.match("2026-09-17 08:30 无括号"))
        self.assertIsNone(_logfmt.ENTRY_RE.match("[2026-9-17 8:30] 短位数"))

    def test_time_only_re_semantics(self):
        m = _logfmt.TIME_ONLY_RE.match("[08:30] 值班当场省写日期")
        self.assertEqual((m.group(1), m.group(2)), ("08:30", "值班当场省写日期"))
        self.assertIsNone(_logfmt.TIME_ONLY_RE.match(
            "[2026-09-17 08:30] 完整前缀不是仅时间形态"))

    def test_stamp_re_fragment(self):
        # 片段本身不锚定（供合成），合成后与 v3.37 前消费端正则逐字节等价
        composed = re.compile(rf"^{_logfmt.STAMP_RE} (hotlist_watch: .*)$")
        self.assertEqual(
            composed.pattern,
            r"^\[(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}\] (hotlist_watch: .*)$")
        self.assertEqual(_logfmt.STAMP_FMT, "%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# 2. 四方收口钉
# ---------------------------------------------------------------------------
class TestFourWayConsolidation(unittest.TestCase):
    def test_doctor_aliases_same_object(self):
        # 旧引用名别名保零漂移：同一编译对象（is 身份，v3.36 四方同源同款钉）
        self.assertIs(doctor._SHIFT_ENTRY_RE, _logfmt.ENTRY_RE)
        self.assertIs(doctor._SHIFT_TIME_ONLY_RE, _logfmt.TIME_ONLY_RE)

    def test_digest_watch_line_re_composed(self):
        self.assertEqual(
            dg._WATCH_LINE_RE.pattern,
            r"^\[(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}\] (hotlist_watch: .*)$")

    def test_hotlist_watch_same_module(self):
        # 子目录消费方经父目录注入取到的与 tools 层是同一模块
        self.assertIs(hw._logfmt, _logfmt)

    def test_no_literal_copies_left(self):
        # 源码钉：三消费文件分钟级 strftime 字面量清零（watchdog 带秒形态
        # 与 google-bridge 敏感件均不在本批范围）+ 逐字节正则副本清零
        literals = ["%Y-%m-%d %H:%M\"", "%Y-%m-%d %H:%M'"]
        regex_copies = [r"re.compile(r\"^\[(\d{4}-\d{2}-\d{2})",
                        r"re.compile(r'^\[(\d{4}-\d{2}-\d{2})"]
        for rel in ("tools/doctor.py", "tools/digest.py",
                    "tools/chat-scraper/hotlist_watch.py"):
            src = (REPO / rel).read_text(encoding="utf-8")
            for lit in literals:
                self.assertNotIn(lit, src, rel)
            for pat in regex_copies:
                self.assertNotIn(pat, src, rel)


# ---------------------------------------------------------------------------
# 3. 往返 / 跨解析器契约（写入端 → 解析端，全离线 tmp）
# ---------------------------------------------------------------------------
def _watch_result(ts, status="ok", platforms=("bilibili", "weibo"),
                  new=2, gone=1, kept=17):
    return {"ts": ts, "status": status, "platforms": list(platforms),
            "summary": {"new": new, "gone": gone, "kept": kept},
            "alerts": [f"[NEW] [bilibili#1] 标题{ts} (https://b23.tv/x)"],
            "rows_valid": 20}


class TestRoundTrip(unittest.TestCase):
    def test_watch_line_to_doctor_stats(self):
        # 供方 hotlist_watch.render_log_line → 解析端 doctor._shift_log_stats
        now = datetime(2026, 9, 17, 10, 0)
        line = hw.render_log_line(_watch_result("2026-09-17 08:30:59"))
        self.assertTrue(line.startswith("[2026-09-17 08:30] hotlist_watch: "))
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "shift_log.md"
            log.write_text(line + "\n", encoding="utf-8")
            stats = doctor._shift_log_stats(str(log), now)
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["count"], 1)
        self.assertEqual(stats["days"], 1)
        self.assertEqual(stats["last"], ("2026-09-17 08:30", line[19:99]))

    def test_watch_line_events_counting(self):
        # 事件关键词字面计数走通（restart/处置关键词经 hotlist_watch 行体）
        now = datetime(2026, 9, 17, 10, 0)
        r = _watch_result("2026-09-17 09:00:00")
        r["status"] = "fault"
        r["error"] = "引擎重启后仍故障（restart 处置见快照）"
        line = hw.render_log_line(r)
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "shift_log.md"
            log.write_text(line + "\n", encoding="utf-8")
            stats = doctor._shift_log_stats(str(log), now)
        for k, n in stats["events"].items():
            self.assertEqual(n, line.count(k), f"关键词 {k} 计数漂移")

    def test_digest_line_to_doctor_stats(self):
        now = datetime(2026, 9, 17, 10, 0)
        line = dg.render_log_line(now, {"hotlist": "ok", "hn": "ok",
                                        "releases": "ok", "toolbox": "ok"})
        self.assertTrue(line.startswith("[2026-09-17 10:00] digest: "))
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "shift_log.md"
            log.write_text(line + "\n", encoding="utf-8")
            stats = doctor._shift_log_stats(str(log), now)
        self.assertEqual(stats["count"], 1)
        self.assertEqual(stats["last"][0], "2026-09-17 10:00")

    def test_watch_line_to_digest_consumer(self):
        # 供方→消费端跨解析器契约（v3.31 钉延续）：digest 取今日
        # hotlist_watch 行——正则形态匹配 + group(1) 日期过滤（collect_hotlist
        # 的 `m and m.group(1) == today_s` 双条件，后者在消费方代码）
        today = "2026-09-17"
        line = hw.render_log_line(_watch_result(f"{today} 08:30:59"))
        old = hw.render_log_line(_watch_result("2026-09-16 08:30:00"))
        m = dg._WATCH_LINE_RE.match(line.strip())
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), today)
        self.assertTrue(m.group(2).startswith("hotlist_watch: "))
        # 非今日行正则仍匹配（形态合规），但日期过滤将其剔除——双条件钉
        mo = dg._WATCH_LINE_RE.match(old.strip())
        self.assertIsNotNone(mo)
        self.assertNotEqual(mo.group(1), today)

    def test_digest_line_direct_entry_re(self):
        line = dg.render_log_line(datetime(2026, 9, 17, 10, 0),
                                  {"hotlist": "ok", "hn": "ok",
                                   "releases": "ok", "toolbox": "ok"})
        m = _logfmt.ENTRY_RE.match(line.strip())
        self.assertEqual(m.group(1), "2026-09-17")
        self.assertTrue(m.group(3).startswith("digest: "))

    def test_logfmt_doc_carries_history(self):
        # 诚实文档（架构原则 8）：收口史随 docstring 走
        doc = _logfmt.__doc__ or ""
        self.assertIn("四方", doc)            # 收口范围
        self.assertIn("副本", doc)            # 病灶（副本漂移）
        self.assertIn("别名", doc)            # 零漂移承诺
        self.assertIn("TIME_ONLY_RE", doc)    # 仅时间形态归属


# ---------------------------------------------------------------------------
# 4. 版本锁（自 test_v3370 接管；v3.39 起精确锁交接 test_v3390，本钉降常青）
# ---------------------------------------------------------------------------
class TestVersionSyncV338(unittest.TestCase):
    def test_versions_3380(self):
        # v3.39 起精确版本锁交接 test_v3390，本钉降常青（>= 3.38，
        # v3.33->v3.34 降常青先例）
        self.assertGreaterEqual(
            tuple(int(x) for x in dg.__version__.split(".")), (3, 38, 0))
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        m = re.search(r'__version__ = "(\d+)\.(\d+)\.(\d+)"', init_src)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(tuple(map(int, m.groups())), (3, 38, 0))
        self.assertRegex(init_src, r"chat-scraper v3\.\d+\.\d+")
        try:
            import mcp_server              # noqa: F401
            self.assertGreaterEqual(
                tuple(int(x) for x in mcp_server.__version__.split(".")),
                (3, 38, 0))
        except ImportError:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            self.assertIsNotNone(
                re.search(r'__version__ = "3\.\d+\.\d+"', src))

    def test_changelog_and_readme_3380(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.38.0] - 2026-09-17", changelog)   # 历史段永在
        self.assertIn("_logfmt", changelog)
        self.assertIn("toast.py", changelog)     # toast 取证结论入账
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        # v3.39 起精确版本徽章交接 test_v3390；本钉降常青：只钉徽章形态存在
        self.assertIsNotNone(re.search(r"release-v3\.\d+\.\d+", readme))
        self.assertIsNotNone(re.search(r"tests-\d+%20passing", readme))


if __name__ == "__main__":
    unittest.main()
