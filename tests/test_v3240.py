"""v3.24.0 回归：doctor 实例级健康下限（聚合行数地板 SEARXNG_MIN_ROWS）
+ probe() 实网首用落账（brave streak 2→3 + 连发数据点）+ N 定标
（brave 恢复判据 v2：N=3 + 连发 K=2 + 跨度 ≥24h）。

四块内容（全部离线，零真实搜索请求——本轮实网预算 4/4 已在采样环节
消耗，回归钉全部走 mock / 源码钉）：
1. check_searxng 行数地板三态：<3 行抛「实例级降级」⚠️（optional 异常
   路径，不翻退出码）/ 地板含边界（3 行过 2 行抛）/ 健康路径 detail
   原样保留（unresponsive 引擎照报）。
2. 地板常量与接线源钉：SEARXNG_MIN_ROWS=3、main 里 optional=True
   注册（降级 ⚠️ 不判核心故障的 exit-code 语义锚）。
3. settings.yml v3.24 采样段与 N 定标钉 + 三引擎维持全禁。
4. 版本锁 3.24.0（双 __version__）+ CHANGELOG + README 徽章。
"""
import json
import pathlib
import re
import sys
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import doctor as doctor_mod   # noqa: E402  (tools/doctor.py)

try:
    import mcp_server              # noqa: E402
except ImportError:                # mcp SDK 未安装（部分 CI）——版本锁降级源码断言
    mcp_server = None


def _searxng_body(rows, dead=None):
    return json.dumps({"results": [{"title": f"r{i}"} for i in range(rows)],
                       "unresponsive_engines": dead or []})


# ---- 1. check_searxng 行数地板三态 -----------------------------------------------------


class TestSearxngRowFloor(unittest.TestCase):
    """v3.23 盲区收口：聚合仅 wikipedia 1 行也曾 ✅「引擎全健康」。"""

    def _check(self, rows, dead=None):
        with mock.patch.object(doctor_mod, "_get",
                               return_value=_searxng_body(rows, dead)):
            return doctor_mod.check_searxng()

    def test_below_floor_raises_degradation(self):
        # 1 行（v3.23 实录降级态）→ ⚠️ 异常路径：文本点名实例级、非单引擎
        with self.assertRaises(RuntimeError) as cm:
            self._check(1)
        msg = str(cm.exception)
        for token in ("实例级降级", "仅 1 行", "3 行下限",
                      "非单引擎问题", "引擎全健康"):
            self.assertIn(token, msg, token)

    def test_floor_boundary_inclusive(self):
        # 地板含边界：3 行 = 过（detail 原样返回）；2 行 = 降级抛 ⚠️
        detail = self._check(3)
        self.assertIn("3 条结果", detail)
        self.assertIn("引擎全健康", detail)
        with self.assertRaises(RuntimeError):
            self._check(2)

    def test_healthy_path_detail_preserved(self):
        # 地板之上：unresponsive 引擎照报（v3.14 钉的本意，行数地板不替代）
        detail = self._check(5, dead=["bing"])
        self.assertIn("5 条结果", detail)
        self.assertIn("不健康引擎", detail)
        self.assertIn("bing", detail)


# ---- 2. 地板常量与接线源钉 --------------------------------------------------------------


class TestFloorWiring(unittest.TestCase):
    def test_constant_and_optional_registration(self):
        # 地板常量钉 + exit-code 语义锚：check_searxng 在 main 里以
        # optional=True 注册——降级走异常路径渲染 ⚠️ 但不进 core_fail，
        # 退出码不翻（实例活着只是聚合枯竭 = 降级不是核心故障）
        self.assertEqual(doctor_mod.SEARXNG_MIN_ROWS, 3)
        src = (REPO / "tools" / "doctor.py").read_text(encoding="utf-8")
        self.assertIn("SEARXNG_MIN_ROWS = 3", src)
        self.assertIn('_check("SearXNG 本地实例", check_searxng, '
                      'optional=True)', src)
        self.assertIn("非单引擎问题", src)   # 与单引擎止损判据的边界写明


# ---- 3. settings.yml v3.24 采样段与 N 定标 ----------------------------------------------


class TestSettingsV324Sampling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = (REPO / "tools" / "searxng" / "docker" / "searxng"
                   / "settings.yml").read_text(encoding="utf-8")

    def test_v324_block_and_n_calibration_pinned(self):
        # 判词只收证据链：行数/连发/症状逐字在案（判据 v2 三条 + gate-1.5
        # 评估 + 实网首用落账）
        for token in ("v3.24 第六轮采样", "probe()", "实网首用",
                      "streak 2→3", "背靠背", "20 行", "CAPTCHA",
                      "N=3", "24h", "gate-1.5", "google cse"):
            self.assertIn(token, self.src, token)

    def test_three_engines_still_disabled(self):
        # 三引擎全禁维持（brave 资格未齐不烧、ddg streak=0、startpage 止损）
        for engine in ("brave", "duckduckgo", "startpage"):
            m = re.search(rf"- name: {engine}\n\s+disabled: (true|false)",
                          self.src)
            self.assertIsNotNone(m, engine)
            self.assertEqual(m.group(1), "true", f"{engine} 应维持禁用")


# ---- 4. 版本锁 / CHANGELOG / README ------------------------------------------------------


class TestVersionSyncV324(unittest.TestCase):
    def test_versions_3240(self):
        if mcp_server is None:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            ver = re.search(r'__version__ = "([^"]+)"', src).group(1)
        else:
            ver = mcp_server.__version__
        self.assertEqual(ver, "3.24.0")
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        self.assertIn(f'__version__ = "{ver}"', init_src)
        self.assertIn(f"chat-scraper v{ver}", init_src)   # docstring 首行同步

    def test_changelog_and_readme_3240(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.24.0] - 2026-09-17", changelog)
        self.assertIn("SEARXNG_MIN_ROWS", changelog)
        self.assertIn("probe() 实网首用", changelog)
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("release-v3.24.0", readme)
        self.assertIn("v3.24.0（2026-09-17）", readme)


if __name__ == "__main__":
    unittest.main()
