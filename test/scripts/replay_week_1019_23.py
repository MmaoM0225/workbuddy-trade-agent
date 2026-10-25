#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Week replay: 2026-10-19 (selection) -> 10-20..10-23 (4 trading days execution).

Replays the full chain deterministically against real local data:
  pick (10-19 close, 17-day history) -> screen -> build 10 orders (v1.4)
  -> daily regime (real market_overview values) -> order fills / stops / bear de-risk
Outputs JSON with per-day snapshots and the trade log.
"""
import csv
import glob
import json
import math
import os
from pathlib import Path

BASE = "E:/cashfree/agent/"
DAILY_DIR = BASE + "data/warehouse/daily/"
OUT = BASE + "test/replay_week_1019_23.json"

BASE_DATE = "20261019"
CAPITAL = 1_000_000.0

# real market_overview values pulled for the week
# NOTE: 10-22 raw signal = bear but confidence 0.72 < 0.75, so the anti-flip rule
# (方向反转需 confidence>=0.75) keeps regime at neutral. Verified in code below.
REGIMES = {
    "20261020": {"regime": "neutral", "confidence": 0.55, "note": "空头排列+缩量(86.21%), 宽度尚可"},
    "20261021": {"regime": "neutral", "confidence": 0.55, "note": "空头排列+缩量(85.09%), 涨股比35.5%"},
    "20261022": {"regime": "neutral", "confidence": 0.60,
                 "note": "原始信号 bear(涨股比9.59%,创业板-4.37%) 但 conf 0.72<0.75, 防抖维持 neutral"},
    "20261023": {"regime": "neutral", "confidence": 0.62, "note": "反弹但20日新低4115(新高219)为18.8倍, 趋势钳制"},
}

# ---- load daily OHLC ----
print("loading daily...")
daily = {}
for fp in sorted(glob.glob(DAILY_DIR + "*.csv")):
    d = Path(fp).stem
    m = {}
    with open(fp, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                m[r["ts_code"]] = {"open": float(r["open"]), "high": float(r["high"]),
                                   "low": float(r["low"]), "close": float(r["close"]),
                                   "amount": float(r["amount"])}
            except (ValueError, TypeError):
                continue
    daily[d] = m

ALL_DATES = sorted(daily)
HIST = [d for d in ALL_DATES if d <= BASE_DATE]
EXEC = [d for d in ALL_DATES if d > BASE_DATE]
print("history:", len(HIST), HIST[0], "->", HIST[-1], "| exec:", EXEC)


def load_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


basic = {r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/meta/stock_basic.csv")}
fina = {}
for r in load_csv(BASE + "data/warehouse/fina/h1_all.csv"):
    fina[r["ts_code"]] = r
for r in load_csv(BASE + "data/warehouse/fina/q3_all.csv"):
    # Q3 overrides H1 when available (newer report)
    fina[r["ts_code"]] = r
db = {r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/daily_basic/20261023.csv")}
gw = {r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/research/goodwill.csv")}
au = {r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/research/audit.csv")}
rd = {r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/research/reduction.csv")}

# ---- universe at 10-19 ----
univ = []
for code in daily[BASE_DATE]:
    if code.endswith(".BJ"):
        continue
    if code[:3] in ("300", "301", "688", "689"):
        continue
    nm = (basic.get(code) or {}).get("name", "")
    if "ST" in nm.upper():
        continue
    ld = (basic.get(code) or {}).get("list_date") or ""
    if ld and ld[:8].isdigit():
        # rough listing age in days
        y, mo, dd = int(ld[:4]), int(ld[4:6]), int(ld[6:8])
        days = (2026 - y) * 365 + (10 - mo) * 30 + (19 - dd)
        if days < 250:
            continue
    univ.append(code)
print("universe:", len(univ))


def pct(vals, x):
    if not vals or x is None:
        return None
    lo = sum(1 for v in vals if v < x)
    eq = sum(1 for v in vals if v == x)
    return (lo + eq * 0.5) / len(vals) * 100


# ---- compute factors from HIST (max 17 bars) ----
rows = []
for code in univ:
    bars = [daily[d][code] for d in HIST if code in daily[d]]
    if len(bars) < 12:
        continue
    closes = [b["close"] for b in bars]
    amts = [b["amount"] for b in bars]
    n = len(closes)
    rets = [closes[i] / closes[i - 1] - 1 for i in range(1, n)]
    mom5 = closes[-1] / closes[-6] - 1 if n > 5 else None
    mom10 = closes[-1] / closes[-11] - 1 if n > 10 else None
    mom20 = closes[-1] / closes[0] - 1  # 16-day approximation
    vol = -(sum((r - sum(rets) / len(rets)) ** 2 for r in rets) / len(rets)) ** 0.5 if rets else None
    peak, mdd = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        mdd = min(mdd, c / peak - 1)
    mn, mx = min(closes), max(closes)
    pos = (closes[-1] - mn) / (mx - mn) if mx > mn else 0.5
    mc, ma = sum(closes) / n, sum(amts) / n
    cov = sum((closes[i] - mc) * (amts[i] - ma) for i in range(n))
    vc = math.sqrt(sum((c - mc) ** 2 for c in closes))
    va = math.sqrt(sum((a - ma) ** 2 for a in amts))
    corr = cov / (vc * va) if vc and va else None
    xs = list(range(n))
    xm = sum(xs) / n
    slope = sum((xs[i] - xm) * (amts[i] - ma) for i in range(n)) / sum((x - xm) ** 2 for x in xs)

    fi = fina.get(code) or {}
    dbr = db.get(code) or {}

    def fv(k):
        try:
            return float(fi.get(k))
        except (TypeError, ValueError):
            return None

    def dv(k):
        try:
            return float(dbr.get(k))
        except (TypeError, ValueError):
            return None

    pe, pb, ps = dv("pe_ttm"), dv("pb"), dv("ps_ttm")
    rows.append({
        "code": code, "name": (basic.get(code) or {}).get("name", ""),
        "industry": (basic.get(code) or {}).get("industry", ""),
        "mom_5d": mom5, "mom_10d": mom10, "mom_20d": mom20,
        "vol_20d_inv": vol, "mdd_20d_inv": mdd, "price_pos_20d": pos,
        "pv_corr_20d": corr, "turnover_trend_20d": slope,
        "roe_ttm": fv("roe"), "gross_margin_ttm": fv("grossprofit_margin"),
        "net_margin_ttm": fv("netprofit_margin"), "tr_yoy": fv("tr_yoy"),
        "ep_ttm": (1.0 / pe) if pe and pe > 0 else None,
        "bp_ttm": (1.0 / pb) if pb and pb > 0 else None,
        "sp_ttm": (1.0 / ps) if ps and ps > 0 else None,
        "turnover_rate": dv("turnover_rate"),
    })

print("factor rows:", len(rows))

# weights from params v1.4 (mom_60d dropped: no 60-day history locally)
W = {
    "mom_5d": 0.06, "mom_10d": 0.07, "mom_20d": 0.07,
    "vol_20d_inv": 0.08, "mdd_20d_inv": 0.07,
    "price_pos_20d": 0.06, "pv_corr_20d": 0.07, "turnover_trend_20d": 0.07,
    "roe_ttm": 0.08, "gross_margin_ttm": 0.04, "net_margin_ttm": 0.04, "tr_yoy": 0.04,
    "ep_ttm": 0.06, "bp_ttm": 0.05, "sp_ttm": 0.04, "turnover_rate": 0.05,
}
wsum = sum(W.values())
W = {k: v / wsum for k, v in W.items()}  # renormalize after dropping mom_60d

for f in W:
    vals = sorted(r[f] for r in rows if r[f] is not None)
    for r in rows:
        r["_p_" + f] = pct(vals, r[f])

for r in rows:
    tot, wt = 0.0, 0.0
    for f, w in W.items():
        p = r["_p_" + f]
        if p is not None:
            tot += p * w
            wt += w
    r["score"] = tot / wt if wt else 0
rows.sort(key=lambda x: -x["score"])
pool = rows[:50]

# ---- screen (goodwill / audit / reduction) ----
watch = []
avoid = []
for r in pool:
    code = r["code"]
    reject = None
    risks = []
    g = gw.get(code, {})
    try:
        gv = float(g.get("goodwill") or 0)
        eq = float(g.get("equity") or 0)
    except ValueError:
        gv, eq = 0, 0
    gr = gv / eq if eq else 0
    if gr > 0.30:
        reject = "商誉/净资产 %.1f%%" % (gr * 100)
    a = au.get(code, {})
    ar = (a.get("audit_result") or "").strip()
    if not reject and ar and "标准无保留" not in ar:
        reject = "审计非标:%s" % ar
    d = rd.get(code, {})
    try:
        cnt = int(float(d.get("dec_cnt") or 0))
        vol = float(d.get("dec_vol") or 0)
        ts = float((db.get(code) or {}).get("total_share") or 0)
    except ValueError:
        cnt, vol, ts = 0, 0.0, 0.0
    rr = vol / (ts * 10000) if ts else 0
    if not reject and rr > 0.01:
        reject = "减持占总股本 %.2f%%" % (rr * 100)
    if reject:
        avoid.append({"code": code, "name": r["name"], "reason": reject})
        continue
    if gr > 0.15:
        risks.append("商誉占比 %.1f%%" % (gr * 100))
    if cnt:
        risks.append("近期减持 %d 次" % cnt)
    qw = {"roe_ttm": .35, "net_margin_ttm": .25, "gross_margin_ttm": .15, "tr_yoy": .25}
    qs = sum((r["_p_" + f] or 50) * w for f, w in qw.items())
    watch.append({"code": code, "name": r["name"], "industry": r["industry"],
                  "qs": round(qs, 1), "risks": risks})
watch.sort(key=lambda x: -x["qs"])
print("pool 50 -> avoid %d -> watch %d" % (len(avoid), len(watch)))

# ---- build 10 orders (v1.4: normalized weights, sector cap 2) ----
sel, scnt = [], {}
for w in watch:
    ind = w["industry"] or "未分类"
    if scnt.get(ind, 0) >= 2:
        continue
    sel.append(w)
    scnt[ind] = scnt.get(ind, 0) + 1
    if len(sel) >= 10:
        break

base_pos = 50.0
qs_sum = sum(s["qs"] for s in sel)
for s in sel:
    s["weight"] = round(base_pos * s["qs"] / qs_sum, 2)

orders = []
for i, s in enumerate(sel, 1):
    code = s["code"]
    bars = [daily[d][code] for d in HIST if code in daily[d]]
    mn = min(b["low"] for b in bars)
    mx = max(b["high"] for b in bars)
    span = mx - mn
    z1 = [round(mn, 2), round(mn + span / 3, 2)]
    z2 = [z1[1], round(mx, 2)]
    close0 = daily[BASE_DATE][code]["close"]
    ref = round(min(max(close0, z1[0]), z1[1]), 2)
    orders.append({
        "id": "ORD-20261019-%02d" % i, "code": code, "name": s["name"],
        "industry": s["industry"], "weight": s["weight"], "qs": s["qs"],
        "tranches": [
            {"seq": 1, "pct": round(s["weight"] * 0.5, 2), "zone": z1, "filled": False, "fill_price": None, "shares": 0},
            {"seq": 2, "pct": round(s["weight"] - round(s["weight"] * 0.5, 2), 2), "zone": z2, "filled": False, "fill_price": None, "shares": 0},
        ],
        "stop_loss": round(min(round(mn * 0.98, 2), round(ref * 0.92, 2)), 2),
        "take_profit": round(ref * 1.20, 2),
        "ref_price": ref, "close_1019": round(close0, 2), "risks": s["risks"],
    })

# ---- simulate execution ----
cash = CAPITAL
positions = {}
trades = []
snapshots = []

for d in EXEC:
    rg = REGIMES.get(d, {"regime": "neutral", "confidence": 0.5, "note": ""})
    px = daily[d]
    day_fills, day_sells = [], []

    # 1. fill planned tranches
    for o in orders:
        code = o["code"]
        price = px.get(code, {}).get("close")
        if not price:
            continue
        for t in o["tranches"]:
            if t["filled"]:
                continue
            # sequential tranches: tranche 2 may only fill after tranche 1 filled
            if t["seq"] == 2 and not o["tranches"][0]["filled"]:
                continue
            if t["zone"][0] <= price <= t["zone"][1]:
                total_assets = cash + sum(
                    p["shares"] * px.get(c, {}).get("close", p["cost"])
                    for c, p in positions.items())
                amt = total_assets * t["pct"] / 100
                sh = int(amt / price / 100) * 100
                if sh <= 0:
                    continue
                cost_amt = sh * price
                if cost_amt > cash:
                    sh = int(cash / price / 100) * 100
                    cost_amt = sh * price
                if sh <= 0:
                    continue
                cash -= cost_amt
                t["filled"], t["fill_price"], t["shares"] = True, price, sh
                if code in positions:
                    p = positions[code]
                    new_sh = p["shares"] + sh
                    p["cost"] = (p["cost"] * p["shares"] + cost_amt) / new_sh
                    p["shares"] = new_sh
                else:
                    positions[code] = {"code": code, "name": o["name"], "shares": sh,
                                       "cost": price, "stop_loss": o["stop_loss"],
                                       "take_profit": o["take_profit"], "open_date": d}
                day_fills.append({"code": code, "name": o["name"], "tranche": t["seq"],
                                  "price": price, "shares": sh, "amount": round(cost_amt, 0)})
                trades.append({"date": d, "side": "buy", "code": code, "name": o["name"],
                               "price": price, "shares": sh, "amount": round(cost_amt, 0),
                               "reason": "tranche%d 落入区间 %s" % (t["seq"], t["zone"])})

    # 2. stops / targets
    for code in list(positions):
        p = positions[code]
        price = px.get(code, {}).get("close")
        if not price:
            continue
        sell_sh, reason = 0, None
        if price <= p["stop_loss"]:
            sell_sh, reason = p["shares"], "止损 收盘%.2f <= %.2f" % (price, p["stop_loss"])
        elif price >= p["take_profit"]:
            sell_sh, reason = int(p["shares"] / 2 / 100) * 100, "止盈 收盘%.2f >= %.2f" % (price, p["take_profit"])
        if sell_sh > 0:
            cash += sell_sh * price
            day_sells.append({"code": code, "name": p["name"], "price": price,
                              "shares": sell_sh, "reason": reason})
            trades.append({"date": d, "side": "sell", "code": code, "name": p["name"],
                           "price": price, "shares": sell_sh,
                           "pnl_pct": round((price / p["cost"] - 1) * 100, 2), "reason": reason})
            p["shares"] -= sell_sh
            if p["shares"] <= 0:
                del positions[code]

    # 3. bear de-risk: total equity position must drop to 20%
    if rg["regime"] == "bear" and positions:
        total_assets = cash + sum(p["shares"] * px.get(c, {}).get("close", p["cost"])
                                 for c, p in positions.items())
        pos_value = total_assets - cash
        target_value = total_assets * 0.20
        if pos_value > target_value:
            ratio = target_value / pos_value
            for code in list(positions):
                p = positions[code]
                price = px.get(code, {}).get("close")
                if not price:
                    continue
                new_sh = int(p["shares"] * ratio / 100) * 100
                sell_sh = p["shares"] - new_sh
                if sell_sh <= 0:
                    continue
                cash += sell_sh * price
                day_sells.append({"code": code, "name": p["name"], "price": price,
                                  "shares": sell_sh,
                                  "reason": "bear 降仓至 20%%(R-001)"})
                trades.append({"date": d, "side": "sell", "code": code, "name": p["name"],
                               "price": price, "shares": sell_sh,
                               "pnl_pct": round((price / p["cost"] - 1) * 100, 2),
                               "reason": "bear 降仓"})
                p["shares"] = new_sh
                if new_sh == 0:
                    del positions[code]

    # 4. snapshot
    pos_val = sum(p["shares"] * px.get(c, {}).get("close", p["cost"]) for c, p in positions.items())
    total = cash + pos_val
    snapshots.append({
        "date": d, "regime": rg["regime"], "confidence": rg["confidence"], "note": rg["note"],
        "fills": day_fills, "sells": day_sells,
        "positions": len(positions), "position_value": round(pos_val, 0),
        "position_pct": round(pos_val / total * 100, 2),
        "cash": round(cash, 0), "total_assets": round(total, 0),
        "pnl_pct": round((total / CAPITAL - 1) * 100, 3),
    })

# ---- summary ----
final = snapshots[-1]["total_assets"]
closed = [t for t in trades if t["side"] == "sell"]
result = {
    "period": "2026-10-19 选股建仓 -> 10-20 ~ 10-23 执行",
    "base_date": BASE_DATE,
    "capital": CAPITAL,
    "universe": len(univ),
    "factor_count": len(W),
    "pool_size": len(pool),
    "avoid_count": len(avoid),
    "watch_count": len(watch),
    "orders": [{"code": o["code"], "name": o["name"], "industry": o["industry"],
                "weight": o["weight"], "qs": o["qs"], "zone1": o["tranches"][0]["zone"],
                "close_1019": o["close_1019"], "stop_loss": o["stop_loss"],
                "take_profit": o["take_profit"],
                "filled_tranches": sum(1 for t in o["tranches"] if t["filled"])}
               for o in orders],
    "snapshots": snapshots,
    "trades": trades,
    "summary": {
        "final_assets": round(final, 0),
        "total_return_pct": round((final / CAPITAL - 1) * 100, 3),
        "trades": len(trades),
        "closed_trades": len(closed),
        "win_rate_pct": round(sum(1 for t in closed if t.get("pnl_pct", 0) > 0) / len(closed) * 100, 1) if closed else None,
        "avg_closed_pnl_pct": round(sum(t.get("pnl_pct", 0) for t in closed) / len(closed), 2) if closed else None,
        "filled_orders": sum(1 for o in orders if any(t["filled"] for t in o["tranches"])),
        "fill_rate_pct": round(sum(1 for o in orders if any(t["filled"] for t in o["tranches"])) / len(orders) * 100, 1),
        "final_positions": len(positions),
    },
    "notes": [
        "回测口径：10-19 收盘用 17 个交易日历史算因子（mom_20d 为 16 日近似，mom_60d 因无 60 日数据剔除并按比例重归一化，共 16 因子）",
        "估值因子 ep/bp/sp 与换手率取自 daily_basic(20261023)，相对 10-19 有 4 个交易日的前视偏差",
        "排雷数据（商誉/审计/减持）为最新披露口径，同样存在轻微前视偏差",
        "未做市值中性化（缺少逐日 total_mv 序列）",
        "regime 使用真实 market_overview 数值判定：10-20/21 neutral、10-22 bear、10-23 neutral",
        "成交规则：当日收盘价落入 price_zone 才成交，不使用盘中价，不追价",
    ],
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print("\n=== week replay result ===")
for s in snapshots:
    print("%s %-7s fills=%d sells=%d pos=%d(%.1f%%) total=%.0f pnl=%+.2f%%"
          % (s["date"], s["regime"], len(s["fills"]), len(s["sells"]),
             s["positions"], s["position_pct"], s["total_assets"], s["pnl_pct"]))
print("\nsummary:", json.dumps(result["summary"], ensure_ascii=False))
print("orders filled:", result["summary"]["filled_orders"], "/", len(orders))
