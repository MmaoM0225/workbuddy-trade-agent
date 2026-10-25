#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Multi-week replay: 8 independent weeks on 60 days of local history.

Each week: selection on base date (16-day factor window) -> screen -> build 10
orders (v1.5 ladder) -> execute next 5 trading days -> settle to cash.
Daily regime is computed locally (breadth / limit-ups / 20d extremes / turnover
/ index MAs) so no per-day MCP calls are needed.
"""
import csv
import glob
import json
import math
import os
from pathlib import Path

BASE = "E:/cashfree/agent/"
DAILY_DIR = BASE + "data/warehouse/daily/"
IDX_CSV = BASE + "data/warehouse/index/000001.SH.csv"
OUT_JSON = BASE + "test/replay_multiweek.json"
OUT_MD = BASE + "test/reports/replay_multiweek.md"

HIST_DAYS = 16
WEEKS = 8
CAPITAL = 1_000_000.0

# ---------------- load ----------------
print("loading daily bars...")
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
print("daily:", len(DATES), DATES[0], "->", DATES[-1])

# index (saved from MCP pull)
idx = {}
os.makedirs(os.path.dirname(IDX_CSV), exist_ok=True)
RAW_IDX = json.load(open(BASE + "test/index_000001SH.json", encoding="utf-8")) if os.path.exists(
    BASE + "test/index_000001SH.json") else None
if RAW_IDX:
    for r in RAW_IDX:
        idx[r["trade_date"]] = float(r["close"])
else:
    print("WARN: no index file, MA-based trend check disabled")


def load_csv(p):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


basic = {r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/meta/stock_basic.csv")}
fina = {r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/fina/h1_all.csv")}
fina.update({r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/fina/q3_all.csv")})
gw = {r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/research/goodwill.csv")}
au = {r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/research/audit.csv")}
rd = {r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/research/reduction.csv")}


def load_basic(date):
    p = BASE + "data/warehouse/daily_basic/%s.csv" % date
    if not os.path.exists(p):
        return {}
    return {r["ts_code"]: r for r in load_csv(p)}


# ---------------- daily metrics (local) ----------------
IDX_DATES = sorted(idx)


def ma_on(date, n):
    if not IDX_DATES:
        return None
    i = IDX_DATES.index(date) if date in IDX_DATES else None
    if i is None or i + 1 < n:
        return None
    seg = IDX_DATES[i - n + 1:i + 1]
    return sum(idx[d] for d in seg) / n


def metrics(date):
    i = DATES.index(date)
    if i < 20:
        return None
    day, prev = daily[date], daily[DATES[i - 1]]
    up = dn = lu = ld = 0
    hi20 = lo20 = 0
    amt = 0.0
    for code, b in day.items():
        amt += b["amount"]
        if code not in prev or prev[code]["close"] <= 0:
            continue
        pct = b["close"] / prev[code]["close"] - 1
        if pct > 0:
            up += 1
        elif pct < 0:
            dn += 1
        lim = 0.198 if code[:3] in ("300", "301", "688", "689") else 0.098
        if pct >= lim:
            lu += 1
        elif pct <= -lim:
            ld += 1
        # 20d extremes
        hist = [daily[DATES[i - k]][code]["close"] for k in range(1, 21)
                if code in daily[DATES[i - k]]]
        if len(hist) >= 15 and b["close"] >= max(hist):
            hi20 += 1
        if len(hist) >= 15 and b["close"] <= min(hist):
            lo20 += 1
    tot = max(len(day), 1)
    close_idx = idx.get(date)
    ma20, ma60, ma250 = ma_on(date, 20), ma_on(date, 60), ma_on(date, 250)
    # turnover vs 20d avg
    seg = [sum(b["amount"] for b in daily[DATES[i - k]].values()) for k in range(1, 21)]
    avg_amt = sum(seg) / len(seg) if seg else amt
    return {
        "date": date, "up_ratio": round(up / tot * 100, 2), "up": up, "down": dn,
        "lu": lu, "ld": ld, "hi20": hi20, "lo20": lo20,
        "amount_yi": round(amt / 1e5, 1), "amount_ratio": round(amt / avg_amt * 100, 1) if avg_amt else None,
        "idx_close": close_idx, "ma20": ma20, "ma60": ma60, "ma250": ma250,
        "chg": round((close_idx / idx[DATES[i - 1]] - 1) * 100, 2) if close_idx and DATES[i - 1] in idx else None,
    }


def judge(m, prev_regime):
    if not m:
        return {"regime": "neutral", "confidence": 0.5, "score": 0, "clamp": False, "note": "数据不足"}
    bear_trend = bool(m["idx_close"] and m["ma20"] and m["ma60"] and m["ma250"]
                      and m["idx_close"] < m["ma20"] < m["ma60"] < m["ma250"])
    trend = -2 if bear_trend else (2 if (m["idx_close"] and m["ma60"] and m["idx_close"] > m["ma20"] > m["ma60"]) else 0)
    if m["up_ratio"] < 30:
        width = -2
    elif m["up_ratio"] > 70 and m["hi20"] > m["lo20"]:
        width = 2
    else:
        width = 0
    if m["ld"] > 20 or m["lu"] < 20:
        senti = -2
    elif m["lu"] > 50 and m["ld"] < 5:
        senti = 2
    else:
        senti = 0
    ar = m["amount_ratio"] or 100
    vol = -2 if ar < 80 else (2 if ar > 110 and (m["chg"] or 0) > 0 else 0)
    total = trend + width + senti + vol
    clamp = bear_trend or (m["lo20"] > m["hi20"] * 3)
    raw = "bear" if total <= -4 else ("bull" if total >= 4 else "neutral")
    if clamp and raw == "bull":
        raw = "neutral"
    conf = min(.85, .55 + abs(total) * .045)
    final = raw if (raw == prev_regime or conf >= .75) else prev_regime
    return {"regime": final, "raw": raw, "confidence": round(conf, 2), "score": total,
            "clamp": clamp, "switched": final != prev_regime,
            "dims": {"trend": trend, "breadth": width, "sentiment": senti, "volume": vol}}


# ---------------- factor model ----------------
W = {"mom_5d": .06, "mom_10d": .07, "mom_20d": .07, "vol_20d_inv": .08, "mdd_20d_inv": .07,
     "price_pos_20d": .06, "pv_corr_20d": .07, "turnover_trend_20d": .07,
     "roe_ttm": .08, "gross_margin_ttm": .04, "net_margin_ttm": .04, "tr_yoy": .04,
     "ep_ttm": .06, "bp_ttm": .05, "sp_ttm": .04, "turnover_rate": .05}
ws = sum(W.values())
W = {k: v / ws for k, v in W.items()}


def pctl(vals, x):
    if not vals or x is None:
        return None
    lo = sum(1 for v in vals if v < x)
    eq = sum(1 for v in vals if v == x)
    return (lo + eq * .5) / len(vals) * 100


def select(base, base_pos=50.0):
    hist = [d for d in DATES if d <= base][-HIST_DAYS:]
    dbr = load_basic(base)
    rows = []
    for code, b in daily[base].items():
        if code.endswith(".BJ") or code[:3] in ("300", "301", "688", "689"):
            continue
        if "ST" in ((basic.get(code) or {}).get("name", "")).upper():
            continue
        bars = [daily[d][code] for d in hist if code in daily[d]]
        if len(bars) < 12:
            continue
        c = [x["close"] for x in bars]
        a = [x["amount"] for x in bars]
        n = len(c)
        rets = [c[i] / c[i - 1] - 1 for i in range(1, n)]
        mu = sum(rets) / len(rets)
        vol = -math.sqrt(sum((r - mu) ** 2 for r in rets) / len(rets))
        peak, mdd = c[0], 0.0
        for x in c:
            peak = max(peak, x)
            mdd = min(mdd, x / peak - 1)
        mn, mx = min(c), max(c)
        mc, ma_ = sum(c) / n, sum(a) / n
        vc = math.sqrt(sum((x - mc) ** 2 for x in c))
        va = math.sqrt(sum((x - ma_) ** 2 for x in a))
        xs = list(range(n))
        xm = sum(xs) / n
        slope = sum((xs[i] - xm) * (a[i] - ma_) for i in range(n)) / sum((x - xm) ** 2 for x in xs)
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
            "mom_20d": c[-1] / c[0] - 1,
            "vol_20d_inv": vol, "mdd_20d_inv": mdd,
            "price_pos_20d": (c[-1] - mn) / (mx - mn) if mx > mn else .5,
            "pv_corr_20d": (sum((c[i] - mc) * (a[i] - ma_) for i in range(n)) / (vc * va)) if vc and va else None,
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

    watch = []
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
            vol_ = float((rd.get(code) or {}).get("dec_vol") or 0)
            ts = float(((dbr.get(code) or {}).get("total_share")) or 0)
        except ValueError:
            vol_ = ts = 0
        if ts and vol_ / (ts * 10000) > .01:
            continue
        qw = {"roe_ttm": .35, "net_margin_ttm": .25, "gross_margin_ttm": .15, "tr_yoy": .25}
        qs = sum((r["_p_" + k] or 50) * v for k, v in qw.items())
        watch.append({"code": code, "name": r["name"], "industry": r["industry"], "qs": round(qs, 1)})
    watch.sort(key=lambda x: -x["qs"])
    sel, scnt = [], {}
    for w in watch:
        ind = w["industry"] or "未分类"
        if scnt.get(ind, 0) >= 2:
            continue
        sel.append(w)
        scnt[ind] = scnt.get(ind, 0) + 1
        if len(sel) >= 10:
            break
    qsum = sum(s["qs"] for s in sel)
    for s in sel:
        s["weight"] = round(base_pos * s["qs"] / qsum, 2)
    return sel


def run_week(base, exec_dates, prev_regime="neutral"):
    # regime on base date decides base position and whether we may build at all
    rg0 = judge(metrics(base), prev_regime)
    base_regime = rg0["regime"]
    if base_regime == "bear":
        return {
            "base": base, "exec": [exec_dates[0], exec_dates[-1]], "base_regime": "bear",
            "universe_pool": 0, "orders": 0, "filled": 0, "fill_rate": 0.0,
            "final": CAPITAL, "ret_pct": 0.0, "index_ret_pct": None, "excess_pct": None,
            "trades": 0, "days": [], "holdings": [], "position_value": 0, "position_pct_end": 0.0,
            "positions": [],
            "note": "基准日 regime=bear，R-001 禁止新建仓，本周空仓",
        }
    base_pos = {"bull": 80.0, "neutral": 50.0, "bear": 20.0}[base_regime]

    sel = select(base, base_pos)
    orders = []
    for i, s in enumerate(sel, 1):
        code = s["code"]
        bars = [daily[d][code] for d in DATES if d <= base][-20:]
        mn = min(b["low"] for b in bars)
        ref = round(daily[base][code]["close"], 2)
        half = round(s["weight"] * .5, 2)
        orders.append({
            "code": code, "name": s["name"], "industry": s["industry"], "weight": s["weight"],
            "ref": ref, "t1": round(ref * .99, 2), "t2": round(ref * .96, 2),
            "guard": round(ref * .88, 2),
            "tranches": [{"seq": 1, "pct": half, "filled": False}, {"seq": 2, "pct": round(s["weight"] - half, 2), "filled": False}],
            "sl": round(min(round(ref * .92, 2), round(mn * .98, 2)), 2),
            "tp": round(ref * 1.20, 2),
        })
    cash, pos, trades, days = CAPITAL, {}, [], []
    regime = prev_regime
    for d in exec_dates:
        m = metrics(d)
        rg = judge(m, regime)
        regime = rg["regime"]
        px = daily[d]
        fills, sells = [], []
        for o in orders:
            price = (px.get(o["code"]) or {}).get("close")
            if not price or price < o["guard"]:
                continue
            for t in o["tranches"]:
                if t["filled"]:
                    continue
                trig = o["t1"] if t["seq"] == 1 else o["t2"]
                if price <= trig:
                    ta = cash + sum(p["sh"] * (px.get(c) or {}).get("close", p["cost"]) for c, p in pos.items())
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
                    if o["code"] in pos:
                        p = pos[o["code"]]
                        ns = p["sh"] + sh
                        p["cost"] = (p["cost"] * p["sh"] + amt) / ns
                        p["sh"] = ns
                    else:
                        pos[o["code"]] = {"code": o["code"], "name": o["name"], "sh": sh,
                                          "cost": price, "sl": o["sl"], "tp": o["tp"]}
                    fills.append({"code": o["code"], "name": o["name"], "tr": t["seq"], "price": price, "sh": sh})
                    trades.append({"date": d, "side": "buy", "code": o["code"], "name": o["name"], "price": price, "sh": sh})
        for code in list(pos):
            p = pos[code]
            price = (px.get(code) or {}).get("close")
            if not price:
                continue
            sh, why = 0, None
            if price <= p["sl"]:
                sh, why = p["sh"], "stop"
            elif price >= p["tp"]:
                sh, why = int(p["sh"] / 2 / 100) * 100, "target"
            if sh > 0:
                cash += sh * price
                sells.append({"code": code, "name": p["name"], "price": price, "sh": sh, "why": why})
                trades.append({"date": d, "side": "sell", "code": code, "name": p["name"], "price": price,
                               "sh": sh, "pnl_pct": round((price / p["cost"] - 1) * 100, 2), "why": why})
                p["sh"] -= sh
                if p["sh"] <= 0:
                    del pos[code]
        if regime == "bear" and pos:
            ta = cash + sum(p["sh"] * (px.get(c) or {}).get("close", p["cost"]) for c, p in pos.items())
            pv = ta - cash
            if pv > ta * .20:
                ratio = ta * .20 / pv
                for code in list(pos):
                    p = pos[code]
                    price = (px.get(code) or {}).get("close")
                    if not price:
                        continue
                    ns = int(p["sh"] * ratio / 100) * 100
                    sh = p["sh"] - ns
                    if sh <= 0:
                        continue
                    cash += sh * price
                    sells.append({"code": code, "name": p["name"], "price": price, "sh": sh, "why": "bear"})
                    trades.append({"date": d, "side": "sell", "code": code, "name": p["name"], "price": price,
                                   "sh": sh, "pnl_pct": round((price / p["cost"] - 1) * 100, 2), "why": "bear"})
                    p["sh"] = ns
                    if ns == 0:
                        del pos[code]
        pv = sum(p["sh"] * (px.get(c) or {}).get("close", p["cost"]) for c, p in pos.items())
        days.append({"date": d, "regime": rg["regime"], "conf": rg["confidence"], "score": rg["score"],
                     "dims": rg.get("dims"), "up_ratio": (m or {}).get("up_ratio"), "lu": (m or {}).get("lu"),
                     "ld": (m or {}).get("ld"), "amount_yi": (m or {}).get("amount_yi"),
                     "fills": len(fills), "sells": len(sells), "pos": len(pos),
                     "pos_pct": round(pv / (cash + pv) * 100, 2), "total": round(cash + pv),
                     "pnl_pct": round((cash + pv) / CAPITAL * 100 - 100, 3)})
    # settle remaining at last close
    last = daily[exec_dates[-1]]
    pv = sum(p["sh"] * (last.get(c) or {}).get("close", p["cost"]) for c, p in pos.items())
    holdings = []
    for c, p in pos.items():
        price = (last.get(c) or {}).get("close")
        holdings.append({
            "code": c, "name": p["name"], "shares": p["sh"], "cost": round(p["cost"], 2),
            "last": round(price, 2) if price else None,
            "market_value": round(p["sh"] * price) if price else 0,
            "pnl_pct": round((price / p["cost"] - 1) * 100, 2) if price else None,
            "stop_loss": p["sl"], "take_profit": p["tp"],
        })
    holdings.sort(key=lambda x: -x["market_value"])
    for c, p in pos.items():
        price = (last.get(c) or {}).get("close")
        if price:
            trades.append({"date": exec_dates[-1], "side": "sell", "code": c, "name": p["name"],
                           "price": price, "sh": p["sh"],
                           "pnl_pct": round((price / p["cost"] - 1) * 100, 2), "why": "settle"})
    final = cash + pv
    idx_ret = None
    if exec_dates[-1] in idx and base in idx:
        idx_ret = round((idx[exec_dates[-1]] / idx[base] - 1) * 100, 3)
    filled = sum(1 for o in orders if any(t["filled"] for t in o["tranches"]))
    return {
        "base": base, "exec": [exec_dates[0], exec_dates[-1]],
        "base_regime": base_regime, "base_pos": base_pos,
        "universe_pool": len(sel), "orders": len(orders), "filled": filled,
        "fill_rate": round(filled / max(len(orders), 1) * 100, 1),
        "final": round(final), "ret_pct": round((final / CAPITAL - 1) * 100, 3),
        "index_ret_pct": idx_ret,
        "excess_pct": round((final / CAPITAL - 1) * 100 - (idx_ret or 0), 3),
        "trades": len(trades), "days": days, "holdings": holdings,
        "position_value": round(pv), "position_pct_end": round(pv / final * 100, 2) if final else 0,
        "positions": [o for o in orders if any(t["filled"] for t in o["tranches"])],
    }


# ---------------- run ----------------
weeks = []
base_idx = [HIST_DAYS - 1 + 5 * k for k in range(WEEKS)]
for k, bi in enumerate(base_idx):
    if bi + 5 >= len(DATES):
        break
    base = DATES[bi]
    exec_dates = DATES[bi + 1: bi + 6]
    r = run_week(base, exec_dates)
    weeks.append(r)
    print("W%d base %s exec %s~%s | filled %d/%d | ret %+.3f%% vs idx %s | excess %s"
          % (k + 1, base, exec_dates[0], exec_dates[-1], r["filled"], r["orders"],
             r["ret_pct"],
             ("%+.3f%%" % r["index_ret_pct"]) if r.get("index_ret_pct") is not None else "n/a",
             ("%+.3f%%" % r["excess_pct"]) if r.get("excess_pct") is not None else "n/a"), flush=True)

rets = [w["ret_pct"] for w in weeks]
exc = [w["excess_pct"] for w in weeks if w.get("excess_pct") is not None]
summary = {
    "weeks": len(weeks),
    "avg_ret_pct": round(sum(rets) / len(rets), 3),
    "avg_excess_pct": round(sum(exc) / len(exc), 3),
    "win_weeks": sum(1 for r in rets if r > 0),
    "beat_index_weeks": sum(1 for e in exc if e > 0),
    "best": max(weeks, key=lambda w: w["ret_pct"])["base"],
    "worst": min(weeks, key=lambda w: w["ret_pct"])["base"],
    "avg_fill_rate": round(sum(w["fill_rate"] for w in weeks) / len(weeks), 1),
}
json.dump({"summary": summary, "weeks": weeks}, open(OUT_JSON, "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

L = ["# 多周回测 8 周（v1.5 买点规则）\n",
     "- 数据：warehouse 60 个交易日（20260724 ~ 20261023），每周独立回测",
     "- 每周：基准日选股（16 日历史窗口）→ 排雷 → 建仓 10 只 → 执行 5 个交易日 → 期末清仓结算",
     "- regime 由本地日线计算（涨跌家数/涨跌停/20日新高新低/成交额/指数均线），含趋势钳制与防抖\n",
     "## 各周结果\n",
     "| 周 | 选股基准日 | 执行区间 | 成交 | 收益率 | 上证同期 | 超额 |",
     "|---|---|---|---|---|---|---|"]
for i, w in enumerate(weeks, 1):
    L.append("| W%d | %s | %s~%s | %d/%d (%.0f%%) | **%+.2f%%** | %s | %s |"
             % (i, w["base"], w["exec"][0], w["exec"][1], w["filled"], w["orders"], w["fill_rate"],
                w["ret_pct"],
                ("%+.2f%%" % w["index_ret_pct"]) if w.get("index_ret_pct") is not None else "n/a",
                ("%+.2f%%" % w["excess_pct"]) if w.get("excess_pct") is not None else "空仓"))
L.append("")
L.append("## 汇总\n")
L.append("| 指标 | 数值 |")
L.append("|---|---|")
L.append("| 平均周收益 | %+.3f%% |" % summary["avg_ret_pct"])
L.append("| 平均超额（vs 上证） | %+.3f%% |" % summary["avg_excess_pct"])
L.append("| 正收益周数 | %d/%d |" % (summary["win_weeks"], len(weeks)))
L.append("| 跑赢上证周数 | %d/%d |" % (summary["beat_index_weeks"], len(weeks)))
L.append("| 平均成交率 | %.1f%% |" % summary["avg_fill_rate"])
L.append("| 最好周 | %s |" % summary["best"])
L.append("| 最差周 | %s |" % summary["worst"])
L.append("")
L.append("## 逐周 regime 路径\n")
for i, w in enumerate(weeks, 1):
    L.append("- W%d (%s): %s" % (i, w["base"], " → ".join("%s(%.2f)" % (d["regime"], d["conf"]) for d in w["days"])))
open(OUT_MD, "w", encoding="utf-8").write("\n".join(L))
print("\nsummary:", json.dumps(summary, ensure_ascii=False))
print("report ->", OUT_MD)
