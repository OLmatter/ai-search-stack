"""v3.40.0 回归：digest watch_feeds 厂商 RSS 动态段 + SOP client-shim 诚实性修复。

背景（v3.40 探索批裁决 A）：vendor 官宣第一方信号此前零自动覆盖（HN
watch_queries 只接社区讨论、GitHub releases 只接代码发布、热榜只接中文
回声）——digest 第五段「厂商动态（RSS）」闭合该缺口。模板默认只收实测
验证过的源（2026-09-17 openai.com/news/rss.xml HTTP 200 RSS 2.0；
anthropic 无 RSS、DeepMind/Meta/HF 本机网络不可达、机器之心 /rss 已
302 下线——取证记录见 digest.py docstring v3.40 段）。

四块内容（全部离线——fixture XML + tmp seen 状态 + 源码钉，零网络）：
1. parse_feed 原语：RSS 2.0 / Atom 双形态、坏 XML 与未知形态 ValueError
   如实报（不伪装成真空）、无链接条目跳过、FEED_PARSE_MAX 截断。
2. fetch_feeds 段：首轮建基线不洪水 / 二轮起 diff 新增 / seen 截断 /
   部分源故障单源降级 / 全源 fault 才段 fault / 空列表=empty 诚实 /
   seen 写失败整段 fault（承重态）/ 坏 seen 按首轮重建不炸。
3. 接线与文案：load_config 第四键、run_digest 五段 sections、render
   厂商动态段与页脚 RSS 图标、render_log_line RSS= 段、feeds=None 旧
   调用方兼容形态、toast 缺键渲染 ➖ 不虚报 ⚠️。
4. SOP client-shim 诚实性修复钉（chat-scraper 无 shim 的假陈述清除，
   实测 ModuleNotFoundError 先证）+ 版本锁 3.40.0 + CHANGELOG/README。
"""
import json
import pathlib
import re
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tools" / "chat-scraper"))

import digest as dg                  # noqa: E402

NOW = datetime(2026, 9, 17, 10, 0, 0)

_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>T</title>
<item><title>Item One</title><link>https://e.example/1</link>
<pubDate>Wed, 16 Sep 2026 09:00:00 GMT</pubDate></item>
<item><title>Item Two</title><link>https://e.example/2</link>
<pubDate>Wed, 16 Sep 2026 08:00:00 GMT</pubDate></item>
<item><title>No Link Item</title><pubDate>Wed, 16 Sep 2026 07:00:00 GMT</pubDate></item>
</channel></rss>"""

_ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>A</title>
<entry><title>Atom One</title>
<link href="https://a.example/1"/><updated>2026-09-16T12:00:00Z</updated></entry>
<entry><title>Atom Two</title>
<link href="https://a.example/2"/><published>2026-09-16T11:00:00Z</published></entry>
</feed>"""


def _rss_of(n):
    items = "".join(
        f"<item><title>i{k}</title><link>https://x.example/{k}</link></item>"
        for k in range(n))
    return f"<rss version='2.0'><channel>{items}</channel></rss>"


# ---------------------------------------------------------------------------
# 1. parse_feed 原语
# ---------------------------------------------------------------------------
class TestParseFeed(unittest.TestCase):
    def test_rss_items_extracted(self):
        rows = dg.parse_feed(_RSS)
        self.assertEqual([r["url"] for r in rows],
                         ["https://e.example/1", "https://e.example/2"])
        self.assertEqual(rows[0]["title"], "Item One")
        self.assertIn("2026", rows[0]["date"])

    def test_atom_entries_extracted(self):
        rows = dg.parse_feed(_ATOM)
        self.assertEqual([r["url"] for r in rows],
                         ["https://a.example/1", "https://a.example/2"])
        self.assertEqual(rows[0]["title"], "Atom One")
        self.assertTrue(rows[0]["date"])          # updated 优先
        self.assertTrue(rows[1]["date"])          # published 兜底

    def test_rss_cap_parse_max(self):
        rows = dg.parse_feed(_rss_of(dg.FEED_PARSE_MAX + 5))
        self.assertEqual(len(rows), dg.FEED_PARSE_MAX)

    def test_bad_xml_valueerror_not_crash(self):
        with self.assertRaises(ValueError):
            dg.parse_feed("<rss><channel><item>")

    def test_unknown_root_valueerror_not_fake_empty(self):
        # 无法识别形态如实报故障——不伪装成「0 条真空」（诚实协议）
        with self.assertRaises(ValueError):
            dg.parse_feed("<html><body>blocked</body></html>")

    def test_no_items_valueerror(self):
        with self.assertRaises(ValueError):
            dg.parse_feed("<rss version='2.0'><channel></channel></rss>")


