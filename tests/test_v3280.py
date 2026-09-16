"""v3.28.0 回归：三轴批次——A1 掘金官方搜索 API 专用引擎 + B1 google-bridge
常驻看门狗（Windows 计划任务）+ C1 zhihu_content 通用阅读线拆分 read_page.py。

六块内容（全部离线，零真实搜索请求——掘金实测 2 发探测在实施环节消耗
（预算 8 发实耗 2），看门狗实机取证（杀进程真实拉起 + schtasks /Run 调度
链）不烧任何搜索配额，回归钉全部走 mock / 本地 HTTP / 源码钉）：
1. juejin_engine：信封解析/字段映射/类型过滤/翻页游标链/MAX_PAGES 护栏/
   跨页去重/since 过滤/错误协议（mock 会话，信封形态取自 2026-09-16
   实测 2 发探测：data 直接列表 + 顶层 cursor/has_more + result_type=2）。
2. search 门面路由：juejin 走专用引擎，百度 site: 路由不再接手。
3. watchdog：健康判定三态（200/HTTPError=活，连接拒绝=死）/恢复编排
   退出码契约（0/1/2/3）/.env setdefault 语义/分离进程拉起形状。
4. watchdog_task：注册参数构造（承重任务先烧）/GBK 解码回退链/幂等卸载
   （中文「找不到」措辞）/ONLOGON 拒绝降级语义（承重成败定退出码）。
5. C1 拆分钉：read_page 模块 AST 级零知乎依赖 + zc 重导出同体（引用路径
   不变的兼容契约）+ mcp read_page 工具仍委托 zhihu_content.read。
6. 版本锁 3.28.0（双 __version__，自 test_v3270 接管精确锁）+ CHANGELOG
   + README 徽章。
"""
import ast
import io
import json
import os
import pathlib
import re
import sys
import unittest
from contextlib import redirect_stderr
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools" / "chat-scraper"))
sys.path.insert(0, str(REPO / "tools" / "google-bridge"))

import juejin_engine as je    # noqa: E402
import search as facade       # noqa: E402
import watchdog as wd         # noqa: E402
import watchdog_task as wt    # noqa: E402
import zhihu_content as zc    # noqa: E402
import read_page as rp        # noqa: E402

try:
    import mcp_server              # noqa: E402
except ImportError:                # mcp SDK 未安装（部分 CI）——降级源码断言
    mcp_server = None


# ---------------------------------------------------------------------------
# 1. juejin_engine（信封形态 = 2026-09-16 实测 2 发探测）
# ---------------------------------------------------------------------------

def _article(aid, title="t", ctime="1700000000", author="张三"):
    """按实测形态构造一条 result_type=2 的掘金条目。"""
    return {
        "result_type": 2,
        "result_model": {
            "article_id": aid,
            "article_info": {
                "article_id": aid, "title": title, "brief_content": "摘要"
                + aid, "ctime": ctime, "view_count": 100,
                "digg_count": 10, "comment_count": 2,
            },
            "author_user_info": {"user_name": author},
            "category": {"category_name": "前端"},
        },
    }


class _FakeResp:
    def __init__(self, payload):
        self._p = payload
        self.status_code = 200
        self.text = ""

    def json(self):
        if isinstance(self._p, Exception):
            raise self._p
        return self._p


def _juejin(pages, num=10, since=None, on_error="raise"):
    """跑 juejin_engine.search：会话打 mock（离线零请求）、节流归零。

    pages: 按请求顺序返回的信封列表；返回 (results, captured_params_list)。
    """
    calls = []

    class _Sess:
        def get(self, url, params=None, timeout=None):
            calls.append(dict(params or {}))
            return _FakeResp(pages[min(len(calls) - 1, len(pages) - 1)])

    with mock.patch.object(je, "_get_session", return_value=_Sess()), \
            mock.patch.dict(os.environ,
                            {je.ENV_MIN_INTERVAL: "0"}):
        results = je.search("q", num=num, since=since, on_error=on_error)
    return results, calls


