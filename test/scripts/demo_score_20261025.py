# -*- coding: utf-8 -*-
"""Demo run: 17-factor scoring per params_v1.2 (2026-10-25)."""
import csv, math, os, statistics

BASE = r"E:\cashfree\agent\data\demo_20261025"
PY = "C:/Users/19204/.workbuddy/binaries/python/versions/3.13.12/python.exe"

def read_csv(p):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def fnum(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None

# ---- load universe ----
uni = {}
for r in read_csv(os.path.join(BASE, "universe_200.csv")):
    uni[r["ts_code"]] = {"name": r["name"], "industry": r["industry"], "total_mv": fnum(r["total_mv"])}

# ---- daily (price/volume factors) ----
daily = {}
for i in range(1, 9):
    for r in read_csv(os.path.join(BASE, f"daily_b{i}.csv")):
        daily.setdefault(r["ts_code"], []).append(r)
for c in daily:
    daily[c].sort(key=lambda r: r["trade_date"])

# ---- weekly (60d momentum) ----
weekly = {}
for i in range(1, 9):
    for r in read_csv(os.path.join(BASE, f"weekly_b{i}.csv")):
        weekly.setdefault(r["ts_code"], []).append(r)
for c in weekly:
    weekly[c].sort(key=lambda r: r["trade_date"])

# ---- fundamentals ----
fina = {}
for p in ["fina_q3.csv", "fina_h1_a.csv", "fina_h1_b.csv"]:
    fp = os.path.join(BASE, p)
    if not os.path.exists(fp):
        continue
    for r in read_csv(fp):
        fina[r["ts_code"]] = r  # already deduped by ann_date

# ---- daily_basic (valuation/liquidity) ----
dbasic = {}
for r in read_csv(os.path.join(BASE, "daily_basic_20261023.csv")):
    if r["ts_code"] in uni:
        dbasic[r["ts_code"]] = r

# ---- compute raw factors ----
F = {}  # F[code][factor] = raw value or None

def mom(closes, n):
    if len(closes) < n + 1:
        return None
    base = closes[-(n + 1)]
    return closes[-1] / base - 1.0 if base else None

for code in uni:
    F[code] = {}
    d = daily.get(code, [])
    closes = [fnum(r["close"]) for r in d]
    highs = [fnum(r["high"]) for r in d]
    lows = [fnum(r["low"]) for r in d]
    amts = [fnum(r["amount"]) for r in d]
    closes = [c for c in closes if c is not None]
    # momentum
    F[code]["mom_5d"] = mom(closes, 5)
    F[code]["mom_10d"] = mom(closes, 10)
    F[code]["mom_20d"] = mom(closes, 20)
    # volatility: 20d std of daily returns (inv)
    if len(closes) >= 5:
        rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1]]
        F[code]["vol_20d_inv"] = -statistics.pstdev(rets) if len(rets) >= 5 else None
    else:
        F[code]["vol_20d_inv"] = None
    # max drawdown (inv)
    if closes:
        peak, mdd = closes[0], 0.0
        for c in closes:
            peak = max(peak, c)
            mdd = min(mdd, c / peak - 1.0)
        F[code]["mdd_20d_inv"] = mdd  # already negative
    else:
        F[code]["mdd_20d_inv"] = None
    # price position in 20d range
    valid_h = [h for h in highs if h is not None]
    valid_l = [l for l in lows if l is not None]
    if closes and valid_h and valid_l:
        lo, hi = min(valid_l), max(valid_h)
        F[code]["price_pos_20d"] = (closes[-1] - lo) / (hi - lo) if hi > lo else 0.5
    else:
        F[code]["price_pos_20d"] = None
    # price-volume correlation (20d)
    if len(closes) >= 5 and len(amts) == len(closes):
        mc, ma = statistics.fmean(closes), statistics.fmean(amts)
        num = sum((c - mc) * (a - ma) for c, a in zip(closes, amts))
        dc = math.sqrt(sum((c - mc) ** 2 for c in closes))
        da = math.sqrt(sum((a - ma) ** 2 for a in amts))
        F[code]["pv_corr_20d"] = num / (dc * da) if dc > 0 and da > 0 else None
    else:
        F[code]["pv_corr_20d"] = None
    # turnover trend: slope of amount over days
    if len(amts) >= 5 and all(a is not None for a in amts):
        n = len(amts)
        xs = list(range(n))
        mx, my = statistics.fmean(xs), statistics.fmean(amts)
        num = sum((x - mx) * (y - my) for x, y in zip(xs, amts))
        den = sum((x - mx) ** 2 for x in xs)
        F[code]["turnover_trend_20d"] = num / den if den else None
    else:
        F[code]["turnover_trend_20d"] = None
    # 60d momentum from weekly (13 weeks back)
    w = weekly.get(code, [])
    wc = [fnum(r["close"]) for r in w]
    wc = [c for c in wc if c is not None]
    F[code]["mom_60d"] = (wc[-1] / wc[-14] - 1.0) if len(wc) >= 14 else None
    # valuation & liquidity
    db = dbasic.get(code, {})
    pe, pb, ps = fnum(db.get("pe_ttm")), fnum(db.get("pb")), fnum(db.get("ps_ttm"))
    F[code]["ep_ttm"] = 1.0 / pe if pe and pe > 0 else None
    F[code]["bp_ttm"] = 1.0 / pb if pb and pb > 0 else None
    F[code]["sp_ttm"] = 1.0 / ps if ps and ps > 0 else None
    F[code]["turnover_rate"] = fnum(db.get("turnover_rate"))
    # quality
    fi = fina.get(code, {})
    F[code]["roe_ttm"] = fnum(fi.get("roe"))
    F[code]["gross_margin_ttm"] = fnum(fi.get("grossprofit_margin"))
    F[code]["net_margin_ttm"] = fnum(fi.get("netprofit_margin"))
    F[code]["tr_yoy"] = fnum(fi.get("tr_yoy"))

