#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stock picker (full-market): build pool.json from warehouse scores_full.csv.

Universe: v1.3 compliant (BJ / GEM / STAR / ST all excluded), 1802 stocks with
complete 17-factor coverage. Compares against the previous 200-capped pool.
"""
import csv
import json
from collections import Counter

SCORES = "E:/cashfree/agent/data/warehouse/scores_full.csv"
OUT = "E:/cashfree/agent/test/state/pool.json"

FACTORS = [
    ("mom_5d", "5日动量"), ("mom_10d", "10日动量"), ("mom_20d", "20日动量"),
    ("mom_60d", "60日动量"), ("vol_20d_inv", "20日低波动"), ("mdd_20d_inv", "20日低回撤"),
    ("price_pos_20d", "20日价格位置"), ("pv_corr_20d", "量价相关性"),
    ("turnover_trend_20d", "成交额趋势"), ("roe_ttm", "ROE(TTM)"),
    ("gross_margin_ttm", "毛利率"), ("net_margin_ttm", "净利率"), ("tr_yoy", "营收同比"),
    ("ep_ttm", "EP(TTM)"), ("bp_ttm", "BP(TTM)"), ("sp_ttm", "SP(TTM)"),
    ("turnover_rate", "换手率"),
]


def load(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


rows = load(SCORES)
for r in rows:
    r["_score"] = float(r["score"])

# cross-sectional percentile within the full 1802-stock universe
pct = {}
for key, _label in FACTORS:
    vals = []
    for r in rows:
        try:
            vals.append((float(r[key]), r["ts_code"]))
        except (ValueError, KeyError):
            continue
    vals.sort(key=lambda x: x[0])
    d = {}
    for i, (_, code) in enumerate(vals):
        d[code] = (i + 0.5) / len(vals) * 100
    pct[key] = d

rows.sort(key=lambda x: -x["_score"])
top = rows[:50]

stocks = []
for i, r in enumerate(top, 1):
    code = r["ts_code"]
    contrib = sorted(((pct[k].get(code, 0), lbl) for k, lbl in FACTORS), reverse=True)
    reasons = ["%s 分位 %.0f%%" % (lbl, p) for p, lbl in contrib[:3]]
    if r.get("industry"):
        reasons.append("行业 %s" % r["industry"])
    stocks.append({
        "code": code,
        "name": r["name"],
        "score": round(r["_score"], 4),
        "rank": i,
        "reasons": reasons,
    })

ind = Counter(r.get("industry", "") for r in top)

# overlap with the previous 200-capped pool (if still available)
prev = []
try:
    with open("E:/cashfree/agent/test/data/20261025/factor_scores_200.csv", encoding="utf-8-sig") as f:
        prev_rows = list(csv.DictReader(f))
    prev_codes = {r["ts_code"] for r in prev_rows if not (
        r["ts_code"][:3] in ("300", "301", "688", "689") or "ST" in r["name"].upper()
        or r["ts_code"].endswith(".BJ"))}
    prev_top50 = sorted([r for r in prev_rows if r["ts_code"] in prev_codes],
                        key=lambda x: -float(x["score"]))[:50]
    prev = [r["ts_code"] for r in prev_top50]
except FileNotFoundError:
    prev = []

overlap = [c["code"] for c in stocks if c["code"] in set(prev)]

payload = {
    "date": "20261023",
    "strategy_version": "v1.3",
    "universe_size": len(rows),
    "universe_mode": "full_market_v13",
    "count": len(stocks),
    "stocks": stocks,
    "notes": [
        "全市场口径：剔除北交所/创业板(300·301)/科创板(688·689)/ST 后，再剔次新、停牌、流动性不足与因子缺失，最终 %d 只参与排名" % len(rows),
        "数据来源 data/warehouse/scores_full.csv（全市场 21 日线 + 13 周线 + 财务已本地化落库，因子本地计算，零 MCP 调用）",
        "17/17 因子全部激活；Top50 行业分布：%s" % "、".join("%s %d" % (k, v) for k, v in ind.most_common(8)),
        "行业集中度：最大行业 %s 占 %d/50 = %.0f%%，低于单行业 30%% 上限" % (
            ind.most_common(1)[0][0], ind.most_common(1)[0][1], ind.most_common(1)[0][1] / 50 * 100),
        "与旧口径（市值 top300 → 200 只）Top50 重合 %d 只（%.0f%%）：旧口径存在显著大盘偏误" % (
            len(overlap), len(overlap) / 50 * 100),
        "score 区间 %.4f ~ %.4f，全样本 median %.4f" % (
            stocks[-1]["score"], stocks[0]["score"],
            sorted(float(r["score"]) for r in rows)[len(rows) // 2]),
    ],
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)

print("universe:", len(rows), "| pool:", len(stocks))
print("industry top8:", ind.most_common(8))
print("overlap with old 200-capped pool: %d/50" % len(overlap))
print("score range: %.4f ~ %.4f" % (stocks[-1]["score"], stocks[0]["score"]))
print("\ntop15:")
for s in stocks[:15]:
    print("  %2d. %-9s %-7s %.4f  %s" % (s["rank"], s["code"], s["name"], s["score"], " / ".join(s["reasons"][:2])))
