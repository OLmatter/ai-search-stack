"""v3.45.0 回归：全平台协议直连（B站评论/贴吧H5/微博H5/10大游戏资产盘口/财经快讯）+ 双订阅多端口代理池。

覆盖：
1. proxy_pool：双中转机场铁律（不按 server:port 去重、不过滤含"流量倍率"节点、精确过滤"剩余/有效期"说明节点）
   + mihomo listeners 一对一端口映射生成 + ProxyPoolRotator 冷却/熔断轮换。
2. bilibili_engine.fetch_comments：免登录 /x/v2/reply 评论+置顶+子评论 + 弹幕 deflate 解压 + 错误协议三态。
3. tieba_engine：getFrsData 吧内帖子流 + getPbData 千楼详情 + zhihu_content.read 贴吧 URL 自动分流。
4. weibo_engine：genvisitor2 秒签 .weibo.cn 访客流 + m.weibo.cn getIndex 实时/热门搜索 + ok!=1 自动刷新重试。
5. rmt_engine：7881 lb-sign 双 MD5 签名纯函数 + diff_order_book 两轮订单簿快照差分纯函数
   （区分 PARTIAL_FILL_CLEARED / TOUCH_CLEARED 与 RELIST_PRICE_CUT / OUT_OF_BOOK_CANCEL）
   + 10 平台路由与非法平台名错误协议。
6. finance_engine：东方财富股吧 var article_list 提取 + 7x24 快讯 + 非法源名错误协议。
7. TestVersionLock3450：三载体 3.45.0 精确锁 + README/CHANGELOG 同步 + 全仓真实测试数徽章对账。
"""
import pathlib
import re
import sys
import unittest
import zlib
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "tools" / "chat-scraper"))

import bilibili_engine as be        # noqa: E402
import finance_engine as fe         # noqa: E402
import macro_probe_engine as mpe    # noqa: E402
import proxy_pool as pp             # noqa: E402
import rmt_engine as rmt            # noqa: E402
import tieba_engine as te           # noqa: E402
import weibo_engine as we           # noqa: E402
import zhihu_content as zc          # noqa: E402


class TestProxyPoolRelayRules(unittest.TestCase):
    """中转机场两大工程铁律与轮换器离线钉。"""

    def test_preserves_shared_entry_relay_and_traffic_rate_nodes(self):
        # 铁律一：同 (server, port) 的不同国家落地节点绝不误删；
        # 铁律二：节点名含 "流量倍率:0.1" 绝不被当成 "剩余流量" 说明节点误删。
        sub2 = [
            {"name": "有效期2027-09-23, 剩余 100.00 GB", "server": "1.1.1.1", "port": 443},
            {"name": "荷兰-NL-4-流量倍率:0.1", "server": "relay.example.com", "port": 5566, "sni": "nl"},
            {"name": "德国-DE-2-流量倍率:1", "server": "relay.example.com", "port": 5566, "sni": "de"},
            {"name": "英国-UK-1-流量倍率:0.9", "server": "relay.example.com", "port": 5566, "sni": "uk"},
        ]
        valid = pp.filter_valid_proxies([("Sub2", sub2)])
        self.assertEqual(len(valid), 3)
        names = [p["name"] for p in valid]
        self.assertIn("[Sub2] 荷兰-NL-4-流量倍率:0.1", names)
        self.assertIn("[Sub2] 德国-DE-2-流量倍率:1", names)
        self.assertIn("[Sub2] 英国-UK-1-流量倍率:0.9", names)

    def test_build_mihomo_listeners_one_to_one_ports(self):
        proxies = [
            {"name": "n1", "server": "s1", "port": 443},
            {"name": "n2", "server": "s2", "port": 443},
        ]
        cfg, port_map = pp.build_mihomo_listeners_config(proxies, base_port=18201)
        self.assertEqual(port_map, {18201: "n1", 18202: "n2"})
        self.assertEqual(len(cfg["listeners"]), 2)
        self.assertEqual(cfg["listeners"][0]["port"], 18201)
        self.assertEqual(cfg["listeners"][1]["proxy"], "n2")

    def test_rotator_round_robin_and_blacklist(self):
        rot = pp.ProxyPoolRotator(ports=[18201, 18202], cooldown_sec=0.0)
        p1 = rot.pick_proxy("bilibili.com")
        p2 = rot.pick_proxy("bilibili.com")
        self.assertEqual(p1, "http://127.0.0.1:18201")
        self.assertEqual(p2, "http://127.0.0.1:18202")
        rot.mark_failed("http://127.0.0.1:18201", penalty_sec=120.0)
        self.assertEqual(rot.pick_proxy("bilibili.com"), "http://127.0.0.1:18202")


