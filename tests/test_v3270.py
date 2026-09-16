"""v3.27.0 回归：症状漂移观察轮（brave/ddg 双回摆逐字症状，v3.26
timeout 漂移未持续；双 streak 维持 0，a)+c) 双拦 gate-2 不烧）+
CLI --probe 退出码契约钉（自评立项：gate-1 班次实际入口的退出码
语义此前只活在 help 文本）。

三块内容（全部离线，零真实搜索请求——本轮实网预算 3/3 已在采样环节
消耗，回归钉全部走 mock / 源码钉）：
1. CLI --probe 退出码三态钉（本轮自评立项主契约钉）：exit 0 = 有效
   观测（ok True/False 均算，判读看 JSON）；exit 1 = 传输/解析故障
   无有效观测（error 键在场，doctor sogou 探活同语义）。
2. settings.yml v3.27 采样段钉（症状回摆 + streak 记账 + gate-2 不烧 +
   三引擎维持全禁）。
3. 版本锁 3.27.0（双 __version__，自 test_v3260 接管精确锁）+ CHANGELOG
   + README 徽章。
"""
import io
import json
import pathlib
import re
import sys
import unittest
import urllib.error
from contextlib import redirect_stdout
from unittest import mock

import runpy

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "searxng"))

import searxng_client as sx    # noqa: E402,F401  （导入即钉模块名唯一前提）

try:
    import mcp_server              # noqa: E402
except ImportError:                # mcp SDK 未安装（部分 CI）——版本锁降级源码断言
    mcp_server = None

CLI_PATH = REPO / "tools" / "searxng" / "searxng_client.py"


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


def _run_cli_probe(payload=None, exc=None):
    """以 __main__ 身份跑 searxng_client.py "python" --probe brave。

    urlopen 打 mock（离线零请求）；返回 (退出码, stdout JSON 文本,
    实际请求 URL)。
    """
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        if exc is not None:
            raise exc
        return _FakeResp(payload)

    buf = io.StringIO()
    argv = [str(CLI_PATH), "python", "--probe", "brave"]
    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen), \
            mock.patch("sys.argv", argv), redirect_stdout(buf):
        try:
            runpy.run_path(str(CLI_PATH), run_name="__main__")
            code = None                  # 不退出=防御（脚本恒 sys.exit）
        except SystemExit as e:
            code = e.code
    return code, buf.getvalue(), captured.get("url", "")


# ---- 1. CLI --probe 退出码三态 ---------------------------------------------------------


class TestProbeCliExitCode(unittest.TestCase):
    """CLI --probe 退出码契约（--probe help 文本所载，本轮前零测试钉）：

    0 = 有效观测（ok 真假都是有效观测，判读看 JSON 的 ok 字段）；
    1 = 传输/解析故障无有效观测（doctor sogou 探活同语义）。
    v3.27 第九轮采样即用该入口实测（brave/ddg 双发 exit=0 有效观测）。
    """

    def test_exit0_gate1_pass_ok_true(self):
        # 第一关过（rows>0 且 unresponsive 空）：exit 0，JSON ok=True 无 error
        code, out, url = _run_cli_probe(
            payload={"results": [{"t": 1}, {"t": 2}],
                     "unresponsive_engines": []})
        self.assertEqual(code, 0)
        verdict = json.loads(out)
        self.assertTrue(verdict["ok"])
        self.assertNotIn("error", verdict)
        # probe 严格收窄请求形状不回归（v3.25/v3.26 契约延续）
        self.assertIn("engines=brave", url)
        self.assertNotIn("categories", url)

    def test_exit0_upstream_fail_is_valid_observation(self):
        # 上游复发（rows=0 + unresponsive）：ok=False 但仍是有效观测 → exit 0
        # （v3.27 实测：brave too many requests / ddg CAPTCHA 双发 exit=0）
        code, out, _ = _run_cli_probe(
            payload={"results": [],
                     "unresponsive_engines": [["brave", "too many requests"]]})
        self.assertEqual(code, 0)
        verdict = json.loads(out)
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["unresponsive"], ["brave: too many requests"])
        self.assertNotIn("error", verdict)

    def test_exit1_transport_failure_no_valid_observation(self):
        # 传输故障（urlopen 抛异常）：probe 返回带 error 键 → JSON + exit 1
        code, out, _ = _run_cli_probe(
            exc=urllib.error.URLError("connection refused"))
        self.assertEqual(code, 1)
        verdict = json.loads(out)
        self.assertIn("error", verdict)
        self.assertFalse(verdict["ok"])
        self.assertEqual(verdict["rows"], 0)


# ---- 2. settings.yml v3.27 采样段 ------------------------------------------------------


class TestSettingsV327Sampling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = (REPO / "tools" / "searxng" / "docker" / "searxng"
                   / "settings.yml").read_text(encoding="utf-8")

    def test_v327_block_pinned(self):
        # 判词只收证据链：时间戳/症状逐字/裁决/记账在案
        for token in ("v3.27 第九轮采样", "预算 3/3", "01:52:34",
                      "01:52:52", "01:53:10", "brave: too many requests",
                      "duckduckgo: CAPTCHA", "症状漂移观察轮", "未持续",
                      "第 5 fail", "重积累第 1 发 fail", "gate-2 不烧",
                      "~0.5h << 24h", "20 行", "逐字复发",
                      "三引擎维持全禁"):
            self.assertIn(token, self.src, token)

    def test_three_engines_still_disabled(self):
        # 三引擎全禁维持（brave/ddg gate-1 fail + 跨度不足、startpage 止损）；
        # 实例级聚合 20 行是实例级健康确认，不触发任何单引擎状态调整
        for engine in ("brave", "duckduckgo", "startpage"):
            m = re.search(rf"- name: {engine}\n\s+disabled: (true|false)",
                          self.src)
            self.assertIsNotNone(m, engine)
            self.assertEqual(m.group(1), "true", f"{engine} 应维持禁用")


# ---- 3. 版本锁 / CHANGELOG / README ----------------------------------------------------


class TestVersionSyncV327(unittest.TestCase):
    def test_versions_3270(self):
        # v3.28 起精确锁移交 test_v3280，此处降常青下限（v3.17→v3.19、
        # v3.23→v3.24、v3.24→v3.25、v3.25→v3.26、v3.26→v3.27 先例）：
        # 双 __version__ 同步本身不许破
        if mcp_server is None:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            ver = re.search(r'__version__ = "([^"]+)"', src).group(1)
        else:
            ver = mcp_server.__version__
        self.assertGreaterEqual(
            [int(x) for x in ver.split(".")], [3, 27, 0])
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        self.assertIn(f'__version__ = "{ver}"', init_src)
        self.assertIn(f"chat-scraper v{ver}", init_src)   # docstring 首行同步

    def test_changelog_and_readme_3270(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        # CHANGELOG 历史段是 append-only，3.27.0 条目钉保持精确
        self.assertIn("## [3.27.0] - 2026-09-17", changelog)
        self.assertIn("症状漂移观察轮", changelog)
        self.assertIn("退出码契约钉", changelog)
        # v3.28 起精确徽章/状态行锁移交 test_v3280，此处降常青：
        # 徽章/状态行与 __version__ 一致（防止换版时徽章漂移回退）
        readme = (REPO / "README.md").read_text(encoding="utf-8")
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
