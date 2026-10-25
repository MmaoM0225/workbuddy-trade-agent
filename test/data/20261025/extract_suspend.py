import csv
import json
import os

raw_path = r"E:\cashfree\agent\data\demo_20261025\suspend_raw_20261023.json"
out_path = r"E:\cashfree\agent\data\demo_20261025\suspend_20261023.csv"

with open(raw_path, "r", encoding="utf-8") as f:
    records = json.load(f)

ts_codes = [r["ts_code"] for r in records]

os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["ts_code"])
    for code in ts_codes:
        writer.writerow([code])

print(f"total: {len(ts_codes)}")
print("first10:")
for c in ts_codes[:10]:
    print(c)
print(f"file: {out_path}")
print(f"exists: {os.path.exists(out_path)}, size: {os.path.getsize(out_path)} bytes")
