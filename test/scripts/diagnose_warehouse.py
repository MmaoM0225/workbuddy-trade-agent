#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Diagnose the full-market warehouse: what universe does scores_full.csv cover?"""
import csv
from collections import Counter

BASE = "E:/cashfree/agent/data/warehouse/"


def load(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


scores = load(BASE + "scores_full.csv")
basic = load(BASE + "meta/stock_basic.csv")
db = load(BASE + "daily_basic/20261023.csv") if __import__("os").path.exists(
    BASE + "daily_basic/20261023.csv") else []

codes_scored = {r["ts_code"] for r in scores}
name_of = {r["ts_code"]: r.get("name", "") for r in basic}

print("scores_full:", len(scores), "stocks")
print("stock_basic:", len(basic), "stocks")
print("daily_basic:", len(db), "stocks")

# composition check on scored set
gem = sum(1 for c in codes_scored if c[:3] in ("300", "301"))
star = sum(1 for c in codes_scored if c[:3] in ("688", "689"))
bj = sum(1 for c in codes_scored if c.endswith(".BJ"))
st = sum(1 for c in codes_scored if "ST" in name_of.get(c, "").upper())
print("\n--- scored-set composition ---")
print("创业板 300/301:", gem, "| 科创板 688/689:", star, "| 北交所 .BJ:", bj, "| ST:", st)

# how many market-wide stocks got excluded
if db:
    db_codes = {r["ts_code"] for r in db}
    only_in_db = db_codes - codes_scored
    gem_db = sum(1 for c in only_in_db if c[:3] in ("300", "301"))
    star_db = sum(1 for c in only_in_db if c[:3] in ("688", "689"))
    bj_db = sum(1 for c in only_in_db if c.endswith(".BJ"))
    st_db = sum(1 for c in only_in_db if "ST" in name_of.get(c, "").upper())
    print("\n--- excluded from market-wide (%d stocks) ---" % len(only_in_db))
    print("创业板:", gem_db, "科创板:", star_db, "北交所:", bj_db, "ST:", st_db)
    print("其他（次新/停牌/流动性/因子缺失）:", len(only_in_db) - gem_db - star_db - bj_db - st_db)

print("\n--- industry distribution (top15) ---")
for k, v in Counter(r.get("industry", "") for r in scores).most_common(15):
    print("  %-10s %d" % (k, v))

print("\n--- score stats ---")
sc = sorted(float(r["score"]) for r in scores)
print("min %.4f | p25 %.4f | median %.4f | p75 %.4f | max %.4f"
      % (sc[0], sc[len(sc)//4], sc[len(sc)//2], sc[len(sc)*3//4], sc[-1]))

print("\n--- top10 ---")
for r in scores[:10]:
    print("  %-3s %-9s %-6s %.4f %s" % (r["rank"], r["ts_code"], r["name"], float(r["score"]), r.get("industry", "")))
