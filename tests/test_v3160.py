"""v3.16.0 回归（v3.18 适配版）：SearXNG 禁用引擎恢复观察钉子 + doctor
注册/描述/版本钉子。

v3.18 将 check_shift_log 统计口径重做（每日分布/关键事件计数/最近一条
摘要；缺文件/空/全坏行不报警），本文件的 shift_log 行为钉子随行为演进
移入 tests/test_v3180.py（v3.12 护栏测试适配先例）；本文件保留仍然为真
的部分：settings.yml 恢复观察钉子、main() 注册钉子、版本常青下限、
mcp doctor 描述钉子。

实测证据（判词用，不入测试）：2026-09-16 enabled_engines 单发探活
brave 21 / duckduckgo 21 / startpage 20 条均 unresponsive 空；回滚启用
+ restart 后 doctor 聚合搜索三引擎即全部复发（too many requests /
CAPTCHA / parsing error）——单发探活通过 ≠ 可回滚，维持禁用。
"""
import pathlib
import re
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
for d in ("", "chat-scraper"):
    sys.path.insert(0, str(REPO / "tools" / d))

try:
    sys.path.insert(0, str(REPO / "tools"))
    import mcp_server
except ImportError:  # mcp SDK 未安装（部分 CI）——MCP 块整体跳过
    mcp_server = None


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
        # 恢复禁用。v3.19 适配：startpage 经单引擎两关双过单独回滚；
        # v3.23 再适配（行为演进先例同款）：startpage 两轮三观测复发
        # （见 settings.yml v3.23 段）回到禁用，恢复 v3.16 全量元组
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
    def test_versions_not_older_than_3160(self):
        # v3.17 起改为常青下限（v3.13->v3.14 先例）：精确锁当前版本是
        # test_v3170 的职责
        self.assertGreaterEqual(
            tuple(int(x) for x in mcp_server.__version__.split(".")),
            (3, 16, 0))
        # chat-scraper 目录名带连字符不可 import，源码级断言（v3.12 先例）
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        ver = __import__("re").search(
            r'__version__ = "([^"]+)"', init_src).group(1)
        self.assertGreaterEqual(
            tuple(int(x) for x in ver.split(".")), (3, 16, 0))
        self.assertIn(f"chat-scraper v{ver}", init_src)   # docstring 首行同步

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
