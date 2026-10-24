#!/usr/bin/env python3
"""P0 pipeline integrity checker for the multi-agent trading framework.

Usage:
    python check_pipeline.py            # check state files + latest data dir (if any)
    python check_pipeline.py --date 20261023

Checks:
    1. state/*.json parse as JSON and contain required schema keys
    2. state/trades.jsonl every non-empty line is valid JSON
    3. data/daily_<date>/ exists with meta.json and non-empty core files

Exit code 0 = all pass, 1 = at least one FAIL.
"""
import json
import sys
from pathlib import Path

BASE = Path("E:/cashfree/agent")
STATE = BASE / "state"
DATA = BASE / "data"

STATE_SCHEMAS = {
    "pool.json": ["date", "strategy_version", "count", "stocks"],
    "watchlist.json": ["date", "source_pool_date", "items"],
    "regime.json": ["date", "regime", "confidence", "evidence",
                    "sector_signals", "risk_level", "confirmed_days"],
    "positions.json": ["as_of", "cash_pct", "total_pnl_pct", "holdings"],
    "orders.json": ["orders"],
}

DATA_CORE_FILES = ["indices.json"]
DATA_OPTIONAL_FILES = ["market_overview.json", "news.json"]

failures = []


def check_state():
    for fname, keys in STATE_SCHEMAS.items():
        p = STATE / fname
        if not p.exists():
            failures.append(f"missing state file: {p}")
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            failures.append(f"{fname}: invalid JSON ({e})")
            continue
        missing = [k for k in keys if k not in data]
        if missing:
            failures.append(f"{fname}: missing keys {missing}")
    trades = STATE / "trades.jsonl"
    if not trades.exists():
        failures.append("missing state/trades.jsonl")
    else:
        bad = 0
        total = 0
        for line in trades.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            total += 1
            try:
                json.loads(line)
            except Exception:
                bad += 1
        if bad:
            failures.append(f"trades.jsonl: {bad}/{total} lines are not valid JSON")
    print(f"[state] schema check done, {len(STATE_SCHEMAS)} files + trades.jsonl")


def latest_data_date():
    if not DATA.exists():
        return None
    dirs = sorted(d.name.replace("daily_", "") for d in DATA.glob("daily_*") if d.is_dir())
    return dirs[-1] if dirs else None


def check_data(date_str):
    d = DATA / f"daily_{date_str}"
    if not d.exists():
        failures.append(f"data dir missing: {d}")
        return
    meta_p = d / "meta.json"
    if not meta_p.exists():
        failures.append(f"{d}/meta.json missing")
        return
    try:
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
    except Exception as e:
        failures.append(f"meta.json invalid JSON ({e})")
        return
    if meta.get("degraded"):
        print(f"[data] {date_str} marked degraded: {meta.get('notes')}")
    for f in DATA_CORE_FILES:
        p = d / f
        if not p.exists():
            failures.append(f"core data file missing: {f}")
            continue
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            failures.append(f"{f}: invalid JSON ({e})")
            continue
        n = len(payload) if isinstance(payload, list) else len(payload.get("records", payload.get("items", [1])))
        if n == 0:
            failures.append(f"{f}: empty")
        else:
            print(f"[data] {f}: {n} records")
    for f in DATA_OPTIONAL_FILES:
        p = d / f
        if not p.exists():
            print(f"[data] {f}: absent (non-core)")
            continue
        try:
            payload = json.loads(p.read_text(encoding="utf-8"))
            n = len(payload) if isinstance(payload, list) else len(payload.get("records", []))
            print(f"[data] {f}: {n} records")
        except Exception as e:
            failures.append(f"{f}: invalid JSON ({e})")


def main():
    date_str = None
    args = sys.argv[1:]
    if "--date" in args:
        i = args.index("--date")
        if i + 1 < len(args):
            date_str = args[i + 1]
    if date_str is None:
        date_str = latest_data_date()

    check_state()
    if date_str:
        check_data(date_str)
    else:
        print("[data] no daily_* data dir found, skipping data check")

    if failures:
        print("\n=== RESULT: FAIL ===")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("\n=== RESULT: PASS ===")
    sys.exit(0)


if __name__ == "__main__":
    main()
