#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Position builder rehearsal under params v1.4.

Changes vs v1.3 run:
  - holdings count constrained to 8-12 (default 10), sector-diversified
  - weights normalized: weight_i = base_pos * qs_i / sum(qs of N), clamped to [3,15]
  - NO amount fields: position manager computes money/shares at execution time
"""
import csv
import glob
import json

BASE = "E:/cashfree/agent/"
WATCH = BASE + "test/state/watchlist.json"
REGIME = BASE + "test/state/regime.json"
POSITIONS = BASE + "test/state/positions.json"
PARAMS = BASE + "knowledge/params_v1.4.json"
OUT = BASE + "test/state/orders.json"
DAILY_DIR = BASE + "data/warehouse/daily/"

watch = json.load(open(WATCH, encoding="utf-8"))
regime = json.load(open(REGIME, encoding="utf-8"))
positions = json.load(open(POSITIONS, encoding="utf-8"))
params = json.load(open(PARAMS, encoding="utf-8"))

lim = params["position_limits"]
base_pos = params["regime_base_position_pct"][regime["regime"]]
MAX_SINGLE = lim["max_single_weight_pct"]
MIN_SINGLE = lim["min_single_weight_pct"]
MAX_SECTOR = lim["max_sector_weight_pct"]
MIN_H = lim["min_holdings"]
MAX_H = lim["max_holdings"]
FIRST_CAP = lim["first_tranche_max_pct_of_target"] / 100
SL = params["risk"]["single_stop_loss_pct"] / 100
TP = params["risk"]["single_take_profit_pct"] / 100
TARGET_N = 10

held = {h.get("code") for h in positions.get("holdings", [])}

# ---- OHLC last 20 trading days ----
files = sorted(glob.glob(DAILY_DIR + "*.csv"))[-20:]
ohlc = {}
for fp in files:
    with open(fp, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            d = ohlc.setdefault(r["ts_code"], {"low": [], "high": [], "close": None})
            try:
                d["low"].append(float(r["low"]))
                d["high"].append(float(r["high"]))
                d["close"] = float(r["close"])
            except (ValueError, TypeError):
                continue

# ---- industry lookup (watchlist has no sector field; take it from warehouse) ----
industry = {}
with open(BASE + "data/warehouse/scores_full.csv", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        industry[r["ts_code"]] = (r.get("industry") or "").strip()

# ---- select N candidates, sector-diversified (max 2 per sector) ----
cands = [it for it in watch["items"] if it["code"] not in held]
cands.sort(key=lambda x: -x["quality_score"])
selected, sector_cnt = [], {}
for it in cands:
    sector = industry.get(it["code"]) or "未分类"
    if sector_cnt.get(sector, 0) >= 2:
        continue
    if len(selected) >= TARGET_N:
        break
    if not ohlc.get(it["code"], {}).get("close"):
        continue
    it["_sector"] = sector
    selected.append(it)
    sector_cnt[sector] = sector_cnt.get(sector, 0) + 1


# ---- normalized weights with iterative clamp (never breaks the 15% cap) ----
def allocate(qs_map, total, lo, hi, iters=30):
    s = sum(qs_map.values())
    w = {c: total * q / s for c, q in qs_map.items()}
    for _ in range(iters):
        w = {c: min(max(v, lo), hi) for c, v in w.items()}
        gap = total - sum(w.values())
        if abs(gap) < 0.01:
            break
        free = [c for c in w if lo + 0.01 < w[c] < hi - 0.01]
        if not free:
            break
        share = sum(w[c] for c in free)
        for c in free:
            w[c] += gap * (w[c] / share if share else 1.0 / len(free))
    return w


weights = allocate({it["code"]: it["quality_score"] for it in selected},
                   base_pos, MIN_SINGLE, MAX_SINGLE)

# ---- build orders ----
orders = []
for i, it in enumerate(selected, 1):
    code = it["code"]
    o = ohlc[code]
    min20, max20 = min(o["low"]), max(o["high"])
    close = o["close"]
    span = max20 - min20
    z1_lo, z1_hi = round(min20, 2), round(min20 + span / 3, 2)
    z2_lo, z2_hi = z1_hi, round(max20, 2)
    ref = round(min(max(close, z1_lo), z1_hi), 2)

    tw = round(weights[code], 2)
    t1 = round(tw * FIRST_CAP, 2)
    t2 = round(tw - t1, 2)

    orders.append({
        "id": "ORD-20261023-%02d" % i,
        "side": "buy",
        "code": code,
        "name": it["name"],
        "sector": it["_sector"],
        "quality_score": it["quality_score"],
        "target_weight_pct": tw,
        "tranches": [
            {"seq": 1, "pct": t1, "price_zone": [z1_lo, z1_hi], "status": "planned"},
            {"seq": 2, "pct": t2, "price_zone": [z2_lo, z2_hi], "status": "planned"},
        ],
        "stop_loss": round(min(round(min20 * 0.98, 2), round(ref * (1 - SL), 2)), 2),
        "take_profit": round(ref * (1 + TP), 2),
        "ref_price": ref,
        "last_close": round(close, 2),
        "rationale": it["thesis"],
        "risks": it["risks"],
        "status": "planned",
        "notes": "首档位于 20 日区间下三分位 [%.2f, %.2f]，10-23 收盘 %.2f；金额与股数由持仓管家执行时按总资产计算"
                 % (z1_lo, z1_hi, close),
    })

total = sum(o["target_weight_pct"] for o in orders)
sector_w = {}
for o in orders:
    sector_w[o["sector"]] = sector_w.get(o["sector"], 0) + o["target_weight_pct"]

payload = {
    "date": "20261023",
    "params_version": params["version"],
    "regime": regime["regime"],
    "regime_base_position_pct": base_pos,
    "planned_holdings": len(orders),
    "planned_total_weight_pct": round(total, 2),
    "cash_reserved_pct": round(100 - total, 2),
    "orders": orders,
    "notes": [
        "彩排运行，仅写 test/state/orders.json；正式 orders.json 未被触碰",
        "params v1.4：持仓数量约束 %d~%d 只（本次 %d 只）" % (MIN_H, MAX_H, len(orders)),
        "权重归一化：weight_i = %.0f × qs_i / Σqs，clamp 到 [%.0f%%, %.0f%%] 后重新归一化，合计 %.2f%%"
        % (base_pos, MIN_SINGLE, MAX_SINGLE, total),
        "单票权重区间 %.2f%% ~ %.2f%%（v1.3 旧规则下为 15%% 顶格 × 3 只）"
        % (min(o["target_weight_pct"] for o in orders), max(o["target_weight_pct"] for o in orders)),
        "单行业最大 %s %.2f%%，上限 %.0f%%" % (
            max(sector_w, key=sector_w.get), max(sector_w.values()), MAX_SECTOR),
        "订单不含金额与股数：持仓管家执行时按当日实际总资产 × 权重计算，股数按 100 股整数倍取整",
        "价格区间基于 2026-09-23~2026-10-23 共 20 个交易日高低点三等分，首档取下三分位",
        "止损 = min(20日最低×0.98, 首档参考价×%.2f)；止盈 = 首档参考价×%.2f" % (1 - SL, 1 + TP),
    ],
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)

print("params=%s | N=%d (constraint %d~%d) | total=%.2f%% | cash=%.1f%%"
      % (params["version"], len(orders), MIN_H, MAX_H, total, 100 - total))
print("\n%-9s %-8s %-8s %6s %6s %6s %6s %6s"
      % ("code", "name", "sector", "wt%", "t1%", "zone1", "SL", "TP"))
for o in orders:
    print("%-9s %-8s %-8s %6.2f %6.2f [%5.2f,%5.2f] %6.2f %6.2f"
          % (o["code"], o["name"], o["sector"], o["target_weight_pct"],
             o["tranches"][0]["pct"], o["tranches"][0]["price_zone"][0],
             o["tranches"][0]["price_zone"][1], o["stop_loss"], o["take_profit"]))
print("\nsector weights:", {k: round(v, 2) for k, v in sector_w.items()})
print("amount fields present:", any("amount" in str(o).lower() for o in orders))
