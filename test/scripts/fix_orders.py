#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一次性修复：持仓管家 2026-10-26 重写 orders.json 导致订单 ID 错位。

问题：
  - 成交的 2 张买单被整条删除（本应保留并标 filled）
  - 剩余 8 张被重新编号 ORD-20261023-001..008，与 trades.jsonl 的 order_id 错位
  - 凭空多出 000966 长源电力，丢失 000009 中国宝安

做法：
  以 git 50d9b89 版本为基线（原始 10 张单），按 trades.jsonl 的 buy 成交回填
  fill_* 与 status，未成交的保持 planned 且 ID 不变。

用法：python test/scripts/fix_orders.py [--apply]
  不带 --apply 只打印差异，不写文件。
"""
import argparse
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE = os.path.join(ROOT, ".tmp_orig.json")          # git 50d9b89 导出的原始订单
CUR = os.path.join(ROOT, "state", "orders.json")
TRADES = os.path.join(ROOT, "state", "trades.jsonl")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    orig = json.load(open(BASE, encoding="utf-8"))
    cur = json.load(open(CUR, encoding="utf-8"))

    fills = {}
    for line in open(TRADES, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        t = json.loads(line)
        if t.get("side") != "buy":
            continue
        o = t.get("open") or {}
        f = fills.setdefault(t["order_id"], [])
        f.append({"price": o.get("price"), "shares": o.get("shares"),
                  "amount": o.get("amount"), "date": o.get("date"),
                  "tranche": t.get("tranche")})

    print("原始订单 %d 张，当前 %d 张，成交记录 %d 笔"
          % (len(orig["orders"]), len(cur["orders"]), sum(len(v) for v in fills.values())))
    print("-" * 96)

    rebuilt = []
    for o in orig["orders"]:
        oid = o["id"]
        got = fills.get(oid)
        if got:
            tot_sh = sum(x["shares"] or 0 for x in got)
            tot_amt = sum(x["amount"] or 0 for x in got)
            o["status"] = "filled"
            o["fill_price"] = round(tot_amt / tot_sh, 3) if tot_sh else None
            o["fill_shares"] = tot_sh
            o["fill_amount"] = round(tot_amt, 2)
            o["fill_date"] = got[0]["date"]
            o["filled_tranches"] = [x["tranche"] for x in got]
            flag = "FILLED  %s x%s @%.2f" % (tot_sh, "", o["fill_price"])
        else:
            o["status"] = "planned"
            flag = "planned"
        rebuilt.append(o)
        print("%-20s %-11s %-9s %s" % (oid, o["code"], str(o.get("name"))[:8], flag))

    orig["orders"] = rebuilt
    notes = orig.get("notes")
    if isinstance(notes, dict):
        notes["rebuild_note"] = ("2026-10-26 修复：持仓管家重写订单导致 ID 错位，"
                                 "按 git 50d9b89 基线 + trades.jsonl 成交回填重建")
    orig["orders_rebuilt_at"] = "2026-10-26"

    if not a.apply:
        print("\n[dry-run] 未写文件。加 --apply 生效。")
        return 0

    shutil.copy2(CUR, CUR + ".bak_20261026")
    tmp = CUR + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(orig, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CUR)
    print("\n已写回 %s（备份 orders.json.bak_20261026）" % CUR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
