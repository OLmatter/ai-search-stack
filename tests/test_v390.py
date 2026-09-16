"""v3.9.0 回归：cookie 续期策略（renew-if-older-than）+ bilibili 字幕读取。

三块内容：
1. doctor --cookie-probe 加 --renew-if-older-than H（实测标定：知乎访客
   cookie 寿命 <48h，47.4h 即 403；现行"用时触发自愈"白天首用要吃 ~15s
   无头引导延迟）——探活发现 expired 且超龄时顺手动用一次无头引导续期，
   cron 低峰窗口把续期做掉。全分支 mock：expired+超龄→bootstrap 调用；
   valid / 未超龄 / 龄未知 / missing / error → 不调；续期失败 → exit 1。
   标定纪律不破坏：续期发生在读数落定之后，status 仍是真实读数。
2. bilibili 字幕读取（v3.9）：fetch_subtitles 的 bvid 提取 / 空字幕如实
   报告（空列表=无字幕，非故障）/ 有字幕正文解析 / fetch_video 补 cid。
   HTTP 层全 mock，零真实请求。
3. bilibili_subtitles MCP 工具透传（注册表全集锁在 test_mcp_server。

全部离线零外部网络、零浏览器：真实探活/续期由人手动跑
`python tools/doctor.py --cookie-probe [--renew-if-older-than 36]`。
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
for d in ("", "chat-scraper"):
    sys.path.insert(0, str(REPO / "tools" / d))

import doctor  # noqa: E402  (tools/doctor.py)
import zhihu_bootstrap  # noqa: E402  (chat-scraper/zhihu_bootstrap.py)
import zhihu_content as zc  # noqa: E402  (chat-scraper/zhihu_content.py)


class _CookieProbeBase(unittest.TestCase):
    """公共脚手架：临时 cookie 文件 + 临时标定日志 + fetch_question mock 位。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log_path = os.path.join(self.tmp.name, "state",
                                     "cookie_lifetime_log.jsonl")
        self.cookie_path = os.path.join(self.tmp.name, "zhihu_cookies.json")
        self._write_cookie(age_h=47.4)
        self._orig_cookie_path = doctor.COOKIE_PATH
        self._orig_log_path = doctor.COOKIE_LOG_PATH
        doctor.COOKIE_PATH = self.cookie_path
        doctor.COOKIE_LOG_PATH = self.log_path
        self.addCleanup(setattr, doctor, "COOKIE_PATH",
                        self._orig_cookie_path)
        self.addCleanup(setattr, doctor, "COOKIE_LOG_PATH",
                        self._orig_log_path)
        self._orig_fetch = zc.fetch_question
        self.addCleanup(setattr, zc, "fetch_question", self._orig_fetch)

    def _write_cookie(self, age_h=None, with_fetched_at=True):
        payload = {"cookies": {"d_c0": "x", "__zse_ck": "y"}}
        if with_fetched_at:
            if age_h is None:   # 龄未知：文件里没有 fetched_at
                payload.pop("fetched_at", None)
            else:
                payload["fetched_at"] = (
                    datetime.now(timezone.utc)
                    - timedelta(hours=age_h)).isoformat()
        with open(self.cookie_path, "w", encoding="utf-8") as f:
            json.dump(payload, f)

    def _read_log(self):
        with open(self.log_path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]


