#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""worker_queue.json 派工队列认领机制（v3.17.0）——多 worker 并行领队列互踩的修复。

背景（上轮实证，判词证据）：两个 worker 并行领同一 ~/.zcode/worker_queue.json，
做了同一份活——v3.16 的 848065c 与另一班次工作树编辑逐字一致即为互踩证据。
本模块给派工队列加认领标记：worker 领活前先原子认领，其他 worker 见有效认领
即跳过；认领超时（默认 30 分钟无 complete）可重新认领；完成时删标记+清队列。

原子性设计（Windows / POSIX 双兼容，全部标准库）：
- 认领标记是独立伴生文件 ``<queue>.claim.json``，**绝不写队列文件本身**——
  创建用 ``os.open(O_CREAT|O_EXCL|O_WRONLY)``：两个平台都原子，目标已存在即
  抛 FileExistsError = 互斥成立（os.rename 在 POSIX 上会静默覆盖，不可用作
  创建互斥，故不用）。
- 超时接管不用"删旧+建新"两步——窗口期内两个 worker 可能都通过；改用
  tmp 文件 + ``os.replace`` 原子覆盖，覆盖后**读回校验**：标记内容不是自己的
  worker_id = 输给了并发接管的对手 → 返回 skipped 放弃。新建与接管两条路径
  统一过读回校验，防一切交错。
- 损坏标记（JSON 解析失败 / 字段缺失 / claimed_at 非数字）视为陈旧垃圾，走
  接管路径覆盖自愈——崩溃残留的半截标记文件不会永久卡死队列。
- 所有普通写（tmp、clear）均为 tmp + ``os.replace`` 同目录原子替换。

时钟基准：``time.time()`` epoch 秒。不保证单调（NTP 回拨会让 age 短暂偏小），
但认领超时粒度为分钟级，秒级回拨无实际影响——如实声明，不假装单调。

前提（审计补）：``queue_path`` 所在目录必须已存在（派工方写队列时自然满足）；
目录缺失时本模块不替调用方建目录也不静默吞错，直接抛 OSError——调用方
路径错误应在调用方修，模块不掩盖。

