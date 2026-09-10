"""离线单元测试：不发外部请求，任何机器/CI 都能跑。

覆盖三类回归：
1. v3.0.0 修复过的 bug（时区漂移、null points 崩溃、since 双默认…）
2. v2 空壳事故的防回归（NUL 文件检测）
3. toolbox 组合的前提（同进程多工具 import 不撞名）

运行：python -m unittest discover -s tests -p "test_*.py" -v
"""
import pathlib
import os
import subprocess
import sys
import time
import unittest
import requests
from contextlib import redirect_stderr
from unittest import mock
import json
from io import StringIO

REPO = pathlib.Path(__file__).resolve().parent.parent
for d in ("hackernews", "github", "searxng", "chat-scraper", "google-bridge"):
    sys.path.insert(0, str(REPO / "tools" / d))


class TestNulRegression(unittest.TestCase):
    """v2 的 chat-scraper 曾以"保留大小、内容全 NUL"的空壳入库且 CI 假绿。"""

    def test_no_nul_only_py_files(self):
        bad = []
        for p in sorted((REPO / "tools").rglob("*.py")):
            data = p.read_bytes()
            if data and data.replace(b"\x00", b"") == b"":
                bad.append(str(p))
        self.assertEqual(bad, [], f"NUL 空壳文件（v2 事故防回归）: {bad}")

    def test_no_empty_py_files(self):
        empty = [str(p) for p in sorted((REPO / "tools").rglob("*.py"))
                 if p.read_bytes() == b""]
        self.assertEqual(empty, [])


class TestImportCollisionRegression(unittest.TestCase):
    """v2 三客户端同名 client.py，同进程 import 第二个命中 sys.modules
    缓存被静默劫持（审计实测）。v3 模块名唯一，此测试锁死该前提。"""

    def test_unique_module_names_coexist(self):
        import hackernews_client
        import searxng_client

        self.assertIsNot(hackernews_client.search, searxng_client.search)
        # 本进程从未 import 过任何 client.py shim——模块名唯一化的前提
        self.assertNotIn("client", sys.modules)

    def test_legacy_shim_warns_and_forwards(self):
        """旧用法 from client import search 仍工作，但必须打 DeprecationWarning。"""
        code = (
            "import warnings, sys\n"
            "sys.path.insert(0, r'{dir}')\n"
            "warnings.simplefilter('error', DeprecationWarning)\n"
            "try:\n"
            "    from client import search\n"
            "except DeprecationWarning:\n"
            "    print('WARNED'); sys.exit(0)\n"
            "print('NO_WARN'); sys.exit(1)\n"
        ).format(dir=REPO / "tools" / "hackernews")
        r = subprocess.run([sys.executable, "-c", code],
                           capture_output=True, text=True, timeout=30)
        self.assertIn("WARNED", r.stdout,
                      f"shim 未打 DeprecationWarning: {r.stdout} {r.stderr}")


class TestHackernews(unittest.TestCase):
    def test_since_timestamp_is_utc_now_based(self):
        # v3 修复前：naive utcnow 按本地时区解释，UTC+8 机器漂移 -28800s
        import hackernews_client as hn
        got = hn._since_to_timestamp("7d")
        expect = time.time() - 7 * 86400
        self.assertLess(abs(got - expect), 120,
                        f"7d 截止戳偏差 {got - expect:.0f}s（时区漂移回归？）")

    def test_null_points_coerced_to_int(self):
        # v3 修复前：comment 模式 points 为 JSON null，`hit.get("points", 0)`
        # 拿到 None，调用方 `points >= 50` 直接 TypeError（审计实测）
        import hackernews_client as hn
        row = hn._row_from_hit({"title": None, "points": None,
                                "num_comments": None, "author": None},
                               vendor="t", role="verify", since="7d")
        self.assertEqual(row["points"], 0)
        self.assertIsInstance(row["points"], int)
        self.assertEqual(row["comments"], 0)
        self.assertEqual(row["title"], "")

    def test_search_end_to_end_null_points(self):
        # 端到端锁死：mock 掉 urlopen，返回 points=null 的真实 hit 形状
        import io
        import json
        from unittest import mock
        import urllib.request  # noqa: F401  (hackernews_client 引用其命名空间)
        import hackernews_client as hn
        payload = json.dumps({"hits": [{"objectID": "1", "title": "t",
                                        "points": None, "num_comments": None}]}).encode()
        fake_resp = io.BytesIO(payload)
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = lambda s, *a: False
        with mock.patch("urllib.request.urlopen", return_value=fake_resp):
            results = hn.search("q", on_error="raise")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["points"], 0)