class TestJuejinEngine(unittest.TestCase):
    def test_field_mapping(self):
        out, calls = _juejin([
            {"err_no": 0, "err_msg": "success",
             "data": [_article("7067424364894879781", title="图解 python",
                               ctime="1645512968")],
             "cursor": "20_x", "has_more": False, "count": 1}])
        self.assertEqual(len(out), 1)
        r = out[0]
        self.assertEqual(r["title"], "图解 python")
        self.assertEqual(r["url"],
                         "https://juejin.cn/post/7067424364894879781")
        self.assertEqual(r["author"], "张三")
        self.assertEqual(r["views"], 100)
        self.assertEqual(r["diggs"], 10)
        self.assertEqual(r["comments"], 2)
        self.assertEqual(r["category"], "前端")
        self.assertEqual(r["platform"], "juejin")
        self.assertEqual(r["engine"], "juejin")
        # ctime unix 秒串 → 本地时间 "%Y-%m-%d %H:%M"（按 datetime 计算期望值，
        # 钉格式契约与字段映射，不钉墙上时区）
        import datetime as _dt
        self.assertEqual(r["pubdate"],
                         _dt.datetime.fromtimestamp(
                             1645512968).strftime("%Y-%m-%d %H:%M"))
        # 请求形状（实测探测形态）：id_type=0 + search_type=0 + limit=20
        self.assertEqual(calls[0]["id_type"], "0")
        self.assertEqual(calls[0]["search_type"], "0")
        self.assertEqual(calls[0]["limit"], "20")
        self.assertEqual(calls[0]["cursor"], "0")
        self.assertEqual(calls[0]["query"], "q")

    def test_title_tag_strip_defensive(self):
        out, _ = _juejin([{"err_no": 0, "data": [
            _article("1", title="<em>py</em> &amp; go")]}])
        self.assertEqual(out[0]["title"], "py & go")

    def test_non_article_and_bad_models_dropped(self):
        out, _ = _juejin([{"err_no": 0, "data": [
            {"result_type": 1, "result_model": {"user_id": "u"}},   # 非文章
            {"result_type": 2, "result_model": "article"},          # 旧字符串形态
            {"result_type": 2, "result_model": {"article_id": ""}},  # 空 id
            _article("2"),
        ]}])
        self.assertEqual([r["url"].rsplit("/", 1)[-1] for r in out], ["2"])

    def test_err_no_nonzero_is_error_not_empty(self):
        bad = {"err_no": 403, "err_msg": "forbidden"}
        with self.assertRaises(je.JuejinApiError):
            _juejin([bad])
        out, _ = _juejin([bad], on_error="report")
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["error"].startswith("juejin_api_error:"))
        self.assertEqual(out[0]["tool"], "chat-scraper")
        self.assertEqual(out[0]["platform"], "juejin")
        out, _ = _juejin([bad], on_error="empty")
        self.assertEqual(out, [])

    def test_non_json_response_raises_with_slug(self):
        results, _ = _juejin([ValueError("no json")], on_error="report")
        self.assertTrue(results[0]["error"].startswith("juejin_api_error:"))

    def test_paging_cursor_chain(self):
        p1 = {"err_no": 0, "data": [_article(str(i)) for i in range(20)],
              "cursor": "CUR_2", "has_more": True}
        p2 = {"err_no": 0, "data": [_article(str(20 + i)) for i in range(10)],
              "cursor": "CUR_3", "has_more": False}
        out, calls = _juejin([p1, p2], num=25)
        self.assertEqual(len(out), 25)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1]["cursor"], "CUR_2")   # 沿服务端游标续翻

    def test_paging_stops_when_has_more_false(self):
        p1 = {"err_no": 0, "data": [_article(str(i)) for i in range(20)],
              "cursor": "x", "has_more": False}
        out, calls = _juejin([p1], num=100)
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(out), 20)   # 护栏耗尽≠异常，如实返回已收集

    def test_max_pages_guard(self):
        # 每页 id 不同（去重不干扰护栏计数）：护栏耗尽即停，安静返回 100 条
        pages = [{"err_no": 0,
                  "data": [_article(str(p * 20 + i)) for i in range(20)],
                  "cursor": f"next{p}", "has_more": True} for p in range(5)]
        out, calls = _juejin(pages, num=999)
        self.assertEqual(len(calls), je.MAX_PAGES)
        self.assertEqual(len(out), je.MAX_PAGES * je.PAGE_LIMIT)

    def test_cross_page_dedup(self):
        dup = _article("7")
        p1 = {"err_no": 0, "data": [dup], "cursor": "c", "has_more": True}
        p2 = {"err_no": 0, "data": [dup, _article("8")],
              "cursor": "", "has_more": False}
        out, _ = _juejin([p1, p2], num=10)
        ids = [r["url"].rsplit("/", 1)[-1] for r in out]
        self.assertEqual(ids, ["7", "8"])

    def test_since_client_filter(self):
        import time as _t
        fresh = str(int(_t.time()) - 3600)          # 1h 前
        stale = str(int(_t.time()) - 86400 * 3)     # 3 天前
        out, _ = _juejin([{"err_no": 0, "data": [
            _article("1", ctime=fresh), _article("2", ctime=stale)],
            "has_more": False}], since="24h")
        self.assertEqual([r["url"].rsplit("/", 1)[-1] for r in out], ["1"])

    def test_num_zero_no_request(self):
        out, calls = _juejin([{"err_no": 0, "data": [], "has_more": False}],
                             num=0)
        self.assertEqual(out, [])
        self.assertEqual(len(calls), 0)

    def test_throttle_env_default(self):
        # 引擎节流默认 2s（对齐 bilibili 模式）；env 可调、非法回退默认
        with mock.patch.dict(os.environ, {je.ENV_MIN_INTERVAL: "abc"}):
            self.assertEqual(je._min_interval(), je.DEFAULT_MIN_INTERVAL)
        with mock.patch.dict(os.environ, {je.ENV_MIN_INTERVAL: "0.5"}):
            self.assertEqual(je._min_interval(), 0.5)