class TestBilibiliCommentsEngine(unittest.TestCase):
    """bilibili_engine.fetch_comments 评论+置顶+弹幕离线钉。"""

    def test_fetch_comments_parses_top_replies_and_deflate_danmaku(self):
        view_resp = mock.Mock(status_code=200)
        view_resp.json.return_value = {
            "code": 0,
            "data": {
                "aid": 11744395,
                "cid": 998877,
                "title": "搬砖金价日报",
                "owner": {"name": "工作室老王"},
                "pages": [{"page": 1, "cid": 998877, "part": "P1"}],
            },
        }
        reply_resp = mock.Mock(status_code=200)
        reply_resp.json.return_value = {
            "code": 0,
            "data": {
                "upper": {
                    "top": {
                        "rpid": 1,
                        "member": {"uname": "工作室老王"},
                        "content": {"message": "今日置顶收金比例 1:62"},
                        "like": 88,
                        "rcount": 2,
                        "ctime": 1700000000,
                        "replies": [],
                    }
                },
                "replies": [
                    {
                        "rpid": 2,
                        "member": {"uname": "路人甲"},
                        "content": {"message": "广东一区已经跌到 1:65 了"},
                        "like": 12,
                        "rcount": 1,
                        "ctime": 1700000100,
                        "replies": [
                            {
                                "rpid": 3,
                                "member": {"uname": "路人乙"},
                                "content": {"message": "属实"},
                                "like": 1,
                                "ctime": 1700000200,
                            }
                        ],
                    }
                ],
            },
        }
        raw_xml = '<i ><d p="0,1,25">1:65真实成交</d><d p="1,1,25">商人压价</d></i>'.encode("utf-8")
        comp = zlib.compressobj(zlib.Z_DEFAULT_COMPRESSION, zlib.DEFLATED, -zlib.MAX_WBITS)
        dm_resp = mock.Mock(status_code=200, content=comp.compress(raw_xml) + comp.flush())

        fake_sess = mock.Mock()
        fake_sess.get.side_effect = [view_resp, reply_resp, dm_resp]
        with mock.patch.object(be, "_get_session", return_value=fake_sess), \
             mock.patch.object(be, "_wait_turn"):
            out = be.fetch_comments("BV1GJ411x7h7", num=5)

        self.assertEqual(out["aid"], 11744395)
        self.assertEqual(out["top_reply"]["content"], "今日置顶收金比例 1:62")
        self.assertEqual(out["comment_count"], 1)
        self.assertEqual(out["comments"][0]["sub_replies"][0]["content"], "属实")
        self.assertEqual(out["danmaku"], ["1:65真实成交", "商人压价"])

    def test_fetch_comments_invalid_bvid_error_modes(self):
        rep = be.fetch_comments("not_a_bv", on_error="report")
        self.assertIn("ValueError", rep[0]["error"])
        self.assertEqual(be.fetch_comments("not_a_bv", on_error="empty"), [])
        with self.assertRaises(ValueError):
            be.fetch_comments("not_a_bv", on_error="raise")


