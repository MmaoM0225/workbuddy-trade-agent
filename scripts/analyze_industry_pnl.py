#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""analyze_industry_pnl.py - 拆解回测里每个行业的投入与盈亏"""
import csv, importlib.util, json, os, sys
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("bt", os.path.join(ROOT, "scripts", "backtest_dca_v3.py"))
bt = importlib.util.module_from_spec(spec); spec.loader.exec_module(bt)

def main():
    top = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    start = sys.argv[2] if len(sys.argv) > 2 else "20201102"
    params = json.load(open(os.path.join(ROOT, "data", "index_params.json"), encoding="utf-8"))
    d0 = os.path.join(ROOT, "data", "warehouse", "daily")
    cal = sorted(x[:-4] for x in os.listdir(d0) if x.endswith(".csv"))
    cal = [d for d in cal if start <= d <= "20261027"]
    items = bt.build(cal, params, top)
    import sys as _s
    roe = "--roe" in _s.argv
    curve, trades, hold, inv, real = bt.run(items, cal, params, 20, top, freq="daily", roe_filter=roe, roe_th=0.15)
    final = curve[-1]

    # 按标的汇总：买入总额、卖出总额、已实现、持仓市值/成本
    stat = {}
    for d, c, name, side, amt, pnl in trades:
        s = stat.setdefault(c, {"name": name, "kind": items[c]["kind"], "buy": 0.0, "sell": 0.0,
                                "realized": 0.0, "nbuy": 0, "nsell": 0})
        if side == "B":
            s["buy"] += amt; s["nbuy"] += 1
        else:
            s["sell"] += amt; s["realized"] += pnl; s["nsell"] += 1
    for c, h in hold.items():
        s = stat.setdefault(c, {"name": items[c]["name"], "kind": items[c]["kind"], "buy": 0.0,
                                "sell": 0.0, "realized": 0.0, "nbuy": 0, "nsell": 0})
        s["mv"] = h["value"]; s["cost_left"] = h["cost"]
        s["unreal"] = h["value"] - h["cost"]

    print("=" * 92)
    print("行业层明细（top=%d，%s ~ 20261027）  只列行业，按总盈亏排序" % (top, cal[0]))
    print("=" * 92)
    print("%-14s %5s %5s %10s %10s %10s %9s %9s" % (
        "行业", "买次", "卖次", "累计买入", "已实现", "未实现", "总盈亏", "盈亏率"))
    print("-" * 92)
    rows = []
    for c, s in stat.items():
        if s["kind"] != "industry":
            continue
        unreal = s.get("unreal", 0.0)
        tot = s["realized"] + unreal
        base = s["buy"] if s["buy"] > 0 else 1
        rows.append((tot, c, s, unreal, tot / base * 100))
    rows.sort(key=lambda x: x[0])
    for tot, c, s, unreal, pct in rows:
        print("%-14s %5d %5d %10s %10s %10s %9s %8.1f%%" % (
            s["name"][:12], s["nbuy"], s["nsell"],
            format(s["buy"], ",.0f"), format(s["realized"], "+,.0f"),
            format(unreal, "+,.0f"), format(tot, "+,.0f"), pct))

    tot_buy = sum(s["buy"] for s in stat.values() if s["kind"] == "industry")
    tot_rl = sum(s["realized"] for s in stat.values() if s["kind"] == "industry")
    tot_un = sum(s.get("unreal", 0) for s in stat.values() if s["kind"] == "industry")
    n_ind = len(rows)
    lose = [r for r in rows if r[0] < 0]
    print("-" * 92)
    print("行业合计：%d 个标的，买入 %s 元，已实现 %s，未实现 %s，合计 %s（%.1f%%）" % (
        n_ind, format(tot_buy, ",.0f"), format(tot_rl, "+,.0f"), format(tot_un, "+,.0f"),
        format(tot_rl + tot_un, "+,.0f"), (tot_rl + tot_un) / (tot_buy or 1) * 100))
    print("其中亏损 %d 个，合计亏损 %s 元" % (
        len(lose), format(sum(r[0] for r in lose), ",.0f")))

    # 宽基对照
    print()
    wb = [s for s in stat.values() if s["kind"] == "broad"]
    wb_buy = sum(s["buy"] for s in wb)
    wb_rl = sum(s["realized"] for s in wb)
    wb_un = sum(s.get("unreal", 0) for s in wb)
    print("宽基合计：%d 个标的，买入 %s 元，已实现 %s，未实现 %s，合计 %s（%.1f%%）" % (
        len(wb), format(wb_buy, ",.0f"), format(wb_rl, "+,.0f"), format(wb_un, "+,.0f"),
        format(wb_rl + wb_un, "+,.0f"), (wb_rl + wb_un) / (wb_buy or 1) * 100))

    # 已卖出明细
    sells = [t for t in trades if t[3] == "S"]
    print("\n已卖出的 %d 笔（按实现盈亏排序）：" % len(sells))
    for d, c, name, side, amt, pnl in sorted(sells, key=lambda x: x[5])[:12]:
        print("  %s  %-12s %8s 元  实现 %+8s" % (d, name[:10], format(amt, ",.0f"), format(pnl, "+,.0f")))
    return 0

if __name__ == "__main__":
    sys.exit(main())
