# -*- coding: utf-8 -*-
"""zhihu x-zse-96 签名（x-zse-93 = 101_3_3.0）纯 Python 实现。

移植自公开逆向成果 zly2006/zhihu_sign_rs (src/lib.rs, "使用来自 zhihu++ 的
成果")，属社区公开的反混淆知识。仅用于访客态只读请求。
配套：zhihu_bootstrap.py（无头 camoufox 领 d_c0/__zse_ck）、
zhihu_content.py（cookie+签名调官方 API 读内容）。

2026-09-09 验证记录：签名+真 cookie 调 /api/v4/questions/19550227 →
HTTP 200 真实 JSON（此前假 d_c0=40353、无签名=10003）；服务器验签通过。

核心流程:
  1. sign_source = "101_3_3.0" + "+" + pathname(+query) + "+" + d_c0 [+ "+" + body]
  2. md5hex = md5(sign_source).hexdigest()
  3. x-zse-96 = "2.0_" + encrypt_zse_v4(md5hex)
  4. 请求头: x-zse-93: 101_3_3.0, x-zse-96: <上一步>, x-requested-with: fetch
"""
import hashlib

ZSE93 = "101_3_3.0"
ALPHABET = "6fpLRqJO8M/c3jnYxFkUVC4ZIG12SiH=5v0mXDazWBTsuw7QetbKdoPyAl+hN9rgE"
KEY16 = b"059053f7d15e01d7"

ZK = [
    1170614578, 1024848638, 1413669199, 3951632832, 3528873006, 2921909214,
    4151847688, 3997739139, 1933479194, 3323781115, 3888513386, 460404854,
    3747539722, 2403641034, 2615871395, 2119585428, 2265697227, 2035090028,
    2773447226, 4289380121, 4217216195, 2200601443, 3051914490, 1579901135,
    1321810770, 456816404, 2903323407, 4065664991, 330002838, 3506006750,
    363569021, 2347096187,
]

ZB = [
    20, 223, 245, 7, 248, 2, 194, 209, 87, 6, 227, 253, 240, 128, 222, 91,
    237, 9, 125, 157, 230, 93, 252, 205, 90, 79, 144, 199, 159, 197, 186, 167,
    39, 37, 156, 198, 38, 42, 43, 168, 217, 153, 15, 103, 80, 189, 71, 191, 97,
    84, 247, 95, 36, 69, 14, 35, 12, 171, 28, 114, 178, 148, 86, 182, 32, 83,
    158, 109, 22, 255, 94, 238, 151, 85, 77, 124, 254, 18, 4, 26, 123, 176,
    232, 193, 131, 172, 143, 142, 150, 30, 10, 146, 162, 62, 224, 218, 196,
    229, 1, 192, 213, 27, 110, 56, 231, 180, 138, 107, 242, 187, 54, 120, 19,
    44, 117, 228, 215, 203, 53, 239, 251, 127, 81, 11, 133, 96, 204, 132, 41,
    115, 73, 55, 249, 147, 102, 48, 122, 145, 106, 118, 74, 190, 29, 16, 174,
    5, 177, 129, 63, 113, 99, 31, 161, 76, 246, 34, 211, 13, 60, 68, 207, 160,
    65, 111, 82, 165, 67, 169, 225, 57, 112, 244, 155, 51, 236, 200, 233, 58,
    61, 47, 100, 137, 185, 64, 17, 70, 234, 163, 219, 108, 170, 166, 59, 149,
    52, 105, 24, 212, 78, 173, 45, 0, 116, 226, 119, 136, 206, 135, 175, 195,
    25, 92, 121, 208, 126, 139, 3, 75, 141, 21, 130, 98, 241, 40, 154, 66, 184,
    49, 181, 46, 243, 88, 101, 183, 8, 23, 72, 188, 104, 179, 210, 134, 250,
    201, 164, 89, 216, 202, 220, 50, 221, 152, 140, 33, 235, 214,
]

_U32 = 0xFFFFFFFF


def _rol32(v, n):
    v &= _U32
    return ((v << n) | (v >> (32 - n))) & _U32


def encode_uri_component(s: str) -> bytes:
    """JS encodeURIComponent 的字节级等价。"""
    unescaped = set(
        b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.!~*'()"
    )
    out = bytearray()
    hexu = b"0123456789ABCDEF"
    for b in s.encode("utf-8"):
        if b in unescaped:
            out.append(b)
        else:
            out += b"%" + hexu[(b >> 4):((b >> 4) + 1)] + hexu[(b & 0x0F):((b & 0x0F) + 1)]
    return bytes(out)


