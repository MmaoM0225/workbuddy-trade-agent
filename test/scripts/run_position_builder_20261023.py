#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Position builder rehearsal: watchlist -> orders.json (planned buy orders).

All inputs local: watchlist.json / regime.json / params_v1.3.json / warehouse daily.
Writes ONLY to test/state/orders.json (production orders.json is executed by
position-manager at 23:20 on trading days and must never be touched here).
"""
import csv
import glob
import json

BASE = "E:/cashfree/agent/"
WATCH = BASE + "test/state/watchlist.json"
REGIME = BASE + "test/state/regime.json"
PARAMS = BASE + "knowledge/params_v1.3.json"
OUT = BASE + "test/state/orders.json"
DAILY_DIR = BASE + "data/warehouse/daily/"

watch = json.load(open(WATCH, encoding="utf-8"))
regime = json.load(open(REGIME, encoding="utf-8"))
params = json.load(open(PARAMS, encoding="utf-8"))

base_pos = params["regime_base_position_pct"][regime["regime"]]
max_single = params["position_limits"]["max_single_weight_pct"]
max_sector = params["position_limits"]["max_sector_weight_pct"]
min_weight = params["position_limits"]["min_order_weight_pct"]
first_tranche_cap = params["position_limits"]["first_tranche_max_pct_of_target"] / 100
sl_pct = params["risk"]["single_stop_loss_pct"] / 100
tp_pct = params["risk"]["single_take_profit_pct"] / 100
capital = params["capital"]["initial_sim_capital_cny"]

# ---- load last 20 trading days of OHLC ----
files = sorted(glob.glob(DAILY_DIR + "*.csv"))[-20:]
ohlc = {}
for fp in files:
    with open(fp, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            code = r["ts_code"]
            d = ohlc.setdefault(code, {"low": [], "high": [], "close": None})
            try:
                d["low"].append(float(r["low"]))
                d["high"].append(float(r["high"]))
                d["close"] = float(r["close"])
            except (ValueError, TypeError):
                continue

# ---- industry lookup from pool scores ----
ind = {}
with open(BASE + "data/warehouse/scores_full.csv", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        ind[r["ts_code"]] = r.get("industry", "")

orders = []
skipped = []
sector_used = {}
total = 0.0

for it in watch["items"]:
    code = it["code"]
    if total >= base_pos:
        skipped.append({"code": code, "name": it["name"], "reason": "总仓位已达 regime 基础仓位 %.0f%%" % base_pos})
        continue

    o = ohlc.get(code)
    if not o or not o["low"] or not o["close"]:
        skipped.append({"code": code, "name": it["name"], "reason": "日线数据缺失，无法计算价格区间"})
        continue

    min20, max20 = min(o["low"]), max(o["high"])
    close = o["close"]
    span = max20 - min20

    raw = base_pos * it["quality_score"] / 100.0
    target = min(raw, max_single)
    remaining = base_pos - total
    if target > remaining:
        target = remaining
    if target < min_weight:
        skipped.append({"code": code, "name": it["name"],
                        "reason": "剩余仓位 %.1f%% 低于最小建仓 %.1f%%" % (remaining, min_weight)})
        continue

    sector = ind.get(code, "未知")
    if sector_used.get(sector, 0) + target > max_sector:
        skipped.append({"code": code, "name": it["name"],
                        "reason": "行业 %s 累计 %.1f%% 将超 %.0f%% 上限" % (sector, sector_used.get(sector, 0) + target, max_sector)})
        continue

    # two tranches: first in the lower third of the 20-day range
    z1_lo, z1_hi = round(min20, 2), round(min20 + span / 3, 2)
    z2_lo, z2_hi = z1_hi, round(max20, 2)
    ref = round(min(max(close, z1_lo), z1_hi), 2)  # first-tranche reference price within zone 1

    t1 = round(target * first_tranche_cap, 2)
    t2 = round(target - t1, 2)

    stop_loss = round(min(round(min20 * 0.98, 2), round(ref * (1 - sl_pct), 2)), 2)
    take_profit = round(ref * (1 + tp_pct), 2)

    orders.append({
        "id": "ORD-20261023-%02d" % (len(orders) + 1),
        "side": "buy",
        "code": code,
        "name": it["name"],
        "sector": sector,
        "quality_score": it["quality_score"],
        "target_weight_pct": round(target, 2),
        "tranches": [
            {"seq": 1, "pct": t1, "price_zone": [z1_lo, z1_hi], "status": "planned"},
            {"seq": 2, "pct": t2, "price_zone": [z2_lo, z2_hi], "status": "planned"},
        ],
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "ref_price": ref,
        "last_close": round(close, 2),
        "amount_cny": round(capital * target / 100, 0),
        "rationale": it["thesis"],
        "risks": it["risks"],
        "status": "planned",
        "notes": "首档位于 20 日区间下三分位 [%.2f, %.2f]，收盘 %.2f" % (z1_lo, z1_hi, close),
    })
    total += target
    sector_used[sector] = sector_used.get(sector, 0) + target

payload = {
    "date": "20261023",
    "regime": regime["regime"],
    "regime_base_position_pct": base_pos,
    "planned_total_weight_pct": round(total, 2),
    "cash_reserved_pct": round(100 - total, 2),
    "order_count": len(orders),
    "capital_cny": capital,
    "orders": orders,
    "skipped": skipped,
    "notes": [
        "彩排运行，仅写 test/state/orders.json；正式 orders.json 未被触碰",
        "regime=%s → 基础仓位 %.0f%%；单票上限 %.0f%%、单行业上限 %.0f%%、最小建仓 %.0f%%" % (
            regime["regime"], base_pos, max_single, max_sector, min_weight),
        "target_weight = 基础仓位 × quality_score/100，超过 15%% 上限则截断为 15%%",
        "价格区间基于 2026-09-23~2026-10-23 共 20 个交易日的最高/最低价三等分，首档取低三分位",
        "止损 = min(20日最低×0.98, 首档参考价×0.92)；止盈 = 首档参考价×1.20",
        "入选 %d 只、跳过 %d 只；总仓位 %.1f%%，留存现金 %.1f%%" % (
            len(orders), len(skipped), total, 100 - total),
        "【设计问题待议】watchlist 内 quality_score 全部在 68~90，target=50×qs/100 必然 >15%% 从而全部撞单票上限，"
        "结果只能建 %d 只、组合分散度不足。建议 params v1.4 改为池内归一化分配（权重 = 50 × qs/Σqs）" % len(orders),
    ],
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False, indent=2)

print("regime=%s base=%.0f%% | orders=%d | total=%.1f%% | cash=%.1f%%"
      % (regime["regime"], base_pos, len(orders), total, 100 - total))
print("\n--- orders ---")
for o in orders:
    print("  %-9s %-8s %-6s tgt=%5.1f%%  zone1=[%.2f,%.2f]  close=%.2f  SL=%.2f TP=%.2f  金额=%.0f元"
          % (o["code"], o["name"], o["sector"], o["target_weight_pct"],
             o["tranches"][0]["price_zone"][0], o["tranches"][0]["price_zone"][1],
             o["last_close"], o["stop_loss"], o["take_profit"], o["amount_cny"]))
print("\n--- skipped (%d) ---" % len(skipped))
for s in skipped[:6]:
    print("  %-9s %-8s %s" % (s["code"], s["name"], s["reason"]))
print("  ...")
print("\nsector usage:", sector_used)
