#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""因子 IC 检验：13 个选股因子 + 4 个财务因子对未来 20 日收益的预测力。

方法：按选股日（有 daily_basic 的交易日）做横截面 Spearman rank IC。
  rank IC = corr( rank(factor_i), rank(fwd_ret_20_i) )
输出：IC 均值、ICIR（均值/标准差）、IC>0 占比、t 值、样本数。

用法：python scripts/ic_analysis.py [--horizon 20]
"""
import argparse
import csv
import glob
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = r"E:\cashfree\agent"
WH = os.path.join(ROOT, "data", "warehouse")


def load_basic():
    with open(os.path.join(WH, "meta", "stock_basic.csv"), encoding="utf-8-sig") as f:
        return {r["ts_code"]: r for r in csv.DictReader(f)}


def load_hist():
    rows = []
    for fp in sorted(glob.glob(os.path.join(WH, "daily", "*.csv"))):
        d = Path(fp).stem
        with open(fp, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                try:
                    rows.append((r["ts_code"], d, float(r["close"]), float(r["high"]),
                                 float(r["low"]), float(r["amount"])))
                except (TypeError, ValueError):
                    continue
    df = pd.DataFrame(rows, columns=["code", "date", "close", "high", "low", "amount"])
    for c in ("close", "high", "low", "amount"):
        df[c] = df[c].astype("float32")
    return df


def load_dbasic_dates():
    return sorted(Path(f).stem for f in glob.glob(os.path.join(WH, "daily_basic", "*.csv")))


def load_dbasic(d):
    p = os.path.join(WH, "daily_basic", d + ".csv")
    if not os.path.exists(p):
        return {}
    out = {}
    with open(p, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            out[r["ts_code"]] = r
    return out


def load_fina():
    p = os.path.join(WH, "fina", "history.csv")
    h = {}
    if not os.path.exists(p):
        return h
    with open(p, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            pub = (r.get("pub_date") or "").replace("-", "")
            if len(pub) < 8:
                continue
            h.setdefault(r["ts_code"], []).append((pub, r))
    for k in h:
        h[k].sort(key=lambda x: x[0])
    return h


def fina_at(h, code, base):
    best = None
    for pub, r in h.get(code) or []:
        if pub <= base:
            best = r
        else:
            break
    return best or {}


def fnum(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=20)
    ap.add_argument("--split", default=None, help="YYYYMMDD，前半/后半分段检验最优组稳定性")
    a = ap.parse_args()
    H = a.horizon

    print("loading daily bars...", flush=True)
    df = load_hist()
    dates_all = sorted(df["date"].unique())
    print("bars: %d rows, %d dates, %d codes" % (len(df), len(dates_all), df["code"].nunique()), flush=True)

    print("computing price/volume factors...", flush=True)
    feats = []
    for code, g in df.groupby("code", sort=False):
        g = g.sort_values("date")
        d_arr = g["date"].values
        c = g["close"].to_numpy(np.float64)
        h = g["high"].to_numpy(np.float64)
        lo = g["low"].to_numpy(np.float64)
        am = g["amount"].to_numpy(np.float64)
        n = len(c)
        if n < 30:
            continue
        ret = np.empty(n); ret[0] = np.nan; ret[1:] = c[1:] / c[:-1] - 1

        def shift_ret(k):
            r = np.full(n, np.nan)
            if n > k:
                r[k:] = c[k:] / c[:-k] - 1
            return r

        def roll_std(x, w):
            s = pd.Series(x).rolling(w).std().to_numpy()
            return s

        def roll_min(x, w):
            return pd.Series(x).rolling(w).min().to_numpy()

        def roll_max(x, w):
            return pd.Series(x).rolling(w).max().to_numpy()

        def roll_corr(x, y, w):
            return pd.Series(x).rolling(w).corr(pd.Series(y)).to_numpy()

        def roll_slope(y, w):
            out = np.full(len(y), np.nan)
            x = np.arange(w)
            xm = x.mean()
            den = ((x - xm) ** 2).sum()
            for i in range(w - 1, len(y)):
                seg = y[i - w + 1:i + 1]
                out[i] = ((x - xm) * (seg - seg.mean())).sum() / den if den else np.nan
            return out

        vol20 = -roll_std(ret, 20)
        peak = pd.Series(c).rolling(20).max().to_numpy()
        mdd20 = -((c / peak) - 1)
        mn20, mx20 = roll_min(lo, 20), roll_max(h, 20)
        pos20 = np.where(mx20 > mn20, (c - mn20) / (mx20 - mn20), 0.5)
        corr20 = roll_corr(c, am, 20)
        slope20 = roll_slope(am, 20)
        fwd = np.full(n, np.nan)
        if n > H:
            fwd[:-H] = c[H:] / c[:-H] - 1

        feats.append(pd.DataFrame({
            "code": code, "date": d_arr,
            "mom_5d": shift_ret(5), "mom_10d": shift_ret(10), "mom_20d": shift_ret(20),
            "vol_20d_inv": vol20, "mdd_20d_inv": mdd20,
            "price_pos_20d": pos20, "pv_corr_20d": corr20, "turnover_trend_20d": slope20,
            "fwd_ret": fwd,
        }))
    F = pd.concat(feats, ignore_index=True)
    print("factor table: %d rows" % len(F), flush=True)

    basic = load_basic()
    F = F[~F["code"].str.endswith(".BJ")]
    F = F[~F["code"].str[:3].isin(["300", "301", "688", "689"])]
    F = F[~F["code"].map(lambda c: "ST" in (basic.get(c, {}).get("name", "")).upper())]

    sel_dates = [d for d in load_dbasic_dates() if d in set(dates_all)]
    print("selection dates with daily_basic: %d" % len(sel_dates), flush=True)

    print("attaching valuation factors...", flush=True)
    val_rows = []
    for d in sel_dates:
        db = load_dbasic(d)
        for code, r in db.items():
            pe, pb, ps = fnum(r.get("pe_ttm")), fnum(r.get("pb")), fnum(r.get("ps_ttm"))
            val_rows.append((code, d,
                             1 / pe if pe and pe > 0 else np.nan,
                             1 / pb if pb and pb > 0 else np.nan,
                             1 / ps if ps and ps > 0 else np.nan,
                             fnum(r.get("turnover_rate"))))
    V = pd.DataFrame(val_rows, columns=["code", "date", "ep_ttm", "bp_ttm", "sp_ttm", "turnover_rate"])
    F = F.merge(V, on=["code", "date"], how="inner")
    print("merged: %d rows" % len(F), flush=True)

    print("attaching financial factors (point-in-time)...", flush=True)
    fh = load_fina()
    F["roe_ttm"] = np.nan; F["net_margin_ttm"] = np.nan
    F["gross_margin_ttm"] = np.nan; F["tr_yoy"] = np.nan
    for d, idx in F.groupby("date").groups.items():
        rows = F.loc[idx]
        vals = {c: fina_at(fh, c, d) for c in rows["code"]}
        F.loc[idx, "roe_ttm"] = [fnum(vals[c].get("roe_ttm")) for c in rows["code"]]
        F.loc[idx, "net_margin_ttm"] = [fnum(vals[c].get("net_margin")) for c in rows["code"]]
        F.loc[idx, "gross_margin_ttm"] = [fnum(vals[c].get("gross_margin")) for c in rows["code"]]
        F.loc[idx, "tr_yoy"] = [fnum(vals[c].get("rev_yoy")) for c in rows["code"]]
    print("financials attached", flush=True)

    FACTORS = ["mom_5d", "mom_10d", "mom_20d", "vol_20d_inv", "mdd_20d_inv",
               "price_pos_20d", "pv_corr_20d", "turnover_trend_20d",
               "ep_ttm", "bp_ttm", "sp_ttm", "turnover_rate",
               "roe_ttm", "net_margin_ttm", "gross_margin_ttm", "tr_yoy"]
    for f in FACTORS:
        F[f] = pd.to_numeric(F[f], errors="coerce")
    F["fwd_ret"] = pd.to_numeric(F["fwd_ret"], errors="coerce")

    print("\ncomputing rank IC per date...", flush=True)
    ics = {f: [] for f in FACTORS}
    for d, g in F.groupby("date"):
        if len(g) < 200:
            continue
        fr = g["fwd_ret"].to_numpy()
        if np.isnan(fr).all():
            continue
        rr = pd.Series(fr).rank().to_numpy()
        for f in FACTORS:
            v = g[f].to_numpy()
            m = ~np.isnan(v) & ~np.isnan(fr)
            if m.sum() < 100:
                continue
            vr = pd.Series(v[m]).rank().to_numpy()
            ic = np.corrcoef(vr, rr[m])[0, 1]
            if not np.isnan(ic):
                ics[f].append(ic)

    print("\n%-20s %8s %8s %8s %8s %6s" % ("因子", "IC均值", "IC标准差", "ICIR", "IC>0占比", "样本"))
    rows = []
    for f in FACTORS:
        v = np.array(ics[f])
        if len(v) < 20:
            print("%-20s 样本不足(%d)" % (f, len(v)))
            continue
        m, s = v.mean(), v.std(ddof=1)
        icir = m / s if s else 0
        t = icir * np.sqrt(len(v))
        win = (v > 0).mean() * 100
        rows.append({"factor": f, "ic_mean": round(float(m), 4), "ic_std": round(float(s), 4),
                     "icir": round(float(icir), 3), "ic_pos_pct": round(float(win), 1),
                     "t_stat": round(float(t), 2), "n": int(len(v))})
        print("%-20s %+8.4f %8.4f %+8.3f %7.1f%% %6d" % (f, m, s, icir, win, len(v)))

    rows.sort(key=lambda x: -abs(x["ic_mean"]))
    out = os.path.join(ROOT, "test", "ic_analysis.json")
    json.dump({"horizon": H, "dates": len(sel_dates), "results": rows},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("\nwritten:", out)

    # ---- 分位分组收益：检验因子是否存在非线性/门槛效应 ----
    def group_returns(factor_df, label):
        GROUPS = 5
        rows_out = {}
        for f in FACTORS:
            acc = {i: [] for i in range(GROUPS)}
            for d, g in factor_df.groupby("date"):
                sub = g[[f, "fwd_ret"]].dropna()
                if len(sub) < 300:
                    continue
                try:
                    q = pd.qcut(sub[f], GROUPS, labels=False, duplicates="drop")
                except ValueError:
                    continue
                fr = sub["fwd_ret"].to_numpy()
                qv = q.to_numpy()
                for i in range(GROUPS):
                    m = qv == i
                    if m.sum() >= 20:
                        acc[i].append(float(fr[m].mean()))
            means = [np.mean(acc[i]) * 10000 if acc[i] else np.nan for i in range(GROUPS)]
            if np.isnan(means).all():
                continue
            rows_out[f] = means
        print("\n=== 分组收益 [%s]  样本日=%d ===" % (label, factor_df["date"].nunique()), flush=True)
        print("%-20s %8s %8s %8s %8s %8s %9s %8s" % ("因子", "Q1", "Q2", "Q3", "Q4", "Q5", "最优组", "最优值"), flush=True)
        best = {}
        for f, means in rows_out.items():
            arr = np.array(means, dtype=float)
            bi = int(np.nanargmax(arr)) if not np.isnan(arr).all() else -1
            best[f] = bi
            print("%-20s %8.1f %8.1f %8.1f %8.1f %8.1f %9s %8.1f" % (
                f, means[0], means[1], means[2], means[3], means[4],
                "Q%d" % (bi + 1) if bi >= 0 else "-",
                means[bi] if bi >= 0 else np.nan), flush=True)
        return rows_out, best

    all_groups, all_best = group_returns(F, "全样本")

    if a.split:
        cuts = [x.strip() for x in a.split.split(",") if x.strip()]
        segments = []
        prev = None
        for c in cuts:
            segments.append((prev, c))
            prev = c
        segments.append((prev, None))
        seg_best, seg_worst = {}, {}
        for lo, hi in segments:
            sub = F
            if lo:
                sub = sub[sub["date"] >= lo]
            if hi:
                sub = sub[sub["date"] < hi]
            label = "%s~%s" % (lo or "起", hi or "今")
            g, b = group_returns(sub, label)
            best_map, worst_map = {}, {}
            for f, means in g.items():
                arr = np.array(means, dtype=float)
                if np.isnan(arr).all():
                    continue
                best_map[f] = int(np.nanargmax(arr))
                worst_map[f] = int(np.nanargmin(arr))
            seg_best[label] = best_map
            seg_worst[label] = worst_map

        print("\n=== 最差组跨期一致性（排除器的依据）===", flush=True)
        labels = list(seg_best.keys())
        print("%-20s " % "因子" + " ".join("%10s" % l for l in labels) + "   %s" % "稳定")
        stable = 0
        for f in FACTORS:
            ws = [seg_worst[l].get(f) for l in labels]
            if any(w is None for w in ws):
                continue
            same = len(set(ws)) == 1
            stable += 1 if same else 0
            print("%-20s " % f + " ".join("%10s" % ("Q%d" % (w + 1)) for w in ws) + "   %s" % ("一致" if same else "漂移"))
        print("\n最差组稳定因子数: %d / %d" % (stable, len(FACTORS)), flush=True)

        print("\n=== 最优组跨期一致性 ===", flush=True)
        print("%-20s " % "因子" + " ".join("%10s" % l for l in labels) + "   %s" % "稳定")
        stable_b = 0
        for f in FACTORS:
            bs = [seg_best[l].get(f) for l in labels]
            if any(b is None for b in bs):
                continue
            same = len(set(bs)) == 1
            stable_b += 1 if same else 0
            print("%-20s " % f + " ".join("%10s" % ("Q%d" % (b + 1)) for b in bs) + "   %s" % ("一致" if same else "漂移"))
        print("\n最优组稳定因子数: %d / %d" % (stable_b, len(FACTORS)), flush=True)

        json.dump({"segments": labels, "worst": seg_worst, "best": seg_best},
                  open(os.path.join(ROOT, "test", "ic_stability.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print("written:", os.path.join(ROOT, "test", "ic_stability.json"))


if __name__ == "__main__":
    main()
