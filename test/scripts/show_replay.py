#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json

d = json.load(open("E:/cashfree/agent/test/replay_week_1019_23.json", encoding="utf-8"))

print("=== orders (10) ===")
print("%-9s %-8s %-8s %6s %-18s %7s %7s %8s" % ("code", "name", "industry", "wt%", "zone1", "close19", "SL", "TP"))
for o in d["orders"]:
    print("%-9s %-8s %-8s %6.2f [%7.2f,%7.2f] %7.2f %7.2f %8.2f"
          % (o["code"], o["name"], o.get("industry", "")[:8], o["weight"],
             o["zone1"][0], o["zone1"][1], o["close_1019"], o["stop_loss"], o["take_profit"]))

print("\n=== daily snapshots ===")
for s in d["snapshots"]:
    print("%s %-7s fills=%d sells=%d pos=%2d (%.1f%%) cash=%9.0f total=%9.0f pnl=%+.3f%%"
          % (s["date"], s["regime"], len(s["fills"]), len(s["sells"]),
             s["positions"], s["position_pct"], s["cash"], s["total_assets"], s["pnl_pct"]))
    for f in s["fills"]:
        print("    BUY  %-9s %-8s tr%d @%.2f x%6d = %8.0f" % (f["code"], f["name"], f["tranche"], f["price"], f["shares"], f["amount"]))
    for x in s["sells"]:
        print("    SELL %-9s %-8s @%.2f x%6d  %s" % (x["code"], x["name"], x["price"], x["shares"], x["reason"]))

print("\n=== closed trades ===")
closed = [t for t in d["trades"] if t["side"] == "sell"]
for t in closed:
    print("  %s %-9s %-8s @%.2f  pnl=%+.2f%%" % (t["date"], t["code"], t["name"], t["price"], t.get("pnl_pct", 0)))
print("win rate: %s%% | avg pnl: %s%%" % (d["summary"]["win_rate_pct"], d["summary"]["avg_closed_pnl_pct"]))

print("\n=== final holdings (10-23) ===")
last = d["snapshots"][-1]
print("position value %.0f (%.1f%%), cash %.0f, total %.0f, return %+.3f%%"
      % (last["position_value"], last["position_pct"], last["cash"], last["total_assets"], last["pnl_pct"]))
