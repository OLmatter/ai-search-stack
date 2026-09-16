"""v3.29.0 回归：A2 热榜聚合——hotlist_engine.py（bilibili 热门/微博热搜/
知乎诚实上限）+ 门面 search.hot() 路由 + MCP china_hotlist 工具。

五块内容（全部离线，零真实榜单请求——逻辑探测预算 8 发在评估/实施环节
消耗：6 发评估探测 + 微博 incarnate 全链实跑 1 发 + 聚合验收实跑 1 发，
回归钉全部走 mock / 源码钉）：
1. hotlist_engine bilibili 线：信封解析/字段映射/翻页 pn 链与 no_more 停/
   跨页去重/num 截断/无 bvid 丢弃/错误协议（report/raise/empty 三态）。
2. hotlist_engine weibo 线：缓存 cookie 路径/缓存缺失走 incarnate 并落
   state/HTTP 级失效重领/信封级 ok!=1 缓存路径重领/重领后仍失败如实抛/
   JSONP 壳解析（实测 window.gen_callback && gen_callback({...}) 形态）/
   is_ad 广告位剔除。
3. zhihu 诚实上限：零网络请求守卫（Session.get 被调即断言失败）+ 三态
   错误协议 + raise 形态。
4. 聚合路由：未知平台 ValueError/默认平台序与 num 逐平台透传/门面
   search.hot 委托/CLI --hot（q 省略 + 错误退出码）/MCP china_hotlist 委托。
5. 版本锁 3.29.0（双 __version__，自 test_v3280 接管精确锁）+ CHANGELOG
   + README 徽章 + 诚实文档证据链钉（docstring 实测证据/工具清单 15）。
"""
import io
import json
import pathlib
import re
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "chat-scraper"))

import hotlist_engine as hl    # noqa: E402
import search as facade        # noqa: E402

try:
    import mcp_server              # noqa: E402
except ImportError:                # mcp SDK 未安装（部分 CI）——降级源码断言
    mcp_server = None


# ---------------------------------------------------------------------------
# 共享假件
# ---------------------------------------------------------------------------
class _FakeResp:
    def __init__(self, payload=None, text="", status_code=200):
        self._p = payload
        self.text = text
        self.status_code = status_code

    def json(self):
        if isinstance(self._p, Exception):
            raise self._p
        return self._p


class _FakeBiliSession:
    """按序吐 payload 的假会话，记录 pn 链。"""

    def __init__(self, pages):
        self.pages = list(pages)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {})})
        payload = (self.pages.pop(0) if self.pages
                   else {"code": 0, "data": {"list": [], "no_more": True}})
        return _FakeResp(payload=payload)


def _bili_item(bvid, title="t"):
    """按实测形态构造一条 popular 条目（2026-09-17 探测 #3）。"""
    return {
        "bvid": bvid, "title": title,
        "owner": {"name": "up主"},
        "stat": {"view": 1, "danmaku": 2, "like": 3},
        "pubdate": 1789560000, "tname": "数码",
    }


def _weibo_payload():
    """按实测形态构造 hotSearch 信封（含广告位/无 word 脏条目）。"""
    return {"ok": 1, "data": {"realtime": [
        {"word": "话题A", "num": "614522", "label_name": "新",
         "is_ad": 0, "word_scheme": "话题A"},
        {"word": "广告位", "num": "999", "label_name": "", "is_ad": 1,
         "word_scheme": "#广告位#"},
        {"word": "话题B", "num": 143391, "label_name": "热",
         "word_scheme": "#话题B#"},
        {"word": "", "num": 1},
    ]}}