class TestGithub(unittest.TestCase):
    def test_error_protocol_modes(self):
        import github_client as gh
        err = RuntimeError("boom")
        rep = gh._handle_error(err, "report", "releases", "q")
        self.assertIn("error", rep[0])
        self.assertEqual(rep[0]["action"], "releases")
        self.assertEqual(gh._handle_error(err, "empty", "releases", "q"), [])
        with self.assertRaises(RuntimeError):
            gh._handle_error(err, "raise", "releases", "q")


class TestSearxng(unittest.TestCase):
    def test_unknown_since_warns_not_silent(self):
        import searxng_client as sx
        err = StringIO()
        with redirect_stderr(err):
            self.assertEqual(sx._since_to_time_range("3w"), "")
        self.assertIn("warning", err.getvalue().lower())

    def test_known_since_windows(self):
        import searxng_client as sx
        self.assertNotEqual(sx._since_to_time_range("7d"), "")
        self.assertEqual(sx._since_to_time_range(""), "")


class TestChatScraper(unittest.TestCase):
    def test_baidu_placeholder_detection(self):
        import baidu_engine as bd
        self.assertIsNotNone(bd._looks_soft_blocked("<html>timeout hide</html>"))
        self.assertIsNotNone(bd._looks_soft_blocked("xxx wappass yyy"))
        self.assertIsNone(bd._looks_soft_blocked(
            "<html>" + "x" * (bd.PLACEHOLDER_MAX_LEN + 10) + "timeout</html>"))

    def test_baidu_parse_uses_mu_direct_link(self):
        # 百度 mu 属性即真实直链（侦察实证），跳转解析都省了——锁死该解析契约
        import baidu_engine as bd
        html = (
            '<div class="result" mu="https://zhuanlan.zhihu.com/p/1">'
            '<h3><a href="#">标题A</a></h3>'
            '<div class="summary-text_1">摘要A</div></div>'
            '<div class="result-op" mu="https://www.zhihu.com/question/2">'
            '<h3>标题B</h3></div>'
            '<div class="result" mu="https://zhuanlan.zhihu.com/p/1">'
            '<h3>重复mu应去重</h3></div>'
            '<div class="result"><h3>无mu应跳过</h3></div>')
        out = bd._parse_results(html)
        self.assertEqual([r["url"] for r in out],
                         ["https://zhuanlan.zhihu.com/p/1",
                          "https://www.zhihu.com/question/2"])
        self.assertEqual(out[0]["title"], "标题A")
        self.assertEqual(out[0]["snippet"], "摘要A")

    def test_bilibili_clean_title(self):
        import bilibili_engine as bl
        self.assertEqual(bl._clean_title('<em class="keyword">python</em> 教程'),
                         "python 教程")
        self.assertEqual(bl._clean_title("A &amp; B"), "A & B")
        self.assertEqual(bl._clean_title(None), "")

    def test_bilibili_mixin_key_length(self):
        import bilibili_engine as bl
        # 真实输入 img_key+sub_key = 64 hex；测试串取 70 字符覆盖重排表最大索引
        key = bl._mixin_key("0123456789" * 7)
        self.assertEqual(len(key), 32)

    def test_platform_registry(self):
        import search as cs
        plats = cs.list_platforms()
        self.assertIn("zhihu", plats)
        self.assertIn("bilibili", plats)

    def test_unknown_platform_reports_not_crashes(self):
        import search as cs
        out = cs.search("q", platforms=["nonexistent_platform"],
                        on_error="report")
        self.assertEqual(len(out), 1)
        self.assertIn("unknown platform", out[0]["error"])

    def test_error_protocol_modes(self):
        import search as cs
        out = cs.search("q", platforms=["nonexistent_platform"],
                        on_error="empty")
        self.assertEqual(out, [])
        with self.assertRaises(ValueError):
            cs.search("q", platforms=["nonexistent_platform"],
                      on_error="raise")


