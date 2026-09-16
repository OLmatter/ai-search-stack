"""v3.13.0 回归：搜狗连发风控阈值标定（--probe）+ bilibili 多 P 展开
（fetch_video/fetch_subtitles ?p=N）。

三块内容（全部离线，零真实请求、零浏览器）：
1. 搜狗阈值标定：probe_burst 连发探测——绕过引擎默认节流（探测目的就是
   测短间隔）、每请求读数追加 jsonl（tmp 路径验证落账格式）、首个风控
   读数（antispider 重定向 / 0 行软风控）即停不烧多余请求、网络异常记
   error 读数即停、log_path=None 不落账。风控判定抽 helper（_blocked /
   _soft_blocked）与 search() 逐字共用——search() 主风控/软风控行为
   回归钉死（helper 重构零语义漂移）。
2. bilibili 多 P：URL ?p=N 自动提取 / 显式 part 参数（优先于 URL）/
   默认 P1 行为不变；_resolve_cid 多 P 取对应分 P 的 cid 与标题、超界
   抛错含合法范围、无 pages 旧形态回退 data.cid（v390 旧 fixture 兼容）、
   pages 条目缺 cid 如实报错；fetch_video 输出 page/part_title/
   pages_count、分 P>1 时 url 带 ?p=N；fetch_subtitles 用指定分 P 的
   cid 签 player 请求（参数级验证）。
3. 版本一致性：mcp_server 与 chat-scraper __version__ 同步 3.13.0；
   MCP bilibili_video 透传新增 part 参数（默认 None 行为不变）。
"""
import json
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

import requests

REPO = pathlib.Path(__file__).resolve().parent.parent
for d in ("", "chat-scraper"):
    sys.path.insert(0, str(REPO / "tools" / d))

import bilibili_engine as be       # noqa: E402  (chat-scraper/bilibili_engine.py)
import sogou_engine as se          # noqa: E402  (chat-scraper/sogou_engine.py)


class _Resp:
    """最小 HTTP 响应桩：status_code/url/text 三件套。"""

    def __init__(self, text="", status_code=200,
                 url="https://www.sogou.com/web?query=x"):
        self.text = text
        self.status_code = status_code
        self.url = url


_SOGOU_OK = """
<div class="vrwrap" data-url="https://example.com/1">
  <h3><a href="/link?url=a1">标题一</a></h3><p class="space-txt">摘要一</p>
</div>
<div class="vrwrap" data-url="https://example.com/2">
  <h3><a href="/link?url=a2">标题二</a></h3><p class="space-txt">摘要二</p>
</div>
"""


# ---- 1. 搜狗连发阈值标定 ----------------------------------------------------


