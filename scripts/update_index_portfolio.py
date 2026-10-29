#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""update_index_portfolio.py - 指数定投账本：成交登记 + 每日盯市 + 盈亏核算

两个动作：
  --commit   把 state/index_orders.json 里的本期买卖落成实际持仓/已实现盈亏
              （人工确认后执行，模拟场外 T 日净值成交）
  默认       按最新净值给所有持仓盯市，输出账面市值与盈亏
              （= 投入 + 已实现 + 未实现，与 index_plan.py 同一公式）

用法：
  python scripts/update_index_portfolio.py --commit
  python scripts/update_index_portfolio.py
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = os.path.join(ROOT, "state", "index_portfolio.json")
ORDERS = os.path.join(ROOT, "state", "index_orders.json")
SIGNAL = os.path.join(ROOT, "state", "index_signal.json")
NAVD = os.path.join(ROOT, "data", "warehouse", "fund_nav")
PARAMS = os.path.join(ROOT, "data", "index_params.json")


def load(p, d=None):
    if not os.path.exists(p):
        return d
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def latest_nav(code):
    fp = os.path.join(NAVD, code + ".csv")
    if not os.path.exists(fp):
        return None, None
    last = None
    with open(fp, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("unit_nav"):
                last = (r["nav_date"], float(r["unit_nav"]))
    return last if last else (None, None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="把 orders 落成持仓")
    ap.add_argument("--port", default=PORT)
    ap.add_argument("--from", dest="src", default=None, help="指定要登记的 orders 文件")
    args = ap.parse_args()

    params = load(PARAMS, {})
    port = load(args.port) or {"version": "v1.0", "created": datetime.now().strftime("%Y%m%d"),
                               "cumulative_invested_cny": 0.0, "realized_pnl_cny": 0.0,
                               "cash_from_sells_cny": 0.0, "holdings": {}, "history": []}
    hold = port.setdefault("holdings", {})
    fee = params.get("execute", {}).get("buy_fee", 0.0012)

    if args.commit:
        orders = load(args.src or ORDERS)
        if not orders:
            print("没有 state/index_orders.json，先跑 index_plan.py")
            return 1
        d = orders["as_of"]
        # 幂等保护：自动化每日调用 --commit，同一份 orders 重复登记会把份额/成本累加翻倍。
        if any(h.get("date") == d for h in port.get("history", [])):
            print("跳过登记：as_of=%s 已在 history 中（幂等保护）" % d)
        else:
            nb = ns = 0
            for b in orders.get("buys", []):
                code = b["code"]
                amt = b["amount_cny"]
                shares_add = amt * (1 - fee) / (latest_nav(b["fund"])[1] or 1) if b.get("fund") else 0
                h = hold.setdefault(code, {"shares": 0.0, "cost": 0.0, "stage_done": 0,
                                           "first_buy_date": d, "last_action_date": d, "nav": 0.0})
                h["shares"] += shares_add
                h["cost"] += amt
                h["last_action_date"] = d
                h["fund"] = b.get("fund", "")
                h["name"] = b["name"]
                h.setdefault("first_buy_date", d)
                port["cumulative_invested_cny"] += amt
                nb += 1
            for s in orders.get("sells", []):
                code = s["code"]
                h = hold.get(code)
                if not h:
                    continue
                ratio = s["ratio"]
                sell_shares = h["shares"] * ratio
                cost_out = h["cost"] * ratio
                nav = latest_nav(h.get("fund", ""))[1] or h.get("nav") or 1
                proceeds = sell_shares * nav
                port["realized_pnl_cny"] += proceeds - cost_out
                h["shares"] -= sell_shares
                h["cost"] -= cost_out
                h["stage_done"] = s["stage"]
                h["last_action_date"] = d
                port["cash_from_sells_cny"] += proceeds
                ns += 1
                if h["shares"] < 1e-6:
                    hold.pop(code, None)
            port["history"].append({"date": d, "buys": nb, "sells": ns,
                                    "invested": orders.get("total_buy_cny", 0)})
            with open(args.port, "w", encoding="utf-8") as f:
                json.dump(port, f, ensure_ascii=False, indent=2)
            print("已登记 %s：买入 %d 笔 / 卖出 %d 笔" % (d, nb, ns))

    # 每日盯市
    mv = cost = 0.0
    print("\n%-14s %-12s %10s %10s %10s %8s" % ("标的", "基金", "份额", "市值", "成本", "盈亏"))
    print("-" * 74)
    for code, h in sorted(hold.items()):
        nd, nav = latest_nav(h.get("fund", ""))
        if nav:
            h["nav"] = nav
            h["nav_date"] = nd
        cur = h["shares"] * (h.get("nav") or 0)
        h["value"] = cur
        mv += cur
        cost += h["cost"]
        print("%-14s %-12s %10.2f %10s %10s %+8s" % (
            (h.get("name") or code)[:12], h.get("fund", "")[:10], h["shares"],
            format(cur, ",.0f"), format(h["cost"], ",.0f"), format(cur - h["cost"], "+,.0f")))
    unreal = mv - cost
    inv = port["cumulative_invested_cny"]
    real = port["realized_pnl_cny"]
    total = inv + real + unreal
    print("-" * 74)
    print("持仓 %d 只   市值 %s   成本 %s   未实现 %s" % (
        len(hold), format(mv, ",.0f"), format(cost, ",.0f"), format(unreal, "+,.0f")))
    print("\n【收益核算】")
    print("  累计投入        %12s 元" % format(inv, ",.0f"))
    print("  + 已实现盈亏    %12s 元" % format(real, "+,.0f"))
    print("  + 未实现盈亏    %12s 元" % format(unreal, "+,.0f"))
    print("  = 总资产        %12s 元" % format(total, ",.0f"))
    if inv > 0:
        print("  总收益率        %11.2f%%" % ((real + unreal) / inv * 100))

    if not args.commit:
        with open(args.port, "w", encoding="utf-8") as f:
            json.dump(port, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
