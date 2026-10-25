#!/usr/bin/env python3
"""Pipeline integrity checker for the multi-agent trading framework.

Usage:
    python check_pipeline.py [--base E:/cashfree/agent] [--date 20261023]

Checks:
    1. state/*.json parse as JSON and contain required schema keys
    2. state/trades.jsonl every non-empty line is valid JSON
    3. data/daily_<date>/ exists with meta.json and non-empty core files
    4. business rules on populated state files (weight caps, stop/take sanity,
       regime enum, evidence count, order tranche rules, trade record sanity)
    5. state/tasks/*.json task status files (9 tasks, undo/doing/done enum,
       single-writer file per task)

Business rules only apply to files that have been populated (date/as_of set),
so the initial empty skeleton passes.

Exit code 0 = all pass, 1 = at least one FAIL.
"""
import argparse
import json
import sys
from pathlib import Path

STATE_SCHEMAS = {
    "pool.json": ["date", "strategy_version", "count", "stocks"],
    "watchlist.json": ["date", "source_pool_date", "items"],
    "regime.json": ["date", "regime", "confidence", "evidence",
                    "sector_signals", "risk_level", "confirmed_days"],
    "positions.json": ["as_of", "cash_pct", "total_pnl_pct", "holdings"],
    "orders.json": ["orders"],
}

DATA_CORE_FILES = ["indices.json", "market_overview.json"]
DATA_OPTIONAL_FILES = ["news.json", "hot_news.json", "hot_board.json",
                       "sector_ranking.json", "dragon_tiger.json", "northbound.json"]

REGIMES = ("bull", "neutral", "bear")
TOL = 0.5

failures = []
STATE = None
DATA = None


def load_json(p):
    return json.loads(p.read_text(encoding="utf-8"))


def check_state():
    for fname, keys in STATE_SCHEMAS.items():
        p = STATE / fname
        if not p.exists():
            failures.append(f"missing state file: {p}")
            continue
        try:
            data = load_json(p)
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


