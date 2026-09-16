"""v3.18.0 回归：doctor 值班巡检趋势统计口径重做（shift_log 近 7 天汇总）
+ doctor GitHub 检查可选 GITHUB_TOKEN 认证。

三块内容（全部离线，零真实请求、零浏览器）：
1. doctor._shift_log_stats / check_shift_log（v3.16 引入、v3.18 重做）：
   近 7 天记录条数/覆盖天数/每日条数分布/关键事件计数（restart/处置/❌/
   恶化，纯字面大小写敏感子串，一行可命中多词各自计数）/最近一条时间戳
   +首 80 字摘要；[HH:MM] 省日期行继承上一条带日期条目的日期（文件头部
   无日期可继承时跳过）；坏行/非法日期跳过不计数；缺文件/空文件/全坏行
   = 可选观测未启用，不报警（沿 sogou_recovery_log 先例）；有记录但近
   7 天零记录 → ⚠️ 值班连续性中断（optional 不判核心故障）；窗口过滤
   （第 8 天前不计，last 与 last_any 口径分立）。v3.16 旧行为钉子
   （疑似异常口径/缺文件报警）随行为演进移除，见 test_v3160 适配注记。
2. doctor.check_github：GITHUB_TOKEN 存在时带 Authorization: Bearer 头
   （值去空白），缺失/空串维持匿名观测（可选配置缺失不是故障）；UA 头
   不丢（v3.11 修复不回退，test_v3110 另有独立钉子）。取证背景：值班
   日志 08:52/09:03 两班 doctor 403 而同刻独立 curl 直连全 200 = 匿名
   60 req/h 共享配额限流窗口；MCP 侧 github_client 早已支持 token 而
   doctor 不支持（声明-实现缺口），本版补齐。
3. 版本锁 3.18.0（mcp_server + chat-scraper __init__ 精确锁，v3.12 先例
   源码级断言；test_v3170 的 3.17.0 锁同步转常青下限）+ main() 注册顺序
   钉子 + mcp doctor 描述钉子。
"""
import datetime
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

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


class _FrozenDateTime(datetime.datetime):
    """check_shift_log 内部 datetime.now() 冻结到 _NOW（消真实时钟时炸弹）。"""

    @classmethod
    def now(cls, tz=None):
        return _NOW


# ---- 1. shift_log 统计与检查 ----------------------------------------------------


