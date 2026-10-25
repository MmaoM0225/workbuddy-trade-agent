#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Researcher rehearsal: screen pool top50 -> watchlist.json (fully local, zero MCP).

Inputs: warehouse scores_full.csv (17 factors), research/{goodwill,audit,reduction}.csv,
daily_basic/20261023.csv (total_share for reduction-ratio check).
"""
import csv
import json

BASE = "E:/cashfree/agent/"
POOL = BASE + "test/state/pool.json"
SCORES = BASE + "data/warehouse/scores_full.csv"
GOODWILL = BASE + "data/warehouse/research/goodwill.csv"
AUDIT = BASE + "data/warehouse/research/audit.csv"
REDUCTION = BASE + "data/warehouse/research/reduction.csv"
DAILY_BASIC = BASE + "data/warehouse/daily_basic/20261023.csv"
OUT = BASE + "test/state/watchlist.json"

GOODWILL_CAP = 0.30      # 商誉/净资产 上限
REDUCE_RATIO_CAP = 0.01  # 近3月减持占总股本比例上限
REDUCE_CNT_CAP = 3       # 近3月减持次数上限


def load(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


pool = json.load(open(POOL, encoding="utf-8"))
pool_codes = [s["code"] for s in pool["stocks"]]
pool_name = {s["code"]: s["name"] for s in pool["stocks"]}
pool_rank = {s["code"]: s["rank"] for s in pool["stocks"]}

scores = {r["ts_code"]: r for r in load(SCORES)}
gw = {r["ts_code"]: r for r in load(GOODWILL)}
au = {r["ts_code"]: r for r in load(AUDIT)}
rd = {r["ts_code"]: r for r in load(REDUCTION)}
db = {r["ts_code"]: r for r in load(DAILY_BASIC)}

# percentile within the 1802-stock full universe for each factor
FACTORS = ["mom_5d", "mom_10d", "mom_20d", "mom_60d", "vol_20d_inv", "mdd_20d_inv",
           "price_pos_20d", "pv_corr_20d", "turnover_trend_20d", "roe_ttm",
           "gross_margin_ttm", "net_margin_ttm", "tr_yoy", "ep_ttm", "bp_ttm",
           "sp_ttm", "turnover_rate"]
all_rows = list(scores.values())
pct = {}
for f in FACTORS:
    vals = []
    for r in all_rows:
        try:
            vals.append((float(r[f]), r["ts_code"]))
        except (ValueError, KeyError):
            continue
    vals.sort(key=lambda x: x[0])
    pct[f] = {code: (i + 0.5) / len(vals) * 100 for i, (_, code) in enumerate(vals)}

LABEL = {
    "mom_5d": "5日动量", "mom_10d": "10日动量", "mom_20d": "20日动量", "mom_60d": "60日动量",
    "vol_20d_inv": "20日低波动", "mdd_20d_inv": "20日低回撤", "price_pos_20d": "20日价格位置",
    "pv_corr_20d": "量价相关性", "turnover_trend_20d": "成交额趋势", "roe_ttm": "ROE(TTM)",
    "gross_margin_ttm": "毛利率", "net_margin_ttm": "净利率", "tr_yoy": "营收同比",
    "ep_ttm": "EP(TTM)", "bp_ttm": "BP(TTM)", "sp_ttm": "SP(TTM)", "turnover_rate": "换手率",
}

QUALITY_W = {"roe_ttm": 0.35, "net_margin_ttm": 0.25, "gross_margin_ttm": 0.15, "tr_yoy": 0.25}

items = []
screened = []
for code in pool_codes:
    name = pool_name[code]
    s = scores.get(code)
    if not s:
        screened.append({"code": code, "name": name, "verdict": "avoid", "reason": "因子数据缺失"})
        continue

    avoid_reason = None
    risks = []

    g = gw.get(code, {})
    try:
        gv = float(g.get("goodwill") or 0)
        eq = float(g.get("equity") or 0)
    except ValueError:
        gv, eq = 0.0, 0.0
    g_ratio = gv / eq if eq else 0.0
    if g_ratio > GOODWILL_CAP:
        avoid_reason = "商誉/净资产 %.1f%% 超过 30%% 上限" % (g_ratio * 100)
    elif g_ratio > 0.15:
        risks.append("商誉占比 %.1f%% 偏高" % (g_ratio * 100))

    a = au.get(code, {})
    audit = (a.get("audit_result") or "").strip()
    if audit and "标准无保留" not in audit:
        avoid_reason = "审计意见非标：%s" % audit

    r = rd.get(code, {})
    try:
        dec_cnt = int(float(r.get("dec_cnt") or 0))
        dec_vol = float(r.get("dec_vol") or 0)
        tshare = float((db.get(code) or {}).get("total_share") or 0)
    except ValueError:
        dec_cnt, dec_vol, tshare = 0, 0.0, 0.0
    # dec_vol 单位为「股」，daily_basic.total_share 单位为「万股」→ 需换算
    red_ratio = (dec_vol / (tshare * 10000)) if tshare else 0.0
    if red_ratio > REDUCE_RATIO_CAP:
        avoid_reason = "近3月大股东减持 %d 次 / %s 万股（占总股本 %.2f%%）" % (
            dec_cnt, format(dec_vol / 10000, ".0f"), red_ratio * 100)
    elif dec_cnt:
        risks.append("近3月大股东减持 %d 次共 %s 万股（占 %.2f%%）%s" % (
            dec_cnt, format(dec_vol / 10000, ".0f"), red_ratio * 100,
            "，频率偏高" if dec_cnt >= REDUCE_CNT_CAP else ""))

    if avoid_reason:
        screened.append({"code": code, "name": name, "verdict": "avoid", "reason": avoid_reason})
        continue

    qs = sum(pct[f].get(code, 50) * w for f, w in QUALITY_W.items())

    # thesis: strongest quality + valuation + momentum factors
    cand = []
    for f, w in (("roe_ttm", 1), ("net_margin_ttm", 1), ("tr_yoy", 1), ("gross_margin_ttm", 1),
                 ("ep_ttm", 1), ("bp_ttm", 1), ("mom_20d", 1), ("vol_20d_inv", 1)):
        cand.append((pct[f].get(code, 0), f))
    cand.sort(reverse=True)
    thesis = "；".join("%s 分位 %.0f%%" % (LABEL[f], p) for p, f in cand[:3])

    if pct["ep_ttm"].get(code, 50) < 30:
        risks.append("估值处于样本高位（EP 分位 %.0f%%）" % pct["ep_ttm"][code])
    if pct["mom_5d"].get(code, 50) > 90:
        risks.append("5 日涨幅居前（分位 %.0f%%），短期追高风险" % pct["mom_5d"][code])
    if pct["vol_20d_inv"].get(code, 50) < 30:
        risks.append("波动率高于样本（低波分位 %.0f%%）" % pct["vol_20d_inv"][code])
    if not risks:
        risks.append("未发现明显瑕疵，但需跟踪三季报与行业景气变化")

    items.append({
        "code": code,
        "name": name,
        "pool_rank": pool_rank[code],
        "pool_score": next(s2["score"] for s2 in pool["stocks"] if s2["code"] == code),
        "quality_score": round(qs, 1),
        "goodwill_ratio_pct": round(g_ratio * 100, 1),
        "audit": audit or "未披露",
        "verdict": "buy_watch",
        "thesis": thesis,
        "risks": risks,
    })

items.sort(key=lambda x: -x["quality_score"])
for i, it in enumerate(items, 1):
    it["watch_rank"] = i

selected = items[:20]

payload = {
    "date": "20261023",
    "source_pool_date": pool["date"],
    "pool_universe_size": pool["universe_size"],
    "screened_count": len(pool_codes),
    "avoid_count": len(screened),
    "buy_watch_count": len(selected),
    "items": selected,
    "avoid_list": screened,
    "notes": [
        "彩排：全本地研判，零 MCP 调用（因子来自 warehouse/scores_full.csv，排雷来自 warehouse/research/）",
        "排雷规则：商誉/净资产>30% 或 审计非标 或 近3月减持≥3次或占总股本>1% → avoid",
        "quality_score 定义：ROE 35% + 净利率 25% + 毛利率 15% + 营收同比 25%，均为 1802 只样本内百分位加权",
        "入围 %d 只（按 quality_score 取前 20），剔除 %d 只" % (len(selected), len(screened)),
        "正式运行需补充：个股级新闻情绪扫描（news_search）与近 3 年 PE/PB 分位（当前用横截面 EP/BP 分位近似）",
    ],
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)

print("screened:", len(pool_codes), "| avoid:", len(screened), "| buy_watch:", len(selected))
print("\n--- avoid list ---")
for s in screened:
    print("  %-9s %-8s %s" % (s["code"], s["name"], s["reason"]))
print("\n--- watchlist top15 ---")
for it in selected[:15]:
    print("  %2d. %-9s %-8s qs=%.1f  商誉%4.1f%%  %s" % (
        it["watch_rank"], it["code"], it["name"], it["quality_score"],
        it["goodwill_ratio_pct"], it["thesis"][:46]))