def check_business():
    regime = load_json(STATE / "regime.json")
    if regime.get("date"):
        if regime.get("regime") not in REGIMES:
            failures.append(f"regime.json: regime={regime.get('regime')!r} not in {REGIMES}")
        c = regime.get("confidence")
        if not (isinstance(c, (int, float)) and 0 <= c <= 1):
            failures.append(f"regime.json: confidence={c!r} out of [0,1]")
        if len(regime.get("evidence") or []) < 2:
            failures.append("regime.json: fewer than 2 evidence items")

    pool = load_json(STATE / "pool.json")
    if pool.get("date"):
        stocks = pool.get("stocks") or []
        if pool.get("count") != len(stocks):
            failures.append(f"pool.json: count={pool.get('count')} != len(stocks)={len(stocks)}")
        if not pool.get("strategy_version"):
            failures.append("pool.json: strategy_version missing")

    wl = load_json(STATE / "watchlist.json")
    if wl.get("date"):
        for it in wl.get("items") or []:
            if it.get("verdict") == "buy_watch":
                if not it.get("thesis"):
                    failures.append(f"watchlist.json: {it.get('code')} buy_watch without thesis")
                if not (it.get("risks") or []):
                    failures.append(f"watchlist.json: {it.get('code')} buy_watch without risks")

    pos = load_json(STATE / "positions.json")
    if pos.get("as_of"):
        holdings = pos.get("holdings") or []
        total_w = sum(h.get("weight_pct", 0) or 0 for h in holdings)
        if total_w > 100 + TOL:
            failures.append(f"positions.json: holdings weight sum {total_w:.1f}% > 100%")
        cash = pos.get("cash_pct") or 0
        if abs(cash + total_w - 100) > 1.0:
            failures.append(f"positions.json: cash {cash:.1f}% + weights {total_w:.1f}% != 100%")
        for h in holdings:
            code = h.get("code")
            w = h.get("weight_pct") or 0
            if w > 15 + TOL:
                failures.append(f"positions.json: {code} weight {w:.1f}% exceeds 15% cap")
            cost, sl, tp = h.get("cost"), h.get("stop_loss"), h.get("take_profit")
            if cost and sl and sl >= cost:
                failures.append(f"positions.json: {code} stop_loss {sl} >= cost {cost}")
            if cost and tp and tp <= cost:
                failures.append(f"positions.json: {code} take_profit {tp} <= cost {cost}")

    orders = (load_json(STATE / "orders.json")).get("orders") or []
    for o in orders:
        oid = o.get("id", "?")
        if o.get("side") == "buy":
            trs = o.get("tranches") or []
            if len(trs) < 2:
                failures.append(f"orders.json: {oid} has {len(trs)} tranches (<2)")
            if sum(t.get("pct", 0) or 0 for t in trs) > 15 + TOL:
                failures.append(f"orders.json: {oid} tranche pct sum exceeds 15% cap")
            if not (o.get("stop_loss") and o.get("take_profit")):
                failures.append(f"orders.json: {oid} missing stop_loss/take_profit")
        elif o.get("side") == "sell":
            if not (o.get("reason") and o.get("trigger")):
                failures.append(f"orders.json: {oid} sell order missing reason/trigger")

    for line in (STATE / "trades.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            t = json.loads(line)
        except Exception:
            continue
        tid = t.get("trade_id", "?")
        if (t.get("open") or {}).get("price", 0) <= 0:
            failures.append(f"trades.jsonl: {tid} open price <= 0")
        if t.get("close"):
            if (t["close"] or {}).get("price", 0) <= 0:
                failures.append(f"trades.jsonl: {tid} close price <= 0")
            if t.get("pnl_pct") is None:
                failures.append(f"trades.jsonl: {tid} closed without pnl_pct")
    print("[state] business rules checked (populated files only)")


TASK_NAMES = [
    "data_officer", "market_analyst", "position_manager", "inspector",
    "stock_picker", "researcher", "position_builder", "reviewer", "archivist",
]
TASK_STATUSES = ("undo", "doing", "done")


def check_tasks():
    """state/tasks/*.json: one file per task (single-writer), status enum valid."""
    tasks_dir = STATE / "tasks"
    if not tasks_dir.exists():
        failures.append(f"missing tasks dir: {tasks_dir}")
        return
    for name in TASK_NAMES:
        p = tasks_dir / f"{name}.json"
        if not p.exists():
            failures.append(f"missing task state: {name}.json")
            continue
        try:
            t = load_json(p)
        except Exception as e:
            failures.append(f"tasks/{name}.json: invalid JSON ({e})")
            continue
        st = t.get("status")
        if st not in TASK_STATUSES:
            failures.append(f"tasks/{name}.json: invalid status {st!r}")
        if t.get("task") and t.get("task") != name:
            failures.append(f"tasks/{name}.json: task field mismatch ({t.get('task')})")
    print("[tasks] %d task states checked" % len(TASK_NAMES))


def latest_data_date():
    if not DATA.exists():
        return None
    dirs = sorted(d.name.replace("daily_", "") for d in DATA.glob("daily_*") if d.is_dir())
    return dirs[-1] if dirs else None


def _record_count(payload):
    """Best-effort record count across the daily_* file shapes."""
    if isinstance(payload, list):
        return len(payload)
    for k in ("records", "items", "dimensions", "top_gainers", "net_buy_top10"):
        v = payload.get(k)
        if isinstance(v, (list, dict)):
            return len(v)
    return 1


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
        meta = load_json(meta_p)
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
            payload = load_json(p)
        except Exception as e:
            failures.append(f"{f}: invalid JSON ({e})")
            continue
        n = _record_count(payload)
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
            payload = load_json(p)
            n = _record_count(payload)
            print(f"[data] {f}: {n} records")
        except Exception as e:
            failures.append(f"{f}: invalid JSON ({e})")


def main():
    global STATE, DATA
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="E:/cashfree/agent")
    ap.add_argument("--date", default=None)
    args = ap.parse_args()

    STATE = Path(args.base) / "state"
    DATA = Path(args.base) / "data"

    date_str = args.date or latest_data_date()

    check_state()
    check_business()
    check_tasks()
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
