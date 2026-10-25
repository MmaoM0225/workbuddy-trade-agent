import csv
import json
import sys


def main():
    in_path, out_path = sys.argv[1], sys.argv[2]
    cols = ["ts_code", "open", "high", "low", "close", "amount"]
    with open(in_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(cols)
        for row in data:
            writer.writerow([row.get(c, "") for c in cols])
    print(len(data))


if __name__ == "__main__":
    main()
