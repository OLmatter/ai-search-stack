"""v3.11.0 回归：doctor GitHub 403 根因修复 + B站搜索翻页 + Method 2 死代码
清理 + 截断可见化。

四块内容（全部离线，零真实请求、零浏览器）：
1. doctor.check_github（v3.11）：实测对照（2026-09-16，同 IP 同分钟）证明
   裸 urlopen 默认 UA（Python-urllib/3.x）被 GitHub 按 IP 强限流成稳定 403
   "rate limit exceeded"，带 UA 直连即 200——修复=走 _get() 统一通道。
   测试钉死两件事：check_github 绝不再碰裸 urlopen；HTTPError 照常上抛
   （_check 才好标 ❌）。
2. bilibili 搜索翻页：num>30 不再静默截断。单页快路径请求次数与 v3.10
   一致；翻页沿 num/空页/MAX_PAGES 三停止条件；页间节流走引擎内置
   _wait_turn（本测试 mock 掉 _call_search，不触网）；wbi 重试路径逐页存活。
3. 截断可见化：_content_field 统一 8000 截断 + truncated 标记；源代码级
   断言 zhihu_content.py 不再有裸 text[:8000]。
4. search_helper Method 2 死代码确已删除且文件仍可编译。
"""
import pathlib
import py_compile
import sys
import time
import unittest
import urllib.error
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
for d in ("", "chat-scraper"):
    sys.path.insert(0, str(REPO / "tools" / d))

import doctor  # noqa: E402  (tools/doctor.py)
import bilibili_engine as be  # noqa: E402  (chat-scraper/bilibili_engine.py)
import zhihu_content as zc  # noqa: E402  (chat-scraper/zhihu_content.py)


# ---- 1. doctor GitHub 检查（v3.11 根因修复） -------------------------------


class TestDoctorGithubV311(unittest.TestCase):
    """check_github 走 _get() 统一通道：UA 头 + 绕代理 opener。"""

    def test_uses_get_channel_never_bare_urlopen(self):
        # 双重断言：_get 被调用且返回可达详情；裸 urlopen 一旦被碰立即炸
        # （回归钉：谁把裸 urlopen 改回来，这条就红）
        with mock.patch.object(doctor, "_get", return_value="{}") as m, \
             mock.patch.object(urllib.request, "urlopen",
                               side_effect=AssertionError(
                                   "check_github 不得再用裸 urlopen")):
            detail = doctor.check_github()
        m.assert_called_once()
        self.assertIn("api.github.com", m.call_args[0][0])
        self.assertIn("200", detail)

    def test_http_error_propagates_for_check_runner(self):
        err = urllib.error.HTTPError("https://api.github.com/", 403,
                                     "rate limit exceeded", None, None)
        with mock.patch.object(doctor, "_get", side_effect=err):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                doctor.check_github()
        self.assertEqual(cm.exception.code, 403)


# ---- 2. bilibili 搜索翻页 ---------------------------------------------------


def _item(i, pubdate=1700000000):
    """搜索 result 行的实测字段子集（bvid 缺失=广告卡）。"""
    return {"bvid": f"BV{i:011d}x",
            "title": f"<em class=\"keyword\">t{i}</em>",
            "description": f"d{i}", "author": f"a{i}", "play": i,
            "pubdate": pubdate}


def _page(items):
    return {"code": 0, "data": {"result": items}}