class TestJuejinFacadeRouting(unittest.TestCase):
    def test_juejin_routes_to_dedicated_engine_not_baidu(self):
        with mock.patch.object(facade.juejin_engine, "search",
                               return_value=[{"u": 1}]) as je_search, \
                mock.patch.object(facade.baidu_engine, "search",
                                  side_effect=AssertionError("baidu 不该接手")), \
                mock.patch.object(facade.sogou_engine, "search",
                                  side_effect=AssertionError("sogou 不该接手")):
            out = facade.search("q", platforms=["juejin"])
        je_search.assert_called_once()
        self.assertEqual(out, [{"u": 1}])

    def test_list_platforms_declares_official_api(self):
        plats = facade.list_platforms()
        self.assertIn("official search API", plats["juejin"])
        self.assertNotIn("site:", plats["juejin"])   # 不再是百度 site: 路由

    def test_juejin_error_propagates_as_error_record(self):
        with mock.patch.object(facade.juejin_engine, "search",
                               side_effect=je.JuejinApiError("err_no=1")):
            out = facade.search("q", platforms=["juejin"])
        self.assertEqual(len(out), 1)
        self.assertIn("juejin_api_error", out[0]["error"])
        self.assertEqual(out[0]["platform"], "juejin")


# ---------------------------------------------------------------------------
# 2. watchdog（健康判定 / 恢复编排 / 退出码契约 / .env 语义）
# ---------------------------------------------------------------------------

class _HealthServer:
    """本地假 helper：线程内 HTTP 服务器，可指定状态码（默认 200）。"""

    def __init__(self, status=200):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        srv = HTTPServer(("127.0.0.1", 0), type(
            "H", (BaseHTTPRequestHandler,),
            {"do_GET": lambda self: (
                self.send_response(status), self.end_headers(),
                self.wfile.write(b"{}")),
             "log_message": lambda self, *a: None}))
        self.port = srv.server_address[1]
        self._srv = srv
        import threading
        self._t = threading.Thread(target=srv.serve_forever, daemon=True)
        self._t.start()

    def stop(self):
        self._srv.shutdown()
        self._srv.server_close()


