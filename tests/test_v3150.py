"""v3.15.0 回归：doctor 钩子活性检查扩展（覆盖 sogou_recovery_log）+ mcp
doctor 工具 mode 子模式参数 + SearXNG 实例上游引擎调优钉子。

四块内容（全部离线，零真实请求、零浏览器）：
1. doctor.check_hook_liveness 扩展：sogou_recovery_log 有读数后最后一条
   >48h 报警（开了就必须活着）；文件缺失/无有效读数=可选观测项未启用
   **不报警**（恢复曲线是增值观测，没人跑不算钩子断线）；坏行跳过不误报
   （append-only 日志的防御同 sogou_engine 读数解析）；cookie 侧 v3.8.2
   既有行为不回退（缺文件报警、坏时间戳原样 ValueError）。
2. mcp doctor 工具 mode 参数：full（默认，委托 main）/cookie（委托
   cmd_cookie_probe）/sogou（委托 cmd_sogou_probe）；退出码语义随模式
   如实变化（探活模式观测不判故障）；非法 mode 返回统一错误协议 JSON。
3. SearXNG settings.yml 引擎调优钉子：长期不健康引擎（brave/ddg/
   startpage，2026-09-16 doctor 标定）禁用条目在文件里、limiter:false
   保留、use_default_settings 合并语义保留、恢复方法注释在文件里。
4. 版本锁 3.15.0（mcp_server + chat-scraper __init__ 精确锁）。

实测证据（判词用，不入测试）：调优前 doctor 不健康引擎
[['brave','too many requests'],['duckduckgo','CAPTCHA'],
 ['startpage','parsing error']]，restart 后同一命令输出「引擎全健康」。
"""
import asyncio
import datetime
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

REPO = pathlib.Path(__file__).resolve().parent.parent
for d in ("", "chat-scraper"):
    sys.path.insert(0, str(REPO / "tools" / d))

import doctor as doctor_mod   # noqa: E402  (tools/doctor.py)

try:
    sys.path.insert(0, str(REPO / "tools"))
    import mcp_server
except ImportError:  # mcp SDK 未安装（部分 CI）——MCP 块整体跳过
    mcp_server = None


def _iso(dt):
    return dt.astimezone().isoformat()


# ---- 1. doctor 钩子活性扩展：sogou_recovery_log 覆盖 --------------------------


