"""v3.26.0 回归：判据 v2 第二次实战（brave gate-1 fail + 跨度 3.5h<<24h
双拦，gate-2 不烧；streak 4→0 诚实归零）+ search(engines=) 语义统一
（弃 categories 换严格收窄，行为级变更落地）。

四块内容（全部离线，零真实搜索请求——本轮实网预算 3/5 已在采样环节
消耗，回归钉全部走 mock / 源码钉）：
1. engines= 统一语义行为钉（本轮行为级变更的主契约钉）：search(engines=X)
   弃 categories 严格收窄；search() 默认路径 categories=general 不变；
   probe() 严格收窄不回归。
2. 契约注释源钉（代码内 v3.26 严格收窄注释在场——钉机制落点防回归）。
3. settings.yml v3.26 采样段钉（判据 v2 双拦 + streak 4→0 + ddg 症状
   变异 + 聚合恢复 + 三引擎维持全禁）。
4. 版本锁 3.26.0（双 __version__，自 test_v3250 接管精确锁）+ CHANGELOG
   + README 徽章。
"""
import json
import pathlib
import re
import sys
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "searxng"))

import searxng_client as sx    # noqa: E402

try:
    import mcp_server              # noqa: E402
except ImportError:                # mcp SDK 未安装（部分 CI）——版本锁降级源码断言
    mcp_server = None


class _FakeResp:
    """urlopen 假响应（支持 with 上下文）。"""

    def __init__(self, payload):
        self._b = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# ---- 1. engines= 统一语义：行为钉 -------------------------------------------------------


class TestEnginesUnifiedBehavior(unittest.TestCase):
    """v3.26 行为级变更主契约钉：engines= 显式点名 = 严格收窄（全路径）。"""

    def _capture(self, fn, *args, **kwargs):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            return _FakeResp({"results": [], "unresponsive_engines": []})

        with mock.patch("urllib.request.urlopen",
                        side_effect=fake_urlopen):
            fn(*args, **kwargs)
        return captured["url"]

    def test_search_single_engine_strict_narrowing(self):
        # search(engines="brave")：URL 无 categories（v3.25 及以前在此
        # 场景恒传 categories=general → 默认集混入，google cse 实测 6 行
        # 混入 brave,wikipedia 查询——settings.yml v3.25/v3.26 段在案）
        url = self._capture(sx.search, "python", since=None, engines="brave")
        self.assertIn("engines=brave", url)
        self.assertNotIn("categories", url)

    def test_search_multi_engine_strict_narrowing(self):
        # 多引擎点名同语义（v3.25 gate-1.5 的实害场景——统一后不再混入）
        url = self._capture(sx.search, "python", since=None,
                            engines="brave,wikipedia")
        self.assertIn("engines=brave%2Cwikipedia", url)
        self.assertNotIn("categories", url)

    def test_search_default_path_unchanged(self):
        # engines=None：默认引擎集路径生产行为不变（categories=general 在场）
        url = self._capture(sx.search, "python", since=None)
        self.assertIn("categories=general", url)
        self.assertNotIn("engines=", url)

    def test_probe_strict_narrowing_regression(self):
        # probe() 严格收窄不回归（v3.25 原钉随语义统一平移）
        url = self._capture(sx.probe, "python", "brave")
        self.assertIn("engines=brave", url)
        self.assertNotIn("categories", url)


# ---- 2. 契约注释源钉 -------------------------------------------------------------------


class TestStrictNarrowingSourcePin(unittest.TestCase):
    def test_code_marker_in_source(self):
        # 机制落点钉：search() 内 engines= 分支的 categories 剔除必须在
        # 源码里（防后续重构把严格收窄悄悄改回「默认集 ∪ 点名」）
        src = (REPO / "tools" / "searxng" / "searxng_client.py"
               ).read_text(encoding="utf-8")
        self.assertIn('del params["categories"]', src)
        self.assertIn("v3.26 严格收窄", src)


# ---- 3. settings.yml v3.26 采样段 ------------------------------------------------------


class TestSettingsV326Sampling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = (REPO / "tools" / "searxng" / "docker" / "searxng"
                   / "settings.yml").read_text(encoding="utf-8")

    def test_v326_block_pinned(self):
        # 判词只收证据链：时间戳/行数/裁决/症状逐字在案
        for token in ("v3.26 第八轮采样", "预算 3/5", "01:23:10",
                      "01:23:37", "01:24:19", "streak 4→0", "判据 v2 第二次实战",
                      "duckduckgo: timeout", "brave: timeout", "症状变异首录",
                      "第 4 fail", "20 行全部 google cse", "gate-2 不烧",
                      "~3.5h << 24h", "语义统一"):
            self.assertIn(token, self.src, token)

    def test_three_engines_still_disabled(self):
        # 三引擎全禁维持（brave gate-1 fail + 跨度不足双拦、ddg streak=0、
        # startpage 止损）；实例级聚合波动不触发任何单引擎状态调整
        for engine in ("brave", "duckduckgo", "startpage"):
            m = re.search(rf"- name: {engine}\n\s+disabled: (true|false)",
                          self.src)
            self.assertIsNotNone(m, engine)
            self.assertEqual(m.group(1), "true", f"{engine} 应维持禁用")


# ---- 4. 版本锁 / CHANGELOG / README ----------------------------------------------------


class TestVersionSyncV326(unittest.TestCase):
    def test_versions_3260(self):
        # v3.26 起精确锁自 test_v3250 接管（降常青先例延续）
        if mcp_server is None:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            ver = re.search(r'__version__ = "([^"]+)"', src).group(1)
        else:
            ver = mcp_server.__version__
        self.assertEqual(ver, "3.26.0")
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        self.assertIn(f'__version__ = "{ver}"', init_src)
        self.assertIn(f"chat-scraper v{ver}", init_src)   # docstring 首行同步

    def test_changelog_and_readme_3260(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.26.0] - 2026-09-17", changelog)
        self.assertIn("判据 v2 第二次实战", changelog)
        self.assertIn("严格收窄", changelog)
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("release-v3.26.0", readme)
        self.assertIn("v3.26.0（2026-09-17）", readme)


if __name__ == "__main__":
    unittest.main()
