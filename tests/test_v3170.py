"""v3.17.0 回归：worker_queue 派工队列认领机制（多 worker 并行领队列互踩的
修复）+ 版本锁 3.17.0。

两块内容（全部离线，零真实请求、零浏览器、不碰真实 ~/.zcode/worker_queue.json）：
1. tools/chat-scraper/worker_queue.py：认领互斥（第二个 worker skipped 且
   能看到持有者）/认领超时重新认领（timeout_s=0 立即超时 → reclaimed，读回
   校验保证并发接管单一赢家）/完成清空（complete 只删自己的标记，别人的
   删不掉；clear 原子写回空队列）/损坏标记自愈（坏 JSON/缺字段视为陈旧走
   接管）/认领标记是伴生文件绝不写队列文件本身。
   实证背景：v3.16 的 848065c 与并行班次工作树编辑逐字一致 = 互踩证据；
   本班次实施期间第二次实时互踩（test_v3160.py 双方同改，Edit 冲突检测
   挡下覆盖）——机制动机两次实证。
2. 版本锁 3.17.0（v3.18 起转常青下限，v3.13->v3.14 先例；精确锁移交
   test_v3180）。
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "chat-scraper"))
sys.path.insert(0, str(REPO / "tools"))

import worker_queue as wq          # noqa: E402

try:
    import mcp_server              # noqa: E402
except ImportError:                # mcp SDK 未安装（部分 CI）——版本锁降级源码断言
    mcp_server = None


# ---- 1. worker_queue 认领机制 ----------------------------------------------------


class TestWorkerQueueClaim(unittest.TestCase):
    """claim/complete/clear：互斥、超时重认领、完成清空、损坏自愈。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.queue = os.path.join(self.tmp.name, "worker_queue.json")
        with open(self.queue, "w", encoding="utf-8") as f:
            json.dump({"instructions": "v3.17 派工内容"}, f)

    def _claim_file(self):
        return self.queue + wq.CLAIM_SUFFIX

    def test_first_claim_wins(self):
        r = wq.claim(self.queue, worker_id="worker-A")
        self.assertEqual(r["status"], "claimed")
        self.assertEqual(r["worker_id"], "worker-A")
        marker = wq.read_claim(self.queue)
        self.assertEqual(marker["claimed_by"], "worker-A")
        self.assertGreaterEqual(marker["age_s"], 0.0)

    def test_second_claim_skipped_and_sees_owner(self):
        wq.claim(self.queue, worker_id="worker-A")
        r = wq.claim(self.queue, worker_id="worker-B")
        self.assertEqual(r["status"], "skipped")
        self.assertEqual(r["owner"], "worker-A")
        self.assertGreaterEqual(r["age_s"], 0.0)
        # 持有者仍是谁只有 A——B 没有写任何东西
        self.assertEqual(wq.read_claim(self.queue)["claimed_by"], "worker-A")

    def test_timeout_allows_reclaim(self):
        wq.claim(self.queue, worker_id="worker-A")
        r = wq.claim(self.queue, worker_id="worker-B", timeout_s=0)
        self.assertEqual(r["status"], "reclaimed")
        self.assertEqual(r["prev_owner"], "worker-A")
        self.assertEqual(wq.read_claim(self.queue)["claimed_by"], "worker-B")

    def test_valid_claim_within_timeout_not_reclaimable(self):
        wq.claim(self.queue, worker_id="worker-A")
        r = wq.claim(self.queue, worker_id="worker-B", timeout_s=3600)
        self.assertEqual(r["status"], "skipped")   # 1 小时门槛，刚认领不可抢

    def test_claim_is_sidecar_queue_untouched(self):
        with open(self.queue, encoding="utf-8") as f:
            before = f.read()
        wq.claim(self.queue, worker_id="worker-A")
        with open(self.queue, encoding="utf-8") as f:
            after = f.read()
        self.assertEqual(before, after)            # 认领绝不写队列文件本身

    def test_complete_removes_own_claim_and_allows_reclaim(self):
        wq.claim(self.queue, worker_id="worker-A")
        self.assertTrue(wq.complete(self.queue, worker_id="worker-A"))
        self.assertIsNone(wq.read_claim(self.queue))
        r = wq.claim(self.queue, worker_id="worker-B")
        self.assertEqual(r["status"], "claimed")   # 完成后队列立即可再认领

    def test_complete_rejects_foreign_claim(self):
        wq.claim(self.queue, worker_id="worker-A")
        self.assertFalse(wq.complete(self.queue, worker_id="worker-B"))
        self.assertEqual(wq.read_claim(self.queue)["claimed_by"],
                         "worker-A")               # 别人的标记删不掉

    def test_complete_after_reclaim_original_owner_loses(self):
        # A 认领 → 超时被 B 接管（标记已覆盖为 B）→ A 的 complete 必须 False
        # （读回校验路径：A 不能删掉 B 的活标记）
        wq.claim(self.queue, worker_id="worker-A")
        wq.claim(self.queue, worker_id="worker-B", timeout_s=0)
        self.assertFalse(wq.complete(self.queue, worker_id="worker-A"))
        self.assertTrue(wq.complete(self.queue, worker_id="worker-B"))

    def test_corrupt_claim_json_taken_over(self):
        with open(self._claim_file(), "w", encoding="utf-8") as f:
            f.write("{not valid json")
        r = wq.claim(self.queue, worker_id="worker-B")
        self.assertEqual(r["status"], "reclaimed")
        self.assertIsNone(r["prev_owner"])         # 损坏无主可报

    def test_corrupt_claim_missing_fields_taken_over(self):
        with open(self._claim_file(), "w", encoding="utf-8") as f:
            json.dump({"foo": 1}, f)               # 缺 claimed_by/claimed_at
        r = wq.claim(self.queue, worker_id="worker-B")
        self.assertEqual(r["status"], "reclaimed")

    def test_corrupt_claim_non_numeric_at_taken_over(self):
        with open(self._claim_file(), "w", encoding="utf-8") as f:
            json.dump({"claimed_by": "x", "claimed_at": "yesterday"}, f)
        r = wq.claim(self.queue, worker_id="worker-B")
        self.assertEqual(r["status"], "reclaimed")

    def test_clear_resets_queue_payload(self):
        wq.claim(self.queue, worker_id="worker-A")
        wq.complete(self.queue, worker_id="worker-A")
        wq.clear(self.queue)
        with open(self.queue, encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"instructions": ""})

    def test_default_worker_id_shape(self):
        wid = wq._default_worker_id()
        self.assertIn(":", wid)                    # hostname:pid 形态
        self.assertTrue(wid.split(":", 1)[1].isdigit())