class TestTiebaEngineAndReadRouting(unittest.TestCase):
    """tieba_engine H5 吧内流、楼层流及 zhihu_content.read 贴吧分流钉。"""

    def test_fetch_forum_and_thread_parsing(self):
        frs_resp = mock.Mock(status_code=200)
        frs_resp.json.return_value = {
            "errno": 0,
            "data": {
                "thread_list": [
                    {
                        "tid": 10186259783,
                        "title": "DNF跨五收金出金专贴",
                        "abstract": [{"text": "今日长期1:63收"}],
                        "author": {"name_show": "币商A"},
                        "reply_num": 815,
                        "last_time_int": 1700000500,
                        "is_top": False,
                    }
                ]
            },
        }
        pb_resp = mock.Mock(status_code=200)
        pb_resp.json.return_value = {
            "errno": 0,
            "data": {
                "thread": {"title": "DNF跨五收金出金专贴", "reply_num": 815},
                "forum": {"name": "dd373"},
                "page": {"current_page": 1, "total_page": 28},
                "post_list": [
                    {
                        "id": 991,
                        "floor": 1,
                        "author": {"name_show": "币商A"},
                        "content": [{"text": "一楼长期有效，骗子绕道"}],
                        "time": 1700000000,
                    }
                ],
            },
        }
        fake_sess = mock.Mock()
        fake_sess.get.side_effect = [frs_resp, pb_resp]
        with mock.patch.object(te, "_get_session", return_value=fake_sess), \
             mock.patch.object(te, "_wait_turn"):
            forum_rows = te.fetch_forum("dd373吧", num=5)
            th_data = te.fetch_thread("https://tieba.baidu.com/p/10186259783")

        self.assertEqual(len(forum_rows), 1)
        self.assertEqual(forum_rows[0]["forum"], "dd373")
        self.assertEqual(forum_rows[0]["tid"], "10186259783")
        self.assertEqual(th_data["post_count"], 1)
        self.assertIn("骗子绕道", th_data["posts"][0]["content"])

    def test_read_page_routes_tieba_thread_to_h5_api(self):
        fake_th = {
            "tid": "10186259783",
            "title": "交易专帖",
            "posts": [{"floor": 1, "author": "楼主", "content": "出1000万金币"}],
            "url": "https://tieba.baidu.com/p/10186259783",
        }
        with mock.patch.object(zc, "_check_http_url", side_effect=lambda u: u), \
             mock.patch("tieba_engine.fetch_thread", return_value=fake_th):
            res = zc.read("https://tieba.baidu.com/p/10186259783")
        self.assertEqual(res["engine"], "tieba-h5-api")
        self.assertIn("#1 @楼主: 出1000万金币", res["content"])


class TestWeiboEngine(unittest.TestCase):
    """weibo_engine .weibo.cn 访客流与实时搜索离线钉。"""

    def test_weibo_search_extracts_mblogs_and_strips_html(self):
        fake_resp = mock.Mock(status_code=200)
        fake_resp.json.return_value = {
            "ok": 1,
            "data": {
                "cards": [
                    {
                        "card_group": [
                            {
                                "mblog": {
                                    "id": "5354683888830124",
                                    "text": "县城商铺转让潮<br/>实体档口空置率上升",
                                    "user": {"screen_name": "调研员"},
                                    "created_at": "Fri Oct 16 16:33:07 +0800 2026",
                                    "attitudes_count": 42,
                                    "comments_count": 7,
                                    "reposts_count": 3,
                                }
                            }
                        ]
                    }
                ]
            },
        }
        with mock.patch.object(we, "_load_or_mint_cookies", return_value={"SUB": "tok"}), \
             mock.patch("requests.Session.get", return_value=fake_resp):
            rows = we.search("商铺转让", mode="realtime", num=5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "5354683888830124")
        self.assertIn("县城商铺转让潮\n实体档口空置率上升", rows[0]["content"])
        self.assertEqual(rows[0]["engine"], "mweibo-api")


