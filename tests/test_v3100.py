"""v3.10.0 回归：知乎回答列表登录门修复（去 include）+ cursor 翻页 + doctor 钩子活性检查。

三块内容：
1. fetch_answers 直测（v3.10）：实测（2026-09-16，403 现场复现）知乎登录门
   已拦截 include=data[*].content 形态（403 code=40353，全新 cookie 亦然），
   v3.4 形态已死——新实现无 include（excerpt 契约不变）+ 服务端 cursor
   翻页（num≤500，paging.next 字节一致直调，max_pages 护栏）+ 访客配额墙
   按 is_end 如实截断。全部 mock _api_get，零真实请求。
2. doctor.check_hook_liveness（559c2c4 加入后无任何测试）：四分支——
   日志缺失 / 新鲜读数 / >48h 断线报警 / 坏时间戳。
3. 去重清理的行为等价证据：_raise_if_error_page 保留唯一一处后行为不变
   （短文本命中标记抛 ReadError、长文本放行）。

全部离线零外部网络、零浏览器。
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
for d in ("", "chat-scraper"):
    sys.path.insert(0, str(REPO / "tools" / d))

import doctor  # noqa: E402  (tools/doctor.py)
import zhihu_content as zc  # noqa: E402  (chat-scraper/zhihu_content.py)


def _ans_row(aid, author="张三", excerpt="答案摘要", content="<p>全文</p>",
             voteup=42):
    """/feeds 行的实测形态（2026-09-16 R4 实测键集的子集）。"""
    return {"target": {"id": str(aid), "author": {"name": author},
                       "excerpt": excerpt, "content": content,
                       "voteup_count": voteup}}


def _feed_page(rows, is_end, next_url=""):
    return {"data": rows,
            "paging": {"is_end": is_end, "next": next_url}}


class TestFetchAnswersV310(unittest.TestCase):
    """fetch_answers v3.10：无 include + cursor 翻页 + 护栏。"""

    def test_first_hop_has_no_include_param(self):
        # 登录门修复的核心断言：首跳请求串里绝不允许再出现 include=
        with mock.patch.object(zc, "_api_get",
                               return_value=_feed_page([], True)) as m:
            zc.fetch_answers("19550227", num=30)
        path = m.call_args_list[0][0][0]
        self.assertNotIn("include=", path)
        self.assertIn("/api/v4/questions/19550227/feeds?", path)
        self.assertIn("offset=0", path)
        self.assertIn("limit=20", path)          # min(num=30, 20)
        self.assertIn("sort_by=default", path)

    def test_single_hop_projection(self):
        page = _feed_page([_ans_row(111, author="李四", excerpt="摘",
                                    voteup=7)], is_end=True)
        with mock.patch.object(zc, "_api_get", return_value=page) as m:
            rows = zc.fetch_answers("19550227", num=10)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["author"], "李四")
        self.assertEqual(rows[0]["excerpt"], "摘")
        self.assertEqual(rows[0]["voteup"], 7)
        self.assertEqual(rows[0]["url"],
                         "https://www.zhihu.com/question/19550227/answer/111")
        self.assertEqual(m.call_count, 1)        # is_end 即停，不发第二跳

    def test_paging_follows_cursor_next_byte_exact(self):
        # 实测 cursor 形态：?cursor=...&limit= 尾随空 limit——剥壳后必须
        # 字节一致直调（签名字节=请求字节纪律）
        next_url = ("https://www.zhihu.com/api/v4/questions/19550227/feeds"
                    "?cursor=d3782dd27e1ca72e2a9a2f780b0931bf&limit=")
        page1 = _feed_page([_ans_row(i) for i in range(20)],
                           is_end=False, next_url=next_url)
        page2 = _feed_page([_ans_row(100 + i) for i in range(5)], is_end=True)
        with mock.patch.object(zc, "_api_get",
                               side_effect=[page1, page2]) as m:
            rows = zc.fetch_answers("19550227", num=30)
        self.assertEqual(len(rows), 25)
        second_path = m.call_args_list[1][0][0]
        self.assertEqual(
            second_path,
            "/api/v4/questions/19550227/feeds"
            "?cursor=d3782dd27e1ca72e2a9a2f780b0931bf&limit=")

    def test_num_reached_stops_without_second_call(self):
        page1 = _feed_page([_ans_row(i) for i in range(20)],
                           is_end=False, next_url="https://x/next")
        with mock.patch.object(zc, "_api_get", return_value=page1) as m:
            rows = zc.fetch_answers("19550227", num=10)
        self.assertEqual(len(rows), 10)          # 够数即停
        self.assertEqual(m.call_count, 1)

    def test_max_pages_guard(self):
        page = _feed_page([_ans_row(i) for i in range(20)],
                          is_end=False,
                          next_url="https://www.zhihu.com/api/v4/questions"
                                   "/19550227/feeds?cursor=x&limit=")
        with mock.patch.object(zc, "_api_get", return_value=page) as m:
            rows = zc.fetch_answers("19550227", num=500, max_pages=2)
        self.assertEqual(len(rows), 40)          # 2 页 × 20
        self.assertEqual(m.call_count, 2)        # 护栏生效，不无限翻

    def test_excerpt_falls_back_to_stripped_content(self):
        page = _feed_page([_ans_row(9, excerpt="", content="<p>你好<b>世界</b></p>")],
                          is_end=True)
        with mock.patch.object(zc, "_api_get", return_value=page):
            rows = zc.fetch_answers("19550227", num=5)
        # _strip_html 以空格替换标签边界（与评论/文章线同款行为）
        self.assertEqual(rows[0]["excerpt"], "你好 世界")

    def test_invalid_question_id_raises(self):
        with self.assertRaises(zc.ZhihuApiError):
            zc.fetch_answers("abc; rm -rf")

    def test_num_non_positive_zero_requests(self):
        with mock.patch.object(zc, "_api_get") as m:
            self.assertEqual(zc.fetch_answers("19550227", num=0), [])
            self.assertEqual(zc.fetch_answers("19550227", num=-3), [])
        m.assert_not_called()


class TestCheckHookLiveness(unittest.TestCase):
    """doctor.check_hook_liveness 四分支（559c2c4 引入后首次覆盖）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.log_path = os.path.join(self.tmp.name, "hook_log.jsonl")
        self._orig = doctor.COOKIE_LOG_PATH
        doctor.COOKIE_LOG_PATH = self.log_path
        self.addCleanup(setattr, doctor, "COOKIE_LOG_PATH", self._orig)

    def _write(self, obj):
        with open(self.log_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def test_missing_log_raises(self):
        self.assertRaises(RuntimeError, doctor.check_hook_liveness)

    def test_fresh_reading_passes(self):
        self._write({"ts": datetime.now().astimezone().isoformat(),
                     "status": "valid"})
        detail = doctor.check_hook_liveness()
        self.assertIn("最后读数", detail)
        self.assertIn("valid", detail)

    def test_stale_reading_raises_broken_hook_alarm(self):
        stale = datetime.now().astimezone() - timedelta(hours=49)
        self._write({"ts": stale.isoformat(), "status": "valid"})
        with self.assertRaises(RuntimeError) as ctx:
            doctor.check_hook_liveness()
        self.assertIn("断线", str(ctx.exception))

    def test_bad_ts_raises_valueerror(self):
        # 坏时间戳：原样抛 ValueError（由 _check 包装成 ⚠️ 可选异常显示）
        self._write({"ts": "not-a-timestamp", "status": "valid"})
        self.assertRaises(ValueError, doctor.check_hook_liveness)


class TestErrorPageMarkerDedup(unittest.TestCase):
    """去重后 _raise_if_error_page 行为不变（编译期唯一，运行期等价）。"""

    def test_short_text_with_marker_raises(self):
        self.assertRaises(zc.ReadError, zc._raise_if_error_page,
                          "完成验证后即可继续访问", "https://zhihu.com/q")

    def test_long_text_with_marker_passes(self):
        long_text = "正常讨论" * 300 + "环境异常"
        zc._raise_if_error_page(long_text, "https://zhihu.com/q")  # 不抛即过


if __name__ == "__main__":
    unittest.main()
