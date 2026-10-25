import csv
import json
import os

BASE = r"E:\cashfree\agent\data\demo_20261025"
FIELDS = ["ts_code", "trade_date", "open", "high", "low", "close", "amount"]

# 1) 读取 8 个批次原始 JSON，提取字段，写 daily_0917.csv
all_rows = []
batch_codes = {}
for n in range(1, 9):
    with open(os.path.join(BASE, f"daily_raw_b{n}.json"), encoding="utf-8") as f:
        data = json.load(f)
    for rec in data:
        all_rows.append({k: rec[k] for k in FIELDS})
    # 批次股票清单（用于合并时归类）
    with open(os.path.join(BASE, f"batch_{n}.txt"), encoding="utf-8") as f:
        batch_codes[n] = set(c.strip() for c in f.read().strip().split(",") if c.strip())

all_rows.sort(key=lambda r: (r["ts_code"], r["trade_date"]))
out_path = os.path.join(BASE, "daily_0917.csv")
with open(out_path, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=FIELDS)
    w.writeheader()
    w.writerows(all_rows)
print(f"daily_0917.csv written: {len(all_rows)} rows")

# 校验：每只股票只出现一次
codes = [r["ts_code"] for r in all_rows]
assert len(codes) == len(set(codes)), "duplicate ts_code in daily_0917.csv"

# 2) 合并进 daily_b{N}.csv
report = {}
for n in range(1, 9):
    path = os.path.join(BASE, f"daily_b{n}.csv")
    existing = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            existing[(row["ts_code"], row["trade_date"])] = row
    before = len(existing)
    added = 0
    for r in all_rows:
        if r["ts_code"] in batch_codes[n]:
            key = (r["ts_code"], r["trade_date"])
            if key not in existing:
                added += 1
            existing[key] = {k: str(r[k]) for k in FIELDS}
    merged = sorted(existing.values(), key=lambda r: (r["ts_code"], r["trade_date"]))
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(merged)
    n_stocks = len(set(r["ts_code"] for r in merged))
    report[n] = (before, added, len(merged), n_stocks)
    print(f"daily_b{n}.csv: before={before}, added={added}, after={len(merged)}, stocks={n_stocks}")

# 校验：合并后总行数 = 8 个文件行数之和
total = sum(v[2] for v in report.values())
print(f"sum of daily_b* rows: {total}")
