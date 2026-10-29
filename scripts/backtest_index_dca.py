#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""backtest_index_dca.py - 指数估值定投回测

口径：
  - 决策频率：每月第一个交易日（当日收盘算分位、当日收盘价成交）
  - 分位：滚动 5 年（1250 交易日）PE/PB 加权，与实盘 signal 同口径，无前视
  - 买入：分位 <40 才买，mult 2.0/1.5/1.0；40-60 完全停投
  - 卖出：75 档卖当前 1/3，85 档再卖 1/2，95 档清仓，间隔 >=20 交易日
  - 同族去重：同 family 只买分位最低的一只
  - 分红：按当时股息率年化摊到每日计入（近似全收益）
  - 费用：单边 0.03%
  - 日历：统一用沪深300 交易日（A股日历），海外标的按前值填充

用法：
  python scripts/backtest_index_dca.py
  python scripts/backtest_index_dca.py --start 20220104 --capital 500000
"""
import argparse
import csv
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAL = os.path.join(ROOT, "data", "warehouse", "index_valuation")
PRC = os.path.join(ROOT, "data", "warehouse", "index_price")
FPRC = os.path.join(ROOT, "data", "warehouse", "fund_price")
FNAV = os.path.join(ROOT, "data", "warehouse", "fund_nav")
POOL = os.path.join(ROOT, "data", "index_universe.json")
PARAMS_LEGACY = os.path.join(ROOT, "data", "index_params.json")


def load_index_params():
    """v3.0：指数线参数已并入 knowledge/params_{current}.json 的 index_dca 段（唯一真源）。
    读不到该段时回退旧 data/index_params.json，保证历史脚本仍可跑。"""
    try:
        # 指数线唯一真源：knowledge/index_params.json（个股线 params_v*.json 不含本线段）
        with open(os.path.join(ROOT, "knowledge", "index_params.json"), encoding="utf-8") as _f:
            return json.load(_f)
    except Exception:
        pass
    raise SystemExit("缺少 knowledge/index_params.json（指数线唯一真源）")

CYCLICAL = {"000928.SH", "000929.SH", "000986.SH", "000987.SH", "000934.SH", "399975.SZ", "000932.SH"}
GROWTH = {"399006.SZ", "000688.SH", "000935.SH", "000993.SH", "399967.SZ", "HSTECH.HK", "IXIC.US", "000933.SH"}


def fnum(v):
    try:
        return float(v) if v not in ("", None, "--") else None
    except (TypeError, ValueError):
        return None


def weights(code):
    if code in CYCLICAL:
        return 0.3, 0.7
    if code in GROWTH:
        return 0.7, 0.3
    return 0.5, 0.5


def load_series(code, need_price=True):
    vp = os.path.join(VAL, code + ".csv")
    pp = os.path.join(PRC, code + ".csv")
    if not os.path.exists(vp):
        return None
    if need_price and not os.path.exists(pp):
        return None
    val = {}
    with open(vp, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            pe, pb = fnum(r["pe_ttm_ex_neg"]), fnum(r["pb_lf"])
            if pe is None and pb is None:
                continue
            val[r["trade_date"]] = (pe, pb, fnum(r["dividend_ratio"]))
    prc = {}
    if os.path.exists(pp):
        with open(pp, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                c = fnum(r["close"])
                if c:
                    prc[r["trade_date"]] = c
    return val, prc


def pct_series(series, win, mp):
    arr = np.array([np.nan if v is None else v for v in series], dtype=float)
    out = np.full(len(arr), np.nan)
    for i in range(len(arr)):
        if np.isnan(arr[i]):
            continue
        h = arr[max(0, i - win + 1):i + 1]
        h = h[~np.isnan(h)]
        if len(h) < mp:
            continue
        out[i] = (np.sum(h < arr[i]) + 0.5 * np.sum(h == arr[i])) / len(h) * 100.0
    return out


def align(calendar, dates, values):
    """把 (dates, values) 按前值填充对齐到 calendar。"""
    out = np.full(len(calendar), np.nan)
    j, last = 0, np.nan
    for i, d in enumerate(calendar):
        while j < len(dates) and dates[j] <= d:
            last = values[j]
            j += 1
        out[i] = last
    return out


def build_panel(uni, params, calendar, use_fund=True, of_mode=True):
    panel, skipped = {}, []
    for code, m in uni.items():
        if m["group"] == "benchmark":
            continue
        if use_fund and not m.get("tradable"):
            skipped.append((m["name"], "无基金"))
            continue
        ser = load_series(code, need_price=not use_fund)
        if not ser:
            skipped.append((m["name"], "无估值数据"))
            continue
        val, prc = ser
        # 价格来源：基金二级市场价（默认）或指数点位
        px_map = prc
        if use_fund:
            # 场外用复权净值 adj_nav；场内用 ETF 二级市场价
            if of_mode:
                fp = os.path.join(FNAV, (m.get("of_fund") or "") + ".csv")
                dcol, vcol = "nav_date", "adj_nav"
            else:
                fp = os.path.join(FPRC, (m.get("fund") or "") + ".csv")
                dcol, vcol = "trade_date", "close"
            if not os.path.exists(fp):
                skipped.append((m["name"], "无基金价格"))
                continue
            px_map = {}
            with open(fp, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    c = fnum(r[vcol])
                    if c:
                        px_map[r[dcol]] = c
        if not px_map:
            skipped.append((m["name"], "价格为空"))
            continue
        vd = sorted(val)
        pe_s = [val[d][0] for d in vd]
        pb_s = [val[d][1] for d in vd]
        dv_s = [val[d][2] for d in vd]
        pe_p = pct_series(pe_s, params["window_days"], params["min_periods"])
        pb_p = pct_series(pb_s, params["window_days"], params["min_periods"])
        wp, wb = weights(code)
        score = np.full(len(vd), np.nan)
        for i in range(len(vd)):
            a, b = pe_p[i], pb_p[i]
            if np.isnan(a) and np.isnan(b):
                continue
            if np.isnan(a):
                s = b
            elif np.isnan(b):
                s = a
            else:
                s = wp * a + wb * b
            pe, pb, dv = val[vd[i]]
            if s >= 75 and ((pb is not None and pb < params["pb_floor_no_high"]) or
                            (dv is not None and dv >= params["div_yield_no_high"])):
                s = min(s, 74.9)
            if s < 25 and pe is not None and pe > params["pe_cap_no_low"]:
                s = 25.0
            score[i] = s
        pd_ = sorted(px_map)
        close = align(calendar, pd_, [px_map[d] for d in pd_])
        sc = align(calendar, vd, list(score))
        dv = align(calendar, vd, [(x if x is not None else 0.0) for x in dv_s])
        if np.isnan(close).all() or np.isnan(sc).all():
            skipped.append((m["name"], "对齐后为空"))
            continue
        panel[code] = {"meta": m, "close": close, "score": sc, "div": dv}
    return panel, skipped


def redeem_fee(held_td, base_fee):
    """场外赎回费阶梯（按持有交易日近似自然日 ×1.4）。"""
    if base_fee > 0.001:                       # 调用方传的是 ETF 佣金，直接返回
        return base_fee
    days = held_td * 1.4
    if days < 7:
        return 0.015
    if days < 30:
        return 0.0075
    if days < 365:
        return 0.005
    if days < 730:
        return 0.0025
    return 0.0


def run_strategy(panel, params, calendar, capital, fee, sell_on=True, dedup_on=True, buy_th=40):
    ex = params["execute"]
    # 2026-10-28 参数迁移后 guards 段被删（指数线改为不看本金），这里给等价默认值：
    # 不限单标的上限 = 与原口径"不看本金"一致
    guards = params.get("guards") or {"single_index_max_pct": 100,
                                      "group_max_pct": {"broad": 100, "industry": 100}}
    cash, hold, nav, trades = float(capital), {}, [], []
    seen_month = set()

    for i, d in enumerate(calendar):
        # 1. 每日盯市（含股息摊销）
        for code in list(hold):
            p = panel[code]
            if i > 0 and not np.isnan(p["close"][i]) and not np.isnan(p["close"][i - 1]) and p["close"][i - 1] > 0:
                r = p["close"][i] / p["close"][i - 1] - 1.0 + p["div"][i] / 100.0 / 244.0
                hold[code]["value"] *= (1.0 + r)

        ym = d[:6]
        if ym not in seen_month:
            seen_month.add(ym)
            scores = {c: p["score"][i] for c, p in panel.items() if not np.isnan(p["score"][i])}
            total = cash + sum(h["value"] for h in hold.values())

            # 2. 卖
            for code in list(hold):
                if not sell_on:
                    break
                if code not in scores:
                    continue
                sc = scores[code]
                stage = None
                for s in sorted(ex["sell_stages"], key=lambda x: x["min_score"]):
                    if sc >= s["min_score"]:
                        stage = s
                if not stage:
                    continue
                h = hold[code]
                if stage["min_score"] <= h["stage_done"]:
                    continue
                if h["first_buy_i"] is not None and i - h["first_buy_i"] < 20:
                    continue
                if h["last_action_i"] is not None and i - h["last_action_i"] < ex["sell_interval_td"]:
                    continue
                amt = h["value"] * stage["sell_current_ratio"]
                if amt <= 0:
                    continue
                held = i - (h["first_buy_i"] if h["first_buy_i"] is not None else 0)
                cash += amt * (1 - redeem_fee(held, fee))
                h["value"] -= amt
                h["stage_done"] = stage["min_score"]
                h["last_action_i"] = i
                trades.append({"date": d, "code": code, "side": "S", "amt": amt,
                               "score": sc, "note": stage["label"]})
                if h["value"] < 1:
                    hold.pop(code, None)

            # 3. 买（同族去重）
            fam_best = {}
            for code, sc in scores.items():
                fam = panel[code]["meta"]["family"] if dedup_on else code
                if fam not in fam_best or sc < fam_best[fam][1]:
                    fam_best[fam] = (code, sc)
            cands = []
            for fam, (code, sc) in fam_best.items():
                if sc >= buy_th:
                    continue
                mult = 2.0 if sc < 10 else (1.5 if sc < 25 else 1.0)
                cands.append([code, sc, ex["base_amount_per_index_cny"] * mult])
            gross = sum(c[2] for c in cands)
            scale = 1.0
            if gross > ex["max_per_period_cny"]:
                scale = ex["max_per_period_cny"] / gross
            if gross * scale > cash:
                scale = min(scale, cash / gross if gross else 1.0)

            gused = {"cn_broad": 0, "cn_industry": 0, "overseas": 0}
            for code, h in hold.items():
                gused[panel[code]["meta"]["group"]] = gused.get(panel[code]["meta"]["group"], 0) + h["value"]
            for code, sc, amt in cands:
                if np.isnan(panel[code]["close"][i]):
                    continue                      # 基金当日未上市/无价格，买不到
                amt *= scale
                g = panel[code]["meta"]["group"]
                cur_v = hold.get(code, {}).get("value", 0)
                amt = min(amt, max(0, total * guards["single_index_max_pct"] / 100.0 - cur_v))
                amt = min(amt, max(0, total * guards["group_max_pct"].get(g, 100) / 100.0 - gused.get(g, 0)))
                if amt < 100:
                    continue
                cash -= amt
                amt = amt * (1 - fee)
                gused[g] = gused.get(g, 0) + amt
                if code in hold:
                    hold[code]["value"] += amt
                    hold[code]["last_action_i"] = i
                else:
                    hold[code] = {"value": amt, "stage_done": 0, "last_action_i": i, "first_buy_i": i}
                trades.append({"date": d, "code": code, "side": "B", "amt": amt, "score": sc, "note": ""})

        nav.append((d, cash + sum(h["value"] for h in hold.values())))

    return nav, trades, hold, cash


def run_buyhold(panel, calendar, capital, fee=0.0003):
    """首日等权买入全部可用标的，持有不动。"""
    codes = [c for c, p in panel.items() if not np.isnan(p["close"][0])]
    if not codes:
        return []
    per = capital / len(codes)
    base = {c: panel[c]["close"][0] for c in codes}
    nav = []
    for i, d in enumerate(calendar):
        v = 0.0
        for c in codes:
            if np.isnan(panel[c]["close"][i]):
                v += per
            else:
                v += per * panel[c]["close"][i] / base[c]
        nav.append((d, v * (1 - fee)))
    return nav


def stats(nav, label):
    if not nav:
        return None
    vals = np.array([v for _, v in nav], dtype=float)
    ret = vals[-1] / vals[0] - 1
    years = len(vals) / 244.0
    cagr = (vals[-1] / vals[0]) ** (1 / years) - 1 if years > 0 and vals[0] > 0 else 0
    dd = (vals / np.maximum.accumulate(vals) - 1).min()
    daily = np.diff(vals) / vals[:-1]
    sharpe = daily.mean() / daily.std() * np.sqrt(244) if daily.std() > 0 else 0
    return {"label": label, "ret": ret, "cagr": cagr, "mdd": dd, "sharpe": sharpe,
            "final": vals[-1], "vals": vals}


def run_dca_bench(panel, calendar, capital, fee=0.0003):
    """同节奏对照：每月第一个交易日定投沪深300，投完为止，不卖。"""
    if "000300.SH" not in panel:
        return []
    p = panel["000300.SH"]
    months = []
    seen = set()
    for i, d in enumerate(calendar):
        if d[:6] not in seen:
            seen.add(d[:6])
            months.append(i)
    per = capital / len(months) if months else 0
    units, cash, nav = 0.0, float(capital), []
    for i, d in enumerate(calendar):
        if i in months and cash >= per and not np.isnan(p["close"][i]):
            spend = min(per, cash)
            units += spend * (1 - fee) / p["close"][i]
            cash -= spend
        v = cash + (units * p["close"][i] if not np.isnan(p["close"][i]) else 0)
        nav.append((d, v))
    return nav


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="20220104")
    ap.add_argument("--end", default="20261027")
    ap.add_argument("--capital", type=float, default=500000)
    ap.add_argument("--fee", type=float, default=0.0012)
    ap.add_argument("--buy-th", type=float, default=40)
    ap.add_argument("--index-price", action="store_true", help="用指数点位而非基金价格回测")
    ap.add_argument("--etf", action="store_true", help="用场内ETF价格而非场外基金净值")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    params = load_index_params()
    with open(POOL, encoding="utf-8") as f:
        uni = {x["code"]: x for x in json.load(f)["indices"]}

    # 统一日历：沪深300 交易日
    _, prc = load_series("000300.SH")
    calendar = [d for d in sorted(prc) if args.start <= d <= args.end]

    panel, skipped = build_panel(uni, params, calendar, use_fund=not args.index_price,
                                 of_mode=not args.etf)
    print("日历 %s ~ %s  共 %d 个交易日" % (calendar[0], calendar[-1], len(calendar)))
    print("回测价格口径：%s" % ("指数点位" if args.index_price else ("场内ETF二级市场价" if args.etf else "场外基金复权净值（含管理费与全部申赎成本）")))
    print("可用标的 %d / %d" % (len(panel), len([x for x in uni.values() if x["group"] != "benchmark"])))
    if skipped:
        from collections import Counter
        c = Counter(r for _, r in skipped)
        print("剔除：%s" % "；".join("%s %d 个" % (k, v) for k, v in c.items()))

    nav, trades, hold, cash = run_strategy(panel, params, calendar, args.capital, args.fee, buy_th=args.buy_th)
    res = [stats(nav, "① 估值定投（现行参数）")]

    nav_ns, tr_ns, h_ns, c_ns = run_strategy(panel, params, calendar, args.capital, args.fee, sell_on=False)
    res.append(stats(nav_ns, "② 只买不卖（对照）"))

    nav_nd, _, _, _ = run_strategy(panel, params, calendar, args.capital, args.fee, dedup_on=False)
    res.append(stats(nav_nd, "③ 不做同族去重（对照）"))

    res.append(stats(run_buyhold(panel, calendar, args.capital), "④ 等权买入持有全池"))
    res.append(stats(run_dca_bench(panel, calendar, args.capital), "⑤ 定投沪深300（同节奏）"))

    if "000300.SH" in panel:
        p = panel["000300.SH"]
        base = p["close"][0]
        res.append(stats([(d, args.capital * c / base) for d, c in zip(calendar, p["close"])],
                         "⑥ 沪深300 一次性买入"))

    print("\n初始资金 %s 元   单边费率 %.2f%%\n" % (format(int(args.capital), ","), args.fee * 100))
    print("%-20s %10s %9s %9s %8s %12s" % ("策略", "累计收益", "年化", "最大回撤", "夏普", "期末资产"))
    print("-" * 74)
    for r in res:
        if r:
            print("%-20s %9.2f%% %8.2f%% %8.2f%% %8.2f %12s" % (
                r["label"], r["ret"] * 100, r["cagr"] * 100, r["mdd"] * 100,
                r["sharpe"], format(int(r["final"]), ",")))

    buys = [t for t in trades if t["side"] == "B"]
    sells = [t for t in trades if t["side"] == "S"]
    print("\n交易：买入 %d 次 / 卖出 %d 次；期末现金 %s 元，持仓 %d 只" % (
        len(buys), len(sells), format(int(cash), ","), len(hold)))

    by_year = {}
    for d, v in nav:
        by_year.setdefault(d[:4], []).append(v)
    print("\n分年（策略）：")
    for y in sorted(by_year):
        v = by_year[y]
        print("  %s  期末 %12s   年内 %+7.2f%%" % (y, format(int(v[-1]), ","), (v[-1] / v[0] - 1) * 100))

    print("\n期末持仓：")
    total = cash + sum(h["value"] for h in hold.values())
    for code, h in sorted(hold.items(), key=lambda x: -x[1]["value"]):
        print("  %-12s %-14s %10s 元  %5.2f%%   已减仓档 %s" % (
            code, uni[code]["name"], format(int(h["value"]), ","),
            h["value"] / total * 100, h["stage_done"] or "-"))

    print("\n卖出明细（前 20 笔）：")
    for t in sells[:20]:
        print("  %s  %-12s %10s 元  分位%.0f  %s" % (
            t["date"], uni[t["code"]]["name"], format(int(t["amt"]), ","), t["score"], t["note"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
