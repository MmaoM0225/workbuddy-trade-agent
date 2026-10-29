#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backtest_dca_v3.py - 定投策略 6 年回测（宽基 + 申万二级行业）

口径（与 v3.0 参数一致，不看本金）：
  每期投入 = unit × 倍数（unit 默认 10 元，见 knowledge/index_params.json execute.unit_amount_cny）
  宽基：分位<40 就买；行业：分位<40 的按升序取前 top_industry 个
  卖出：75 卖 1/3、85 再卖 1/2、95 清仓，间隔 >=20 交易日
  同基金只买一次
  收益核算：总资产 = 累计投入 + 已实现盈亏 + 未实现盈亏

价格：场外/LOF 的复权净值 adj_nav（含分红再投资、已扣管理费）
估值：宽基自算滚动分位；行业用申万官方 5 年分位（无前视）

用法：
  python scripts/backtest_dca_v3.py
  python scripts/backtest_dca_v3.py --start 20201102 --top 5 --unit 10
"""
import argparse, csv, json, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WD = os.path.join(ROOT, "data", "warehouse")
VAL = os.path.join(WD, "index_valuation")
SWD = os.path.join(WD, "sw_industry")
NAVD = os.path.join(WD, "fund_nav")
POOL = os.path.join(ROOT, "data", "index_universe.json")
IFM = os.path.join(ROOT, "data", "industry_fund_map.json")
PARAMS = os.path.join(ROOT, "knowledge", "index_params.json")

CYCLICAL = {"000986.SH", "399975.SZ"}
GROWTH = {"399006.SZ", "000688.SH", "000935.SH", "HSTECH.HK", "IXIC.US", "NDX.US", "000933.SH"}


def fnum(v):
    try:
        return float(v) if v not in ("", None, "--") else None
    except (TypeError, ValueError):
        return None


def style_w(code):
    if code in CYCLICAL:
        return 0.3, 0.7
    if code in GROWTH:
        return 0.7, 0.3
    return 0.5, 0.5


def pct_rank(series, win, mp):
    out = [None] * len(series)
    for i, v in enumerate(series):
        if v is None:
            continue
        h = [x for x in series[max(0, i - win + 1):i + 1] if x is not None]
        if len(h) < mp:
            continue
        out[i] = (sum(1 for x in h if x < v) + 0.5 * sum(1 for x in h if x == v)) / len(h) * 100.0
    return out


def align(cal, dates, vals):
    out = np.full(len(cal), np.nan)
    j, last = 0, np.nan
    for i, d in enumerate(cal):
        while j < len(dates) and dates[j] <= d:
            last = vals[j]
            j += 1
        out[i] = last
    return out


RECYCLE = True    # True = 卖出回款优先用于再投（不再闲置）
SELL_RULE = "ladder"   # ladder=持续减仓（默认）| stage=旧的 75/85/95 各触发一次
USE_ADJ = False   # True = 用 adj_nav（含分红再投资）；默认 unit_nav（保守）


def load_nav(fp):
    if not os.path.exists(fp):
        return None
    ds, vs = [], []
    with open(fp, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            v = fnum(r.get("adj_nav") if USE_ADJ else r.get("unit_nav"))
            if v:
                ds.append(r["nav_date"])
                vs.append(v)
    return (ds, vs) if ds else None


UNIVERSE = set()   # 诊断用白名单；空=全部
LEGACY = False   # True = 复现 2026-10-29 前的老口径（宽基 PE/PB 0.5:0.5、行业 (PB+PS)/2、无 caps）


def _zone_of(score, params):
    for z in params["zones"]:
        if z["lo"] <= score < z["hi"]:
            return z
    return params["zones"][-1]


def build(cal, params, top_industry):
    """构造每个标的的**逐日最终分数**（已套用模型权重 + pick_zone 全部否决规则）。

    与实盘 index_valuation_signal 共用 pick_zone，避免"回测一个策略、实盘另一个策略"。
    """
    from index_valuation_signal import pick_zone, sell_step

    items = {}
    with open(POOL, encoding="utf-8") as f:
        uni = json.load(f)["indices"]
    win, mp = params["window_days"], params["min_periods"]
    bmodels = params.get("broad_models", {}) or {}
    bmap = params.get("broad_model_map", {}) or {}
    imodels = params.get("industry_models", {}) or {}
    imap = params.get("industry_model_map", {}) or {}

    def model_score(weights, avails):
        num = den = 0.0
        for k, w in weights.items():
            x = avails.get(k)
            if x is None:
                continue
            num += w * x
            den += w
        return (num / den) if den > 0 else None

    # ---- 宽基：自算滚动分位（PE 剔负 / PB / 股息率）----
    for m in uni:
        if m.get("enabled") is False:
            continue   # 人工停用的标的（越南/SENSEX/中韩半导体）不参与回测，与实盘一致
        if UNIVERSE and m["code"] not in UNIVERSE:
            continue   # 诊断用：只跑指定宽基（复现历史配置）
        fp = os.path.join(VAL, m["code"] + ".csv")
        nav = load_nav(os.path.join(NAVD, (m.get("of_fund") or "") + ".csv"))
        if not os.path.exists(fp) or not nav:
            continue
        rows = []
        with open(fp, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        rows.sort(key=lambda r: r["trade_date"])
        ds = [r["trade_date"] for r in rows]
        pe = [fnum(r["pe_ttm_ex_neg"]) for r in rows]
        pb = [fnum(r["pb_lf"]) for r in rows]
        dv = [fnum(r["dividend_ratio"]) for r in rows]
        pep, pbp, dvp = pct_rank(pe, win, mp), pct_rank(pb, win, mp), pct_rank(dv, win, mp)
        key = bmap.get(m["code"], "M_BROAD_CORE")
        w = (bmodels.get(key) or {}).get("weights") or {"pb": 0.55, "pe": 0.45}
        if LEGACY:
            w = {"pe": 0.5, "pb": 0.5}
        sc, mu = [], []
        for i in range(len(ds)):
            s = model_score(w, {"pe": pep[i], "pb": pbp[i],
                                "div": None if dvp[i] is None else 100.0 - dvp[i]})
            if s is None:
                sc.append(np.nan)
                mu.append(np.nan)
                continue
            zone, _cap, s2 = ((None, None, s) if LEGACY else pick_zone(s, params, pb[i], dv[i], pe[i]))
            zone = zone or _zone_of(s2, params)
            sc.append(s2)
            mu.append(zone["mult"])
        items[m["code"]] = {"kind": "broad", "name": m["name"], "fund": m.get("of_fund"),
                            "score": align(cal, ds, sc), "mult": align(cal, ds, mu),
                            "nav": align(cal, list(nav[0]), list(nav[1]))}

    # ---- 行业：申万官方 5 年分位（PB / PS / 股息），point-in-time 列 ----
    with open(IFM, encoding="utf-8") as f:
        fm = json.load(f)["map"]
    for code, v in fm.items():
        p = v.get("primary")
        if not p or p.get("venue") not in ("场外", "LOF"):
            continue
        fp = os.path.join(SWD, code + ".csv")
        nav = load_nav(os.path.join(NAVD, p["fund_code"] + ".csv"))
        if not os.path.exists(fp) or not nav:
            continue
        ds, sc, mu, roe = [], [], [], []
        key = imap.get(v["name"], "M_DEFAULT")
        w = (imodels.get(key) or {}).get("weights") or {"pb": 0.5, "ps": 0.5}
        if LEGACY:
            w = {"pb": 0.5, "ps": 0.5}
        with open(fp, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                pbp_, psp_ = fnum(r.get("pb_pct")), fnum(r.get("ps_pct"))
                dvp_ = fnum(r.get("div_pct"))
                pbv, pev = fnum(r.get("pb_lf")), fnum(r.get("pe_ttm"))
                s = model_score(w, {"pb": pbp_, "ps": psp_,
                                    "div": None if dvp_ is None else 100.0 - dvp_})
                ds.append(r["date"])
                if s is None:
                    sc.append(np.nan)
                    mu.append(np.nan)
                else:
                    zone, _cap, s2 = ((None, None, s) if LEGACY else pick_zone(s, params, pbv, fnum(r.get("div_yield_ttm")), pev))
                    zone = zone or _zone_of(s2, params)
                    sc.append(s2)
                    mu.append(zone["mult"])
                roe.append(pbv / pev if (pbv and pev and pev > 0) else None)
        roe_chg = [None] * len(roe)
        for i in range(len(roe)):
            j = i - 244
            if j >= 0 and roe[i] is not None and roe[j]:
                roe_chg[i] = roe[i] / roe[j] - 1.0
        items[code] = {"kind": "industry", "name": v["name"], "fund": p["fund_code"],
                       "score": align(cal, ds, sc), "mult": align(cal, ds, mu),
                       "nav": align(cal, list(nav[0]), list(nav[1])),
                       "roe_chg": align(cal, ds, roe_chg)}
    return items


def xirr(flows, end_date, end_value):
    """资金加权年化收益率（含所有买入现金流 + 期末市值）。flows=[(YYYYMMDD, 金额)]"""
    from datetime import date
    def dt(x):
        return date(int(x[:4]), int(x[4:6]), int(x[6:8]))
    t0 = dt(flows[0][0])
    pts = [((dt(d) - t0).days / 365.0, -a) for d, a in flows]
    pts.append(((dt(end_date) - t0).days / 365.0, end_value))
    lo, hi = -0.99, 3.0
    for _ in range(300):
        mid = (lo + hi) / 2
        v = sum(cf / (1 + mid) ** t for t, cf in pts)
        if v > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def twr(curve):
    """时间加权收益率：剔除"什么时候投钱"的影响，衡量策略自身表现。"""
    prod, prev = 1.0, None
    for day, inv, real, unreal, mv in curve:
        V = inv + real + unreal
        if prev is not None:
            v0, i0 = prev
            flow = inv - i0
            if v0 > 1e-9 and flow >= 0:
                r = (V - v0 - flow) / v0
                if -1 < r < 5:
                    prod *= (1 + r)
        prev = (V, inv)
    return prod


def run(items, cal, params, unit, top_ind, start_i=0, freq="daily", roe_filter=False, roe_th=0.0):
    from index_valuation_signal import sell_step
    ex = params["execute"]
    rd_cfg = ex.get("cash_redeploy") or {}
    ladder = ex.get("sell_ladder") or []
    _ov = os.environ.get("BT_LADDER")   # 例如 "75:2,80:4,85:8,90:15,95:30"（填倍数 X）
    if _ov:
        ladder = [{"min_score": float(a.split(":")[0]), "mult": float(a.split(":")[1]),
                   "label": "卖%sX" % a.split(":")[1]} for a in _ov.split(",")]
    sell_unit = ex.get("sell_unit_cny") or ex.get("unit_amount_cny", 10)
    legacy_stages = sorted(ex.get("sell_stages") or [], key=lambda x: x["min_score"])
    hold, nav_curve, trades, flows = {}, [], [], []
    cash = 0.0            # 卖出回款现金池
    cash_curve = []       # 每日闲置现金，用于统计
    recycled = 0.0        # 用卖出款再投的累计金额
    invested = realized = 0.0
    seen_month = set()

    for i, d in enumerate(cal):
        # 每日盯市
        for c in list(hold):
            p = items[c]["nav"]
            if i > 0 and not np.isnan(p[i]) and not np.isnan(p[i - 1]) and p[i - 1] > 0:
                hold[c]["value"] *= p[i] / p[i - 1]

        key = d if freq == "daily" else d[:6]
        if key not in seen_month:
            seen_month.add(key)
            sc = {c: it["score"][i] for c, it in items.items()
                  if not np.isnan(it["score"][i]) and not np.isnan(it["nav"][i])}

            # 卖
            for c in list(hold):
                if c not in sc:
                    continue
                s0 = sc[c]
                if SELL_RULE == "stage":
                    # 旧规则：75/85/95 每档只触发一次
                    st = None
                    for s in legacy_stages:
                        if s0 >= s["min_score"]:
                            st = s
                    if not st or st["min_score"] <= hold[c]["stage"]:
                        continue
                    ratio, st_key = st["sell_current_ratio"], st["min_score"]
                    _legacy_ratio = True
                else:
                    # 新规则：持续减仓。>=75 就在每个冷却期按当前档位卖，直到清空
                    st = sell_step(s0, ladder)
                    if not st:
                        continue
                    st_key = st["min_score"]
                if hold[c]["first"] is not None and i - hold[c]["first"] < ex["min_hold_days"]:
                    continue
                if hold[c]["last"] is not None and i - hold[c]["last"] < ex["sell_interval_td"]:
                    continue
                # 按金额倍数卖：sell_unit × mult，最多清空
                if SELL_RULE == "stage":
                    amt = hold[c]["value"] * ratio
                else:
                    amt = min(sell_unit * st.get("mult", 1), hold[c]["value"])
                ratio = amt / hold[c]["value"] if hold[c]["value"] > 0 else 1.0
                if amt <= 0:
                    continue
                cost_out = hold[c]["cost"] * ratio
                realized += amt - cost_out
                cash += amt          # 卖出回款进现金池
                hold[c]["value"] -= amt
                hold[c]["cost"] -= cost_out
                hold[c]["stage"] = st_key
                hold[c]["last"] = i
                trades.append((d, c, items[c]["name"], "S", amt, amt - cost_out))
                if hold[c]["value"] < 0.01:
                    hold.pop(c, None)

            # 买
            from collections import OrderedDict
            seen_f = {}
            cands = []
            for c, it in items.items():
                if c not in sc:
                    continue
                f = it["fund"]
                if f in seen_f:
                    if sc[c] < sc[seen_f[f]]:
                        seen_f[f] = c
                    continue
                seen_f[f] = c
            picked = []
            for f, c in seen_f.items():
                picked.append(c)
            broad = sorted([c for c in picked if items[c]["kind"] == "broad" and sc[c] < 40
                            and items[c]["fund"]], key=lambda c: sc[c])
            ind_pool = [c for c in picked if items[c]["kind"] == "industry" and sc[c] < 40]
            if roe_filter:
                keep = []
                for c in ind_pool:
                    rv = items[c].get("roe_chg")
                    v = rv[i] if rv is not None else np.nan
                    # 盈利改善：ROE 同比 > 阈值；ROE 算不出（PE<=0）视为不合格
                    if not np.isnan(v) and v > roe_th:
                        keep.append(c)
                ind_pool = keep
            ind_pool_all = list(ind_pool)
            ind = sorted(ind_pool, key=lambda c: sc[c])[:top_ind]
            def do_buy(c):
                """买一笔：先花现金池，不足部分记为外部新增投入。返回实际买入金额。"""
                nonlocal cash, recycled, invested
                mlt = items[c]["mult"][i]
                if np.isnan(mlt) or mlt <= 0:
                    return 0.0
                amt = unit * mlt
                pay_cash = min(cash, amt) if RECYCLE else 0.0
                cash -= pay_cash
                recycled += pay_cash
                new_money = amt - pay_cash
                invested += new_money
                if new_money > 0:
                    flows.append((d, new_money))
                if c in hold:
                    hold[c]["value"] += amt
                    hold[c]["cost"] += amt
                    # 不把 last 设为 i：last 是「上次卖出日」，用于卖出冷却
                else:
                    hold[c] = {"value": amt, "cost": amt, "stage": 0, "first": i, "last": None}
                trades.append((d, c, items[c]["name"], "B", amt, 0.0))
                return amt

            bought_today = set()
            for c in broad + ind:
                if do_buy(c) > 0:
                    bought_today.add(c)

            # ---- 现金积压补买：超出 reserve 的回款，按分位升序补买当日没买过的合格标的 ----
            if RECYCLE and rd_cfg.get("enabled"):
                reserve = float(rd_cfg.get("reserve_cny", 0))
                top_n = int(rd_cfg.get("top_n", 0))
                pool = [c for c in (broad + ind_pool_all)
                        if c not in bought_today and sc[c] < 40]
                # 去重 + 按分位升序
                pool = sorted(set(pool), key=lambda c: sc[c])
                added = 0
                for c in pool:
                    if cash <= reserve or added >= top_n:
                        break
                    if do_buy(c) > 0:
                        bought_today.add(c)
                        added += 1

        mv = sum(h["value"] for h in hold.values())
        cost = sum(h["cost"] for h in hold.values())
        nav_curve.append((d, invested, realized, mv - cost, mv))
        cash_curve.append(cash)

    run.last_cash = cash
    run.recycled = recycled
    run.cash_curve = cash_curve
    return nav_curve, trades, hold, invested, realized, flows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="20201102")
    ap.add_argument("--end", default="20261027")
    ap.add_argument("--unit", type=float, default=10)
    ap.add_argument("--legacy", action="store_true", help="用旧口径做对照（无模型、无 caps）")
    ap.add_argument("--broad", default="", help="诊断用：只跑逗号分隔的宽基代码")
    ap.add_argument("--adj", action="store_true", help="用 adj_nav（含分红再投资）对照")
    ap.add_argument("--no-recycle", action="store_true", help="关闭卖出回款再投，现金闲置（对照用）")
    ap.add_argument("--sell-rule", default="ladder", choices=["ladder", "stage"],
                    help="卖出规则：ladder=持续减仓（默认）/ stage=旧的分档各触发一次")
    ap.add_argument("--cal", default="daily", choices=["daily", "index"],
                    help="交易日历来源：daily=按 data/warehouse/daily 文件名（仅 2019-11 起）/ index=按沪深300估值序列")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--freq", default="daily", choices=["daily", "monthly"])
    ap.add_argument("--roe-filter", action="store_true", help="行业需隐含ROE同比改善才买")
    ap.add_argument("--roe-th", type=float, default=None, help="ROE同比阈值，默认取参数文件")
    args = ap.parse_args()
    global LEGACY, UNIVERSE, USE_ADJ, SELL_RULE, RECYCLE
    LEGACY = args.legacy
    RECYCLE = not args.no_recycle
    USE_ADJ = args.adj
    SELL_RULE = args.sell_rule
    UNIVERSE = {c.strip() for c in args.broad.split(",") if c.strip()}

    with open(PARAMS, encoding="utf-8") as f:
        params = json.load(f)
    if args.roe_th is None:
        args.roe_th = params.get("execute", {}).get("industry_roe_filter", {}).get("roe_th", 0.0)
    if args.cal == "index":
        # 用沪深300 的估值序列当交易日历：data/warehouse/daily 只保留近 7 年，
        # 要跑更长的回测必须切到指数序列（2019 年起，回补后 2015 年起）
        with open(os.path.join(VAL, "000300.SH.csv"), encoding="utf-8") as f:
            cal = [r["trade_date"] for r in csv.DictReader(f) if r.get("trade_date")]
    else:
        d0 = os.path.join(WD, "daily")
        cal = sorted(x[:-4] for x in os.listdir(d0) if x.endswith(".csv"))
    cal = [d for d in cal if args.start <= d <= args.end]
    print("日历 %s ~ %s 共 %d 交易日" % (cal[0], cal[-1], len(cal)))

    items = build(cal, params, args.top)
    nb = sum(1 for v in items.values() if v["kind"] == "broad")
    print("可用标的：宽基 %d / 行业 %d" % (nb, len(items) - nb))

    curve, trades, hold, inv, real, flows = run(items, cal, params, args.unit, args.top,
                                        freq=args.freq, roe_filter=args.roe_filter, roe_th=args.roe_th)
    final = curve[-1]
    total = inv + real + final[3]
    print("\n" + "=" * 68)
    print("回测结果（%s ~ %s，1X=%.0f 元，%s定投，不看本金）" % (
        cal[0], cal[-1], args.unit, "每日" if args.freq == "daily" else "每月"))
    if args.roe_filter:
        print("行业过滤：隐含ROE 同比 > %.1f%% 才买" % (args.roe_th * 100))
    print("=" * 68)
    print("  累计投入        %12s 元" % format(inv, ",.0f"))
    print("  + 已实现盈亏    %12s 元" % format(real, "+,.0f"))
    print("  + 未实现盈亏    %12s 元" % format(final[3], "+,.0f"))
    print("  = 总资产        %12s 元" % format(total, ",.0f"))
    # 资金加权年化：把每天买入当现金流，期末市值当收回，算 XIRR
    print("  年化(XIRR)      %11.2f%%   ← 资金加权：我这笔钱实际年化" % (
        xirr(flows, cal[-1], total) * 100 if flows else 0))
    _years = len(cal) / 244.0
    _p = twr(curve)
    print("  年化(TWR)       %11.2f%%   ← 时间加权：策略自身表现（不受投钱节奏影响）" % (
        (_p ** (1 / _years) - 1) * 100 if _p > 0 else 0))
    if inv > 0:
        print("  总收益率        %11.2f%%" % ((real + final[3]) / inv * 100))
    _cash = getattr(run, "last_cash", 0.0)
    _rec = getattr(run, "recycled", 0.0)
    _cc = getattr(run, "cash_curve", []) or []
    if RECYCLE:
        print("  卖出款再投      %12s 元   ← 这部分买入没花你的新钱" % format(_rec, ",.0f"))
        print("  期末闲置现金    %12s 元" % format(_cash, ",.0f"))
        if _cc:
            _avg = sum(_cc) / len(_cc)
            print("  平均闲置现金    %12s 元   占期末总资产 %.1f%%"
                  % (format(_avg, ",.0f"), _avg / max(1e-9, total) * 100))
    print("\n  交易：买入 %d 笔 / 卖出 %d 笔；期末持仓 %d 只" % (
        sum(1 for t in trades if t[3] == "B"), sum(1 for t in trades if t[3] == "S"), len(hold)))

    # 分年
    by = {}
    for d, iv, rl, un, mv in curve:
        by.setdefault(d[:4], []).append((iv, rl, un, mv))
    print("\n分年（年末总资产 / 累计投入 / 累计收益率）：")
    for y in sorted(by):
        v = by[y][-1]
        r = (v[1] + v[2]) / v[0] * 100 if v[0] > 0 else 0
        print("  %s  总资产 %10s  投入 %10s  收益 %+8.2f%%" % (
            y, format(v[0] + v[1] + v[2], ",.0f"), format(v[0], ",.0f"), r))

    # 回撤两种口径：
    # ① 账面收益率回撤：定投早期本金小，收益率的百分数抖动极大，长周期会失真到 -50% 以上
    rets = [((x[2] + x[3]) / x[1]) if x[1] > 0 else 0 for x in curve]
    peak, mdd = -9e9, 0
    for r in rets:
        peak = max(peak, r)
        mdd = min(mdd, r - peak)
    # ② 净值回撤（标准口径）：把每日 TWR 连乘成净值曲线再算回撤，不受投入节奏影响
    nav_i, peak_i, mdd_i, prev = 1.0, 1.0, 0.0, None
    for day, inv, real, unreal, mv in curve:
        V = inv + real + unreal
        if prev is not None:
            v0, i0 = prev
            flow = inv - i0
            if v0 > 1e-9 and flow >= 0:
                r = (V - v0 - flow) / v0
                if -1 < r < 5:
                    nav_i *= (1 + r)
        prev = (V, inv)
        peak_i = max(peak_i, nav_i)
        mdd_i = min(mdd_i, nav_i / peak_i - 1)
    print("\n  净值最大回撤 %.2f%%   （账面收益率回撤 %.2f%%，定投早期本金小、失真大）"
          % (mdd_i * 100, mdd * 100))
    if os.environ.get("BT_DUMP"):
        with open(os.environ["BT_DUMP"], "w", encoding="utf-8") as _f:
            json.dump({"flows": flows, "curve": curve, "total": total, "inv": inv,
                       "trades": trades},
                      _f, ensure_ascii=False)
        print("  [dump] %s" % os.environ["BT_DUMP"])

    print("\n期末持仓（按市值）：")
    tot_mv = sum(h["value"] for h in hold.values()) or 1
    for c, h in sorted(hold.items(), key=lambda x: -x[1]["value"])[:12]:
        print("  %-16s %10s 元  %5.1f%%  成本 %9s  盈亏 %+8s" % (
            items[c]["name"][:14], format(h["value"], ",.0f"), h["value"] / tot_mv * 100,
            format(h["cost"], ",.0f"), format(h["value"] - h["cost"], "+,.0f")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
