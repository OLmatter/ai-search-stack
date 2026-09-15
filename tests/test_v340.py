"""v3.4.0 离线单测：错误协议修正（10003/404）、API 认证自愈、文章端点、
通用阅读器分流。

纪律：不跑真实网络、不起真浏览器——bootstrap 用假模块顶替（sys.modules），
requests 全 mock。与 test_offline.py 同套 discover 运行。
运行：python -m unittest discover -s tests -p "test_*.py" -v
"""
import contextlib
import json
import pathlib
import sys
import time
import unittest
from unittest import mock

import requests

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "chat-scraper"))

import zhihu_content as zc  # noqa: E402

COOKIE_JSON = json.dumps(
    {"cookies": {"d_c0": "fake", "__zse_ck": "fake"},
     "user_agent": "Firefox"})


@contextlib.contextmanager
def fake_cookie_file():
    """mock 掉 cookie 文件加载（与 test_offline 同款组合）。"""
    with mock.patch.object(zc, "_cookie_path",
                           return_value="state/fake.json"), \
         mock.patch.object(zc.os.path, "exists", return_value=True), \
         mock.patch("builtins.open",
                    mock.mock_open(read_data=COOKIE_JSON)):
        yield


def fake_bootstrap_module():
    """假 zhihu_bootstrap：bootstrap() 可计数、不碰 camoufox/网络。"""
    mod = mock.Mock()
    mod.bootstrap.return_value = {"cookies": {"d_c0": "new"}}
    return mod


def auth_fail_resp(status=401, code=100, message="请先登录"):
    r = mock.Mock(status_code=status,
                  text=json.dumps({"error": {"code": code,
                                             "message": message}}))
    r.json.return_value = {"error": {"code": code, "message": message}}
    return r


def auth_fail(*a, **k):
    """requests.get 的 side_effect 版：吞掉调用参数，恒回认证失败。"""
    return auth_fail_resp()


def ok_resp(body):
    r = mock.Mock(status_code=200, text=json.dumps(body))
    r.json.return_value = body
    return r


class SelfHealTestBase(unittest.TestCase):
    """自愈闸门状态隔离：每个用例拿干净的时间戳。"""

    def setUp(self):
        self._saved_ts = zc._selfheal_last_ts
        zc._selfheal_last_ts = -1e18   # 允许自愈

    def tearDown(self):
        zc._selfheal_last_ts = self._saved_ts


class TestErrorProtocolV340(unittest.TestCase):
    """共识 #1/#2：10003 误诊与 404 协议缺口是必修前置。"""

    def test_10003_maps_to_sign_rejected_even_with_403(self):
        # 实测：cookie 有效时 members/answers 也回 403+10003（签名被拒）。
        # 误诊成 auth_expired 会诱发自愈重试风暴——必须先于认证检查分流
        fake = auth_fail_resp(status=403, code=10003, message="请求参数异常")
        boot = fake_bootstrap_module()
        with fake_cookie_file(), \
             mock.patch.object(zc.requests, "get", return_value=fake), \
             mock.patch.dict(sys.modules, {"zhihu_bootstrap": boot}):
            with self.assertRaises(zc.ZhihuSignRejected) as cm:
                zc.fetch_question("19550227")
        self.assertEqual(zc.ZhihuSignRejected.slug, "zhihu_sign_rejected")
        self.assertIn("非 cookie", str(cm.exception))
        boot.bootstrap.assert_not_called()   # 签名被拒绝不碰引导

    def test_bare_404_maps_to_not_found(self):
        # 死端点裸 404（无 error body、非 JSON）此前以无 slug 的
        # HTTPError 穿透——协议缺口
        fake = mock.Mock(status_code=404, text="404: page not found")
        fake.json.side_effect = ValueError("no json")
        fake.url = "https://www.zhihu.com/api/v4/dead_endpoint"
        with fake_cookie_file(), \
             mock.patch.object(zc.requests, "get", return_value=fake):
            with self.assertRaises(zc.ZhihuNotFound) as cm:
                zc.fetch_question("999999")
        self.assertEqual(zc.ZhihuNotFound.slug, "zhihu_not_found")
        self.assertIn("404", str(cm.exception))

    def test_all_exception_slugs(self):
        self.assertEqual(zc.ZhihuAuthExpired.slug, "zhihu_auth_expired")
        self.assertEqual(zc.ZhihuBehaviorLimited.slug, "zhihu_behavior_limited")
        self.assertEqual(zc.ZhihuSignRejected.slug, "zhihu_sign_rejected")
        self.assertEqual(zc.ZhihuNotFound.slug, "zhihu_not_found")
        self.assertEqual(zc.ZhihuApiError.slug, "zhihu_api_error")
        self.assertEqual(zc.ReadError.slug, "read_failed")
        for name in ("ZhihuSignRejected", "ZhihuNotFound", "ReadError"):
            self.assertIn(name, zc.__all__)


