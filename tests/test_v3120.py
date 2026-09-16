"""v3.12.0 回归：百度搜索翻页 + 跨页去重（审查 A1）+ 截断可见化扫尾
（wenxin / bilibili desc）。

四块内容（全部离线，零真实请求、零浏览器）：
1. 百度搜索翻页：num>20 不再静默截断（v3.11 只修了 bilibili，本轮把同一
   架构病扫完最后一处引擎）。单页快路径请求次数与 v3.11 一致（1 次）；
   翻页沿 num/空页(含整页重复)/MAX_PAGES 三停止条件，pn 偏移逐页正确；
   已收集 >0 条后桌面桶病了→如实抛错（message 含已收集数，不伪装部分
   结果为完整，也绝不切移动桶）；0 收获才走移动桶兜底（v3.2 语义原样）。
2. 跨页去重（审查 A1，独立审计发现）：两引擎翻页页间重叠条目不再重复进
   返回集；整页重复 = 排序穷尽信号，如实停不发多余请求（baidu +
   bilibili v3.11 引入的同构病一并扫出）。
3. 截断可见化扫尾：wenxin answer/citations[].abstract、bilibili
   fetch_video desc 三处输出口全部带 truncated 标记；源代码级断言不再有
   裸截断切片（wenxin [:ANSWER_MAX_CHARS]/[:ABSTRACT_MAX_CHARS]、
   bilibili [:2000]）。
4. 版本一致性：mcp_server __version__ 同步 3.12.0。
"""
import pathlib
import sys
import unittest
from unittest import mock

import requests

REPO = pathlib.Path(__file__).resolve().parent.parent
for d in ("", "chat-scraper"):
    sys.path.insert(0, str(REPO / "tools" / d))

import baidu_engine as bd          # noqa: E402  (chat-scraper/baidu_engine.py)
import bilibili_engine as be       # noqa: E402  (chat-scraper/bilibili_engine.py)
import wenxin_engine as we         # noqa: E402  (chat-scraper/wenxin_engine.py)


def _baidu_html(n, base=0):
    """n 条百度桌面结果的最小 HTML（mu 属性=直链，h3=标题）。

    base：url 偏移，用于构造页间不重复的多页数据（翻页早停语义下，
    页间重复=到底信号，见 test_cross_page_duplicates_deduped_and_stop_honest）。
    """
    return "".join(
        f'<div class="result" mu="https://example.com/p/{base + i}">'
        f"<h3>标题{base + i}</h3></div>" for i in range(n))


class _Resp:
    def __init__(self, text):
        self.text = text


# ---- 1. 百度搜索翻页 --------------------------------------------------------


