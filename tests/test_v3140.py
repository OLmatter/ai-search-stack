"""v3.14.0 回归：搜狗恢复曲线标定机制（doctor --sogou-probe + 引擎侧
probe_once）+ wenxin 声明对齐复查修复 + doctor SearXNG 引擎健康输出钉死。

四块内容（全部离线，零真实请求、零浏览器）：
1. 搜狗恢复曲线探活（sogou_engine.probe_once）：单发、判定与 search()
   逐字同判据（_blocked / 0 行 + _soft_blocked）、走引擎默认节流（探活
   不是攻击，与 probe_burst 的绕节流连发相反）、读数自带
   since_last_block_s（距连发标定日志末条 blocked 读数的秒数，无记录/坏
   行/文件缺失如实 null——恢复曲线的 x 轴）、网络异常也记读数落账（风控
   期 RST 是真实数据点）、log_path=None 不落账。
2. doctor --sogou-probe：cmd 模式显式传全局日志路径（patch 生效）、读数
   tool 字段标识发起者、blocked/正常均 exit 0（观测不判故障，同
   --cookie-probe 语义）、probe_once 本地故障 exit 1。
3. doctor.check_searxng 引擎健康历史观察（上轮发现项收尾确认）：
   unresponsive_engines 在 detail 里如实输出、零不健康时明说"引擎全健
   康"（此前零测试覆盖，钉死防回退）。
4. wenxin 对齐修复钉子：README v3.7 输出契约补 truncated 字段（v3.12
   截断可见化时文档滞后失实，本轮复查发现）；mcp china_search 描述补
   wenxin 单条聚合行声明。+ 版本锁 3.14.0。
"""
import datetime
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

import doctor as doctor_mod   # noqa: E402  (tools/doctor.py)
import sogou_engine as se     # noqa: E402  (chat-scraper/sogou_engine.py)


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


# ---- 1. 搜狗恢复曲线探活（引擎侧 probe_once） --------------------------------


