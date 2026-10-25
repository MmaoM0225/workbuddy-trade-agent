# -*- coding: utf-8 -*-
"""全市场 17 因子打分（权重/规则从 params_current 指向的版本读取），读取 data/warehouse/ 本地仓库。
输出：data/warehouse/scores_full.csv + state/pool.json（正式）
彩排时用环境变量 POOL_OUT 指向 test/state/pool.json。
"""
import csv
import glob
import json
import math
import os
import statistics
from datetime import date, datetime, timedelta

ROOT = r"E:\cashfree\agent"
WH = os.path.join(ROOT, "data", "warehouse")
# 基准日 = daily_basic 目录里最新的一天
_db_dates = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(WH, "daily_basic", "*.csv")))
BASE_DATE = _db_dates[-1] if _db_dates else "20261023"
OUT_SCORES = os.path.join(WH, "scores_full.csv")
# 正式跑写 state/pool.json；彩排时用环境变量 POOL_OUT 指向 test/state/pool.json
OUT_POOL = os.environ.get("POOL_OUT") or os.path.join(ROOT, "state", "pool.json")

# ---------- params：版本与权重全部从 knowledge/params_current.txt 指向的文件读取 ----------
KN = os.path.join(ROOT, "knowledge")
VERSION = open(os.path.join(KN, "params_current.txt"), encoding="utf-8").read().strip()
PARAMS = json.load(open(os.path.join(KN, f"params_{VERSION}.json"), encoding="utf-8"))
_strategy = PARAMS["strategy"]
W = {k: v["weight"] for k, v in _strategy["factors"].items()}
GROUPS = _strategy["scoring_pipeline"]["factor_groups"]
UNIV = _strategy["universe"]
POOL_SIZE = int(_strategy.get("pool_size", 50))
FACTORS = list(W.keys())
_mode = "production" if os.path.abspath(OUT_POOL).startswith(os.path.abspath(os.path.join(ROOT, "state"))) else "rehearsal"
print(f"params={VERSION} mode={_mode} base_date={BASE_DATE} weight_sum={sum(W.values()):.4f}", flush=True)


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

# ---------- universe filter（规则来自 params.strategy.universe）----------
_min_days = int(UNIV.get("min_list_days", 250))
cut = datetime.strptime(BASE_DATE, "%Y%m%d").date() - timedelta(days=round(_min_days * 365 / 250))
# tushare daily.amount 单位为千元：5000 万元 = 50,000 千元
_amt_min_qian = float(UNIV.get("min_amount_20d_avg_cny", 50000000)) / 1000.0
stats = {"all": 0, "BJ": 0, "GEM_STAR": 0, "ST": 0, "NEW": 0, "SUSPEND": 0,
         "NO_FINA": 0, "NO_QUOTE": 0, "ILLIQ": 0}
universe = []
for code, b in basic.items():
    stats["all"] += 1
    if UNIV.get("exclude_bj", True) and code.endswith(".BJ"):
        stats["BJ"] += 1
        continue
    if UNIV.get("exclude_gem_star", True) and code.startswith(("300", "301", "688", "689")):
        stats["GEM_STAR"] += 1
        continue
    if UNIV.get("exclude_st", True) and "ST" in b["name"].upper():
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
    # v1.8: 财务数据缺失不再导致出局——选股只用量价/技术/估值，财务由研究员在 Top50 阶段处理
    if UNIV.get("require_fina", False) and code not in fina:
        stats["NO_FINA"] += 1
        continue
    rows = daily.get(code, [])
    if not rows:
        stats["NO_QUOTE"] += 1
        continue
    amts = [r[4] for r in rows[-20:] if r[4] is not None]  # 20 日平均成交额（不是全历史）
    if amts and statistics.fmean(amts) < _amt_min_qian:
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
    closes = [r[1] for r in rows if r[1] is not None]          # 全历史收盘（仅 mom_* 用尾部）
    # 20 日窗口：所有 *_20d 因子严格只用最后 20 个交易日（backfill 后仓库有 450 天，必须切片）
    w20 = rows[-20:]
    c20 = [r[1] for r in w20 if r[1] is not None]
    h20 = [r[2] for r in w20 if r[2] is not None]
    l20 = [r[3] for r in w20 if r[3] is not None]
    a20 = [r[4] for r in w20 if r[4] is not None]

    def mom(n):
        if len(closes) < n + 1:
            return None
        base = closes[-(n + 1)]
        return closes[-1] / base - 1.0 if base else None

    f["mom_5d"], f["mom_10d"], f["mom_20d"] = mom(5), mom(10), mom(20)
    if len(c20) >= 6:
        rets = [c20[i] / c20[i - 1] - 1 for i in range(1, len(c20)) if c20[i - 1]]
        f["vol_20d_inv"] = -statistics.pstdev(rets) if len(rets) >= 5 else None
    else:
        f["vol_20d_inv"] = None
    if c20:
        peak, mdd = c20[0], 0.0
        for c in c20:
            peak = max(peak, c)
            mdd = min(mdd, c / peak - 1.0)
        f["mdd_20d_inv"] = mdd
    else:
        f["mdd_20d_inv"] = None
    if c20 and h20 and l20:
        lo, hi = min(l20), max(h20)
        f["price_pos_20d"] = (c20[-1] - lo) / (hi - lo) if hi > lo else 0.5
    else:
        f["price_pos_20d"] = None
    if len(c20) >= 5 and len(a20) == len(c20):
        mc, ma = statistics.fmean(c20), statistics.fmean(a20)
        num = sum((c - mc) * (a - ma) for c, a in zip(c20, a20))
        dc = math.sqrt(sum((c - mc) ** 2 for c in c20))
        da = math.sqrt(sum((a - ma) ** 2 for a in a20))
        f["pv_corr_20d"] = num / (dc * da) if dc > 0 and da > 0 else None
    else:
        f["pv_corr_20d"] = None
    if len(a20) >= 5:
        n = len(a20)
        xs = list(range(n))
        mx, my = statistics.fmean(xs), statistics.fmean(a20)
        den = sum((x - mx) ** 2 for x in xs)
        f["turnover_trend_20d"] = sum((x - mx) * (y - my) for x, y in zip(xs, a20)) / den if den else None
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
# v1.8: 财务指标不参与选股打分，但仍随 CSV 落盘，供研究员计算质量分使用
FINA_COLS = ["roe_ttm", "gross_margin_ttm", "net_margin_ttm", "tr_yoy"]
with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["rank", "ts_code", "name", "industry", "score"] + FACTORS + FINA_COLS)
    for i, c in enumerate(ranked, 1):
        b = basic[c]
        w.writerow([i, c, b["name"], b["industry"], round(scores[c], 4)] +
                   ["" if F[c][fac] is None else round(F[c][fac], 4) for fac in FACTORS] +
                   ["" if F[c].get(k) is None else round(F[c][k], 4) for k in FINA_COLS])

os.makedirs(os.path.dirname(OUT_POOL), exist_ok=True)
pool = {
    "date": BASE_DATE,
    "strategy_version": VERSION,
    "universe_size": n,
    "count": min(POOL_SIZE, len(ranked)),
    "stocks": [
        {"code": c, "name": basic[c]["name"], "score": round(scores[c], 4), "reasons": reasons(c)}
        for c in ranked[:POOL_SIZE]
    ],
    "notes": {
        "mode": _mode,
        "run_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "params_file": f"params_{VERSION}.json",
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