class TestWatchdog(unittest.TestCase):
    def test_health_up_is_true(self):
        srv = _HealthServer(200)
        try:
            self.assertTrue(wd.check_health(srv.port, timeout=3))
        finally:
            srv.stop()

    def test_health_5xx_still_counts_alive(self):
        # 任何 HTTP 应答 = 进程在（503 是 chrome_ready 语义态，不是看门狗的活）
        srv = _HealthServer(503)
        try:
            self.assertTrue(wd.check_health(srv.port, timeout=3))
        finally:
            srv.stop()

    def test_health_down_on_closed_port(self):
        self.assertFalse(wd.check_health(1, timeout=1))   # 端口 1 必拒绝

    def test_exit0_healthy_no_action(self):
        with mock.patch.object(wd, "_log_decision") as lg:
            code = wd.run(health_fn=lambda p: True, spawn_fn=mock.MagicMock())
        self.assertEqual(code, 0)
        self.assertIn("healthy", lg.call_args[0][0])

    def test_exit1_recovery_within_grace(self):
        health = mock.MagicMock(side_effect=[False, True])
        spawn = mock.MagicMock(return_value=4242)
        with mock.patch.object(wd, "_log_decision") as lg:
            code = wd.run(health_fn=health, spawn_fn=spawn,
                          grace=1.0, poll=0.01)
        self.assertEqual(code, 1)
        spawn.assert_called_once()
        msgs = " | ".join(str(c.args[0]) for c in lg.call_args_list)
        self.assertIn("restarting", msgs)
        self.assertIn("pid=4242", msgs)
        self.assertIn("restart OK", msgs)

    def test_exit2_grace_exhausted(self):
        with mock.patch.object(wd, "_log_decision") as lg:
            code = wd.run(health_fn=lambda p: False,
                          spawn_fn=lambda: 7, grace=0.05, poll=0.01)
        self.assertEqual(code, 2)
        self.assertIn("UNCONFIRMED", lg.call_args[0][0])

    def test_exit2_spawn_failure(self):
        def boom():
            raise OSError("no exec")
        with mock.patch.object(wd, "_log_decision"):
            code = wd.run(health_fn=lambda p: False, spawn_fn=boom)
        self.assertEqual(code, 2)

    def test_exit3_check_only_never_spawns(self):
        spawn = mock.MagicMock()
        with mock.patch.object(wd, "_log_decision"):
            code = wd.run(check_only=True, health_fn=lambda p: False,
                          spawn_fn=spawn)
        self.assertEqual(code, 3)
        spawn.assert_not_called()

    def test_env_defaults_setdefault_semantics(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            envf = pathlib.Path(td) / ".env"
            envf.write_text(
                "# comment\nWD_TEST_A=from-file\n"
                'WD_TEST_B="quoted"\nWD_TEST_C=from-file\n'
                "broken line without equals\n\n",
                encoding="utf-8")
            with mock.patch.dict(os.environ,
                                 {"WD_TEST_C": "user-exported"},
                                 clear=False):
                applied = wd.load_env_defaults(envf)
                self.assertIn("WD_TEST_A", applied)
                self.assertEqual(os.environ["WD_TEST_A"], "from-file")
                self.assertEqual(os.environ["WD_TEST_B"], "quoted")
                # 用户已导出的值永远赢（:= 语义）
                self.assertEqual(os.environ["WD_TEST_C"], "user-exported")
                self.assertNotIn("WD_TEST_C", applied)

    def test_spawn_shape_detached_and_path_autonomous(self):
        opened = []
        with mock.patch.object(wd.subprocess, "Popen") as popen, \
                mock.patch("builtins.open",
                           side_effect=lambda f, m, **k:
                           opened.append(f) or io.BytesIO()):
            wd._spawn_helper()
        argv = popen.call_args[0][0]
        self.assertEqual(argv, [sys.executable, str(wd.HELPER)])
        self.assertEqual(popen.call_args[1]["cwd"], str(wd.HERE))
        if sys.platform == "win32":
            flags = popen.call_args[1]["creationflags"]
            self.assertTrue(flags & 0x00000008)   # DETACHED_PROCESS
            self.assertTrue(flags & 0x00000200)   # CREATE_NEW_PROCESS_GROUP
        else:
            self.assertTrue(popen.call_args[1]["start_new_session"])


# ---------------------------------------------------------------------------
# 3. watchdog_task（注册器参数构造 / GBK 解码 / 幂等 / 降级语义）
# ---------------------------------------------------------------------------

class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestWatchdogTask(unittest.TestCase):
    def _runner(self, results):
        """按调用顺序吐预置结果的 runner 替身。"""
        calls = []
        results = list(results)

        def run(argv, **kw):
            calls.append(argv)
            return results[min(len(calls) - 1, len(results) - 1)]
        return run, calls

    def test_register_boot_first_watchdog_second(self):
        run, calls = self._runner([_Proc(0), _Proc(0)])
        with mock.patch.object(wt, "sys") as msys:
            msys.platform = "win32"
            msys.executable = "py.exe"
            code = wt.register(interval=15, runner=run)
        self.assertEqual(code, 0)
        # 承重任务（MINUTE 巡检）先注册
        self.assertIn("/TN", calls[0])
        self.assertEqual(calls[0][calls[0].index("/TN") + 1],
                         wt.TASK_WATCHDOG)
        self.assertEqual(calls[0][calls[0].index("/SC") + 1], "MINUTE")
        self.assertEqual(calls[0][calls[0].index("/MO") + 1], "15")
        self.assertEqual(calls[0][calls[0].index("/F") + 0], "/F")
        # 开机增强任务随后（ONLOGON）
        self.assertEqual(calls[1][calls[1].index("/TN") + 1], wt.TASK_BOOT)
        self.assertEqual(calls[1][calls[1].index("/SC") + 1], "ONLOGON")

    def test_register_tr_value_quoted_paths(self):
        tr = wt._tr_value("C:\\Program Files\\py\\pythonw.exe")
        # 带空格路径必须整串嵌入引号（schtasks /TR 语义）
        self.assertTrue(tr.startswith('"'))
        self.assertIn('" "', tr)
        self.assertTrue(tr.endswith('"'))

    def test_register_tr_too_long_raises_not_truncates(self):
        with mock.patch.object(wt, "WATCHDOG_PY",
                               pathlib.Path("C:/" + "x" * 300 + ".py")):
            with self.assertRaises(ValueError):
                wt._tr_value("py.exe")

    def test_register_load_bearing_failure_is_exit1(self):
        run, calls = self._runner([_Proc(1, stderr="denied")])
        with mock.patch.object(wt, "sys") as msys:
            msys.platform = "win32"
            msys.executable = "py.exe"
            code = wt.register(runner=run)
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 1)   # 承重失败即止，不烧开机任务

    def test_register_boot_denied_degrades_to_exit0(self):
        # 实测（2026-09-17）：普通权限令牌 ONLOGON 注册被拒（拒绝访问）——
        # 降级不失败，承重任务在场即 0
        run, calls = self._runner([_Proc(0), _Proc(1, stderr="拒绝访问")])
        with mock.patch.object(wt, "sys") as msys:
            msys.platform = "win32"
            msys.executable = "py.exe"
            code = wt.register(runner=run)
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 2)

    def test_unregister_idempotent_chinese_wording(self):
        # 中文 schtasks 实测措辞「系统找不到指定的文件」= 已是目标状态
        run, _ = self._runner([
            _Proc(1, stderr="错误: 系统找不到指定的文件。"),
            _Proc(1, stderr="错误: 系统找不到指定的文件。")])
        with mock.patch.object(wt, "sys") as msys:
            msys.platform = "win32"
            msys.executable = "py.exe"
            self.assertEqual(wt.unregister(runner=run), 0)

    def test_unregister_real_failure_is_exit1(self):
        run, _ = self._runner([_Proc(1, stderr="boom"), _Proc(1, stderr="b")])
        with mock.patch.object(wt, "sys") as msys:
            msys.platform = "win32"
            msys.executable = "py.exe"
            self.assertEqual(wt.unregister(runner=run), 1)

    def test_status_core_task_decides_exit_code(self):
        run, _ = self._runner([_Proc(0), _Proc(1, stderr="not found")])
        with mock.patch.object(wt, "sys") as msys:
            msys.platform = "win32"
            msys.executable = "py.exe"
            self.assertEqual(wt.status(runner=run), 0)    # 承重在场
        run, _ = self._runner([_Proc(1, stderr="not found"),
                               _Proc(0)])
        with mock.patch.object(wt, "sys") as msys:
            msys.platform = "win32"
            msys.executable = "py.exe"
            self.assertEqual(wt.status(runner=run), 1)    # 承重缺席

    def test_non_windows_honest_error(self):
        with mock.patch.object(wt.sys, "platform", "linux"):
            self.assertEqual(wt.register(runner=self._runner([])[0]), 1)
            self.assertEqual(wt.unregister(runner=self._runner([])[0]), 1)

    def test_decode_gbk_fallback_chain(self):
        self.assertEqual(wt._decode(None), "")
        self.assertEqual(wt._decode("already str"), "already str")
        self.assertEqual(wt._decode("错误".encode("utf-8")), "错误")
        self.assertEqual(wt._decode("错误".encode("gbk")), "错误")   # 实测主路径
        self.assertEqual(wt._decode(b"\xff\xfe"), "\ufffd\ufffd")   # 双败兜底


