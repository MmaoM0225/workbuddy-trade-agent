# -*- coding: utf-8 -*-
"""汇总 tushare fina_indicator demo 数据：合并批次 -> CSV -> 抽样展示"""
import glob
import json
import random
from pathlib import Path

import pandas as pd

DATA_DIR = Path(r"E:\cashfree\agent\data\demo_20261025")
CSV_PATH = DATA_DIR / "fina_indicator.csv"

# 1. 读取并合并所有批次
rows = []
for fp in sorted(glob.glob(str(DATA_DIR / "raw_batch*.json"))):
    with open(fp, encoding="utf-8") as f:
        batch = json.load(f)
    rows.extend(batch)
    print(f"[read] {Path(fp).name}: {len(batch)} rows")

total_rows = len(rows)
codes = [r["ts_code"] for r in rows]
unique_codes = sorted(set(codes))
end_dates = sorted({r.get("end_date") for r in rows})
ann_dates = sorted({r.get("ann_date") for r in rows})
fields = list(rows[0].keys())

# 版本重复情况
from collections import Counter
cnt = Counter(codes)
dups = {k: v for k, v in cnt.items() if v > 1}

print("=" * 60)
print(f"实际报告期 (end_date): {end_dates}")
print(f"总行数: {total_rows}")
print(f"唯一股票数: {len(unique_codes)} -> {unique_codes}")
print(f"公告日期 (ann_date) 分布: {Counter(r.get('ann_date') for r in rows)}")
print(f"同一股票多版本记录: {dups if dups else '无'}")
print(f"字段数: {len(fields)}")
print("字段名列表:")
print(fields)

# 2. 保存 CSV
df = pd.DataFrame(rows, columns=fields)
df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
print("=" * 60)
print(f"CSV 已保存: {CSV_PATH}")
print(f"CSV 行数(不含表头): {len(df)}, 列数: {len(df.columns)}")

# 3. 随机抽 3 行展示指定字段
sample_cols = ["ts_code", "roe", "grossprofit_margin", "netprofit_margin", "tr_yoy"]
sampled = random.sample(rows, 3)
print("=" * 60)
print("随机抽样 3 行 (ts_code / roe / grossprofit_margin / netprofit_margin / tr_yoy):")
for i, r in enumerate(sampled, 1):
    print(f"  样例{i}: " + " | ".join(f"{c}={r.get(c)}" for c in sample_cols))
