# -*- coding: utf-8 -*-
"""
arbitrage_scanner.py — 跨市场套利与九大求财算子排雷扫描引擎 (v3.46.0)
=============================================================================
基于 `sophon-10-wealth-arbitrage-sophon`（求财与套利欺诈智子去魅卡）构建：
1. SOPHON_10_OPERATORS    : 完整固化九大求财算子（A1跨境无货源搬单、A2 Steam双轨延时挂刀、A3退坑号扒皮拆骨、
                            B1法拍车与机床五雷排爆、B2工业厂房土增税与历史欠税剥离、B3政采报废电梯挂靠拆解、
                            C1倒闭设备背靠背双头锁价防跳单、C2法拍房405条破假租约与单方水电报停腾退、
                            C3出海Stripe EFW秒退防封与场外OTC零冻卡）。
2. evaluate_operator      : 纯函数精算器，输入具体标的与隐性摩擦参数，直接返回扣尽全部暗雷后的净现金流与击球裁定。
3. scan_digital_spreads   : 对撞海外 G2G 实结 converted 单价 vs 国内 DD373/UU898 收货价(Bid)/零售价(Ask) + OKX USDT/CNY 汇率。
4. scan_physical_auctions : 对撞京东/阿里司法拍卖二拍/变卖价 vs 什么值得买百亿补贴清仓底价（刺穿注水评估价）。
5. scan_ggzy_scrap        : 扫描全国公共资源交易平台（ggzy_bid）废旧物资/报废电梯/高压柜底单 + 沪铜期货锚点。
6. scan_arbitrage         : 统一入口（支持 mode="all" | "digital" | "physical" | "ggzy_scrap" | "operators"）。
"""
from __future__ import annotations

import json
import math
import re
import sys
import pathlib
from typing import Any, Dict

_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import macro_probe_engine as _macro
import rmt_engine as _rmt

SUPPORTED_SCAN_MODES = ("all", "digital", "physical", "ggzy_scrap", "operators", "blind_discovery")