# ---------------------------------------------------------------------------
# 1. hotlist_engine bilibili 线（信封形态 = 2026-09-17 实测探测 #3/#8）
# ---------------------------------------------------------------------------
class TestBilibiliHot(unittest.TestCase):
    def _run(self, pages, **kw):
        session = _FakeBiliSession(pages)
        with mock.patch.object(hl._bili, "_wait_turn"), \
                mock.patch.object(hl._bili, "_get_session",
                                  return_value=session):
            rows = hl.hot(platforms=["bilibili"], **kw)
        return rows, session

    def test_field_mapping_and_rank(self):
        rows, session = self._run(
            [{"code": 0, "data": {"list": [
                _bili_item("BV1aaa", title="<em>高亮</em>标题&amp;转义")],
                "no_more": True}}], num=5, vendor="v", role="r")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["rank"], 1)
        self.assertEqual(row["title"], "高亮标题&转义")   # _clean_title 生效
        self.assertEqual(row["url"], "https://www.bilibili.com/video/BV1aaa")
        self.assertEqual(row["platform"], "bilibili")
        self.assertEqual(row["engine"], "hotlist")
        self.assertEqual(row["author"], "up主")
        self.assertEqual((row["views"], row["danmaku"], row["likes"]),
                         (1, 2, 3))
        self.assertEqual(row["category"], "数码")
        self.assertTrue(row["pubdate"])          # 实测时间戳，非空
        self.assertEqual((row["vendor"], row["role"]), ("v", "r"))
        self.assertNotIn("hot_value", row)       # 热门页无热度值，如实不造
        self.assertEqual(session.calls[0]["params"],
                         {"ps": 20, "pn": 1})    # 实测单页 20

    def test_paging_and_dedup(self):
        page1 = {"code": 0, "data": {"list": [_bili_item(f"BV{i}") for i in
                                             range(20)]}}   # 无 no_more 键
        page2 = {"code": 0, "data": {"list": (
            [_bili_item("BV18"), _bili_item("BV19")]    # 跨页重叠 -> 去重
            + [_bili_item(f"BV2{i}") for i in range(18)]),
            "no_more": False}}
        page3 = {"code": 0, "data": {"list": [], "no_more": True}}
        rows, session = self._run([page1, page2, page3], num=100)
        self.assertEqual(len(rows), 38)          # 20+20 去重重叠 2 条
        bvids = [r["url"].rsplit("/", 1)[-1] for r in rows]
        self.assertEqual(len(bvids), len(set(bvids)))    # 零重复
        self.assertEqual([c["params"]["pn"] for c in session.calls],
                         [1, 2, 3])              # pn 链 + 空页即停

    def test_num_cap_no_extra_page(self):
        rows, session = self._run(
            [{"code": 0, "data": {"list": [_bili_item(f"BV{i}") for i in
                                           range(20)]}}],
            num=3)
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(session.calls), 1)  # 凑满即停，不发第 2 页

    def test_no_more_stops_paging(self):
        rows, session = self._run(
            [{"code": 0, "data": {"list": [_bili_item("BV1")],
                                  "no_more": True}}], num=50)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(session.calls), 1)  # no_more=true 不翻页

    def test_no_bvid_dropped(self):
        rows, _ = self._run(
            [{"code": 0, "data": {"list": [
                {"title": "无bvid广告卡"}, _bili_item("BV1")],
                "no_more": True}}], num=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rank"], 1)     # 剔除后 rank 连续

    def test_error_protocol_three_modes(self):
        bad = [{"code": -412, "message": "请求被拦"}]
        rows, _ = self._run([dict(bad[0])], on_error="report")
        self.assertEqual(len(rows), 1)
        self.assertIn("bilibili_api_error", rows[0]["error"])
        self.assertEqual(rows[0]["platform"], "bilibili")
        self.assertNotIn("query", rows[0])       # 热榜无查询词
        rows, _ = self._run([dict(bad[0])], on_error="empty")
        self.assertEqual(rows, [])
        with self.assertRaises(hl._bili.BilibiliApiError):
            self._run([dict(bad[0])], on_error="raise")

    def test_non_json_response_reported(self):
        session = _FakeBiliSession([])
        with mock.patch.object(hl._bili, "_wait_turn"), \
                mock.patch.object(hl._bili, "_get_session",
                                  return_value=session), \
                mock.patch.object(session, "get",
                                  return_value=_FakeResp(
                                      payload=ValueError("Expecting value"),
                                      text="<html>风控</html>",
                                      status_code=403)):
            rows = hl.hot(platforms=["bilibili"], on_error="report")
        self.assertEqual(len(rows), 1)
        self.assertIn("bilibili_api_error", rows[0]["error"])


# ---------------------------------------------------------------------------
# 2. hotlist_engine weibo 线（incarnate 流 = 2026-09-17 实测探测 #7）
# ---------------------------------------------------------------------------
class TestWeiboHot(unittest.TestCase):
    def test_cache_path_field_mapping(self):
        with mock.patch.object(hl, "_load_weibo_state",
                               return_value={"SUB": "s", "SUBP": "p"}), \
                mock.patch.object(hl, "_call_hotsearch",
                                  return_value=_weibo_payload()) as mcall, \
                mock.patch.object(hl, "_incarnate_weibo_visitor") as minc:
            rows = hl.hot(platforms=["weibo"], num=10, vendor="v", role="r")
        self.assertEqual(minc.call_count, 0)     # 缓存有效不重领
        self.assertEqual(mcall.call_args[0][0], {"SUB": "s", "SUBP": "p"})
        self.assertEqual(len(rows), 2)           # 广告位 + 无 word 各剔 1
        self.assertEqual([r["rank"] for r in rows], [1, 2])
        self.assertEqual(rows[0]["title"], "话题A")
        self.assertEqual(rows[0]["hot_value"], "614522")
        self.assertEqual(rows[0]["label"], "新")
        self.assertEqual(rows[1]["label"], "热")
        self.assertTrue(rows[1]["url"].startswith(
            "https://s.weibo.com/weibo?q=%23"))  # #话题B# 已 quote
        self.assertEqual((rows[0]["vendor"], rows[0]["role"]), ("v", "r"))
        self.assertNotIn("query", rows[0])

    def test_cache_miss_incarnates_and_saves(self):
        saved = {}
        with mock.patch.object(hl, "_load_weibo_state", return_value={}), \
                mock.patch.object(
                    hl, "_incarnate_weibo_visitor",
                    return_value={"SUB": "s1", "SUBP": "p1"}) as minc, \
                mock.patch.object(hl, "_save_weibo_state",
                                  side_effect=lambda c: saved.update(c)), \
                mock.patch.object(hl, "_call_hotsearch",
                                  return_value=_weibo_payload()) as mcall:
            rows = hl.hot(platforms=["weibo"], num=5)
        self.assertEqual(minc.call_count, 1)
        self.assertEqual(saved, {"SUB": "s1", "SUBP": "p1"})  # 缓存落盘
        self.assertEqual(mcall.call_args[0][0],
                         {"SUB": "s1", "SUBP": "p1"})
        self.assertEqual(len(rows), 2)

    def test_cached_http_fail_reincarnates_once(self):
        calls = []

        def fake_call(cookies):
            calls.append(cookies)
            if len(calls) == 1:
                raise hl.WeiboHotlistError("hotSearch HTTP 403")
            return _weibo_payload()

        with mock.patch.object(hl, "_load_weibo_state",
                               return_value={"SUB": "stale"}), \
                mock.patch.object(hl, "_incarnate_weibo_visitor",
                                  return_value={"SUB": "fresh"}) as minc, \
                mock.patch.object(hl, "_save_weibo_state"), \
                mock.patch.object(hl, "_call_hotsearch",
                                  side_effect=fake_call):
            rows = hl.hot(platforms=["weibo"])
        self.assertEqual(minc.call_count, 1)     # 失效重领一次
        self.assertEqual(rows[0]["title"], "话题A")

    def test_envelope_ok_not_1_cached_reincarnates(self):
        seq = [{"ok": 0}, _weibo_payload()]    # 信封级失效 -> 重领后成功

        def fake_call(cookies):
            return seq.pop(0)

        with mock.patch.object(hl, "_load_weibo_state",
                               return_value={"SUB": "stale"}), \
                mock.patch.object(hl, "_incarnate_weibo_visitor",
                                  return_value={"SUB": "fresh"}) as minc, \
                mock.patch.object(hl, "_save_weibo_state"), \
                mock.patch.object(hl, "_call_hotsearch",
                                  side_effect=fake_call):
            rows = hl.hot(platforms=["weibo"])
        self.assertEqual(minc.call_count, 1)
        self.assertEqual(len(rows), 2)

    def test_fresh_incarnate_still_bad_raises(self):
        with mock.patch.object(hl, "_load_weibo_state", return_value={}), \
                mock.patch.object(hl, "_incarnate_weibo_visitor",
                                  return_value={"SUB": "fresh"}), \
                mock.patch.object(hl, "_save_weibo_state"), \
                mock.patch.object(hl, "_call_hotsearch",
                                  return_value={"ok": -100}):
            rows = hl.hot(platforms=["weibo"], on_error="report")
        self.assertEqual(len(rows), 1)
        self.assertIn("weibo_hotlist_error", rows[0]["error"])
        self.assertEqual(rows[0]["platform"], "weibo")
        with mock.patch.object(hl, "_load_weibo_state", return_value={}), \
                mock.patch.object(hl, "_incarnate_weibo_visitor",
                                  return_value={"SUB": "fresh"}), \
                mock.patch.object(hl, "_save_weibo_state"), \
                mock.patch.object(hl, "_call_hotsearch",
                                  return_value={"ok": -100}):
            self.assertRaises(hl.WeiboHotlistError, hl.hot,
                              platforms=["weibo"], on_error="raise")

    def test_parse_jsonp_live_shapes(self):
        # 2026-09-17 实测壳形态：window.gen_callback && gen_callback({...})
        payload = '{"retcode": 20000000, "data": {"tid": "TID1"}}'
        text = (f"window.gen_callback && gen_callback({payload});")
        self.assertEqual(hl._parse_jsonp(text, "gen_callback"),
                         {"retcode": 20000000, "data": {"tid": "TID1"}})
        # 无关前缀
        with self.assertRaises(hl.WeiboHotlistError):
            hl._parse_jsonp(text, "cross_domain")
        # 非 JSON 体
        with self.assertRaises(hl.WeiboHotlistError):
            hl._parse_jsonp("gen_callback && gen_callback(<html>)",
                            "gen_callback")
        # 无括号体
        with self.assertRaises(hl.WeiboHotlistError):
            hl._parse_jsonp("gen_callback 没有括号", "gen_callback")


# ---------------------------------------------------------------------------
# 3. zhihu 诚实上限（零网络请求）
# ---------------------------------------------------------------------------
class TestZhihuHonestLimit(unittest.TestCase):
    def test_needs_login_zero_network_three_modes(self):
        guard = mock.MagicMock(
            side_effect=AssertionError("zhihu 线不准发网络请求"))
        with mock.patch("requests.Session.get", guard):
            rows = hl.hot(platforms=["zhihu"], on_error="report")
        self.assertEqual(len(rows), 1)
        self.assertIn("zhihu_hotlist_needs_login", rows[0]["error"])
        self.assertEqual(rows[0]["platform"], "zhihu")
        self.assertIn("2026-09-17", rows[0]["error"])   # 证据链带日期
        self.assertIn("401 code=101", rows[0]["error"]) # 实测错误码
        rows = hl.hot(platforms=["zhihu"], on_error="empty")
        self.assertEqual(rows, [])
        self.assertEqual(guard.call_count, 0)    # 全程零网络

    def test_raise_mode(self):
        self.assertRaises(hl.ZhihuHotlistNeedsLogin, hl.hot,
                          platforms=["zhihu"], on_error="raise")


# ---------------------------------------------------------------------------
# 4. 聚合路由 + 门面 + CLI + MCP
# ---------------------------------------------------------------------------
class TestRoutingAndFacade(unittest.TestCase):
    def test_unknown_platform_valueerror(self):
        with self.assertRaises(ValueError) as cm:
            hl.hot(platforms=["nope"])
        self.assertIn("bilibili", str(cm.exception))
        self.assertIn("zhihu", str(cm.exception))

    def test_default_platforms_order_and_num_passthrough(self):
        seen = []

        def fake_bili(num, vendor, role):
            seen.append(("bilibili", num, vendor, role))
            return [{"rank": 1, "platform": "bilibili"}]

        def fake_weibo(num, vendor, role):
            seen.append(("weibo", num, vendor, role))
            return [{"rank": 1, "platform": "weibo"}]

        with mock.patch.dict(hl._FETCHERS,
                             {"bilibili": fake_bili, "weibo": fake_weibo},
                             clear=True):
            rows = hl.hot(platforms=None, num=7, vendor="v", role="r")
        self.assertEqual(seen, [("bilibili", 7, "v", "r"),
                                ("weibo", 7, "v", "r")])  # 默认序 + 透传
        self.assertEqual([r["platform"] for r in rows],
                         ["bilibili", "weibo"])

    def test_facade_hot_delegates(self):
        sentinel = [{"rank": 1, "title": "x"}]
        with mock.patch.object(facade.hotlist_engine, "hot",
                               return_value=sentinel) as mhot:
            out = facade.hot(platforms=["bilibili"], num=3, vendor="v",
                             role="r", on_error="raise")
        self.assertEqual(out, sentinel)
        mhot.assert_called_once_with(platforms=["bilibili"], num=3,
                                     vendor="v", role="r",
                                     on_error="raise")
        self.assertIn("hot", facade.__all__)
        self.assertIn("hot", hl.__all__)

    def test_facade_cli_hot_mode(self):
        # --hot 模式 q 省略不报错；错误记录 -> exit 1（与搜索模式同契约）
        with mock.patch.object(sys, "argv",
                               ["search.py", "--hot", "--platforms",
                                "bilibili,weibo", "--num", "5"]), \
                mock.patch.object(facade, "hot",
                                  return_value=[{"rank": 1}]) as mhot, \
                redirect_stdout(io.StringIO()):
            self.assertEqual(facade._main(), 0)
        mhot.assert_called_once_with(platforms=["bilibili", "weibo"],
                                     num=5, vendor="?", role="primary",
                                     on_error="report")
        with mock.patch.object(sys, "argv",
                               ["search.py", "--hot", "--platforms",
                                "zhihu"]), \
                mock.patch.object(facade, "hot",
                                  return_value=[{"error": "x: y",
                                                 "platform": "zhihu"}]), \
                redirect_stdout(io.StringIO()), \
                redirect_stderr(io.StringIO()):
            self.assertEqual(facade._main(), 1)
        # 搜索模式仍强制 q（--hot 不改变既有行为）
        with mock.patch.object(sys, "argv", ["search.py"]), \
                self.assertRaises(SystemExit):
            facade._main()

    def test_mcp_china_hotlist_tool(self):
        if mcp_server is not None:
            sentinel = [{"rank": 1, "title": "x", "platform": "weibo"}]
            with mock.patch.object(mcp_server._chat, "hot",
                                   return_value=sentinel) as mhot:
                out = mcp_server.china_hotlist(platforms=["weibo"], num=5,
                                               vendor="v", role="r")
            self.assertEqual(json.loads(out), sentinel)
            mhot.assert_called_once_with(platforms=["weibo"], num=5,
                                         vendor="v", role="r",
                                         on_error="report")
        else:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            self.assertIn("china_hotlist", src)
            self.assertIn("_chat.hot", src)


# ---------------------------------------------------------------------------
# 5. 版本锁 3.29.0（自 test_v3280 接管精确锁）+ 文档 + 诚实文档证据链
# ---------------------------------------------------------------------------
class TestVersionSyncV329(unittest.TestCase):
    def test_versions_3290(self):
        if mcp_server is None:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            ver = re.search(r'__version__ = "([^"]+)"', src).group(1)
        else:
            ver = mcp_server.__version__
        self.assertEqual(ver, "3.29.0")
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        self.assertIn(f'__version__ = "{ver}"', init_src)
        self.assertIn(f"chat-scraper v{ver}", init_src)

    def test_changelog_and_readme_3290(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.29.0] - 2026-09-17", changelog)
        self.assertIn("热榜", changelog)
        self.assertIn("incarnate", changelog)
        self.assertIn("zhihu_hotlist_needs_login", changelog)
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("release-v3.29.0", readme)
        self.assertIn("v3.29.0（2026-09-17）", readme)
        # 测试徽章数随本批钉死（下一批交接时降常青）
        m = re.search(r"tests-(\d+)%20passing", readme)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "491")

    def test_honest_doc_evidence_chain(self):
        # 诚实文档（架构原则 8）：能力声明以实测为准，证据链进 docstring
        doc = hl.__doc__ or ""
        self.assertIn("2026-09-17", doc)
        self.assertIn("401 code=101", doc)       # zhihu 实测错误码
        self.assertIn("popular", doc)            # bilibili 实测端点
        self.assertIn("incarnate", doc)          # weibo 访客流
        # mcp 工具清单 14 -> 15
        src = (REPO / "tools" / "mcp_server.py").read_text(
            encoding="utf-8")
        self.assertIn("工具清单（15）", src)
        self.assertIn("china_hotlist", src)
        # __init__ 版本史条目
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        self.assertIn("v3.29.0", init_src)
        self.assertIn("hotlist_engine", init_src)


if __name__ == "__main__":
    unittest.main()