def _g_transform(tt: int) -> int:
    te = tt.to_bytes(4, "big")
    tr = bytes(ZB[b] for b in te)
    ti = int.from_bytes(tr, "big")
    return (ti ^ _rol32(ti, 2) ^ _rol32(ti, 10) ^ _rol32(ti, 18) ^ _rol32(ti, 24)) & _U32


def _r_block(input16: bytes) -> bytes:
    tr = [0] * 36
    for j in range(4):
        tr[j] = int.from_bytes(input16[j * 4:j * 4 + 4], "big")
    for i in range(32):
        ta = _g_transform((tr[i + 1] ^ tr[i + 2] ^ tr[i + 3] ^ ZK[i]) & _U32)
        tr[i + 4] = (tr[i] ^ ta) & _U32
    out = b"".join(tr[k].to_bytes(4, "big") for k in (35, 34, 33, 32))
    return out


def _x_blocks(data: bytes, iv: bytes) -> bytes:
    out = bytearray()
    for off in range(0, len(data), 16):
        chunk = data[off:off + 16]
        mixed = bytes(chunk[i] ^ iv[i] for i in range(16))
        iv = _r_block(mixed)
        out += iv
    return bytes(out)


def _custom_encode(bts: bytes) -> str:
    while len(bts) % 3 != 0:
        bts += b"\x00"
    out = []
    i = 0
    p = len(bts) - 1
    while p >= 0:
        v = 0
        m0 = (58 >> (8 * (i % 4))) & 0xFF
        i += 1
        v |= (bts[p] ^ m0) & 0xFF
        m1 = (58 >> (8 * (i % 4))) & 0xFF
        i += 1
        v |= ((bts[p - 1] ^ m1) & 0xFF) << 8
        m2 = (58 >> (8 * (i % 4))) & 0xFF
        i += 1
        v |= ((bts[p - 2] ^ m2) & 0xFF) << 16
        out.append(ALPHABET[v & 63])
        out.append(ALPHABET[(v >> 6) & 63])
        out.append(ALPHABET[(v >> 12) & 63])
        out.append(ALPHABET[(v >> 18) & 63])
        p -= 3
    return "".join(out)


def encrypt_zse_v4(input_str: str, seed: int = 210) -> str:
    plain = bytearray([seed & 0xFF, 0])
    plain += encode_uri_component(input_str)
    pad = 16 - (len(plain) % 16)
    plain += bytes([pad]) * pad
    first = bytes(plain[i] ^ KEY16[i] ^ 42 for i in range(16))
    c0 = _r_block(first)
    cipher = bytearray(c0)
    if len(plain) > 16:
        cipher += _x_blocks(bytes(plain[16:]), c0)
    return _custom_encode(bytes(cipher))


def extract_pathname(url: str) -> str:
    """https://www.zhihu.com/api/v4/x?a=b -> /api/v4/x?a=b（含查询串）"""
    rest = url.split("//", 1)[1] if "//" in url else url
    path = rest.split("/", 1)[1] if "/" in rest else ""
    return "/" + path


def sign(url: str, d_c0: str, body=None):
    """返回 (x-zse-93, x-zse-96, x-requested-with) 三元组。"""
    sign_source = ZSE93 + "+" + extract_pathname(url) + "+" + d_c0
    if body is not None:
        sign_source += "+" + body
    md5hex = hashlib.md5(sign_source.encode("utf-8")).hexdigest()
    zse96 = "2.0_" + encrypt_zse_v4(md5hex)
    return ZSE93, zse96, "fetch"


def sign_headers(url: str, d_c0: str, body=None) -> dict:
    zse93, zse96, xrw = sign(url, d_c0, body)
    return {"x-zse-93": zse93, "x-zse-96": zse96, "x-requested-with": xrw}


if __name__ == "__main__":
    # 自检：签名输出格式（2.0_ 前缀 + 64 字符自定义 base64，md5hex 32字节输入
    # -> [2,0,32*bytes] 填充后 80 字节明文 -> 密文 80 字节 -> base64 108 字符左右）
    u = "https://www.zhihu.com/api/v4/search_v3?t=general&q=python&correction=1&offset=0&limit=20"
    h = sign_headers(u, "FAKE|1|0|FAKE")
    print("x-zse-93 =", h["x-zse-93"])
    print("x-zse-96 =", h["x-zse-96"])
    assert h["x-zse-96"].startswith("2.0_")
    # 注意 "=" 是自定义字母表里的合法字符（非 base64 填充），不能断言不存在
    assert set(h["x-zse-96"][4:]) <= set(ALPHABET)
    # 确定性检查
    assert h["x-zse-96"] == sign_headers(u, "FAKE|1|0|FAKE")["x-zse-96"]
    print("self-test OK, len(zse96) =", len(h["x-zse-96"]))
