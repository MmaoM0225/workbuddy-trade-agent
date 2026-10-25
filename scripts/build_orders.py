# -*- coding: utf-8 -*-
"""建仓经理：watchlist → 建仓计划 → test/state/orders.json（绝不写 state/）"""
import csv
import glob
import json
import os
import statistics

ROOT = r"E:\cashfree\agent"
WH = os.path.join(ROOT, "data", "warehouse")
WATCHLIST = os.path.join(ROOT, "test", "state", "watchlist.json")
REGIME = os.path.join(ROOT, "state", "regime.json")
POSITIONS = os.path.join(ROOT, "state", "positions.json")
PARAMS = os.path.join(ROOT, "knowledge", "params_v1.3.json")
OUT = os.path.join(ROOT, "test", "state", "orders.json")
SCORES = os.path.join(WH, "scores_full.csv")
MAX_POSITIONS = 10


def read_csv(p):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def fnum(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


wl = json.load(open(WATCHLIST, encoding="utf-8"))
regime = json.load(open(REGIME, encoding="utf-8"))
positions = json.load(open(POSITIONS, encoding="utf-8"))
params = json.load(open(PARAMS, encoding="utf-8"))
scores = {r["ts_code"]: r for r in read_csv(SCORES)}

regime_name = regime.get("regime", "neutral")
base_pct = params["regime_base_position_pct"].get(regime_name, 50)
lim = params["position_limits"]
capital = params["capital"]["initial_sim_capital_cny"]
print(f"regime={regime_name} base={base_pct}% capital={capital}")

# daily bars for price zones
daily = {}
for p in sorted(glob.glob(os.path.join(WH, "daily", "*.csv"))):
    for r in read_csv(p):
        daily.setdefault(r["ts_code"], []).append(
            (os.path.basename(p)[:-4], fnum(r["close"]), fnum(r["high"]), fnum(r["low"])))
for c in daily:
    daily[c].sort()

items = [i for i in wl["items"] if i["verdict"] == "buy_watch"][:MAX_POSITIONS]
if not items:
    out = {"date": "20261023", "orders": [], "notes": {"reason": "无 buy_watch 标的"}}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("no buy_watch items")
    raise SystemExit

# held positions (empty currently)
held = {p.get("code") for p in (positions.get("positions") or [])}

# weight: quality-score proportional within base position
qs_sum = sum(i["quality_score"] for i in items)
raw = []
for i in items:
    w = i["quality_score"] / qs_sum * base_pct
    w = min(w, lim["max_single_weight_pct"])
    if w < lim["min_order_weight_pct"]:
        continue
    raw.append((i, w))

# sector cap
sector_total = {}
final = []
for i, w in sorted(raw, key=lambda x: -x[1]):
    sec = (scores.get(i["code"]) or {}).get("industry", "未知")
    if sector_total.get(sec, 0) + w > lim["max_sector_weight_pct"]:
        print(f"  skip {i['name']} ({sec}) sector cap")
        continue
    sector_total[sec] = sector_total.get(sec, 0) + w
    final.append((i, w, sec))

orders = []
for idx, (i, w, sec) in enumerate(final, 1):
    code = i["code"]
    bars = daily.get(code, [])
    if not bars:
        print(f"  skip {code}: no daily bars")
        continue
    last_close = bars[-1][1]
    lows = [b[3] for b in bars if b[3] is not None]
    highs = [b[2] for b in bars if b[2] is not None]
    low20, high20 = min(lows), max(highs)
    span = high20 - low20
    if span <= 0:
        span = max(last_close * 0.05, 0.01)
    z1 = [round(low20, 2), round(low20 + span / 3, 2)]
    z2 = [round(low20 + span / 3, 2), round(low20 + 2 * span / 3, 2)]
    ref1 = (z1[0] + z1[1]) / 2
    first_pct = 40
    if first_pct > lim["first_tranche_max_pct_of_target"]:
        first_pct = lim["first_tranche_max_pct_of_target"]
    stop = min(round(low20 * 0.98, 2), round(ref1 * (1 - params["risk"]["single_stop_loss_pct"] / 100), 2))
    tp_candidate = round(ref1 * (1 + params["risk"]["single_take_profit_pct"] / 100), 2)
    tp = min(tp_candidate, round(high20, 2)) if high20 > ref1 else tp_candidate

    orders.append({
        "id": f"ORD-20261023-{idx:03d}",
        "side": "buy",
        "code": code,
        "name": i["name"],
        "industry": sec,
        "target_weight_pct": round(w, 2),
        "target_amount_cny": round(capital * w / 100, 0),
        "tranches": [
            {"pct": first_pct, "price_zone": z1, "ref_price": round(ref1, 2)},
            {"pct": 100 - first_pct, "price_zone": z2, "ref_price": round((z2[0] + z2[1]) / 2, 2)},
        ],
        "stop_loss": stop,
        "take_profit": tp,
        "last_close": last_close,
        "quality_score": i["quality_score"],
        "rationale": i["thesis"],
        "risks": i["risks"],
        "status": "planned_demo",
        "notes": "彩排订单，禁止执行；行情基准 20261023",
    })

total_w = sum(o["target_weight_pct"] for o in orders)
out = {
    "date": "20261023",
    "mode": "rehearsal",
    "regime": regime_name,
    "base_position_pct": base_pct,
    "planned_total_weight_pct": round(total_w, 2),
    "planned_total_amount_cny": round(capital * total_w / 100, 0),
    "cash_reserve_pct": round(100 - total_w, 2),
    "orders": orders,
    "notes": {
        "warning": "本文件为彩排产物，status=planned_demo，持仓管家不会执行；正式订单只写 state/orders.json",
        "sector_weights": {k: round(v, 2) for k, v in sector_total.items()},
        "weight_formula": f"{regime_name} base {base_pct}% × quality_score 占比，单票上限 {lim['max_single_weight_pct']}%，行业上限 {lim['max_sector_weight_pct']}%",
        "hard_rule": "所有订单均带 stop_loss 与 take_profit（R-003）",
    },
}
json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

print(f"\norders: {len(orders)}, total weight {total_w:.1f}%, amount {capital*total_w/100:,.0f} CNY")
for o in orders:
    print(f"  {o['name']:<8} {o['code']} w={o['target_weight_pct']:.1f}% 档位{o['tranches'][0]['price_zone']} SL={o['stop_loss']} TP={o['take_profit']}")
print(f"\nwrote {OUT}")