# ---- 2. 版本锁 3.17.0 ------------------------------------------------------------


class TestVersionSyncV317(unittest.TestCase):
    def test_versions_not_older_than_3170(self):
        # v3.18 起改为常青下限（v3.13->v3.14 先例）：精确锁当前版本是
        # test_v3180 的职责
        import re
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        ver = re.search(r'__version__ = "([^"]+)"', init_src).group(1)
        self.assertGreaterEqual(
            tuple(int(x) for x in ver.split(".")), (3, 17, 0))
        self.assertIn(f"chat-scraper v{ver}", init_src)   # docstring 首行同步
        if mcp_server is None:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            mver = re.search(r'__version__ = "([^"]+)"', src).group(1)
        else:
            mver = mcp_server.__version__
        self.assertGreaterEqual(
            tuple(int(x) for x in mver.split(".")), (3, 17, 0))

    def test_changelog_has_3170(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.17.0] - 2026-09-16", changelog)

    def test_worker_queue_module_documented(self):
        src = (REPO / "tools" / "chat-scraper" / "worker_queue.py"
               ).read_text(encoding="utf-8")
        for token in ("认领", "O_EXCL", "os.replace", "timeout_s",
                      "848065c"):   # 实证互踩背景必须写在模块 docstring
            self.assertIn(token, src)


if __name__ == "__main__":
    unittest.main()
