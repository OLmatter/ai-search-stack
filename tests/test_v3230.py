"""v3.23.0 回归：clean-worktree 收工检查固化（「本机绿 ≠ fresh 绿」盲区
收口）+ SearXNG 第五轮采样落账（startpage 止损禁用，三引擎全禁）+
searxng_client 探活机制进库（engines= 参数 + probe() 第一关函数）。

四块内容（除行为钉的夹具仓 subprocess 外全部离线，零真实搜索请求）：
1. scripts/clean_worktree_test.sh：源钉（worktree 方案 + stash 无效论证）
   + CONTRIBUTING 版本发布检查项钉 + 盲区复现行为钉（十杀 #3 检查器
   自身必盲测：夹具仓本机绿 / 脚本跑红 / trap 清理无残留 worktree）。
2. searxng_client：search(engines=) 落 URL / None 不加参数 / 追加在
   on_error 之后（位置传参不断链）；probe() 三态（第一关过 / 上游复发 /
   传输故障=无有效观测）+ 空转（rows=0 且 unres 空 ≠ 过）。
3. settings.yml v3.23 采样段（brave streak=2 / ddg streak 归零 /
   startpage Suspended: CAPTCHA 止损）+ startpage disabled 钉。
4. 版本锁 3.23.0（双 __version__）+ CHANGELOG 3.23.0 + README 徽章。
"""
import inspect
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from io import StringIO
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "searxng"))

import searxng_client as sx    # noqa: E402

try:
    import mcp_server              # noqa: E402
except ImportError:                # mcp SDK 未安装（部分 CI）——版本锁降级源码断言
    mcp_server = None

SCRIPT = REPO / "scripts" / "clean_worktree_test.sh"


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


# ---- 1a. clean-worktree 脚本：源钉 ----------------------------------------------------


class TestCleanWorktreeScriptSource(unittest.TestCase):
    """脚本真源钉：worktree 方案 + pytest 转发 + stash 无效论证在文件里。"""

    @classmethod
    def setUpClass(cls):
        cls.src = SCRIPT.read_text(encoding="utf-8")

    def test_worktree_mechanism_pinned(self):
        for token in ("worktree add --detach", "worktree remove --force",
                      "trap cleanup EXIT", "python -m pytest", "mktemp",
                      "rev-parse --is-inside-work-tree"):
            self.assertIn(token, self.src, token)

    def test_why_not_stash_rationale_pinned(self):
        # 盲区论证写进脚本本身（换人可懂）：stash 不触碰 gitignore 文件
        for token in ("gitignore", "stash", "state/", "__pycache__"):
            self.assertIn(token, self.src, token)

    def test_head_based_discipline_pinned(self):
        # 测的是 HEAD（push 的是提交）——先提交再跑的纪律在脚本输出里
        self.assertIn("HEAD", self.src)
        self.assertIn("status --porcelain", self.src)


# ---- 1b. CONTRIBUTING 检查项 ----------------------------------------------------------


