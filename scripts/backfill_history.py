#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Backfill warehouse history for multi-week replay.

Pulls N trading days of full-market daily bars (and daily_basic for each
selection base date) straight through the tushare MCP over HTTP, so nothing
enters the agent context. Idempotent: skips dates already on disk.
"""
import csv
import os
import sys
import time

sys.path.insert(0, r"E:/cashfree/agent/scripts")
from update_warehouse import McpClient, find_client, WH, THROTTLE  # noqa: E402

TARGET_DAYS = 450
WEEKS = 86                # 450 trading days supports ~86 weekly selections
HIST_DAYS = 16           # history needed for the first selection
BASIC_ONLY_FOR_BASE = True


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow([r.get(k) for k in header])


def main():
    c = find_client()
    cal = c.call("trade_cal", {"exchange": "SSE", "start_date": "20240401",
                               "end_date": "20261023"})
    opens = sorted([r["cal_date"] for r in cal if str(r.get("is_open")) == "1"])
    window = opens[-TARGET_DAYS:]
    print("window: %s -> %s (%d trading days)" % (window[0], window[-1], len(window)), flush=True)

    os.makedirs(os.path.join(WH, "daily"), exist_ok=True)
    os.makedirs(os.path.join(WH, "daily_basic"), exist_ok=True)

    missing = [d for d in window if not os.path.exists(os.path.join(WH, "daily", d + ".csv"))]
    print("missing daily files: %d" % len(missing), flush=True)

    for i, d in enumerate(missing, 1):
        rows = c.call("daily", {"trade_date": d,
                                "fields": ["ts_code", "open", "high", "low", "close", "amount"]})
        if not rows:
            print("  [%d/%d] %s EMPTY (data not published yet?)" % (i, len(missing), d), flush=True)
            continue
        write_csv(os.path.join(WH, "daily", d + ".csv"),
                  ["ts_code", "open", "high", "low", "close", "amount"], rows)
        print("  [%d/%d] daily %s: %d rows" % (i, len(missing), d, len(rows)), flush=True)
        time.sleep(THROTTLE)

    # selection base dates: index HIST_DAYS-1, then every 5 days
    base_idx = [HIST_DAYS - 1 + 5 * k for k in range(WEEKS)]
    base_dates = [window[i] for i in base_idx if i < len(window)]
    print("base dates for %d weeks: %s" % (len(base_dates), base_dates), flush=True)

    need_basic = [d for d in base_dates
                  if not os.path.exists(os.path.join(WH, "daily_basic", d + ".csv"))]
    for i, d in enumerate(need_basic, 1):
        rows = c.call("daily_basic", {"trade_date": d,
                                      "fields": ["ts_code", "close", "turnover_rate", "pe_ttm",
                                                 "pb", "ps_ttm", "total_mv", "circ_mv", "total_share"]})
        if not rows:
            print("  [%d/%d] basic %s EMPTY" % (i, len(need_basic), d), flush=True)
            continue
        write_csv(os.path.join(WH, "daily_basic", d + ".csv"),
                  ["ts_code", "close", "turnover_rate", "pe_ttm", "pb", "ps_ttm",
                   "total_mv", "circ_mv", "total_share"], rows)
        print("  [%d/%d] daily_basic %s: %d rows" % (i, len(need_basic), d, len(rows)), flush=True)
        time.sleep(THROTTLE)

    have = sorted(os.path.splitext(f)[0] for f in os.listdir(os.path.join(WH, "daily"))
                  if f.endswith(".csv"))
    print("\nwarehouse daily now: %d files (%s -> %s)" % (len(have), have[0], have[-1]), flush=True)
    print("replay capacity: %d weeks (need %d days, have %d)"
          % ((len(have) - HIST_DAYS) // 5, HIST_DAYS + 5 * WEEKS, len(have)), flush=True)


if __name__ == "__main__":
    main()