# ---------------------------------------------------------------------------
# 2. fetch_feeds 段
# ---------------------------------------------------------------------------
class TestFetchFeeds(unittest.TestCase):
    def _run(self, feeds, fetcher, td, prepopulate=None):
        seen = Path(td) / "seen.json"
        if prepopulate is not None:
            seen.write_text(json.dumps(prepopulate), encoding="utf-8")
        return dg.fetch_feeds(feeds, fetcher=fetcher,
                              seen_path=str(seen)), seen

    def test_first_round_baseline_no_flood(self):
        with tempfile.TemporaryDirectory() as td:
            out, seen = self._run(["https://f.example/rss"],
                                  lambda url: _RSS, td)
            self.assertEqual(out["status"], "ok")
            f = out["feeds"][0]
            self.assertEqual(f["baseline"], 2)    # 无链接条目已跳过
            self.assertEqual(f["new"], [])
            self.assertTrue(f["items"])           # 基线轮展示源顶样目
            data = json.loads(seen.read_text(encoding="utf-8"))
            self.assertEqual(len(data["https://f.example/rss"]), 2)

    def test_second_round_diff_new_only(self):
        seen_pre = {"https://f.example/rss":
                    ["https://e.example/1", "https://e.example/2"]}
        rss3 = _RSS.replace("</channel>",
                            "<item><title>New!</title>"
                            "<link>https://e.example/3</link></item>"
                            "</channel>")
        with tempfile.TemporaryDirectory() as td:
            out, _ = self._run(["https://f.example/rss"],
                               lambda url: rss3, td, prepopulate=seen_pre)
        f = out["feeds"][0]
        self.assertEqual(f["new_n"], 1)
        self.assertEqual(f["new"][0]["url"], "https://e.example/3")
        self.assertNotIn("baseline", f)

    def test_seen_capped(self):
        seen_pre = {"https://f.example/rss":
                    [f"https://old.example/{k}" for k in range(dg.FEED_SEEN_MAX)]}
        with tempfile.TemporaryDirectory() as td:
            out, seen = self._run(["https://f.example/rss"],
                                  lambda url: _rss_of(3), td,
                                  prepopulate=seen_pre)
            data = json.loads(seen.read_text(encoding="utf-8"))
            self.assertLessEqual(
                len(data["https://f.example/rss"]), dg.FEED_SEEN_MAX)
            self.assertEqual(out["status"], "ok")

    def test_partial_fault_single_feed_degrades(self):
        def flaky(url):
            if "bad" in url:
                raise RuntimeError("HTTPError: 503")
            return _RSS
        with tempfile.TemporaryDirectory() as td:
            out, _ = self._run(["https://bad.example/rss",
                                "https://good.example/rss"], flaky, td)
        self.assertEqual(out["status"], "ok")     # 单源挂不炸段
        self.assertIn("error", out["feeds"][0])
        self.assertEqual(out["feeds"][1]["baseline"], 2)

    def test_all_fault_segment_fault(self):
        def boom(url):
            raise RuntimeError("down")
        with tempfile.TemporaryDirectory() as td:
            out, _ = self._run(["https://a.example/1",
                                "https://b.example/1"], boom, td)
        self.assertEqual(out["status"], "fault")

    def test_empty_config_is_empty_not_fault(self):
        with tempfile.TemporaryDirectory() as td:
            out, seen = self._run([], lambda url: _RSS, td)
        self.assertEqual(out["status"], "empty")
        self.assertFalse(seen.exists())           # 零网络零写

    def test_seen_write_failure_is_segment_fault(self):
        # seen 状态承重：写不进去 = diff 失明，按段 fault 如实报
        # （hotlist_watch 快照目录承重同构）；用目录占位 seen 路径使
        # write_text 必败（IsADirectoryError ⊂ OSError）
        with tempfile.TemporaryDirectory() as td:
            blocked = Path(td) / "d"
            blocked.mkdir()                        # 目录本身充当 seen 路径
            out = dg.fetch_feeds(
                ["https://f.example/rss"], fetcher=lambda url: _RSS,
                seen_path=str(blocked))
        self.assertEqual(out["status"], "fault")
        self.assertIn("seen", out.get("error", ""))

    def test_corrupt_seen_rebuilds_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            seen = Path(td) / "seen.json"
            seen.write_text("{corrupt", encoding="utf-8")
            out = dg.fetch_feeds(["https://f.example/rss"],
                                 fetcher=lambda url: _RSS,
                                 seen_path=str(seen))
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["feeds"][0]["baseline"], 2)  # 按首轮重建不炸


