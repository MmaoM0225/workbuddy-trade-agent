#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""净值历史记录器：每日把组合净值 + 基准指数落盘到 state/nav_history.jsonl。

持仓管家的【收益率曲线】板块数据源。append-only 风格，但同一交易日重复运行会覆盖当天记录
（重跑/补数据不会产生重复点）。

用法：
  python scripts/update_nav.py --date 20261026            # 记录指定交易日
  python scripts/update_nav.py --date 20261026 --backfill # 从基准日补点（空仓期也补）

字段：
  date          交易日
  total_asset   总资产（元）
  cash          现金（元）
  market_value  持仓市值（元）
  pnl_pct       相对初始本金的累计收益率（%）
  position_pct  仓位（%）
  benchmark     基准指数收盘（默认上证 000001.SH）
  benchmark_pct 基准相对建仓首日的涨跌幅（%）
  holdings      持仓只数
"""
import argparse
import glob
import json
import os
from datetime import datetime

ROOT = r"E:\cashfree\agent"
NAV = os.path.join(ROOT, "state", "nav_history.jsonl")
POS = os.path.join(ROOT, "state", "positions.json")
WH = os.path.join(ROOT, "data", "warehouse")
DAILY_ROOT = os.path.join(ROOT, "data")
BENCH_CODE = "000001.SH"


def load_bench_close(date):
    """取基准指数某交易日收盘：优先当日 data/daily_<date>/indices.json，其次 warehouse 快照。
    该文件在历史轮次里存在两种结构（dict 含 indices 键 / 直接是 list），两种都要兼容。"""
    p = os.path.join(DAILY_ROOT, f"daily_{date}", "indices.json")
    if os.path.exists(p):
        try:
            d = json.load(open(p, encoding="utf-8"))
            items = d.get("indices") if isinstance(d, dict) else d
            for x in items or []:
                if isinstance(x, dict) and x.get("ts_code") == BENCH_CODE:
                    return float(x["close"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass
    return None


def read_nav():
    if not os.path.exists(NAV):
        return []
    out = []
    with open(NAV, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def write_nav(rows):
    rows.sort(key=lambda r: r["date"])
    tmp = NAV + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, NAV)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="交易日 YYYYMMDD")
    ap.add_argument("--backfill", action="store_true", help="基准日到指定日之间补点（空仓日按现金计）")
    a = ap.parse_args()
    date = a.date

    pos = json.load(open(POS, encoding="utf-8"))
    initial = float(pos.get("initial_capital_cny") or 1000000)
    total = float(pos.get("total_asset_cny") or initial)
    cash = float(pos.get("cash_cny") or initial)
    holdings = pos.get("holdings") or []
    mv = sum(float(h.get("market_value_cny") or 0) for h in holdings)

    rows = read_nav()
    by_date = {r["date"]: r for r in rows}

    bench = load_bench_close(date)
    rec = {
        "date": date,
        "total_asset": round(total, 2),
        "cash": round(cash, 2),
        "market_value": round(mv, 2),
        "pnl_pct": round((total / initial - 1) * 100, 2),
        "position_pct": round(mv / total * 100, 2) if total else 0.0,
        "benchmark": bench,
        "benchmark_pct": 0.0,   # 占位，下面统一按基期重算
        "holdings": len(holdings),
    }
    by_date[date] = rec

    if a.backfill:
        # 从基准日 20261023 到 date 之间的所有交易日，缺失的按"现金满额、空仓"补
        trade_days = sorted(
            os.path.basename(p)[:-4] for p in glob.glob(os.path.join(WH, "daily", "*.csv"))
            if "20261023" <= os.path.basename(p)[:-4] <= date
        )
        for d in trade_days:
            if d in by_date:
                continue
            by_date[d] = {
                "date": d, "total_asset": round(initial, 2), "cash": round(initial, 2),
                "market_value": 0.0, "pnl_pct": 0.0, "position_pct": 0.0,
                "benchmark": load_bench_close(d), "benchmark_pct": 0.0, "holdings": 0,
            }

    # 统一按最早一条为基期重算基准涨跌幅（避免补点时基期取错导致首点为负）
    ordered = sorted(by_date.values(), key=lambda x: x["date"])
    base_bench = next((r["benchmark"] for r in ordered if r.get("benchmark")), None)
    for r in ordered:
        b = r.get("benchmark")
        r["benchmark_pct"] = round((b / base_bench - 1) * 100, 2) if (b and base_bench) else 0.0

    write_nav(ordered)
    print(f"nav: {len(ordered)} 个交易日 -> {NAV}")
    for r in ordered:
        print(f"  {r['date']}  总资产 {r['total_asset']:>12,.2f}  收益 {r['pnl_pct']:>+6.2f}%  "
              f"仓位 {r['position_pct']:>5.2f}%  基准 {r['benchmark_pct']:>+6.2f}%  持仓 {r['holdings']} 只")


if __name__ == "__main__":
    main()
