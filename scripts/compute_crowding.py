#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
市场拥挤度（成交额前 N% 集中度）

指标来源：量化投资邢不行《如何判断抱团行情？》(YouTube Fq4Le_j2E4g)
           广发策略《微观结构恶化，市场如何布局？》

【口径已实测校准，务必按此实现】
    主口径 = 月度累计（MTD）：当月起累计成交额，排名前 5% 个股合计 / 全市场累计 × 100%
    辅助口径 = 单日：当日成交额前 5% 占比（只用于看短期突变，不可套 45/50 阈值）

校准证据：2026-06 全月累计算得 top5%=48.81%，视频原值 48.76%，误差 0.05pp
          （差异来自 akshare/tushare 成交额统计口径微差，非算法问题）
错过的坑：最初按单日算得 52.26%，与视频差 3.5pp —— 单日集中度天然高于月度，
          直接把单日值套 45% 阈值会天天误报。这是本脚本存在的意义。

为什么不做 universe 过滤：这是市场微观结构指标，必须与视频历史值（45%/50% 阈值）
可比。套用选股 universe（剔北交所/双创/ST）会系统性改变分母，阈值就失效了。

视频分档：
    < 20%   低迷，无人问津，无抱团
    20-35%  正常活跃，存量博弈
    35-45%  情绪升温，资金开始抱团少数大票
    45-50%  极端抱团，最后的多空决战（警戒区）
    > 50%   微观结构恶化（广发口径顶级预警）

历史 6 次触发 45%+（视频）：2007-10(45.01) / 2008-09(48.99) / 2014-12(45.81)
                            / 2018-01(46.58) / 2021-01(49.51) / 2026-06(48.76)

用法：
    python scripts/compute_crowding.py                 # 增量更新（已完结月份跳过）
    python scripts/compute_crowding.py --rebuild       # 全量重算
    python scripts/compute_crowding.py --month 202606  # 单独看某个月

输出：
    data/warehouse/crowding/history.csv   # 月度序列
    data/warehouse/crowding/latest.json   # 最新快照（市场分析师直接读这个）
