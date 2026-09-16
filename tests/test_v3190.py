"""v3.19.0 回归：claim 固化进领活入口（根因修复）+ SearXNG 单引擎回滚
判据 + 版本锁 3.19.0。

三块内容（全部离线，零真实请求、零浏览器、不碰真实 ~/.zcode/worker_queue.json）：
1. worker_queue.acquire()：领活唯一入口——认领+读队列一步完成。v3.17 的
   claim() 三版被实证零使用（并行 worker 领活不查 sidecar 直接干活），
   根因修复 = 调用路径固化：skipped 不返回 instructions（活内容不外泄，
   机制上杜绝"看到活就干"）；claimed 才拿得到活；no_queue 不认领不留
   sidecar；接管归一为 claimed + reclaimed_from。
2. hooks/stop_wake.py（仓库真源）：should_block 决策——有活+有效认领
   放行（活有主，唤醒第二个=制造互踩）；有活+无认领/超时/损坏 → block
   且理由文本自带领活固定入口强制条款；wq 模块不可达放行（可见降级）。
3. settings.yml 单引擎粒度回滚判据：每引擎独立两关（单发探活 + 该引擎
   回滚启用 restart 后聚合 unresponsive 清零），不再三引擎整组绑定——
   v3.18 实证 startpage 单发恢复而 brave/ddg 复发，整组判据会把可救的
   引擎和无救的引擎绑死。
"""
import json
import os
import pathlib
import re
import sys
import tempfile
import time
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "chat-scraper"))
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tools" / "chat-scraper" / "hooks"))

import worker_queue as wq          # noqa: E402
import stop_wake                   # noqa: E402

try:
    import mcp_server              # noqa: E402
except ImportError:                # mcp SDK 未安装（部分 CI）——版本锁降级源码断言
    mcp_server = None


# ---- 1. acquire()：领活固定入口 ---------------------------------------------------