class TestSelfHeal(SelfHealTestBase):
    """共识 #4：仅 ZhihuAuthExpired 触发；每冷却窗口至多一次；重试一次。"""

    def test_auth_expired_triggers_bootstrap_and_retry_succeeds(self):
        good = ok_resp({"id": 19550227, "title": "问题标题",
                        "detail": "细节", "answer_count": 3})
        boot = fake_bootstrap_module()
        with fake_cookie_file(), \
             mock.patch.object(zc.requests, "get",
                               side_effect=[auth_fail_resp(), good]) as get, \
             mock.patch.dict(sys.modules, {"zhihu_bootstrap": boot}):
            out = zc.fetch_question("19550227")
        self.assertEqual(out["title"], "问题标题")
        boot.bootstrap.assert_called_once()
        self.assertIs(boot.bootstrap.call_args.kwargs.get("headless"), True)
        self.assertEqual(get.call_count, 2)   # 失败一次 + 重试一次

    def test_self_heal_bootstrap_failure_reraises_original(self):
        boot = fake_bootstrap_module()
        boot.bootstrap.side_effect = RuntimeError("camoufox 未安装")
        with fake_cookie_file(), \
             mock.patch.object(zc.requests, "get",
                               side_effect=auth_fail) as get, \
             mock.patch.dict(sys.modules, {"zhihu_bootstrap": boot}):
            with self.assertRaises(zc.ZhihuAuthExpired):
                zc.fetch_question("19550227")
        boot.bootstrap.assert_called_once()
        self.assertEqual(get.call_count, 1)   # 引导失败不重试

    def test_retry_failure_does_not_recurse(self):
        # 防递归：重试仍 401 时不得二次自愈，直接抛该次异常
        boot = fake_bootstrap_module()
        with fake_cookie_file(), \
             mock.patch.object(zc.requests, "get",
                               side_effect=[auth_fail_resp(),
                                            auth_fail_resp()]) as get, \
             mock.patch.dict(sys.modules, {"zhihu_bootstrap": boot}):
            with self.assertRaises(zc.ZhihuAuthExpired):
                zc.fetch_question("19550227")
        boot.bootstrap.assert_called_once()   # 只自愈一次
        self.assertEqual(get.call_count, 2)

    def test_cooldown_blocks_second_self_heal(self):
        zc._selfheal_last_ts = time.monotonic()   # 刚自愈过 → 冷却期内
        boot = fake_bootstrap_module()
        with fake_cookie_file(), \
             mock.patch.object(zc.requests, "get",
                               side_effect=auth_fail), \
             mock.patch.dict(sys.modules, {"zhihu_bootstrap": boot}):
            with self.assertRaises(zc.ZhihuAuthExpired):
                zc.fetch_question("19550227")
        boot.bootstrap.assert_not_called()   # 冷却期内不再自愈

    def test_missing_cookie_file_does_not_trigger_heal(self):
        # 本地状态缺失 ≠ 服务端认证拒绝：引导保持显式，离线单测零浏览器
        boot = fake_bootstrap_module()
        with mock.patch.object(zc, "_cookie_path",
                               return_value="Z:/no/such/file.json"), \
             mock.patch.dict(sys.modules, {"zhihu_bootstrap": boot}):
            with self.assertRaises(zc.ZhihuAuthExpired) as cm:
                zc.fetch_question("19550227")
        self.assertIn("zhihu_bootstrap", str(cm.exception))
        boot.bootstrap.assert_not_called()


class TestFetchArticle(unittest.TestCase):
    """共识 #3：articles 端点已实测存在；include 必须逐字段校验。"""

    ARTICLE_BODY = {"id": 18589357376, "title": "文章标题",
                    "content": "<p>正文<b>加粗</b>段落</p>",
                    "created": 1700000000, "updated": 1700000100,
                    "voteup_count": 5, "comment_count": 2}
    EXPECT_PATH = ("/api/v4/articles/18589357376?include="
                   "title,created,updated,voteup_count,comment_count,content")

    def test_accepts_url_and_pure_id(self):
        captured = {}

        def fake_api_get(pq):
            captured["pq"] = pq
            return dict(self.ARTICLE_BODY)

        with mock.patch.object(zc, "_api_get", side_effect=fake_api_get):
            from_url = zc.fetch_article(
                "https://zhuanlan.zhihu.com/p/18589357376")
            from_id = zc.fetch_article("18589357376")
        self.assertEqual(captured["pq"], self.EXPECT_PATH)
        self.assertEqual(from_url["content"], "正文 加粗 段落")
        self.assertEqual(from_url["voteup"], 5)
        self.assertEqual(from_url["comment_count"], 2)
        self.assertEqual(from_url["engine"], "zhihu-api")
        self.assertTrue(from_url["url"].endswith("/p/18589357376"))
        self.assertEqual(from_id["id"], from_url["id"])

    def test_invalid_article_id_rejected(self):
        # id 提取只认 zhuanlan.zhihu.com/p/{连续数字} 或纯数字——提取结果
        # 恒为纯数字，path 拼接注入天然不可能；非数字垃圾一律拒绝
        for bad in ("abc", "", "https://evil.com/p/1",
                    "https://zhuanlan.zhihu.com/p/"):
            with self.assertRaises(zc.ZhihuApiError):
                zc.fetch_article(bad)

    def test_content_empty_falls_back_to_excerpt(self):
        body = dict(self.ARTICLE_BODY, content="", excerpt="摘<b>要</b>")

        with mock.patch.object(zc, "_api_get", return_value=body):
            out = zc.fetch_article("18589357376")
        self.assertEqual(out["content"], "摘 要")

    def test_content_and_excerpt_both_missing_reports_not_vacuum(self):
        # include 逗号语法若未真回正文：如实报字段缺失，不伪装正文为空
        body = dict(self.ARTICLE_BODY, content="", excerpt="")

        with mock.patch.object(zc, "_api_get", return_value=body):
            with self.assertRaises(zc.ZhihuApiError) as cm:
                zc.fetch_article("18589357376")
        self.assertIn("content", str(cm.exception))


