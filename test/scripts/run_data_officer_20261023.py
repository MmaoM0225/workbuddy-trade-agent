#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Rehearsal run of data_officer for baseline 20261023.

Real MCP pulls (executed in the agent session) are embedded here and written
into test/data/daily_20261023/ so the production snapshot is never touched.
"""
import json
import os
import re
from datetime import datetime

BASE = "E:/cashfree/agent"
OUT = os.path.join(BASE, "test", "data", "daily_20261023")
os.makedirs(OUT, exist_ok=True)

INDICES = [
    {"ts_code": "000001.SH", "name": "上证指数", "trade_date": "20261023",
     "close": 3690.4753, "open": 3623.5669, "high": 3691.3988, "low": 3574.2712,
     "pre_close": 3658.0256, "change": 32.4497, "pct_chg": 0.8871,
     "vol": 552842912.0, "amount": 898666874.9023},
    {"ts_code": "399001.SZ", "name": "深证成指", "trade_date": "20261023",
     "close": 11673.8259, "open": 11187.5481, "high": 11707.1479, "low": 11043.3129,
     "pre_close": 11357.3196, "change": 316.5063, "pct_chg": 2.7868,
     "vol": 221663021.01, "amount": 544625366.55974},
    {"ts_code": "399006.SZ", "name": "创业板指", "trade_date": "20261023",
     "close": 2684.0971, "open": 2534.1563, "high": 2695.0757, "low": 2494.2153,
     "pre_close": 2576.901, "change": 107.1961, "pct_chg": 4.1599,
     "vol": 38745924.48, "amount": 230122196.33416},
    {"ts_code": "000300.SH", "name": "沪深300", "trade_date": "20261023",
     "close": 4105.3286, "open": 3992.9041, "high": 4109.5184, "low": 3958.1375,
     "pre_close": 4036.2966, "change": 69.032, "pct_chg": 1.7103,
     "vol": 231325213.0, "amount": 558204983.0573},
    {"ts_code": "000905.SH", "name": "中证500", "trade_date": "20261023",
     "close": 6814.4429, "open": 6559.6131, "high": 6835.391, "low": 6440.2912,
     "pre_close": 6655.2498, "change": 159.1931, "pct_chg": 2.392,
     "vol": 170824050.0, "amount": 336940932.8979},
]

OVERVIEW_ROW = {
    "ADJ_SCORE": 17.99,
    "CAP_ROTATION_SCORE": 3, "CAP_ROTATION_STATUS": "均衡(大小盘差异 < ±3%)",
    "RAW_SCORE": 18.55,
    "SECTOR_ROTATION_SCORE": 4, "SECTOR_ROTATION_STATUS": "分化严重(头部在涨,尾部在跌,头部尾部相差超过5%)",
    "SECTOR_WIDTH_SCORE": 1, "SECTOR_WIDTH_STATUS": "全面下跌(上涨板块<20%)",
    "SENTIMENT_SCORE": 5, "SENTIMENT_STATUS": "情绪狂热(涨停>50只，或者涨股比>70%，两融周增>2% )",
    "STOCK_WIDTH_SCORE": 5, "STOCK_WIDTH_STATUS": "普涨(创新高>200只，或者破位<10只)",
    "STYLE_ROTATION_SCORE": 1, "STYLE_ROTATION_STATUS": "价值主导(价值指数 > 成长指数 +5%)",
    "TECHNICAL_SCORE": 2, "TECHNICAL_STATUS": "偏弱(MACD死叉，或者RSI恐慌抛售时机，或者布林下轨附近)",
    "TREND_LONG_DIRECTION_SCORE": 1, "TREND_LONG_DIRECTION_STATUS": "暴跌(均线空头排列且距离中间均线以下距离很大",
    "TREND_LONG_STRENGTH_SCORE": 3, "TREND_LONG_STRENGTH_STATUS": "震荡",
    "TREND_SHORT_DIRECTION_SCORE": 2, "TREND_SHORT_DIRECTION_STATUS": "弱势下跌(均线空头排列,或者短线下穿中线且距离中线以下距离较小)",
    "TREND_SHORT_STRENGTH_SCORE": 3, "TREND_SHORT_STRENGTH_STATUS": "震荡",
    "VALUATION_SCORE": 3, "VALUATION_STATUS": "合理区间(PE分位数30%-70%)",
    "VOLUME_ENERGE_SCORE": 3, "VOLUME_ENERGE_STATUS": "缩量震荡(成交额90~110%均值)",
    "code": "", "name": "",
}

NEWS_RAW = [
    {"id": "CN2026102516312895474a65", "title": "华神科技：向特定对象发行股票申请获证监会同意注册批复", "source_media": "财联社", "publish_time": 1792917076, "content": "华神科技(000790.SZ)公告称，公司收到证监会出具的《关于同意成都华神科技集团股份有限公司向特定对象发行股票注册的批复》，同意公司向特定对象发行股票的注册申请。本次发行应严格按照报送深交所的申报文件和发行方案实施，批复自同意注册之日起12个月内有效。"},
    {"id": "CN2026102516311595474a55", "title": "民德电子：向特定对象发行股票获证监会同意注册批复", "source_media": "财联社", "publish_time": 1792917073, "content": "民德电子(300656.SZ)公告称，公司收到证监会出具的《关于同意深圳市民德电子科技股份有限公司向特定对象发行股票注册的批复》。", "label_list": [{"label_name": "A股"}]},
    {"id": "CN2026102516270497ac56f7", "title": "百利天恒：双抗ADC新药上市申请获受理", "source_media": "财联社", "publish_time": 1792916809, "content": "百利天恒(688506.SH)公告称，公司自主研发的全球首创双抗ADC药物“伦康依隆妥单抗”用于治疗EGFR-TKI耐药EGFR突变非小细胞肺癌的药品上市申请获国家药监局药审中心正式受理。", "label_list": [{"label_name": "A股"}, {"label_name": "港股"}]},
    {"id": "CN2026102516264997ac56eb", "title": "百利天恒：T-Bren III期临床试验达主要终点", "source_media": "财联社", "publish_time": 1792916806, "content": "百利天恒(688506.SH)公告称，公司自主研发的创新生物药注射用T-Bren(HER2ADC)在III期临床试验中达到无进展生存期主要终点。", "label_list": [{"label_name": "港股"}, {"label_name": "A股"}]},
    {"id": "CN20261025162311a48575c2", "title": "中光防雷：前三季度净利润同比增长17.32%", "source_media": "财联社", "publish_time": 1792916564, "content": "中光防雷(300414.SZ)公告称，第三季度营业收入1.61亿元同比增长24.03%；净利润805.41万元同比增长24.75%。前三季度营收4.28亿元同比增长23.19%，净利润2010.20万元同比增长17.32%。", "label_list": [{"label_name": "A股"}]},
    {"id": "CN20261025161805a4857494", "title": "漫步者：前三季度净利润同比增长13.37%", "source_media": "财联社", "publish_time": 1792916254, "content": "漫步者(002351.SZ)公告称，第三季度营收8.13亿元同比增长15.56%，净利润1.29亿元同比增长29.07%；前三季度营收20.81亿元同比增长1.21%，净利润3.40亿元同比增长13.37%。", "label_list": [{"label_name": "A股"}]},
    {"id": "CN2026102516164895474703", "title": "金溢科技：全资子公司签署2.18亿元算力服务器配件采购合同", "source_media": "财联社", "publish_time": 1792916195, "content": "金溢科技(002869.SZ)公告称，子公司车路通科技签署两笔算力服务器相关配件采购合同，合计约2.18亿元，采购资金来源于公司自有资金。"},
    {"id": "CN20261025161442b66824a0", "title": "大连电瓷：前三季度净利润同比增长144.35%", "source_media": "财联社", "publish_time": 1792916069, "content": "大连电瓷(002606.SZ)公告称，前三季度营收14.24亿元同比增长29.33%，净利润2.82亿元同比增长144.35%，主要系高附加值产品占比提升、毛利率提升所致。", "label_list": [{"label_name": "A股"}]},
    {"id": "CN20261025161408a6db42fc", "title": "万里石：前三季度净利润同比增长3682.08%", "source_media": "财联社", "publish_time": 1792916032, "content": "万里石(002785.SZ)公告称，前三季度营收6.96亿元同比下降18.15%，净利润3402.22万元同比增长3682.08%。", "label_list": [{"label_name": "A股"}]},
    {"id": "CN2026102516134197ac5404", "title": "三利谱：拟投资5亿元迁移产线并升级改造", "source_media": "财联社", "publish_time": 1792916007, "content": "三利谱(002876.SZ)与莆田市城厢区人民政府签订投资协议，将深圳偏光片生产线迁移至莆田并技改升级，项目总投资约5亿元。"},
    {"id": "CN20261025161327b668243a", "title": "罗普斯金：拟2.07亿元收购盟萤科技51%股权", "source_media": "财联社", "publish_time": 1792915991, "content": "罗普斯金(002333.SZ)拟以现金2.07亿元收购苏州盟萤电子科技51%股权，盟萤主营AMHS系统核心零部件，承诺2026-2028年净利润不低于2200/3500/4425万元。"},
    {"id": "CN20261025161243a4857337", "title": "洁美科技：前三季度净利润同比增长26.93%", "source_media": "财联社", "publish_time": 1792915957, "content": "洁美科技(002859.SZ)公告称，前三季度营收19.40亿元同比增长27.10%，净利润2.23亿元同比增长26.93%。", "label_list": [{"label_name": "A股"}]},
    {"id": "CN20261025160641b6682233", "title": "德明利：前三季度净利润同比增长32399.91%", "source_media": "财联社", "publish_time": 1792915575, "content": "德明利(001309.SZ)公告称，前三季度营收285.55亿元同比增长328.81%，净利润87.46亿元同比增长32399.91%；第三季度营收116.45亿元同比增长356.64%。存储行业景气驱动。", "label_list": [{"label_name": "A股"}]},
    {"id": "CN20261025160013b668208e", "title": "天齐锂业：前三季度净利润同比增长3013.86%", "source_media": "财联社", "publish_time": 1792915163, "content": "天齐锂业(002466.SZ)公告称，前三季度营收182.79亿元同比增长147.11%，净利润56.02亿元同比增长3013.86%，主因锂产品销售均价上涨及SQM投资收益增长。", "label_list": [{"label_name": "A股"}, {"label_name": "港股"}]},
    {"id": "CN202610251557379897d2ab", "title": "天原股份：前三季度净利润同比增长753.11%", "source_media": "财联社", "publish_time": 1792915044, "content": "天原股份(002386.SZ)公告称，前三季度营收106.89亿元同比增长25.90%，净利润2.70亿元同比增长753.11%。", "label_list": [{"label_name": "A股"}]},
]

TAG_RE = re.compile(r"<!--.*?-->", re.S)


def clean(txt, limit=100):
    t = TAG_RE.sub("", txt or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:limit]


news = []
for n in NEWS_RAW:
    news.append({
        "id": n["id"],
        "title": n["title"],
        "source": (n.get("source_media") or "").strip(),
        "publish_time": n["publish_time"],
        "labels": [x["label_name"] for x in (n.get("label_list") or [])],
        "digest": clean(n.get("content", ""), 100),
    })

with open(os.path.join(OUT, "indices.json"), "w", encoding="utf-8") as f:
    json.dump(INDICES, f, ensure_ascii=False, indent=2)

with open(os.path.join(OUT, "market_overview.json"), "w", encoding="utf-8") as f:
    json.dump({"date": "2026-10-23", "source": "westock-mcp:data_market_overview",
               "summary": OVERVIEW_ROW}, f, ensure_ascii=False, indent=2)

with open(os.path.join(OUT, "news.json"), "w", encoding="utf-8") as f:
    json.dump(news, f, ensure_ascii=False, indent=2)

meta = {
    "date": "20261023",
    "fetched_at": datetime.now().isoformat(timespec="seconds"),
    "trading_day": True,
    "rehearsal": True,
    "mode": "manual-rehearsal-from-2026-10-25",
    "sources": {
        "trade_cal": "tushare:trade_cal",
        "indices": "tushare:index_daily",
        "market_overview": "westock-mcp:data_market_overview",
        "news": "westock-mcp:data_flash_news_search",
    },
    "record_counts": {"indices": len(INDICES), "market_overview": 1, "news": len(news)},
    "degraded": False,
    "notes": [
        "trade_cal(SSE, 20261023) is_open=1 确认为交易日，pretrade_date=20261022",
        "indices: 5/5 指数按 trade_date=20261023 精确取到，无缺失，无需区间回退",
        "market_overview: 接口支持 date=2026-10-23 回看，返回当日真实市场画像（非当前时点）",
        "news: flash_news 仅支持最近24小时滚动窗口，本次(10-25 16:4x)取到的是10-25当日快讯，非10-23当日；已在 notes 标注，不影响 indices/overview 的基准日正确性",
        "tushare:news 无权限(40203)，快讯统一走 westock",
        "本次为彩排运行，产物写 test/data/，未触碰正式 data/daily_20261023/",
    ],
}
with open(os.path.join(OUT, "meta.json"), "w", encoding="utf-8") as f:
    json.dump(meta, f, ensure_ascii=False, indent=2)

print("written ->", OUT)
for fn in ("indices.json", "market_overview.json", "news.json", "meta.json"):
    p = os.path.join(OUT, fn)
    print("  %-22s %6d bytes" % (fn, os.path.getsize(p)))
