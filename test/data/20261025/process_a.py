import json
import csv
import os

BASE = r"E:\cashfree\agent\data\demo_20261025"

# 1. 读取 4 批原始数据
rows = []
for i in range(1, 5):
    p = os.path.join(BASE, f"fina_a_batch{i}.json")
    with open(p, "r", encoding="utf-8") as f:
        rows.extend(json.load(f))

# 2. 同一 ts_code 多行：取 ann_date 最新；ann_date 相同则优先非空行
best = {}
for r in rows:
    ts = r["ts_code"]
    ann = str(r.get("ann_date") or "")
    nonnull = sum(1 for k in ("roe", "grossprofit_margin", "netprofit_margin", "tr_yoy") if r.get(k) is not None)
    key = (ann, nonnull)
    if ts not in best or key > best[ts][0]:
        best[ts] = (key, r)

# 3. 写 fina_h1_a.csv（UTF-8），五列
out_csv = os.path.join(BASE, "fina_h1_a.csv")
with open(out_csv, "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f)
    w.writerow(["ts_code", "roe", "grossprofit_margin", "netprofit_margin", "tr_yoy"])
    for ts in sorted(best):
        r = best[ts][1]
        w.writerow([ts, r.get("roe"), r.get("grossprofit_margin"), r.get("netprofit_margin"), r.get("tr_yoy")])

# 4. 与目标 100 只对比，统计缺失
with open(os.path.join(BASE, "fina_missing.txt"), "r", encoding="utf-8") as f:
    all_codes = [c.strip() for c in f.read().strip().split(",") if c.strip()]
target = all_codes[:100]

got = {ts for ts in best}
missing = [c for c in target if c not in got]

with open(os.path.join(BASE, "fina_missing2_a.txt"), "w", encoding="utf-8") as f:
    f.write(",".join(missing))

print(f"total target: {len(target)}")
print(f"got data: {len(target) - len(missing)}")
print(f"missing: {len(missing)}")
if missing:
    print(",".join(missing))