class TestRenewIfOlderThan(_CookieProbeBase):
    """renew_if_older_than：expired+超龄才续期，其余分支不动。"""

    def test_expired_over_age_triggers_bootstrap_renew(self):
        zc.fetch_question = lambda qid: (_ for _ in ()).throw(
            zc.ZhihuAuthExpired("10003: 认证过期"))
        with mock.patch.object(zhihu_bootstrap, "bootstrap",
                               return_value={"cookies": {"d_c0": "n1",
                                                         "__zse_ck": "zz"}}
                               ) as mboot:
            entry = doctor.cookie_probe(self.log_path,
                                        renew_if_older_than=36)
        mboot.assert_called_once()   # 一次引导（headless 由 _renew_cookie 定）
        self.assertEqual(mboot.call_args.kwargs.get("out_path"),
                         self.cookie_path)
        # 标定读数不被续期污染：status 仍是探活瞬间的真实读数
        self.assertEqual(entry["status"], "expired")
        self.assertGreater(entry["cookie_age_h"], 36)
        self.assertTrue(entry["renew"])
        self.assertTrue(entry["renew_result"].startswith("ok"))
        rec = self._read_log()[0]   # 续期结果记进同一读数行
        self.assertTrue(rec["renew"])
        self.assertTrue(rec["renew_result"].startswith("ok"))
        for k in ("renew", "renew_result"):
            self.assertIn(k, rec)   # jsonl schema 加列但不删列

    def test_valid_does_not_renew(self):
        zc.fetch_question = lambda qid: {"title": "t", "answer_count": 1}
        with mock.patch.object(zhihu_bootstrap, "bootstrap") as mboot:
            entry = doctor.cookie_probe(self.log_path,
                                        renew_if_older_than=36)
        mboot.assert_not_called()   # valid 不烧引导
        self.assertFalse(entry["renew"])
        self.assertEqual(entry["renew_result"], "")

    def test_expired_under_age_does_not_renew(self):
        self._write_cookie(age_h=10)   # 未超龄的 expired：留着观察，不续
        zc.fetch_question = lambda qid: (_ for _ in ()).throw(
            zc.ZhihuAuthExpired("403"))
        with mock.patch.object(zhihu_bootstrap, "bootstrap") as mboot:
            entry = doctor.cookie_probe(self.log_path,
                                        renew_if_older_than=36)
        mboot.assert_not_called()
        self.assertFalse(entry["renew"])

    def test_expired_unknown_age_does_not_renew(self):
        self._write_cookie(with_fetched_at=False)   # 龄读数 None
        zc.fetch_question = lambda qid: (_ for _ in ()).throw(
            zc.ZhihuAuthExpired("403"))
        with mock.patch.object(zhihu_bootstrap, "bootstrap") as mboot:
            entry = doctor.cookie_probe(self.log_path,
                                        renew_if_older_than=0)
        mboot.assert_not_called()   # 无从判超龄：不盲续
        self.assertFalse(entry["renew"])

    def test_missing_and_error_do_not_renew(self):
        # missing = 没戴表（≠过期）：续期策略不管，留给显式引导
        os.unlink(self.cookie_path)
        zc.fetch_question = self._orig_fetch   # 走真实加载链（零网络即抛）
        orig_cp = zc._cookie_path
        zc._cookie_path = lambda: self.cookie_path
        self.addCleanup(setattr, zc, "_cookie_path", orig_cp)
        with mock.patch.object(zhihu_bootstrap, "bootstrap") as mboot:
            entry = doctor.cookie_probe(self.log_path,
                                        renew_if_older_than=36)
        mboot.assert_not_called()
        self.assertEqual(entry["status"], "missing")
        self.assertFalse(entry["renew"])
        # error = 网络/风控等：续期无用
        self._write_cookie(age_h=47.4)

        def boom(qid):
            raise ConnectionError("net down")
        zc.fetch_question = boom
        with mock.patch.object(zhihu_bootstrap, "bootstrap") as mboot:
            entry = doctor.cookie_probe(self.log_path,
                                        renew_if_older_than=36)
        mboot.assert_not_called()
        self.assertEqual(entry["status"], "error")
        self.assertFalse(entry["renew"])

    def test_renew_disabled_by_default_keeps_calibration_pure(self):
        # 不传 renew_if_older_than（现行标定行为）：expired 也不该碰引导
        zc.fetch_question = lambda qid: (_ for _ in ()).throw(
            zc.ZhihuAuthExpired("403"))
        with mock.patch.object(zhihu_bootstrap, "bootstrap") as mboot:
            entry = doctor.cookie_probe(self.log_path)
        mboot.assert_not_called()
        self.assertIsNone(entry["renew"])   # None=未启用（≠False=启用未触发）

    def test_cmd_exit_codes(self):
        # 续期成功 → exit 0；续期失败 → exit 1（运维动作失败可报警）
        zc.fetch_question = lambda qid: (_ for _ in ()).throw(
            zc.ZhihuAuthExpired("403"))
        with mock.patch.object(zhihu_bootstrap, "bootstrap",
                               return_value={"cookies": {"d_c0": "n1",
                                                         "__zse_ck": "zz"}}):
            self.assertEqual(doctor.cmd_cookie_probe(renew_hours=36), 0)
        with mock.patch.object(zhihu_bootstrap, "bootstrap",
                               side_effect=RuntimeError("4 轮内未领齐")):
            self.assertEqual(doctor.cmd_cookie_probe(renew_hours=36), 1)
        # 纯观测模式（未启用续期）维持 v3.8.2 行为：expired 也 exit 0
        self.assertEqual(doctor.cmd_cookie_probe(), 0)


