#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""google-bridge 看门狗：让「真 Google」通道常亮（v3.28）。

背景：search_helper.py 此前是手动后台进程，会话结束就死——
googlebridge_search 从此报 googlebridge_unreachable、doctor 的
google-bridge 检查亮红，直到有人手动 start_search_helper.sh。本看门狗把
「服务死了 → 拉起」闭环自动化：健康检查 127.0.0.1:<port>/health，
不可达即无人值守拉起 search_helper.py（分离进程，stdout/stderr 落
state/service.log），每次决策追加一行 state/watchdog.log。

架构依据（ARCHITECTURE 的工具自治原则）：
    - search_helper main() 先绑端口后懒加载 Chrome——拉起后 /health
      秒级可达（Chrome 未就绪时 /health 照常 200，"first-call pending"
      是正常启动态，/health 天然区分「进程死了」与「Chrome 未热」）
    - 本脚本路径自治（__file__ 定位仓库目录），不依赖 cwd/env——
      计划任务（watchdog_task.py 注册）与手动运行同一入口
    - .env 兜底加载（KEY=VALUE 逐行，仅 setdefault，绝不覆盖已导出的
      环境变量——与 start_search_helper.sh 的 ":=" 语义一致）

部署（Windows）:
    python watchdog_task.py register     # 开机自启 + 周期巡检两个计划任务
    python watchdog_task.py status / unregister   # 查看 / 一键回滚

手动运行:
    python watchdog.py                   # 检查 + 必要时拉起
    python watchdog.py --check-only      # 只观测不拉起

退出码契约（test_v3280 钉死）:
    0 = 健康（服务在，无动作）
    1 = 执行了恢复且宽限期内 /health 恢复（拉起成功）
    2 = 执行了恢复但宽限期内 /health 仍未达（Chrome/代理/依赖问题——
        进程层看门狗只保进程，不保 Google 可用性，详见两份 state 日志）
    3 = --check-only 且不健康
    10+ = 参数/内部错误（不属于观测语义）
"""
import argparse
import datetime
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

__version__ = "1.0.0"

HERE = Path(__file__).resolve().parent
HELPER = HERE / "search_helper.py"
SERVICE_LOG = HERE / "state" / "service.log"
WATCHDOG_LOG = HERE / "state" / "watchdog.log"
ENV_FILE = HERE / ".env"

ENV_PORT = "SEARCH_HELPER_PORT"
DEFAULT_PORT = 18799
HEALTH_PATH = "/health"
HEALTH_TIMEOUT = 5        # 单次健康检查超时（秒）
GRACE_SECONDS = 20        # 拉起后等待 /health 恢复的宽限（端口绑定秒级即可，
                          # Chrome 懒加载不占宽限——见模块 docstring）
POLL_INTERVAL = 1.0       # 宽限期轮询间隔（秒）

# Windows 分离进程标志；POSIX 用 start_new_session
_CREATE_FLAGS = 0
if sys.platform == "win32":
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    _CREATE_FLAGS = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def _port() -> int:
    """端口取环境变量（.env 兜底加载后），非法值回退默认。"""
    try:
        return int(os.environ.get(ENV_PORT, "") or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT


def load_env_defaults(path: Path = ENV_FILE) -> list:
    """.env 兜底加载：KEY=VALUE 逐行 setdefault 进 os.environ。

    只填空白、绝不覆盖已存在的环境变量（与 start_search_helper.sh 的
    ":=" 语义一致——用户显式 export 的值永远赢）。返回实际应用的键列表
    （测试钉 + 日志用）。解析失败/文件缺失 = 静默跳过（.env 本就可选）。
    """
    applied = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return applied
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key:
            continue
        if key not in os.environ or os.environ[key] == "":
            os.environ[key] = value
            applied.append(key)
    return applied


def check_health(port: int, timeout: int = HEALTH_TIMEOUT) -> bool:
    """/health 可达即健康（任何 HTTP 响应都算进程活着，含 5xx 语义态）；
    连接被拒/超时/DNS 失败 = 不健康。"""
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}{HEALTH_PATH}", timeout=timeout):
            return True
    except urllib.error.HTTPError:
        # 服务应答了（哪怕 503）= 进程在，不是看门狗的活
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _log_decision(line: str) -> None:
    """决策追加一行到 state/watchdog.log（append-only；写失败吞掉——
    日志绝不能影响看门狗动作本身）。"""
    try:
        WATCHDOG_LOG.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(WATCHDOG_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {line}\n")
    except OSError:
        pass


def _spawn_helper() -> int:
    """分离进程拉起 search_helper.py，返回子进程 pid（拉起失败抛 OSError）。

    stdout/stderr 追加进 state/service.log（与手动运行同一日志文件）；
    cwd/Python 解释器均由本脚本位置推导，计划任务环境无需任何配置。
    """
    SERVICE_LOG.parent.mkdir(parents=True, exist_ok=True)
    log_fh = open(SERVICE_LOG, "ab")
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = _CREATE_FLAGS
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(
        [sys.executable, str(HELPER)],
        cwd=str(HERE), stdout=log_fh, stderr=subprocess.STDOUT,
        **kwargs)
    return proc.pid


def run(check_only: bool = False,
        health_fn=check_health, spawn_fn=_spawn_helper,
        grace: float = GRACE_SECONDS, poll: float = POLL_INTERVAL) -> int:
    """看门狗主逻辑，返回退出码（契约见模块 docstring）。

    health_fn/spawn_fn 可注入（测试用假健康/假拉起）；grace/poll 可调
    （测试缩短宽限）。"""
    port = _port()
    if health_fn(port):
        _log_decision(f"healthy port={port} (no action)")
        return 0
    if check_only:
        _log_decision(f"unhealthy port={port} (check-only, no restart)")
        return 3
    try:
        pid = spawn_fn()
    except OSError as e:
        _log_decision(f"restart FAILED port={port} spawn_error={e}")
        return 2
    _log_decision(f"restarting port={port} pid={pid} grace={grace}s")
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        time.sleep(poll)
        if health_fn(port):
            _log_decision(f"restart OK port={port} pid={pid} "
                          "(health recovered within grace)")
            return 1
    _log_decision(f"restart UNCONFIRMED port={port} pid={pid} "
                  f"(health still down after {grace}s grace — "
                  "check state/service.log)")
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(
        description="google-bridge 看门狗：health 检查 + 服务死了自动拉起")
    parser.add_argument("--check-only", action="store_true",
                        help="只观测不拉起（不健康时退出码 3）")
    args = parser.parse_args()
    load_env_defaults()
    return run(check_only=args.check_only)


if __name__ == "__main__":
    sys.exit(main())
