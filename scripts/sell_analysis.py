#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sell_analysis.py - 卖出规则执行情况与有效性检验"""
import importlib.util, json, os
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("bt", os.path.join(ROOT, "scripts", "backtest_dca_v3.py"))
bt = importlib.util.module_from_spec(spec); spec.loader.exec_module(bt)

TOP, ROE_TH, START = 5, 0.15, "20201102"
params = json.load(open(os.path.join(ROOT, "knowledge", "index_params.json"), encoding="utf-8"))
d0 = os.path.join(ROOT, "data", "warehouse", "daily")
cal = sorted(x[:-4] for x in os.listdir(d0) if x.endswith(".csv"))
cal = [d for d in cal if START <= d <= "20261027"]
idx_of = {d: i for i, d in enumerate(cal)}
items = bt.build(cal, params, TOP)
curve, trades, hold, inv, real, _flows = bt.run(items, cal, params, 20, TOP,
                                        freq="daily", roe_filter=True, roe_th=ROE_TH)

ex = params["execute"]
print("=" * 92)
print("卖出规则（参数 %s）" % params["version"])
print("=" * 92)
_u = ex.get("sell_unit_cny") or ex.get("unit_amount_cny", 10)
for s in sorted(ex["sell_ladder"], key=lambda x: x["min_score"]):
    print("  分位 >= %-3d  →  %s（每次卖出 %.0f 元 = 1X %.0f 元 × %.0f 倍）" % (
        s["min_score"], s["label"], _u * s["mult"], _u, s["mult"]))
print("  相邻两次减仓至少间隔 %d 个交易日；买入后 %d 天内不卖" % (
    ex["sell_interval_td"], ex["min_hold_days"]))
print("  卖出标的是【金额】，不是仓位百分比：")
print("    按金额倍数卖：不看仓位大小，每次固定卖 1X×倍数；仓位不足时一次卖光")

sells = [t for t in trades if t[3] == "S"]
print("\n" + "=" * 92)
print("实际执行：%d 笔卖出" % len(sells))
print("=" * 92)

# 按档位分组
bins = {"75-85": [], "85-95": [], "95+": []}
for d, c, name, side, amt, pnl in sells:
    i = idx_of[d]
    q = items[c]["score"][i]
    if np.isnan(q):
        continue
    k = "75-85" if q < 85 else ("85-95" if q < 95 else "95+")
    bins[k].append((d, c, name, amt, pnl, q))

print("%-8s %6s %12s %12s %10s %10s" % ("档位", "笔数", "卖出金额", "实现盈亏", "平均收益率", "占总卖出"))
print("-" * 92)
tot_amt = sum(t[4] for t in sells) or 1
for k in ("75-85", "85-95", "95+"):
    v = bins[k]
    if not v:
        print("%-8s %6d %12s" % (k, 0, "-"))
        continue
    amt = sum(x[3] for x in v)
    pnl = sum(x[4] for x in v)
    cost = amt - pnl
    print("%-8s %6d %12s %+12s %9.1f%% %9.1f%%" % (
        k, len(v), format(amt, ",.0f"), format(pnl, "+,.0f"),
        pnl / cost * 100 if cost > 0 else 0, amt / tot_amt * 100))

# 卖出后表现：卖早了还是卖对了
print("\n" + "=" * 92)
print("卖出后表现（判断是否卖早）—— 以该行业基金净值计")
print("=" * 92)
print("%-8s %6s %10s %10s %10s %10s" % ("档位", "笔数", "20日后", "60日后", "120日后", "至今"))
print("-" * 92)
for k in ("75-85", "85-95", "95+"):
    v = bins[k]
    if not v:
        continue
    res = {20: [], 60: [], 120: [], 9999: []}
    for d, c, name, amt, pnl, q in v:
        i = idx_of[d]
        nav = items[c]["nav"]
        base = nav[i]
        if np.isnan(base) or base <= 0:
            continue
        for h in (20, 60, 120):
            j = min(i + h, len(nav) - 1)
            if not np.isnan(nav[j]):
                res[h].append(nav[j] / base - 1)
        if not np.isnan(nav[-1]):
            res[9999].append(nav[-1] / base - 1)
    print("%-8s %6d %9.1f%% %9.1f%% %9.1f%% %9.1f%%" % (
        k, len(v), np.mean(res[20]) * 100 if res[20] else 0,
        np.mean(res[60]) * 100 if res[60] else 0,
        np.mean(res[120]) * 100 if res[120] else 0,
        np.mean(res[9999]) * 100 if res[9999] else 0))
print("\n（正数=卖出后还涨，说明卖早了；负数=卖出后跌了，说明卖对了）")

# 个案
print("\n" + "=" * 92)
print("典型个案（各档位盈亏最大的一笔）")
print("=" * 92)
for k in ("75-85", "85-95", "95+"):
    v = bins[k]
    if not v:
        continue
    for d, c, name, amt, pnl, q in sorted(v, key=lambda x: -abs(x[4]))[:2]:
        i = idx_of[d]
        nav = items[c]["nav"]
        after = nav[-1] / nav[i] - 1 if not np.isnan(nav[i]) and not np.isnan(nav[-1]) else float("nan")
        print("  [%s] %s %-12s 分位%3.0f  卖 %7s 元  实现 %+8s  卖出至今该基金 %+.1f%%" % (
            k, d, name[:10], q, format(amt, ",.0f"), format(pnl, "+,.0f"), after * 100))