class TestBaiduPaginationV312(unittest.TestCase):
    """_search_impl 翻页：三停止条件 + 单页快路径 + 半途风控如实抛错。"""

    def setUp(self):
        self.calls = []

    def _run(self, pages, **kw):
        """pages: 每页 HTML 字符串列表（按请求顺序，耗尽后再请求即报错——
        测试自身写错页数的护栏）。mock 掉会话与节流。

        返回 (rows, engine)。
        """
        it = iter(pages)

        def fake_get(self_sess, url, **kwargs):
            self.calls.append(dict(kwargs.get("params") or {}))
            return _Resp(next(it))

        sess = requests.Session()
        with mock.patch.object(bd, "_get_session", return_value=sess), \
             mock.patch.object(bd, "_min_interval", return_value=0.0), \
             mock.patch.object(requests.Session, "get", fake_get):
            return bd._search_impl(kw.pop("q", "测试"), kw.pop("num"),
                                   kw.pop("since", None),
                                   kw.pop("site", None),
                                   kw.pop("name", "general"),
                                   kw.pop("page", 1))

    def test_single_page_fast_path_makes_one_request(self):
        out, engine = self._run([_baidu_html(20)], num=10)
        self.assertEqual(len(out), 10)
        self.assertEqual(engine, "baidu")
        self.assertEqual(len(self.calls), 1)   # 与 v3.11 单页行为等价
        self.assertEqual(self.calls[0]["pn"], 0)
        self.assertEqual(self.calls[0]["rn"], bd.RESULTS_PER_PAGE)

    def test_num_over_20_paginates_until_num(self):
        # 45 条需 3 页（20×3=60≥45），pn 偏移 0/20/40
        out, _ = self._run([_baidu_html(20, 0), _baidu_html(20, 20),
                            _baidu_html(20, 40)], num=45)
        self.assertEqual(len(out), 45)
        self.assertEqual([c["pn"] for c in self.calls], [0, 20, 40])

    def test_empty_page_stops_honestly(self):
        # 服务端空页=真空到底：如实返回 5 条，不多发第 3 页
        out, _ = self._run([_baidu_html(5), _baidu_html(0)], num=50)
        self.assertEqual(len(out), 5)
        self.assertEqual(len(self.calls), 2)

    def test_max_pages_guard_caps_requests(self):
        # 护栏 3 页封顶（每页 20 条新数据；页间重复会触发诚实早停，
        # 那是另一条测试的职责）
        out, _ = self._run([_baidu_html(20, pg * 20) for pg in range(6)],
                           num=1000)
        self.assertEqual(len(out), bd.MAX_PAGES * bd.RESULTS_PER_PAGE)  # 60
        self.assertEqual(len(self.calls), bd.MAX_PAGES)  # 护栏 3 页封顶

    def test_num_zero_makes_no_request(self):
        out, _ = self._run([], num=0)
        self.assertEqual(out, [])
        self.assertEqual(self.calls, [])

    def test_explicit_start_page_sets_pn_offset(self):
        self._run([_baidu_html(20)], num=5, page=2)
        self.assertEqual(self.calls[0]["pn"], 20)

    def test_since_gpc_carried_on_every_page(self):
        out, _ = self._run([_baidu_html(20, 0), _baidu_html(20, 20)],
                           num=30, since="7d")
        self.assertEqual(len(out), 30)
        for c in self.calls:
            self.assertIn("stftype=2", c["gpc"])

    def test_interrupted_after_partial_collect_raises_honestly(self):
        # 已收集 >0 条后桌面桶病了（占位页退避穷尽）→ 抛 BaiduSoftBlocked，
        # message 讲明已收集页数/条数；绝不切移动桶、不伪装部分结果为完整
        placeholder = "short page containing timeout"
        seq = [_Resp(_baidu_html(20))] + [_Resp(placeholder)] * 3
        with mock.patch.object(bd, "_get_session",
                               return_value=requests.Session()), \
             mock.patch.object(bd, "_min_interval", return_value=0.0), \
             mock.patch.object(requests.Session, "get",
                               side_effect=seq), \
             mock.patch.object(bd, "_mobile_search_impl") as mobile_mock:
            with self.assertRaises(bd.BaiduSoftBlocked) as cm:
                bd._search_impl("测试", 45, None, None, "general")
        self.assertIn("20 rows collected", str(cm.exception))
        self.assertIn("1 page(s)", str(cm.exception))
        mobile_mock.assert_not_called()   # 半途病了不烧第二个风控桶

    def test_zero_collect_desktop_down_still_falls_back_to_mobile(self):
        # v3.2 语义原样保留：0 收获时桌面穷尽 → 移动桶兜底（单页）
        mobile_rows = [{"title": "m", "url": "https://example.com/m",
                        "snippet": ""}]
        with mock.patch.object(bd, "_get_session",
                               return_value=requests.Session()), \
             mock.patch.object(bd, "_min_interval", return_value=0.0), \
             mock.patch.object(requests.Session, "get",
                               return_value=_Resp(
                                   "short page containing timeout")), \
             mock.patch.object(bd, "_mobile_search_impl",
                               return_value=mobile_rows):
            out, engine = bd._search_impl("测试", 45, None, None, "general")
        self.assertEqual(engine, "baidu-mobile")
        self.assertEqual(out, mobile_rows)

    def test_cross_page_duplicates_deduped_and_stop_honest(self):
        # 审查 A1（独立审计发现）：_parse_results 的 seen 是页内局部，
        # pn 翻页页间重叠是百度常态——重复 url 不得进返回集；整页全是
        # 重复 = 已到底，如实停（不空抛、不多发请求）
        page1 = _baidu_html(20)
        page2_mixed = _baidu_html(10) + "".join(
            f'<div class="result" mu="https://example.com/new/{i}">'
            f"<h3>新{i}</h3></div>" for i in range(5))   # 10 重复 + 5 新
        it = iter([page1, page2_mixed, _baidu_html(0)])   # 第 3 页空页=真空
        calls = []

        def fake_get(s, url, **kwargs):
            calls.append(dict(kwargs.get("params") or {}))
            return _Resp(next(it))

        with mock.patch.object(bd, "_get_session",
                               return_value=requests.Session()), \
             mock.patch.object(bd, "_min_interval", return_value=0.0), \
             mock.patch.object(requests.Session, "get", fake_get):
            out, _ = bd._search_impl("测试", 45, None, None, "general")
        urls = [r["url"] for r in out]
        self.assertEqual(len(urls), len(set(urls)))          # 跨页无重复
        self.assertEqual(len(out), 25)                       # 20 + 5 新
        self.assertEqual([c["pn"] for c in calls], [0, 20, 40])

    def test_page_all_duplicates_stops_without_extra_request(self):
        # 第二页整页跨页重复 = 没有新内容，如实停，不发第三页
        page1 = _baidu_html(20)
        it = iter([page1, page1])
        calls = []

        def fake_get(s, url, **kwargs):
            calls.append(dict(kwargs.get("params") or {}))
            return _Resp(next(it))

        with mock.patch.object(bd, "_get_session",
                               return_value=requests.Session()), \
             mock.patch.object(bd, "_min_interval", return_value=0.0), \
             mock.patch.object(requests.Session, "get", fake_get):
            out, _ = bd._search_impl("测试", 45, None, None, "general")
        self.assertEqual(len(out), 20)
        self.assertEqual(len(calls), 2)

    def test_report_mode_wraps_interruption_as_error_record(self):
        # 双桶皆病经 search(on_error="report") 包装为统一错误记录（slug
        # baidu_soft_blocked），不炸调用方——门面降级搜狗语义已由
        # test_offline 覆盖，此处钉 report 兜底形态
        with mock.patch.object(bd, "_get_session",
                               return_value=requests.Session()), \
             mock.patch.object(bd, "_min_interval", return_value=0.0), \
             mock.patch.object(requests.Session, "get",
                               return_value=_Resp(
                                   "short page containing timeout")), \
             mock.patch.object(bd, "_mobile_search_impl",
                               side_effect=bd.BaiduSoftBlocked(
                                   "mobile also down")), \
             mock.patch.object(bd, "_reset_sessions"):
            out = bd.search("q", num=45, on_error="report")
        self.assertEqual(len(out), 1)
        self.assertIn("baidu_soft_blocked", out[0]["error"])