class TestZhihuEngine(unittest.TestCase):
    """v3.1 知乎专用引擎：降级链 SearXNG→搜狗→百度。"""

    SOGOU_HTML = (
        '<div class="vrwrap"><h3 class="vr-title"><a target="_blank" '
        'href="/link?url=abc123">从零开始学<em><!--red_beg-->Python<!--red_end-->'
        '</em> - 知乎</a></h3><div class="text-layout"><p>入门教程摘要。</p></div></div>'
        '<div class="vrwrap"><h3 class="vr-title"><a href="/link?url=dup">重复</a></h3></div>'
        '<div class="vrwrap"><h3 class="vr-title"><a href="/link?url=dup">重复</a></h3></div>'
        '<div class="rb"><h3><a href="https://zhuanlan.zhihu.com/p/9">直链文章</a></h3>'
        '<div class="space-txt">直链摘要</div></div>')

    def test_sogou_parse(self):
        import zhihu_engine as zg
        rows = zg._sogou_parse(self.SOGOU_HTML)
        self.assertEqual(len(rows), 3)  # 重复 href 去重掉一条
        self.assertEqual(rows[0]["title"], "从零开始学Python - 知乎")
        self.assertTrue(rows[0]["link_href"].startswith("https://www.sogou.com/link"))
        self.assertEqual(rows[0]["snippet"], "入门教程摘要。")
        self.assertTrue(rows[2]["link_href"].startswith("https://zhuanlan."))

    def test_resolve_link_regex(self):
        import zhihu_engine as zg
        page = '<script>window.location.replace("https://zhuanlan.zhihu.com/p/1")</script>'
        self.assertEqual(zg._LOCATION_RE.search(page).group(1),
                         "https://zhuanlan.zhihu.com/p/1")

    def test_searxng_filters_to_zhihu(self):
        # 后端偶尔漏进无关域，引擎层二次过滤锁死
        import zhihu_engine as zg
        import types
        fake_rows = {"results": [
            {"title": "知乎问题", "url": "https://www.zhihu.com/question/1",
             "content": "c1", "engine": "brave"},
            {"title": "CSDN 文章", "url": "https://blog.csdn.net/x", "engine": "brave"},
        ]}
        class FakeResp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return fake_rows
        from unittest import mock
        with mock.patch.object(zg.requests, "get", return_value=FakeResp()):
            with mock.patch.object(zg, "_wait_turn"):
                rows = zg._searxng_search("q", 10, None, "t", "verify")
        self.assertEqual(len(rows), 1)
        self.assertIn("question/1", rows[0]["url"])
        self.assertEqual(rows[0]["engine"], "searxng:brave")

    def test_chain_degrades_on_engine_error(self):
        import zhihu_engine as zg
        from unittest import mock
        good = [{"title": "t", "url": "https://www.zhihu.com/q/1",
                 "snippet": "", "platform": "zhihu", "engine": "sogou",
                 "vendor": "t", "role": "verify", "since": "all"}]
        with mock.patch.object(zg, "_searxng_search",
                               side_effect=zg.SearxngUnavailable("down")), \
             mock.patch.object(zg, "_sogou_search", return_value=good), \
             mock.patch.object(zg, "_baidu_fallback") as baidu:
            rows = zg.search("q", on_error="raise")
        self.assertEqual(rows[0]["engine"], "sogou")
        baidu.assert_not_called()   # 前一环成功就不再降级

    def test_chain_all_fail_reports_with_chain_log(self):
        import zhihu_engine as zg
        from unittest import mock
        with mock.patch.object(zg, "_searxng_search",
                               side_effect=zg.SearxngUnavailable("down")), \
             mock.patch.object(zg, "_sogou_search",
                               side_effect=zg.SogouBlocked("captcha")), \
             mock.patch.object(zg, "_baidu_fallback",
                               side_effect=ConnectionError("RST")):
            rows = zg.search("q", on_error="report")
        self.assertEqual(len(rows), 1)
        self.assertIn("ConnectionError", rows[0]["error"])
        self.assertEqual(rows[0]["chain"], "searxng(失败:SearxngUnavailable)"
                                          "→sogou(失败:SogouBlocked)"
                                          "→baidu(失败:ConnectionError)")
        with mock.patch.object(zg, "_searxng_search",
                               side_effect=zg.SearxngUnavailable("down")), \
             mock.patch.object(zg, "_sogou_search", return_value=[]), \
             mock.patch.object(zg, "_baidu_fallback", return_value=[]):
            # searxng 挂过一环：报错保留链条日志（诊断信息优先），
            # 不允许伪装成真空 []
            rows = zg.search("q", on_error="report")
            self.assertEqual(len(rows), 1)
            self.assertIn("chain", rows[0])
            # 三环全部成功但都 0 结果 —— 这才是真真空
            with mock.patch.object(zg, "_searxng_search", return_value=[]), \
                 mock.patch.object(zg, "_sogou_search", return_value=[]), \
                 mock.patch.object(zg, "_baidu_fallback", return_value=[]):
                self.assertEqual(zg.search("q", on_error="report"), [])
        # raise 路径：chain 挂在异常对象上，门面 _error_record 必须透传
        # （审查发现：chain 曾在标准调用路径丢失）
        with mock.patch.object(zg, "_searxng_search",
                               side_effect=zg.SearxngUnavailable("down")), \
             mock.patch.object(zg, "_sogou_search", return_value=[]), \
             mock.patch.object(zg, "_baidu_fallback", return_value=[]):
            with self.assertRaises(zg.SearxngUnavailable) as cm:
                zg.search("q", on_error="raise")
            self.assertIn("sogou(0条)", cm.exception.chain)
            import search as cs
            rec = cs._error_record(cm.exception, "q", "zhihu")
            self.assertIn("chain", rec)

    def test_site_param_reaches_engines(self):
        # zhuanlan 的 site 限定必须贯穿三环（v3.1.0 曾是死参数，审查修正）
        import zhihu_engine as zg
        from unittest import mock
        captured = {}

        def fake_searxng(q, num, since, vendor, role, site):
            captured["searxng"] = site
            raise zg.SearxngUnavailable("skip")

        with mock.patch.object(zg, "_searxng_search", side_effect=fake_searxng), \
             mock.patch.object(zg, "_sogou_search",
                               side_effect=lambda q, num, vendor, role, since, site:
                               captured.__setitem__("sogou", site) or []), \
             mock.patch.object(zg, "_baidu_fallback",
                               side_effect=lambda q, num, since, vendor, role, site:
                               captured.__setitem__("baidu", site) or []):
            zg.search("q", site="zhuanlan.zhihu.com", on_error="report")
        self.assertEqual(captured, {"searxng": "zhuanlan.zhihu.com",
                                    "sogou": "zhuanlan.zhihu.com",
                                    "baidu": "zhuanlan.zhihu.com"})

    def test_routing_intercepts_zhihu(self):
        import search as cs
        from unittest import mock
        with mock.patch.object(cs.zhihu_engine, "search",
                               return_value=[{"title": "x"}]) as zf:
            cs.search("q", platforms=["zhihu"], on_error="raise")
            self.assertEqual(
                zf.call_args.kwargs.get("site"), "zhihu.com")
            cs.search("q", platforms=["zhuanlan"], on_error="raise")
            self.assertEqual(
                zf.call_args.kwargs.get("site"), "zhuanlan.zhihu.com")


