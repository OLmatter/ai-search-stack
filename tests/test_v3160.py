"""v3.16.0 回归：doctor 值班巡检趋势检查（shift_log 近 7 天汇总）+
SearXNG 禁用引擎恢复观察钉子（v3.15 禁用三引擎维持禁用）。

三块内容（全部离线，零真实请求、零浏览器）：
1. doctor._shift_log_stats / check_shift_log：近 7 天记录条数/覆盖天数/
   疑似异常项数；[HH:MM] 省日期行继承上一条带日期条目的日期；坏行/
   非法日期/头部无日期可继承跳过不计数；缺文件/近 7 天零记录 →
   RuntimeError（optional ⚠️ 不判核心故障）；窗口过滤（第 8 天前不计）；
   异常输出声明"关键词启发式"且 >3 条截断展示。
2. SearXNG settings.yml 恢复观察钉子：三引擎 disabled 条目维持（回滚
   实测复发后恢复禁用）、v3.16 观察结论与两关再评估方法在文件里、
   v3.15 的恢复方法注释保留。
3. 版本锁 3.16.0（mcp_server + chat-scraper __init__ 精确锁）+ main()
   注册钉子 + mcp doctor 描述 8 项钉子。

实测证据（判词用，不入测试）：2026-09-16 enabled_engines 单发探活
brave 21 / duckduckgo 21 / startpage 20 条均 unresponsive 空；回滚启用
+ restart 后 doctor 聚合搜索三引擎即全部复发（too many requests /
CAPTCHA / parsing error）——单发探活通过 ≠ 可回滚，维持禁用。
"""
import datetime
import os
import pathlib
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
for d in ("", "chat-scraper"):
    sys.path.insert(0, str(REPO / "tools" / d))

import doctor as doctor_mod   # noqa: E402  (tools/doctor.py)

try:
    sys.path.insert(0, str(REPO / "tools"))
    import mcp_server
except ImportError:  # mcp SDK 未安装（部分 CI）——MCP 块整体跳过
    mcp_server = None

# 固定"现在"：2026-09-16 20:10（窗口 = 09-10 .. 09-16 共 7 个自然日）
_NOW = datetime.datetime(2026, 9, 16, 20, 10)


# ---- 1. shift_log 统计与检查 ----------------------------------------------------


