# -*- coding: utf-8 -*-
"""全市场 17 因子打分（params v1.3 规则），读取 data/warehouse/ 本地仓库。
输出：data/warehouse/scores_full.csv + test/state/pool.json（彩跑）
"""
import csv
import glob
import json
import math
import os
import statistics
from datetime import date

ROOT = r"E:\cashfree\agent"
WH = os.path.join(ROOT, "data", "warehouse")
# 基准日 = daily_basic 目录里最新的一天
_db_dates = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(WH, "daily_basic", "*.csv")))
BASE_DATE = _db_dates[-1] if _db_dates else "20261023"
OUT_SCORES = os.path.join(WH, "scores_full.csv")
# 正式跑写 state/pool.json；彩排时用环境变量 POOL_OUT 指向 test/state/pool.json
OUT_POOL = os.environ.get("POOL_OUT") or os.path.join(ROOT, "state", "pool.json")
POOL_SIZE = 50

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


def fnum(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def read_csv(p):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ---------- load universe meta ----------
print("loading meta...", flush=True)
basic = {r["ts_code"]: r for r in read_csv(os.path.join(WH, "meta", "stock_basic.csv"))}
suspend = {r["ts_code"] for r in read_csv(os.path.join(WH, "meta", f"suspend_{BASE_DATE}.csv"))}
dbasic = {r["ts_code"]: r for r in read_csv(os.path.join(WH, "daily_basic", f"{BASE_DATE}.csv"))}
print(f"  stock_basic={len(basic)} daily_basic={len(dbasic)}", flush=True)

# ---------- load daily ----------
print("loading daily...", flush=True)
daily = {}
for p in sorted(glob.glob(os.path.join(WH, "daily", "*.csv"))):
    d = os.path.basename(p)[:-4]
    for r in read_csv(p):
        daily.setdefault(r["ts_code"], []).append(
            (d, fnum(r["close"]), fnum(r["high"]), fnum(r["low"]), fnum(r["amount"])))
for c in daily:
    daily[c].sort()
print(f"  codes={len(daily)}", flush=True)

# ---------- load weekly ----------
print("loading weekly...", flush=True)
weekly = {}
for p in glob.glob(os.path.join(WH, "weekly", "part*.csv")):
    for r in read_csv(p):
        weekly.setdefault(r["ts_code"], []).append((r["trade_date"], fnum(r["close"])))
for c in weekly:
    weekly[c].sort()
print(f"  codes={len(weekly)}", flush=True)

# ---------- load fina: Q3 first, H1 fallback ----------
print("loading fina...", flush=True)
fina = {}
for fn in ("h1_part3.csv", "h1_all.csv", "q3_all.csv"):  # 后者覆盖前者：Q3 优先，H1 兜底
    fp = os.path.join(WH, "fina", fn)
    if not os.path.exists(fp):
        continue
    n = 0
    for r in read_csv(fp):
        fina[r["ts_code"]] = r
        n += 1
    print(f"  {fn}: {n} rows", flush=True)
print(f"  fina total codes={len(fina)}", flush=True)

# ---------- universe filter (v1.3) ----------
cut = date(2025, 10, 23)
stats = {"all": 0, "BJ": 0, "GEM_STAR": 0, "ST": 0, "NEW": 0, "SUSPEND": 0,
         "NO_FINA": 0, "NO_QUOTE": 0, "ILLIQ": 0}
universe = []
for code, b in basic.items():
    stats["all"] += 1
    if code.endswith(".BJ"):
        stats["BJ"] += 1
        continue
    if code.startswith(("300", "301", "688", "689")):  # 创业板 300/301，科创板 688/689
        stats["GEM_STAR"] += 1
        continue
    if "ST" in b["name"].upper():
        stats["ST"] += 1
        continue
    ld = b.get("list_date") or ""
    try:
        if date(int(ld[:4]), int(ld[4:6]), int(ld[6:])) > cut:
            stats["NEW"] += 1
            continue
    except Exception:
        pass
    if code in suspend:
        stats["SUSPEND"] += 1
        continue
    # 财务数据缺失 = 信息不透明，直接出局（同时避免质量因子因缺失被整体剔除）
    if code not in fina:
        stats["NO_FINA"] += 1
        continue
    rows = daily.get(code, [])
    if not rows:
        stats["NO_QUOTE"] += 1
        continue
    amts = [r[4] for r in rows if r[4] is not None]
    if amts and statistics.fmean(amts) < 50_000:  # tushare amount 单位为千元：5000万元 = 50,000 千元
        stats["ILLIQ"] += 1
        continue
    universe.append(code)
print(f"universe: {len(universe)}  (stats={stats})", flush=True)

# ---------- compute raw factors ----------
print("computing factors...", flush=True)
F = {}
for code in universe:
    f = {}
    rows = daily.get(code, [])
    closes = [r[1] for r in rows if r[1] is not None]
    highs = [r[2] for r in rows if r[2] is not None]
    lows = [r[3] for r in rows if r[3] is not None]
    amts = [r[4] for r in rows if r[4] is not None]

    def mom(n):
        if len(closes) < n + 1:
            return None
        base = closes[-(n + 1)]
        return closes[-1] / base - 1.0 if base else None

    f["mom_5d"], f["mom_10d"], f["mom_20d"] = mom(5), mom(10), mom(20)
    if len(closes) >= 6:
        rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes)) if closes[i - 1]]
        f["vol_20d_inv"] = -statistics.pstdev(rets) if len(rets) >= 5 else None
    else:
        f["vol_20d_inv"] = None
    if closes:
        peak, mdd = closes[0], 0.0
        for c in closes:
            peak = max(peak, c)
            mdd = min(mdd, c / peak - 1.0)
        f["mdd_20d_inv"] = mdd
    else:
        f["mdd_20d_inv"] = None
    if closes and highs and lows:
        lo, hi = min(lows), max(highs)
        f["price_pos_20d"] = (closes[-1] - lo) / (hi - lo) if hi > lo else 0.5
    else:
        f["price_pos_20d"] = None
    if len(closes) >= 5 and len(amts) == len(closes):
        mc, ma = statistics.fmean(closes), statistics.fmean(amts)
        num = sum((c - mc) * (a - ma) for c, a in zip(closes, amts))
        dc = math.sqrt(sum((c - mc) ** 2 for c in closes))
        da = math.sqrt(sum((a - ma) ** 2 for a in amts))
        f["pv_corr_20d"] = num / (dc * da) if dc > 0 and da > 0 else None
    else:
        f["pv_corr_20d"] = None
    if len(amts) >= 5:
        n = len(amts)
        xs = list(range(n))
        mx, my = statistics.fmean(xs), statistics.fmean(amts)
        den = sum((x - mx) ** 2 for x in xs)
        f["turnover_trend_20d"] = sum((x - mx) * (y - my) for x, y in zip(xs, amts)) / den if den else None
    else:
        f["turnover_trend_20d"] = None
    w = weekly.get(code, [])
    wc = [c for _, c in w if c is not None]
    f["mom_60d"] = (wc[-1] / wc[-14] - 1.0) if len(wc) >= 14 else None
    db = dbasic.get(code, {})
    pe, pb, ps = fnum(db.get("pe_ttm")), fnum(db.get("pb")), fnum(db.get("ps_ttm"))
    f["ep_ttm"] = 1.0 / pe if pe and pe > 0 else None
    f["bp_ttm"] = 1.0 / pb if pb and pb > 0 else None
    f["sp_ttm"] = 1.0 / ps if ps and ps > 0 else None
    f["turnover_rate"] = fnum(db.get("turnover_rate"))
    fi = fina.get(code, {})
    f["roe_ttm"] = fnum(fi.get("roe"))
    f["gross_margin_ttm"] = fnum(fi.get("grossprofit_margin"))
    f["net_margin_ttm"] = fnum(fi.get("netprofit_margin"))
    f["tr_yoy"] = fnum(fi.get("tr_yoy"))
    F[code] = f