class TestBaiduResilience(unittest.TestCase):
    """v3.2 头指纹 + 移动端桶 + 搜狗第三环（审查/侦察驱动的防回归）。"""

    def test_accept_header_fingerprint(self):
        # 头指纹是软风控的直接开关：三件套（缺完整 Accept）是实测被封组合
        import baidu_engine as bd
        from unittest import mock
        with mock.patch.object(requests.Session, "get", return_value=mock.Mock()):
            s = bd._get_session()
        self.assertNotEqual(s.headers.get("Accept", "").strip(), "")
        self.assertNotEqual(s.headers.get("Accept"), "*/*")  # requests 默认值=机器人指纹
        self.assertIn("text/html", s.headers["Accept"])

    def test_mobile_parse_uses_datalog_mu(self):
        # 移动端真 URL 在 data-log 属性 JSON 里（无 mu DOM 属性）；
        # *.baidu.com 自家内容卡是噪音必须丢弃
        import baidu_engine as bd
        html = (
            '<div class="c-result" data-log=\'{"fm":"alop","mu":'
            '"https://zhuanlan.zhihu.com/p/18589357376"}\'><h3>知乎专栏文章</h3>'
            '<div class="c-abstract">摘要A</div></div>'
            '<div class="c-result" data-log=\'{"mu":"https://mbd.baidu.com/x"}\'>'
            '<h3>百度自家卡应丢弃</h3></div>'
            '<div class="c-result" data-log=\'not-json\'><h3>坏json跳过</h3></div>')
        rows = bd._parse_mobile_results(html)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["url"], "https://zhuanlan.zhihu.com/p/18589357376")
        self.assertEqual(rows[0]["title"], "知乎专栏文章")


    def test_desktop_network_error_still_tries_mobile(self):
        # 审查 B1：桌面 RST（软风控形态之一）不得跳过移动桶
        import baidu_engine as bd
        from unittest import mock
        mobile_rows = [{"title": "m", "url": "https://zhuanlan.zhihu.com/p/1",
                        "snippet": ""}]
        calls = {"n": 0}

        def flaky_desktop(self, url, **kw):
            calls["n"] += 1
            raise requests.exceptions.ConnectionError(
                "RemoteDisconnected('RST')")

        with mock.patch.object(bd, "_get_session",
                               side_effect=lambda mobile=False: requests.Session()), \
             mock.patch.object(bd, "_min_interval", return_value=0.0), \
             mock.patch.object(requests.Session, "get", flaky_desktop), \
             mock.patch.object(bd, "_mobile_search_impl",
                               return_value=mobile_rows) as mobile_mock, \
             mock.patch.object(bd, "_reset_sessions"):
            rows, engine = bd._search_impl("q", 5, None, None, "test")
        self.assertEqual(engine, "baidu-mobile")
        self.assertEqual(rows, mobile_rows)
        self.assertEqual(calls["n"], bd.MAX_SOFTBLOCK_RETRIES + 1)  # 桌面 3 次全 RST
        mobile_mock.assert_called_once()   # 移动桶必须被触达