# ---------------------------------------------------------------------------
# 4. C1 拆分钉（read_page 零知乎依赖 + 兼容层同体 + mcp 委托不变）
# ---------------------------------------------------------------------------

class TestReadPageSplit(unittest.TestCase):
    def test_read_page_has_zero_zhihu_imports(self):
        tree = ast.parse((REPO / "tools" / "chat-scraper" / "read_page.py")
                         .read_text(encoding="utf-8"))
        mods = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                mods.append(node.module or "")
        self.assertFalse([m for m in mods if "zhihu" in m.lower()],
                         f"read_page 出现知乎依赖: {mods}")

    def test_zhihu_reexport_identity(self):
        # 兼容契约：zc.<name> 与 read_page.<name> 是同一对象（引用路径不变）
        self.assertIs(zc.ReadError, rp.ReadError)
        self.assertIs(zc._HttpSoftFail, rp._HttpSoftFail)
        self.assertIs(zc._check_http_url, rp._check_http_url)
        self.assertIs(zc._content_field, rp._content_field)
        self.assertIs(zc._GENERIC_SELECTORS, rp._GENERIC_SELECTORS)
        self.assertIs(zc._raise_if_error_page, rp._raise_if_error_page)
        self.assertIs(zc._generic_read_http, rp._generic_read_http)
        self.assertIs(zc.read_generic, rp.read_generic)
        self.assertEqual(zc.CONTENT_LIMIT, rp.CONTENT_LIMIT)

    def test_zhihu_api_line_stays_home(self):
        # API 线本体不许被搬走（fetch_*/签名/自愈是 zhihu_content 的魂）
        for name in ("fetch_question", "fetch_answers", "fetch_article",
                     "fetch_comments", "read", "read_via_browser",
                     "_api_get", "_try_self_heal", "ZhihuAuthExpired"):
            self.assertTrue(hasattr(zc, name), name)
        # 且 read() 外域路径确以 read_generic 收尾（源码钉）
        src = (REPO / "tools" / "chat-scraper" / "zhihu_content.py"
               ).read_text(encoding="utf-8")
        self.assertIn("return read_generic(u)", src)
        self.assertNotIn("def _generic_read_http", src)   # 不许残留双份

    def test_mcp_read_page_still_delegates_zhihu_read(self):
        if mcp_server is not None:
            self.assertTrue(hasattr(mcp_server, "read_page"))
        src = (REPO / "tools" / "mcp_server.py").read_text(encoding="utf-8")
        self.assertIn("_zhihu.read", src)   # 接入层委托路径不变

    def test_generic_read_orchestration_soft_fail_fallback(self):
        # 拆分后编排语义不变：HTTP 线软失败 → 浏览器线
        with mock.patch.object(rp, "_generic_read_http",
                               side_effect=rp._HttpSoftFail("403")), \
                mock.patch.object(rp, "_generic_read_browser",
                                  return_value={"engine": "browser"}) as gb:
            out = rp.read_generic("https://x.com/a")
        gb.assert_called_once_with("https://x.com/a")
        self.assertEqual(out["engine"], "browser")