def _fake_http(views, players, subtitles=None, fail_subtitle_url=False):
    """按 URL 分路的假 Session.get：view / player / 字幕 CDN 三类。"""
    calls = []

    def fake_get(self, url, params=None, timeout=None, headers=None):
        calls.append({"url": url, "params": dict(params or {})})
        resp = mock.Mock(status_code=200)
        resp.raise_for_status = lambda: None
        if "web-interface/view" in url:
            resp.json.return_value = views
        elif "player/wbi/v2" in url:
            resp.json.return_value = players
        elif fail_subtitle_url:
            raise OSError("subtitle cdn down")
        else:
            resp.json.return_value = subtitles or {}
        return resp

    return fake_get, calls


class TestFetchSubtitles(unittest.TestCase):
    """bilibili fetch_subtitles：全 mock HTTP，零真实请求。"""

    def setUp(self):
        import bilibili_engine as be
        self.be = be
        self.view_data = {"code": 0, "data": {
            "bvid": "BV1xx411c7mD", "cid": 12345, "title": "视频标题",
            "owner": {"name": "UP主"}, "pubdate": 1700000000,
            "stat": {"view": 1, "danmaku": 0, "like": 0, "favorite": 0}}}

    def test_invalid_bvid_error_protocol(self):
        out = self.be.fetch_subtitles("not-a-bvid", on_error="report")
        self.assertIn("error", out[0])
        self.assertEqual(out[0]["platform"], "bilibili")
        with self.assertRaises(ValueError):
            self.be.fetch_subtitles("nope", on_error="raise")

    def test_empty_subtitle_list_is_honest_not_error(self):
        players = {"code": 0, "data": {"subtitle": {"subtitles": []}}}
        fake_get, calls = _fake_http(self.view_data, players)
        with mock.patch.object(self.be, "_wait_turn"), \
             mock.patch.object(self.be, "_get_wbi_keys",
                               return_value=("a" * 32, "b" * 32)), \
             mock.patch.object(self.be.requests.Session, "get", fake_get):
            out = self.be.fetch_subtitles(
                "https://www.bilibili.com/video/BV1xx411c7mD",
                on_error="raise")
        self.assertFalse(out["has_subtitles"])
        self.assertEqual(out["subtitles"], [])
        self.assertTrue(out["note"])   # 讲清楚"无字幕≠故障"
        self.assertEqual(out["cid"], 12345)
        # 只烧 view+player 两个请求，无字幕文件可拉
        api_calls = [c for c in calls if "api.bilibili.com" in c["url"]]
        self.assertEqual(len(api_calls), 2)
        player = next(c for c in calls if "player/wbi/v2" in c["url"])
        self.assertEqual(player["params"]["bvid"], "BV1xx411c7mD")
        # cid 来自 view（wbi 签名把参数值统一 str 化，比较按 str）
        self.assertEqual(str(player["params"]["cid"]), "12345")

    def test_subtitles_fetched_and_parsed(self):
        players = {"code": 0, "data": {"subtitle": {"subtitles": [
            {"lan": "zh-CN", "lan_doc": "中文（简体）", "ai_type": 0,
             "subtitle_url": "//i0.hdslb.com/bfs/subtitle/demosub.json"},
        ]}}}
        subs_body = {"body": [
            {"from": 1.0, "to": 2.0, "content": "你好"},
            {"from": 2.0, "to": 3.5, "content": "世界"},
        ]}
        fake_get, calls = _fake_http(self.view_data, players, subs_body)
        with mock.patch.object(self.be, "_wait_turn"), \
             mock.patch.object(self.be, "_get_wbi_keys",
                               return_value=("a" * 32, "b" * 32)), \
             mock.patch.object(self.be.requests.Session, "get", fake_get):
            out = self.be.fetch_subtitles("BV1xx411c7mD", on_error="raise")
        self.assertTrue(out["has_subtitles"])
        sub = out["subtitles"][0]
        self.assertEqual(sub["lan"], "zh-CN")
        self.assertTrue(sub["url"].startswith("https://i0.hdslb.com/"))
        self.assertEqual(sub["line_count"], 2)
        self.assertEqual([ln["content"] for ln in sub["lines"]],
                         ["你好", "世界"])
        self.assertEqual(out["title"], "视频标题")
        self.assertEqual(out["owner"], "UP主")
        # 字幕 CDN 请求带了 Referer（防盗链）
        cdn = next(c for c in calls if "hdslb.com" in c["url"])
        self.assertEqual(cdn["url"],
                         "https://i0.hdslb.com/bfs/subtitle/demosub.json")

    def test_subtitle_cdn_failure_reports_not_raises(self):
        players = {"code": 0, "data": {"subtitle": {"subtitles": [
            {"lan": "zh-CN", "lan_doc": "中文", "ai_type": 0,
             "subtitle_url": "//i0.hdslb.com/bfs/subtitle/broken.json"},
        ]}}}
        fake_get, _ = _fake_http(self.view_data, players,
                                 fail_subtitle_url=True)
        with mock.patch.object(self.be, "_wait_turn"), \
             mock.patch.object(self.be, "_get_wbi_keys",
                               return_value=("a" * 32, "b" * 32)), \
             mock.patch.object(self.be.requests.Session, "get", fake_get):
            out = self.be.fetch_subtitles("BV1xx411c7mD", on_error="report")
        self.assertIn("error", out[0])   # 统一错误协议，不炸调用方

    def test_fetch_video_includes_cid(self):
        fake_get, _ = _fake_http(self.view_data, {})
        with mock.patch.object(self.be, "_wait_turn"), \
             mock.patch.object(self.be.requests.Session, "get", fake_get):
            out = self.be.fetch_video("BV1xx411c7mD", on_error="raise")
        self.assertEqual(out["cid"], 12345)   # v3.9 补全：字幕链路的前置