class TestReadRouting(unittest.TestCase):
    """通用阅读器分流：知乎结构化线优先，外域走通用读取。"""

    def setUp(self):
        patches = [
            mock.patch.object(zc, "fetch_question", return_value={
                "id": "1", "title": "Q", "detail": "D", "answer_count": 1,
                "url": "u", "engine": "zhihu-api"}),
            mock.patch.object(zc, "fetch_article", return_value={
                "id": "42", "title": "A", "content": "C",
                "created": "", "updated": "", "voteup": 0,
                "comment_count": 0, "url": "u2", "engine": "zhihu-api"}),
            mock.patch.object(zc, "fetch_answers", return_value=[
                {"author": "张三", "excerpt": "E", "voteup": 1,
                 "url": "https://www.zhihu.com/question/1/answer/9",
                 "engine": "zhihu-api"}]),
            mock.patch.object(zc, "read_via_browser", return_value={
                "title": "B", "content": "X", "url": "u3",
                "engine": "zhihu-seo-browser"}),
        ]
        self.fq, self.fa, self.fans, self.rb = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)

    def test_question_routes_to_fetch_question(self):
        out = zc.read("https://www.zhihu.com/question/19550227")
        self.assertEqual(out["content"], "D")
        self.assertEqual(out["engine"], "zhihu-api")
        self.fq.assert_called_once_with("19550227")

    def test_answer_url_filters_target_answer(self):
        out = zc.read("https://www.zhihu.com/question/1/answer/9")
        self.assertEqual(out["content"], "E")
        self.assertIn("张三", out["title"])
        self.assertEqual(out["engine"], "zhihu-api")
        self.rb.assert_not_called()

    def test_answer_not_found_falls_back_to_browser(self):
        out = zc.read("https://www.zhihu.com/question/1/answer/404")
        self.assertEqual(out["engine"], "zhihu-seo-browser")
        self.rb.assert_called_once_with(
            "https://www.zhihu.com/question/1/answer/404")

    def test_zhuanlan_routes_to_fetch_article(self):
        out = zc.read("https://zhuanlan.zhihu.com/p/42")
        self.assertEqual(out["content"], "C")
        self.fa.assert_called_once_with("42")

    def test_other_zhihu_url_goes_to_browser(self):
        out = zc.read("https://www.zhihu.com/people/someone")
        self.assertEqual(out["engine"], "zhihu-seo-browser")
        self.fq.assert_not_called()

    def test_non_zhihu_routes_to_generic_read(self):
        with mock.patch.object(zc, "_generic_read",
                               return_value={"title": "t", "content": "c",
                                             "url": "u", "engine": "http"}) \
                as gr:
            out = zc.read("https://blog.csdn.net/x/a/1")
        gr.assert_called_once_with("https://blog.csdn.net/x/a/1")
        self.assertEqual(out["engine"], "http")

    def test_answer_api_failure_falls_back_to_browser(self):
        self.fans.side_effect = zc.ZhihuSignRejected("签名被拒")
        out = zc.read("https://www.zhihu.com/question/1/answer/9")
        self.assertEqual(out["engine"], "zhihu-seo-browser")