n = len(universe)
cover = {fac: sum(1 for c in universe if F[c][fac] is not None) for fac in FACTORS}
print("coverage:", {k: f"{v*100//n}%" for k, v in cover.items()}, flush=True)

active = [fac for fac in FACTORS if cover[fac] > 0.70 * n]
dropped = [fac for fac in FACTORS if cover[fac] <= 0.70 * n]
print(f"active={len(active)} dropped={dropped}", flush=True)

logmv = {}
for c in universe:
    mv = fnum((dbasic.get(c) or {}).get("total_mv"))
    logmv[c] = math.log(mv * 10000) if mv and mv > 0 else None  # 万元 -> 元


def winsorize(vals):
    xs = sorted(vals.values())
    med = statistics.median(xs)
    mad = statistics.median([abs(x - med) for x in xs])
    if mad == 0:
        return vals
    lo, hi = med - 3 * mad, med + 3 * mad
    return {c: min(max(v, lo), hi) for c, v in vals.items()}


def rank_pct(vals):
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


def neutralize(vals):
    pairs = [(logmv[c], v) for c, v in vals.items() if logmv.get(c) is not None]
    if len(pairs) < 3:
        return vals
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return vals
    b = sum((x - mx) * (y - my) for x, y in pairs) / den
    a = my - b * mx
    return {c: (v - (a + b * logmv[c])) if logmv.get(c) is not None else v for c, v in vals.items()}