# ---- 2. 截断可见化扫尾 ------------------------------------------------------


class TestWenxinTruncatedV312(unittest.TestCase):
    """wenxin answer / citations[].abstract 截断带 truncated 标记。"""

    @staticmethod
    def _sse(answer_chars, abstract_chars):
        """拼最小 SSE 流：一段 markdown-yiyan 增量 + 一条引用。"""
        answer = "字" * answer_chars
        abstract = "引" * abstract_chars
        msg = ('{"status":0,"data":{"message":{"metaData":{"endTurn":true},'
               '"content":{"hints":{"parts":[]},"generator":{'
               '"component":"markdown-yiyan","data":{"value":"' + answer +
               '"}}}}}}')
        ref = ('{"status":0,"data":{"message":{"content":{"hints":{"parts":[]},'
               '"generator":{"component":"thinkingSteps","data":{'
               '"referenceList":[{"url":"https://example.com/a",'
               '"text":"标题","abstract":"' + abstract + '","source":"示例"}]'
               '}}}}}}')
        return f"event: message\ndata: {msg}\n\nevent: message\ndata: {ref}\n\n"

    def test_clip_helper_boundaries(self):
        self.assertEqual(we._clip("短", 10), ("短", False))
        self.assertEqual(we._clip("字" * 10, 10), ("字" * 10, False))
        self.assertEqual(we._clip("字" * 11, 10), ("字" * 10, True))

    def test_parse_sse_abstract_truncation_marked(self):
        out = we.parse_sse(self._sse(10, we.ABSTRACT_MAX_CHARS + 100))
        self.assertEqual(len(out["citations"][0]["abstract"]),
                         we.ABSTRACT_MAX_CHARS)
        self.assertTrue(out["citations"][0]["truncated"])
        out2 = we.parse_sse(self._sse(10, 50))
        self.assertFalse(out2["citations"][0]["truncated"])

    def test_search_answer_truncation_marked(self):
        # 熔断隔离 + 浏览器层 mock：answer 超限被截时顶层 truncated=true
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(we, "BREAKER_PATH",
                                   os.path.join(td, "breaker.json")), \
                 mock.patch.object(we, "_breaker_open_until", 0.0), \
                 mock.patch.object(we, "_search_via_browser",
                                   return_value=self._sse(
                                       we.ANSWER_MAX_CHARS + 100, 10)):
                row = we.search("测试", on_error="raise")
        self.assertEqual(len(row["answer"]), we.ANSWER_MAX_CHARS)
        self.assertTrue(row["truncated"])

    def test_search_answer_short_not_marked(self):
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(we, "BREAKER_PATH",
                                   os.path.join(td, "breaker.json")), \
                 mock.patch.object(we, "_breaker_open_until", 0.0), \
                 mock.patch.object(we, "_search_via_browser",
                                   return_value=self._sse(50, 10)):
                row = we.search("测试", on_error="raise")
        self.assertFalse(row["truncated"])


def _view_payload(desc):
    return {"code": 0, "data": {
        "title": "t", "desc": desc,
        "owner": {"name": "up"}, "cid": 17,
        "stat": {"view": 1, "danmaku": 2, "like": 3, "favorite": 4},
        "pubdate": 1700000000}}