class TestSogouProbeOnce(unittest.TestCase):
    """probe_once：单发探活 + 同判据 + 走默认节流 + jsonl 落账。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.log_path = str(pathlib.Path(self.tmpdir.name) / "recovery.jsonl")
        self.calls = []
        self.addCleanup(self.tmpdir.cleanup)

    def tearDown(self):
        with se._throttle_lock:
            se._last_request_ts = 0.0

    def _run(self, response=None, exc=None, **kw):
        def fake_get(session, url, **kwargs):
            self.calls.append(url)
            if exc is not None:
                raise exc
            return response
        kw.setdefault("log_path", self.log_path)
        with mock.patch.object(requests.Session, "get", fake_get), \
             mock.patch.object(se.time, "sleep"):
            return se.probe_once(**kw)

    def _read_log(self):
        with open(self.log_path, encoding="utf-8") as f:
            return [json.loads(ln) for ln in f if ln.strip()]

    def test_ok_reading_appended(self):
        entry = self._run(_Resp(_SOGOU_OK))
        self.assertEqual(self.calls, [se._SEARCH_URL])   # 单发
        self.assertFalse(entry["blocked"])
        self.assertEqual(entry["http"], 200)
        self.assertEqual(entry["rows"], 2)
        self.assertEqual(entry["tool"], "sogou_engine probe_once")
        self.assertIn("ts", entry)
        logged = self._read_log()
        self.assertEqual(len(logged), 1)
        self.assertEqual(logged[0], entry)

    def test_blocked_antispider_redirect(self):
        entry = self._run(_Resp(
            "", status_code=200,
            url="https://www.sogou.com/antispider/?m=1&antip=web_sh2"))
        self.assertTrue(entry["blocked"])
        self.assertIn("antispider", entry["note"])
        self.assertEqual(self._read_log()[0]["blocked"], True)

    def test_soft_block_zero_rows(self):
        # HTTP 200 但 0 行解析 + 全文有验证码标记 → 软风控（与 search 同判据）
        entry = self._run(_Resp("<html>请输入验证码继续访问</html>"))
        self.assertTrue(entry["blocked"])
        self.assertEqual(entry["rows"], 0)

    def test_network_error_recorded_not_raised(self):
        # 网络异常记读数落账不炸（风控期 RST 是恢复曲线的真实数据点）
        entry = self._run(exc=ConnectionError("RST during risk window"))
        self.assertEqual(self.calls, [se._SEARCH_URL])
        self.assertFalse(entry["blocked"])
        self.assertIsNone(entry["http"])
        self.assertIsNone(entry["rows"])
        self.assertIn("ConnectionError", entry["note"])
        self.assertEqual(len(self._read_log()), 1)

    def test_log_path_none_skips_file(self):
        entry = self._run(_Resp(_SOGOU_OK), log_path=None)
        self.assertEqual(entry["rows"], 2)
        self.assertFalse(pathlib.Path(self.log_path).exists())

    def test_waits_engine_throttle_not_bypassed(self):
        # 探活走引擎默认节流（与 probe_burst 的绕节流连发相反）：
        # 预置 _last_request_ts=995、monotonic=1000 → wait = 995+8-1000 = 3
        sleeps = []
        with mock.patch.object(requests.Session, "get",
                               return_value=_Resp(_SOGOU_OK)), \
             mock.patch.object(se.time, "sleep",
                               side_effect=lambda s: sleeps.append(s)), \
             mock.patch.object(se.time, "monotonic",
                               side_effect=lambda: 1000.0):
            with se._throttle_lock:
                se._last_request_ts = 995.0
            se.probe_once(log_path=None)
        self.assertEqual(sleeps, [3.0])

    def test_tool_field_passthrough(self):
        entry = self._run(_Resp(_SOGOU_OK), tool="doctor --sogou-probe")
        self.assertEqual(entry["tool"], "doctor --sogou-probe")


class TestSinceLastBlock(unittest.TestCase):
    """since_last_block_s：恢复曲线 x 轴（距连发标定日志末条 blocked）。"""

    def _write_throttle_log(self, lines):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        p = pathlib.Path(tmpdir.name) / "throttle.jsonl"
        p.write_text("".join(json.dumps(ln, ensure_ascii=False) + "\n"
                             for ln in lines), encoding="utf-8")
        return str(p)

    @staticmethod
    def _ts_seconds_ago(seconds):
        return (datetime.datetime.now().astimezone()
                - datetime.timedelta(seconds=seconds)
                ).isoformat(timespec="seconds")

    def test_seconds_since_last_blocked_reading(self):
        p = self._write_throttle_log([
            {"ts": self._ts_seconds_ago(200), "blocked": False},
            {"ts": self._ts_seconds_ago(100), "blocked": True},
            {"ts": self._ts_seconds_ago(50), "blocked": False},   # 末条非风控
        ])
        s = se._since_last_block_s(throttle_log=p)
        self.assertIsNotNone(s)
        self.assertGreaterEqual(s, 95)
        self.assertLessEqual(s, 105)

    def test_no_block_record_returns_none(self):
        p = self._write_throttle_log([
            {"ts": self._ts_seconds_ago(10), "blocked": False}])
        self.assertIsNone(se._since_last_block_s(throttle_log=p))

    def test_missing_file_returns_none(self):
        self.assertIsNone(se._since_last_block_s(
            throttle_log=str(pathlib.Path(tempfile.gettempdir())
                             / "no_such_throttle_log.jsonl")))

    def test_malformed_lines_skipped(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        p = pathlib.Path(tmpdir.name) / "throttle.jsonl"
        p.write_text("not json\n\n" + json.dumps(
            {"ts": self._ts_seconds_ago(100), "blocked": True}) + "\n",
            encoding="utf-8")
        s = se._since_last_block_s(throttle_log=str(p))
        self.assertGreaterEqual(s, 95)
        self.assertLessEqual(s, 105)

    def test_non_dict_json_lines_skipped(self):
        # 合法 JSON 但非对象（审计轮发现：int.get 会 AttributeError 炸探活，
        # 与"坏行一律如实返回 None"的声明不符）——与真读数混排也照样跳过
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        p = pathlib.Path(tmpdir.name) / "throttle.jsonl"
        p.write_text("123\nnull\n[1, 2]\n" + json.dumps(
            {"ts": self._ts_seconds_ago(100), "blocked": True}) + "\n",
            encoding="utf-8")
        s = se._since_last_block_s(throttle_log=str(p))
        self.assertGreaterEqual(s, 95)
        self.assertLessEqual(s, 105)

    def test_probe_once_carries_field(self):
        p = self._write_throttle_log([
            {"ts": self._ts_seconds_ago(100), "blocked": True}])
        with mock.patch.object(requests.Session, "get",
                               return_value=_Resp(_SOGOU_OK)), \
             mock.patch.object(se.time, "sleep"):
            entry = se.probe_once(log_path=None, throttle_log=p)
        self.assertGreaterEqual(entry["since_last_block_s"], 95)
        self.assertLessEqual(entry["since_last_block_s"], 105)


# ---- 2. doctor --sogou-probe -------------------------------------------------


class TestDoctorSogouProbe(unittest.TestCase):
    """cmd_sogou_probe / main(["--sogou-probe"])：落账、退出码语义。"""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.log_path = str(pathlib.Path(self.tmpdir.name) / "recovery.jsonl")
        self.addCleanup(self.tmpdir.cleanup)
        orig = doctor_mod.SOGOU_RECOVERY_LOG_PATH
        doctor_mod.SOGOU_RECOVERY_LOG_PATH = self.log_path
        self.addCleanup(setattr, doctor_mod, "SOGOU_RECOVERY_LOG_PATH", orig)

    def tearDown(self):
        with se._throttle_lock:
            se._last_request_ts = 0.0

    def _read_log(self):
        with open(self.log_path, encoding="utf-8") as f:
            return [json.loads(ln) for ln in f if ln.strip()]

    def test_ok_probe_appends_and_exits_zero(self):
        with mock.patch.object(requests.Session, "get",
                               return_value=_Resp(_SOGOU_OK)), \
             mock.patch.object(se.time, "sleep"):
            code = doctor_mod.main(["--sogou-probe"])
        self.assertEqual(code, 0)
        logged = self._read_log()
        self.assertEqual(len(logged), 1)
        self.assertEqual(logged[0]["tool"], "doctor --sogou-probe")
        self.assertFalse(logged[0]["blocked"])

    def test_blocked_reading_still_exit_zero(self):
        # 观测不判故障：blocked 是恢复曲线的成功数据点，不是巡检失败
        with mock.patch.object(requests.Session, "get", return_value=_Resp(
                "", status_code=200,
                url="https://www.sogou.com/antispider/?m=1")), \
             mock.patch.object(se.time, "sleep"):
            code = doctor_mod.main(["--sogou-probe"])
        self.assertEqual(code, 0)
        self.assertTrue(self._read_log()[0]["blocked"])

    def test_local_failure_exit_one(self):
        with mock.patch.object(se, "probe_once",
                               side_effect=OSError("disk full")):
            code = doctor_mod.main(["--sogou-probe"])
        self.assertEqual(code, 1)
        self.assertFalse(pathlib.Path(self.log_path).exists())


# ---- 3. doctor SearXNG 引擎健康历史观察 --------------------------------------


class TestDoctorSearxngEngineHealth(unittest.TestCase):
    """check_searxng 输出 unresponsive_engines（v3.14 钉死防回退）。"""

    def test_unresponsive_engines_reported(self):
        body = json.dumps({"results": [{"title": "x"}],
                           "unresponsive_engines": ["bing", "photon"]})
        with mock.patch.object(doctor_mod, "_get", return_value=body):
            detail = doctor_mod.check_searxng()
        self.assertIn("不健康引擎", detail)
        self.assertIn("bing", detail)
        self.assertIn("photon", detail)

    def test_all_healthy_said_explicitly(self):
        body = json.dumps({"results": [], "unresponsive_engines": []})
        with mock.patch.object(doctor_mod, "_get", return_value=body):
            detail = doctor_mod.check_searxng()
        self.assertIn("引擎全健康", detail)


# ---- 4. wenxin 对齐修复钉子 + 版本锁 ------------------------------------------


class TestWenxinAlignmentDocs(unittest.TestCase):
    """对齐复查修复钉子：声明与实现一致（源码级断言，v3.12 先例）。"""

    def test_readme_v37_output_contract_has_truncated(self):
        # v3.12 给 answer 顶层 + citations[].abstract 加 truncated 后，
        # README v3.7 用法节的输出契约未同步（本轮对齐复查发现的失实点）
        src = (REPO / "tools" / "chat-scraper" / "README.md"
               ).read_text(encoding="utf-8")
        self.assertIn("截 4000 时带 truncated=true", src)
        self.assertIn("abstract(截 500 时带 truncated=true)", src)

    def test_readme_truncated_claims_match_implementation(self):
        # 声明的截断上限与实现常量一字不差
        sys.path.insert(0, str(REPO / "tools" / "chat-scraper"))
        import wenxin_engine as we
        self.assertEqual(we.ANSWER_MAX_CHARS, 4000)
        self.assertEqual(we.ABSTRACT_MAX_CHARS, 500)

    def test_mcp_china_search_declares_single_row(self):
        # wenxin 返回单条聚合行（AI 答案 + 引用），不是网页列表——
        # mcp 描述此前缺此声明，调用方会按网页列表误读 answer/citations
        src = (REPO / "tools" / "mcp_server.py").read_text(encoding="utf-8")
        self.assertIn("单条聚合行", src)


class TestVersionSyncV314(unittest.TestCase):
    def test_versions_3140(self):
        sys.path.insert(0, str(REPO / "tools"))
        import mcp_server
        self.assertEqual(mcp_server.__version__, "3.14.0")
        # chat-scraper 目录名带连字符不可 import，源码级断言（v3.12 先例）
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        self.assertIn('__version__ = "3.14.0"', init_src)
        self.assertIn("chat-scraper v3.14.0", init_src)   # docstring 首行同步


if __name__ == "__main__":
    unittest.main()