print("scoring...", flush=True)
R = {}
for fac in active:
    vals = {c: F[c][fac] for c in universe if F[c][fac] is not None}
    if len(vals) < 10:
        continue
    vals = winsorize(vals)
    vals = neutralize(vals)
    R[fac] = rank_pct(vals)

scores = {}
for c in universe:
    num = den = 0.0
    for fac in active:
        if fac in R and c in R[fac]:
            num += R[fac][c] * W[fac]
            den += W[fac]
    scores[c] = num / den if den > 0 else None

ranked = sorted([c for c in universe if scores[c] is not None], key=lambda c: -scores[c])


def reasons(c, k=3):
    contrib = [(R[fac][c] * W[fac], fac, R[fac][c]) for fac in active if fac in R and c in R[fac]]
    contrib.sort(reverse=True)
    return [f"{fac} 百分位{p:.0%}" for _, fac, p in contrib[:k]]


OUT = os.path.join(WH, "scores_full.csv")
with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["rank", "ts_code", "name", "industry", "score"] + FACTORS)
    for i, c in enumerate(ranked, 1):
        b = basic[c]
        w.writerow([i, c, b["name"], b["industry"], round(scores[c], 4)] +
                   ["" if F[c][fac] is None else round(F[c][fac], 4) for fac in FACTORS])

os.makedirs(os.path.dirname(OUT_POOL), exist_ok=True)
pool = {
    "date": BASE_DATE,
    "strategy_version": "v1.3",
    "universe_size": n,
    "count": min(POOL_SIZE, len(ranked)),
    "stocks": [
        {"code": c, "name": basic[c]["name"], "score": round(scores[c], 4), "reasons": reasons(c)}
        for c in ranked[:POOL_SIZE]
    ],
    "notes": {
        "mode": "rehearsal",
        "run_at": "2026-10-25 manual",
        "source": "local warehouse (data/warehouse), zero MCP calls during scoring",
        "universe_filter": stats,
        "factor_coverage": {k: round(v / n, 3) for k, v in cover.items()},
        "factors_dropped": dropped,
        "fina_report_period": "Q3 20260930 优先，缺失回退 H1 20260630",
        "neutralization": "log(total_mv) OLS residual",
    },
}
with open(OUT_POOL, "w", encoding="utf-8") as f:
    json.dump(pool, f, ensure_ascii=False, indent=2)

print(f"\nscored={len(ranked)} universe={n}")
print("TOP 15:")
for i, c in enumerate(ranked[:15], 1):
    print(f"{i:>2}. {basic[c]['name']:<8} {c} {scores[c]:.3f} | {'; '.join(reasons(c))}")
print(f"\nwrote {OUT_SCORES if False else OUT}")
print(f"wrote {OUT_POOL}")
