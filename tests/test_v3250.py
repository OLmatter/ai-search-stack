"""v3.25.0 回归：判据 v2 首次实战（gate-2 资格核验 c) 跨度未达标不烧）
+ gate-1.5 实网首验未过 + engines= 语义钉。

四块内容（全部离线，零真实搜索请求——本轮实网预算 5/5 已在采样环节
消耗，回归钉全部走 mock / 源码钉）：
1. engines= 语义请求形状钉（v3.25 受控对照库内固化；v3.26 行为级变更
   落地后本组钉翻转为「统一严格收窄」——原 union 语义钉的实测依据
   （google cse 混入）移入 settings.yml v3.25/v3.26 段历史）。
2. searxng_client 契约注释源钉（v3.26 起钉「语义统一已落地」；原
   「立项未决」契约注释随行为变更退场）。
3. settings.yml v3.25 采样段钉（判据 v2 裁决 c✗ 不烧 + streak 3→4 +
   ddg 归零后第 3 fail + gate-1.5 未过 + 三引擎维持全禁）。
4. 版本锁（v3.26 起精确锁移交 test_v3260，此处降常青下限——
   v3.17→v3.19、v3.21→v3.22、v3.22→v3.23、v3.23→v3.24、v3.24→v3.25
   先例）：双 __version__ 同步 + CHANGELOG 历史段（append-only）精确 +
   README 徽章/状态行与 __version__ 一致。
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


# ---- 1. engines= 语义：请求形状钉 ------------------------------------------------------


class TestEnginesSemanticsUnified(unittest.TestCase):
    """engines= 语义钉（v3.25 受控对照固化 → v3.26 行为级变更翻转）。

    v3.25 实测（settings.yml v3.25 段）：search() 恒传 categories 时
    engines= 是「默认集 ∪ 点名」，google cse 混入同场返回（实害：
    gate-1.5 不可靠）。v3.26 取证（MCP 不暴露 engines、生产调用方为零）
    后统一为严格收窄——本组钉随契约翻转，历史依据留档 settings.yml。
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

    def test_search_engines_strict_narrowing_drops_categories(self):
        # v3.26 行为级变更翻转（原钉：categories=general 在场=「默认集
        # ∪ 点名」）：search(engines=X) 弃 categories → 严格收窄，与
        # probe() 同语义
        url = self._capture(sx.search, "python", since=None,
                            engines="brave,wikipedia")
        self.assertIn("engines=brave%2Cwikipedia", url)
        self.assertNotIn("categories", url)

    def test_search_default_path_keeps_categories(self):
        # engines=None（默认引擎集路径）不受影响：categories=general 照常
        # 在场（生产行为不变，严格收窄只作用于 engines= 显式点名时）
        url = self._capture(sx.search, "python", since=None)
        self.assertIn("categories=general", url)
        self.assertNotIn("engines=", url)

    def test_probe_url_strict_narrowing_no_categories(self):
        # probe()：无 categories → engines= 严格收窄（单发探活可比性根基）
        url = self._capture(sx.probe, "python", "brave")
        self.assertIn("engines=brave", url)
        self.assertNotIn("categories", url)


# ---- 2. 契约注释源钉 -------------------------------------------------------------------


class TestEnginesDocContract(unittest.TestCase):
    def test_contract_note_in_docstring(self):
        # v3.26 行为级变更已落地——「语义统一 + 严格收窄 + v3.26」契约
        # 必须在源码里；「立项未决」旧契约注释必须退场（防双契约并存）
        src = (REPO / "tools" / "searxng" / "searxng_client.py"
               ).read_text(encoding="utf-8")
        for token in ("语义统一", "严格收窄", "v3.26"):
            self.assertIn(token, src, token)
        self.assertNotIn("立项未决", src, "旧契约注释应已随行为变更退场")


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
    def test_versions_evergreen(self):
        # v3.26 起精确锁移交 test_v3260，此处降常青下限（v3.17→v3.19、
        # v3.21→v3.22、v3.22→v3.23、v3.23→v3.24、v3.24→v3.25 先例）：
        # 双 __version__ 同步本身不许破
        if mcp_server is None:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            ver = re.search(r'__version__ = "([^"]+)"', src).group(1)
        else:
            ver = mcp_server.__version__
        self.assertGreaterEqual(
            [int(x) for x in ver.split(".")], [3, 25, 0])
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        self.assertIn(f'__version__ = "{ver}"', init_src)
        self.assertIn(f"chat-scraper v{ver}", init_src)   # docstring 首行同步

    def test_changelog_history_and_readme_consistency(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        # CHANGELOG 历史段是 append-only，3.25.0 条目钉保持精确
        self.assertIn("## [3.25.0] - 2026-09-17", changelog)
        self.assertIn("判据 v2 首次实战", changelog)
        self.assertIn("gate-1.5 实网首验", changelog)
        # v3.26 起精确徽章/状态行锁移交 test_v3260，此处降常青：徽章/
        # 状态行版本号与 __version__ 一致（防止换版时徽章漂移回退）
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertRegex(readme, r"release-v\d+\.\d+\.\d+")
        if mcp_server is None:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            ver = re.search(r'__version__ = "([^"]+)"', src).group(1)
        else:
            ver = mcp_server.__version__
        self.assertIn(f"release-v{ver}", readme)
        self.assertIn(f"v{ver}（", readme)   # 状态行「vX.Y.Z（日期）」头部在场


if __name__ == "__main__":
    unittest.main()