class TestSogouEngine(unittest.TestCase):
    FIXTURE = (
        '<div class="vrwrap" data-url="https://blog.csdn.net/a/1">'
        '<h3><a href="/link?url=x">CSDN<em><!--red_beg-->Python<!--red_end--></em>教程</a></h3>'
        '<div class="text-layout">摘要一</div></div>'
        '<div class="vrwrap"><h3><a href="/link?url=y">无data-url回退href</a></h3></div>'
        '<div class="vrwrap" data-url="https://blog.csdn.net/a/1">'
        '<h3><a href="/link?url=z">重复应去重</a></h3></div>')

    def test_sogou_parse_data_url_direct_link(self):
        import sogou_engine as se
        rows = se._parse_results(self.FIXTURE)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["url"], "https://blog.csdn.net/a/1")
        self.assertEqual(rows[0]["title"], "CSDNPython教程")
        # 无 data-url 时回退 /link 绝对化，不解析不丢条目
        self.assertTrue(rows[1]["url"].startswith("https://www.sogou.com/link"))

    def test_blocked_raises_with_slug(self):
        import sogou_engine as se
        from unittest import mock
        self.assertEqual(se.SogouBlocked.slug, "sogou_blocked")
        # 软风控页（0 解析行 + 风控标记）→ SogouBlocked 而非静默 []
        blocked = ("<html><title>搜狗反爬拦截</title>antispider 页面"
                   "验证码</html>")
        fake = mock.Mock(status_code=200, url="https://www.sogou.com/web",
                         text=blocked)
        with mock.patch.object(requests.Session, "get", return_value=fake):
            out = se.search("q", on_error="report")
        self.assertIn("sogou_blocked", out[0]["error"])

    def test_antispider_in_results_not_blocked(self):
        # 审查 B2：antispider 出现在正常结果标题里，不得误杀（0 行才查全文）
        import sogou_engine as se
        from unittest import mock
        page = ('<div class="vrwrap" data-url="https://blog.csdn.net/a">'
                '<h3><a href="/link?url=x">网站反爬虫 antispider 实战</a></h3>'
                '<div class="text-layout">讲 antispider 策略的文章</div></div>'
                '<div class="vrwrap" data-url="https://blog.csdn.net/b">'
                '<h3><a href="/link?url=y">另一篇</a></h3></div>')
        fake = mock.Mock(status_code=200, url="https://www.sogou.com/web",
                         text=page + "antispider")
        with mock.patch.object(requests.Session, "get", return_value=fake):
            rows = se.search("antispider", on_error="raise")
        self.assertEqual(len(rows), 2)
        self.assertIn("antispider", rows[0]["title"])

    def test_facade_falls_back_to_sogou_on_baidu_failure(self):
        import search as cs
        from unittest import mock
        sogou_rows = [{"title": "t", "url": "https://blog.csdn.net/a",
                       "snippet": "", "platform": "csdn", "engine": "sogou"}]
        with mock.patch.object(cs.baidu_engine, "search",
                               side_effect=cs.baidu_engine.BaiduSoftBlocked("blocked")), \
             mock.patch.object(cs.sogou_engine, "search",
                               return_value=sogou_rows) as sf:
            rows = cs.search("q", platforms=["csdn"], on_error="raise")
            self.assertEqual(rows[0]["engine"], "sogou")
            # site 限定透传给搜狗环
            self.assertEqual(sf.call_args.kwargs.get("site"), "csdn.net")
        # 百度真空(0条)不触发降级——那是真空不是故障
        with mock.patch.object(cs.baidu_engine, "search", return_value=[]), \
             mock.patch.object(cs.sogou_engine, "search") as sf:
            self.assertEqual(cs.search("q", platforms=["csdn"],
                                       on_error="raise"), [])
            sf.assert_not_called()