class TestBilibiliDescTruncatedV312(unittest.TestCase):
    """fetch_video desc 超 DESC_LIMIT=2000 时 truncated=true（v3.11 只扫了
    zhihu_content 四处，本轮把 view API 这处输出截断扫掉）。"""

    def _fetch(self, desc):
        with mock.patch.object(be, "_get_session",
                               return_value=requests.Session()), \
             mock.patch.object(be, "_min_interval", return_value=0.0), \
             mock.patch.object(requests.Session, "get",
                               return_value=mock.Mock(
                                   status_code=200,
                                   json=lambda: _view_payload(desc))):
            return be.fetch_video("BV1GJ411x7h7", on_error="raise")

    def test_long_desc_marked_and_clipped(self):
        out = self._fetch("d" * 2500)
        self.assertEqual(len(out["desc"]), be.DESC_LIMIT)
        self.assertTrue(out["truncated"])

    def test_short_desc_not_marked(self):
        out = self._fetch("短简介")
        self.assertFalse(out["truncated"])

    def test_boundary_exactly_2000_not_marked(self):
        out = self._fetch("d" * 2000)
        self.assertEqual(len(out["desc"]), 2000)
        self.assertFalse(out["truncated"])


class TestNoSilentTruncationLeftV312(unittest.TestCase):
    """源代码级断言：裸截断切片清零，所有截断口统一带标记。"""

    def test_wenxin_no_bare_clips(self):
        src = (REPO / "tools" / "chat-scraper" / "wenxin_engine.py"
               ).read_text(encoding="utf-8")
        self.assertNotIn("[:ANSWER_MAX_CHARS]", src)
        self.assertNotIn("[:ABSTRACT_MAX_CHARS]", src)

    def test_bilibili_no_bare_desc_clip(self):
        src = (REPO / "tools" / "chat-scraper" / "bilibili_engine.py"
               ).read_text(encoding="utf-8")
        self.assertNotIn("[:2000]", src)


def _item(i, pubdate=1700000000):
    """bilibili 搜索 result 行的最小字段子集（bvid 唯一键）。"""
    return {"bvid": f"BV{i:011d}x",
            "title": f"<em class=\"keyword\">t{i}</em>",
            "description": f"d{i}", "author": f"a{i}", "play": i,
            "pubdate": pubdate}


def _page(items):
    return {"code": 0, "data": {"result": items}}


class TestBilibiliCrossPageDedupV312(unittest.TestCase):
    """审查 A1 同构修复：bilibili v3.11 翻页的跨页重复条目过滤。"""

    def test_duplicate_bvid_across_pages_deduped(self):
        # 第二页 25 个跨页重复 + 5 个新；num=35 恰好满足即停（2 页）
        it = iter([_page([_item(i) for i in range(30)]),
                   _page([_item(i) for i in range(25)] +   # 25 个跨页重复
                         [_item(100 + i) for i in range(5)])])  # 5 个新
        calls = []

        def fake_call(s, params):
            calls.append(dict(params))
            return next(it)

        with mock.patch.object(be, "_get_session", return_value=object()), \
             mock.patch.object(be, "_call_search", side_effect=fake_call):
            out = be._search_impl("测试", 35, None, "?", "primary", 1)
        urls = [r["url"] for r in out]
        self.assertEqual(len(urls), len(set(urls)))   # 跨页无重复
        self.assertEqual(len(out), 35)                # 30 + 5 新
        self.assertEqual([c["page"] for c in calls], [1, 2])

    def test_all_duplicate_page_stops_without_extra_request(self):
        # 整页跨页重复 = 排序已穷尽信号，如实停（不烧第 3 页）
        it = iter([_page([_item(i) for i in range(30)]),
                   _page([_item(i) for i in range(30)])])
        calls = []

        def fake_call(s, params):
            calls.append(dict(params))
            return next(it)

        with mock.patch.object(be, "_get_session", return_value=object()), \
             mock.patch.object(be, "_call_search", side_effect=fake_call):
            out = be._search_impl("测试", 90, None, "?", "primary", 1)
        self.assertEqual(len(out), 30)
        self.assertEqual([c["page"] for c in calls], [1, 2])


# ---- 3. 版本一致性 ----------------------------------------------------------

class TestVersionSyncV312(unittest.TestCase):
    def test_mcp_server_version_not_older_than_3120(self):
        # 3.13 起改为常青下限：精确锁当前版本是 test_v3130 的职责
        sys.path.insert(0, str(REPO / "tools"))
        import mcp_server
        self.assertGreaterEqual(
            tuple(int(x) for x in mcp_server.__version__.split(".")),
            (3, 12, 0))


if __name__ == "__main__":
    unittest.main()
