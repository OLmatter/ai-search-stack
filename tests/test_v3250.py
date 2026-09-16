"""v3.25.0 回归：判据 v2 首次实战（gate-2 资格核验 c) 跨度未达标不烧）
+ gate-1.5 实网首验未过 + engines= 语义两形态钉。

四块内容（全部离线，零真实搜索请求——本轮实网预算 5/5 已在采样环节
消耗，回归钉全部走 mock / 源码钉）：
1. engines= 语义两形态请求形状钉（本轮受控对照的库内固化）：search()
   恒传 categories → engines= 是「默认集 ∪ 点名」；probe() 无
   categories → engines= 严格收窄。两形态 URL 形状不同是实测语义差的
   载体，钉形状即钉语义。
2. searxng_client 契约注释源钉（docstring 语义警告在场——行为级变更
   立项未决，改前注释即契约）。
3. settings.yml v3.25 采样段钉（判据 v2 裁决 c✗ 不烧 + streak 3→4 +
   ddg 归零后第 3 fail + gate-1.5 未过 + 三引擎维持全禁）。
4. 版本锁 3.25.0（双 __version__）+ CHANGELOG + README 徽章。
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


# ---- 1. engines= 语义两形态：请求形状钉 ------------------------------------------------


class TestEnginesSemanticsTwoShapes(unittest.TestCase):
    """v3.25 受控对照（同 engines= 参数、只差 categories 有无）的库内固化。

    实测（settings.yml v3.25 段）：search() 形态 google cse 混入默认集，
    probe() 形态严格只调度点名引擎。URL 形状是语义的载体。
    """

    def _capture(self, fn, *args, **kwargs):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            return _FakeResp({"results": [], "unresponsive_engines": []})

        with mock.patch("urllib.request.urlopen",
                        side_effect=fake_urlopen):
            fn(*args, **kwargs)
        return captured["url"]

    def test_search_engines_keeps_categories_union_semantics(self):
        # search(engines=X)：categories=general 在场 → 「默认集 ∪ 点名」
        url = self._capture(sx.search, "python", since=None,
                            engines="brave,wikipedia")
        self.assertIn("categories=general", url)
        self.assertIn("engines=brave%2Cwikipedia", url)

    def test_probe_url_strict_narrowing_no_categories(self):
        # probe()：无 categories → engines= 严格收窄（单发探活可比性根基）
        url = self._capture(sx.probe, "python", "brave")
        self.assertIn("engines=brave", url)
        self.assertNotIn("categories", url)


# ---- 2. 契约注释源钉 -------------------------------------------------------------------


class TestEnginesDocContract(unittest.TestCase):
    def test_contract_note_in_docstring(self):
        # 行为级变更（engines= 时弃 categories）立项未决——改前注释即
        # 契约，两形态语义警告必须在源码里（防止后续班次不知情踩混）
        src = (REPO / "tools" / "searxng" / "searxng_client.py"
               ).read_text(encoding="utf-8")
        for token in ("默认集 ∪ 点名", "严格收窄", "立项未决"):
            self.assertIn(token, src, token)


# ---- 3. settings.yml v3.25 采样段 ------------------------------------------------------


class TestSettingsV325Sampling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = (REPO / "tools" / "searxng" / "docker" / "searxng"
                   / "settings.yml").read_text(encoding="utf-8")

    def test_v325_block_pinned(self):
        # 判词只收证据链：时间戳/行数/裁决/根因逐字在案
        for token in ("v3.25 第七轮采样", "预算 5/5", "00:51:24", "20 行",
                      "streak", "3→4", "gate-2", "不烧", "24h", "≤2.9h",
                      "gate-1.5", "google cse", "CAPTCHA", "受控对照",
                      "默认集 ∪ 点名", "0 行"):
            self.assertIn(token, self.src, token)

    def test_three_engines_still_disabled(self):
        # 三引擎全禁维持（brave c✗ 不烧、ddg streak=0、startpage 止损）；
        # 实例级聚合 0 行是实例级波动，不触发任何单引擎禁用状态调整
        for engine in ("brave", "duckduckgo", "startpage"):
            m = re.search(rf"- name: {engine}\n\s+disabled: (true|false)",
                          self.src)
            self.assertIsNotNone(m, engine)
            self.assertEqual(m.group(1), "true", f"{engine} 应维持禁用")


# ---- 4. 版本锁 / CHANGELOG / README ----------------------------------------------------


class TestVersionSyncV325(unittest.TestCase):
    def test_versions_3250(self):
        if mcp_server is None:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            ver = re.search(r'__version__ = "([^"]+)"', src).group(1)
        else:
            ver = mcp_server.__version__
        self.assertEqual(ver, "3.25.0")
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        self.assertIn(f'__version__ = "{ver}"', init_src)
        self.assertIn(f"chat-scraper v{ver}", init_src)   # docstring 首行同步

    def test_changelog_and_readme_3250(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.25.0] - 2026-09-17", changelog)
        self.assertIn("判据 v2 首次实战", changelog)
        self.assertIn("gate-1.5 实网首验", changelog)
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("release-v3.25.0", readme)
        self.assertIn("v3.25.0（2026-09-17）", readme)


if __name__ == "__main__":
    unittest.main()
