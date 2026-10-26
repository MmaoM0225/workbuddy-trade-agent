#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""校验 data/warehouse/research/ 排雷数据是否与当前 pool 匹配。

research/ 下三个 CSV 是按候选池生成的上一次快照。若 pool 变了却没重跑
research_check_mcp.py，研究员会把"查不到数据"当成"没有风险"，导致排雷静默失效。

用法：python scripts/check_research_fresh.py
退出码：0 = 匹配；2 = 过期/缺失（研究员应重跑取证或退出）
"""
import csv
import json
import os
import sys

ROOT = r"E:\cashfree\agent"
RES_DIR = os.path.join(ROOT, "data", "warehouse", "research")
MIN_COVERAGE = 0.90


def main():
    pp = os.path.join(ROOT, "state", "pool.json")
    if not os.path.exists(pp):
        print("FAIL pool.json missing")
        return 2
    pool = json.load(open(pp, encoding="utf-8"))
    codes = {s.get("code") or s.get("ts_code") for s in pool.get("stocks", [])}
    codes = {c for c in codes if c}
    if not codes:
        print("FAIL pool has no stocks")
        return 2
    print("pool: date=%s stocks=%d" % (pool.get("date"), len(codes)))

    ok = True
    for f in ("goodwill.csv", "reduction.csv", "audit.csv"):
        p = os.path.join(RES_DIR, f)
        if not os.path.exists(p):
            print("FAIL %-14s missing" % f)
            ok = False
            continue
        with open(p, encoding="utf-8-sig") as fh:
            have = {r.get("ts_code") for r in csv.DictReader(fh)}
        cov = len(codes & have) / len(codes)
        flag = "OK" if cov >= MIN_COVERAGE else "FAIL"
        print("%-4s %-14s rows=%d coverage=%.0f%%" % (flag, f, len(have), cov * 100))
        if cov < MIN_COVERAGE:
            ok = False

    if not ok:
        print("\nRESULT: STALE — research/ does not match current pool.")
        print("ACTION: run  POOL_IN=state/pool.json python scripts/research_check_mcp.py")
        return 2
    print("\nRESULT: FRESH — screening data matches pool.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