class TestGenericRead(unittest.TestCase):
    """外域通用读取：HTTP 直连 + 选择器提取 + 浏览器兜底判定。"""

    FIXTURE = (
        "<html><head><title>CSDN 文章标题</title></head><body>"
        "<script>var tracking = 1;</script><style>body{}</style>"
        "<nav>菜单 导航</nav>"
        "<article><h1>标题</h1><p>" + "这是正文段落。" * 60 + "</p></article>"
        "</body></html>")

    def _mock_session(self, resp):
        sess_cls = mock.Mock()
        sess = sess_cls.return_value
        sess.get.return_value = resp
        return sess_cls, sess

    def test_http_line_parses_fixture(self):
        resp = mock.Mock(status_code=200, url="https://blog.csdn.net/a/1",
                         text=self.FIXTURE,
                         headers={"Content-Type": "text/html; charset=utf-8"})
        sess_cls, sess = self._mock_session(resp)
        with mock.patch.object(zc.requests, "Session", sess_cls):
            out = zc._generic_read_http("https://blog.csdn.net/a/1")
        self.assertIn("这是正文段落。", out["content"])
        self.assertNotIn("var tracking", out["content"])   # script 已剥
        self.assertNotIn("菜单 导航", out["content"])       # article 优先于 body
        self.assertEqual(out["title"], "CSDN 文章标题")
        self.assertEqual(out["engine"], "http")
        self.assertIs(sess.trust_env, False)               # 强制直连
        accept = sess.headers.update.call_args[0][0]["Accept"]
        self.assertIn("text/html", accept)                 # 非 requests 默认 */*

    def test_short_content_is_soft_fail_browser_fallback_signal(self):
        # 反爬判定单元：200 + 正文 <200 字 → _HttpSoftFail（浏览器兜底信号）
        resp = mock.Mock(status_code=200, url="https://x.com/a",
                         text="<html><body>太短了</body></html>",
                         headers={"Content-Type": "text/html"})
        sess_cls, _ = self._mock_session(resp)
        with mock.patch.object(zc.requests, "Session", sess_cls):
            with self.assertRaises(zc._HttpSoftFail):
                zc._generic_read_http("https://x.com/a")

    def test_403_soft_fail_and_404_hard_fail(self):
        resp403 = mock.Mock(status_code=403, url="u", text="forbidden")
        sess_cls, _ = self._mock_session(resp403)
        with mock.patch.object(zc.requests, "Session", sess_cls):
            with self.assertRaises(zc._HttpSoftFail):
                zc._generic_read_http("https://x.com/403")
        resp404 = mock.Mock(status_code=404, url="u", text="gone")
        sess_cls, _ = self._mock_session(resp404)
        with mock.patch.object(zc.requests, "Session", sess_cls):
            with self.assertRaises(zc.ReadError):
                zc._generic_read_http("https://x.com/404")

    def test_soft_fail_triggers_browser_fallback_via_read(self):
        with mock.patch.object(zc, "_generic_read_http",
                               side_effect=zc._HttpSoftFail("疑似反爬")), \
             mock.patch.object(zc, "_generic_read_browser",
                               return_value={"title": "B", "content": "C",
                                             "url": "u",
                                             "engine": "browser"}) as gb:
            out = zc.read("https://x.com/anti-crawl")
        gb.assert_called_once_with("https://x.com/anti-crawl")
        self.assertEqual(out["engine"], "browser")

    def test_non_http_scheme_rejected(self):
        for bad in ("javascript:alert(1)", "file:///C:/x", "not a url"):
            with self.assertRaises(zc.ReadError):
                zc.read(bad)


class TestSearxngHint(unittest.TestCase):
    """价值评估员共识 #5 附带项：实例没起的报错要给一条命令的出路。"""

    def test_unavailable_message_includes_compose_hint(self):
        import zhihu_engine as zg
        with mock.patch.object(zg, "_wait_turn"), \
             mock.patch.object(zg.requests, "get",
                               side_effect=requests.exceptions.ConnectionError(
                                   "refused")):
            with self.assertRaises(zg.SearxngUnavailable) as cm:
                zg._searxng_search("q", 10, None, "t", "verify")
        self.assertIn("docker compose up -d", str(cm.exception))


if __name__ == "__main__":
    unittest.main()