SOPHON_10_OPERATORS: Dict[str, Dict[str, Any]] = {
    "A1_g2g_dropship": {
        "name": "跨境无货源搬单全摩擦算子 (DD373/UU898 -> G2G/Eldorado)",
        "formula": "ROI_net = [P_G2G_converted * FX_USDT * (1 - f_rank) * (1 - f_payout) * (1 - p_cb) - C_DD373 / (1 - tau_AH)] / [C_DD373 / (1 - tau_AH)] > 20%",
        "insider_playbook": [
            "必须读取 G2G 接口 converted_unit_price 字段（展示价 unit_price 含 8%-11% 内部汇损）",
            "G2G 6阶等级佣金墙：Normal(9.99%) -> Legendary(Lv140+, 4.99%)；提现走自动生成的 Payoneer Lite($50起提, 姓名须100%字节级一致) 或 TripleA USDT($11起提)",
            "商品页首行写死：'Please do not return divine if anyone ask you in game, we only communicate in G2G order chat' 封死国内散户切小号回马枪骗退",
            "当面交易强制买家塞垃圾黄装 ('Put any rare item in trade') 绕过数据库单向赠金封号触发器；拍卖行用 5-10 件冷门紫装带零头分拆并转嫁 5% 税",
            "大额单 OBS 一镜到底录屏五步法：刷新 Order ID -> 右键买家 #BattleTag -> 拍下交易前余额与对方黄装及 Trade Complete -> 聊天框敲 /time -> 直传后台",
        ],
    },
    "A2_steam_knife": {
        "name": "Steam 双轨挂刀与延时防冻结算子 (TF2 0CD + CS2 7天CD)",
        "formula": "R_eff = P_BUFF / [0.869565 * P_Steam * (1 - z * sigma_daily * sqrt(T_lock))]",
        "insider_playbook": [
            "2025年10月起 DOTA2 全面加 7天CD；0CD 秒到账唯一主力为 TF2 曼恩箱钥匙 (appid=440 multisell 批量接口，约 82.5 折，日销 5.5 万把)",
            "7天CD 通道走 CS2 高换手武器箱（梦魇/变革箱，日销 7-11 万个）或 55-70 折特定磨损皮肤，必须在大促前 15-20 天提前建仓",
            "破除 Pending Balance (24-72h 待处理余额冻结)：严禁直接砸最高求购单 1 秒成交，必须挂比最低卖单高 1%-2% 让饰品自然停留 15-30 分钟被正常玩家买走",
            "余额安全变现：严禁碰闲鱼 74 折黑卡赃款或跨区送礼超消费额 1.5 倍（商业红信）；改走求购 TF2 钥匙回 BUFF 提现或官网买 Steam Deck OLED 93 折变现",
        ],
    },
    "A3_account_strip": {
        "name": "死鱼退坑号扒皮拆骨算子 (藏宝阁拆角色 vs 非官方 T+0 闪电扒皮)",
        "formula": "Pi_CBG = V_hull*(1-5%) + sum(V_parts*(1-5%)) + 0.95*V_MHB - P_bundle - C_point_14d > 15% ; Non-CBG: V_liquid*(1-f) >= 0.85*P_acct",
        "insider_playbook": [
            "警惕 2026 交易猫'小米/渠道转移号假报警封号拒赔'杀猪盘：原号主次日去派出所报假警称被盗，凭回执让渠道客服永久冻结新号，平台以'封号不属于找回'拒赔",
            "网易藏宝阁六步拆骨：只收直接剥离入自己三无纯净母号的退坑整号 -> 第1秒清仓行囊/牧场/副本积分盲盒 -> 不绑定全红宠/灵饰当天单拆上架回本50% -> 第1天同步点贸易车队总管14天登记倒计时卖空壳",
            "非藏宝阁平台执行'黄金30分钟 T+0 闪电扒皮术'：对绑定战力估值权重压至 <=15%，交接 30 分钟内洗空全部可交易通货收回 85%-120% 购号本金，零过夜敞口",
        ],
    },
    "B1_judicial_movable": {
        "name": "司法法拍车与工业机床五雷排爆算子",
        "formula": "V_net = V_cash_scrap - [P_bid*(1+r_plat) + min(D_park*50, 5000_law_cap) + C_key_tow + C_core_missing + C_traffic_agent]",
        "insider_playbook": [
            "砍掉 80% 天价扣押停车费（如深圳粤BBZ067车价1.17万背1.05万停车费）：拍前用街景查涉案停车场电话报车牌核实入场日；拍后援引《行政强制法》第26条剥离交警查扣期费用 + 最高院《网拍规定》第13条（未明确披露金额属瑕疵）向执行局提异议砍至 2,000-5,000 元包干",
            "无钥匙豪车死锁：无行驶证 4S 店不给订德国钥匙(5000元) <-> 无钥匙无法开车去车管所验车补行驶证，须预算 1,500 元板车往返拖车验车费；无法 12123 直接异地提档；锁定违章预留 1,200-3,500 元黄牛解档",
            "现场看样五必查：①激光机拿内六角扳手开恒温柜核对 IPG/锐科激光源 S/N 码与黄色 QBH 光纤有无剪断（占价值65%）；②CNC 自带 24V 锂电逆变器点亮面板查'融资租赁分期锁机密码'与黄色 FANUC 模块；③豪车拍底盘三元催化焊缝并拔机油尺防泡水乳化与白糖抱瓦；④汽修厂留置权车（《民法典》456条）与 Apple ID 锁机一律 PASS",
        ],
    },
    "B2_industrial_property_tax": {
        "name": "工业厂房/企业商铺土增税与历史欠税剥离算子",
        "formula": "Tax_corp = T_LVAT(30%-60%) + T_VAT_Deed(8.6%) + T_Allocated_Land(40%) + T_Historical_Arrears*(1 - I_SupremeCourt_No59)",
        "insider_playbook": [
            "企业产权房拿地原值极低且无建安发票，查账征收土地增值税高达 30%-60%（吃掉成交价 25%-45%），拍前必去税务局用产权证号查历史原值与能否核定征收",
            "用最高院再审标杆判例（2022）最高法民再59号 与《网拍规定》第30条剥离数百万历史欠税：主张停产企业拖欠10年的房产税/城镇土地使用税属历史保有期欠税，与本次权属变更无关，要求法院从执行款扣划或函告税务局'先证后税'脱钩过户",
            "领裁定书当场提交《延期分配执行款申请书》，破除部分法院'7天内未交完税凭证即分配执行款不再退垫税'的霸王条款",
        ],
    },
    "B3_ggzy_scrap_elevator": {
        "name": "政采报废电梯与废旧物资挂靠拆解算子 (ggzy_bid)",
        "formula": "V_net = sum(W_i*(1 - delta_scale - delta_imp)*P_cash) - P_bid - C_hang(500-800/unit) - C_ins(400/worker) - C_no_hot_work - C_clean",
        "insider_playbook": [
            "黄金击球区：专打医院/国企挂牌 <=8,500元/台 的成批报废电梯（如东莞大朗医院10台挂7,800元/台 vs 铜陵实盘成交18,602元/台，单台拆铜+配重铁净赚5,000-8,500元/台）及账面净值 0-1万元 的矿企含铜高压开关柜",
            "特种设备资质借章挂靠：找本地中小型电梯维保公司签内部承包背靠背协议，小标(<10万)借章费 500-800元/台（或整单2,000-5,000元包干含施工告知书），大标 3%-6%，必买 >=150万 高空作业意外险",
            "严查标书'禁止厂区动火气割'条款（如江南造船规定，禁气割则须雇50吨汽车吊+低平板车整机外运，成本暴增2万+）；防地磅 500L水箱放水+车底对称双工具箱藏铁砂+15吨以上非线性遥控，强制厂外3公里公用磅复磅、水箱铅封、带强磁铁与锉刀看货",
        ],
    },
    "C1_anti_circumvention_broker": {
        "name": "倒闭设备/废料居间「背靠背双头锁价防跳单」算子",
        "formula": "B_dealer_max - A_seller_lock >= max(3000, 0.15*A_seller_lock) AND D_option <= 0.02*A_seller_lock AND Direct_Contact(S, B) == 0",
        "insider_playbook": [
            "废除口头事后茶水费：掏 500-1,000 元小额定金与急退租（距封铺剩3天）老板签 48h《独家包场处置定金协议》锁死买断底价 A（写明乙方有权指定第三方拉货、甲方漏底价扣30%尾款），转头向下家报一口价 B 吃差价 B - A",
            "看货现场'股东伪装术'：提前拿钥匙支开原老板，独自开门带下家看货自称'跟朋友合伙开的店清场'（原老板在场则演双簧称下家是自己雇的搬运工头，严禁递烟递名片）",
            "发定位前先收下家 200-500 元看货诚意押金，并签电子《项目信息咨询服务合同》（绝不签单纯《居间合同》，信息咨询合同只要交付了独家闭店情报即须付费，彻底封死跳单抗辩）",
        ],
    },
    "C2_judicial_eviction": {
        "name": "法拍房破除20年假租约与单方水电报停强制腾退算子",
        "formula": "Fake_Lease_Invalid <=> (T_bank_flow > T_mortgage) OR (Bank_Flow == Empty) OR (Lease_Type == Debt_Offset)",
        "insider_playbook": [
            "三刀击穿20年恶意假租约：①查册核对首次抵押登记日 T_mortgage（《民法典》405条抵押在先必破租赁）；②最高法明确'以租抵债'不适用买卖不破租赁，且责令7日内交当年100万银行转账底单+租赁备案+完税证明；③拍出《刑法》307条虚假诉讼罪威慑挂名亲友假租客，48h内崩溃弃权",
            "单方强制过户水电气+合法报停检修：凭《执行裁定书》单方办新房本当天，持新房本+裁定书去供电局/水司/燃气柜台走'司法转移单方强制过户'，立刻以唯一合法产权人身份申请'室内线路/燃气软管老化隐患暂停供电供气检修'（燃气2小时上门关阀贴封条，无新房主身份证绝不复通）",
            "20分钟调虎离山换锁+双机位4K公证搬家：发EMS限期3日腾房函，趁早7:30买菜遛弯空城窗口，备案锁匠3分钟换超C级霸王锁反锁驻守 + 2台4K执法记录仪一镜到底唱名清点装袋（证件药品单独密封特写），货拉拉运往城郊300元月租平房仓并发彩信告知；110到场隔门亮新房本+裁定书+全程录像，先断电威慑再给3,000-5,000元48h搬空补贴",
        ],
    },
    "C3_stripe_and_otc_safety": {
        "name": "出海 Stripe 防封号与场外 OTC 零冻卡算子",
        "formula": "Stripe_Safe <=> R_dispute < 0.5% AND EFW_Auto_Refund == True ; P_freeze(Kraken -> OCBC/ZA/iFast -> SameName_Alipay) == 0",
        "insider_playbook": [
            "Stripe 破 0.75% 拒付率即封号冻120天（胜诉仍计入分子且倒扣$15+30% Smart Disputes抽成）：后端监听 radar.early_fraud_warning.created 毫秒级自动全额原路退款（宁亏$19绝不变正式Dispute）+ 网页显眼放一键自助秒退 + Radar Score>40 强制3DS责任转移 + 备好 Paddle/Polar.sh MoR 切换层",
            "100% 物理零冻卡黄金通道：USDT 提至 Kraken 海妖/持牌所换 USD -> 同名电汇至英国 iFast / 新加坡 OCBC / 香港众安 ZA / 澳门蚂蚁银行 -> Wise/熊猫速汇同名结汇回大陆支付宝（或绑 OneKey/RedotPay 海外U卡消费），与国内电诈人民币池物理绝缘",
            "国内 C2C 六条保命红线：①绝不卖第一页高价收U商（往下翻选低1-2分老商）；②只选入驻>=2年且买卖单笔数均衡(35%-65%)的神盾大商（拉黑只收不出的洗钱水房）；③强制本人实名+支付宝余利宝/小荷包 T+1 沉淀资金验资；④用平时0余额独立地方城商行卡专卡收款；⑤只在工作日白天 09:30-16:30 出金；⑥到账后严禁5分钟内跨行秒转主力储蓄卡（转余利宝/还信用卡/ATM取现断链）",
        ],
    },
}