class TestAcquireEntry(unittest.TestCase):
    """acquire()：认领+读队列原子入口，skipped 不泄漏活内容。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.queue = os.path.join(self.tmp.name, "worker_queue.json")

    def _write_queue(self, instructions):
        with open(self.queue, "w", encoding="utf-8") as f:
            json.dump({"instructions": instructions}, f)

    def test_claimed_with_instructions(self):
        self._write_queue("v3.19 派工内容")
        r = wq.acquire(self.queue, worker_id="worker-A")
        self.assertEqual(r["status"], "claimed")
        self.assertEqual(r["worker_id"], "worker-A")
        self.assertEqual(r["instructions"], "v3.19 派工内容")
        self.assertIsNone(r["reclaimed_from"])
        self.assertIsNotNone(wq.read_claim(self.queue))   # sidecar 已建立

    def test_claimed_empty_queue_instructions_empty(self):
        self._write_queue("")
        r = wq.acquire(self.queue, worker_id="worker-A")
        self.assertEqual(r["status"], "claimed")
        self.assertEqual(r["instructions"], "")     # 空活：应 complete 收工

    def test_no_queue_no_claim_no_sidecar(self):
        r = wq.acquire(self.queue, worker_id="worker-A")
        self.assertEqual(r["status"], "no_queue")
        self.assertFalse(os.path.exists(            # 不认领、不留 sidecar
            self.queue + wq.CLAIM_SUFFIX))

    def test_skipped_does_not_leak_instructions(self):
        # 根因 pin：他人持有时，活的内容绝不经过 skipped 返回值外泄——
        # 上轮互踩形态正是"看到活就干"，入口层从机制上断掉这条路
        self._write_queue("机密派工内容-A-的活")
        wq.acquire(self.queue, worker_id="worker-A")
        r = wq.acquire(self.queue, worker_id="worker-B")
        self.assertEqual(r["status"], "skipped")
        self.assertNotIn("instructions", r)
        self.assertNotIn("机密派工内容-A-的活", json.dumps(r))
        self.assertEqual(r["owner"], "worker-A")

    def test_lifecycle_acquire_complete_clear(self):
        self._write_queue("完整生命周期")
        r = wq.acquire(self.queue, worker_id="worker-A")
        self.assertEqual(r["status"], "claimed")
        self.assertTrue(wq.complete(self.queue, worker_id="worker-A"))
        wq.clear(self.queue)
        with open(self.queue, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"instructions": ""})
        # 清空后 B 可正常 acquire（no-op 空活）
        r2 = wq.acquire(self.queue, worker_id="worker-B")
        self.assertEqual(r2["status"], "claimed")
        self.assertEqual(r2["instructions"], "")

    def test_takeover_normalized_to_claimed_with_prev_owner(self):
        self._write_queue("被接管的活")
        wq.acquire(self.queue, worker_id="worker-A")
        r = wq.acquire(self.queue, worker_id="worker-B", timeout_s=0)
        self.assertEqual(r["status"], "claimed")    # 接管归一为 claimed
        self.assertEqual(r["instructions"], "被接管的活")
        self.assertEqual(r["reclaimed_from"], "worker-A")

    def test_two_workers_entry_level_mutual_exclusion(self):
        # 入口层并发语义：A 先 acquire，B acquire 必须 skipped（入口即互斥，
        # 不依赖调用方记得先 claim）
        self._write_queue("只能一个人干的活")
        ra = wq.acquire(self.queue, worker_id="worker-A")
        rb = wq.acquire(self.queue, worker_id="worker-B")
        self.assertEqual(ra["status"], "claimed")
        self.assertEqual(rb["status"], "skipped")
        owners = {ra["worker_id"], rb.get("owner")}
        self.assertNotIn(None, {ra["worker_id"]})
        self.assertEqual(ra["worker_id"], "worker-A")
        self.assertEqual(rb["owner"], "worker-A")

    def test_corrupt_queue_reads_as_empty(self):
        self._write_queue("将被写坏")
        with open(self.queue, "w", encoding="utf-8") as f:
            f.write("{broken json")
        r = wq.acquire(self.queue, worker_id="worker-A")
        self.assertEqual(r["status"], "claimed")
        self.assertEqual(r["instructions"], "")     # 损坏如实视为无活

    def test_non_string_instructions_reads_as_empty(self):
        with open(self.queue, "w", encoding="utf-8") as f:
            json.dump({"instructions": 123}, f)
        r = wq.acquire(self.queue, worker_id="worker-A")
        self.assertEqual(r["instructions"], "")     # 非 str 字段不外泄不崩溃

    def test_acquired_instructions_survive_sidecar_read(self):
        # 认领绝不写队列文件本身（v3.17 语义在入口层保持）
        self._write_queue("本体不变验证")
        with open(self.queue, encoding="utf-8") as f:
            before = f.read()
        wq.acquire(self.queue, worker_id="worker-A")
        with open(self.queue, encoding="utf-8") as f:
            after = f.read()
        self.assertEqual(before, after)


# ---- 2. stop_wake.should_block：唤醒层收口 -----------------------------------------


class TestStopWakeDecision(unittest.TestCase):
    """should_block：None=放行；str=block（理由自带强制条款）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.queue = os.path.join(self.tmp.name, "worker_queue.json")

    def _write_queue(self, instructions):
        with open(self.queue, "w", encoding="utf-8") as f:
            json.dump({"instructions": instructions}, f)

    def _claim_fresh(self, worker_id="worker-A"):
        wq.claim(self.queue, worker_id=worker_id)

    def test_no_queue_passes(self):
        self.assertIsNone(stop_wake.should_block(self.queue, wq=wq))

    def test_empty_instructions_passes(self):
        self._write_queue("")
        self.assertIsNone(stop_wake.should_block(self.queue, wq=wq))

    def test_wq_unreachable_passes(self):
        # 模块不可达（wq=None 强制路径）→ 放行不抛异常（可见降级由
        # main 的 stderr 负责）；不传 wq 才是自动探测，_UNSET 哨兵区分
        self._write_queue("有活但探测失败")
        self.assertIsNone(stop_wake.should_block(self.queue, wq=None))

    def test_active_task_unclaimed_blocks_with_clause(self):
        self._write_queue("无人认领的活")
        r = stop_wake.should_block(self.queue, wq=wq)
        self.assertIsInstance(r, str)
        self.assertIn("无人认领的活", r)
        self.assertIn("acquire()", r)               # 强制条款：固定入口
        self.assertIn("skipped", r)                 # 条款含 skipped 语义
        self.assertIn("complete()", r)              # 条款含完成动作

    def test_active_task_foreign_valid_claim_passes(self):
        # 互踩预防在唤醒层收口：活有主（30 分钟内）→ 不唤醒第二个
        self._write_queue("已有主人的活")
        self._claim_fresh("worker-A")
        self.assertIsNone(stop_wake.should_block(self.queue, wq=wq))

    def test_expired_claim_blocks_again(self):
        self._write_queue("持有者失联的活")
        marker = {"claimed_by": "worker-dead", "claimed_at": time.time()}
        with open(self.queue + wq.CLAIM_SUFFIX, "w", encoding="utf-8") as f:
            json.dump(marker, f)
        # 未超时 → 放行
        self.assertIsNone(stop_wake.should_block(self.queue, wq=wq))
        # 人为老化超过 30 分钟 → 恢复拦截（超时自然解封）
        marker["claimed_at"] = time.time() - (wq.DEFAULT_CLAIM_TIMEOUT_S + 5)
        with open(self.queue + wq.CLAIM_SUFFIX, "w", encoding="utf-8") as f:
            json.dump(marker, f)
        r = stop_wake.should_block(self.queue, wq=wq)
        self.assertIsInstance(r, str)
        self.assertIn("acquire()", r)

    def test_corrupt_claim_blocks_again(self):
        # 损坏标记（read_claim 返回 None）→ 视同无人认领，block 让下一个
        # worker 走 acquire() 接管自愈
        self._write_queue("损坏标记下的活")
        with open(self.queue + wq.CLAIM_SUFFIX, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        r = stop_wake.should_block(self.queue, wq=wq)
        self.assertIsInstance(r, str)

    def test_corrupt_queue_file_passes(self):
        with open(self.queue, "w", encoding="utf-8") as f:
            f.write("{broken")
        self.assertIsNone(stop_wake.should_block(self.queue, wq=wq))

    def test_hook_source_pinned_in_repo(self):
        # 单一真源：hook 真源必须在仓库内，且 docstring 带强制条款与
        # 真源-部署关系声明（部署副本 ~/.zcode/hooks/ 不进 CI pin）
        src = (REPO / "tools" / "chat-scraper" / "hooks" / "stop_wake.py"
               ).read_text(encoding="utf-8")
        for token in ("acquire()", "禁止绕过入口", "848065c",
                      "真源", "decision"):
            self.assertIn(token, src)
        self.assertIn("worker_queue.json", src)


# ---- 3. settings.yml 单引擎粒度回滚判据 ---------------------------------------------


class TestSearxngSingleEngineCriterion(unittest.TestCase):
    """settings.yml：单引擎独立两关判据（不再三引擎整组绑定）。"""

    def setUp(self):
        self.src = (REPO / "tools" / "searxng" / "docker" / "searxng"
                    / "settings.yml").read_text(encoding="utf-8")

    def test_single_engine_criterion_documented(self):
        for token in ("单引擎", "两关", "v3.19"):
            self.assertIn(token, self.src)

    def test_engine_states_match_observation(self):
        # 禁用状态必须与本轮实测观察记录一致（settings.yml v3.20 段）：
        # brave 第一关过但第二关聚合复发 → disabled（其"单发过"四轮证明
        # 不可信）；duckduckgo 两关双过 → 回滚启用；startpage v3.19 双过
        # → 维持 enabled。任何状态变更必须先改 settings.yml 观察记录再改
        # 这里（v3.15/v3.16 的"三引擎全禁"旧 pin 已按 v3.19/v3.20 实测
        # 适配——行为先例：v3.18 对 test_v3160 obsolete pins 的处理）
        for engine, want in (("brave", True), ("duckduckgo", False),
                             ("startpage", False)):
            block = re.search(
                rf"- name: {engine}\n\s+disabled: (true|false)", self.src)
            self.assertIsNotNone(block, engine)
            got = block.group(1) == "true"
            self.assertEqual(got, want,
                             f"{engine}: settings disabled={block.group(1)}"
                             f" != 观察记录 {want}")


# ---- 4. 版本锁 3.19.0 ---------------------------------------------------------------


class TestVersionSyncV319(unittest.TestCase):
    def test_versions_3190(self):
        # 精确锁当前版本（v3.17/v3.18 先例：上一版 test_v3180 同步降常青）
        if mcp_server is None:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            ver = re.search(r'__version__ = "([^"]+)"', src).group(1)
        else:
            ver = mcp_server.__version__
        parts = tuple(int(x) for x in ver.split("."))
        self.assertGreaterEqual(parts, (3, 19, 0))   # 常青下限（v3.19 先例）
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        self.assertIn(f'__version__ = "{ver}"', init_src)
        self.assertIn(f"chat-scraper v{ver}", init_src)   # docstring 首行同步

    def test_changelog_has_3190(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.19.0] - 2026-09-16", changelog)

    def test_acquire_documented_in_module(self):
        src = (REPO / "tools" / "chat-scraper" / "worker_queue.py"
               ).read_text(encoding="utf-8")
        for token in ("领活唯一入口", "不返回 instructions", "no_queue",
                      "零使用"):
            self.assertIn(token, src)


if __name__ == "__main__":
    unittest.main()