class TestBilibiliPaginationV311(unittest.TestCase):
    """_search_impl 翻页：三停止条件 + 单页快路径 + wbi 重试逐页存活。"""

    def setUp(self):
        self.calls = []

    def _run(self, payloads, **kw):
        """mock 掉 _get_session/_call_search 跑 _search_impl，记录每页 params。"""
        it = iter(payloads)

        def fake_call(s, params):
            self.calls.append(dict(params))
            return next(it)

        with mock.patch.object(be, "_get_session", return_value=object()), \
             mock.patch.object(be, "_call_search", side_effect=fake_call):
            return be._search_impl(kw.pop("q", "测试"), kw.pop("num"),
                                   kw.pop("since", None), kw.pop("vendor", "?"),
                                   kw.pop("role", "primary"),
                                   kw.pop("page", 1))

    def test_single_page_fast_path_makes_one_request(self):
        out = self._run([_page([_item(i) for i in range(30)])], num=10)
        self.assertEqual(len(out), 10)
        self.assertEqual(len(self.calls), 1)   # 与 v3.10 单页行为等价
        self.assertEqual(self.calls[0]["page"], 1)

    def test_num_over_30_paginates_until_num(self):
        out = self._run([_page([_item(i) for i in range(30)]),
                         _page([_item(i) for i in range(30, 60)])], num=45)
        self.assertEqual(len(out), 45)
        self.assertEqual([c["page"] for c in self.calls], [1, 2])

    def test_empty_page_stops_honestly(self):
        # 服务端空页=真空到底：如实返回 5 条，不多发第 3 页
        out = self._run([_page([_item(i) for i in range(5)]), _page([])],
                        num=50)
        self.assertEqual(len(out), 5)
        self.assertEqual(len(self.calls), 2)

    def test_max_pages_guard_caps_requests(self):
        out = self._run([_page([_item(i) for i in range(30)])] * 6, num=1000)
        self.assertEqual(len(out), be.MAX_PAGES * 30)   # 150
        self.assertEqual(len(self.calls), be.MAX_PAGES)  # 护栏 5 页封顶

    def test_since_filter_spans_pages(self):
        now = int(time.time())
        recent, old = now - 60, now - 90 * 86400 - 60
        out = self._run([_page([_item(1, pubdate=recent), _item(2, pubdate=recent)]),
                         _page([_item(3, pubdate=recent),
                                _item(4, pubdate=old)])],
                        num=3, since="24h")
        self.assertEqual(len(out), 3)
        self.assertEqual([c["page"] for c in self.calls], [1, 2])
        self.assertNotIn("https://www.bilibili.com/video/BV0000000004x",
                         [r["url"] for r in out])   # 老视频被客户端过滤

    def test_num_zero_makes_no_request(self):
        out = self._run([], num=0)
        self.assertEqual(out, [])
        self.assertEqual(self.calls, [])

    def test_explicit_start_page(self):
        self._run([_page([_item(i) for i in range(30)])], num=5, page=2)
        self.assertEqual(self.calls[0]["page"], 2)

    def test_wbi_retry_path_survives_refactor(self):
        it = iter([{"code": -403, "message": "请求被拦截"},
                   _page([_item(i) for i in range(10)])])

        def fake_call(s, params):
            self.calls.append(dict(params))
            return next(it)

        with mock.patch.object(be, "_get_session", return_value=object()), \
             mock.patch.object(be, "_call_search", side_effect=fake_call), \
             mock.patch.object(be, "_get_wbi_keys",
                               return_value=("a" * 32, "b" * 32)):
            out = be._search_impl("测试", 5, None, "?", "primary", 1)
        self.assertEqual(len(out), 5)
        self.assertEqual(len(self.calls), 2)   # 裸调被拒 → 签名重试成功
        self.assertTrue(self.calls[1]["wts"])  # 第二跳带 wbi 签名参数


# ---- 3. 截断可见化 ----------------------------------------------------------


class TestTruncatedMarkerV311(unittest.TestCase):
    """_content_field：8000 截断 + truncated 标记，四处输出口统一。"""

    def test_short_text_not_truncated(self):
        content, truncated = zc._content_field("短正文")
        self.assertEqual((content, truncated), ("短正文", False))

    def test_boundary_8000_is_not_truncated_8001_is(self):
        text = "字" * zc.CONTENT_LIMIT
        content, truncated = zc._content_field(text)
        self.assertEqual(len(content), zc.CONTENT_LIMIT)
        self.assertFalse(truncated)
        content, truncated = zc._content_field(text + "!")
        self.assertEqual(len(content), zc.CONTENT_LIMIT)
        self.assertTrue(truncated)

    def _article_data(self, body_chars):
        return {"id": 123, "title": "文章", "content": f"<p>{'字' * body_chars}</p>",
                "created": 1700000000, "updated": 1700000001,
                "voteup_count": 1, "comment_count": 0}

    def test_fetch_article_long_marks_truncated(self):
        with mock.patch.object(zc, "_api_get",
                               return_value=self._article_data(9000)):
            out = zc.fetch_article("123")
        self.assertEqual(len(out["content"]), zc.CONTENT_LIMIT)
        self.assertTrue(out["truncated"])

    def test_fetch_article_short_marks_not_truncated(self):
        with mock.patch.object(zc, "_api_get",
                               return_value=self._article_data(50)):
            out = zc.fetch_article("123")
        self.assertFalse(out["truncated"])

    def test_no_silent_truncation_left_in_source(self):
        src = (REPO / "tools" / "chat-scraper" / "zhihu_content.py"
               ).read_text(encoding="utf-8")
        self.assertNotIn("[:8000]", src)   # 裸截断清零，统一走 _content_field


# ---- 4. search_helper Method 2 死代码清理 ----------------------------------


class TestSearchHelperDeadCodeV311(unittest.TestCase):
    """可证惰性块（循环体只有 pass）确已删除，且文件仍可编译。"""

    def test_method2_block_removed(self):
        src = (REPO / "tools" / "google-bridge" / "search_helper.py"
               ).read_text(encoding="utf-8")
        self.assertNotIn("AF_initDataCallback", src)

    def test_search_helper_still_compiles(self):
        py_compile.compile(str(REPO / "tools" / "google-bridge" /
                               "search_helper.py"), doraise=True)


if __name__ == "__main__":
    unittest.main()