SOPHON_10_RULES = {
    "card_id": "sophon-10-wealth-arbitrage-sophon",
    "operator_count": len(SOPHON_10_OPERATORS),
    "physical_formula": "P_auction < 0.75 * min(P_smzdm_new, P_scrap_metal, P_dealer_bid) AND bids <= 1",
    "digital_formula": "Net_Spread = (P_G2G_USD * FX_USDT * 0.90 - P_Domestic_CNY) / P_Domestic_CNY > 20% (Zero-Inventory Drop-Shipping)",
    "four_deadly_traps": [
        "TRAP_1_INFLATED_COURT_APPRAISAL: 法院评估价常按3-5年前发票原值注水（如二手RTX3060主机变卖5160元 > 值得买全新RTX3070整机3499元；淘汰P型光伏板评估0.76元/W > 闲鱼统货0.15元/W）",
        "TRAP_2_NEW_GAME_STUDIO_SHILL: 新游开服买量吹嘘日入千金（如剑侠世界4开服次日翠玉日内闪崩-26.2%、吧主卸载退坑；POE2普通赛季零售直搬G2G扣10%通道费后净亏-3%）",
        "TRAP_3_HEAVY_ASSET_HOARDING: 逆周期重资产租大仓囤二手餐饮设备（关店潮远超开店潮导致仓库爆满、回收商批量倒闭，冷柜只能按0.6元/斤废铁称重）",
        "TRAP_4_BLIND_AUCTION_AND_DEBT_VULTURES: 不尽调盲拍法拍房/车遭原房主死赖不走或背89%天价停车费/激光源被拆，或轻信收5%-10%高额服务费的黑心法务公司",
    ],
    "operators": SOPHON_10_OPERATORS,
}