class TestRmtEngineAndOrderBookDiff(unittest.TestCase):
    """rmt_engine 签名、两轮快照差分纯函数与 10 平台路由钉。"""

    def test_compute_7881_lbsign_deterministic(self):
        sig = rmt.compute_7881_lbsign('{"gameId":"G10"}', "1700000000000")
        self.assertEqual(len(sig), 32)
        self.assertRegex(sig, r"^[0-9a-f]{32}$")

    def test_diff_order_book_separates_real_fills_from_relist_and_cancel(self):
        before = [
            {"order_id": "A1", "unit_price": 0.60, "stock": 100, "seller_id": "S1"},
            {"order_id": "A2", "unit_price": 0.61, "stock": 50, "seller_id": "S2"},
            {"order_id": "A3", "unit_price": 0.65, "stock": 80, "seller_id": "S3"},
            {"order_id": "A4", "unit_price": 0.90, "stock": 200, "seller_id": "S4"},
        ]
        after = [
            # A1 库存从 100 降到 40 -> 实锤部分成交 60
            {"order_id": "A1", "unit_price": 0.60, "stock": 40, "seller_id": "S1"},
            # A2 消失且在卖一档附近 -> 实锤吃光 50
            # A3 消失但同一卖家 S3 新挂了同库存 80 的降价单 A3_NEW -> 滞销改价重挂（剔除）
            {"order_id": "A3_NEW", "unit_price": 0.62, "stock": 80, "seller_id": "S3"},
            # A4 消失但远高于卖一档 0.60*1.05 -> 远端无效撤单（剔除）
        ]
        res = rmt.diff_order_book(before, after)
        self.assertEqual(res["cleared_volume"], 110)
        self.assertAlmostEqual(res["cleared_vwap"], (60 * 0.60 + 50 * 0.61) / 110, places=5)
        fake_types = {e["type"] for e in res["fake_events"]}
        self.assertEqual(fake_types, {"RELIST_PRICE_CUT", "OUT_OF_BOOK_CANCEL"})

    def test_rmt_unknown_platform_error_modes(self):
        rep = rmt.probe(platform="not_a_rmt_site", on_error="report")
        self.assertIn("unknown rmt platform", rep[0]["error"])
        with self.assertRaises(ValueError):
            rmt.probe(platform="not_a_rmt_site", on_error="raise")


class TestFinanceEngine(unittest.TestCase):
    """finance_engine 股吧 SSR 解析与错误协议钉。"""

    def test_eastmoney_guba_parses_article_list_json(self):
        html_doc = (
            '<script>var article_list = {"re": [{"post_id": 12345, '
            '"post_title": "光伏组件库存见底了吗", "user_nickname": "老股民", '
            '"post_click_count": 500, "post_comment_count": 12, '
            '"post_publish_time": "2026-10-16 15:00:00"}]};</script>'
        )
        fake_resp = mock.Mock(status_code=200, text=html_doc)
        with mock.patch("requests.Session.get", return_value=fake_resp):
            rows = fe.fetch_wire(source="eastmoney_guba", query="zssh000001", num=5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "光伏组件库存见底了吗")
        self.assertEqual(rows[0]["clicks"], 500)

    def test_finance_unknown_source_error_modes(self):
        rep = fe.fetch_wire(source="bad_src", on_error="report")
        self.assertIn("unknown finance source", rep[0]["error"])
        with self.assertRaises(ValueError):
            fe.fetch_wire(source="bad_src", on_error="raise")