# ---- scoring pipeline ----
W = {
    "mom_5d": 0.06, "mom_10d": 0.07, "mom_20d": 0.07, "mom_60d": 0.05,
    "vol_20d_inv": 0.08, "mdd_20d_inv": 0.07,
    "price_pos_20d": 0.06, "pv_corr_20d": 0.07, "turnover_trend_20d": 0.07,
    "roe_ttm": 0.08, "gross_margin_ttm": 0.04, "net_margin_ttm": 0.04, "tr_yoy": 0.04,
    "ep_ttm": 0.06, "bp_ttm": 0.05, "sp_ttm": 0.04,
    "turnover_rate": 0.05,
}
GROUPS = {
    "momentum": ["mom_5d", "mom_10d", "mom_20d", "mom_60d"],
    "volatility_risk": ["vol_20d_inv", "mdd_20d_inv"],
    "technical_price_volume": ["price_pos_20d", "pv_corr_20d", "turnover_trend_20d"],
    "quality": ["roe_ttm", "gross_margin_ttm", "net_margin_ttm", "tr_yoy"],
    "valuation": ["ep_ttm", "bp_ttm", "sp_ttm"],
    "liquidity": ["turnover_rate"],
}
FACTORS = list(W.keys())
codes = list(uni.keys())
n = len(codes)

# log market cap for neutralization
logmv = {}
for c in codes:
    mv = uni[c]["total_mv"]
    logmv[c] = math.log(mv) if mv and mv > 0 else None

# factor coverage -> drop factor if >30% missing
drop_notes = []
active = []
for fac in FACTORS:
    miss = sum(1 for c in codes if F[c][fac] is None)
    if miss > 0.30 * n:
        drop_notes.append(f"{fac}: dropped (missing {miss}/{n})")
    else:
        active.append(fac)

def mad_winsorize(vals):
    """vals: dict code->value (no None). winsorize at median +/- 3*MAD."""
    xs = sorted(vals.values())
    med = statistics.median(xs)
    mad = statistics.median([abs(x - med) for x in xs])
    if mad == 0:
        return vals
    lo, hi = med - 3 * mad, med + 3 * mad
    return {c: min(max(v, lo), hi) for c, v in vals.items()}

def rank_pct(vals):
    """percentile rank 0..1 (higher = better). vals: code->value."""
    items = sorted(vals.items(), key=lambda kv: kv[1])
    m = len(items)
    out = {}
    i = 0
    while i < m:
        j = i
        while j + 1 < m and items[j + 1][1] == items[i][1]:
            j += 1
        avg = (i + j) / 2.0 / max(m - 1, 1)
        for k in range(i, j + 1):
            out[items[k][0]] = avg
        i = j + 1
    return out

def neutralize(vals, logmv):
    """regress vals on log(total_mv), return residuals (pure python OLS)."""
    xs = [logmv[c] for c in vals]
    ys = [vals[c] for c in vals]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return vals
    b = num / den
    a = my - b * mx
    return {c: y - (a + b * logmv[c]) for c, y in zip(vals.keys(), ys)}

# per-factor processed ranks
R = {}
for fac in active:
    vals = {c: F[c][fac] for c in codes if F[c][fac] is not None}
    if not vals:
        continue
    vals = mad_winsorize(vals)
    if logmv.get(next(iter(vals))) is not None:
        usable = {c: v for c, v in vals.items() if logmv[c] is not None}
        vals = neutralize(usable, logmv) if len(usable) > 2 else vals
    R[fac] = rank_pct(vals)

# composite score with weight renormalization for missing factors
scores = {}
for c in codes:
    num = den = 0.0
    for fac in active:
        if fac in R and c in R[fac]:
            num += R[fac][c] * W[fac]
            den += W[fac]
    scores[c] = num / den if den > 0 else None

# reasons: top-3 contributing factors
def reasons(c):
    contrib = []
    for fac in active:
        if fac in R and c in R[fac]:
            contrib.append((R[fac][c] * W[fac], fac, R[fac][c]))
    contrib.sort(reverse=True)
    return [f"{fac} 百分位{p:.0%}" for _, fac, p in contrib[:3]]

ranked = sorted([c for c in codes if scores[c] is not None], key=lambda c: -scores[c])

# ---- write outputs ----
out = os.path.join(BASE, "factor_scores_200.csv")
with open(out, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["rank", "ts_code", "name", "industry", "score"] + FACTORS)
    for i, c in enumerate(ranked, 1):
        w.writerow([i, c, uni[c]["name"], uni[c]["industry"], round(scores[c], 4)] +
                   ["" if F[c][fac] is None else round(F[c][fac], 4) for fac in FACTORS])

print("universe:", n, "scored:", len(ranked))
print("dropped factors:", drop_notes or "none")
print("\nTOP 20:")
for i, c in enumerate(ranked[:20], 1):
    print(f"{i:>2}. {uni[c]['name']:<8} {c} score={scores[c]:.3f} | {'; '.join(reasons(c))}")
print("\nBOTTOM 5:")
for c in ranked[-5:]:
    print(f"    {uni[c]['name']:<8} {c} score={scores[c]:.3f}")

# group averages for top50 vs all
top50 = ranked[:50]
print("\nTOP50 vs ALL 200 factor averages (rank pct):")
for g, facs in GROUPS.items():
    for fac in facs:
        if fac in R:
            t = statistics.fmean([R[fac][c] for c in top50 if c in R[fac]])
            a = statistics.fmean(list(R[fac].values()))
            print(f"  {g:<24} {fac:<20} top50={t:.2f} all={a:.2f}")