class TestZhihuSignAndContent(unittest.TestCase):
    """v3.3 知乎官方 API 线：无头引导 cookie + 纯签名 HTTP。"""

    def test_sign_headers_shape_and_determinism(self):
        import zhihu_sign as zs
        url = "https://www.zhihu.com/api/v4/questions/19550227"
        h = zs.sign_headers(url, "FAKE|1|0|FAKE")
        self.assertEqual(h["x-zse-93"], "101_3_3.0")
        self.assertTrue(h["x-zse-96"].startswith("2.0_"))
        # 密文字符必须全部落在自定义字母表内（注意 "=" 是表内合法字符，
        # 不是 base64 填充——zse96.py 自检里那条 assert 是侥幸通过的坏断言）
        body = h["x-zse-96"][4:]
        self.assertTrue(body and set(body) <= set(zs.ALPHABET))
        self.assertEqual(h["x-zse-96"],
                         zs.sign_headers(url, "FAKE|1|0|FAKE")["x-zse-96"])
        # 不同 d_c0 必须产出不同签名
        self.assertNotEqual(h["x-zse-96"],
                            zs.sign_headers(url, "OTHER")["x-zse-96"])

    def test_sign_golden_vector(self):
        # 金标准向量（审查 #7）：ZK/ZB 重排表或块加密被改坏时在此爆。
        # 本实现整体已过知乎服务器验签（2026-09-09 真会话 HTTP 200）。
        import zhihu_sign as zs
        url = ("https://www.zhihu.com/api/v4/questions/19550227"
               "?include=detail,answer_count")
        golden = ("2.0_jAJf6aCxgOgRYhjgIp1Rrw=IisCu9=KAm/jlMIUjm5n1tpSz"
                  "igPqM+Cx+V4CbMkZ")
        self.assertEqual(zs.sign_headers(url, "GOLDEN|0|0|VECTOR")["x-zse-96"],
                         golden)

    def test_behavior_limit_distinct_from_auth(self):
        # 审查 #1：40362 行为限制 ≠ cookie 过期。cookie 明明是好的，
        # 误报 auth 会诱导用户白跑引导，还给被标记 IP 再压浏览器流量
        import zhihu_content as zc
        from unittest import mock
        cookie_json = json.dumps(
            {"cookies": {"d_c0": "fake", "__zse_ck": "fake"},
             "user_agent": "Firefox"})
        fake_resp = mock.Mock(status_code=403)
        fake_resp.json.return_value = {
            "error": {"code": 40362, "message": "暂时限制本次访问"}}
        with mock.patch.object(zc, "_cookie_path",
                               return_value="state/fake.json"), \
             mock.patch.object(zc.os.path, "exists", return_value=True), \
             mock.patch("builtins.open",
                        mock.mock_open(read_data=cookie_json)), \
             mock.patch.object(zc.requests, "get", return_value=fake_resp):
            with self.assertRaises(zc.ZhihuBehaviorLimited) as cm:
                zc.fetch_answers("19550227")
        self.assertIn("降频", str(cm.exception))

    def test_200_with_error_body_not_vacuum(self):
        # 审查 #2：HTTP 200 包 error body 不得伪装成真空 []
        import zhihu_content as zc
        from unittest import mock
        cookie_json = json.dumps(
            {"cookies": {"d_c0": "fake"}, "user_agent": "Firefox"})
        fake_resp = mock.Mock(status_code=200)
        fake_resp.json.return_value = {
            "error": {"code": 100, "message": "bad params"}}
        with mock.patch.object(zc, "_cookie_path",
                               return_value="state/fake.json"), \
             mock.patch.object(zc.os.path, "exists", return_value=True), \
             mock.patch("builtins.open",
                        mock.mock_open(read_data=cookie_json)), \
             mock.patch.object(zc.requests, "get", return_value=fake_resp):
            with self.assertRaises(zc.ZhihuApiError):
                zc.fetch_answers("19550227")

    def test_question_id_validated(self):
        # 审查 #5：非纯数字 id 拒绝，防 path 拼接打到别的端点
        import zhihu_content as zc
        with self.assertRaises(zc.ZhihuApiError):
            zc.fetch_question("19550227/answers")

    def test_browser_read_url_guard(self):
        # 审查补充：read_via_browser 的域护栏零成本离线测试
        # （校验在浏览器 import 之前执行，非法 URL 不起浏览器）
        import zhihu_content as zc
        for bad in ("https://zhihu.com.evil.com/x",
                    "https://www.zhihu.com.evil.com/x",
                    "https://zhihu.com@evil.com/x",
                    "javascript:alert(1)"):
            with self.assertRaises(zc.ZhihuApiError):
                zc._check_page_url(bad)

    def test_browser_read_accepts_zhuanlan(self):
        # 审查 #2：zhuanlan 文章是搜索线的常见产物，必须放行
        import zhihu_content as zc
        for good in ("https://zhuanlan.zhihu.com/p/1",
                     "https://www.zhihu.com/question/19550227",
                     "https://www.zhihu.com/question/19550227/answer/12202014"):
            self.assertEqual(zc._check_page_url(good), good)

    def test_missing_cookie_file_is_auth_error(self):
        import zhihu_content as zc
        from unittest import mock
        with mock.patch.object(zc, "_cookie_path",
                               return_value="Z:/no/such/file.json"):
            with self.assertRaises(zc.ZhihuAuthExpired) as cm:
                zc.fetch_question("19550227")
        self.assertIn("zhihu_bootstrap", str(cm.exception))

    def test_auth_error_maps_to_auth_expired(self):
        # 401/403（cookie 过期）必须报 zhihu_auth_expired 并提示重跑引导，
        # 不能伪装成真空或普通错误
        import zhihu_content as zc
        from unittest import mock
        cookie_json = json.dumps(
            {"cookies": {"d_c0": "fake", "__zse_ck": "fake"}})
        fake_resp = mock.Mock(status_code=403, text='{"error":{"code":40353}}')
        fake_resp.json.return_value = {"error": {"code": 40353}}
        with mock.patch.object(zc, "_cookie_path",
                               return_value="state/fake.json"), \
             mock.patch.object(zc.os.path, "exists", return_value=True), \
             mock.patch("builtins.open",
                        mock.mock_open(read_data=cookie_json)), \
             mock.patch.object(zc.requests, "get", return_value=fake_resp):
            with self.assertRaises(zc.ZhihuAuthExpired) as cm:
                zc.fetch_question("19550227")
        self.assertIn("重跑 python zhihu_bootstrap.py", str(cm.exception))