"""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY_DIR = os.path.join(BASE, "data", "warehouse", "daily")
OUT_DIR = os.path.join(BASE, "data", "warehouse", "crowding")
HIST_CSV = os.path.join(OUT_DIR, "history.csv")
LATEST_JSON = os.path.join(OUT_DIR, "latest.json")
PARAMS_DIR = os.path.join(BASE, "knowledge")

FIELDS = ["month", "last_trade_date", "n_days", "n_stocks", "n_top5",
          "top1_pct", "top5_pct", "top10_pct", "total_amount", "complete"]

DEFAULT_CFG = {
    "top_pct": 5,
    "warn_pct": 45.0,
    "alert_pct": 50.0,
    "min_days_for_mtd": 5,      # MTD 累计不足 5 个交易日时，主信号降级为上月值
    "bands": [
        {"max": 20, "label": "低迷", "desc": "无人问津，无抱团"},
        {"max": 35, "label": "正常", "desc": "存量博弈"},
        {"max": 45, "label": "升温", "desc": "资金开始抱团少数大票"},
        {"max": 50, "label": "极端抱团", "desc": "最后的多空决战，警戒区"},
        {"max": 999, "label": "结构恶化", "desc": "微观结构恶化，顶级预警"},
    ],
}


def load_params():
    cfg = dict(DEFAULT_CFG)
    cfg["bands"] = [dict(b) for b in DEFAULT_CFG["bands"]]
    try:
        with open(os.path.join(PARAMS_DIR, "params_current.txt"), encoding="utf-8") as f:
            ver = f.read().strip()
        path = os.path.join(PARAMS_DIR, "params_%s.json" % ver)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                p = json.load(f)
            c = p.get("crowding") or {}
            for k, v in c.items():
                if v is not None and k != "bands":
                    cfg[k] = v
    except Exception as e:
        print("[WARN] 读 params 失败，用默认阈值: %s" % e, file=sys.stderr)
    return cfg


def read_amounts(path):
    """读取单个交易日 amount>0 的 {ts_code: amount}。"""
    out = {}
    try:
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                a = row.get("amount")
                if a in (None, "", "None", "nan"):
                    continue
                try:
                    v = float(a)
                except ValueError:
                    continue
                if v > 0:
                    out[row["ts_code"]] = v
    except Exception as e:
        print("[WARN] 读取失败 %s: %s" % (path, e), file=sys.stderr)
    return out


def top_pcts(amount_map, pcts=(1, 5, 10)):
    """对已累计的成交额做集中度计算。返回 (pcts_dict, counts_dict, total)。"""
    vals = sorted(amount_map.values(), reverse=True)
    total = sum(vals)
    n = len(vals)
    if total <= 0:
        return {}, {}, 0
    p, c = {}, {}
    for q in pcts:
        k = max(1, int(n * q / 100.0))
        p[q] = round(sum(vals[:k]) / total * 100.0, 4)
        c[q] = k
    return p, c, total


def list_daily_files():
    if not os.path.isdir(DAILY_DIR):
        return []
    return sorted(f for f in os.listdir(DAILY_DIR) if f.endswith(".csv"))


def compute_month(files, month, pcts=(1, 5, 10)):
    """对一个月的文件列表做累计，返回月度记录 + 该月最后一日单日记录。"""
    acc = defaultdict(float)
    daily_last = None
    last_date = None
    ndays = 0
    for fn in files:
        date = os.path.splitext(fn)[0]
        am = read_amounts(os.path.join(DAILY_DIR, fn))
        if len(am) < 500:
            continue
        ndays += 1
        last_date = date
        for k, v in am.items():
            acc[k] += v
        daily_last = am  # 保留最后一天的单日快照

    if ndays == 0:
        return None, None

    mp, mc, mtot = top_pcts(acc, pcts)
    dp, dc, dtot = top_pcts(daily_last, pcts) if daily_last else ({}, {}, 0)

    month_rec = {
        "month": month,
        "last_trade_date": last_date,
        "n_days": ndays,
        "n_stocks": len(acc),
        "n_top5": mc.get(5),
        "top1_pct": mp.get(1),
        "top5_pct": mp.get(5),
        "top10_pct": mp.get(10),
        "total_amount": round(mtot, 2),
        "complete": 0,
    }
    day_rec = {
        "trade_date": last_date,
        "n_stocks": len(daily_last) if daily_last else 0,
        "n_top5": dc.get(5),
        "top5_pct": dp.get(5),
        "top1_pct": dp.get(1),
        "top10_pct": dp.get(10),
    }
    return month_rec, day_rec


def load_history():
    if not os.path.exists(HIST_CSV):
        return {}
    with open(HIST_CSV, encoding="utf-8", newline="") as f:
        return {r["month"]: r for r in csv.DictReader(f)}


def save_history(rows):
    os.makedirs(OUT_DIR, exist_ok=True)
    rows = sorted(rows, key=lambda r: r["month"])
    with open(HIST_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in FIELDS})
    return len(rows)


def band_of(value, bands):
    for b in bands:
        if value < b["max"]:
            return b
    return bands[-1]


def pct_rank(series, value):
    if not series:
        return None
    return round(sum(1 for x in series if x < value) / len(series) * 100.0, 1)


def build_latest(month_rows, day_rec, cfg):
    rows = [r for r in month_rows if r.get("top5_pct") not in (None, "")]
    rows = sorted(rows, key=lambda r: r["month"])
    if not rows:
        return None

    cur = rows[-1]
    prev = rows[-2] if len(rows) >= 2 else None
    cur_mtd = float(cur["top5_pct"])
    warn, alert = float(cfg["warn_pct"]), float(cfg["alert_pct"])
    min_days = int(cfg.get("min_days_for_mtd", 5))

    # MTD 样本不足（月初）→ 主信号退回上月完整月值，并打标
    degraded = int(cur["n_days"]) < min_days
    main_val = float(prev["top5_pct"]) if (degraded and prev) else cur_mtd
    main_src = "prev_month" if (degraded and prev) else "mtd"

    hist_series = [float(r["top5_pct"]) for r in rows if r["month"] != cur["month"]]
    band = band_of(main_val, cfg["bands"])

    # 趋势：本月 MTD vs 上月 / 近 3 月
    prev_val = float(prev["top5_pct"]) if prev else None
    mom = round(cur_mtd - prev_val, 4) if prev_val is not None else None
    last3 = [float(r["top5_pct"]) for r in rows[-3:]]
    ma3 = round(sum(last3) / len(last3), 4)

    if main_val >= alert:
        level, sig = "alert", "极端集中，微观结构恶化（顶级预警）"
    elif main_val >= warn:
        level, sig = "warn", "进入极端抱团警戒区"
    elif main_val >= warn - 10:
        level, sig = "watch", "集中度偏高，情绪升温"
    else:
        level, sig = "normal", "集中度正常"

    return {
        "trade_date": day_rec["trade_date"] if day_rec else cur["last_trade_date"],
        "month": cur["month"],
        "top_pct": cfg["top_pct"],

        # 主信号（MTD 月度累计，与视频 45/50 阈值可比）
        "crowding": round(main_val, 4),
        "crowding_source": main_src,
        "mtd_raw": round(cur_mtd, 4),
        "mtd_days": int(cur["n_days"]),
        "mtd_degraded": degraded,

        # 对照
        "prev_month": round(prev_val, 4) if prev_val is not None else None,
        "mom": mom,
        "ma3": ma3,
        "pct_rank": pct_rank(hist_series, main_val),

        # 单日口径（仅看短期突变，不套阈值）
        "daily_crowding": round(float(day_rec["top5_pct"]), 4) if day_rec and day_rec.get("top5_pct") else None,

        # 抱团深度
        "top1_pct": float(cur["top1_pct"]),
        "top10_pct": float(cur["top10_pct"]),
        "n_stocks": int(cur["n_stocks"]),
        "n_top5": int(cur["n_top5"]),

        "band": band["label"],
        "band_desc": band["desc"],
        "warn_pct": warn,
        "alert_pct": alert,
        "level": level,
        "signal": sig,

        "sample_start": rows[0]["month"],
        "sample_months": len(rows),
        "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--month", help="只看某个月 YYYYMM")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    cfg = load_params()
    os.makedirs(OUT_DIR, exist_ok=True)
    files = list_daily_files()
    if not files:
        print("[FAIL] warehouse/daily 为空")
        return 2

    by_month = defaultdict(list)
    for f in files:
        by_month[os.path.splitext(f)[0][:6]].append(f)

    if args.month:
        rec, day = compute_month(by_month.get(args.month, []), args.month)
        print(json.dumps({"month": rec, "day": day}, ensure_ascii=False, indent=1))
        return 0 if rec else 2

    hist = {} if args.rebuild else load_history()
    months_sorted = sorted(by_month)
    cur_month = months_sorted[-1]

    # 已完结月份：history 里已有且天数不变 → 跳过；当前月每次重算
    todo = []
    for m in months_sorted:
        mf = by_month[m]
        if m == cur_month:
            todo.append(m)
        elif m not in hist or int(hist[m].get("n_days") or 0) != len(mf):
            todo.append(m)

    if not args.quiet:
        print("[INFO] 交易日文件 %d 个，%d 个月，待算 %d 个月" % (len(files), len(by_month), len(todo)))

    day_rec = None
    for i, m in enumerate(todo, 1):
        rec, day = compute_month(by_month[m], m)
        if rec:
            rec["complete"] = 0 if m == cur_month else 1
            hist[m] = rec
            if m == cur_month:
                day_rec = day
        if not args.quiet and i % 20 == 0:
            print("[INFO] 进度 %d/%d" % (i, len(todo)))

    # 当前月若不在 todo 也需取 day_rec
    if day_rec is None:
        _, day_rec = compute_month(by_month[cur_month], cur_month)

    n = save_history(list(hist.values()))
    latest = build_latest(list(hist.values()), day_rec, cfg)
    if not latest:
        print("[FAIL] 无有效样本")
        return 1

    with open(LATEST_JSON, "w", encoding="utf-8") as f:
        json.dump(latest, f, ensure_ascii=False, indent=2)

    if not args.quiet:
        print("[OK] history.csv %d 个月（%s ~ %s）" % (n, latest["sample_start"], latest["month"]))
        print("[OK] %s 拥挤度 %.2f%% [%s/%s] 来源=%s（MTD %.2f%% / %d日，单日 %.2f%%）"
              % (latest["trade_date"], latest["crowding"], latest["level"], latest["band"],
                 latest["crowding_source"], latest["mtd_raw"], latest["mtd_days"],
                 latest["daily_crowding"] or 0))
        print("[OK] 上月 %.2f%% 环比 %+.2f | 历史分位 %.1f%% | 前5%%共%d只/共%d只"
              % (latest["prev_month"] or 0, latest["mom"] or 0, latest["pct_rank"] or 0,
                 latest["n_top5"], latest["n_stocks"]))
    print("CROWDING=%s" % latest["crowding"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