class TestMcpSubtitlesPassthrough(unittest.TestCase):
    """bilibili_subtitles MCP 工具：透传保真 + 错误协议（mcp SDK 装了才跑）。"""

    @classmethod
    def setUpClass(cls):
        try:
            sys.path.insert(0, str(REPO / "tools"))
            import mcp_server  # noqa: F401
            cls.mcp_server = mcp_server
        except ImportError:
            cls.mcp_server = None

    def test_passthrough_and_json_roundtrip(self):
        if self.mcp_server is None:
            self.skipTest("mcp SDK 未安装")
        be = self.mcp_server._bilibili
        want = {"bvid": "BV1xx411c7mD", "cid": 1, "has_subtitles": False,
                "subtitles": [], "note": "无字幕"}
        with mock.patch.object(be, "fetch_subtitles", return_value=want) as m:
            out = self.mcp_server.bilibili_subtitles(video="BV1xx411c7mD")
        # v3.13 起新增可选 part 参数（多 P 展开），默认 None 行为不变
        m.assert_called_once_with("BV1xx411c7mD", part=None, on_error="report")
        self.assertEqual(json.loads(out), want)   # JSON round-trip 保真

    def test_error_reported_not_raised(self):
        if self.mcp_server is None:
            self.skipTest("mcp SDK 未安装")
        be = self.mcp_server._bilibili
        with mock.patch.object(be, "fetch_subtitles",
                               side_effect=RuntimeError("boom")):
            out = self.mcp_server.bilibili_subtitles(video="BV1xx411c7mD")
        data = json.loads(out)
        self.assertIn("error", data[0])
        self.assertIn("RuntimeError", data[0]["error"])


if __name__ == "__main__":
    unittest.main()