class TestContributingCheckpoint(unittest.TestCase):
    def test_contributing_has_clean_worktree_item(self):
        src = (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")
        self.assertIn("clean-worktree 复跑", src)
        self.assertIn("scripts/clean_worktree_test.sh", src)
        self.assertIn("本机绿 ≠ fresh 绿", src)       # 盲区名如实入档
        self.assertIn("worktree 而非 stash", src)      # 手段裁决有据


# ---- 1c. 行为钉：检查器自身盲测（十杀 #3） --------------------------------------------


_BASH_CACHE = []


def _working_bash():
    """可用 bash 的真实路径；不可用返回 None（skip 判据，不做假执行）。

    Windows 教训（本文件首版实测病）：PATH 上的 `bash` 在 Windows 常是
    WSL bash（System32\\bash.exe），无发行版时 execvpe(/bin/bash) 直接
    失败 rc=1——盲测钉「期望非零退出码」会被这种假执行虚假满足（v3.20
    ddg 假阳性同构：检查器自身失效）。故 ①Windows 优先取 git 同源的
    Git Bash；②任何候选先跑 `bash -c true` 验证真的能用。
    """
    if _BASH_CACHE:
        return _BASH_CACHE[0]
    cands = []
    if os.name == "nt":
        git_exe = shutil.which("git")
        if git_exe:
            cands.append(pathlib.Path(git_exe).parent.parent / "bin"
                         / "bash.exe")
    cands.append(pathlib.Path(shutil.which("bash") or "bash-nonexistent"))
    for cand in cands:
        if cand.exists():
            try:
                r = subprocess.run([str(cand), "-c", "true"],
                                   capture_output=True, timeout=30)
                if r.returncode == 0:
                    _BASH_CACHE.append(str(cand))
                    return _BASH_CACHE[0]
            except (OSError, subprocess.TimeoutExpired):
                continue
    return None


@unittest.skipUnless(_working_bash(), "需要可用的 bash（-c true 验证过）与 git")
class TestCleanWorktreeBehavior(unittest.TestCase):
    """夹具仓盲测：本机绿 / 脚本跑红 = 盲区暴露；绿路径 = exit 0 且无残留。

    两钉必须成对：单看「脚本跑红」会被假执行（WSL bash 起不来的 rc=1）
    虚假满足——首版实测即被绿路径钉揪出。红钉证盲区暴露，绿钉证机制
    本身可用 + trap 清理，缺一即自欺。
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _make_fixture(self, body, marker):
        fx = pathlib.Path(self.tmp.name) / "fx"
        (fx / "tests").mkdir(parents=True)
        (fx / "state").mkdir()
        (fx / ".gitignore").write_text("state/\n", encoding="utf-8")
        (fx / "tests" / "test_blind.py").write_text(body, encoding="utf-8")
        if marker:
            (fx / "state" / "marker.txt").write_text("x", encoding="utf-8")

        def git(*a):
            subprocess.run(["git", "-C", str(fx), *a], check=True,
                           capture_output=True, text=True)
        git("init", "-q")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        git("add", "-A")
        git("commit", "-qm", "init")
        return fx

    BLIND_BODY = (
        "import pathlib, unittest\n"
        "class T(unittest.TestCase):\n"
        "    def test_local_artifact_illusion(self):\n"
        "        self.assertTrue(pathlib.Path(\"state/marker.txt\").exists(),\n"
        "                        \"fresh checkout 缺本地产物——盲区本身\")\n")

    def test_blind_spot_reproduction_local_green_script_red(self):
        # v3.18/v3.22 事故微缩复现：gitignore 产物在场 → 本机 pytest 绿；
        # 脚本在 HEAD fresh checkout 里跑 → 缺产物 → 红。检查器有效。
        fx = self._make_fixture(self.BLIND_BODY, marker=True)
        local = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q"], cwd=fx,
            capture_output=True, text=True, timeout=120)
        self.assertEqual(local.returncode, 0, "夹具本机应绿（假象绿）")
        script = subprocess.run(
            [_working_bash(), str(SCRIPT), str(fx)],
            capture_output=True, text=True, timeout=300)
        self.assertNotEqual(script.returncode, 0,
                            "fresh checkout 应红（盲区暴露）")

    def test_green_path_exit0_and_no_worktree_residue(self):
        fx = self._make_fixture(
            "import unittest\n"
            "class T(unittest.TestCase):\n"
            "    def test_ok(self):\n"
            "        self.assertTrue(True)\n", marker=False)
        script = subprocess.run(
            [_working_bash(), str(SCRIPT), str(fx)],
            capture_output=True, text=True, timeout=300)
        self.assertEqual(script.returncode, 0, script.stdout + script.stderr)
        listing = subprocess.run(
            ["git", "-C", str(fx), "worktree", "list", "--porcelain"],
            capture_output=True, text=True, check=True).stdout
        self.assertEqual(listing.count("worktree "), 1,
                         "trap 清理后只应剩夹具仓自身 worktree")


# ---- 2. searxng_client：engines= 参数 + probe() ---------------------------------------


class TestSearchEnginesParam(unittest.TestCase):
    def _capture_url(self, **kwargs):
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            return _FakeResp({"results": [], "unresponsive_engines": []})

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            sx.search("q", since=None, **kwargs)
        return captured["url"]

    def test_engines_param_lands_in_url(self):
        url = self._capture_url(engines="brave")
        self.assertIn("engines=brave", url)

    def test_engines_none_omits_param(self):
        url = self._capture_url()
        self.assertNotIn("engines=", url)

    def test_engines_appended_after_on_error_positional_safe(self):
        # 向后兼容契约（CONTRIBUTING：保持向后兼容）：engines 追加在
        # on_error 之后——既有调用方按位置传满 8 参不断链
        params = list(inspect.signature(sx.search).parameters)
        self.assertEqual(params[:8], ["q", "num", "since", "vendor", "role",
                                      "instance", "categories", "on_error"])
        self.assertEqual(params[8], "engines")


class TestProbe(unittest.TestCase):
    """probe()：两关判据第一关的库固化，三态 + 空转区分。"""

    def _probe(self, payload):
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResp(payload)):
            return sx.probe("python", "brave")

    def test_gate1_pass(self):
        r = self._probe({"results": [{"t": 1}, {"t": 2}, {"t": 3}],
                         "unresponsive_engines": []})
        self.assertTrue(r["ok"])
        self.assertEqual(r["rows"], 3)
        self.assertEqual(r["unresponsive"], [])

    def test_gate1_flare_upstream_relapse(self):
        # 上游复发：rows=0 + unresponsive 有条目 → ok=False 但仍是有效观测
        r = self._probe({"results": [],
                         "unresponsive_engines": [["duckduckgo", "CAPTCHA"]]})
        self.assertFalse(r["ok"])
        self.assertEqual(r["rows"], 0)
        self.assertEqual(r["unresponsive"], ["duckduckgo: CAPTCHA"])
        self.assertNotIn("error", r)

    def test_gate1_vacuum_is_not_pass(self):
        # 真空 ≠ 过：rows=0 且 unresponsive 空，ok 仍 False（判据原文
        # rows>0 且 unresponsive 空，两条件缺一不可）
        r = self._probe({"results": [], "unresponsive_engines": []})
        self.assertFalse(r["ok"])
        self.assertNotIn("error", r)

    def test_transport_error_is_no_valid_observation(self):
        # 传输故障 = 无有效观测（与「上游复发」两回事）：error 字段如实
        from urllib.error import URLError
        with mock.patch("urllib.request.urlopen",
                        side_effect=URLError("conn refused")):
            r = sx.probe("python", "brave")
        self.assertFalse(r["ok"])
        self.assertIn("error", r)
        self.assertIn("URLError", r["error"])

    def test_probe_success_contract_keys(self):
        # 返回契约钉：成功观测恰含五键（error 仅在传输故障时出现）；
        # probe 为纯观测函数，streak 记账归 settings.yml 观察注释（判读
        # 与探活数据分离——数据在返回值里，判词在使用方落账处）
        r = self._probe({"results": [{"t": 1}], "unresponsive_engines": []})
        self.assertEqual(
            set(r), {"engine", "rows", "unresponsive", "ok", "query"})
        self.assertEqual(r["engine"], "brave")
        self.assertEqual(r["query"], "python")


# ---- 3. settings.yml v3.23 采样段 ------------------------------------------------------


class TestSettingsV323Sampling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = (REPO / "tools" / "searxng" / "docker" / "searxng"
                   / "settings.yml").read_text(encoding="utf-8")

    def test_v323_sampling_block_pinned(self):
        # 第五轮采样判读原文在案（判词只收证据链：行数/症状逐字可查）
        for token in ("v3.23 第五轮采样", "预算 4/4", "20 行", "CAPTCHA",
                      "Suspended: CAPTCHA", "streak=2", "streak 归零",
                      "止损判据"):
            self.assertIn(token, self.src, token)

    def test_startpage_disabled_block(self):
        m = re.search(r"- name: startpage\n\s+disabled: (true|false)",
                      self.src)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "true",
                         "startpage v3.23 两轮三观测后应为止损禁用")


# ---- 4. 版本锁 / CHANGELOG / README ----------------------------------------------------


class TestVersionSyncV323(unittest.TestCase):
    def test_versions_3230(self):
        # v3.24 起精确锁移交 test_v3240，此处降常青下限（v3.17→v3.19、
        # v3.21→v3.22、v3.22→v3.23 先例）：双 __version__ 同步本身不许破
        if mcp_server is None:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            ver = re.search(r'__version__ = "([^"]+)"', src).group(1)
        else:
            ver = mcp_server.__version__
        self.assertGreaterEqual(
            [int(x) for x in ver.split(".")], [3, 23, 0])
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        self.assertIn(f'__version__ = "{ver}"', init_src)
        self.assertIn(f"chat-scraper v{ver}", init_src)   # docstring 首行同步

    def test_changelog_has_3230(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.23.0] - 2026-09-17", changelog)
        self.assertIn("clean_worktree_test.sh", changelog)
        self.assertIn("Suspended: CAPTCHA", changelog)
        self.assertIn("probe()", changelog)

    def test_readme_badge_3230(self):
        # v3.24 起精确徽章锁移交 test_v3240，此处降常青：徽章/状态行存在
        # 且版本号与 __version__ 一致（防止换版时徽章漂移回退）
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertRegex(readme, r"release-v\d+\.\d+\.\d+")
        if mcp_server is None:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            ver = re.search(r'__version__ = "([^"]+)"', src).group(1)
        else:
            ver = mcp_server.__version__
        self.assertIn(f"v{ver}（", readme)   # 状态行随版本走


if __name__ == "__main__":
    unittest.main()
