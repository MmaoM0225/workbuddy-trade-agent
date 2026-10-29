#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""industry_trades_report.py - 6 年行业层买卖统计（v4.0 配置：每日定投 + ROE>15% + top5）"""
import csv, importlib.util, json, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("bt", os.path.join(ROOT, "scripts", "backtest_dca_v3.py"))
bt = importlib.util.module_from_spec(spec); spec.loader.exec_module(bt)

TOP = 5
ROE_TH = 0.15
START = "20201102"

params = json.load(open(os.path.join(ROOT, "data", "index_params.json"), encoding="utf-8"))
d0 = os.path.join(ROOT, "data", "warehouse", "daily")
cal = sorted(x[:-4] for x in os.listdir(d0) if x.endswith(".csv"))
cal = [d for d in cal if START <= d <= "20261027"]
idx_of = {d: i for i, d in enumerate(cal)}

items = bt.build(cal, params, TOP)
curve, trades, hold, inv, real = bt.run(items, cal, params, 20, TOP,
                                        freq="daily", roe_filter=True, roe_th=ROE_TH)

def sc(c, d):
    v = items[c]["score"][idx_of[d]]
    return None if np.isnan(v) else v

# ---------- 1. 每个行业的买卖汇总 ----------
stat = {}
for d, c, name, side, amt, pnl in trades:
    s = stat.setdefault(c, {"name": name, "kind": items[c]["kind"], "first_b": None, "last_b": None,
                            "nbuy": 0, "buy": 0.0, "nsell": 0, "sell": 0.0, "real": 0.0})
    if items[c]["kind"] != "industry":
        continue
    if side == "B":
        s["nbuy"] += 1; s["buy"] += amt
        s["first_b"] = s["first_b"] or d; s["last_b"] = d
    else:
        s["nsell"] += 1; s["sell"] += amt; s["real"] += pnl
for c, h in hold.items():
    if items[c]["kind"] == "industry":
        s = stat.setdefault(c, {"name": items[c]["name"], "kind": "industry", "first_b": None,
                                "last_b": None, "nbuy": 0, "buy": 0.0, "nsell": 0, "sell": 0.0, "real": 0.0})
        s["mv"] = h["value"]; s["cost"] = h["cost"]

rows = [(c, s) for c, s in stat.items() if s["kind"] == "industry" and s["nbuy"] > 0]
rows.sort(key=lambda x: -(x[1].get("real", 0) + (x[1].get("mv", 0) - x[1].get("cost", 0))))

print("=" * 108)
print("行业层买卖统计（每日定投 + 隐含ROE同比>%.0f%% + 每期top%d）  %s ~ %s" % (ROE_TH * 100, TOP, cal[0], cal[-1]))
print("=" * 108)
print("%-14s %-10s %-10s %5s %10s %5s %10s %10s %10s %8s" % (
    "行业", "首次买入", "末次买入", "买次", "累计买入", "卖次", "累计卖出", "已实现", "持仓盈亏", "总盈亏"))
print("-" * 108)
for c, s in rows:
    un = s.get("mv", 0) - s.get("cost", 0)
    print("%-14s %-10s %-10s %5d %10s %5d %10s %10s %10s %+9s" % (
        s["name"][:12], s["first_b"] or "-", s["last_b"] or "-", s["nbuy"],
        format(s["buy"], ",.0f"), s["nsell"], format(s["sell"], ",.0f"),
        format(s["real"], "+,.0f"), format(un, "+,.0f"), format(s["real"] + un, "+,.0f")))

ib = sum(s["buy"] for _, s in rows)
ir = sum(s["real"] for _, s in rows)
iu = sum(s.get("mv", 0) - s.get("cost", 0) for _, s in rows)
print("-" * 108)
print("行业合计：%d 个标的  买入 %s  卖出 %s  已实现 %s  持仓盈亏 %s  总盈亏 %s" % (
    len(rows), format(ib, ",.0f"), format(sum(s["sell"] for _, s in rows), ",.0f"),
    format(ir, "+,.0f"), format(iu, "+,.0f"), format(ir + iu, "+,.0f")))

# ---------- 2. 卖出明细 ----------
sells = [t for t in trades if t[3] == "S" and items[t[1]]["kind"] == "industry"]
print("\n" + "=" * 108)
print("行业卖出明细（共 %d 笔）" % len(sells))
print("=" * 108)
print("%-10s %-14s %10s %10s %9s %8s" % ("日期", "行业", "卖出金额", "实现盈亏", "当时分位", "收益率"))
print("-" * 108)
for d, c, name, side, amt, pnl in sells:
    q = sc(c, d)
    print("%-10s %-14s %10s %+10s %9s %7.1f%%" % (
        d, name[:12], format(amt, ",.0f"), format(pnl, "+,.0f"),
        "-" if q is None else "%.0f" % q, pnl / (amt - pnl) * 100 if amt > pnl else 0))
sq = [sc(t[1], t[0]) for t in sells if sc(t[1], t[0]) is not None]
if sq:
    print("-" * 108)
    print("卖出时点分位：最低 %.0f / 中位 %.0f / 最高 %.0f" % (
        min(sq), sorted(sq)[len(sq) // 2], max(sq)))
    print("卖出总金额 %s，实现盈亏合计 %s" % (
        format(sum(t[4] for t in sells), ",.0f"), format(sum(t[5] for t in sells), "+,.0f")))

# ---------- 3. 分年统计 ----------
print("\n" + "=" * 108)
print("分年买卖（行业层）")
print("=" * 108)
print("%-6s %6s %12s %6s %12s %10s" % ("年份", "买入笔", "买入金额", "卖出笔", "卖出金额", "实现盈亏"))
print("-" * 108)
by = {}
for d, c, name, side, amt, pnl in trades:
    if items[c]["kind"] != "industry":
        continue
    y = d[:4]
    r = by.setdefault(y, [0, 0.0, 0, 0.0, 0.0])
    if side == "B":
        r[0] += 1; r[1] += amt
    else:
        r[2] += 1; r[3] += amt; r[4] += pnl
for y in sorted(by):
    r = by[y]
    print("%-6s %6d %12s %6d %12s %+10s" % (y, r[0], format(r[1], ",.0f"), r[2],
                                            format(r[3], ",.0f"), format(r[4], "+,.0f")))