并发语义边界（如实声明）：本模块是协作约定不是安全边界——complete 删除前
读回校验 claimed_by，但"读回是我的 → 对手刚好接管覆盖 → 我的 remove 删掉
对方的标记"这一窗口无法用单文件原语消除；后果仅是对手的 complete 返回
False（对手自知失去标记），队列不会被破坏。跨进程真正的硬互斥以 O_EXCL
创建为准，该原语本身无窗口。
"""
import json
import os
import socket
import time

DEFAULT_CLAIM_TIMEOUT_S = 30 * 60   # 认领超时：30 分钟无 complete 可被重新认领
CLAIM_SUFFIX = ".claim.json"
_QUEUE_CLEAR_PAYLOAD = {"instructions": ""}


def _claim_path(queue_path):
    return queue_path + CLAIM_SUFFIX


def _default_worker_id():
    return f"{socket.gethostname()}:{os.getpid()}"


def _atomic_write_json(path, payload):
    """tmp + os.replace 同目录原子写 JSON。"""
    tmp = f"{path}.tmp.{os.getpid()}.{time.time_ns()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)


def _read_claim_raw(queue_path):
    """读认领标记原文。返回 (marker|None, corrupt:bool)。

    marker=None 且 corrupt=False：无标记文件；corrupt=True：文件在但内容
    不是合法标记（JSON 坏 / 非 dict / 缺字段 / claimed_at 非数字）。
    """
    p = _claim_path(queue_path)
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None, False
    except (OSError, ValueError):
        return None, True
    if not isinstance(data, dict):
        return None, True
    if not isinstance(data.get("claimed_by"), str) or \
       not isinstance(data.get("claimed_at"), (int, float)):
        return None, True
    return data, False


def read_claim(queue_path):
    """读当前认领标记（诊断用）：返回 {"claimed_by", "claimed_at", "age_s"}
    或 None（无标记/损坏——损坏细节走 claim() 的接管路径，这里不重复暴露）。"""
    marker, corrupt = _read_claim_raw(queue_path)
    if marker is None:
        return None
    return {"claimed_by": marker["claimed_by"],
            "claimed_at": marker["claimed_at"],
            "age_s": max(0.0, time.time() - marker["claimed_at"])}


def _create_claim_excl(queue_path, worker_id):
    """O_EXCL 原子创建认领标记。成功返回 True；已存在返回 False。
    写一半崩溃残留半截文件 → 下次被 corrupt 判定接管自愈。"""
    payload = json.dumps({"claimed_by": worker_id,
                          "claimed_at": time.time()},
                         ensure_ascii=False).encode("utf-8")
    try:
        fd = os.open(_claim_path(queue_path),
                     os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    except OSError:
        return False   # 平台差异兜底（如目录缺失），归入"没抢到"
    try:
        os.write(fd, payload)
    finally:
        os.close(fd)
    return True


def _verify_mine(queue_path, worker_id):
    """读回校验：标记在且 claimed_by == worker_id。"""
    marker, _ = _read_claim_raw(queue_path)
    return marker is not None and marker["claimed_by"] == worker_id


def claim(queue_path, worker_id=None, timeout_s=DEFAULT_CLAIM_TIMEOUT_S):
    """认领派工队列。

    返回 dict：
        {"status": "claimed",   "worker_id": ...}            新建认领成功
        {"status": "reclaimed", "worker_id": ...,
         "prev_owner": ...|None}                            超时/损坏接管成功
        {"status": "skipped",   "owner": ...|None, "age_s": x}  别人有效持有
    skipped 的 owner=None 表示标记损坏或接管竞态失败（可稍后重试）。
    """
    wid = worker_id or _default_worker_id()
    if _create_claim_excl(queue_path, wid) and _verify_mine(queue_path, wid):
        return {"status": "claimed", "worker_id": wid}

    marker, corrupt = _read_claim_raw(queue_path)
    if not corrupt and marker is not None:
        age = time.time() - marker["claimed_at"]
        if age < timeout_s:
            return {"status": "skipped", "owner": marker["claimed_by"],
                    "age_s": age}
        prev_owner = marker["claimed_by"]          # 超时 → 接管
    else:
        prev_owner = None                          # 损坏 → 接管自愈

    _atomic_write_json(_claim_path(queue_path),
                       {"claimed_by": wid, "claimed_at": time.time()})
    if _verify_mine(queue_path, wid):
        return {"status": "reclaimed", "worker_id": wid,
                "prev_owner": prev_owner}
    return {"status": "skipped", "owner": None, "age_s": None}


def acquire(queue_path, worker_id=None, timeout_s=DEFAULT_CLAIM_TIMEOUT_S):
    """领活唯一入口（v3.19.0）：认领 + 读队列一步完成。

    背景（根因修复）：v3.17 的 claim()/complete() 落地后被实证零使用——
    并行 worker 领活时不查 sidecar 直接干活，机制在库里、调用路径在各
    worker 的习惯里，等于没修。本函数把"先认领再读队列"固化成唯一入口：
    skipped 时**不返回 instructions**——看不到活的内容，从机制上杜绝
    "看到活就干"的互踩形态；claimed 才拿得到活的内容。

    返回 dict：
        {"status": "claimed", "worker_id": ...,
         "instructions": str,                可为空串 = 队列无活或队列读
         "reclaimed_from": ...|None}         不了（损坏如实视为无活）；非空
                                             = 超时/损坏接管，原持有者可见
                                             → 有活干完 complete()+clear()，
                                             空活直接 complete() 收工
        {"status": "skipped", "owner": ...|None,
         "age_s": ...}                       他人有效持有——不返回
                                             instructions，调用方应直接
                                             收工，不碰队列
        {"status": "no_queue"}               队列文件不存在，无事发生
                                             （不认领、不留 sidecar）
    """
    wid = worker_id or _default_worker_id()
    if not os.path.exists(queue_path):
        return {"status": "no_queue"}
    r = claim(queue_path, worker_id=wid, timeout_s=timeout_s)
    if r["status"] not in ("claimed", "reclaimed"):
        return r                       # skipped 原样透传（不含活内容）
    instructions = ""
    try:
        with open(queue_path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            val = data.get("instructions")
            instructions = val if isinstance(val, str) else ""
    except (OSError, ValueError):
        instructions = ""              # 队列损坏/读失败 = 无活可展示，如实
    return {"status": "claimed", "worker_id": r["worker_id"],
            "instructions": instructions,
            "reclaimed_from": r.get("prev_owner")}


def complete(queue_path, worker_id=None):
    """完成派工：删除**自己的**认领标记。返回 True=已删；False=无标记或
    标记不是自己的（超时被接管/从未认领）——调用方应停止动队列。"""
    wid = worker_id or _default_worker_id()
    if not _verify_mine(queue_path, wid):
        return False
    try:
        os.remove(_claim_path(queue_path))
    except OSError:
        # FileNotFoundError：极小窗口被接管者覆盖后移走；
        # PermissionError（Windows）：读句柄瞬时竞争。
        # 两者语义相同——标记没被我删掉，如实 False
        return False
    return True


def clear(queue_path):
    """清空派工队列：原子写回 {"instructions": ""}（与 observed 现状同款）。"""
    _atomic_write_json(queue_path, dict(_QUEUE_CLEAR_PAYLOAD))
