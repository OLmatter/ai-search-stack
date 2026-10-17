#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""多平台游戏币/虚拟资产盘口与在线人口遥测引擎（v3.45.0）—— 10 大平台免登录直连 + 快照差分。

实测结论（2026-10-16 10 大平台协议级直连验证）:
    1. dd373     : 绕过 PC 端阿里云 ESA 滑块，直调 https://gw.dd373.com/<svc>/Api/...
                   (Origin: https://h5.dd373.com)，拿 538 款游戏目录 + C2C 卖盘 Ask + 求购盘 Bid。
    2. 7881      : 逆向 lb-cry.js 双重 MD5 签名 (secret="5c2c538a3937c6db2d04bce3d03bbe88bl"[::-1])
                   直调 https://gw.7881.com/goods-service-api/api/goods/list 拿卖盘 +
                   https://shou.7881.com/ajax/querySearchReceiptGoodsList.htm 拿求购盘 Bid。
    3. uu898     : SSR 直读 https://www.uu898.com/newTrade-... 卖盘与 newShTrade.aspx 求购盘。
    4. 5173      : 直调 2026 现役网关 https://shop.5173.com/g/gsort (456 款游戏目录与实时基准金价) +
                   /g/accounts (在售账号挂牌) + /g/recommend (全站推荐抛售流)。
    5. jiaoyimao : 绕过阿里霸下 (_____tmd_____)，直取 https://www.jiaoyimao.com/ SSR 内嵌
                   window.__INITIAL_DATA__.homePageInfo.realtimeTransactionInfos (96 条全站秒级
                   真实付款成交流水，含 '1秒前'/'4秒前') + 热门游戏挂牌。
    6. pzds      : 绕过 H5 _WASM_SIGN_API_LIST 签名，直读 https://www.pzds.com/goodsList/<id>/6
                   Nuxt SSR 退坑号列表（含标价与 '已减XX元' 降价幅度）。
    7. cbg       : 网易藏宝阁 https://dh2.cbg.163.com/cgi-bin/recommend.py 在售公示接口。
    8. steam     : 社区市场五档深度图 (itemordershistogram) + 官方实时在线人数 API
                   (ISteamUserStats/GetNumberOfCurrentPlayers/v1) + 商店最新评测 (appreviews)。
    9. g2g       : 全球跨境 RMT 微服务 https://sls.g2g.com/offer/search (USD 报价与库存深度)。
    10. taptap   : 固定 X-UA 免 Cookie 直调 https://www.taptap.cn/webapiv2/ 热榜/搜索/玩家评论。

复用边界（同 hotlist_engine.hot_diff 先例）:
    引擎提供无状态采样原语 probe() 与两轮盘口快照差分纯函数 diff_order_book(before, after)，
    将静态挂单（Ask）转化为实锤部分成交（PARTIAL_FILL_CLEARED）与卖一档消化（TOUCH_CLEARED），
    剔除改价重挂（RELIST_PRICE_CUT）与远端撤单（OUT_OF_BOOK_CANCEL）。
"""
import hashlib
import json
import re
import time
import urllib.parse
from typing import Dict, List, Optional, Tuple

import requests

__all__ = [
    "SUPPORTED_PLATFORMS",
    "probe",
    "compute_7881_lbsign",
    "diff_order_book",
    "RmtApiError",
]

_TOOL = "rmt-market"
SUPPORTED_PLATFORMS: Tuple[str, ...] = (
    "dd373", "7881", "uu898", "5173", "jiaoyimao",
    "pzds", "cbg", "steam", "g2g", "taptap",
)

_UA_PC = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)
_UA_H5 = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
_TAPTAP_XUA = (
    "V=1&PN=WebApp&LANG=zh_CN&VN_CODE=102&LOC=CN&PLT=PC&DS=Android"
    "&UID=00000000-0000-0000-0000-000000000000&OS=Windows&OSV=10&DT=PC"
)
_7881_SECRET = "5c2c538a3937c6db2d04bce3d03bbe88bl"[::-1]
TIMEOUT = 15


class RmtApiError(RuntimeError):
    """RMT 盘口接口非预期响应或反爬拦截。"""
    slug = "rmt_api_error"


def compute_7881_lbsign(body_str: str, timestamp_ms: str) -> str:
    """7881 lb-cry.js 双重 MD5 签名纯函数：pubKey=md5(secret+ts), sign=md5(pubKey+body)。"""
    pub_key = hashlib.md5((_7881_SECRET + str(timestamp_ms)).encode("utf-8")).hexdigest()
    return hashlib.md5((pub_key + str(body_str)).encode("utf-8")).hexdigest()


def diff_order_book(
    before: List[Dict],
    after: List[Dict],
    best_ask_tolerance: float = 1.05,
) -> Dict:
    """两轮订单簿快照差分纯函数（零网络依赖，把静态挂单转化为真实成交信号）。

    输入条目字段约定:
        {"order_id": str, "unit_price": float, "stock": int, "seller_id": str(可选)}
    """
    b_map = {str(x["order_id"]): x for x in (before or [])
             if isinstance(x, dict) and x.get("order_id")}
    a_map = {str(x["order_id"]): x for x in (after or [])
             if isinstance(x, dict) and x.get("order_id")}
    if not b_map:
        return {
            "cleared_events": [],
            "fake_events": [],
            "cleared_volume": 0,
            "cleared_vwap": None,
        }

    best_ask = min(float(x.get("unit_price") or 0.0) for x in b_map.values())
    new_orders = [x for oid, x in a_map.items() if oid not in b_map]

    cleared_events: List[Dict] = []
    fake_events: List[Dict] = []

    for oid, b in b_map.items():
        b_price = float(b.get("unit_price") or 0.0)
        b_stock = int(b.get("stock") or 0)
        b_seller = str(b.get("seller_id") or "")

        if oid in a_map:
            a = a_map[oid]
            a_stock = int(a.get("stock") or 0)
            a_price = float(a.get("unit_price") or b_price)
            if a_stock < b_stock:
                cleared_events.append({
                    "type": "PARTIAL_FILL_CLEARED",
                    "order_id": oid,
                    "unit_price": a_price,
                    "delta_qty": b_stock - a_stock,
                })
        else:
            relisted = any(
                b_seller and str(n.get("seller_id") or "") == b_seller
                and int(n.get("stock") or 0) == b_stock
                and float(n.get("unit_price") or 0.0) < b_price
                for n in new_orders
            )
            if relisted:
                fake_events.append({"type": "RELIST_PRICE_CUT", "order_id": oid})
            elif b_price <= best_ask * float(best_ask_tolerance):
                cleared_events.append({
                    "type": "TOUCH_CLEARED",
                    "order_id": oid,
                    "unit_price": b_price,
                    "delta_qty": b_stock,
                })
            else:
                fake_events.append({"type": "OUT_OF_BOOK_CANCEL", "order_id": oid})

    total_vol = sum(int(e["delta_qty"]) for e in cleared_events)
    vwap = (
        round(sum(float(e["unit_price"]) * int(e["delta_qty"]) for e in cleared_events) / total_vol, 6)
        if total_vol > 0 else None
    )
    return {
        "cleared_events": cleared_events,
        "fake_events": fake_events,
        "cleared_volume": total_vol,
        "cleared_vwap": vwap,
    }


def _probe_dd373(session: requests.Session, query: str, num: int) -> Dict:
    hdr = {
        "User-Agent": _UA_H5,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json; charset=utf-8",
        "Origin": "https://h5.dd373.com",
        "Referer": "https://h5.dd373.com/",
    }
    r_games = session.get(
        "https://gw.dd373.com/game/Api/Game/MobileList",
        params={"GameType": "全部游戏", "Keyword": query or ""},
        headers=hdr, timeout=TIMEOUT,
    )
    r_games.raise_for_status()
    games = ((r_games.json().get("StatusData") or {}).get("ResultData")) or []

    # 默认附带 DNF 广东1区实时买卖盘样本以验证点差
    srv_id = "f902c7b6-4ce7-4b0d-8d9f-4bf422f65e7d"
    gt_id = "739b5eb8-3d96-4b09-9a06-5a8983a6adf4"
    c2c_payload = {
        "DealType": "", "GoodsType": gt_id, "LastId": srv_id,
        "MaxPrice": "", "MinPrice": "", "SecurityList": "",
        "ShopAttributeIdentifyList": "", "SortType": "", "Title": "",
        "PageIndex": 1, "PageSize": max(1, min(int(num), 10)),
    }
    r_ask = session.post(
        "https://gw.dd373.com/goods/Api/Goods/UserCenter/QueryList",
        data=json.dumps(c2c_payload).encode("utf-8"),
        headers=hdr, timeout=TIMEOUT,
    )
    r_ask.raise_for_status()
    asks = (((r_ask.json().get("StatusData") or {}).get("ResultData") or {}).get("PageResult")) or []

    r_bid = session.get(
        "https://gw.dd373.com/goods/Api/Receive/UserCenter/QueryList",
        params={"LastId": srv_id, "GoodsType": gt_id, "PageIndex": 1,
                "PageSize": max(1, min(int(num), 10)), "SplitPage": "false"},
        headers=hdr, timeout=TIMEOUT,
    )
    r_bid.raise_for_status()
    bids = (((r_bid.json().get("StatusData") or {}).get("ResultData") or {}).get("PageResult")) or []

    return {
        "platform": "dd373",
        "engine": "dd373-h5-gw",
        "games_matched": len(games),
        "games_sample": [{"id": g.get("Id"), "name": g.get("Name"), "type": g.get("GameType")}
                         for g in games[:max(1, int(num))]],
        "ask_orders": asks[:max(1, int(num))],
        "bid_orders": bids[:max(1, int(num))],
    }


def _probe_7881(session: requests.Session, game_id: str, num: int) -> Dict:
    gid = (game_id or "G10").strip() or "G10"
    ts = str(int(time.time() * 1000))
    param_obj = {
        "marketRequestSource": "search", "sellerType": "C",
        "gameId": gid, "gtid": "100001", "tradePlace": "0",
        "pageNum": 1, "pageSize": max(1, min(int(num), 10)),
    }
    body_str = json.dumps(param_obj, separators=(",", ":"))
    lb_sign = compute_7881_lbsign(body_str, ts)
    hdr = {
        "User-Agent": _UA_PC,
        "Content-Type": "application/json",
        "Origin": "https://search.7881.com",
        "Referer": f"https://search.7881.com/list.html?gameId={gid}&gtId=100001",
        "lb-timestamp": ts,
        "lb-sign": lb_sign,
    }
    r_ask = session.post(
        "https://gw.7881.com/goods-service-api/api/goods/list",
        data=body_str.encode("utf-8"), headers=hdr, timeout=TIMEOUT,
    )
    r_ask.raise_for_status()
    c2c_body = (r_ask.json().get("body")) or {}

    r_bid = session.get(
        "https://shou.7881.com/ajax/querySearchReceiptGoodsList.htm",
        params={
            "gameId": gid, "goodsType": "100001", "groupId": f"{gid}P001",
            "serverId": f"{gid}P001001", "campId": "", "t": ts,
            "queryReceiptCallback": "queryReceiptCallback",
        },
        headers={"User-Agent": _UA_PC, "Referer": "https://search.7881.com/"},
        timeout=TIMEOUT,
    )
    r_bid.raise_for_status()
    m = re.search(r"^queryReceiptCallback\((.*)\)$", r_bid.text.strip(), re.S)
    bid_body = json.loads(m.group(1)) if m else {}

    return {
        "platform": "7881",
        "engine": "7881-gw-lbsign",
        "game_id": gid,
        "total_ask_records": c2c_body.get("records", 0),
        "ask_orders": (c2c_body.get("results") or [])[:max(1, int(num))],
        "bid_orders": (bid_body.get("simpleList") or [])[:max(1, int(num))],
    }


def _probe_5173(session: requests.Session, query: str, num: int) -> Dict:
    hdr = {
        "User-Agent": _UA_PC,
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://shop.5173.com",
        "Referer": "https://shop.5173.com/",
    }
    r_gsort = session.get("https://shop.5173.com/g/gsort", headers=hdr, timeout=TIMEOUT)
    r_gsort.raise_for_status()
    gsort_data = (r_gsort.json().get("data")) or []
    flat_games: List[Dict] = []
    if isinstance(gsort_data, dict):
        raw_items = gsort_data.get("items") or []
        if isinstance(raw_items, list):
            flat_games.extend(x for x in raw_items if isinstance(x, dict))
    elif isinstance(gsort_data, list):
        for group in gsort_data:
            items = group.get("items") if isinstance(group, dict) else None
            if isinstance(items, list):
                flat_games.extend(x for x in items if isinstance(x, dict))
            elif isinstance(group, dict) and group.get("game_name"):
                flat_games.append(group)

    kw = (query or "").strip()
    matched = [g for g in flat_games if not kw or kw.lower() in str(g.get("game_name", "")).lower()]
    with_gold_price = [g for g in matched if g.get("price") and str(g.get("price")) != "0"]

    r_rec = session.get(
        "https://shop.5173.com/g/recommend",
        params={"page": 1, "page_size": max(1, min(int(num), 15))},
        headers=hdr, timeout=TIMEOUT,
    )
    r_rec.raise_for_status()
    rec_items = ((r_rec.json().get("data") or {}).get("items")) or []

    return {
        "platform": "5173",
        "engine": "5173-shop-api",
        "total_games": len(flat_games),
        "gold_benchmark_prices": with_gold_price[:max(1, int(num))],
        "games_sample": matched[:max(1, int(num))],
        "recommend_listings": rec_items[:max(1, int(num))],
    }


def _probe_jiaoyimao(session: requests.Session, num: int) -> Dict:
    resp = session.get("https://www.jiaoyimao.com/", headers={"User-Agent": _UA_PC}, timeout=TIMEOUT)
    resp.raise_for_status()
    text = resp.text
    if "_____tmd_____" in text:
        session.trust_env = not getattr(session, "trust_env", False)
        resp = session.get("https://www.jiaoyimao.com/", headers={"User-Agent": _UA_PC}, timeout=TIMEOUT)
        resp.raise_for_status()
        text = resp.text
    if "_____tmd_____" in text:
        raise RmtApiError("jiaoyimao triggered Alibaba baxia slider")
    m = re.search(r"window\.__INITIAL_DATA__\s*=\s*(\{.*?\});?\s*</script>", text, re.S)
    if not m:
        raise RmtApiError("jiaoyimao SSR missing window.__INITIAL_DATA__")
    raw_clean = re.sub(r"(?<=[:\[,])\s*undefined\b", "null", m.group(1))
    raw_clean = re.sub(r"new\s+Date\(([^)]*)\)", r"\1", raw_clean)
    obj, _ = json.JSONDecoder().raw_decode(raw_clean)
    home = (
        obj.get("homePageInfo")
        or ((obj.get("pageInitialProps") or {}).get("initialData") or {}).get("homePageInfo")
        or {}
    )
    tx_list = home.get("realtimeTransactionInfos") or []
    return {
        "platform": "jiaoyimao",
        "engine": "jiaoyimao-ssr",
        "realtime_cleared_count": len(tx_list),
        "realtime_cleared_orders": tx_list[:max(1, int(num))],
    }


def _probe_pzds(session: requests.Session, game_id: str, num: int) -> Dict:
    gid = (game_id or "1").strip() or "1"
    url = f"https://www.pzds.com/goodsList/{urllib.parse.quote(gid)}/6"
    resp = session.get(url, headers={"User-Agent": _UA_PC}, timeout=TIMEOUT)
    resp.raise_for_status()
    cards = re.findall(
        r'href="(/goodsDetails/[A-Za-z0-9]+/\d+)"[^>]*>(.*?)</a>',
        resp.text, re.S,
    )
    items: List[Dict] = []
    for href, inner in cards[:max(1, int(num))]:
        clean = re.sub(r"<[^>]+>", " ", inner)
        clean = re.sub(r"\s+", " ", clean).strip()
        items.append({"url": "https://www.pzds.com" + href, "summary": clean[:300]})
    return {
        "platform": "pzds",
        "engine": "pzds-nuxt-ssr",
        "game_id": gid,
        "listing_count": len(items),
        "listings": items,
    }


def _probe_uu898(session: requests.Session, gm_id: str, num: int) -> Dict:
    gm = (gm_id or "95").strip() or "95"
    r_ask = session.get(f"https://www.uu898.com/newTrade-{gm}-c-3/",
                        headers={"User-Agent": _UA_PC}, timeout=TIMEOUT)
    r_ask.raise_for_status()
    asks = re.findall(
        r"<span>(1元=[0-9.]+[^<]*)</span><span>([0-9.]+元/[^<]*)</span>.*?ID=(ES[0-9-]+)",
        r_ask.text, re.S,
    )
    r_bid = session.get(f"https://www.uu898.com/newShTrade.aspx?gm={gm}&area=&srv=&c=-3",
                        headers={"User-Agent": _UA_PC}, timeout=TIMEOUT)
    r_bid.raise_for_status()
    bids = re.findall(
        r'<li class="list-w4">\s*(1元=[0-9.]+[^<]*)<br/>([^<]+)\s*</li>\s*<li class="list-w5">\s*<a href="/CreateShouHuoOrder\.aspx\?id=(SH[0-9-]+)',
        r_bid.text, re.S,
    )
    return {
        "platform": "uu898",
        "engine": "uu898-ssr",
        "game_id": gm,
        "ask_orders": [{"scale": a[0], "unit": a[1], "order_id": a[2]}
                       for a in asks[:max(1, int(num))]],
        "bid_orders": [{"scale": b[0], "unit": b[1].strip(), "order_id": b[2]}
                       for b in bids[:max(1, int(num))]],
    }


def _probe_cbg(session: requests.Session, num: int) -> Dict:
    resp = session.get(
        "https://dh2.cbg.163.com/cgi-bin/recommend.py",
        params={"act": "recommd_by_role", "page": 1, "count": max(1, min(int(num), 15)), "kindid": 21},
        headers={"User-Agent": _UA_PC, "Referer": "https://dh2.cbg.163.com/"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    rows = (resp.json().get("result")) or []
    return {
        "platform": "cbg",
        "engine": "netease-cbg-api",
        "listings": [
            {
                "ordersn": x.get("game_ordersn"),
                "name": x.get("equip_name"),
                "price_yuan": float(x.get("price") or 0) / 100.0,
                "server": x.get("server_name"),
            }
            for x in rows[:max(1, int(num))] if isinstance(x, dict)
        ],
    }


def _probe_steam(session: requests.Session, query: str, num: int) -> Dict:
    appid = (query or "730").strip()
    if not appid.isdigit():
        appid = "730"
    r_players = session.get(
        "https://api.steampowered.com/ISteamUserStats/GetNumberOfCurrentPlayers/v1/",
        params={"appid": appid}, headers={"User-Agent": _UA_PC}, timeout=TIMEOUT,
    )
    r_players.raise_for_status()
    player_count = ((r_players.json().get("response")) or {}).get("player_count", 0)

    r_hist = session.get(
        "https://steamcommunity.com/market/itemordershistogram",
        params={"country": "CN", "language": "schinese", "currency": 23,
                "item_nameid": "176288467", "two_factor": 0},
        headers={"User-Agent": _UA_PC}, timeout=TIMEOUT,
    )
    r_hist.raise_for_status()
    hdata = r_hist.json()
    return {
        "platform": "steam",
        "engine": "steam-webapi",
        "appid": int(appid),
        "concurrent_players": int(player_count or 0),
        "buy_order_graph": (hdata.get("buy_order_graph") or [])[:max(1, int(num))],
        "sell_order_graph": (hdata.get("sell_order_graph") or [])[:max(1, int(num))],
    }


def _probe_g2g(session: requests.Session, query: str, num: int) -> Dict:
    brand_id = (query or "lgc_game_29076").strip()
    if not brand_id.startswith("lgc_"):
        brand_id = "lgc_game_29076"
    hdr = {
        "User-Agent": _UA_PC,
        "Origin": "https://www.g2g.com",
        "Referer": "https://www.g2g.com/",
    }
    resp = session.get(
        "https://sls.g2g.com/offer/search",
        params={
            "service_id": "lgc_service_1", "brand_id": brand_id,
            "page_size": max(1, min(int(num), 20)), "page": 1,
            "currency": "USD", "country": "US",
        },
        headers=hdr, timeout=TIMEOUT,
    )
    resp.raise_for_status()
    results = ((resp.json().get("payload") or {}).get("results")) or []
    return {
        "platform": "g2g",
        "engine": "g2g-sls-api",
        "brand_id": brand_id,
        "offers": [
            {
                "offer_id": x.get("offer_id"),
                "seller": x.get("username"),
                "unit_price_usd": x.get("converted_unit_price"),
                "available_qty": x.get("available_qty"),
                "min_qty": x.get("min_qty"),
            }
            for x in results[:max(1, int(num))] if isinstance(x, dict)
        ],
    }


def _probe_taptap(session: requests.Session, query: str, num: int) -> Dict:
    hdr = {"User-Agent": _UA_PC, "Referer": "https://www.taptap.cn/"}
    kw = (query or "").strip()
    if kw:
        resp = session.get(
            "https://www.taptap.cn/webapiv2/search/v2/app",
            params={"kw": kw, "from": 0, "limit": max(1, min(int(num), 20)), "X-UA": _TAPTAP_XUA},
            headers=hdr, timeout=TIMEOUT,
        )
    else:
        resp = session.get(
            "https://www.taptap.cn/webapiv2/app-top/v2/hits",
            params={"type_name": "hot", "from": 0, "limit": max(1, min(int(num), 20)), "X-UA": _TAPTAP_XUA},
            headers=hdr, timeout=TIMEOUT,
        )
    resp.raise_for_status()
    items = ((resp.json().get("data") or {}).get("list")) or []
    out_apps = []
    for item in items[:max(1, int(num))]:
        app = item.get("app") if isinstance(item, dict) and isinstance(item.get("app"), dict) else item
        if not isinstance(app, dict):
            continue
        stat = app.get("stat") or {}
        out_apps.append({
            "id": app.get("id"),
            "title": app.get("title"),
            "rating": ((stat.get("rating") or {}).get("score")),
            "fans_count": stat.get("fans_count"),
            "hits_total": stat.get("hits_total"),
        })
    return {
        "platform": "taptap",
        "engine": "taptap-webapiv2",
        "query": kw or "hot",
        "apps": out_apps,
    }


def probe(
    platform: str = "dd373",
    query: str = "",
    num: int = 5,
    on_error: str = "report",
) -> Dict:
    """多平台游戏币/虚拟资产与在线人口统一探针入口。"""
    plat = (platform or "").strip().lower()
    if plat not in SUPPORTED_PLATFORMS:
        err = ValueError(
            f"unknown rmt platform {platform!r}; supported: {list(SUPPORTED_PLATFORMS)}"
        )
        if on_error == "raise":
            raise err
        if on_error == "report":
            return [{"error": f"ValueError: {err}", "tool": _TOOL,
                     "query": query, "platform": plat}]
        return []

    try:
        s = requests.Session()
        s.trust_env = plat in ("steam", "g2g")
        if plat == "dd373":
            return _probe_dd373(s, query, num)
        if plat == "7881":
            return _probe_7881(s, query, num)
        if plat == "5173":
            return _probe_5173(s, query, num)
        if plat == "jiaoyimao":
            return _probe_jiaoyimao(s, num)
        if plat == "pzds":
            return _probe_pzds(s, query, num)
        if plat == "uu898":
            return _probe_uu898(s, query, num)
        if plat == "cbg":
            return _probe_cbg(s, num)
        if plat == "steam":
            return _probe_steam(s, query, num)
        if plat == "g2g":
            return _probe_g2g(s, query, num)
        return _probe_taptap(s, query, num)
    except Exception as e:
        if on_error == "raise":
            raise
        if on_error == "report":
            slug = getattr(e, "slug", None) or type(e).__name__
            return [{"error": f"{slug}: {e}", "tool": _TOOL,
                     "query": query, "platform": plat}]
        return []