class TestShiftLogStats(unittest.TestCase):
    """_shift_log_stats：窗口/继承/坏行/每日分布/事件计数/最近一条。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = os.path.join(self.tmp.name, "shift_log.md")

    def _write(self, *lines):
        with open(self.log, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def test_normal_full_stats(self):
        # 两种时间戳格式混合 + 两天覆盖 + 事件计数 + 最近一条
        self._write(
            "[2026-09-15 08:30] 班次：探活 valid，无残留",
            "[09:00] 值班巡检：docker restart 后引擎全健康",   # 继承 09-15
            "[2026-09-16 08:48] 处置：doctor 复查 ❌ 403 较昨恶化",
        )
        s = doctor_mod._shift_log_stats(self.log, _NOW)
        self.assertEqual(s["count"], 3)
        self.assertEqual(s["days"], 2)
        self.assertEqual(s["per_day"],
                         [(datetime.date(2026, 9, 15), 2),
                          (datetime.date(2026, 9, 16), 1)])
        self.assertEqual(s["events"], {"restart": 1, "处置": 1,
                                       "❌": 1, "恶化": 1})
        self.assertEqual(s["last"],
                         ("2026-09-16 08:48",
                          "处置：doctor 复查 ❌ 403 较昨恶化"))
        self.assertEqual(s["last"], s["last_any"])   # 全文件最后一条同窗口

    def test_short_form_inherits_previous_date(self):
        self._write(
            "[2026-09-15 08:30] 带日期条目",
            "[23:59] 省写日期条目（继承 09-15）",
        )
        s = doctor_mod._shift_log_stats(self.log, _NOW)
        self.assertEqual(s["count"], 2)
        self.assertEqual(s["last"][0], "2026-09-15 23:59")   # 继承日期可见

    def test_short_form_at_head_without_date_skipped(self):
        # 文件头部无日期可继承 → 跳过不计数（声明的口径，测试钉死）
        self._write(
            "[08:00] 头部无日期可继承",
            "[2026-09-16 09:00] 合法条目",
        )
        s = doctor_mod._shift_log_stats(self.log, _NOW)
        self.assertEqual((s["total"], s["count"]), (1, 1))

    def test_window_excludes_8th_day_back(self):
        # 窗口外条目放在文件末尾：验证 last（窗口内文件序最后）与
        # last_any（全文件序最后）口径不同且各自正确
        self._write(
            "[2026-09-10 00:01] 窗口第一天：计",
            "[2026-09-16 20:00] 今天：计",
            "[2026-09-08 23:00] 第 8 天前：不计",
        )
        s = doctor_mod._shift_log_stats(self.log, _NOW)
        self.assertEqual((s["count"], s["days"]), (2, 2))
        self.assertEqual(s["total"], 3)   # 全文件口径含窗口外
        self.assertEqual(s["last_any"][0], "2026-09-08 23:00")   # 全文件最后
        self.assertEqual(s["last"][0], "2026-09-16 20:00")       # 窗口内最后

    def test_bad_lines_skipped(self):
        self._write(
            "这是一行没有时间戳的流水",
            "[2026-13-99 25:61] 非法日期时间",
            "[2026-09-16 09:00] 合法条目：探活 valid",
            "尾随脏行",
        )
        s = doctor_mod._shift_log_stats(self.log, _NOW)
        self.assertEqual((s["total"], s["count"], s["days"]), (1, 1, 1))

    def test_empty_file_zero_parseable(self):
        self._write("")
        s = doctor_mod._shift_log_stats(self.log, _NOW)
        self.assertEqual((s["total"], s["count"], s["days"]), (0, 0, 0))
        self.assertIsNone(s["last"])

    def test_whitespace_only_file_zero_parseable(self):
        self._write("   ", "\t", "")
        s = doctor_mod._shift_log_stats(self.log, _NOW)
        self.assertEqual(s["total"], 0)

    def test_events_literal_and_case_sensitive(self):
        # 纯字面计数：大写 Restart 不命中 restart（大小写敏感子串）；
        # 一行命中两词各计一次；不做任何 NLP
        self._write(
            "[2026-09-16 08:00] Restart 大写不算 restart 小写算",
            "[2026-09-16 08:10] 处置：❌ 复现，一行两词",
            "[2026-09-16 08:20] 恶化描述",
        )
        s = doctor_mod._shift_log_stats(self.log, _NOW)
        self.assertEqual(s["events"], {"restart": 1, "处置": 1,
                                       "❌": 1, "恶化": 1})

    def test_events_all_zero_keys_present(self):
        self._write("[2026-09-16 08:00] 平淡无事的班次")
        s = doctor_mod._shift_log_stats(self.log, _NOW)
        self.assertEqual(s["events"], {"restart": 0, "处置": 0,
                                       "❌": 0, "恶化": 0})

    def test_last_text_clipped_to_80_chars(self):
        long_text = "字" * 200
        self._write(f"[2026-09-16 08:00] {long_text}")
        s = doctor_mod._shift_log_stats(self.log, _NOW)
        self.assertEqual(s["last"][1], "字" * 80)   # 首 80 字摘要

    def test_missing_file_returns_none(self):
        self.assertIsNone(
            doctor_mod._shift_log_stats(os.path.join(self.tmp.name, "nope.md"),
                                        _NOW))

    def test_window_days_parameter(self):
        self._write(
            "[2026-09-01 08:00] 很早的条目：探活 valid",
            "[2026-09-16 08:00] 今天：探活 valid",
        )
        s = doctor_mod._shift_log_stats(self.log, _NOW, window_days=30)
        self.assertEqual(s["count"], 2)

    def test_real_repo_shift_log_readable(self):
        # 真实仓库日志可统计（口径对真实格式不炸；不断言具体数字——
        # shift_log 是活的，数字随值班变化）
        s = doctor_mod._shift_log_stats(doctor_mod.SHIFT_LOG_PATH, _NOW)
        self.assertIsNotNone(s)
        self.assertIsInstance(s["count"], int)
        self.assertIsInstance(s["days"], int)
        self.assertLessEqual(s["count"], s["total"])


class TestCheckShiftLog(unittest.TestCase):
    """check_shift_log：缺文件/空/全坏行不报警；7 天零记录 ⚠️；正常出汇总。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log = os.path.join(self.tmp.name, "shift_log.md")
        self.addCleanup(setattr, doctor_mod, "SHIFT_LOG_PATH",
                        doctor_mod.SHIFT_LOG_PATH)
        doctor_mod.SHIFT_LOG_PATH = self.log
        # 冻结内部 now()：真实日志断言不随运行日期漂移（时炸弹防御）
        p = mock.patch.object(doctor_mod, "datetime", _FrozenDateTime)
        p.start()
        self.addCleanup(p.stop)

    def _write(self, *lines):
        with open(self.log, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

    def test_missing_file_not_enabled_no_alarm(self):
        # v3.18 口径：缺文件 = 可选观测项未启用，不报警不判故障
        # （沿 sogou_recovery_log 先例；返回 ✅ 说明串，不 raise。
        #  v3.16 初版缺文件报警，与队列口径相悖，本版返工）
        detail = doctor_mod.check_shift_log()
        self.assertIsInstance(detail, str)
        self.assertIn("不存在", detail)
        self.assertIn("不报警", detail)

    def test_empty_file_not_enabled_no_alarm(self):
        self._write("")
        detail = doctor_mod.check_shift_log()
        self.assertIn("无可解析记录", detail)
        self.assertIn("不报警", detail)

    def test_all_bad_lines_not_enabled_no_alarm(self):
        self._write(" junk ", "[13:99] 非法", "no timestamp")
        detail = doctor_mod.check_shift_log()
        self.assertIn("无可解析记录", detail)
        self.assertIn("不报警", detail)

    def test_zero_records_in_window_raises_continuity(self):
        # 有记录但近 7 天零记录 → ⚠️ 连续性中断（optional 不判核心故障，
        # 但要有可观测报警；消息带最近一条时间戳让"断了多久"可见）
        self._write("[2026-09-01 08:00] 很久以前的记录")
        with self.assertRaises(RuntimeError) as ctx:
            doctor_mod.check_shift_log()
        msg = str(ctx.exception)
        self.assertIn("零记录", msg)
        self.assertIn("连续性中断", msg)
        self.assertIn("2026-09-01 08:00", msg)

    def test_normal_summary_contains_all_stats(self):
        self._write(
            "[2026-09-16 08:38] SearXNG 容器重启：docker restart 后恢复",
            "[2026-09-16 08:50] 处置：复查通过",
            "[2026-09-16 09:03] 班次收工：GitHub ❌ 403 恶化趋势中止",
        )
        detail = doctor_mod.check_shift_log()
        self.assertIn("近 7 天记录 3 条", detail)
        self.assertIn("覆盖 1 天", detail)
        self.assertIn("2026-09-16:3", detail)          # 每天条数分布
        self.assertIn("restart×1", detail)             # 关键事件计数
        self.assertIn("处置×1", detail)
        self.assertIn("❌×1", detail)
        self.assertIn("恶化×1", detail)
        self.assertIn("最近一条 [2026-09-16 09:03]", detail)
        self.assertIn("班次收工", detail)              # 首 80 字摘要可见

    def test_real_repo_shift_log_summary(self):
        # 真实仓库日志出汇总（now 已冻结到 _NOW=2026-09-16，确定性绿）
        real = REPO / "tools" / "chat-scraper" / "state" / "shift_log.md"
        if not real.exists():
            self.skipTest("真实 shift_log.md 不存在")
        target = os.path.join(self.tmp.name, "shift_log.md")
        with open(real, encoding="utf-8") as f:
            content = f.read()
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        doctor_mod.SHIFT_LOG_PATH = target
        detail = doctor_mod.check_shift_log()
        self.assertIn("近 7 天记录", detail)
        self.assertIn("事件计数", detail)
        self.assertIn("最近一条 [", detail)


class TestCheckGithubToken(unittest.TestCase):
    """check_github v3.18：GITHUB_TOKEN 存在带 Bearer 头；缺失维持匿名。"""

    def _call(self, env):
        calls = {}

        def fake_get(url, timeout=doctor_mod.TIMEOUT, headers=None):
            calls["url"] = url
            calls["headers"] = headers
            return "{}"

        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(doctor_mod, "_get", side_effect=fake_get):
            detail = doctor_mod.check_github()
        return calls, detail

    def test_token_set_adds_bearer_header_keeps_ua(self):
        calls, detail = self._call({"GITHUB_TOKEN": "ghp_test123"})
        self.assertIn("api.github.com", calls["url"])
        self.assertEqual(calls["headers"]["Authorization"],
                         "Bearer ghp_test123")
        self.assertEqual(calls["headers"]["User-Agent"],
                         "ai-search-stack-doctor")   # v3.11 UA 修复不回退
        self.assertIn("Bearer 认证", detail)
        self.assertIn("200", detail)

    def test_token_absent_stays_anonymous(self):
        calls, detail = self._call({})
        self.assertNotIn("Authorization", calls["headers"])
        self.assertIn("匿名", detail)

    def test_token_whitespace_stripped(self):
        calls, _ = self._call({"GITHUB_TOKEN": "  ghp_x  \t"})
        self.assertEqual(calls["headers"]["Authorization"], "Bearer ghp_x")

    def test_empty_token_treated_as_absent(self):
        calls, detail = self._call({"GITHUB_TOKEN": ""})
        self.assertNotIn("Authorization", calls["headers"])
        self.assertIn("匿名", detail)


# ---- 2. main() 注册顺序钉子 ------------------------------------------------------


class TestDoctorRegistration(unittest.TestCase):
    """main() 注册钉子：第 8 项检查，optional，排在尾部。"""

    def test_shift_log_check_registered_optional_last(self):
        src = (REPO / "tools" / "doctor.py").read_text(encoding="utf-8")
        self.assertIn('_check("值班巡检趋势", check_shift_log, optional=True)',
                      src)
        self.assertIn("8 = 5 网络探活 + 3 本地状态", src)   # docstring 同步
        # 排在 GitHub API（第 7 项）之后 = full 模式尾部
        self.assertLess(src.index('_check("GitHub API"'),
                        src.index('_check("值班巡检趋势"'))


# ---- 3. 版本锁 + mcp 描述 ---------------------------------------------------------


class TestVersionSyncV318(unittest.TestCase):
    def test_versions_3180(self):
        self.assertEqual(mcp_server.__version__, "3.18.0")
        # chat-scraper 目录名带连字符不可 import，源码级断言（v3.12 先例）
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        self.assertIn('__version__ = "3.18.0"', init_src)
        self.assertIn("chat-scraper v3.18.0", init_src)   # docstring 首行同步

    def test_changelog_has_3180(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.18.0] - 2026-09-16", changelog)


class TestMcpDoctorDescriptionV318(unittest.TestCase):
    """mcp doctor 描述钉子：8 项清单 + v3.18 统计口径词。"""

    def test_description_declares_8_items(self):
        if mcp_server is None:
            self.skipTest("mcp SDK 未安装")
        import asyncio
        tools = asyncio.run(mcp_server.mcp.list_tools())
        desc = {t.name: t.description for t in tools}["doctor"]
        for token in ("8 项", "值班巡检趋势", "shift_log", "每日分布",
                      "事件计数", "最近一条",
                      "cookie_lifetime_log.jsonl", "sogou_recovery_log.jsonl"):
            self.assertIn(token, desc)


if __name__ == "__main__":
    unittest.main()