class TestShiftLogStats(unittest.TestCase):
    """_shift_log_stats：窗口/继承/坏行/缺文件。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = os.path.join(self.tmp.name, "shift_log.md")

    def _write(self, *lines):
        with open(self.log, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def test_normal_count_days_anomalies(self):
        self._write(
            "[2026-09-15 08:30] 班次：探活 valid，无残留",
            "[09:00] 值班巡检：双服务存活持续",          # 继承 09-15
            "[2026-09-16 08:48] 正式班次 doctor：GitHub ❌ 403 限流",
        )
        count, days, anomalies = doctor_mod._shift_log_stats(self.log, _NOW)
        self.assertEqual((count, days), (3, 2))
        self.assertEqual(len(anomalies), 1)
        self.assertIn("403", anomalies[0])
        self.assertTrue(anomalies[0].startswith("2026-09-16"))

    def test_window_excludes_8th_day_back(self):
        self._write(
            "[2026-09-09 23:00] 窗口外一天：不算",
            "[2026-09-10 00:01] 窗口第一天：算",
            "[2026-09-16 20:00] 今天：算",
        )
        count, days, anomalies = doctor_mod._shift_log_stats(self.log, _NOW)
        self.assertEqual((count, days), (2, 2))
        self.assertEqual(anomalies, [])

    def test_bad_lines_skipped(self):
        # 无 [ 前缀行 / 非法日期 / 头部无日期可继承的 [HH:MM] 行：全跳过
        self._write(
            "这是一行没有时间戳的流水",
            "[2026-13-99 25:61] 非法日期时间",
            "[08:00] 头部无日期可继承",
            "[2026-09-16 09:00] 合法条目：探活 valid",
            "尾随脏行",
        )
        count, days, anomalies = doctor_mod._shift_log_stats(self.log, _NOW)
        self.assertEqual((count, days), (1, 1))
        self.assertEqual(anomalies, [])

    def test_missing_file_returns_none(self):
        self.assertIsNone(
            doctor_mod._shift_log_stats(os.path.join(self.tmp.name, "nope.md"),
                                        _NOW))

    def test_window_days_parameter(self):
        self._write(
            "[2026-09-01 08:00] 很早的条目：探活 valid",
            "[2026-09-16 08:00] 今天：探活 valid",
        )
        count, _, _ = doctor_mod._shift_log_stats(self.log, _NOW, window_days=30)
        self.assertEqual(count, 2)


class TestCheckShiftLog(unittest.TestCase):
    """check_shift_log：缺文件/零记录报警，正常统计带启发式声明。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = os.path.join(self.tmp.name, "shift_log.md")
        self.addCleanup(setattr, doctor_mod, "SHIFT_LOG_PATH",
                        doctor_mod.SHIFT_LOG_PATH)
        doctor_mod.SHIFT_LOG_PATH = self.log

    def _write(self, *lines):
        with open(self.log, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def test_missing_file_raises(self):
        with self.assertRaisesRegex(RuntimeError, "不存在"):
            doctor_mod.check_shift_log()

    def test_zero_records_in_window_raises(self):
        self._write("[2026-08-01 08:00] 很久以前的记录")
        with self.assertRaisesRegex(RuntimeError, "无班次记录"):
            doctor_mod.check_shift_log()

    def test_normal_with_anomalies_declares_heuristic_and_truncates(self):
        self._write(*[f"[2026-09-16 0{i}:00] 异常记录第{i}项：CAPTCHA"
                      for i in range(1, 6)])
        detail = doctor_mod.check_shift_log()
        self.assertIn("近 7 天记录 5 条", detail)
        self.assertIn("覆盖 1 天", detail)
        self.assertIn("疑似异常 5 项", detail)
        self.assertIn("关键词启发式", detail)      # 误报风险如实声明
        self.assertEqual(detail.count("异常记录第"), 3)   # 只展示前 3 条
        self.assertIn("等 5 项", detail)

    def test_normal_without_anomalies(self):
        self._write("[2026-09-16 08:00] 班次：探活 valid，无残留")
        detail = doctor_mod.check_shift_log()
        self.assertIn("近 7 天记录 1 条", detail)
        self.assertIn("疑似异常 0 项", detail)
        self.assertNotIn("启发式", detail)          # 无异常无需声明

    def test_real_repo_shift_log_readable(self):
        # 真实仓库日志可统计（统计口径对真实格式不炸；不断言具体数字——
        # shift_log 是活的，数字随值班变化）。显式用真实路径：本测试类
        # setUp 已把 SHIFT_LOG_PATH 全局 patch 到 tmp（v3.15 默认参数
        # 教训的反向应用——此处要的就是真实文件）
        real_log = (REPO / "tools" / "chat-scraper" / "state"
                    / "shift_log.md")
        if not real_log.exists():
            self.skipTest("真实仓库无 shift_log.md（全新 checkout）")
        stats = doctor_mod._shift_log_stats(str(real_log), _NOW)
        self.assertIsNotNone(stats)
        count, days, _ = stats
        self.assertIsInstance(count, int)
        self.assertIsInstance(days, int)


class TestDoctorRegistration(unittest.TestCase):
    """main() 注册钉子：第 8 项检查，optional。"""

    def test_shift_log_check_registered_optional(self):
        src = (REPO / "tools" / "doctor.py").read_text(encoding="utf-8")
        self.assertIn('_check("值班巡检趋势", check_shift_log, optional=True)',
                      src)
        self.assertIn("8 = 5 网络探活 + 3 本地状态", src)   # docstring 同步


# ---- 2. SearXNG settings.yml 恢复观察钉子 ----------------------------------------


class TestSearxngRestoreObservation(unittest.TestCase):
    """v3.16 恢复观察（维持禁用）：条目/结论/再评估方法在文件里钉死。"""

    @classmethod
    def setUpClass(cls):
        cls.src = (REPO / "tools" / "searxng" / "docker" / "searxng"
                   / "settings.yml").read_text(encoding="utf-8")

    def test_engines_still_disabled(self):
        # 回滚实测复发（too many requests / CAPTCHA / parsing error）→
        # 恢复禁用，三个条目原样保留
        for engine in ("brave", "duckduckgo", "startpage"):
            block = f"- name: {engine}\n    disabled: true"
            self.assertIn(block, self.src, f"{engine} 缺禁用条目")

    def test_v316_observation_conclusion_in_file(self):
        # 实证结论写进文件：单发探活通过 ≠ 可回滚
        self.assertIn("v3.16 恢复观察", self.src)
        self.assertIn("维持禁用", self.src)
        self.assertIn("单发探活通过 ≠ 可回滚", self.src)
        self.assertIn("unresponsive 清零", self.src)   # 恢复判据

    def test_v315_rollback_guidance_kept(self):
        self.assertIn("恢复方法", self.src)
        self.assertIn("docker compose restart", self.src)

    def test_safety_baselines_kept(self):
        self.assertIn("use_default_settings: true", self.src)
        self.assertIn("limiter: false", self.src)
        self.assertIn("- json", self.src)


# ---- 3. 版本锁 + mcp 描述 ---------------------------------------------------------


class TestVersionSyncV316(unittest.TestCase):
    def test_versions_3160(self):
        self.assertEqual(mcp_server.__version__, "3.16.0")
        # chat-scraper 目录名带连字符不可 import，源码级断言（v3.12 先例）
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        self.assertIn('__version__ = "3.16.0"', init_src)
        self.assertIn("chat-scraper v3.16.0", init_src)   # docstring 首行同步

    def test_changelog_has_3160(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.16.0] - 2026-09-16", changelog)


class TestMcpDoctorDescriptionV316(unittest.TestCase):
    """mcp doctor 描述同步 8 项（v3.15 的 7 项清单不回退）。"""

    def test_description_declares_8_items(self):
        if mcp_server is None:
            self.skipTest("mcp SDK 未安装")
        import asyncio
        tools = asyncio.run(mcp_server.mcp.list_tools())
        desc = {t.name: t.description for t in tools}["doctor"]
        for token in ("8 项", "值班巡检趋势", "shift_log",
                      "cookie_lifetime_log.jsonl", "sogou_recovery_log.jsonl"):
            self.assertIn(token, desc)


if __name__ == "__main__":
    unittest.main()
