"""v3.8.2 回归：doctor --cookie-probe 寿命标定 + v3.8.1 Host 白名单审计复核。

两块内容：
1. cookie 寿命标定（doctor.cookie_probe）：读数四态 valid/expired/missing/error
   全分支 mock（零真实请求）、jsonl 日志格式、探活期间自愈禁用（标定要的是
   cookie 真实寿命——过期即自愈会把每条 expired 读数"续命"，分布永远测不出）。
2. v3.8.2 审计确认轮对 v3.8.1 Host 白名单的边界复核补强：空白 Host、前导零
   端口、空端口段、裸 IPv6、大小写不敏感对称（test_v381 已覆盖主干，本文件
   只补刁钻边界）。外加 README 徽章版本与 __version__ 一致性锁（防徽章再滞后
   ——v3.7.0→v3.8.1 徽章替换失败即本教训）。

全部离线零外部网络：知乎请求一律 mock（真实探活由人手动跑
`python tools/doctor.py --cookie-probe`，不走测试）。
"""
import email.message
import json
import os
import pathlib
import re
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

REPO = pathlib.Path(__file__).resolve().parent.parent
for d in ("", "chat-scraper", "google-bridge"):
    sys.path.insert(0, str(REPO / "tools" / d))

import doctor  # noqa: E402  (tools/doctor.py)
import server as chat_server  # noqa: E402  (chat-scraper/server.py)
import search_helper  # noqa: E402  (google-bridge/search_helper.py)
import zhihu_content as zc  # noqa: E402  (chat-scraper/zhihu_content.py)


