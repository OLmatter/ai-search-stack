#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""非游戏跨领域真实物理探针引擎（v3.46.0）—— 覆盖司法强平、二手豪车/挖掘机/房产折价、大宗现货与USDT场外换汇、公共资源招投标、黑猫投诉、企业风险、蓝领薪资、猫眼票房上座率、豆瓣生存小组、清仓好价与特价机票。

设计铁律（反智子 Costly Signaling 物理探针）：
    - 严禁依赖官方宏观统计公报（T-∞），直接从造假代价高昂的微观交易/司法/强平/维权/盘口端点拉取一手底单。
    - 全部 15 个探针源（SUPPORTED_PROBES）均已于 2026-10-16 实测免登录直连（国内源默认 trust_env=False 绕过系统代理干扰，海外/加密源自动启用系统代理）。
    - 内置两项纯函数供离线审计与跨引擎调用：
      1) decode_dongchedi_pua(text)      : 懂车帝二手车 14 字符 PUA 私有区字体完整还原表
      2) compute_blackcat_signature(...) : 新浪黑猫投诉 $d6eb7ff91ee257475% SHA256 签名生成
"""
import hashlib
import html
import json
import random
import re
import string
import time
import urllib.parse
from typing import Dict, List, Optional

import requests

__all__ = [
    "probe",
    "decode_dongchedi_pua",
    "compute_blackcat_signature",
    "SUPPORTED_PROBES",
    "MacroProbeError",
]

_TOOL = "macro-probe"
TIMEOUT = 15

_UA_PC = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_UA_H5 = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
)

SUPPORTED_PROBES = (
    "jd_auction",       # 京东司法拍卖/破产资产强平 JSON API
    "ali_auction",      # 阿里司法拍卖 SSR JSON
    "used_car",         # 懂车帝全国二手豪车/新能源骨折价 JSON API + PUA 字体解码
    "used_excavator",   # 铁甲二手机械挖掘机/装载机抛售价 SSR
    "ershoufang",       # 贝壳找房全国城市二手房真实挂牌与滞销周期 SSR
    "commodity_spot",   # 生意社大宗商品现货基准价 + 新浪期货连续合约贴水
    "crypto_otc",       # OKX C2C & 币安 P2P 实时 USDT/CNY 场外换汇盘口
    "ggzy_bid",         # 全国公共资源交易平台中标公告与采购合同全文直取
    "blackcat",         # 新浪黑猫投诉实时维权/欠薪/跑路/爆雷 JSON API
    "corp_risk",        # 巨潮资讯欠薪停工诉讼公告 + 水滴信用企业存续/注销/破产股东直查
    "blue_collar",      # 新安人才网 + 国家大学生就业网 蓝领普工/保安/日结真实薪资
    "maoyan_boxoffice", # 猫眼专业版无字体加密实时票房、场均人次与上座率 API
    "douban_group",     # 豆瓣草根生存小组（失业/负债/消费降级/租房/考公）Rexxar JSON + 全站实时搜索
    "smzdm_clearance",  # 什么值得买 api.smzdm.com 全网清仓/茅台/黄金/组件好价 API
    "qunar_airfare",    # 去哪儿全国航线 50 天最低特价机票日历 JSON API
    "arbitrage_scan",   # 跨市场套利与求财智子排雷扫描器（sophon-10：跨境游戏币/法拍防坑/政采废旧暗标）
)

# 懂车帝二手车 14 字符 PUA 字体完整破译表（2026-10-16 实测 100% 还原）
DONGCHEDI_PUA_MAP = {
    "\ue439": "0",
    "\ue54c": "1",
    "\ue463": "2",
    "\ue49d": "3",
    "\ue41d": "4",
    "\ue411": "5",
    "\ue534": "6",
    "\ue3eb": "7",
    "\ue4e3": "8",
    "\ue45d": "9",
    "\ue40a": "万",
    "\ue525": "年",
    "\ue492": "公",
    "\ue4a8": "里",
}

_DONGCHEDI_BRANDS = {
    "路虎": "19",
    "保时捷": "20",
    "奔驰": "3",
    "宝马": "4",
    "奥迪": "2",
    "丰田": "5",
    "劳斯莱斯": "41",
    "兰博基尼": "42",
    "玛莎拉蒂": "45",
    "特斯拉": "63",
    "比亚迪": "16",
    "蔚来": "112",
    "小鹏": "195",
}

_CITY_KE_MAP = {
    "海口": "hk", "三亚": "sanya", "北京": "bj", "上海": "sh",
    "深圳": "sz", "广州": "gz", "成都": "cd", "杭州": "hz",
    "武汉": "wh", "南京": "nj", "重庆": "cq", "天津": "tj",
    "西安": "xa", "苏州": "su", "郑州": "zz", "长沙": "cs",
}

_COMMODITY_100PPI_MAP = {
    "多晶硅": "463",
    "碳酸锂": "1162",
    "工业级碳酸锂": "733",
    "水泥": "603",
    "螺纹钢": "927",
    "玻璃": "959",
    "炼焦煤": "1121",
    "生猪": "936",
    "铜": "524",
}

_DOUBAN_GROUP_ALIASES = {
    "失业": "691565",
    "失业大军": "691565",
    "裸辞": "676169",
    "负债": "712285",
    "逾期负债": "712285",
    "消费降级": "644670",
    "攒钱": "330706",
    "穷人攒钱": "649358",
    "躺平": "726097",
    "买房": "677158",
    "还房贷": "711976",
    "考公": "641264",
    "相亲": "345244",
    "深圳租房": "106955",
    "北京租房": "beijingzufang",
    "上海租房": "shanghaizufang",
    "广州租房": "gz_rent",
}

_BLACKCAT_SALT = "$d6eb7ff91ee257475%"


class MacroProbeError(RuntimeError):
    """非游戏跨领域物理探针异常。"""
    slug = "macro_probe_error"


def decode_dongchedi_pua(text: str) -> str:
    """将懂车帝二手车接口中的 PUA 私有区乱码还原为明文数字与单位。"""
    if not text:
        return ""
    return "".join(DONGCHEDI_PUA_MAP.get(ch, ch) for ch in str(text))


def compute_blackcat_signature(ts: str, rs: str, *extra_params: str) -> str:
    """计算新浪黑猫投诉接口 SHA256 签名：sorted([ts, rs, '$d6eb7ff91ee257475%', ...]).join('')。"""
    items = [str(ts), str(rs), _BLACKCAT_SALT] + [str(x) for x in extra_params]
    items.sort()
    raw = "".join(items).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _clean_html(raw: str) -> str:
    if not raw:
        return ""
    txt = re.sub(r"<[^>]+>", " ", str(raw))
    txt = html.unescape(txt)
    return re.sub(r"\s+", " ", txt).strip()


# ---------------------------------------------------------------------------
# 1. 司法强平与破产拍卖（京东法拍 JSON + 阿里法拍 SSR）
# ---------------------------------------------------------------------------

def _probe_jd_auction(session: requests.Session, query: str, num: int) -> Dict:
    kw = (query or "住宅").strip() or "住宅"
    body_obj = {
        "apiType": 2,
        "page": 1,
        "pageSize": max(1, min(int(num), 20)),
        "reqSource": 0,
        "keyword": kw,
    }
    resp = session.get(
        "https://api.m.jd.com/api",
        params={
            "appid": "paimai-search-soa",
            "functionId": "paimai_unifiedSearch",
            "body": json.dumps(body_obj, ensure_ascii=False),
            "loginType": 3,
        },
        headers={"User-Agent": _UA_PC, "Referer": "https://auction.jd.com/"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    datas = data.get("datas") or []
    stage_map = {1: "一拍", 2: "二拍", 4: "变卖"}
    items = []
    for d in datas[:max(1, int(num))]:
        if not isinstance(d, dict):
            continue
        cur = float(d.get("currentPrice") or 0)
        assess = float(d.get("assessmentPrice") or 0)
        disc = round((cur - assess) / assess * 100, 2) if assess > 0 else None
        items.append({
            "id": d.get("id"),
            "title": _clean_html(d.get("title") or ""),
            "province": d.get("province"),
            "city": d.get("city"),
            "current_price": cur,
            "assessment_price": assess,
            "discount_pct": disc,
            "stage": stage_map.get(d.get("paimaiTimes"), str(d.get("paimaiTimes"))),
            "bid_count": d.get("bidCount", 0),
            "court": d.get("shopName"),
            "url": f"https://paimai.jd.com/{d.get('id')}" if d.get("id") else "",
        })
    return {
        "source": "jd_auction",
        "engine": "jd-paimai-soa-json",
        "query": kw,
        "total_items": data.get("totalItem", len(items)),
        "items": items,
    }


def _probe_ali_auction(session: requests.Session, query: str, num: int) -> Dict:
    kw = (query or "住宅").strip() or "住宅"
    q_gbk = urllib.parse.quote(kw.encode("gbk", errors="ignore"))
    url = f"https://sf.taobao.com/item_list.htm?q={q_gbk}"
    resp = session.get(url, headers={"User-Agent": _UA_PC}, timeout=TIMEOUT)
    resp.raise_for_status()
    m = re.search(
        r'<script\s+id="sf-item-list-data"\s+type="text/json">\s*(\{.*?\})\s*</script>',
        resp.text, re.S,
    )
    raw_list = (json.loads(m.group(1)).get("data") or []) if m else []
    items = []
    for d in raw_list[:max(1, int(num))]:
        if not isinstance(d, dict):
            continue
        cur = float(d.get("currentPrice") or d.get("initialPrice") or 0)
        assess = float(d.get("consultPrice") or 0)
        disc = round((cur - assess) / assess * 100, 2) if assess > 0 else None
        item_url = d.get("itemUrl") or ""
        if item_url.startswith("//"):
            item_url = "https:" + item_url
        items.append({
            "id": d.get("id"),
            "title": _clean_html(d.get("title") or ""),
            "status": d.get("status"),
            "initial_price": d.get("initialPrice"),
            "current_price": cur,
            "assessment_price": assess,
            "discount_pct": disc,
            "viewer_count": d.get("viewerCount", 0),
            "bid_count": d.get("bidCount", 0),
            "apply_count": d.get("applyCount", 0),
            "url": item_url,
        })
    return {
        "source": "ali_auction",
        "engine": "ali-sf-ssr-json",
        "query": kw,
        "items": items,
    }


# ---------------------------------------------------------------------------
# 2. 二手豪车骨折价与二手工程机械（懂车帝 PUA 解码 + 铁甲二手机械）
# ---------------------------------------------------------------------------

def _probe_used_car(session: requests.Session, query: str, num: int) -> Dict:
    q = (query or "路虎").strip() or "路虎"
    brand_id = _DONGCHEDI_BRANDS.get(q, q if q.isdigit() else "19")
    resp = session.post(
        "https://www.dongchedi.com/motor/pc/sh/sh_sku_list?aid=1839&app_name=auto_web_pc",
        data={
            "sh_city_name": "全国",
            "page": 1,
            "limit": max(1, min(int(num), 20)),
            "brand": brand_id,
        },
        headers={"User-Agent": _UA_PC, "Referer": "https://www.dongchedi.com/usedcar"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = (resp.json().get("data")) or {}
    sku_list = data.get("search_sh_sku_info_list") or []
    items = []
    for x in sku_list[:max(1, int(num))]:
        if not isinstance(x, dict):
            continue
        sh_price = decode_dongchedi_pua(x.get("sh_price") or "")
        off_price = decode_dongchedi_pua(x.get("official_price") or "")
        items.append({
            "sku_id": x.get("sku_id"),
            "brand_name": x.get("brand_name"),
            "series_name": x.get("series_name"),
            "car_name": x.get("car_name"),
            "sub_title": decode_dongchedi_pua(x.get("sub_title") or ""),
            "secondhand_price": sh_price,
            "new_car_official_price": off_price,
            "city": x.get("car_source_city_name"),
            "url": f"https://www.dongchedi.com/usedcar/{x.get('sku_id')}" if x.get("sku_id") else "",
        })
    return {
        "source": "used_car",
        "engine": "dongchedi-pua-decoded",
        "query": q,
        "brand_id": brand_id,
        "total_count": data.get("total", len(items)),
        "items": items,
    }


def _probe_used_excavator(session: requests.Session, num: int) -> Dict:
    url = "https://m.tiebaobei.com/ue/nel/"
    resp = session.get(url, headers={"User-Agent": _UA_H5}, timeout=TIMEOUT)
    resp.raise_for_status()
    cards = re.findall(
        r'<a[^>]+href="([^"]*?/ue/[^"]+\.html)"[^>]*>(.*?)</a>',
        resp.text, re.S,
    )
    items = []
    for href, inner in cards:
        txt = _clean_html(inner)
        if not txt or len(txt) < 8:
            continue
        full_url = href if href.startswith("http") else ("https:" + href if href.startswith("//") else "https://m.tiebaobei.com" + href)
        items.append({"title_and_quote": txt[:200], "url": full_url})
        if len(items) >= max(1, int(num)):
            break
    return {
        "source": "used_excavator",
        "engine": "tiebaobei-ssr",
        "items": items,
    }


# ---------------------------------------------------------------------------
# 3. 全国二手房挂牌与滞销周期（贝壳找房 PC SSR）
# ---------------------------------------------------------------------------

def _probe_ershoufang(session: requests.Session, query: str, num: int) -> Dict:
    q = (query or "hk").strip()
    city = _CITY_KE_MAP.get(q, q.lower() if q.isalpha() else "hk")
    url = f"https://{city}.ke.com/ershoufang/"
    resp = session.get(url, headers={"User-Agent": _UA_PC}, timeout=TIMEOUT)
    resp.raise_for_status()
    blocks = re.findall(
        r'<li\s+class="clear">.*?</li>',
        resp.text, re.S,
    )
    items = []
    for blk in blocks[:max(1, int(num))]:
        m_title = re.search(r'class="title"[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', blk, re.S)
        m_pos = re.search(r'class="positionInfo"[^>]*>(.*?)</div>', blk, re.S)
        m_house = re.search(r'class="houseInfo"[^>]*>(.*?)</div>', blk, re.S)
        m_follow = re.search(r'class="followInfo"[^>]*>(.*?)</div>', blk, re.S)
        m_total = re.search(r'class="totalPrice[^"]*"[^>]*>(.*?)</div>', blk, re.S)
        m_unit = re.search(r'class="unitPrice"[^>]*>(.*?)</div>', blk, re.S)
        if not m_title:
            continue
        items.append({
            "title": _clean_html(m_title.group(2)),
            "community": _clean_html(m_pos.group(1)) if m_pos else "",
            "house_info": _clean_html(m_house.group(1)) if m_house else "",
            "follow_info": _clean_html(m_follow.group(1)) if m_follow else "",
            "total_price": _clean_html(m_total.group(1)) if m_total else "",
            "unit_price": _clean_html(m_unit.group(1)) if m_unit else "",
            "url": m_title.group(1),
        })
    return {
        "source": "ershoufang",
        "engine": "ke-pc-ssr",
        "city": city,
        "items": items,
    }


# ---------------------------------------------------------------------------
# 4. 大宗工业品现货与期货贴水（生意社 100ppi + 新浪期货连续）& 场外 USDT/CNY
# ---------------------------------------------------------------------------

def _probe_commodity_spot(session: requests.Session, query: str) -> Dict:
    q = (query or "多晶硅").strip() or "多晶硅"
    cid = _COMMODITY_100PPI_MAP.get(q, q if q.isdigit() else "463")
    url_spot = f"https://www.100ppi.com/rawmex/detail-{cid}.html"
    r_spot = session.get(url_spot, headers={"User-Agent": _UA_PC}, timeout=TIMEOUT)
    r_spot.raise_for_status()
    text_spot = _clean_html(r_spot.text)

    r_fut = session.get(
        "https://hq.sinajs.cn/list=nf_PS0,nf_LC0,nf_SI0,nf_RB0,nf_FG0,nf_JM0,nf_LH0,nf_CU0",
        headers={"User-Agent": _UA_PC, "Referer": "https://finance.sina.com.cn/"},
        timeout=TIMEOUT,
    )
    futures = {}
    if r_fut.status_code == 200:
        for line in r_fut.text.splitlines():
            m = re.search(r'hq_str_(nf_[A-Z0-9]+)="([^"]*)"', line)
            if m and m.group(2):
                parts = m.group(2).split(",")
                futures[m.group(1)] = {
                    "name": parts[0] if len(parts) > 0 else "",
                    "last_price": parts[8] if len(parts) > 8 else "",
                    "settle_price": parts[9] if len(parts) > 9 else "",
                    "open_interest": parts[13] if len(parts) > 13 else "",
                }
    return {
        "source": "commodity_spot",
        "engine": "100ppi-plus-sina-futures",
        "query": q,
        "commodity_id": cid,
        "spot_summary": text_spot[:600],
        "futures_continuous": futures,
        "url": url_spot,
    }


def _probe_crypto_otc(session: requests.Session, num: int) -> Dict:
    ts = str(int(time.time() * 1000))
    resp = session.get(
        "https://www.okx.com/v3/c2c/tradingOrders/books",
        params={
            "quoteCurrency": "CNY",
            "baseCurrency": "USDT",
            "side": "sell",
            "paymentMethod": "all",
            "userType": "all",
            "showTrade": "false",
            "showFollow": "false",
            "showAlreadyTraded": "false",
            "isAbleFilter": "false",
            "t": ts,
        },
        headers={
            "User-Agent": _UA_PC,
            "App-Type": "web",
            "Referer": "https://www.okx.com/p2p-markets/cny/buy-usdt",
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    sell_list = ((resp.json().get("data") or {}).get("sell")) or []
    merchants = [
        {
            "nick_name": x.get("nickName"),
            "price_cny": x.get("price"),
            "available_usdt": x.get("availableAmount"),
            "min_cny": x.get("quoteMinAmountPerOrder"),
            "max_cny": x.get("quoteMaxAmountPerOrder"),
            "completed_rate": x.get("completedRate"),
            "payment_methods": x.get("paymentMethods"),
        }
        for x in sell_list[:max(1, int(num))] if isinstance(x, dict)
    ]
    return {
        "source": "crypto_otc",
        "engine": "okx-c2c-orderbook",
        "pair": "USDT/CNY",
        "merchant_count": len(sell_list),
        "best_ask_cny": merchants[0]["price_cny"] if merchants else None,
        "merchants": merchants,
    }


# ---------------------------------------------------------------------------
# 5. 国家公共资源交易平台招投标底单（ggzy.gov.cn）与黑猫投诉、企业风险、蓝领薪资
# ---------------------------------------------------------------------------

def _probe_ggzy_bid(session: requests.Session, query: str, num: int) -> Dict:
    kw = (query or "保安").strip() or "保安"
    today = time.strftime("%Y-%m-%d")
    payload = {
        "SOURCE_TYPE": "1",
        "DEAL_TIME": "02",
        "TIMEBEGIN": "2026-07-01",
        "TIMEEND": today,
        "FINDTXT": kw,
        "PAGENUMBER": "1",
    }
    resp = session.post(
        "https://www.ggzy.gov.cn/information/pubTradingInfo/getTradList",
        data=payload,
        headers={
            "User-Agent": _UA_PC,
            "Referer": "https://www.ggzy.gov.cn/deal/dealList.html",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Pass-Token": "",
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    body = resp.json()
    data = body.get("data") or {}
    records = data.get("records") or []
    items = []
    for idx, rec in enumerate(records[:max(1, int(num))]):
        if not isinstance(rec, dict):
            continue
        rel_url = rec.get("url") or ""
        b_url = ("https://www.ggzy.gov.cn" + rel_url.replace("/html/a/", "/html/b/")) if rel_url else ""
        excerpt = ""
        if idx < 2 and b_url:
            try:
                rb = session.get(b_url, headers={"User-Agent": _UA_PC}, timeout=8)
                rb.encoding = "utf-8"
                if rb.status_code == 200:
                    excerpt = _clean_html(rb.text)[:500]
            except Exception:
                pass
        items.append({
            "id": rec.get("id"),
            "title": _clean_html(rec.get("title") or ""),
            "publish_time": rec.get("publishTime"),
            "province": rec.get("provinceText"),
            "platform": rec.get("transactionSourcesPlatformText"),
            "business_type": rec.get("businessTypeText"),
            "info_type": rec.get("informationTypeText"),
            "url": b_url,
            "body_excerpt": excerpt,
        })
    return {
        "source": "ggzy_bid",
        "engine": "ggzy-getTradList-plus-html-b",
        "query": kw,
        "total_records": data.get("total", len(items)),
        "items": items,
    }


def _probe_blackcat(session: requests.Session, query: str, num: int) -> Dict:
    kw = (query or "").strip()
    page_size = max(1, min(int(num), 20))
    hdr = {
        "User-Agent": _UA_PC,
        "Referer": "https://tousu.sina.com.cn/",
        "X-Requested-With": "XMLHttpRequest",
    }
    matched_companies = []
    lists = []

    if kw:
        r_comp = session.get(
            "https://tousu.sina.com.cn/api/company/main_search",
            params={"keywords": kw, "page_size": 5, "page": 1},
            headers=hdr,
            timeout=TIMEOUT,
        )
        if r_comp.status_code == 200:
            comp_lists = (((r_comp.json().get("result") or {}).get("data") or {}).get("lists")) or []
            for c in comp_lists[:5]:
                if isinstance(c, dict) and c.get("uid"):
                    matched_companies.append({
                        "couid": c.get("uid"),
                        "title": _clean_html(c.get("title") or ""),
                        "valid_30d": c.get("valid30d"),
                        "reply_30d": c.get("reply30d"),
                        "complete_30d": c.get("complete30d"),
                        "bankrupt_flag": c.get("bkrpt"),
                    })
            if matched_companies:
                couid = str(matched_companies[0]["couid"])
                ts = str(int(time.time() * 1000))
                rs = "".join(random.choices(string.ascii_letters + string.digits, k=16))
                sig = compute_blackcat_signature(ts, rs, couid, "1", str(page_size), "1")
                r_rc = session.get(
                    "https://tousu.sina.com.cn/api/company/received_complaints",
                    params={
                        "ts": ts, "rs": rs, "signature": sig,
                        "couid": couid, "type": 1, "page_size": page_size, "page": 1,
                    },
                    headers=hdr,
                    timeout=TIMEOUT,
                )
                if r_rc.status_code == 200:
                    lists = (((r_rc.json().get("result") or {}).get("data") or {}).get("complaints")) or []

    if not lists:
        ts = str(int(time.time() * 1000))
        rs = "".join(random.choices(string.ascii_letters + string.digits, k=16))
        sig = compute_blackcat_signature(ts, rs, "1", str(page_size), "1")
        resp = session.get(
            "https://tousu.sina.com.cn/api/index/feed",
            params={
                "ts": ts, "rs": rs, "signature": sig,
                "type": 1, "page_size": page_size, "page": 1,
            },
            headers=hdr,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        lists = (((resp.json().get("result") or {}).get("data") or {}).get("lists")) or []

    items = []
    for entry in lists:
        main = (entry.get("main") if isinstance(entry, dict) else None) or {}
        title = _clean_html(main.get("title") or "")
        summary = _clean_html(main.get("summary") or "")
        url = main.get("url") or ""
        if url.startswith("//"):
            url = "https:" + url
        items.append({
            "sn": main.get("sn"),
            "title": title,
            "summary": summary[:300],
            "target_company": main.get("cotitle"),
            "cost_rmb": main.get("cost"),
            "appeal": main.get("appeal"),
            "timestamp": main.get("timestamp"),
            "url": url,
        })
        if len(items) >= max(1, int(num)):
            break
    return {
        "source": "blackcat",
        "engine": "sina-blackcat-sha256",
        "query": kw,
        "matched_companies": matched_companies,
        "items": items,
    }


def _probe_corp_risk(session: requests.Session, query: str, num: int) -> Dict:
    kw = (query or "欠薪").strip() or "欠薪"
    r_cn = session.get(
        "http://www.cninfo.com.cn/new/fulltextSearch/full",
        params={
            "searchkey": kw,
            "sdate": "",
            "edate": "",
            "isfulltext": "false",
            "sortName": "pubdate",
            "sortType": "desc",
            "pageNum": 1,
            "pageSize": max(1, min(int(num), 20)),
        },
        headers={
            "User-Agent": _UA_PC,
            "Referer": "http://www.cninfo.com.cn/",
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=TIMEOUT,
    )
    r_cn.raise_for_status()
    cn_json = r_cn.json()
    anns = cn_json.get("announcements") or []
    filings = [
        {
            "sec_code": a.get("secCode"),
            "sec_name": _clean_html(a.get("secName") or ""),
            "title": _clean_html(a.get("announcementTitle") or ""),
            "url": f"http://static.cninfo.com.cn/{a.get('adjunctUrl')}" if a.get("adjunctUrl") else "",
        }
        for a in anns[:max(1, int(num))] if isinstance(a, dict)
    ]

    shuidi_companies = []
    try:
        r_sd = session.get(
            f"https://shuidi.cn/b-search?key={urllib.parse.quote(kw)}",
            headers={"User-Agent": _UA_PC},
            timeout=10,
        )
        if r_sd.status_code == 200:
            blocks = re.split(r'href="(/company-[a-f0-9]+\.html[^"]*)"', r_sd.text)
            for i in range(1, min(len(blocks), int(num) * 2 + 1), 2):
                href = blocks[i]
                prev_chunk = _clean_html(blocks[i - 1][-600:])
                shuidi_companies.append({
                    "summary": prev_chunk[-260:],
                    "url": "https://shuidi.cn" + href,
                })
    except Exception:
        pass

    return {
        "source": "corp_risk",
        "engine": "cninfo-plus-shuidi",
        "query": kw,
        "total_announcements": cn_json.get("totalAnnouncement", len(filings)),
        "filings": filings,
        "shuidi_credit_records": shuidi_companies[:max(1, int(num))],
    }


def _probe_blue_collar(session: requests.Session, query: str, num: int) -> Dict:
    kw = (query or "普工").strip() or "普工"
    url = f"https://search.goodjobs.cn/index.php?keyword={urllib.parse.quote(kw)}"
    resp = session.get(url, headers={"User-Agent": _UA_PC}, timeout=TIMEOUT)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    parts = re.split(
        r'<a[^>]+href="(https://ehr\.goodjobs\.cn/show\.php\?jobID=\d+[^"]*)"[^>]*>',
        resp.text,
    )
    jobs = []
    for i in range(1, len(parts), 2):
        href = parts[i]
        chunk = _clean_html(parts[i + 1][:900])
        jobs.append({
            "summary": chunk[:240],
            "url": href,
        })
        if len(jobs) >= max(1, int(num)):
            break
    return {
        "source": "blue_collar",
        "engine": "goodjobs-ssr",
        "query": kw,
        "jobs": jobs,
    }


# ---------------------------------------------------------------------------
# 6. 线下消费人流（猫眼票房/场均人次）、豆瓣草根小组、值得买清仓价、去哪儿机票
# ---------------------------------------------------------------------------

def _probe_maoyan_boxoffice(session: requests.Session, query: str, num: int) -> Dict:
    params = {}
    q = (query or "").strip().replace("-", "")
    if len(q) == 8 and q.isdigit():
        params["showDate"] = q
    resp = session.get(
        "https://piaofang.maoyan.com/dashboard-ajax/movie",
        params=params,
        headers={
            "User-Agent": _UA_PC,
            "Referer": "https://piaofang.maoyan.com/dashboard/movie",
            "Accept": "application/json, text/plain, */*",
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    movie_list_obj = (resp.json().get("movieList")) or {}
    nation = movie_list_obj.get("nationBoxInfo") or {}
    split_unit = nation.get("nationBoxSplitUnit") or {}
    raw_movies = movie_list_obj.get("list") or []
    movies = []
    for m in raw_movies[:max(1, int(num))]:
        if not isinstance(m, dict):
            continue
        info = m.get("movieInfo") or {}
        box_unit = m.get("boxSplitUnit") or {}
        movies.append({
            "movie_id": info.get("movieId"),
            "movie_name": info.get("movieName"),
            "release_info": info.get("releaseInfo"),
            "box_office": f"{box_unit.get('num', '')}{box_unit.get('unit', '')}",
            "box_rate": m.get("boxRate"),
            "sum_box_desc": m.get("sumBoxDesc"),
            "show_count": m.get("showCount"),
            "avg_people_per_show": m.get("avgShowView"),
            "seat_occupancy": m.get("avgSeatView"),
        })
    return {
        "source": "maoyan_boxoffice",
        "engine": "maoyan-dashboard-movie-json",
        "nation_box_office": f"{split_unit.get('num', '')}{split_unit.get('unit', '')}",
        "nation_total_shows": nation.get("showCountDesc"),
        "nation_total_viewers": nation.get("viewCountDesc"),
        "movies": movies,
    }


def _probe_douban_group(session: requests.Session, query: str, num: int) -> Dict:
    q = (query or "失业").strip() or "失业"
    gid = _DOUBAN_GROUP_ALIASES.get(q) or (q if q.isdigit() else None)
    if gid:
        url = f"https://m.douban.com/rexxar/api/v2/group/{gid}/topics"
        resp = session.get(
            url,
            params={"start": 0, "count": max(1, min(int(num), 30))},
            headers={"User-Agent": _UA_H5, "Referer": "https://m.douban.com/group/"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        topics = (resp.json().get("topics")) or []
        return {
            "source": "douban_group",
            "engine": "douban-rexxar-group-json",
            "group_id": gid,
            "query": q,
            "topics": [
                {
                    "id": t.get("id"),
                    "title": t.get("title"),
                    "author": (t.get("author") or {}).get("name"),
                    "comments_count": t.get("comments_count"),
                    "created": t.get("create_time") or t.get("updated"),
                    "url": t.get("url") or f"https://www.douban.com/group/topic/{t.get('id')}/",
                }
                for t in topics[:max(1, int(num))] if isinstance(t, dict)
            ],
        }

    # 全站跨小组实时帖搜索（PC UA）
    resp = session.get(
        "https://www.douban.com/group/search",
        params={"cat": 1013, "q": q, "sort": "time"},
        headers={"User-Agent": _UA_PC, "Referer": "https://www.douban.com/group/"},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    rows = re.findall(
        r'<a[^>]+href="(https://www\.douban\.com/group/topic/\d+/)"[^>]+title="([^"]+)"',
        resp.text,
    )
    return {
        "source": "douban_group",
        "engine": "douban-cross-group-search",
        "query": q,
        "topics": [
            {"title": _clean_html(title), "url": href}
            for href, title in rows[:max(1, int(num))]
        ],
    }


def _probe_smzdm_clearance(session: requests.Session, query: str, num: int) -> Dict:
    kw = (query or "飞天茅台").strip() or "飞天茅台"
    resp = session.get(
        "https://api.smzdm.com/v1/list",
        params={
            "keyword": kw,
            "type": "good_price",
            "offset": 0,
            "limit": max(1, min(int(num), 20)),
            "sort": "time",
        },
        headers={"User-Agent": _UA_H5},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = (resp.json().get("data")) or {}
    rows = data.get("rows") or []
    return {
        "source": "smzdm_clearance",
        "engine": "smzdm-api-v1",
        "query": kw,
        "total_num": data.get("total_num", len(rows)),
        "items": [
            {
                "title": r.get("article_title"),
                "price": r.get("article_price"),
                "mall": r.get("article_mall"),
                "date": r.get("article_format_date"),
                "comments": r.get("article_comment"),
                "worthy": r.get("article_worthy"),
                "unworthy": r.get("article_unworthy"),
                "url": r.get("article_url"),
            }
            for r in rows[:max(1, int(num))] if isinstance(r, dict)
        ],
    }


def _probe_qunar_airfare(session: requests.Session, query: str, num: int) -> Dict:
    q = (query or "上海-深圳").strip() or "上海-深圳"
    parts = [p.strip() for p in re.split(r"[-—>to\s]+", q) if p.strip()]
    dep = parts[0] if len(parts) >= 1 else "上海"
    arr = parts[1] if len(parts) >= 2 else "深圳"
    resp = session.get(
        "https://gw.flight.qunar.com/api/f/priceCalendar",
        params={"dep": dep, "arr": arr},
        headers={
            "User-Agent": _UA_PC,
            "Referer": "https://flight.qunar.com/",
            "Accept": "application/json, text/plain, */*",
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    gflights = ((resp.json().get("data") or {}).get("gflights")) or []
    priced = [x for x in gflights if isinstance(x, dict) and x.get("price")]
    priced_sorted = sorted(priced, key=lambda x: float(x.get("price") or 999999))
    return {
        "source": "qunar_airfare",
        "engine": "qunar-gw-priceCalendar",
        "dep": dep,
        "arr": arr,
        "priced_days_count": len(priced),
        "lowest_flight": priced_sorted[0] if priced_sorted else None,
        "calendar_sample": priced[:max(1, int(num))],
    }


def probe(
    source: str = "jd_auction",
    query: str = "",
    num: int = 5,
    on_error: str = "report",
) -> Dict:
    """非游戏跨领域真实物理探针统一入口。"""
    src = (source or "").strip().lower()
    if src not in SUPPORTED_PROBES:
        err = ValueError(
            f"unknown physical probe source {source!r}; supported: {list(SUPPORTED_PROBES)}"
        )
        if on_error == "raise":
            raise err
        if on_error == "report":
            return [{"error": f"ValueError: {err}", "tool": _TOOL,
                     "query": query, "source": src}]
        return []

    try:
        s = requests.Session()
        s.trust_env = src in ("crypto_otc",)
        if src == "jd_auction":
            return _probe_jd_auction(s, query, num)
        if src == "ali_auction":
            return _probe_ali_auction(s, query, num)
        if src == "used_car":
            return _probe_used_car(s, query, num)
        if src == "used_excavator":
            return _probe_used_excavator(s, num)
        if src == "ershoufang":
            return _probe_ershoufang(s, query, num)
        if src == "commodity_spot":
            return _probe_commodity_spot(s, query)
        if src == "crypto_otc":
            return _probe_crypto_otc(s, num)
        if src == "ggzy_bid":
            return _probe_ggzy_bid(s, query, num)
        if src == "blackcat":
            return _probe_blackcat(s, query, num)
        if src == "corp_risk":
            return _probe_corp_risk(s, query, num)
        if src == "blue_collar":
            return _probe_blue_collar(s, query, num)
        if src == "maoyan_boxoffice":
            return _probe_maoyan_boxoffice(s, query, num)
        if src == "douban_group":
            return _probe_douban_group(s, query, num)
        if src == "smzdm_clearance":
            return _probe_smzdm_clearance(s, query, num)
        if src == "arbitrage_scan":
            import arbitrage_scanner as _arb
            parts = [p.strip() for p in (query or "all").split(":", 1)]
            mode_arg = parts[0] if parts and parts[0] else "all"
            kw_arg = parts[1] if len(parts) > 1 else ""
            if mode_arg not in _arb.SUPPORTED_SCAN_MODES:
                kw_arg = mode_arg
                mode_arg = "all"
            return _arb.scan_arbitrage(mode=mode_arg, keyword=kw_arg, num=num)
        return _probe_qunar_airfare(s, query, num)
    except Exception as e:
        if on_error == "raise":
            raise
        if on_error == "report":
            slug = getattr(e, "slug", None) or type(e).__name__
            return [{"error": f"{slug}: {e}", "tool": _TOOL,
                     "query": query, "source": src}]
        return []