class TestAuditRoundV341(unittest.TestCase):
    """复审轮修复：并发自愈单次性、Content-Type 护栏、浏览器线短正文、
    question/zhuanlan 分支浏览器兜底一致性。"""

    def setUp(self):
        import zhihu_content as zc
        self.zc = zc
        self._saved_ts = zc._selfheal_last_ts
        zc._selfheal_last_ts = -1e18   # 允许自愈

    def tearDown(self):
        self.zc._selfheal_last_ts = self._saved_ts

    def test_self_heal_concurrent_single_bootstrap(self):
        # 复审缺口：闸门并发正确性此前无测试锁死——两线程同时 auth_expired
        # 只放一个进引导；自愈成功方重试拿到结果，冷却方拿原异常
        import threading
        boot = fake_bootstrap_module()
        barrier = threading.Barrier(2, timeout=10)
        results = []
        state = {"n": 0}
        slock = threading.Lock()

        def ok_resp():
            r = mock.Mock(status_code=200, text="")
            r.json.return_value = {"id": "19550227", "title": "t",
                                   "detail": "", "answer_count": 0}
            return r

        def slow_auth_fail(*a, **kw):
            with slock:
                state["n"] += 1
                first_two = state["n"] <= 2
            if first_two:
                barrier.wait(timeout=10)   # 两线程的首发同时到达
                return auth_fail_resp()
            return ok_resp()               # 自愈后的重试：成功

        with fake_cookie_file(), \
             mock.patch.object(self.zc.requests, "get",
                               side_effect=slow_auth_fail), \
             mock.patch.dict(sys.modules, {"zhihu_bootstrap": boot}):
            def worker():
                try:
                    self.zc.fetch_question("19550227")
                    results.append("ok")
                except self.zc.ZhihuAuthExpired:
                    results.append("auth")
            t1, t2 = threading.Thread(target=worker), threading.Thread(target=worker)
            t1.start(); t2.start(); t1.join(15); t2.join(15)
        self.assertEqual(boot.bootstrap.call_count, 1,
                         "并发 auth_expired 引导了不止一次")
        self.assertEqual(sorted(results), ["auth", "ok"])

    def test_content_type_guard_non_html_soft_fails(self):
        # 复审 #2：>200 字的 JSON 不再被当"正文"以 engine=http 假成功
        import zhihu_content as zc
        from unittest import mock
        big_json = '{"error": "' + "x" * 400 + '"}'
        fake = mock.Mock(status_code=200,
                         headers={"Content-Type": "application/json"},
                         text=big_json, url="https://api.example.com/x")
        fake.json.return_value = {"error": "x" * 400}
        with mock.patch.object(requests.Session, "get", return_value=fake):
            with self.assertRaises(zc._HttpSoftFail):
                zc._generic_read_http("https://api.example.com/x")

    def test_browser_line_returns_short_content(self):
        # 复审 #3：浏览器线能过反爬说明页面是真的，短正文照实返回不报错
        import zhihu_content as zc
        fake_page = mock.MagicMock()
        fake_page.url = "https://www.zhihu.com/question/1"
        fake_page.title.return_value = "短文"
        fake_page.content.return_value = ("<html><body><div class="
                                          "'post-content'>短正文。</div>"
                                          "</body></html>")
        fake_cam = mock.MagicMock()
        fake_cam.return_value = fake_cam               # Camoufox(...) 调用
        fake_cam.__enter__.return_value = fake_cam     # with 进入后的 browser
        fake_cam.new_context.return_value.new_page.return_value = fake_page
        cam_pkg, cam_sync = mock.MagicMock(), mock.MagicMock()
        cam_sync.Camoufox = fake_cam
        cam_pkg.sync_api = cam_sync
        with mock.patch.dict("sys.modules", {"camoufox": cam_pkg,
                                             "camoufox.sync_api": cam_sync}):
            out = zc.read_via_browser("https://www.zhihu.com/question/1")
        self.assertEqual(out["content"], "短正文。")
        self.assertEqual(out["engine"], "zhihu-seo-browser")

    def test_question_branch_browser_fallback_consistency(self):
        # 复审 #1：question/zhuanlan 分支 API 失败也必须回浏览器线（与
        # answer 分支一致），不得让 ZhihuAuthExpired 直接逃逸
        import zhihu_content as zc
        from unittest import mock
        browser_row = {"title": "t", "content": "c", "url": "u",
                       "engine": "zhihu-seo-browser"}
        for url, api_fn in (
                ("https://www.zhihu.com/question/19550227",
                 lambda: zc.fetch_question("19550227")),
                ("https://zhuanlan.zhihu.com/p/1",
                 lambda: zc.fetch_article("1"))):
            with mock.patch.object(zc, "fetch_question",
                                   side_effect=zc.ZhihuAuthExpired("expired")), \
                 mock.patch.object(zc, "fetch_article",
                                   side_effect=zc.ZhihuAuthExpired("expired")), \
                 mock.patch.object(zc, "fetch_answers",
                                   side_effect=zc.ZhihuAuthExpired("expired")), \
                 mock.patch.object(zc, "read_via_browser",
                                   return_value=browser_row) as rb:
                out = zc.read(url)
            self.assertEqual(out["engine"], "zhihu-seo-browser")
            rb.assert_called_once()


class TestV350(unittest.TestCase):
    """v3.5：微信/B站读取分流 + fetch_video。"""

    def test_fetch_video_rejects_invalid_bvid(self):
        import bilibili_engine as be
        out = be.fetch_video("not-a-bvid", on_error="report")
        self.assertIn("error", out[0])
        with self.assertRaises(ValueError):
            be.fetch_video("not-a-bvid", on_error="raise")

    def test_fetch_video_success_shape(self):
        import bilibili_engine as be
        from unittest import mock
        data = {"code": 0, "data": {
            "title": "标题<em>清理</em>", "desc": "简介", "owner": {"name": "UP"},
            "stat": {"view": 1, "danmaku": 2, "like": 3, "favorite": 4},
            "pubdate": 1700000000}}
        fake = mock.Mock(status_code=200)
        fake.json.return_value = data
        with mock.patch.object(be, "_wait_turn"), \
             mock.patch.object(be.requests.Session, "get",
                               return_value=fake):
            out = be.fetch_video("BV1GJ411x7h7", on_error="raise")
        self.assertEqual(out["title"], "标题清理")
        self.assertEqual(out["owner"], "UP")
        self.assertEqual(out["like"], 3)
        self.assertIn("/video/BV1GJ411x7h7", out["url"])

    def test_read_routes_bilibili(self):
        import zhihu_content as zc
        from unittest import mock
        row = {"title": "t", "desc": "d", "owner": "o", "cid": 137,
               "view": 1, "danmaku": 0, "like": 0, "favorite": 0,
               "pubdate": "x", "url": "u", "engine": "bilibili-api"}
        fake_be = mock.MagicMock()
        fake_be.fetch_video.return_value = row
        with mock.patch.dict(sys.modules, {"bilibili_engine": fake_be}):
            out = zc.read("https://www.bilibili.com/video/BV1GJ411x7h7")
        self.assertEqual(out["engine"], "bilibili-api")
        self.assertIn("BV1GJ411x7h7",
                      fake_be.fetch_video.call_args.args[0])

    def test_generic_selectors_cover_weixin(self):
        # 公众号正文容器选择器在列（价值评估员：vendor 官宣主渠道）
        import zhihu_content as zc
        self.assertIn("js_content", zc._GENERIC_SELECTORS)
        self.assertIn("rich_media_content", zc._GENERIC_SELECTORS)