def evaluate_operator(op_id: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """根据九大求财算子对具体项目参数做精确净利与风控验算。"""
    p = params or {}
    if op_id == "A1_g2g_dropship":
        g2g_conv = float(p.get("g2g_converted_usd", 1.289))
        fx = float(p.get("fx_usdt", 6.78))
        f_rank = float(p.get("f_rank", 0.0499))
        f_payout = float(p.get("f_payout", 0.015))
        dom_cny = float(p.get("domestic_cny", 5.694))
        ah_tax = float(p.get("ah_tax", 0.0))
        eff_cost = dom_cny / max(0.01, (1.0 - ah_tax))
        net_rev = g2g_conv * fx * (1.0 - f_rank) * (1.0 - f_payout)
        roi = round((net_rev / eff_cost - 1.0) * 100.0, 2)
        return {
            "operator": op_id,
            "net_revenue_cny": round(net_rev, 4),
            "effective_cost_cny": round(eff_cost, 4),
            "net_roi_pct": roi,
            "verdict": "ACTIONABLE_ARBITRAGE" if roi >= 20.0 else "REJECT_BELOW_SAFETY_MARGIN",
        }
    if op_id == "B3_ggzy_scrap_elevator":
        units = int(p.get("units", 10))
        bid_total = float(p.get("bid_total_cny", 78000.0))
        scrap_per_unit = float(p.get("scrap_value_per_unit_cny", 18500.0))
        hang_fee_per_unit = float(p.get("hang_fee_per_unit_cny", 600.0))
        demolition_per_unit = float(p.get("demolition_per_unit_cny", 2200.0))
        hot_work_banned = bool(p.get("hot_work_banned", False))
        crane_penalty = 25000.0 if hot_work_banned else 0.0
        gross = units * scrap_per_unit * 0.95
        total_cost = bid_total + units * (hang_fee_per_unit + demolition_per_unit) + crane_penalty
        net_profit = round(gross - total_cost, 2)
        return {
            "operator": op_id,
            "gross_scrap_cny": round(gross, 2),
            "total_all_in_cost_cny": round(total_cost, 2),
            "net_profit_cny": net_profit,
            "net_profit_per_unit_cny": round(net_profit / max(1, units), 2),
            "verdict": "HIGH_MARGIN_STRIKE" if net_profit / max(1.0, total_cost) >= 0.25 else "PASS_HIGH_FRICTION",
        }
    if op_id == "C1_anti_circumvention_broker":
        seller_a = float(p.get("seller_lock_a", 50000.0))
        dealer_b = float(p.get("dealer_max_b", 62000.0))
        deposit = float(p.get("option_deposit", 800.0))
        spread = round(dealer_b - seller_a, 2)
        ok = spread >= max(3000.0, 0.15 * seller_a) and deposit <= 0.02 * seller_a
        return {
            "operator": op_id,
            "back_to_back_spread_cny": spread,
            "option_deposit_ratio": round(deposit / max(1.0, seller_a), 4),
            "verdict": "EXECUTE_48H_EXCLUSIVE_LOCK" if ok else "REJECT_THIN_SPREAD_OR_HIGH_DEPOSIT",
        }
    raise ValueError(f"Unknown operator id: {op_id!r}. Available: {list(SOPHON_10_OPERATORS)}")


def _extract_first_float(text: str) -> float | None:
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", str(text).replace(",", ""))
    return float(m.group(1)) if m else None


def get_live_usdt_cny(default_fx: float = 6.78) -> float:
    """从 OKX C2C 探针获取实时 USDT/CNY 汇率基准。"""
    try:
        res = _macro.probe("crypto_otc", "", num=3, on_error="ignore")
        if isinstance(res, dict):
            p = res.get("best_price_cny")
            if p and 6.0 <= float(p) <= 8.5:
                return float(p)
    except Exception:
        pass
    return default_fx


def scan_digital_spreads(game: str = "Path of Exile 2", num: int = 5) -> dict[str, Any]:
    """扫描跨境/跨平台数字资产价差（G2G USD vs 国内 RMT + 实测基准矩阵）。"""
    fx = get_live_usdt_cny()
    live_g2g = {}
    live_dom = {}
    try:
        r = _rmt.probe("g2g", game, num=num, on_error="ignore")
        if isinstance(r, dict):
            live_g2g = r
    except Exception:
        pass
    try:
        r2 = _rmt.probe("dd373", game, num=num, on_error="ignore")
        if isinstance(r2, dict):
            live_dom = r2
    except Exception:
        pass

    verified_matrix = [
        {
            "game": "冒险岛怀旧服 (MapleStory CW - 蓝蜗牛 [CN])",
            "unit": "100万金 (1,000K Mesos)",
            "domestic_source": "DD373 Ask DB20261016180852-58288",
            "domestic_cny": 5.694,
            "overseas_source": "G2G CNLTeam G1791367715725NR",
            "g2g_usd": 1.289,
            "mode": "同服无货源直搬 (Put rare item + Order Chat lock)",
        },
        {
            "game": "暗黑破坏神4 (Diablo 4 S15 赛季普通)",
            "unit": "1,000亿金 (100B Gold)",
            "domestic_source": "DD373 Dealer Bid SH20260914234549-51004 (收货价)",
            "domestic_cny": 1.210,
            "overseas_source": "G2G Thanku G1789356439738EW",
            "g2g_usd": 0.300,
            "mode": "国内挂收货单(Bid) -> 死士号转公会仓 -> 海外G2G零售(Ask)",
        },
        {
            "game": "永恒之塔2国际服 (Aion 2 亚服 Siel/Triniel)",
            "unit": "100万基纳 (1M Kinah)",
            "domestic_source": "DD373 Dealer Bid SH20261002150327-10001 (收货价)",
            "domestic_cny": 4.000,
            "overseas_source": "G2G Thanku G1790850834734RZ",
            "g2g_usd": 0.800,
            "mode": "国内挂收货单(Bid) -> 海外G2G零售(Ask)",
        },
        {
            "game": "流放之路2国际服 (POE2 闪回专家 HC)",
            "unit": "100 Divine Orbs (神圣石)",
            "domestic_source": "DD373 Ask DB20261015165538-18890",
            "domestic_cny": 13.390,
            "overseas_source": "G2G CNLTeam G1788460432277EN",
            "g2g_usd": 2.4856,
            "mode": "专家服高溢价搬单 (converted_unit_price 已折算)",
        },
        {
            "game": "流放之路2国际服 (POE2 闪回普通 Softcore)",
            "unit": "1,000 Divine Orbs (神圣石)",
            "domestic_source": "DD373 Ask DB20261016174842-73447",
            "domestic_cny": 33.989,
            "overseas_source": "G2G Thanku G1788232531146XR",
            "g2g_usd": 5.400,
            "mode": "普通服零售直搬（反面教材：扣费后倒亏）",
        },
    ]

    evaluated = []
    for item in verified_matrix:
        g2g_cny = round(item["g2g_usd"] * fx, 3)
        implied_fx = round(item["domestic_cny"] / item["g2g_usd"], 2)
        gross_pct = round((g2g_cny / item["domestic_cny"] - 1.0) * 100.0, 2)
        net_pct = round(((g2g_cny * 0.90) / item["domestic_cny"] - 1.0) * 100.0, 2)
        verdict = (
            "ACTIONABLE_ARBITRAGE"
            if net_pct >= 15.0
            else ("MARGINAL_SPREAD" if net_pct > 0 else "FEE_TRAP_NET_LOSS")
        )
        evaluated.append({
            **item,
            "usdt_cny_fx": fx,
            "g2g_equiv_cny": g2g_cny,
            "implied_usd_cny": implied_fx,
            "gross_spread_pct": gross_pct,
            "net_spread_after_10pct_fee": net_pct,
            "verdict": verdict,
        })

    return {
        "usdt_cny_fx": fx,
        "query_game": game,
        "live_g2g_offers": (live_g2g.get("offers") or [])[:3],
        "live_domestic_orders": (live_dom.get("sell_orders") or [])[:3],
        "cross_border_spread_table": evaluated,
    }


def scan_physical_auctions(keyword: str = "茅台", num: int = 5) -> dict[str, Any]:
    """扫描司法拍卖（京东/阿里）vs 什么值得买全网清仓底价，自动识别真套利与注水评估陷阱。"""
    auctions: list[dict[str, Any]] = []
    clearances: list[dict[str, Any]] = []
    try:
        res_a = _macro.probe("jd_auction", keyword, num=num, on_error="ignore")
        if isinstance(res_a, dict):
            auctions = res_a.get("items") or []
    except Exception:
        pass
    try:
        res_c = _macro.probe("smzdm_clearance", keyword, num=num, on_error="ignore")
        if isinstance(res_c, dict):
            clearances = res_c.get("items") or []
    except Exception:
        pass

    clearance_prices = []
    for c in clearances:
        p = _extract_first_float(str(c.get("price", "")))
        if p and p > 0:
            clearance_prices.append(p)
    min_clearance = min(clearance_prices) if clearance_prices else None

    audited_auctions = []
    for a in auctions:
        cur_p = a.get("current_price")
        ass_p = a.get("assessment_price")
        bids = a.get("bid_count") or 0
        disc = a.get("discount_vs_assessment_pct") or a.get("discount_pct")
        status_flag = "NEEDS_MANUAL_UNIT_CHECK"
        if cur_p and ass_p and float(ass_p) > 0:
            ratio = float(cur_p) / float(ass_p)
            if ratio <= 0.60 and int(bids) <= 1:
                status_flag = "DEEP_DISCOUNT_CANDIDATE_VERIFY_SPOT_AND_PARKING_FEE"
            elif ratio >= 0.85 or int(bids) >= 10:
                status_flag = "OVERPRICED_OR_CROWDED_WARNING"
        audited_auctions.append({
            "title": a.get("title"),
            "url": a.get("url"),
            "stage": a.get("stage"),
            "current_price": cur_p,
            "assessment_price_sophon": ass_p,
            "nominal_discount_pct": disc,
            "bid_count": bids,
            "audit_flag": status_flag,
        })

    return {
        "keyword": keyword,
        "smzdm_clearance_benchmark_min": min_clearance,
        "smzdm_clearance_samples": clearances[:3],
        "audited_jd_auctions": audited_auctions,
    }


def scan_ggzy_scrap(keyword: str = "废旧", num: int = 5) -> dict[str, Any]:
    """扫描全国公共资源交易平台（ggzy_bid）废旧物资/报废处置与大宗废料期货锚点。"""
    bids: list[dict[str, Any]] = []
    copper_spot: dict[str, Any] = {}
    try:
        res_b = _macro.probe("ggzy_bid", keyword, num=num, on_error="ignore")
        if isinstance(res_b, dict):
            bids = res_b.get("records") or []
    except Exception:
        pass
    try:
        res_s = _macro.probe("commodity_spot", "铜", num=2, on_error="ignore")
        if isinstance(res_s, dict):
            copper_spot = res_s
    except Exception:
        pass

    highlighted = []
    for b in bids:
        snippet = str(b.get("detail_excerpt") or "")
        amt = b.get("extracted_prices") or []
        zero_book = ("0万元" in snippet) or ("账面净值" in snippet and "0" in snippet)
        no_hot_work = ("禁止动火" in snippet) or ("严禁动火" in snippet) or ("整体提货" in snippet)
        highlighted.append({
            "title": b.get("title"),
            "url": b.get("url"),
            "province": b.get("province"),
            "date": b.get("time"),
            "extracted_prices": amt,
            "zero_book_value_flag": zero_book,
            "hot_work_ban_crane_warning": no_hot_work,
            "snippet": snippet[:180],
        })

    return {
        "keyword": keyword,
        "commodity_benchmark": {
            "spot_price": copper_spot.get("spot_price"),
            "futures": (copper_spot.get("futures") or [])[:2],
        },
        "ggzy_disposal_deals": highlighted,
    }


def scan_arbitrage(mode: str = "all", keyword: str = "", num: int = 5) -> Dict[str, Any]:
    """统一套利与排雷扫描入口。"""
    mode_clean = (mode or "all").strip().lower()
    if mode_clean not in SUPPORTED_SCAN_MODES:
        raise ValueError(
            f"Unsupported arbitrage scan mode '{mode}'. Supported: {', '.join(SUPPORTED_SCAN_MODES)}"
        )

    result: Dict[str, Any] = {
        "source": "arbitrage_scan",
        "engine": "sophon-10-arbitrage-scanner",
        "mode": mode_clean,
        "keyword": keyword,
        "sophon_10_rules": SOPHON_10_RULES,
    }

    if mode_clean == "operators":
        result["verified_operator_demos"] = {
            "A1_maple_cw": evaluate_operator("A1_g2g_dropship"),
            "B3_dalang_hospital_10_elevators": evaluate_operator("B3_ggzy_scrap_elevator"),
            "C1_kitchen_brokerage": evaluate_operator("C1_anti_circumvention_broker"),
        }
        return result

    if mode_clean == "blind_discovery":
        result["blind_discovery"] = scan_blind_wild_business(seed_override=keyword, num=num)
        return result

    if mode_clean in ("all", "digital"):
        result["digital"] = scan_digital_spreads(game=keyword or "Path of Exile 2", num=num)

    if mode_clean in ("all", "physical"):
        result["physical"] = scan_physical_auctions(keyword=keyword or "茅台", num=num)

    if mode_clean in ("all", "ggzy_scrap"):
        result["ggzy_scrap"] = scan_ggzy_scrap(keyword=keyword or "废旧", num=num)

    return result


UNIVERSAL_MONEY_OPERATOR = {
    "root_anchors": ["钱 (Money: 钱是什么/哪4种钱在流)", "赚 (Earn/Surplus: 赚是什么/哪4种动作能以小博大产生净差额)"],
    "unfold_money_4_flows": {
        "M1_exchange_money": "1. 交换买单之钱：买方为获取实物、服务或注意力点击(广告主预算)而付出的钱",
        "M2_rule_grant_money": "2. 规则拨付之钱：政府/赛事主办方/平台按既定条文机械拨付的补贴、奖金、理赔款",
        "M3_wager_market_money": "3. 盘口博弈之钱：交易者在股市/期市/汇市/币市里，针对『价格数字本身跳动』押上的筹码之钱",
        "M4_credit_aum_money": "4. 跨期信用与募资之钱：借贷吃息、过桥拆借、或把别人的本金拢过来代管抽水(AUM)的钱",
    },
    "unfold_earn_4_mechanisms": {
        "E1_move_spread": "1. 搬（跨界错配赚差价）：同一样东西从嫌它贱的坐标系收来，搬到当宝的坐标系卖出",
        "E2_copy_scale": "2. 印（零成本复制赚倍数）：花1次固定成本造出母版，复制10000份或向30个不联网水龙头重复领钱",
        "E3_hack_credential": "3. 凑（以廉充贵钻规则漏洞）：用几十块廉价替代品/假凭证糊弄表面形式审查，领走按高成本定价的钱",
        "E4_compute_prob_speed": "4. 算（机器极速与统计概率降维）：在随机波动中用算法找出52%胜率的微弱正期望，靠微秒速度与每日十万次交易(大数定律)收割慢速情绪对手盘",
    },
}

BLIND_DISCOVERY_METHODOLOGY: Dict[str, Dict[str, Any]] = {
    "M1_faucet_and_ledger_recurrence": {
        "name": "通用发现算子一：扫『出钱水龙头与收款公示账本』的高频复现异常（Faucet & Payee Recurrence Mining）",
        "invariant_law": "凡有『钱』流出，必有发钱规则与结果账本（政府补贴发放公示名单、双创/行业比赛获奖名单、政采中标公告、平台分成排行榜）。对收款实体做 GROUP BY 复现率检测：同一个团队一年跨省拿30次比赛奖金（职业赛棍）、参保0人的空壳公司领走百万培训/农机补贴（骗补专业户），无需知道业务名词即可在账本端直接抓出正在抽干奖池/补贴池的套利者。",
        "blind_seeds": ["政策补贴 套利 揭秘", "赛棍 打比赛 赚钱 奖金", "财政补贴 空壳 套取"],
    },
    "M2_judicial_and_audit_autopsy": {
        "name": "通用发现算子二：扫『翻车尸检报告：裁判文书与审计/处罚通报』（Judicial & Audit Autopsy Mining）",
        "invariant_law": "任何暴利野路子（无论是骗国补、薅运费险、打比赛买奖、微信群流量主、危废居间）只要有人干大或分赃不均，必进《裁判文书网》或《审计署/部委行政追缴通报》。司法与审计文书会免费把『发钱规则漏洞在哪、怎么用极低成本造凭证、一共赚了多少万』写成完整说明书。",
        "blind_seeds": ["套取补贴 典型案例 漏洞", "非法获利 商业模式 揭秘", "合同纠纷 分成 暴利"],
    },
    "M3_strange_credential_buying": {
        "name": "通用发现算子三：扫『奇葩凭证/要素求购暗流』逆推发钱端（Strange Credential Demand Mining）",
        "invariant_law": "为了用极低成本 C_in 凑出触发打款的凭证 v(x)，套利者必须在民间求购看似无用的怪东西：扫全网『长期收/高价收/租借 + X』——有人收往届未公开比赛废稿/休眠专利（打比赛/高新骗补）、收残疾证/退役军人证/失业证（残保金/免税/培训骗补）、收国三破车绿本（国补套利）、收百人死群（私域广告）。看到有人花小钱批量收垃圾凭证，另一头必有10倍吐钱的水龙头。",
        "blind_seeds": ["高价回收 证件 补贴 揭秘", "挂靠 补贴 套利 门道", "收购 闲置 账号 变现"],
    },
    "M4_gatekeeper_and_insider_leak": {
        "name": "通用发现算子四：扫『发钱守门人/评委/前员工视角』泄密语料（Gatekeeper & Insider Confession Mining）",
        "invariant_law": "发钱水龙头的审核员（科技局/人社局经办人、比赛评委、平台风控、银行信贷员）和离职员工最清楚别人是怎么卡规则漏洞把钱拿走的。直接按『守门人角色词 + 空手套白狼/套利/漏洞』盲扫。",
        "blind_seeds": ["闷声发大财 小公司 业务", "审核 补贴 空手套白狼", "评委 创业大赛 刷奖"],
    },
    "M5_cross_system_valuation_gap": {
        "name": "通用发现算子五：扫『双坐标系估值剪刀差』（Cross-System Valuation Gap Mining）",
        "invariant_law": "同一个物理标的 x，在体制/清算坐标系 A 被按『废品/账面折旧0元/违规处置』贱卖（C_in），在市场/刚需坐标系 B 被按『含铜量/美金购买力/救命刚需』高价收购（P_out）。扫描一切非市场化定价节点（法拍变卖、国企报废、跨国汇率隔离、牌照壁垒）。",
        "blind_seeds": ["信息差 暴利 野路子", "冷门 套利 闷声发财", "报废 处置 差价"],
    },
}


def scan_blind_wild_business(seed_override: str = "", num: int = 3) -> Dict[str, Any]:
    """基于通用赚钱算子 Pi = P_out(Rule) - C_in(Credential Hack) 的五维逆向盲扫引擎。"""
    import bilibili_engine as _bili
    import tieba_engine as _tieba

    cap = max(1, min(int(num), 5))
    discovered: Dict[str, list[dict[str, Any]]] = {k: [] for k in BLIND_DISCOVERY_METHODOLOGY}

    for path_key in ("M1_faucet_and_ledger_recurrence", "M3_strange_credential_buying", "M5_cross_system_valuation_gap"):
        seeds = [seed_override] if seed_override else BLIND_DISCOVERY_METHODOLOGY[path_key]["blind_seeds"][:2]
        for q in seeds:
            try:
                rows = _bili.search(q, num=cap, on_error="empty")
                for r in (rows or [])[:cap]:
                    if isinstance(r, dict) and not r.get("error"):
                        discovered[path_key].append({
                            "seed": q,
                            "title": r.get("title"),
                            "play": r.get("play"),
                            "url": r.get("url"),
                        })
            except Exception:
                pass

    t_seeds = [seed_override] if seed_override else ["副业", "工作室"]
    for kw in t_seeds:
        try:
            threads = _tieba.fetch_forum(kw, num=cap, on_error="empty")
            for t in (threads or [])[:cap]:
                if isinstance(t, dict) and not t.get("error"):
                    discovered["M2_judicial_and_audit_autopsy"].append({
                        "seed": f"tieba:{kw}吧",
                        "title": t.get("title"),
                        "reply_num": t.get("reply_num"),
                        "url": t.get("url"),
                    })
        except Exception:
            pass

    try:
        bc_jobs = _macro.probe("ggzy_bid", seed_override or "报废", num=cap, on_error="ignore")
        if isinstance(bc_jobs, dict):
            for j in (bc_jobs.get("records") or [])[:cap]:
                discovered["M4_gatekeeper_and_insider_leak"].append({
                    "seed": "ggzy_bid",
                    "title": j.get("title"),
                    "url": j.get("url"),
                })
    except Exception:
        pass

    return {
        "universal_money_operator": UNIVERSAL_MONEY_OPERATOR,
        "methodology_count": len(BLIND_DISCOVERY_METHODOLOGY),
        "methodology_matrix": BLIND_DISCOVERY_METHODOLOGY,
        "live_blind_captures": discovered,
    }


if __name__ == "__main__":
    mode_arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    kw_arg = sys.argv[2] if len(sys.argv) > 2 else ""
    res = scan_arbitrage(mode=mode_arg, keyword=kw_arg, num=3)
    print(json.dumps(res, ensure_ascii=False, indent=2))

