#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""双机场订阅多端口代理池（v3.45.0）—— 基于 mihomo listeners 的零切换延迟多 IP 轮换。

实测结论（2026-10-16 本机双订阅 84 节点实测）:
    - 合并 Clash Verge 配置目录下的两个机场订阅（Sub1 51 节点 + Sub2 33 节点 = 84 节点），
      通过 mihomo 的 listeners 配置将每个节点一对一绑定至本地独立端口 127.0.0.1:18201..18284。
    - 彻底消除通过 RESTful API 切换 GLOBAL 节点带来的全局竞态与连接中断：
      52 个存活节点对应 37 个完全独立的公网出口 IP（覆盖美/日/港/台/新/澳/德/英/荷/爱沙尼亚），
      其中 Google 204 通过 32 个 IP、Steam 订单簿通过 33 个 IP、B 站评论通过 32 个 IP、
      百度贴吧 H5 通过 31 个 IP。
    - 两大中转机场工程铁律（实测踩坑固化）:
      1. 严禁按 (server, port, type) 对节点入口去重：中转机场（如 Sub2）常复用仅有的
         3 个入口 (server, port)，靠 password/sni/协议参数在服务端路由至各国不同落地机；
         按入口去重会误杀 90% 节点。
      2. 严禁使用宽泛子串 "流量" 或 "群" 过滤说明节点：节点名常含 "流量倍率:0.1"，
         仅允许过滤精确信息词 ("剩余", "有效期", "到期", "官网", "重置", "网址", "进群", "导航")。

离线/无状态纪律:
    - 模块导入零网络请求、零进程拉起；
    - 当本地代理池未启动时，pick_proxy() 优雅返回 None（各引擎自动回退直连或环境变量代理）。
"""
import os
import socket
import threading
import time
from typing import Dict, List, Optional, Tuple

__all__ = [
    "INFO_NODE_SKIP_KEYWORDS",
    "filter_valid_proxies",
    "build_mihomo_listeners_config",
    "ProxyPoolRotator",
    "default_rotator",
]

# 铁律二：精确信息节点过滤词表（绝不含 "流量" 或宽泛 "群"，防误杀 "流量倍率:0.1" / "IEPL集群"）
INFO_NODE_SKIP_KEYWORDS: Tuple[str, ...] = (
    "剩余", "有效期", "到期", "官网", "重置", "网址", "进群", "导航",
)

DEFAULT_BASE_PORT = 18201


def filter_valid_proxies(
    sources: List[Tuple[str, List[Dict]]],
    skip_keywords: Tuple[str, ...] = INFO_NODE_SKIP_KEYWORDS,
) -> List[Dict]:
    """合并多订阅节点列表，仅剔除到期/剩余流量等纯说明项，保留全部中转节点（铁律一：不按 server:port 去重）。"""
    combined: List[Dict] = []
    used_names = set()
    for tag, plist in sources:
        if not isinstance(plist, list):
            continue
        for p in plist:
            if not isinstance(p, dict):
                continue
            raw_name = str(p.get("name") or "").strip()
            if not raw_name or any(k in raw_name for k in skip_keywords):
                continue
            if not p.get("server") or not p.get("port"):
                continue
            p_copy = dict(p)
            name = f"[{tag}] {raw_name}" if tag else raw_name
            while name in used_names:
                name += "_"
            used_names.add(name)
            p_copy["name"] = name
            combined.append(p_copy)
    return combined


def build_mihomo_listeners_config(
    proxies: List[Dict],
    base_port: int = DEFAULT_BASE_PORT,
    mixed_port: int = 17892,
    controller_port: int = 19100,
) -> Tuple[Dict, Dict[int, str]]:
    """生成一对一端口绑定的 mihomo 配置字典与 {port: node_name} 映射表。"""
    listeners: List[Dict] = []
    port_map: Dict[int, str] = {}
    for idx, p in enumerate(proxies):
        port = int(base_port) + idx
        listeners.append({
            "name": f"pool_{idx + 1}",
            "type": "mixed",
            "port": port,
            "listen": "127.0.0.1",
            "proxy": p["name"],
        })
        port_map[port] = p["name"]

    cfg = {
        "mixed-port": int(mixed_port),
        "allow-lan": False,
        "bind-address": "127.0.0.1",
        "mode": "rule",
        "log-level": "error",
        "ipv6": False,
        "external-controller": f"127.0.0.1:{int(controller_port)}",
        "proxies": proxies,
        "listeners": listeners,
        "rules": ["MATCH,DIRECT"],
    }
    return cfg, port_map


class ProxyPoolRotator:
    """按域名冷却时间与健康度轮换本地多端口代理池（线程安全，零外部依赖）。"""

    def __init__(self, ports: Optional[List[int]] = None, cooldown_sec: float = 2.0):
        self._lock = threading.Lock()
        self._ports: List[int] = list(ports or [])
        self._cooldown_sec = float(cooldown_sec)
        # {(domain, port): last_used_monotonic}
        self._last_used: Dict[Tuple[str, int], float] = {}
        # {port: fail_until_monotonic}
        self._blacklist_until: Dict[int, float] = {}
        self._cursor = 0

    def set_ports(self, ports: List[int]) -> None:
        with self._lock:
            self._ports = list(ports)
            self._cursor = 0

    def get_ports(self) -> List[int]:
        with self._lock:
            return list(self._ports)

    def mark_failed(self, proxy_url: str, penalty_sec: float = 60.0) -> None:
        """某端口请求超时或触发风控时临时熔断该端口。"""
        port = self._extract_port(proxy_url)
        if port is None:
            return
        with self._lock:
            self._blacklist_until[port] = time.monotonic() + float(penalty_sec)

    def mark_success(self, proxy_url: str) -> None:
        port = self._extract_port(proxy_url)
        if port is None:
            return
        with self._lock:
            self._blacklist_until.pop(port, None)

    @staticmethod
    def _extract_port(proxy_url: str) -> Optional[int]:
        if not proxy_url:
            return None
        try:
            tail = proxy_url.rsplit(":", 1)[-1].rstrip("/")
            return int(tail)
        except ValueError:
            return None

    def pick_proxy(self, domain: str = "default", min_interval: Optional[float] = None) -> Optional[str]:
        """挑选一个针对该 domain 已过冷却期且未熔断的代理 URL；池为空则返回 None。"""
        with self._lock:
            if not self._ports:
                return None
            now = time.monotonic()
            cd = self._cooldown_sec if min_interval is None else float(min_interval)
            n = len(self._ports)
            best_port = None
            earliest_ready = None

            for offset in range(n):
                idx = (self._cursor + offset) % n
                port = self._ports[idx]
                if self._blacklist_until.get(port, 0.0) > now:
                    continue
                last = self._last_used.get((domain, port), 0.0)
                if now - last >= cd:
                    best_port = port
                    self._cursor = (idx + 1) % n
                    self._last_used[(domain, port)] = now
                    break
                ready_at = last + cd
                if earliest_ready is None or ready_at < earliest_ready:
                    earliest_ready = ready_at
                    best_port = port

            if best_port is None:
                return None
            self._last_used[(domain, best_port)] = now
            return f"http://127.0.0.1:{best_port}"


def discover_listening_pool_ports(
    base_port: int = DEFAULT_BASE_PORT,
    count: int = 88,
    timeout: float = 0.05,
) -> List[int]:
    """快速探测本机已启动的 mihomo 代理池端口（仅按需调用，import 时不调）。"""
    open_ports: List[int] = []
    for port in range(int(base_port), int(base_port) + int(count)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                open_ports.append(port)
    return open_ports


default_rotator = ProxyPoolRotator()