class TestAuditV350Round(unittest.TestCase):
    """复审轮修复：bilibili 分支双失效、错误页守卫双向、doctor 诚实化。"""

    def test_error_page_guard_short_hits_long_passes(self):
        # #3/#4：短文本+标记 → ReadError；长文含同词是正常讨论不误杀
        import zhihu_content as zc
        short = "参数错误 当前环境异常 完成验证后即可继续访问"
        with self.assertRaises(zc.ReadError):
            zc._raise_if_error_page(short, "https://mp.weixin.qq.com/s/x")
        long_body = "这是一篇讲监控系统的技术文章，" + "讨论了环境异常的检测方法。" * 40
        zc._raise_if_error_page(long_body, "https://blog.csdn.net/a")  # 不抛

    def test_bilibili_api_fail_falls_to_generic_not_zhihu_browser(self):
        # 复审 #1/#2：API 失败要回通用线，且不得逃逸/不得调知乎浏览器线
        import zhihu_content as zc
        import bilibili_engine as be
        generic_row = {"title": "g", "content": "c", "url": "u",
                       "engine": "http"}
        fake_be = mock.MagicMock()
        fake_be.fetch_video.side_effect = be.BilibiliApiError("code=-404")
        with mock.patch.dict(sys.modules, {"bilibili_engine": fake_be}),              mock.patch.object(zc, "_generic_read",
                               return_value=generic_row) as gr,              mock.patch.object(zc, "read_via_browser") as rb:
            out = zc.read("https://www.bilibili.com/video/BV1GJ411x7h7")
        self.assertEqual(out["engine"], "http")
        gr.assert_called_once()
        rb.assert_not_called()   # 兜底是通用线不是知乎浏览器线

    def test_bilibili_non_video_page_goes_generic(self):
        import zhihu_content as zc
        from unittest import mock
        generic_row = {"title": "g", "content": "c", "url": "u",
                       "engine": "http"}
        fake_be = mock.MagicMock()
        with mock.patch.dict(sys.modules, {"bilibili_engine": fake_be}), \
             mock.patch.object(zc, "_generic_read",
                               return_value=generic_row) as gr:
            out = zc.read("https://space.bilibili.com/123")
        self.assertEqual(out["engine"], "http")
        fake_be.fetch_video.assert_not_called()   # 非 /video 页不进 API

    def test_fetch_video_api_error_report_uses_tool_field(self):
        # 复审 #5：report 错误条目 tool 字段统一 chat-scraper（曾两制）
        import bilibili_engine as be
        from unittest import mock
        fake = mock.Mock(status_code=200)
        fake.json.return_value = {"code": -404, "message": "啥都木有"}
        with mock.patch.object(be, "_wait_turn"), \
             mock.patch.object(be.requests.Session, "get",
                               return_value=fake):
            out = be.fetch_video("BV1GJ411x7h7", on_error="report")
        self.assertEqual(out[0]["tool"], "chat-scraper")
        self.assertIn("bilibili_api_error", out[0]["error"])

    def test_doctor_cookie_missing_is_optional_fail(self):
        # 复审 #6：cookie 缺失必须 ⚠️（异常）而不是永绿
        import pathlib
        sys.path.insert(0, str(pathlib.Path(__file__).resolve()
                               .parent.parent / "tools"))
        import doctor
        from unittest import mock
        with mock.patch.object(doctor, "COOKIE_PATH",
                               "Z:/no/such/zhihu_cookies.json"):
            with self.assertRaises(RuntimeError):
                doctor.check_cookie()


# ---- v3.6.0 知乎评论读取（comment_v5 家族） --------------------------------

def _raw_comment(cid, **kw):
    """comment_v5 响应 data[] 里的原始评论形态（测试相关字段）。"""
    return {
        "id": cid,
        "content": kw.get("content", f"<p>评论{cid}</p>"),
        "like_count": kw.get("likes", 1),
        "created_time": kw.get("created_time", 1700000000),
        "author": {"name": kw.get("author", "甲"), "url_token": "user-a"},
        "child_comment_count": kw.get("child_count", 0),
        "child_comments": kw.get("children", []),
        "reply_comment_id": kw.get("reply_to"),
    }


def _comment_page(comments, is_end=True, next_url=""):
    return ok_resp({"data": comments,
                    "paging": {"is_end": is_end, "next": next_url},
                    "counts": {"total_counts": len(comments)}})


_ROOT_URL = ("https://www.zhihu.com/api/v4/comment_v5/answers/12202014/"
             "root_comment?order_by=score&limit=20&offset=")