# ---------------------------------------------------------------------------
# 3. 接线与文案
# ---------------------------------------------------------------------------
class TestWiring(unittest.TestCase):
    def test_load_config_watch_feeds_key(self):
        # 第四键：合法透传 / 类型不对落默认带注
        raw = json.dumps({"watch_feeds": ["https://ok.example/rss"]})
        r = dg.load_config(loader=lambda p: raw)
        self.assertEqual(r["config"]["watch_feeds"],
                         ["https://ok.example/rss"])
        r2 = dg.load_config(loader=lambda p: '{"watch_feeds": "not-a-list"}')
        self.assertEqual(r2["config"]["watch_feeds"], dg.DEFAULT_FEEDS)
        self.assertIn("watch_feeds 类型不对", r2["note"])

    def test_template_readme_documents_feeds(self):
        data = json.loads((REPO / "tools" / "digest_config.example.json")
                          .read_text(encoding="utf-8"))
        self.assertIn("watch_feeds", data["_readme"])
        self.assertIn("openai.com/news/rss.xml", data["_readme"])

    def test_run_digest_five_sections_and_render(self):
        with tempfile.TemporaryDirectory() as td:
            r = dg.run_digest(
                config_loader=lambda p: json.dumps(
                    {"watch_repos": [], "watch_queries": [],
                     "watch_platforms": [], "watch_feeds":
                         ["https://f.example/rss"]}),
                feeds_fetcher=lambda url: _RSS,
                feed_seen_path=str(Path(td) / "seen.json"),
                shift_log=str(Path(td) / "none.log"),
                snapshots_dir=str(Path(td) / "snaps"), now=NOW)
        self.assertEqual(r["sections"]["feeds"], "ok")
        self.assertIn("## 厂商动态（RSS）", r["markdown"])
        self.assertIn("建基线 2 条", r["markdown"])
        self.assertIn("RSS ✅", r["markdown"])    # 页脚段状态

    def test_render_log_line_has_rss_segment(self):
        line = dg.render_log_line(NOW, {"hotlist": "ok", "hn": "ok",
                                        "releases": "ok", "feeds": "ok",
                                        "toolbox": "ok"})
        self.assertIn("RSS=ok", line)
        self.assertIn("digest: 热榜=ok", line)

    def test_render_feeds_none_old_caller_compat(self):
        # render(feeds=None)（旧调用方形态）走 empty 路径不炸、页脚 ➖
        md = dg.render({"status": "empty", "top": [], "watch_lines": []},
                       {"status": "ok", "queries": []},
                       {"status": "ok", "repos": []},
                       {"status": "ok", "shift_stats": None,
                        "cookie_age_h": None, "weibo_reading": None,
                        "snapshots_n": 0, "snapshots_latest": None},
                       "", now=NOW)
        self.assertIn("（未配置）watch_feeds 为空", md)
        self.assertIn("RSS ➖", md)

    def test_toast_missing_feeds_key_renders_dash_not_warn(self):
        # sections 缺 feeds 键（旧形态）→ RSS ➖ 不虚报 ⚠️
        # （非故障不许伪装成故障——统一错误协议的镜像纪律）
        _, body = dg.toast_text(
            {"overall": "ok", "ts": "2026-09-17 10:00:00",
             "sections": {"hotlist": "ok", "hn": "ok",
                          "releases": "ok", "toolbox": "ok"}})
        self.assertIn("RSS➖", body)
        self.assertNotIn("RSS⚠️", body)