class TestMacroProbeEngine(unittest.TestCase):
    """macro_probe_engine 非游戏跨领域物理探针（PUA解码、黑猫签名、法拍折价、猫眼票房）离线钉。"""

    def test_decode_dongchedi_pua_restores_prices_and_mileage(self):
        # \ue49d=3, \ue3eb=7, .=., \ue4e3=8, \ue439=0, \ue40a=万
        raw = "\ue49d\ue3eb.\ue4e3\ue439\ue40a | \ue463\ue439\ue54c\ue3eb\ue525\ue54c\ue463\ue40a\ue492\ue4a8"
        self.assertEqual(mpe.decode_dongchedi_pua(raw), "37.80万 | 2017年12万公里")

    def test_compute_blackcat_signature_sha256(self):
        sig = mpe.compute_blackcat_signature("1700000000000", "AbCdEfGh12345678", "1", "10", "1")
        self.assertEqual(len(sig), 64)
        self.assertRegex(sig, r"^[0-9a-f]{64}$")

    def test_jd_auction_and_maoyan_boxoffice_parsing(self):
        jd_resp = mock.Mock(status_code=200)
        jd_resp.json.return_value = {
            "totalItem": 380126,
            "datas": [
                {
                    "id": 990011,
                    "title": "海口市某住宅房产",
                    "province": "海南",
                    "city": "海口",
                    "currentPrice": 270000,
                    "assessmentPrice": 450000,
                    "paimaiTimes": 4,
                    "bidCount": 0,
                    "shopName": "海口市某区人民法院",
                }
            ],
        }
        my_resp = mock.Mock(status_code=200)
        my_resp.json.return_value = {
            "movieList": {
                "nationBoxInfo": {
                    "nationBoxSplitUnit": {"num": "1995.4", "unit": "万"},
                    "showCountDesc": "37.7万",
                    "viewCountDesc": "52.7万",
                },
                "list": [
                    {
                        "movieInfo": {"movieId": 1, "movieName": "测试影片", "releaseInfo": "上映12天"},
                        "boxSplitUnit": {"num": "600.0", "unit": "万"},
                        "boxRate": "30.1%",
                        "sumBoxDesc": "3.18亿",
                        "showCount": 98927,
                        "avgShowView": "1.5",
                        "avgSeatView": "1.0%",
                    }
                ],
            }
        }
        with mock.patch("requests.Session.get", side_effect=[jd_resp, my_resp]):
            res_jd = mpe.probe(source="jd_auction", query="住宅", num=2)
            res_my = mpe.probe(source="maoyan_boxoffice", query="", num=2)

        self.assertEqual(res_jd["total_items"], 380126)
        self.assertEqual(res_jd["items"][0]["discount_pct"], -40.0)
        self.assertEqual(res_jd["items"][0]["stage"], "变卖")
        self.assertEqual(res_my["nation_box_office"], "1995.4万")
        self.assertEqual(res_my["movies"][0]["avg_people_per_show"], "1.5")

    def test_macro_probe_unknown_source_error_modes(self):
        rep = mpe.probe(source="invalid_probe", on_error="report")
        self.assertIn("unknown physical probe source", rep[0]["error"])
        with self.assertRaises(ValueError):
            mpe.probe(source="invalid_probe", on_error="raise")

    def test_arbitrage_scanner_sophon10_routing(self):
        import arbitrage_scanner as arb
        with mock.patch.object(arb, "get_live_usdt_cny", return_value=6.78), \
             mock.patch.object(rmt, "probe", return_value={}), \
             mock.patch.object(mpe, "probe", return_value={}):
            res = arb.scan_arbitrage(mode="digital", keyword="Path of Exile 2", num=2)
        self.assertEqual(res["source"], "arbitrage_scan")
        self.assertEqual(res["sophon_10_rules"]["card_id"], "sophon-10-wealth-arbitrage-sophon")
        table = res["digital"]["cross_border_spread_table"]
        self.assertGreaterEqual(len(table), 4)
        verdicts = {r["verdict"] for r in table}
        self.assertIn("ACTIONABLE_ARBITRAGE", verdicts)
        self.assertIn("FEE_TRAP_NET_LOSS", verdicts)
        self.assertEqual(len(arb.BLIND_DISCOVERY_METHODOLOGY), 5)
        self.assertIn("blind_discovery", arb.SUPPORTED_SCAN_MODES)



class TestVersionLock3450(unittest.TestCase):
    """v3.45.0 精确锁（接管自 test_v3440）：三版本载体 + README/CHANGELOG + 真实测试数徽章。"""

    def test_mcp_server_version(self):
        import mcp_server
        self.assertEqual(mcp_server.__version__, "3.45.0")

    def test_chat_scraper_package_version(self):
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        self.assertIn('__version__ = "3.45.0"', init_src)
        self.assertIn("chat-scraper v3.45.0", init_src)

    def test_digest_version(self):
        digest_src = (REPO / "tools" / "digest.py").read_text(encoding="utf-8")
        self.assertIn('__version__ = "3.45.0"', digest_src)

    def test_readme_headline_mentions_3450(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("release-v3.45.0", readme)
        self.assertIn("v3.45.0（2026-10-16）", readme)

    def test_changelog_has_3450_entry(self):
        cl = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [3.45.0] - ", cl)

    def test_readme_badge_count(self):
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        m = re.search(r"tests-(\d+)%20passing", readme)
        self.assertIsNotNone(m)
        real = 0
        for f in (REPO / "tests").glob("test_*.py"):
            real += len(re.findall(r"^    def (test_\w+)\(",
                                   f.read_text(encoding="utf-8"), re.M))
        self.assertGreater(real, 850)
        self.assertEqual(int(m.group(1)), real)


if __name__ == "__main__":
    unittest.main()