class TestSogouProbeBurst(unittest.TestCase):
    """probe_burst：连发探测 + jsonl 落账 + 风控即停。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.log_path = str(pathlib.Path(self.tmpdir.name) / "probe_log.jsonl")
        self.calls = []

    def tearDown(self):
        self.tmpdir.cleanup()
        with se._throttle_lock:
            se._last_request_ts = 0.0

    def _run(self, responses, **kw):
        """responses: 按请求顺序的 _Resp 列表（耗尽即测试自身写错页数的护栏）。"""
        it = iter(responses)

        def fake_get(session, url, **kwargs):
            self.calls.append(url)
            return next(it)

        with mock.patch.object(requests.Session, "get", fake_get), \
             mock.patch.object(se.time, "sleep"):
            return se.probe_burst(log_path=kw.pop("log_path", self.log_path),
                                  **kw)

    def _read_log(self):
        with open(self.log_path, encoding="utf-8") as f:
            return [json.loads(ln) for ln in f if ln.strip()]

    def test_all_ok_records_each_request(self):
        readings = self._run([_Resp(_SOGOU_OK)] * 4, count=4, interval=2.0)
        self.assertEqual(len(readings), 4)
        self.assertTrue(all(not r["blocked"] for r in readings))
        self.assertEqual([r["seq"] for r in readings], [0, 1, 2, 3])
        self.assertEqual([r["http"] for r in readings], [200] * 4)
        self.assertEqual([r["rows"] for r in readings], [2] * 4)
        # 读数逐行落账（每请求一行，非收尾一次写）
        logged = self._read_log()
        self.assertEqual(len(logged), 4)
        self.assertEqual(logged[0]["tool"], "sogou_engine --probe")

    def test_stops_on_antispider_redirect(self):
        # 前 4 发过审，第 5 发 302 到 antispider 页（2026-09-16 实测形态）
        responses = [_Resp(_SOGOU_OK)] * 4 + [
            _Resp("", status_code=200,
                  url="https://www.sogou.com/antispider/?m=1&antip=web_sh2")]
        readings = self._run(responses, count=6, interval=2.0)
        self.assertEqual(len(self.calls), 5)   # 风控即停，第 6 发不发
        self.assertEqual(len(readings), 5)
        self.assertTrue(readings[-1]["blocked"])
        self.assertIn("antispider", readings[-1]["note"])
        self.assertFalse(any(r["blocked"] for r in readings[:-1]))

    def test_stops_on_soft_block_zero_rows(self):
        # HTTP 200 但 0 行解析 + 全文有验证码标记 → 软风控（审查 B2 判据）
        responses = [_Resp(_SOGOU_OK),
                     _Resp("<html>请输入验证码继续访问</html>")]
        readings = self._run(responses, count=4, interval=2.0)
        self.assertEqual(len(self.calls), 2)
        self.assertTrue(readings[-1]["blocked"])
        self.assertEqual(readings[-1]["rows"], 0)

    def test_normal_results_with_risk_words_not_blocked(self):
        # 正常结果含风险词（如搜"反爬虫"主题，标题/摘要带 antispider）不
        # 误杀（审查 B2：全文标记只准在 0 行时参与判定）
        html = ('<div class="vrwrap" data-url="https://example.com/x">'
                '<h3><a href="/link?url=x">如何绕过 antispider 检测</a></h3>'
                "<p>反爬虫策略分析</p></div>")
        readings = self._run([_Resp(html)], count=1, interval=2.0)
        self.assertFalse(readings[0]["blocked"])
        self.assertEqual(readings[0]["rows"], 1)

    def test_network_error_records_and_stops(self):
        calls = {"n": 0}

        def boom(session, url, **kwargs):
            calls["n"] += 1
            raise ConnectionError("network down")

        with mock.patch.object(requests.Session, "get", boom), \
             mock.patch.object(se.time, "sleep"):
            readings = se.probe_burst(count=5, interval=2.0,
                                      log_path=self.log_path)
        self.assertEqual(calls["n"], 1)   # 网络不通测不出阈值，1 发即停
        self.assertEqual(len(readings), 1)
        self.assertFalse(readings[0]["blocked"])
        self.assertIn("ConnectionError", readings[0]["note"])
        self.assertIn("ConnectionError", self._read_log()[0]["note"])

    def test_log_path_none_skips_file(self):
        readings = self._run([_Resp(_SOGOU_OK)], count=1, interval=2.0,
                             log_path=None)
        self.assertEqual(len(readings), 1)
        self.assertFalse(pathlib.Path(self.log_path).exists())

    def test_probe_sleeps_explicit_interval_not_engine_default(self):
        # 探测绕过引擎默认 8s 节流：sleep 用 interval 参数，且更新引擎级
        # 时间戳（同进程普通 search 不至于贴脸连发）
        sleeps = []
        with mock.patch.object(requests.Session, "get",
                               return_value=_Resp(_SOGOU_OK)), \
             mock.patch.object(se.time, "sleep",
                               side_effect=lambda s: sleeps.append(s)):
            se.probe_burst(count=3, interval=1.5, log_path=None)
        self.assertEqual(sleeps, [1.5, 1.5])   # 第 1 发前不 sleep
        with se._throttle_lock:
            self.assertGreater(se._last_request_ts, 0.0)


class TestSogouBlockedJudgement(unittest.TestCase):
    """_blocked/_soft_blocked 判据 + search() 重构零语义漂移回归。"""

    def test_blocked_main_judgement(self):
        self.assertTrue(se._blocked(403, "https://www.sogou.com/web", "x"))
        self.assertTrue(se._blocked(
            200, "https://www.sogou.com/antispider/?m=1", "x"))
        self.assertTrue(se._blocked(200, "https://www.sogou.com/web",
                                    "验证码" + "y" * 3000))  # 只查前 2000 字
        self.assertFalse(se._blocked(200, "https://www.sogou.com/web",
                                     "正常" + "y" * 3000))

    def test_soft_blocked_judgement(self):
        self.assertTrue(se._soft_blocked("<html>验证码</html>"))
        self.assertTrue(se._soft_blocked("<html>ANTIspider</html>"))
        self.assertFalse(se._soft_blocked(_SOGOU_OK))

    def test_search_main_block_regression(self):
        # helper 重构后 search() 行为钉死：主风控抛 SogouBlocked
        with mock.patch.object(se, "_new_session") as mk_sess, \
             mock.patch.object(se, "_wait_turn"):
            mk_sess.return_value.get.return_value = _Resp(
                "", status_code=200,
                url="https://www.sogou.com/antispider/?m=1")
            out = se.search("测试", on_error="report")
        self.assertIn("sogou_blocked", out[0]["error"])

    def test_search_soft_block_regression(self):
        # 软风控页：验证码标记在 2000 字之后（前段是正常解析域）——主判据
        # 查 text[:2000] 抓不到，由"0 行 + 全文标记"的软风控路径兜住
        with mock.patch.object(se, "_new_session") as mk_sess, \
             mock.patch.object(se, "_wait_turn"):
            mk_sess.return_value.get.return_value = _Resp(
                "<html>" + "正常内容" * 800 + "请输入验证码</html>")
            out = se.search("测试", on_error="report")
        self.assertIn("soft-block page", out[0]["error"])

    def test_search_normal_parse_regression(self):
        with mock.patch.object(se, "_new_session") as mk_sess, \
             mock.patch.object(se, "_wait_turn"):
            mk_sess.return_value.get.return_value = _Resp(_SOGOU_OK)
            out = se.search("测试", num=1, on_error="report")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["url"], "https://example.com/1")
        self.assertEqual(out[0]["engine"], "sogou")


# ---- 2. bilibili 多 P 展开 --------------------------------------------------


def _view_payload(pages, cid=111):
    """多 P 视频的最小 view 响应。pages: [(page_no, cid, part_title)]。"""
    return {"code": 0, "data": {
        "bvid": "BV1xx411c7mD", "cid": cid, "title": "多P课程",
        "desc": "简介", "owner": {"name": "UP主"}, "pubdate": 1700000000,
        "pages": [{"page": p, "cid": c, "part": t, "duration": 600}
                  for p, c, t in pages],
        "stat": {"view": 1, "danmaku": 0, "like": 0, "favorite": 0}}}


class TestBilibiliMultiPage(unittest.TestCase):
    """?p=N 提取 / _resolve_cid / fetch_video、fetch_subtitles 多 P。"""

    def setUp(self):
        self.payload = _view_payload(
            [(1, 111, "1.第一集"), (2, 222, "2.第二集"), (3, 333, "3.第三集")])

    def test_extract_part(self):
        self.assertEqual(be._extract_part("BV1xx411c7mD?p=2"), 2)
        self.assertEqual(be._extract_part(
            "https://www.bilibili.com/video/BV1xx411c7mD?p=3"), 3)
        self.assertEqual(be._extract_part("BV1xx411c7mD?p=2&t=9"), 2)
        self.assertEqual(be._extract_part(
            "https://www.bilibili.com/video/BV1xx411c7mD/"), None)  # 无标记
        self.assertEqual(be._extract_part("BV1xx411c7mD?p=abc"), None)
        self.assertEqual(be._extract_part("BV1xx411c7mD?spm=x&p=12"), 12)

    def test_resolve_cid_pages(self):
        cid, count, title = be._resolve_cid(self.payload["data"], 2)
        self.assertEqual((cid, count, title), (222, 3, "2.第二集"))
        cid, count, title = be._resolve_cid(self.payload["data"], 1)
        self.assertEqual((cid, count, title), (111, 3, "1.第一集"))

    def test_resolve_cid_out_of_range_honest_error(self):
        with self.assertRaises(be.BilibiliApiError) as cm:
            be._resolve_cid(self.payload["data"], 9)
        self.assertIn("1~3", str(cm.exception))
        with self.assertRaises(be.BilibiliApiError):
            be._resolve_cid(self.payload["data"], 0)

    def test_resolve_cid_no_pages_falls_back_to_data_cid(self):
        # 旧形态（view 未下发 pages，v3.9/v3.4 fixture 即此形态）：行为原样
        v = {"cid": 12345}
        self.assertEqual(be._resolve_cid(v, 1), (12345, 1, ""))
        self.assertIsNone(be._resolve_cid({}, 1)[0])   # cid 缺失交调用方定语义

    def test_resolve_cid_page_entry_missing_cid(self):
        v = {"cid": 111, "pages": [{"page": 1, "part": "x"}]}
        with self.assertRaises(be.BilibiliApiError):
            be._resolve_cid(v, 1)

    def _fetch_video(self, video, **kw):
        fake = mock.Mock(status_code=200)
        fake.json.return_value = self.payload
        with mock.patch.object(be, "_wait_turn"), \
             mock.patch.object(be.requests.Session, "get",
                               return_value=fake):
            return be.fetch_video(video, on_error="raise", **kw)

    def test_fetch_video_default_p1_uses_page_entry(self):
        out = self._fetch_video("BV1xx411c7mD")
        self.assertEqual(out["cid"], 111)          # pages[0] 的 cid（=data.cid）
        self.assertEqual(out["page"], 1)
        self.assertEqual(out["part_title"], "1.第一集")
        self.assertEqual(out["pages_count"], 3)
        self.assertNotIn("?p=", out["url"])        # P1 不带参数（原形态）

    def test_fetch_video_url_p_marker(self):
        out = self._fetch_video(
            "https://www.bilibili.com/video/BV1xx411c7mD?p=2")
        self.assertEqual(out["cid"], 222)
        self.assertEqual(out["page"], 2)
        self.assertEqual(out["part_title"], "2.第二集")
        self.assertTrue(out["url"].endswith("?p=2"))   # 分 P>1 回跳链接

    def test_fetch_video_explicit_part_wins_over_url(self):
        out = self._fetch_video("BV1xx411c7mD?p=2", part=3)
        self.assertEqual(out["page"], 3)
        self.assertEqual(out["cid"], 333)
        self.assertTrue(out["url"].endswith("?p=3"))

    def test_fetch_video_out_of_range_report_protocol(self):
        fake = mock.Mock(status_code=200)
        fake.json.return_value = self.payload
        with mock.patch.object(be, "_wait_turn"), \
             mock.patch.object(be.requests.Session, "get",
                               return_value=fake):
            out = be.fetch_video("BV1xx411c7mD?p=99", on_error="report")
        self.assertIn("error", out[0])
        self.assertIn("1~3", out[0]["error"])      # 含合法范围，如实报错

    def _fetch_subtitles(self, video, **kw):
        """view 响应（多 P）+ player 响应（空字幕=未登录已知上限）。"""
        view = mock.Mock(status_code=200)
        view.json.return_value = self.payload
        player = mock.Mock(status_code=200)
        player.json.return_value = {"code": 0,
                                    "data": {"subtitle": {"subtitles": []}}}
        calls = []

        def fake_get(session, url, **kwargs):
            calls.append({"url": url, "params": kwargs.get("params")})
            return view if "view" in url else player

        with mock.patch.object(be, "_wait_turn"), \
             mock.patch.object(be, "_get_wbi_keys",
                               return_value=("a" * 32, "b" * 32)), \
             mock.patch.object(be.requests.Session, "get", fake_get):
            out = be.fetch_subtitles(video, on_error="raise", **kw)
        return out, calls

    def test_fetch_subtitles_part_uses_part_cid(self):
        out, calls = self._fetch_subtitles("BV1xx411c7mD?p=2")
        self.assertEqual(out["cid"], 222)          # P2 的 cid，不是 data.cid
        self.assertEqual(out["page"], 2)
        self.assertEqual(out["pages_count"], 3)
        self.assertEqual(out["part_title"], "2.第二集")
        self.assertFalse(out["has_subtitles"])     # 未登录恒空（已知上限）
        player = next(c for c in calls if "player/wbi/v2" in c["url"])
        self.assertEqual(str(player["params"]["cid"]), "222")   # 签名用 P2 cid

    def test_fetch_subtitles_out_of_range(self):
        with self.assertRaises(be.BilibiliApiError) as cm:
            self._fetch_subtitles("BV1xx411c7mD", part=99)
        self.assertIn("1~3", str(cm.exception))


# ---- 3. 版本一致性与 MCP 透传 ------------------------------------------------


class TestVersionSyncV313(unittest.TestCase):
    def test_mcp_server_version_not_older_than_3130(self):
        # 3.14 起改为常青下限：精确锁当前版本是 test_v3140 的职责
        sys.path.insert(0, str(REPO / "tools"))
        import mcp_server
        self.assertGreaterEqual(
            tuple(int(x) for x in mcp_server.__version__.split(".")),
            (3, 13, 0))


class TestMcpVideoPassthroughV313(unittest.TestCase):
    """bilibili_video MCP 工具：part 参数透传（mcp SDK 装了才跑）。"""

    @classmethod
    def setUpClass(cls):
        try:
            sys.path.insert(0, str(REPO / "tools"))
            import mcp_server  # noqa: F401
            cls.mcp_server = mcp_server
        except ImportError:
            cls.mcp_server = None

    def test_part_passthrough(self):
        if self.mcp_server is None:
            self.skipTest("mcp SDK 未安装")
        be_mod = self.mcp_server._bilibili
        want = {"cid": 222, "page": 2}
        with mock.patch.object(be_mod, "fetch_video",
                               return_value=want) as m:
            out = self.mcp_server.bilibili_video(video="BV1xx411c7mD?p=9",
                                                 part=2)
        m.assert_called_once_with("BV1xx411c7mD?p=9", part=2,
                                  on_error="report")
        self.assertEqual(json.loads(out), want)

    def test_part_default_none(self):
        if self.mcp_server is None:
            self.skipTest("mcp SDK 未安装")
        be_mod = self.mcp_server._bilibili
        with mock.patch.object(be_mod, "fetch_video",
                               return_value={"page": 1}) as m:
            self.mcp_server.bilibili_video(video="BV1xx411c7mD")
        m.assert_called_once_with("BV1xx411c7mD", part=None,
                                  on_error="report")


if __name__ == "__main__":
    unittest.main()