class TestCookieProbe(unittest.TestCase):
    """doctor.cookie_probe：全分支 mock，零真实网络。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log_path = os.path.join(self.tmp.name, "state",
                                     "cookie_lifetime_log.jsonl")
        # 假 cookie 文件：fetched_at = 24h 前（龄读数可精确断言）
        fixed = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        self.cookie_path = os.path.join(self.tmp.name, "zhihu_cookies.json")
        with open(self.cookie_path, "w", encoding="utf-8") as f:
            json.dump({"fetched_at": fixed, "cookies": {"d_c0": "x"}}, f)
        self._orig_cookie_path = doctor.COOKIE_PATH
        doctor.COOKIE_PATH = self.cookie_path
        self.addCleanup(setattr, doctor, "COOKIE_PATH",
                        self._orig_cookie_path)
        self._orig_fetch = zc.fetch_question
        self.addCleanup(setattr, zc, "fetch_question", self._orig_fetch)

    def _read_log(self):
        with open(self.log_path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_valid_branch_appends_jsonl(self):
        zc.fetch_question = lambda qid: {"title": "测试问题", "answer_count": 3}
        entry = doctor.cookie_probe(self.log_path)
        self.assertEqual(entry["status"], "valid")
        # jsonl 格式：子目录自动创建、单行合法 JSON、必备字段齐全
        recs = self._read_log()
        self.assertEqual(len(recs), 1)
        rec = recs[0]
        for k in ("ts", "tool", "question_id", "fetched_at", "cookie_age_h",
                  "status", "note"):
            self.assertIn(k, rec)
        self.assertEqual(rec["status"], "valid")
        self.assertEqual(rec["question_id"], doctor.PROBE_QUESTION_ID)
        # cookie 龄读数 ≈ 24h（fetched_at 注入为 24h 前）
        self.assertAlmostEqual(rec["cookie_age_h"], 24.0, delta=0.1)
        # 追加语义：再探一次 → 两行
        doctor.cookie_probe(self.log_path)
        self.assertEqual(len(self._read_log()), 2)

    def test_expired_branch_recorded(self):
        def boom(qid):
            raise zc.ZhihuAuthExpired("10003: 签名被拒（认证过期）")
        zc.fetch_question = boom
        entry = doctor.cookie_probe(self.log_path)
        self.assertEqual(entry["status"], "expired")
        self.assertIn("10003", entry["note"])
        recs = self._read_log()
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["status"], "expired")

    def test_missing_cookie_file_uses_real_loader(self):
        # cookie 文件整个缺失：走 zhihu_content 真实加载链（零网络——
        # _load_session_state 在发请求前就抛 _CookieStateMissing）
        missing = os.path.join(self.tmp.name, "nope.json")
        doctor.COOKIE_PATH = missing
        orig_cp = zc._cookie_path
        zc._cookie_path = lambda: missing
        self.addCleanup(setattr, zc, "_cookie_path", orig_cp)
        zc.fetch_question = self._orig_fetch   # 恢复真实 fetch_question
        entry = doctor.cookie_probe(self.log_path)
        self.assertEqual(entry["status"], "missing")   # ≠ expired，分开记
        self.assertIsNone(entry["fetched_at"])
        self.assertIn("不存在", entry["note"])

    def test_error_branch_recorded(self):
        # 网络/风控等其他异常 → status=error，不污染 valid/expired 两类主读数
        def boom(qid):
            raise ConnectionError("net down")
        zc.fetch_question = boom
        entry = doctor.cookie_probe(self.log_path)
        self.assertEqual(entry["status"], "error")
        self.assertIn("ConnectionError", entry["note"])

    def test_self_heal_disabled_during_probe_and_restored(self):
        # 标定纪律：探活期间 _try_self_heal 必须被禁用（lambda: False），
        # 且探活结束后恢复原函数（不影响同一进程内其他调用方的自愈能力）
        seen = {}

        def spy(qid):
            seen["during"] = zc._try_self_heal
            return {"title": "t", "answer_count": 0}
        zc.fetch_question = spy
        before = zc._try_self_heal
        doctor.cookie_probe(self.log_path)
        self.assertIsNot(seen["during"], before)
        self.assertFalse(seen["during"]())   # 禁用版：调用直接返回 False
        self.assertIs(zc._try_self_heal, before)   # 探后已恢复


class TestHostBoundaryAuditV382(unittest.TestCase):
    """v3.8.1 Host 白名单的复核补强（v3.8.2 审计确认轮）。"""

    def test_chat_host_allowed_extra_boundaries(self):
        f = chat_server._host_allowed
        # 首尾空白由 strip 吃掉（requests/手搓客户端都可能带）
        self.assertTrue(f(" 127.0.0.1:8765 ", 8765))
        self.assertTrue(f("\tlocalhost:8765\n", 8765))
        # 前导零端口 ≠ "8765"（字符串全等比较，fail closed）
        self.assertFalse(f("127.0.0.1:08765", 8765))
        # 空端口段
        self.assertFalse(f("localhost:", 8765))
        # 裸 IPv6 即使带端口也认不出（本服务只绑 127.0.0.1，IPv6 本就不可达）
        self.assertFalse(f("::1:8765", 8765))

    def test_search_helper_host_ok_extra_boundaries(self):
        def mk(host_value):
            sh = search_helper.SearchHandler.__new__(
                search_helper.SearchHandler)
            msg = email.message.Message()
            if host_value is not None:
                msg["Host"] = host_value
            sh.headers = msg
            sh.server = type("S", (), {"server_address":
                                       ("127.0.0.1", 18799)})()
            return sh
        self.assertTrue(mk("LocalHost:18799")._host_ok())   # 大小写对称
        self.assertFalse(mk("127.0.0.1:018799")._host_ok())  # 前导零端口
        self.assertFalse(mk("localhost:")._host_ok())        # 空端口段
        self.assertFalse(mk("  ")._host_ok())                # 纯空白 Host


class TestVersionConsistency(unittest.TestCase):
    """README 徽章 / CHANGELOG / __version__ 三处一致（防徽章再滞后）。"""

    def test_readme_badge_matches_version(self):
        init = (REPO / "tools" / "chat-scraper" / "__init__.py"
                ).read_text(encoding="utf-8")
        ver = re.search(r'__version__ = "([^"]+)"', init).group(1)
        mcp = (REPO / "tools" / "mcp_server.py").read_text(encoding="utf-8")
        self.assertIn(f'__version__ = "{ver}"', mcp)
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"release-v{ver}", readme)          # badge 文本
        self.assertIn(f"releases/tag/v{ver}", readme)     # badge 链接
        self.assertNotIn("release-v3.7.0", readme)        # 本轮教训
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn(f"## [{ver}]", changelog)


if __name__ == "__main__":
    unittest.main()