class TestZhihuComments(unittest.TestCase):
    """v3.6 评论线：comment_v5 端点/参数（offset 首跳留空）、沿 paging.next
    翻页、子评论展开条件、602 需登录映射、target URL 提取。

    requests.get 全 mock（顺带断言「签名字节 = 请求字节」纪律），cookie 文件
    走 fake_cookie_file：零真实网络、零浏览器。
    """

    def _fetch(self, responses, *args, **kwargs):
        """mock requests.get 按序回响应并记录每次请求的完整 URL。"""
        calls = []

        def fake_get(url, **kw):
            calls.append(url)
            return responses[min(len(calls) - 1, len(responses) - 1)]

        kwargs.setdefault("on_error", "raise")
        with fake_cookie_file(), \
             mock.patch.object(zc.requests, "get", side_effect=fake_get):
            out = zc.fetch_comments(*args, **kwargs)
        return out, calls

    def test_first_hop_path_and_output_shape(self):
        out, calls = self._fetch(
            [_comment_page([_raw_comment("c1")])], "12202014")
        # offset 首次留空但尾随 &offset= 必须保留在签名串里（字节级一致）
        self.assertEqual(calls, [_ROOT_URL])
        self.assertEqual(len(out), 1)
        item = out[0]
        self.assertEqual(item["id"], "c1")
        self.assertEqual(item["content"], "评论c1")     # HTML 剥净
        self.assertEqual(item["author"], "甲")
        self.assertEqual(item["like_count"], 1)
        self.assertEqual(item["created_time"], zc._fmt_epoch(1700000000))
        self.assertEqual(item["url"], "")   # 纯回答 id 无 qid：不伪造死链（v3.6 #4）

    def test_target_url_extraction_answer_and_question(self):
        resp = _comment_page([_raw_comment("c1")])
        # 回答 URL → answers 端点（问题 id 顺带提取不进端点）
        _, calls = self._fetch(
            [resp], "https://www.zhihu.com/question/111/answer/12202014")
        self.assertEqual(calls[0], _ROOT_URL)
        q_url = ("https://www.zhihu.com/api/v4/comment_v5/questions/19550227/"
                 "root_comment?order_by=score&limit=20&offset=")
        # 问题 URL → questions 端点
        _, calls = self._fetch(
            [resp], "https://www.zhihu.com/question/19550227/")
        self.assertEqual(calls[0], q_url)
        # 纯数字问题 id 需 kind="question" 消歧（纯数字默认按回答）
        _, calls = self._fetch([resp], "19550227", kind="question")
        self.assertEqual(calls[0], q_url)

    def test_pagination_follows_paging_next_verbatim(self):
        # paging.next 是服务端下发的完整 URL——剥壳后必须原样直调（不重排）
        next_url = ("https://www.zhihu.com/api/v4/comment_v5/answers/12202014/"
                    "root_comment?order_by=score&limit=20"
                    "&offset=99_78247946_open")
        out, calls = self._fetch([
            _comment_page([_raw_comment("c1")], is_end=False,
                          next_url=next_url),
            _comment_page([_raw_comment("c2")], is_end=True),
        ], "12202014", num=40)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1], next_url)
        self.assertEqual([i["id"] for i in out], ["c1", "c2"])

    def test_pagination_stops_on_is_end_or_empty_next(self):
        # is_end=true：即便 next 非空也停
        _, calls = self._fetch([
            _comment_page([_raw_comment("c1")], is_end=True,
                          next_url="https://www.zhihu.com/api/v4/x?offset=1"),
        ], "12202014", num=40)
        self.assertEqual(len(calls), 1)
        # next 空：也停（防御形态）
        _, calls = self._fetch([
            _comment_page([_raw_comment("c1")], is_end=False, next_url=""),
        ], "12202014", num=40)
        self.assertEqual(len(calls), 1)

    def test_num_limit_stops_without_extra_requests(self):
        out, calls = self._fetch([
            _comment_page([_raw_comment("c1"), _raw_comment("c2")],
                          is_end=False,
                          next_url="https://www.zhihu.com/api/v4/x?offset=1"),
        ], "12202014", num=2)
        self.assertEqual(len(calls), 1, "num 够了不再发翻页请求")
        self.assertEqual(len(out), 2)

    def test_children_embedded_sufficient_no_extra_call(self):
        resp = _comment_page([
            _raw_comment("c1", child_count=1,
                         children=[_raw_comment("c1a")]),
        ])
        out, calls = self._fetch([resp], "12202014")
        self.assertEqual(len(calls), 1, "内嵌够 child_comment_count 不补拉")
        kids = out[0]["child_comments"]
        self.assertEqual([k["id"] for k in kids], ["c1a"])
        self.assertEqual(kids[0]["content"], "评论c1a")

    def test_children_fetch_when_count_exceeds_embedded(self):
        root = _comment_page([
            _raw_comment("c1", child_count=3, children=[_raw_comment("c1a")]),
        ])
        child_next = ("https://www.zhihu.com/api/v4/comment_v5/comment/c1/"
                      "child_comment?limit=10&offset=1")
        out, calls = self._fetch([
            root,
            _comment_page([_raw_comment("c1a"), _raw_comment("c1b")],
                          is_end=False, next_url=child_next),
            _comment_page([_raw_comment("c1c")], is_end=True),
        ], "12202014")
        # 子评论首跳无 query（实测形态）；child_comment 端点回全量，替换内嵌
        self.assertEqual(calls[1], "https://www.zhihu.com/api/v4/"
                                   "comment_v5/comment/c1/child_comment")
        self.assertEqual(calls[2], child_next)
        self.assertEqual([k["id"] for k in out[0]["child_comments"]],
                         ["c1a", "c1b", "c1c"])

    def test_602_maps_to_auth_semantics_without_self_heal(self):
        # 401+code 602"第三方应用无此权限"=该端点需登录态：归
        # ZhihuAuthExpired 语义，但 message 明写"需登录/访客不可读"，
        # 且自愈跳过（引导只领访客 cookie，刷不出登录态）
        fake = auth_fail_resp(status=401, code=602, message="第三方应用无此权限")
        boot = fake_bootstrap_module()
        with fake_cookie_file(), \
             mock.patch.object(zc.requests, "get", return_value=fake), \
             mock.patch.dict(sys.modules, {"zhihu_bootstrap": boot}):
            with self.assertRaises(zc.ZhihuAuthExpired) as cm:
                zc.fetch_comments("12202014", on_error="raise")
        msg = str(cm.exception)
        self.assertIn("602", msg)
        self.assertIn("需要登录态", msg)
        self.assertIn("访客不可读", msg)
        self.assertIn("重跑引导无用", msg)
        boot.bootstrap.assert_not_called()   # 引导刷不出登录态——不碰引导
        # report 形态：统一错误协议，slug 保留 zhihu_auth_expired
        with fake_cookie_file(), \
             mock.patch.object(zc.requests, "get", return_value=fake), \
             mock.patch.dict(sys.modules, {"zhihu_bootstrap": boot}):
            out = zc.fetch_comments("12202014")
        self.assertIn("zhihu_auth_expired", out[0]["error"])
        self.assertEqual(out[0]["tool"], "chat-scraper")
        self.assertEqual(out[0]["query"], "12202014")

    def test_max_pages_guard_reports_runaway(self):
        runaway = _comment_page(
            [_raw_comment("c1")], is_end=False,
            next_url=("https://www.zhihu.com/api/v4/comment_v5/answers/"
                      "12202014/root_comment?offset=loop"))
        out, calls = self._fetch([runaway], "12202014", num=100, max_pages=3,
                                 on_error="report")
        self.assertEqual(len(calls), 3)
        self.assertIn("zhihu_api_error", out[0]["error"])
        self.assertIn("max_pages=3", out[0]["error"])

    def test_invalid_target_and_order_by_rejected(self):
        with self.assertRaises(zc.ZhihuApiError):
            zc.fetch_comments("not-a-target", on_error="raise")
        # 专栏 URL 不是评论 target（评论线只收回答/问题）
        with self.assertRaises(zc.ZhihuApiError):
            zc.fetch_comments("https://zhuanlan.zhihu.com/p/123",
                              on_error="raise")
        with self.assertRaises(zc.ZhihuApiError):
            zc.fetch_comments("12202014", order_by="hot", on_error="raise")



