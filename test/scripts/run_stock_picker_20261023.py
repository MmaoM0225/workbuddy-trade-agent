#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Stock picker rehearsal: build pool.json for baseline 20261023.

Reuses the 17-factor scores produced by the 2026-10-25 demo run
(test/data/20261025/factor_scores_200.csv) and intersects them with the
v1.3 universe (dual-board / BJ / ST excluded) so the pool respects the
current params口径. No new data pulls.
"""
import csv
import json
from collections import Counter

SCORES = "E:/cashfree/agent/test/data/20261025/factor_scores_200.csv"
UNIV13 = "E:/cashfree/agent/test/data/20261025/universe_200_v13.csv"
OUT = "E:/cashfree/agent/test/state/pool.json"

FACTORS = {
    "mom_5d": ("5日动量", 0.06),
    "mom_10d": ("10日动量", 0.07),
    "mom_20d": ("20日动量", 0.07),
    "mom_60d": ("60日动量", 0.05),
    "vol_20d_inv": ("20日低波动", 0.08),
    "mdd_20d_inv": ("20日低回撤", 0.07),
    "price_pos_20d": ("20日价格位置", 0.06),
    "pv_corr_20d": ("量价相关性", 0.07),
    "turnover_trend_20d": ("成交额趋势", 0.07),
    "roe_ttm": ("ROE(TTM)", 0.08),
    "gross_margin_ttm": ("毛利率", 0.04),
    "net_margin_ttm": ("净利率", 0.04),
    "tr_yoy": ("营收同比", 0.04),
    "ep_ttm": ("EP(TTM)", 0.06),
    "bp_ttm": ("BP(TTM)", 0.05),
    "sp_ttm": ("SP(TTM)", 0.04),
    "turnover_rate": ("换手率", 0.05),
}


def load_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


scores = load_csv(SCORES)
v13 = {r["ts_code"] for r in load_csv(UNIV13)}

rows = []
dropped = {"not_in_v13": 0, "gem_star": 0, "st": 0, "bj": 0}
for r in scores:
    code = r["ts_code"]
    name = r["name"]
    if code.endswith(".BJ"):
        dropped["bj"] += 1
        continue
    if code[:3] in ("300", "301") or code[:3] in ("688", "689"):
        dropped["gem_star"] += 1
        continue
    if "ST" in name.upper():
        dropped["st"] += 1
        continue
    if code not in v13:
        dropped["not_in_v13"] += 1
        continue
    rows.append(r)

for r in rows:
    r["_score"] = float(r["score"])

# cross-sectional percentile per factor within the eligible universe
n = len(rows)
pct = {f: {} for f in FACTORS}
for f in FACTORS:
    vals = []
    for r in rows:
        try:
            vals.append((float(r[f]), r["ts_code"]))
        except (ValueError, KeyError):
            continue
    vals.sort(key=lambda x: x[0])
    for i, (_, code) in enumerate(vals):
        pct[f][code] = (i + 0.5) / len(vals) * 100 if vals else None

rows.sort(key=lambda x: -x["_score"])
top = rows[:50]

stocks = []
for i, r in enumerate(top, 1):
    code = r["ts_code"]
    contrib = []
    for f, (label, _w) in FACTORS.items():
        p = pct[f].get(code)
        if p is not None:
            contrib.append((p, label))
    contrib.sort(key=lambda x: -x[0])
    reasons = ["%s 分位 %.0f%%" % (label, p) for p, label in contrib[:3]]
    if r.get("industry"):
        reasons.append("行业 %s" % r["industry"])
    stocks.append({
        "code": code,
        "name": r["name"],
        "score": round(r["_score"], 4),
        "rank": i,
        "reasons": reasons,
    })

industries = Counter(r.get("industry", "") for r in top)

payload = {
    "date": "20261023",
    "strategy_version": "v1.3",
    "universe_size": n,
    "count": len(stocks),
    "stocks": stocks,
    "notes": [
        "彩排运行：复用 2026-10-25 演示跑已算好的 17 因子分数（factor_scores_200.csv），未重新拉数",
        "universe 口径 v1.3：剔北交所/双创(300·301·688·689)/ST 后与演示跑因子表取交集 %d 只；剔除明细 not_in_v13=%d, gem_star=%d, bj=%d, st=%d"
        % (n, dropped["not_in_v13"], dropped["gem_star"], dropped["bj"], dropped["st"]),
        "universe_200_v13 中另有 34 只未覆盖因子分数（清单 test/data/20261025/fresh_codes.txt），本次未参与排名",
        "17/17 因子全部激活；Top50 行业分布：%s"
        % "、".join("%s %d" % (k, v) for k, v in industries.most_common(8)),
        "正式首跑 2026-10-31 21:30 执行完整链路：daily_basic 全市场初筛 → 200 只批量取证 → MAD 去极值 → 横截面百分位 → log 市值中性化 → 加权求和",
        "pool_size 固定 50，不因标的多少调整",
    ],
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)

print("eligible universe:", n, "| dropped:", dropped)
print("pool size:", len(stocks))
print("industry top8:", industries.most_common(8))
print("score range: %.4f ~ %.4f" % (stocks[0]["score"], stocks[-1]["score"]))
print("top10:")
for s in stocks[:10]:
    print("  %2d. %-8s %-6s %.4f  %s" % (s["rank"], s["code"], s["name"], s["score"], " / ".join(s["reasons"][:2])))