class TestWenxinEngine(unittest.TestCase):
    """v3.7 文心 AI 搜索引擎：SSE 解析 + 熔断器 + on_error 三态。

    测试边界（硬约束）：camoufox 浏览器交互（起浏览器/提交搜索/截获 SSE 流）
    不进离线测试——真浏览器 + 真配额（每浏览器身份约 1 次）+ 时序不确定，
    离线环境不可复现也不可负担；浏览器层只按侦察 p2 蓝本移植并在真实一发
    自测中人工验证。离线覆盖的是纯函数：parse_sse（真实 SSE 切片 fixture）、
    风控分类、熔断器状态机、env 解析、on_error 三态、门面路由。

    fixture 来源（真实样本切片，勿删）:
      - wenxin_sse_success.txt: cap_168.body（2026-09-10 成功搜索会话）切片——
        basedata + 前两个 markdown-yiyan 增量 + thinkingSteps（引用截前 2 条、
        摘要截 120 字）+ 末尾 endTurn 块；读取字段逐字节保真。
      - wenxin_sse_quota_1005.txt: cap2_146.body 全文（1005+kunlun_popup 原样）。
      - wenxin_sse_tokenfail_1001.txt: p3_repro1_sse.txt 前 1001/tokenFail 两块。
    """

    @classmethod
    def setUpClass(cls):
        cls.fixtures = REPO / "tests" / "fixtures"

    def _fixture(self, name):
        return (self.fixtures / name).read_text(encoding="utf-8")

    def setUp(self):
        import wenxin_engine as we
        import tempfile
        self.we = we
        # 熔断状态隔离：模块状态清零 + 落盘路径指到临时文件，
        # 绝不能让测试把真实 state/wenxin_breaker.json 置成 6h 冷却
        we._breaker_open_until = 0.0
        self._tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self._tmp.close()
        tmp_path = self._tmp.name
        patcher = mock.patch.object(we, "BREAKER_PATH", tmp_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(lambda: os.path.exists(tmp_path)
                        and os.unlink(tmp_path))

    def tearDown(self):
        self.we._breaker_open_until = 0.0

    def test_parse_success_fixture(self):
        # 真实成功流切片：markdown 增量拼接、引用字段、结束标志全对上
        we = self.we
        out = we.parse_sse(self._fixture("wenxin_sse_success.txt"))
        self.assertTrue(out["answer"].startswith("基于"),
                        f"答案拼接错: {out['answer'][:50]!r}")
        self.assertTrue(out["end_turn"])
        self.assertFalse(out["kunlun"])
        self.assertEqual(out["status_first"], 0)
        self.assertFalse(out["token_fail"])
        self.assertGreaterEqual(len(out["citations"]), 1)
        c0 = out["citations"][0]
        for key in ("url", "title", "abstract", "source"):
            self.assertIn(key, c0)
        self.assertTrue(c0["url"].startswith("http"))
        urls = [c["url"] for c in out["citations"]]
        self.assertEqual(len(urls), len(set(urls)))     # url 去重保序

    def test_parse_quota_1005_trips_breaker(self):
        # 真实 1005 样本：kunlun_popup + status 1005 → WenxinQuotaError + 熔断
        we = self.we
        out = we.parse_sse(self._fixture("wenxin_sse_quota_1005.txt"))
        self.assertEqual(out["kunlun"], "kunlun_popup")
        self.assertEqual(out["status_first"], 1005)
        self.assertTrue(out["end_turn"])
        with self.assertRaises(we.WenxinQuotaError) as cm:
            we._raise_for_risk(out)
        self.assertIn("熔断", str(cm.exception))
        self.assertTrue(we._breaker_is_open())          # 熔断器已进入冷却
        self.assertGreater(we._breaker_remaining_s(), 0)

    def test_parse_tokenfail_1001_no_breaker(self):
        # 真实 1001 样本：tokenFail → WenxinTokenError；不触发熔断
        # （token 失败是前端版本漂移，不是 IP 风控，冷却没有意义）
        we = self.we
        out = we.parse_sse(self._fixture("wenxin_sse_tokenfail_1001.txt"))
        self.assertEqual(out["status_first"], 1001)
        self.assertTrue(out["token_fail"])
        self.assertFalse(out["kunlun"])
        with self.assertRaises(we.WenxinTokenError):
            we._raise_for_risk(out)
        self.assertFalse(we._breaker_is_open())

    def test_wappass_page_url_trips_breaker(self):
        # SSE 没截到但页面跳了 wappass 验证码 —— 同样是熔断信号
        we = self.we
        with self.assertRaises(we.WenxinQuotaError):
            we._raise_for_risk({"kunlun": "", "status_first": 0},
                               page_url="https://wappass.baidu.com/static/captcha")
        self.assertTrue(we._breaker_is_open())

    def test_breaker_blocks_browser_launch(self):
        # 冷却期内直接报 wenxin_quota，绝不起浏览器（保护本 IP）
        we = self.we
        from unittest import mock
        we._trip_breaker("unit-test")
        with mock.patch.object(we, "_search_via_browser") as browser:
            with self.assertRaises(we.WenxinQuotaError) as cm:
                we.search("q", on_error="raise")
            self.assertIn("冷却", str(cm.exception))
            browser.assert_not_called()

    def test_breaker_expires(self):
        we = self.we
        we._breaker_open_until = time.time() - 1
        self.assertFalse(we._breaker_is_open())         # 过期即放行

    def test_cooldown_env_parsing(self):
        we = self.we
        from unittest import mock
        with mock.patch.dict(os.environ,
                             {"CHAT_SCRAPER_WENXIN_COOLDOWN_H": "0.5"}):
            self.assertEqual(we._cooldown_seconds(), 1800.0)
        with mock.patch.dict(os.environ,
                             {"CHAT_SCRAPER_WENXIN_COOLDOWN_H": "abc"}):
            self.assertEqual(we._cooldown_seconds(), 6.0 * 3600.0)
        with mock.patch.dict(os.environ, {}, clear=True):   # 防宿主残留变量
            self.assertEqual(we._cooldown_seconds(), 6.0 * 3600.0)

    def test_on_error_three_modes(self):
        # 熔断开放时的三态：report=错误记录 / raise=抛 / empty={}
        we = self.we
        we._trip_breaker("unit-test")
        row = we.search("q", on_error="report")
        self.assertIn("wenxin_quota", row["error"])
        self.assertEqual(row["tool"], "chat-scraper")
        self.assertEqual(row["platform"], "wenxin")
        self.assertEqual(row["query"], "q")
        self.assertEqual(we.search("q", on_error="empty"), {})
        with self.assertRaises(we.WenxinQuotaError):
            we.search("q", on_error="raise")

    def test_facade_routes_wenxin(self):
        # 门面分流：platforms=["wenxin"] -> 引擎单条聚合行原样入列
        import search as cs
        from unittest import mock
        row = {"q": "x", "answer": "a", "citations": [], "engine": "wenxin-ai",
               "count": 0, "platform": "wenxin", "vendor": "t", "role": "p"}
        with mock.patch.object(cs.wenxin_engine, "search",
                               return_value=row) as wf:
            out = cs.search("x", platforms=["wenxin"], vendor="t", role="p")
        self.assertEqual(out, [row])
        self.assertEqual(wf.call_args.kwargs.get("on_error"), "raise")
        self.assertEqual(wf.call_args.kwargs.get("vendor"), "t")

    def test_facade_wenxin_error_protocol(self):
        # 门面兜错误：引擎 raise 时 slug（wenxin_quota）进错误记录
        import search as cs
        from unittest import mock
        with mock.patch.object(cs.wenxin_engine, "search",
                               side_effect=cs.wenxin_engine.WenxinQuotaError("x")):
            out = cs.search("q", platforms=["wenxin"], on_error="report")
            self.assertEqual(len(out), 1)
            self.assertIn("wenxin_quota", out[0]["error"])
            self.assertEqual(out[0]["platform"], "wenxin")
            self.assertEqual(cs.search("q", platforms=["wenxin"],
                                       on_error="empty"), [])
            with self.assertRaises(cs.wenxin_engine.WenxinQuotaError):
                cs.search("q", platforms=["wenxin"], on_error="raise")

    def test_platform_registry_lists_wenxin(self):
        import search as cs
        self.assertIn("wenxin", cs.list_platforms())


class TestGoogleBridgeImport(unittest.TestCase):
    """v2 在 Windows import 即崩（SIGUSR1 无守卫）。能 import 本身就是回归测试。"""

    def test_import_on_any_platform(self):
        import search_helper  # noqa: F401


if __name__ == "__main__":
    unittest.main(verbosity=2)