class TestV36Audit(unittest.TestCase):
    """v3.6 复审：评论请求预算 / question-0 死链 / _strip_api_base 边界。"""

    def test_comment_budget_exhausts_honestly(self):
        # 复审 #1：全局请求预算护栏——耗尽时诚实报错（确定性单元测试）
        import zhihu_content as zc
        from unittest import mock
        page_body = {"data": [{"id": "1", "author": {"name": "a"},
                               "content": "c", "like_count": 0,
                               "created_time": 0, "child_comment_count": 0,
                               "child_comments": []}],
                     "paging": {"is_end": False,
                                "next": "/api/v4/comment_v5/x?offset=next"}}
        with mock.patch.object(zc, "_api_get", return_value=page_body):
            gen = zc._comment_paged("/api/v4/comment_v5/x", "ref", 50,
                                    {"used": 0, "total": 3})
            got = []
            with self.assertRaises(zc.ZhihuApiError) as cm:
                for item in gen:
                    got.append(item)   # 预算 3 < max_pages 50 → 耗尽即抛
        self.assertEqual(len(got), 3)
        self.assertIn("请求预算耗尽", str(cm.exception))
        with mock.patch.object(zc, "_api_get", return_value=page_body):
            with self.assertRaises(zc.ZhihuApiError) as cm:
                list(zc._comment_paged("/api/v4/comment_v5/x", "ref", 50,
                                       {"used": 0, "total": 2}))
        self.assertIn("请求预算耗尽", str(cm.exception))

    def test_answer_without_qid_no_dead_link(self):
        import zhihu_content as zc
        c = {"id": "78247946", "author": {"name": "a"}, "content": "c",
             "like_count": 9, "created_time": 0, "child_comment_count": 0,
             "child_comments": []}
        out = zc._comment_item(c, "answer", None, "12202014")
        self.assertEqual(out["url"], "")   # 不伪造 /question/0/ 死链

    def test_strip_api_base_boundaries(self):
        import zhihu_content as zc
        self.assertEqual(zc._strip_api_base("/api/v4/x?offset="),
                         "/api/v4/x?offset=")
        self.assertEqual(zc._strip_api_base(
            "https://www.zhihu.com/api/v4/x?a=1"), "/api/v4/x?a=1")
        for bad in ("https://evil.com/api/v4/x",
                    "https://zhihu.com.evil.com/api/v4/x",
                    "https://www.zhihu.com/web/x", "javascript:x"):
            with self.assertRaises(zc.ZhihuApiError):
                zc._strip_api_base(bad)
