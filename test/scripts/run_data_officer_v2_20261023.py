#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Data officer v2 rehearsal: upgraded source set for baseline 20261023.

Adds over the v1 output:
  - market_overview.json  -> type=all (8 dimensions, 100+ numeric fields)
  - sector_ranking.json   -> SW industry ranking (pre-aggregated Top/Bottom + main net inflow)
  - dragon_tiger.json     -> top_list summary (net buy/sell top10)
  - northbound.json       -> moneyflow_hsgt
  - hot_news.json         -> data_hot kind=news (hot news board)
"""
import json
import os

OUT = "E:/cashfree/agent/test/data/daily_20261023"

OVERVIEW = [
    {
        "type": "summary", "date": "2026-10-23", "desc": "市场画像总评",
        "row": {
            "ADJ_SCORE": 17.99,
            "SENTIMENT_STATUS": "情绪狂热(涨停>50只，或者涨股比>70%，两融周增>2%)",
            "STOCK_WIDTH_STATUS": "普涨(创新高>200只，或者破位<10只)",
            "SECTOR_WIDTH_STATUS": "全面下跌(上涨板块<20%)",
            "SECTOR_ROTATION_STATUS": "分化严重(头部在涨,尾部在跌,头部尾部相差超过5%)",
            "STYLE_ROTATION_STATUS": "价值主导(价值指数 > 成长指数 +5%)",
            "CAP_ROTATION_STATUS": "均衡(大小盘差异 < ±3%)",
            "TECHNICAL_STATUS": "偏弱(MACD死叉，或者RSI恐慌抛售时机，或者布林下轨附近)",
            "TREND_LONG_DIRECTION_STATUS": "暴跌(均线空头排列且距离中间均线以下距离很大)",
            "TREND_SHORT_DIRECTION_STATUS": "弱势下跌(均线空头排列,或者短线下穿中线且距离中线以下距离较小)",
            "VALUATION_STATUS": "合理区间(PE分位数30%-70%)",
            "VOLUME_ENERGE_STATUS": "缩量震荡(成交额90~110%均值)",
        },
    },
    {
        "type": "trade", "date": "2026-10-23", "desc": "三大指数收盘统计 + 量能 vs 多周期均值",
        "row": {
            "CLOSE_PRICE_SZZS": 3690.48, "CHANGE_PCT_SZZS": 0.89,
            "CLOSE_PRICE_SZCZ": 11673.83, "CHANGE_PCT_SZCZ": 2.79,
            "CLOSE_PRICE_CYBZ": 2684.10, "CHANGE_PCT_CYBZ": 4.16,
            "MONEY": 19562.84,
            "MONEY_5DAVG_RATIO": 125.27, "MONEY_10DAVG_RATIO": 125.21,
            "MONEY_20DAVG_RATIO": 117.07, "MONEY_60DAVG_RATIO": 99.85,
            "MONEY_120DAVG_RATIO": 78.49, "MONEY_250DAVG_RATIO": 82.79,
        },
    },
    {
        "type": "interval", "date": "2026-10-23", "desc": "指数区间涨跌幅与52周位置",
        "row": {
            "CHG_5D_SZZS": -0.69, "CHG_10D_SZZS": -3.23, "CHG_20D_SZZS": -4.78,
            "CHG_60D_SZZS": -4.81, "CHG_120D_SZZS": -9.54, "CHG_250D_SZZS": -5.12,
            "CHG_5D_CYBZ": -3.18, "CHG_10D_CYBZ": -11.80, "CHG_20D_CYBZ": -18.62,
            "CHG_60D_CYBZ": -24.93, "CHG_120D_CYBZ": -26.82, "CHG_250D_CYBZ": -12.82,
            "CHG_20D_HS300": -7.96,
            "52WEEK_HIGH_SZZS": 4258.86, "52WEEK_LOW_SZZS": 3574.27,
            "52WEEK_HIGH_CYBZ": 4380.41, "52WEEK_LOW_CYBZ": 2494.22,
        },
    },
    {
        "type": "technical", "date": "2026-10-23", "desc": "上证指数技术指标",
        "row": {
            "MA_5": 3705.566, "MA_10": 3731.692, "MA_20": 3803.8835,
            "MA_60": 3871.5665, "MA_120": 3965.6712, "MA_250": 3985.4474,
            "MACD": -21.9835, "DIF": -57.1019, "DEA": -46.1101,
            "KDJ_K": 28.1134, "KDJ_D": 24.4193, "KDJ_J": 35.5014,
            "RSI_6": 32.4786, "RSI_12": 31.6024, "RSI_24": 36.5171,
            "BOLL_UPPER": 3983.4666, "BOLL_MID": 3803.8835, "BOLL_LOWER": 3624.3004,
        },
    },
    {
        "type": "updown", "date": "2026-10-23", "desc": "A股涨跌分布（情绪与宽度硬数据）",
        "row": {
            "CNT_TOTAL": 5577, "CNT_RED": 4526, "CNT_GREEN": 909, "CNT_ZERO": 142,
            "RATIO_UP": 81.15, "RATIO_DOWN": 16.30, "RATIO_UPDOWN": 4.98,
            "CNT_REACH_UPLIMIT": 82, "CNT_REACH_DNLIMIT": 2,
            "RATIO_UPLIMIT": 1.47, "RATIO_DOWNLIMIT": 0.04,
            "CNT_HIGH20": 219, "CNT_LOW20": 4115,
            "CNT_HIGH60": 108, "CNT_LOW60": 2339,
            "CNT_HIGH250": 12, "CNT_LOW250": 1087,
        },
    },
    {
        "type": "valuation", "date": "2026-10-22", "desc": "中证全指估值水平（T+1 更新，滞后1日）",
        "row": {
            "PE_TTM": 18.5, "PB_LF": 1.6, "PS_TTM": 1.47,
            "DIV_TTM": 2.08, "PCF_TTM": 5.15,
            "PE_TTM_PCT_3Y": 50.13, "PE_TTM_PCT_5Y": 68.25, "PE_TTM_PCT_10Y": 57.02,
        },
    },
    {
        "type": "rotation", "date": "2026-10-23", "desc": "风格指数轮动（价值/成长/大小盘）",
        "row": {
            "CHG_5D_QZJZ": -1.86, "CHG_10D_QZJZ": -1.55, "CHG_20D_QZJZ": -0.15,
            "CHG_60D_QZJZ": -1.36, "CHG_120D_QZJZ": -4.31, "CHG_250D_QZJZ": -2.84,
            "CHG_5D_QZCZ": -0.47, "CHG_10D_QZCZ": -5.21, "CHG_20D_QZCZ": -9.69,
            "CHG_60D_QZCZ": -12.63, "CHG_120D_QZCZ": -13.18, "CHG_250D_QZCZ": -12.37,
            "CHG_5D_HS300": -1.57, "CHG_20D_HS300": -7.96,
            "CHG_5D_ZZ1000": 0.79, "CHG_20D_ZZ1000": -10.79,
        },
    },
    {
        "type": "margin", "date": "2026-10-23", "desc": "两融余额变动（接口返回空，标记缺失）",
        "row": {}, "missing": True,
    },
]

SECTORS_TOP = [
    {"name": "电池", "changePct": 5.98, "upCount": "95/97", "mainNetInflow_wan": 101229.42, "mainNetInflow5d_wan": -1130292.39, "leader": "利元亨 +16.04"},
    {"name": "软件开发", "changePct": 5.79, "upCount": "119/130", "mainNetInflow_wan": 199485.04, "mainNetInflow5d_wan": -48563.65, "leader": "汇金科技 +20.00"},
    {"name": "自动化设备", "changePct": 5.66, "upCount": "78/82", "mainNetInflow_wan": 49990.74, "mainNetInflow5d_wan": 105720.33, "leader": "奥普特 +20.00"},
    {"name": "电机Ⅱ", "changePct": 5.55, "upCount": "26/26", "mainNetInflow_wan": 21886.23, "mainNetInflow5d_wan": 123555.05, "leader": "华阳智能 +20.00"},
    {"name": "影视院线", "changePct": 4.75, "upCount": "18/19", "mainNetInflow_wan": 27137.41, "mainNetInflow5d_wan": -69255.91, "leader": "中广天择 +10.01"},
    {"name": "数字媒体", "changePct": 4.58, "upCount": "13/14", "mainNetInflow_wan": 5011.87, "mainNetInflow5d_wan": -40868.97, "leader": "凡拓数创 +20.00"},
    {"name": "广告营销", "changePct": 4.58, "upCount": "23/28", "mainNetInflow_wan": 150783.76, "mainNetInflow5d_wan": 67197.83, "leader": "天娱数科 +10.00"},
    {"name": "消费电子", "changePct": 4.49, "upCount": "77/91", "mainNetInflow_wan": 218330.41, "mainNetInflow5d_wan": 431729.01, "leader": "长盈精密 +14.82"},
    {"name": "IT服务Ⅱ", "changePct": 4.36, "upCount": "107/122", "mainNetInflow_wan": 144273.22, "mainNetInflow5d_wan": 65693.26, "leader": "海天瑞声 +20.00"},
    {"name": "游戏Ⅱ", "changePct": 3.85, "upCount": "23/26", "mainNetInflow_wan": 3709.08, "mainNetInflow5d_wan": -224958.09, "leader": "宝通科技 +14.42"},
    {"name": "工程机械", "changePct": 3.58, "upCount": "26/28", "mainNetInflow_wan": 20660.60, "mainNetInflow5d_wan": 62800.35, "leader": "南方路机 +10.01"},
    {"name": "计算机设备", "changePct": 3.41, "upCount": "77/82", "mainNetInflow_wan": 6254.30, "mainNetInflow5d_wan": -254978.24, "leader": "汇金股份 +9.09"},
    {"name": "半导体", "changePct": 3.30, "upCount": "168/183", "mainNetInflow_wan": 689656.16, "mainNetInflow5d_wan": 234872.22, "leader": "粤芯半导体-U +20.01"},
    {"name": "汽车零部件", "changePct": 3.03, "upCount": "217/244", "mainNetInflow_wan": 73476.49, "mainNetInflow5d_wan": -27269.77, "leader": "松原安全 +13.01"},
    {"name": "光学光电子", "changePct": 2.78, "upCount": "79/93", "mainNetInflow_wan": 56519.64, "mainNetInflow5d_wan": -23432.00, "leader": "利亚德 +20.00"},
]

SECTORS_BOTTOM = [
    {"name": "国有大型银行Ⅱ", "changePct": -2.89, "upCount": "0/6", "mainNetInflow_wan": -145892.52, "leader": "邮储银行 -1.44"},
    {"name": "特钢Ⅱ", "changePct": -1.30, "upCount": "7/12", "mainNetInflow_wan": 7154.71, "leader": "久立特材 +3.23"},
    {"name": "城商行Ⅱ", "changePct": -1.06, "upCount": "5/17", "mainNetInflow_wan": -31420.53, "leader": "苏州银行 +2.10"},
    {"name": "电力", "changePct": -0.68, "upCount": "55/109", "mainNetInflow_wan": -150982.59, "leader": "京运通 +1.82"},
    {"name": "股份制银行Ⅱ", "changePct": -0.41, "upCount": "2/9", "mainNetInflow_wan": -111152.63, "leader": "民生银行 +0.58"},
    {"name": "养殖业", "changePct": -0.41, "upCount": "17/22", "mainNetInflow_wan": -21800.87, "leader": "湘佳股份 +10.02"},
    {"name": "铁路公路", "changePct": -0.39, "upCount": "13/33", "mainNetInflow_wan": -18753.18, "leader": "重庆路桥 +1.96"},
    {"name": "工程咨询服务Ⅱ", "changePct": -0.24, "upCount": "29/40", "mainNetInflow_wan": -13988.04, "leader": "勘设股份 +5.48"},
    {"name": "地面兵装Ⅱ", "changePct": -0.24, "upCount": "8/12", "mainNetInflow_wan": -19552.14, "leader": "北方导航 +3.12"},
    {"name": "农产品加工", "changePct": -0.23, "upCount": "12/23", "mainNetInflow_wan": -9984.84, "leader": "中基健康 +10.03"},
]

DT_NET_BUY = [
    {"name": "天娱数科", "code": "002354.SZ", "net_amount_yi": 4.89, "reason": "日涨幅偏离值达7%"},
    {"name": "歌尔股份", "code": "002241.SZ", "net_amount_yi": 4.51, "reason": "日涨幅偏离值达7%"},
    {"name": "兆威机电", "code": "003021.SZ", "net_amount_yi": 2.34, "reason": "连续三日涨幅偏离20%"},
    {"name": "宇树科技", "code": "688836.SH", "net_amount_yi": 2.11, "reason": "日涨幅达15%"},
    {"name": "粤芯半导体", "code": "301660.SZ", "net_amount_yi": 1.95, "reason": "日涨幅达15%"},
    {"name": "凡拓数创", "code": "301313.SZ", "net_amount_yi": 1.76, "reason": "日涨幅达15%"},
    {"name": "埃斯顿", "code": "002747.SZ", "net_amount_yi": 1.72, "reason": "日涨幅偏离值达7%"},
    {"name": "绿盟科技", "code": "300369.SZ", "net_amount_yi": 1.66, "reason": "日涨幅达15%"},
    {"name": "慈星股份", "code": "300307.SZ", "net_amount_yi": 1.59, "reason": "日涨幅达15%"},
    {"name": "华瓷股份", "code": "001216.SZ", "net_amount_yi": 1.42, "reason": "连续三日涨幅偏离20%"},
]

DT_NET_SELL = [
    {"name": "索辰科技", "code": "688507.SH", "net_amount_yi": -3.03, "reason": "日振幅达30%"},
    {"name": "盛视科技", "code": "002990.SZ", "net_amount_yi": -1.48, "reason": "连续三日跌幅偏离20%"},
    {"name": "风语筑", "code": "603466.SH", "net_amount_yi": -1.27, "reason": "日涨幅偏离值达7%"},
    {"name": "沈鼓集团", "code": "601091.SH", "net_amount_yi": -1.19, "reason": "日换手率达20%"},
    {"name": "冰山冷热", "code": "000530.SZ", "net_amount_yi": -1.01, "reason": "日换手率达20%"},
    {"name": "万里石", "code": "002785.SZ", "net_amount_yi": -0.62, "reason": "日跌幅偏离值达7%"},
    {"name": "闽发铝业", "code": "002578.SZ", "net_amount_yi": -0.56, "reason": "日跌幅偏离值达7%"},
    {"name": "海量数据", "code": "603138.SH", "net_amount_yi": -0.50, "reason": "日跌幅偏离值达7%"},
    {"name": "华依科技", "code": "688071.SH", "net_amount_yi": -0.44, "reason": "日涨幅达15%"},
    {"name": "晶丰明源", "code": "688368.SH", "net_amount_yi": -0.41, "reason": "日涨幅达15%"},
]

HOT_NEWS = [
    {"rank": 1, "title": "A股大消息！重要指数调整，明起实施", "source": "券商中国"},
    {"rank": 2, "title": "集体拉升！超级赛道利好传来，影响多大？", "source": "券商中国"},
    {"rank": 3, "title": "环球下周看点：AI巨头财报密集揭晓 美联储议息或为利率定调", "source": "财联社"},
    {"rank": 4, "title": "A股、港股止跌反弹，趋势何时反转？", "source": "《财经》杂志"},
    {"rank": 5, "title": "一周机会前瞻|这次AI交易能否自救？美联储决议和科技巨头财报都来了", "source": "腾讯自选股"},
    {"rank": 6, "title": "没人要，东山精密公开发售仅认购0.39倍？A股3个月闪崩62%", "source": "金石杂谈"},
    {"rank": 7, "title": "业绩暴增，股价连续重挫！CPO概念股获机构密集调研", "source": "e公司"},
    {"rank": 8, "title": "逼近举牌线、重仓PCB概念股！知名牛散三季度新进股梳理", "source": "证券时报"},
    {"rank": 9, "title": "大信号：亚洲股市技术面极度超卖！国际大行突然发声", "source": "证券时报网"},
    {"rank": 10, "title": "美银：中国1.4万亿美元AI基建投向哪里", "source": "数之涌现"},
    {"rank": 11, "title": "688808拟赴港 净利暴增18倍", "source": "21世纪经济报道"},
    {"rank": 12, "title": "量子科技，基金重仓的6家公司", "source": "硬派研选"},
    {"rank": 13, "title": "机器人IPO门槛提高 具身智能一级市场预期变了", "source": "财联社"},
    {"rank": 14, "title": "化学原料行业：地缘冲突背景下的甲醇-醋酸产业链近况更新", "source": "天风证券"},
    {"rank": 15, "title": "5连板、4连板！固态电池概念火了", "source": "证券市场周刊"},
    {"rank": 16, "title": "现货黄金跌穿4000美元/盎司，瑞银：可视为加仓机会", "source": "21世纪经济报道"},
    {"rank": 17, "title": "上证系列综合指数明起有重要调整：增加单样本权重上限15%", "source": "潇湘晨报"},
    {"rank": 18, "title": "对于A股调整，但斌称还是要高抛低吸，其美股三季度调仓曝光", "source": "每日经济新闻"},
    {"rank": 19, "title": "冲突升级！胡塞武装对沙特发起多次袭击 目标直指能源设施和机场", "source": "财联社"},
    {"rank": 20, "title": "欧洲多国开始实施冬令时", "source": "财联社"},
]

NORTHBOUND = {
    "date": "20261023",
    "source": "tushare:moneyflow_hsgt",
    "unit": "万元",
    "hgt": 156251.0,
    "sgt": 156927.26,
    "north_money": 313178.26,
    "ggt_ss": 32333.19,
    "ggt_sz": 22874.67,
    "south_money": 55207.86,
    "north_money_yi": 31.32,
}

with open(os.path.join(OUT, "market_overview.json"), "w", encoding="utf-8") as f:
    json.dump({"date": "2026-10-23", "source": "westock-mcp:data_market_overview",
               "mode": "all", "dimensions": OVERVIEW}, f, ensure_ascii=False, indent=2)

with open(os.path.join(OUT, "sector_ranking.json"), "w", encoding="utf-8") as f:
    json.dump({
        "date": "2026-10-23",
        "source": "westock-mcp:data_sector ranking industry changePct",
        "universe_note": "申万行业全量约 100 个二级行业，此处预聚合 Top15 涨幅 / Bottom10 跌幅；mainNetInflow 单位万元",
        "top_gainers": SECTORS_TOP,
        "bottom_losers": SECTORS_BOTTOM,
        "breadth_note": "上涨行业数/下跌行业数需从全量计算：本次返回中 changePct>0 的行业约占多数，但涨幅>3%的集中在 TMT/电力设备",
    }, f, ensure_ascii=False, indent=2)

with open(os.path.join(OUT, "dragon_tiger.json"), "w", encoding="utf-8") as f:
    json.dump({
        "date": "20261023",
        "source": "tushare:top_list",
        "note": "原始返回约 80 条记录（含同一股票多个上榜原因），此处按 net_amount 预聚合 Top10 净买/净卖",
        "net_buy_top10": DT_NET_BUY,
        "net_sell_top10": DT_NET_SELL,
    }, f, ensure_ascii=False, indent=2)

with open(os.path.join(OUT, "northbound.json"), "w", encoding="utf-8") as f:
    json.dump(NORTHBOUND, f, ensure_ascii=False, indent=2)

with open(os.path.join(OUT, "hot_news.json"), "w", encoding="utf-8") as f:
    json.dump({
        "source": "westock-mcp:data_hot kind=news",
        "note": "热点新闻榜为实时榜单，不支持历史回看；本次(10-25)取到的是 10-25 榜单，非 10-23 当日",
        "items": HOT_NEWS,
    }, f, ensure_ascii=False, indent=2)

meta_p = os.path.join(OUT, "meta.json")
meta = json.load(open(meta_p, encoding="utf-8"))
meta["version"] = "v2-multi-source"
meta["sources"].update({
    "sector_ranking": "westock-mcp:data_sector",
    "dragon_tiger": "tushare:top_list",
    "northbound": "tushare:moneyflow_hsgt",
    "hot_news": "westock-mcp:data_hot",
})
meta["record_counts"] = {
    "indices": 5,
    "market_overview_dimensions": len(OVERVIEW),
    "sector_top": len(SECTORS_TOP),
    "sector_bottom": len(SECTORS_BOTTOM),
    "dragon_tiger_net_buy": len(DT_NET_BUY),
    "dragon_tiger_net_sell": len(DT_NET_SELL),
    "northbound": 1,
    "news": 15,
    "hot_news": len(HOT_NEWS),
}
meta["notes"].append("v2 扩展：market_overview 改用 type=all（8 维度），新增 sector_ranking / dragon_tiger / northbound / hot_news")
meta["notes"].append("接口权限实测：limit_list_d/limit_cpt_list/moneyflow_mkt_dc/major_news/news/stk_factor 均 40203 无权限；top_list、moneyflow_hsgt 有权限；data_sector ranking 支持 date 回看")
meta["notes"].append("summary 标签 VOLUME_ENERGE_STATUS=缩量震荡 与实测矛盾：当日两市成交 19562.84 亿，为 20 日均值 117.07%、10 日均值 125.21%（实为放量）——定性标签不可单独采信")
meta["notes"].append("market_overview 的 valuation 维度为 T+1 更新，date 显示 2026-10-22，已标注滞后")
meta["notes"].append("margin（两融）维度接口返回空 row，标记 missing")
meta["notes"].append("hot_news / data_hot 为实时榜，无法回看 10-23；正式跑(当日23:00)不受影响")

json.dump(meta, open(meta_p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

print("upgraded outputs ->", OUT)
for fn in ("market_overview.json", "sector_ranking.json", "dragon_tiger.json",
           "northbound.json", "hot_news.json", "meta.json"):
    print("  %-24s %7d bytes" % (fn, os.path.getsize(os.path.join(OUT, fn))))