# ---------------------------------------------------------------------------
# 4. SOP 诚实性修复钉 + 版本锁
# ---------------------------------------------------------------------------
class TestSopHonesty(unittest.TestCase):
    def test_sop_no_false_client_shim_claim(self):
        # v3.40 修复：SOP 曾称「旧的 from client import search 仍可用」
        # ——chat-scraper 全仓库史无 client.py（git log --all 实证）、
        # 实测 ModuleNotFoundError，假陈述清除并钉防回焊
        sop = (REPO / "SOP.md").read_text(encoding="utf-8")
        self.assertNotIn("`from client import search` 仍可用", sop)
        self.assertIn("chat-scraper 无 client shim", sop)
        self.assertIn("from search import search", sop)

    def test_digest_doc_documents_feeds_segment(self):
        doc = dg.__doc__ or ""
        self.assertIn("厂商动态（RSS）", doc)
        self.assertIn("openai.com/news/rss.xml", doc)   # 验证源取证在场
        self.assertIn("建基线", doc)


class TestVersionSyncV340(unittest.TestCase):
    def test_versions_evergreen(self):
        # v3.42 起精确锁移交 test_v3420，此处降常青下限（交接先例：
        # v3.27->…->v3.39 链延续）：双 __version__ 同步本身不许破，
        # 只放开具体版本号
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        m = re.search(r'__version__ = "([^"]+)"', init_src)
        self.assertIsNotNone(m)
        ver = m.group(1)
        self.assertGreaterEqual(
            tuple(int(x) for x in ver.split(".")), (3, 40, 0))
        self.assertIn(f"chat-scraper v{ver}", init_src)
        try:
            import mcp_server              # noqa: F401
            self.assertEqual(mcp_server.__version__, ver)
        except ImportError:
            src = (REPO / "tools" / "mcp_server.py").read_text(
                encoding="utf-8")
            self.assertIn(f'__version__ = "{ver}"', src)

    def test_changelog_and_readme_evergreen(self):
        # v3.42 起精确徽章/状态行锁移交 test_v3420，此处降常青：
        # 3.40 批次的 CHANGELOG 事实行（watch_feeds 五段）永久在场
        changelog = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.40.0] - 2026-09-17", changelog)
        self.assertIn("watch_feeds", changelog)
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        # 测试徽章数 v3.42 起移交 test_v3420 精确锁，此处降常青单调下限：
        # 770（v3.40 基线 = 746 + 本批 24 钉），回归只许增不许缩
        m = re.search(r"tests-(\d+)%20passing", readme)
        self.assertIsNotNone(m)
        self.assertGreaterEqual(int(m.group(1)), 770)

    @staticmethod
    def _batch_pins():
        src = (REPO / "tests" / "test_v3400.py").read_text(encoding="utf-8")
        # 数真实 test 方法定义形态；本函数注释与正则字面量一律不得写成
        # 可被下方正则命中的形态（自引用虚增——v3.33 首跑抓到过）
        return len(re.findall(r"def (test_\w+)\(", src))


if __name__ == "__main__":
    unittest.main()