class TestHookLivenessSogouCoverage(unittest.TestCase):
    """check_hook_liveness v3.15 扩展：双标定日志，缺失语义分型。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cookie_log = os.path.join(self.tmp.name, "cookie_lifetime_log.jsonl")
        self.sogou_log = os.path.join(self.tmp.name, "sogou_recovery_log.jsonl")
        for attr, path in (("COOKIE_LOG_PATH", self.cookie_log),
                           ("SOGOU_RECOVERY_LOG_PATH", self.sogou_log)):
            self.addCleanup(setattr, doctor_mod, attr, getattr(doctor_mod, attr))
            setattr(doctor_mod, attr, path)

    def _write(self, path, *objs):
        with open(path, "w", encoding="utf-8") as f:
            for o in objs:
                f.write((o if isinstance(o, str) else
                         json.dumps(o, ensure_ascii=False)) + "\n")

    def _fresh_cookie(self):
        self._write(self.cookie_log,
                    {"ts": _iso(datetime.datetime.now()), "status": "valid"})

    # ---- sogou 侧：文件缺失 = 可选观测项，不报警 ----

    def test_sogou_log_missing_no_alarm(self):
        self._fresh_cookie()
        detail = doctor_mod.check_hook_liveness()
        self.assertIn("cookie 最后读数", detail)
        self.assertIn("sogou", detail)
        self.assertIn("不报警", detail)

    def test_sogou_log_all_garbage_treated_as_missing(self):
        # 全坏行 = 等于没有有效读数，同样不报警（不因日志损坏误报断线）
        self._fresh_cookie()
        self._write(self.sogou_log, "{not json", "[1, 2]", '"plain string"')
        detail = doctor_mod.check_hook_liveness()
        self.assertIn("不报警", detail)

    # ---- sogou 侧：有读数后 >48h = 报警 ----

    def test_sogou_stale_reading_raises_alarm(self):
        self._fresh_cookie()
        stale = datetime.datetime.now() - datetime.timedelta(hours=49)
        self._write(self.sogou_log,
                    {"ts": _iso(stale), "blocked": False, "http": 200})
        with self.assertRaises(RuntimeError) as ctx:
            doctor_mod.check_hook_liveness()
        msg = str(ctx.exception)
        self.assertIn("sogou", msg)
        self.assertIn("断线", msg)

    def test_sogou_stale_ignores_trailing_bad_lines(self):
        # 末尾坏行之后才是真读数？反向：坏行在中间——跳过后以最后一条
        # 有效读数为准（append-only 日志防御，不误报）
        self._fresh_cookie()
        now = datetime.datetime.now()
        self._write(self.sogou_log,
                    {"ts": _iso(now - datetime.timedelta(hours=50)),
                     "blocked": False},
                    "{broken line",
                    {"ts": _iso(now - datetime.timedelta(hours=1)),
                     "blocked": False})
        detail = doctor_mod.check_hook_liveness()
        self.assertIn("sogou 最后读数 1.0h 前", detail)

    # ---- sogou 侧：新读数如实进 detail；blocked 是读数不是故障 ----

    def test_sogou_fresh_reading_reported(self):
        self._fresh_cookie()
        self._write(self.sogou_log,
                    {"ts": _iso(datetime.datetime.now()),
                     "blocked": False, "http": 200, "rows": 9})
        detail = doctor_mod.check_hook_liveness()
        self.assertIn("sogou 最后读数", detail)
        self.assertIn("ok", detail)

    def test_sogou_blocked_reading_not_an_alarm(self):
        self._fresh_cookie()
        self._write(self.sogou_log,
                    {"ts": _iso(datetime.datetime.now()), "blocked": True})
        detail = doctor_mod.check_hook_liveness()
        self.assertIn("blocked", detail)   # 观测值照报，但不抛

    # ---- cookie 侧：v3.8.2 行为不回退 ----

    def test_cookie_log_missing_still_raises(self):
        self.assertRaises(RuntimeError, doctor_mod.check_hook_liveness)

    def test_cookie_log_empty_raises_no_valid_reading(self):
        # v3.15 收紧：空文件/全坏行从裸 JSONDecodeError 改为可读 RuntimeError
        self._write(self.cookie_log, "   ")
        with self.assertRaises(RuntimeError) as ctx:
            doctor_mod.check_hook_liveness()
        self.assertIn("无有效读数", str(ctx.exception))

    def test_cookie_bad_ts_still_valueerror(self):
        # 坏时间戳原样抛 ValueError（由 _check 包装成 ⚠️，v3.10 钉子不回退）
        self._write(self.cookie_log, {"ts": "not-a-timestamp", "status": "valid"})
        self.assertRaises(ValueError, doctor_mod.check_hook_liveness)

    def test_cookie_trailing_bad_line_uses_last_valid(self):
        self._write(self.cookie_log,
                    {"ts": _iso(datetime.datetime.now()), "status": "valid"},
                    "{broken")
        detail = doctor_mod.check_hook_liveness()
        self.assertIn("valid", detail)


# ---- 2. mcp doctor 工具 mode 子模式 -------------------------------------------


@unittest.skipUnless(mcp_server, "mcp SDK 未安装，跳过 MCP server 离线测试")
class TestMcpDoctorMode(unittest.TestCase):
    """mcp doctor(mode)：三态委托 + 退出码语义随模式 + 非法值错误协议。"""

    def test_full_mode_delegates_to_main(self):
        with mock.patch.object(mcp_server._doctor, "main", return_value=0) as m:
            out = mcp_server.doctor()
        m.assert_called_once_with()
        self.assertIn("退出码: 0", out)
        self.assertIn("核心通道全绿", out)   # full 语义的退出码说明

    def test_cookie_mode_delegates_to_cmd_cookie_probe(self):
        with mock.patch.object(mcp_server._doctor, "cmd_cookie_probe",
                               return_value=0) as m:
            out = mcp_server.doctor(mode="cookie")
        m.assert_called_once_with()
        self.assertIn("退出码: 0", out)
        self.assertIn("成功观测", out)       # 探活模式语义：expired 也是有效读数
        self.assertNotIn("核心通道全绿", out)

    def test_sogou_mode_delegates_to_cmd_sogou_probe(self):
        with mock.patch.object(mcp_server._doctor, "cmd_sogou_probe",
                               return_value=0) as m:
            out = mcp_server.doctor(mode="sogou")
        m.assert_called_once_with()
        self.assertIn("成功观测", out)

    def test_probe_mode_exit_one_surfaced(self):
        # 本地故障 exit 1 原样透传给调用方（cron/MCP 客户端可报警）
        with mock.patch.object(mcp_server._doctor, "cmd_sogou_probe",
                               return_value=1):
            out = mcp_server.doctor(mode="sogou")
        self.assertIn("退出码: 1", out)
        self.assertIn("本地故障", out)

    def test_invalid_mode_error_protocol(self):
        # 三个委托入口都挂上"被调即炸"的桩：非法 mode 不该碰任何探活函数
        for name in ("main", "cmd_cookie_probe", "cmd_sogou_probe"):
            m = mock.patch.object(mcp_server._doctor, name,
                                  side_effect=AssertionError("不该被调"))
            m.start()
            self.addCleanup(m.stop)
        out = json.loads(mcp_server.doctor(mode="yolo"))
        self.assertIn("full|cookie|sogou", out[0]["error"])
        self.assertEqual(out[0]["tool"], "doctor")

    def test_description_declares_modes_and_log_files(self):
        tools = asyncio.run(mcp_server.mcp.list_tools())
        desc = {t.name: t.description for t in tools}["doctor"]
        for token in ("full", "cookie", "sogou",
                      "cookie_lifetime_log.jsonl", "sogou_recovery_log.jsonl"):
            self.assertIn(token, desc)


# ---- 3. SearXNG settings.yml 引擎调优钉子 --------------------------------------


class TestSearxngEngineTuning(unittest.TestCase):
    """上游引擎调优（2026-09-16）：禁用条目/回滚方法/安全基线在文件里钉死。"""

    @classmethod
    def setUpClass(cls):
        cls.src = (REPO / "tools" / "searxng" / "docker" / "searxng"
                   / "settings.yml").read_text(encoding="utf-8")

    def test_chronic_unhealthy_engines_disabled(self):
        # 2026-09-16 doctor 标定：brave too many requests / duckduckgo
        # CAPTCHA / startpage parsing error（连轮不健康，见 v3.14 判词）。
        # v3.19 适配（行为演进先例，v3.18 对 test_v3160 obsolete pins 的
        # 处理同款）：startpage 经单引擎两关双过单独回滚（见 settings.yml
        # v3.19 观察记录），仅 brave/duckduckgo 维持禁用
        for engine in ("brave", "duckduckgo"):
            block = (f"- name: {engine}\n    disabled: true")
            self.assertIn(block, self.src, f"{engine} 缺禁用条目")

    def test_use_default_settings_merge_semantics_kept(self):
        # use_default_settings: true 下 engines 按名合并（269 引擎不缩水），
        # 禁用是"默认不调度"而非"从实例移除"——回滚零成本
        self.assertIn("use_default_settings: true", self.src)

    def test_limiter_still_off(self):
        # 本机实例基线：limiter 关闭（否则 urllib 客户端被自家实例 429）
        self.assertIn("limiter: false", self.src)

    def test_json_format_kept(self):
        self.assertIn("- json", self.src)

    def test_rollback_guidance_in_file(self):
        # 优雅回滚路径写进文件本身（换人可执行：注释掉条目→restart→doctor）
        self.assertIn("恢复方法", self.src)
        self.assertIn("docker compose restart", self.src)
        self.assertIn("tools/doctor.py", self.src)


# ---- 4. 版本锁 ------------------------------------------------------------------


class TestVersionSyncV315(unittest.TestCase):
    def test_versions_not_older_than_3150(self):
        # v3.16 起改为常青下限（v3.13->v3.14 先例）：精确锁当前版本是
        # test_v3160 的职责
        sys.path.insert(0, str(REPO / "tools"))
        import mcp_server
        self.assertGreaterEqual(
            tuple(int(x) for x in mcp_server.__version__.split(".")),
            (3, 15, 0))
        # chat-scraper 目录名带连字符不可 import，源码级断言（v3.12 先例）
        init_src = (REPO / "tools" / "chat-scraper" / "__init__.py"
                    ).read_text(encoding="utf-8")
        ver = __import__("re").search(
            r'__version__ = "([^"]+)"', init_src).group(1)
        self.assertGreaterEqual(
            tuple(int(x) for x in ver.split(".")), (3, 15, 0))
        self.assertIn(f"chat-scraper v{ver}", init_src)   # docstring 首行同步


if __name__ == "__main__":
    unittest.main()
