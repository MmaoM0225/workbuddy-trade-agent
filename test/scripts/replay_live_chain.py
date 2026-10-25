#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Live-chain replay: event-driven, continuous account, no weekly liquidation.

Timeline mirrors the production schedule:
  every Fri after close : stock_picker -> researcher -> position_builder (new orders queued)
  every trading day     : data -> regime -> position_manager (expiry/fills/valuation/
                          stops/rotation/bear-de-risk/circuit) -> inspector
Holdings persist across weeks; orders survive until filled or expired (R-006);
rotation (R-007) compares holdings against the latest watchlist.
"""
import csv
import glob
import json
import math
import os
from pathlib import Path

BASE = "E:/cashfree/agent/"
DAILY_DIR = BASE + "data/warehouse/daily/"
IDX_FILE = BASE + "test/index_000001SH.json"
OUT_JSON = BASE + "test/replay_2y_v6.json"
OUT_MD = BASE + "test/reports/replay_2y_v6.md"

VER = os.environ.get("REPLAY_VER", "v3")   # v1=daily derisk, v2=once, v3=layered

HIST_DAYS = 21            # 20d factors need 21 closes (mom_20d = c[-1]/c[-21])
MIN_AMT_20D_QIAN = 50000.0   # liquidity gate: 20d avg turnover >= 50M CNY (tushare amount is in 千元)
CAPITAL = 1_000_000.0
MAX_HOLD, MIN_HOLD, MAX_SINGLE = 12, 8, 15.0
SL_PCT, TP_PCT = 0.08, 0.20
ORDER_TTL_DAYS = 10
ROT_GAP = 10.0 if VER == "v1" else 15.0
ROT_MAX, ROT_BAND = 3, (-5.0, 5.0)
ROT_MIN_HOLD_DAYS = 0 if VER == "v1" else 20

print("loading...")
daily = {}
for fp in sorted(glob.glob(DAILY_DIR + "*.csv")):
    d = Path(fp).stem
    m = {}
    with open(fp, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                m[r["ts_code"]] = {k: float(r[k]) for k in ("open", "high", "low", "close", "amount")}
            except (ValueError, TypeError, KeyError):
                continue
    daily[d] = m
DATES = sorted(daily)
idx = {r["trade_date"]: float(r["close"]) for r in json.load(open(IDX_FILE, encoding="utf-8"))}
IDXD = sorted(idx)


def load_csv(p):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


basic = {r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/meta/stock_basic.csv")}
fina = {r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/fina/h1_all.csv")}
fina.update({r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/fina/q3_all.csv")})
gw = {r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/research/goodwill.csv")}
au = {r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/research/audit.csv")}
rd = {r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/research/reduction.csv")}


def load_basic(d):
    p = BASE + "data/warehouse/daily_basic/%s.csv" % d
    return {r["ts_code"]: r for r in load_csv(p)} if os.path.exists(p) else {}


def ma_of(d, n):
    if d not in idx:
        return None
    i = IDXD.index(d)
    if i + 1 < n:
        return None
    return sum(idx[x] for x in IDXD[i - n + 1:i + 1]) / n


def regime_of(d, prev):
    i = DATES.index(d)
    day, prevd = daily[d], daily[DATES[i - 1]]
    up = dn = lu = ld = 0
    for code, b in day.items():
        if code not in prevd or prevd[code]["close"] <= 0:
            continue
        pct = b["close"] / prevd[code]["close"] - 1
        if pct > 0:
            up += 1
        elif pct < 0:
            dn += 1
        lim = 0.198 if code[:3] in ("300", "301", "688", "689") else 0.098
        if pct >= lim:
            lu += 1
        elif pct <= -lim:
            ld += 1
    tot = max(len(day), 1)
    upr = up / tot * 100
    hi20 = lo20 = 0
    for code, b in day.items():
        hist = [daily[DATES[i - k]][code]["close"] for k in range(1, 21) if code in daily[DATES[i - k]]]
        if len(hist) >= 15:
            if b["close"] >= max(hist):
                hi20 += 1
            if b["close"] <= min(hist):
                lo20 += 1
    amt = sum(b["amount"] for b in day.values())
    seg = [sum(b["amount"] for b in daily[DATES[i - k]].values()) for k in range(1, 21)]
    ar = amt / (sum(seg) / len(seg)) * 100 if seg else 100
    c0, m20, m60, m250 = idx.get(d), ma_of(d, 20), ma_of(d, 60), ma_of(d, 250)
    chg = (c0 / idx[DATES[i - 1]] - 1) * 100 if c0 and DATES[i - 1] in idx else 0
    bear_trend = bool(c0 and m20 and m60 and m250 and c0 < m20 < m60 < m250)
    trend = -2 if bear_trend else (2 if (c0 and m20 and m60 and c0 > m20 > m60) else 0)
    width = -2 if upr < 30 else (2 if (upr > 70 and hi20 > lo20) else 0)
    senti = -2 if (ld > 20 or lu < 20) else (2 if (lu > 50 and ld < 5) else 0)
    vol = -2 if ar < 80 else (2 if (ar > 110 and chg > 0) else 0)
    total = trend + width + senti + vol
    clamp = bear_trend or (lo20 > hi20 * 3)
    if VER == "v3":
        # layered: -6~-8 = bear/light (no forced de-risk), <=-8 = bear/heavy
        if total <= -8:
            raw, sev = "bear", "heavy"
        elif total <= -6:
            raw, sev = "bear", "light"
        elif total >= 4:
            raw, sev = "bull", None
        else:
            raw, sev = "neutral", None
    else:
        raw = "bear" if total <= -4 else ("bull" if total >= 4 else "neutral")
        sev = None
    if clamp and raw == "bull":
        raw, sev = "neutral", None
    conf = min(.85, .55 + abs(total) * .045)
    final = raw if (raw == prev or conf >= .75) else prev
    if final != raw:
        sev = None
    return final, conf, {"score": total, "up_ratio": round(upr, 1), "lu": lu, "ld": ld,
                         "hi20": hi20, "lo20": lo20, "amount_ratio": round(ar, 1),
                         "clamp": clamp, "severity": sev}


# v6 architecture: stock picker uses price/volume/valuation only (12 factors).
# Financial quality is decided by the researcher on the Top50, not by the picker.
W = {"mom_5d": .06, "mom_10d": .07, "mom_20d": .07, "vol_20d_inv": .08, "mdd_20d_inv": .07,
     "price_pos_20d": .06, "pv_corr_20d": .07, "turnover_trend_20d": .07,
     "ep_ttm": .06, "bp_ttm": .05, "sp_ttm": .04, "turnover_rate": .05}
FIN_W = {"roe_ttm": .35, "net_margin_ttm": .25, "gross_margin_ttm": .15, "tr_yoy": .25}
_s = sum(W.values())
W = {k: v / _s for k, v in W.items()}


def pctl(vals, x):
    if not vals or x is None:
        return None
    lo = sum(1 for v in vals if v < x)
    eq = sum(1 for v in vals if v == x)
    return (lo + eq * .5) / len(vals) * 100


def pick_and_screen(base):
    """stock_picker + researcher: returns watchlist with quality_score."""
    hist = [d for d in DATES if d <= base][-HIST_DAYS:]
    dbr = load_basic(base)
    rows = []
    for code, b in daily[base].items():
        if code.endswith(".BJ") or code[:3] in ("300", "301", "688", "689"):
            continue
        if "ST" in ((basic.get(code) or {}).get("name", "")).upper():
            continue
        # newly-listed filter (params.universe.min_list_days = 250 trading days ~ 365 calendar days)
        ld = (basic.get(code) or {}).get("list_date") or ""
        if len(ld) >= 8 and ld[:8].isdigit():
            try:
                from datetime import date as _d
                age = (_d(int(base[:4]), int(base[4:6]), int(base[6:8]))
                       - _d(int(ld[:4]), int(ld[4:6]), int(ld[6:8]))).days
                if age < 365:
                    continue
            except ValueError:
                pass
        bars = [daily[d][code] for d in hist if code in daily[d]]
        if len(bars) < 15:
            continue
        # liquidity gate (params.universe.min_amount_20d_avg_cny = 5000万)
        amts20 = [b["amount"] for b in bars[-20:]]
        if not amts20 or sum(amts20) / len(amts20) < MIN_AMT_20D_QIAN:
            continue
        c = [x["close"] for x in bars]
        a = [x["amount"] for x in bars]
        n = len(c)
        # strict 20-day window for all *_20d factors
        c20, a20 = c[-20:], a[-20:]
        rets = [c20[i] / c20[i - 1] - 1 for i in range(1, len(c20))]
        mu = sum(rets) / len(rets)
        vol = -math.sqrt(sum((r - mu) ** 2 for r in rets) / len(rets))
        peak, mdd = c20[0], 0.0
        for x in c20:
            peak = max(peak, x)
            mdd = min(mdd, x / peak - 1)
        mn, mx = min(c20), max(c20)
        n20 = len(c20)
        mc, ma_ = sum(c20) / n20, sum(a20) / n20
        vc = math.sqrt(sum((x - mc) ** 2 for x in c20))
        va = math.sqrt(sum((x - ma_) ** 2 for x in a20))
        xs = list(range(n20))
        xm = sum(xs) / n20
        slope = sum((xs[i] - xm) * (a20[i] - ma_) for i in range(n20)) / sum((x - xm) ** 2 for x in xs)
        fi, db = fina.get(code) or {}, dbr.get(code) or {}

        def f(k, src):
            try:
                return float(src.get(k))
            except (TypeError, ValueError):
                return None
        pe, pb, ps = f("pe_ttm", db), f("pb", db), f("ps_ttm", db)
        rows.append({
            "code": code, "name": (basic.get(code) or {}).get("name", ""),
            "industry": (basic.get(code) or {}).get("industry", ""),
            "mom_5d": c[-1] / c[-6] - 1 if n > 5 else None,
            "mom_10d": c[-1] / c[-11] - 1 if n > 10 else None,
            "mom_20d": c[-1] / c[-21] - 1 if n >= 21 else None,
            "vol_20d_inv": vol, "mdd_20d_inv": mdd,
            "price_pos_20d": (c20[-1] - mn) / (mx - mn) if mx > mn else .5,
            "pv_corr_20d": (sum((c20[i] - mc) * (a20[i] - ma_) for i in range(n20)) / (vc * va)) if vc and va else None,
            "turnover_trend_20d": slope,
            "roe_ttm": f("roe", fi), "gross_margin_ttm": f("grossprofit_margin", fi),
            "net_margin_ttm": f("netprofit_margin", fi), "tr_yoy": f("tr_yoy", fi),
            "ep_ttm": (1 / pe) if pe and pe > 0 else None,
            "bp_ttm": (1 / pb) if pb and pb > 0 else None,
            "sp_ttm": (1 / ps) if ps and ps > 0 else None,
            "turnover_rate": f("turnover_rate", db),
        })
    for fac in W:
        vals = sorted(r[fac] for r in rows if r[fac] is not None)
        for r in rows:
            r["_p_" + fac] = pctl(vals, r[fac])
    for r in rows:
        tot = wt = 0.0
        for fac, w in W.items():
            p = r["_p_" + fac]
            if p is not None:
                tot += p * w
                wt += w
        r["score"] = tot / wt if wt else 0
    rows.sort(key=lambda x: -x["score"])

    # ---- researcher stage: risk screen + financial quality (within Top50) ----
    survived = []
    for r in rows[:50]:
        code = r["code"]
        try:
            gv = float((gw.get(code) or {}).get("goodwill") or 0)
            eq = float((gw.get(code) or {}).get("equity") or 0)
        except ValueError:
            gv = eq = 0
        if eq and gv / eq > .30:
            continue
        ar = ((au.get(code) or {}).get("audit_result") or "").strip()
        if ar and "标准无保留" not in ar:
            continue
        try:
            vv = float((rd.get(code) or {}).get("dec_vol") or 0)
            ts = float((dbr.get(code) or {}).get("total_share") or 0)
        except ValueError:
            vv = ts = 0
        if ts and vv / (ts * 10000) > .01:
            continue
        survived.append(r)

    for k in FIN_W:
        vals = sorted(r[k] for r in survived if r[k] is not None)
        for r in survived:
            r["_q_" + k] = pctl(vals, r[k])

    watch = []
    for r in survived:
        qs = sum((r["_q_" + k] if r["_q_" + k] is not None else 50) * w for k, w in FIN_W.items())
        # 一半看财务质量、一半看选股分，避免财务数据缺失时排序失真
        watch.append({"code": r["code"], "name": r["name"], "industry": r["industry"],
                      "qs": round(0.5 * qs + 0.5 * r["score"], 1)})
    watch.sort(key=lambda x: -x["qs"])
    return watch


# ---------------- account state ----------------
cash = CAPITAL
positions = {}      # code -> {name, shares, cost, sl, tp, open_date, qs}
orders = []         # planned buy orders
watchlist = []      # latest from researcher
trades = []
equity = []
regime = "neutral"
last_select = None
confirmed = 0
bear_derisk_done = False
rotated_codes = set()


def total_assets(d):
    px = daily[d]
    return cash + sum(p["shares"] * (px.get(c) or {}).get("close", p["cost"]) for c, p in positions.items())


def do_select(d):
    """Friday after close: picker -> researcher -> builder (new orders)."""
    global watchlist, last_select
    watchlist = pick_and_screen(d)
    last_select = d
    if regime == "bear":
        return 0, "bear regime 禁止建仓"
    H = len(positions)
    pending = sum(1 for o in orders if o["status"] == "planned")   # orders in flight also consume slots
    if H + pending >= MAX_HOLD:
        return 0, "持仓 %d 只 + 在途 %d 单已达上限，等待成交或换仓" % (H, pending)
    target_new = MAX_HOLD - H - pending
    target_new = max(target_new, 0)
    cands = [w for w in watchlist if w["code"] not in positions]
    sel, scnt = [], {}
    held_ind = {}
    for c, p in positions.items():
        ind = (basic.get(c) or {}).get("industry", "")
        held_ind[ind] = held_ind.get(ind, 0) + 1
    for w in cands:
        ind = w["industry"] or "未分类"
        if scnt.get(ind, 0) >= 2 or held_ind.get(ind, 0) + scnt.get(ind, 0) >= 2:
            continue
        sel.append(w)
        scnt[ind] = scnt.get(ind, 0) + 1
        if len(sel) >= target_new:
            break
    if not sel:
        return 0, "无可用候选"
    base_pos = {"bull": 80.0, "neutral": 50.0, "bear": 20.0}[regime]
    # weight: share of remaining capacity
    room = max(base_pos - sum(p["shares"] * (daily[d].get(c) or {}).get("close", p["cost"]) for c, p in positions.items()) / total_assets(d) * 100, 0)
    qsum = sum(s["qs"] for s in sel)
    n = 0
    for i, s in enumerate(sel, 1):
        code = s["code"]
        ref = round(daily[d][code]["close"], 2)
        bars = [daily[x][code] for x in DATES if x <= d and code in daily[x]][-20:]
        mn = min(b["low"] for b in bars)
        w = round(min(max_pos_share(room, len(sel), s["qs"], qsum), MAX_SINGLE), 3)
        half = round(w * .5, 3)
        orders.append({
            "id": "ORD-%s-%02d" % (d, i), "code": code, "name": s["name"], "industry": s["industry"],
            "created": d, "weight": w, "qs": s["qs"], "ref": ref,
            "t1": round(ref * .99, 2), "t2": round(ref * .96, 2), "guard": round(ref * .88, 2),
            "tranches": [{"seq": 1, "pct": half, "filled": False}, {"seq": 2, "pct": round(w - half, 3), "filled": False}],
            "sl": round(min(round(ref * .92, 2), round(mn * .98, 2)), 2),
            "tp": round(ref * 1.20, 2), "status": "planned", "source": "builder",
        })
        n += 1
    return n, "新建 %d 只（现有 %d，目标总数 %d）" % (n, H, H + n)


def max_pos_share(room, n, qs, qsum):
    """distribute remaining position room by quality."""
    if qsum <= 0:
        return 0
    return room * qs / qsum


def rotate(d, conf):
    """R-007: swap laggards for stronger candidates."""
    global cash, rotated_codes
    if not watchlist or not positions:
        return []
    qs_map = {w["code"]: w["qs"] for w in watchlist}
    px = daily[d]
    held = []
    for c, p in positions.items():
        price = (px.get(c) or {}).get("close")
        if not price:
            continue
        pnl = (price / p["cost"] - 1) * 100
        held.append({"code": c, "qs": qs_map.get(c, 0.0), "pnl": pnl, "price": price,
                     "open_date": p.get("open_date")})
    held.sort(key=lambda x: x["qs"])
    cands = [w for w in watchlist if w["code"] not in positions]
    cands.sort(key=lambda x: -x["qs"])
    pairs = []
    di = DATES.index(d)
    for h in held:
        if len(pairs) >= ROT_MAX:
            break
        if h["code"] in rotated_codes and VER != "v1":   # v1 allowed repeats
            continue
        if h["open_date"] and di - DATES.index(h["open_date"]) < ROT_MIN_HOLD_DAYS:
            continue                               # hold at least 4 weeks
        if h["pnl"] < ROT_BAND[0] or h["pnl"] > ROT_BAND[1]:
            continue
        for c in cands:
            if c["code"] in positions or any(x["to"] == c["code"] for x in pairs):
                continue
            if c["qs"] - h["qs"] >= ROT_GAP:
                pairs.append({"from": h["code"], "to": c["code"], "qs_h": h["qs"], "qs_c": c["qs"],
                              "name_to": c["name"], "industry": c["industry"], "price": h["price"],
                              "pnl": round(h["pnl"], 2)})
                rotated_codes.add(h["code"])
                break
    for p in pairs:
        pos = positions.pop(p["from"])
        amount = pos["shares"] * p["price"]
        cash += amount
        trades.append({"date": d, "side": "sell", "code": p["from"], "name": pos["name"],
                       "price": p["price"], "shares": pos["shares"],
                       "pnl_pct": round((p["price"] / pos["cost"] - 1) * 100, 2), "why": "rotate_out"})
        # queue rotation buy for the new candidate (same weight as swapped-out)
        to = next(w for w in watchlist if w["code"] == p["to"])
        ref = round(daily[d][p["to"]]["close"], 2)
        bars = [daily[x][p["to"]] for x in DATES if x <= d and p["to"] in daily[x]][-20:]
        mn = min(b["low"] for b in bars)
        w = pos.get("weight", MAX_SINGLE)
        orders.append({
            "id": "ORD-%s-R%02d" % (d, len(pairs)), "code": p["to"], "name": to["name"],
            "industry": to["industry"], "created": d, "weight": w, "qs": p["qs_c"], "ref": ref,
            "t1": round(ref * .99, 2), "t2": round(ref * .96, 2), "guard": round(ref * .88, 2),
            "tranches": [{"seq": 1, "pct": round(w * .5, 3), "filled": False},
                         {"seq": 2, "pct": round(w * .5, 3), "filled": False}],
            "sl": round(min(round(ref * .92, 2), round(mn * .98, 2)), 2),
            "tp": round(ref * 1.20, 2), "status": "planned", "source": "rotation",
        })
    return pairs


# ---------------- main loop ----------------
sel_days = [DATES[i] for i in range(HIST_DAYS - 1, len(DATES), 5)]
print("select days:", sel_days)

for i, d in enumerate(DATES):
    if i < HIST_DAYS:
        continue
    px = daily[d]
    # 1) regime (with confirmation counter)
    prev_reg = regime
    regime, conf, rmeta = regime_of(d, regime)
    confirmed = confirmed + 1 if regime == prev_reg else 1
    if regime != "bear":
        bear_derisk_done = False

    # 2) order expiry (R-006)
    di = DATES.index(d)
    for o in orders:
        if o["status"] != "planned":
            continue
        created_i = DATES.index(o["created"])
        if di - created_i > ORDER_TTL_DAYS:
            o["status"] = "expired"

    # 3) fills (cumulative threshold ladder)
    for o in orders:
        if o["status"] != "planned":
            continue
        code = o["code"]
        price = (px.get(code) or {}).get("close")
        if not price or price < o["guard"]:
            continue
        for t in o["tranches"]:
            if t["filled"]:
                continue
            trig = o["t1"] if t["seq"] == 1 else o["t2"]
            if price <= trig:
                ta = total_assets(d)
                sh = int(ta * t["pct"] / 100 / price / 100) * 100
                if sh <= 0:
                    continue
                amt = sh * price
                if amt > cash:
                    sh = int(cash / price / 100) * 100
                    amt = sh * price
                if sh <= 0:
                    continue
                cash -= amt
                t["filled"] = True
                if code in positions:
                    p = positions[code]
                    ns = p["shares"] + sh
                    p["cost"] = (p["cost"] * p["shares"] + amt) / ns
                    p["shares"] = ns
                else:
                    positions[code] = {"name": o["name"], "shares": sh, "cost": price,
                                       "sl": o["sl"], "tp": o["tp"], "open_date": d,
                                       "qs": o.get("qs", 0), "weight": o["weight"]}
                trades.append({"date": d, "side": "buy", "code": code, "name": o["name"],
                               "price": price, "shares": sh, "amount": round(amt),
                               "why": "%s tr%d" % (o["source"], t["seq"]), "qs": o.get("qs")})
        if all(t["filled"] for t in o["tranches"]):
            o["status"] = "filled"

    # 4) stops / targets (open-gap aware: if open already broke SL, fill at open)
    for code in list(positions):
        p = positions[code]
        bar = px.get(code) or {}
        price, op = bar.get("close"), bar.get("open")
        if not price:
            continue
        sh, why, exec_px = 0, None, price
        if price <= p["sl"]:
            sh, why = p["shares"], "stop_loss"
            if op and op <= p["sl"]:
                exec_px = op  # gapped down through the stop: fill at open, not close
        elif price >= p["tp"]:
            sh, why = int(p["shares"] / 2 / 100) * 100, "take_profit"
            if sh > 0:
                # trailing target: move TP up 20% from the fill, and lift stop to breakeven
                p["tp"] = round(price * 1.20, 2)
                p["sl"] = round(max(p["sl"], p["cost"]), 2)
            if op and op >= p["tp"]:
                exec_px = op
        if sh > 0:
            cash += sh * exec_px
            trades.append({"date": d, "side": "sell", "code": code, "name": p["name"], "price": exec_px,
                           "shares": sh, "pnl_pct": round((exec_px / p["cost"] - 1) * 100, 2), "why": why})
            p["shares"] -= sh
            if p["shares"] <= 0:
                del positions[code]

    # 5) rotation: run once per week, on the first trading day after a new watchlist
    rot = []
    if watchlist and last_select and d > last_select and (di - DATES.index(last_select)) == 1:
        rot = rotate(d, conf)

    # 6) bear de-risk (version-dependent)
    sev = rmeta.get("severity")
    if VER == "v1":       # every day while in bear
        want = regime == "bear" and bool(positions)
    elif VER == "v2":     # once per bear episode, after 2 confirmed days
        want = regime == "bear" and bool(positions) and confirmed >= 2 and not bear_derisk_done
    else:                 # v3: heavy bear only
        want = (regime == "bear" and sev == "heavy" and bool(positions)
                and confirmed >= 2 and not bear_derisk_done)
    if want:
        ta = total_assets(d)
        pv = ta - cash
        if pv > ta * 0.20:
            ratio = ta * 0.20 / pv
            for code in list(positions):
                p = positions[code]
                price = (px.get(code) or {}).get("close")
                if not price:
                    continue
                ns = int(p["shares"] * ratio / 100) * 100
                sh = p["shares"] - ns
                if sh <= 0:
                    continue
                cash += sh * price
                trades.append({"date": d, "side": "sell", "code": code, "name": p["name"],
                               "price": price, "shares": sh,
                               "pnl_pct": round((price / p["cost"] - 1) * 100, 2), "why": "bear_derisk"})
                p["shares"] = ns
                if ns == 0:
                    del positions[code]
        if VER != "v1":
            bear_derisk_done = True
    if not (regime == "bear" and (VER != "v3" or sev == "heavy")):
        bear_derisk_done = False

    # 7) snapshot
    pv = sum(p["shares"] * (px.get(c) or {}).get("close", p["cost"]) for c, p in positions.items())
    ta = cash + pv
    equity.append({"date": d, "regime": regime, "conf": conf, "total": round(ta),
                   "pos_pct": round(pv / ta * 100, 2), "holdings": len(positions),
                   "pnl_pct": round((ta / CAPITAL - 1) * 100, 3),
                   "rotation": len(rot), "metrics": rmeta})

    # 8) Friday after close: selection + building
    if d in sel_days:
        n, msg = do_select(d)

# ---------------- stats ----------------
final = equity[-1]["total"]
rets = [e["pnl_pct"] for e in equity]
peak, mdd = 0, 0.0
for r in rets:
    peak = max(peak, r)
    mdd = min(mdd, r - peak)
sells = [t for t in trades if t["side"] == "sell"]
wins = [t for t in sells if (t.get("pnl_pct") or 0) > 0]
by_reason = {}
for t in sells:
    by_reason[t["why"]] = by_reason.get(t["why"], 0) + 1
idx_first, idx_last = idx.get(DATES[HIST_DAYS]), idx.get(DATES[-1])
idx_ret = (idx_last / idx_first - 1) * 100 if idx_first and idx_last else None

summary = {
    "period": "%s ~ %s (%d 交易日)" % (DATES[HIST_DAYS], DATES[-1], len(DATES) - HIST_DAYS),
    "final_assets": final, "total_return_pct": round((final / CAPITAL - 1) * 100, 2),
    "index_return_pct": round(idx_ret, 2) if idx_ret is not None else None,
    "excess_pct": round((final / CAPITAL - 1) * 100 - idx_ret, 2) if idx_ret is not None else None,
    "max_drawdown_pct": round(mdd, 2),
    "trades": len(trades), "closed": len(sells),
    "win_rate_pct": round(len(wins) / len(sells) * 100, 1) if sells else None,
    "avg_win_pct": round(sum(t["pnl_pct"] for t in wins) / len(wins), 2) if wins else None,
    "avg_loss_pct": round(sum(t["pnl_pct"] for t in sells if (t.get("pnl_pct") or 0) <= 0) /
                          max(len(sells) - len(wins), 1), 2),
    "sell_reasons": by_reason,
    "final_holdings": len(positions),
    "avg_position_pct": round(sum(e["pos_pct"] for e in equity) / len(equity), 2),
    "rotations": sum(e["rotation"] for e in equity),
}

json.dump({"summary": summary, "equity": equity, "trades": trades,
           "holdings": [{"code": c, "name": p["name"], "shares": p["shares"],
                         "cost": round(p["cost"], 2), "qs": p.get("qs")} for c, p in positions.items()]},
          open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

print("\n=== live chain replay ===")
print(json.dumps(summary, ensure_ascii=False, indent=2))
print("equity curve (every 5th day):")
for e in equity[::5]:
    print("  %s %-7s pos %5.1f%% (%2d只) total %9.0f  pnl %+6.2f%%"
          % (e["date"], e["regime"], e["pos_pct"], e["holdings"], e["total"], e["pnl_pct"]))