# ---------------------------------------------------------------------------
# 5. 版本锁 3.28.0（双 __version__ 精确锁，自 test_v3270 接管）+ 文档
# ---------------------------------------------------------------------------

class TestVersionSyncV328(unittest.TestCase):
    def test_versions_3280(self):
        # v3.29 起精确锁移交 test_v3290，此处降常青下限（v3.26→v3.27、
        # v3.27→v3.28 先例）：双 __version__ 同步本身不许破
        if mcp_server is None:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            ver = re.search(r'__version__ = "([^"]+)"', src).group(1)
        else:
            ver = mcp_server.__version__
        self.assertGreaterEqual(
            [int(x) for x in ver.split(".")], [3, 28, 0])
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        self.assertIn(f'__version__ = "{ver}"', init_src)
        self.assertIn(f"chat-scraper v{ver}", init_src)

    def test_changelog_and_readme_3280(self):
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.28.0] - 2026-09-17", changelog)
        self.assertIn("juejin", changelog)
        self.assertIn("看门狗", changelog)
        self.assertIn("read_page", changelog)
        # v3.29 起精确徽章/状态行锁移交 test_v3290，此处降常青：
        # 徽章/状态行与 __version__ 一致（防止换版时徽章漂移回退）
        if mcp_server is None:
            src2 = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            ver = re.search(r'__version__ = "([^"]+)"', src2).group(1)
        else:
            ver = mcp_server.__version__
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn(f"release-v{ver}", readme)
        self.assertIn(f"v{ver}（", readme)   # 状态行「vX.Y.Z（日期）」头部在场

    def test_watchdog_contract_doc_pinned(self):
        # 退出码契约写死在 help/docstring（测试钉死文本存在）
        self.assertIn("0 = 健康", wd.__doc__)
        self.assertIn("3 = --check-only", wd.__doc__)
        self.assertEqual(wd.__version__, "1.0.0")


if __name__ == "__main__":
    unittest.main()
