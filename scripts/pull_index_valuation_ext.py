#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pull_index_valuation_ext.py - 外部源补指数估值（neodata 覆盖不到的市场）

## 为什么需要这个脚本

neodata index_valuation 只支持 A股 / 港股 / 美股主要指数。日本、越南、印度
三个市场在 neodata / tushare / westock 全部无 PE/PB 序列（2026-10-29 已穷举）。
本脚本从公开源把能拿到的补进来。

## 当前覆盖

| 市场 | 代码 | 源 | 频率 | 口径 |
|---|---|---|---|---|
| 印度 NIFTY 50 | NIFTY50.NS | downstox.com（聚合 NSE 官方读数） | 月度 | PE / PB / 股息率 |

## 为什么印度用 NIFTY 50 而不是 SENSEX

SENSEX 的估值只在 BSE 官网，且被 Akamai 反爬（沙箱直连 403）。
NIFTY 50 是 NSE 的旗舰基准，与 SENSEX 相关性 >0.98，且公开月度 PE/PB 序列可拿。
原 SENSEX.GI 条目保留但 enabled=false，注明改走 NIFTY50.NS。

## 月度 → 日度

上游是月度读数，但下游 index_valuation_signal.build_broad 按"行数"算滚动分位
（window_days≈1250 行）。所以这里做**前向填充**：按 A股交易日历把每月读数铺满，
使 1250 行 ≈ 5 年，分位口径与日度序列一致。原始月度序列另存一份供审计。

## 失败处理

月度数据，晚一天无影响，所以网络失败**不返回非 0**，只打 WARN 并保留旧文件。
真正的数据缺失由 index_valuation_signal 的 missing 列表报出来。

用法：
  python scripts/pull_index_valuation_ext.py
"""
import csv
import json
import os
import sys
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WD = os.path.join(ROOT, "data", "warehouse", "index_valuation")
RAW = os.path.join(ROOT, "data", "warehouse", "index_valuation_ext")
HEADER = ("trade_date,pe_ttm,pe_ttm_ex_neg,pb_lf,pb_mrq,"
          "dividend_ratio,total_mv,index_nc,loss_nc")

SOURCES = [
    {
        "code": "NIFTY50.NS",
        "name": "印度NIFTY50",
        "url": "https://downstox.com/api/index-pe/nifty-50/download",
        "credit": "Downstox https://downstox.com/nifty-pe/nifty-50 （上游 NSE 官方读数）",
    },
]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0"


def fetch(url, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def parse_monthly(text):
    """解析 'Month,PE,PB,DividendYield' + '#' 注释头，返回 [(YYYY-MM, pe, pb, dy)]。"""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4 or not parts[0][:4].isdigit():
            continue  # 表头
        ym = parts[0][:7]
        if len(ym) != 7:
            continue
        def f(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        out.append((ym, f(parts[1]), f(parts[2]), f(parts[3])))
    out.sort(key=lambda x: x[0])
    return out


def trading_days():
    """用 A股沪深300 的已有估值序列当交易日历（本地，无网络）。"""
    p = os.path.join(WD, "000300.SH.csv")
    if not os.path.exists(p):
        return []
    ds = []
    with open(p, encoding="utf-8") as f:
        next(f, None)
        for line in f:
            if line.strip():
                ds.append(line.split(",")[0])
    return ds


def build_daily(monthly, days):
    """月度读数前向填充到日度。返回 {trade_date: (pe, pb, dy)}。"""
    if not monthly:
        return {}
    out = {}
    i = 0
    cur = None
    for d in days:
        ym = d[:4] + "-" + d[4:6]
        while i < len(monthly) and monthly[i][0] <= ym:
            cur = monthly[i]
            i += 1
        if cur:
            out[d] = (cur[1], cur[2], cur[3])
    return out


def main():
    os.makedirs(RAW, exist_ok=True)
    os.makedirs(WD, exist_ok=True)
    days = trading_days()
    if not days:
        print("FAILED 找不到交易日历 data/warehouse/index_valuation/000300.SH.csv")
        return 1

    rc = 0
    for s in SOURCES:
        code = s["code"]
        try:
            text = fetch(s["url"])
            monthly = parse_monthly(text)
            if len(monthly) < 60:
                raise RuntimeError("只解析到 %d 条月度读数" % len(monthly))
        except Exception as e:  # noqa: BLE001
            print("WARN %s 拉取失败，保留旧文件：%s" % (code, str(e)[:160]))
            continue

        raw_path = os.path.join(RAW, code + "_monthly.csv")
        with open(raw_path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["month", "pe", "pb", "dividend_yield"])
            w.writerows(monthly)

        daily = build_daily(monthly, days)
        path = os.path.join(WD, code + ".csv")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(HEADER + "\n")
            for d in sorted(daily):
                pe, pb, dy = daily[d]
                f.write("%s,%s,%s,%s,%s,%s,,,\n"
                        % (d, _s(pe), _s(pe), _s(pb), _s(pb), _s(dy)))

        last_month, lpe, lpb, ldy = monthly[-1]
        print("%s <- %s  月度 %d 条（%s..%s） 日度 %d 行  最新 %s PE=%s PB=%s DY=%s"
              % (code, s["name"], len(monthly), monthly[0][0], last_month,
                 len(daily), last_month, lpe, lpb, ldy))
        print("    源：%s" % s["credit"])

    # 记账：谁在什么时候更新过，便于排查陈旧数据
    meta = os.path.join(RAW, "last_update.json")
    try:
        old = json.load(open(meta, encoding="utf-8")) if os.path.exists(meta) else {}
    except (ValueError, OSError):
        old = {}
    old[datetime.now().strftime("%Y-%m-%d %H:%M")] = [
        s["code"] for s in SOURCES
        if os.path.exists(os.path.join(WD, s["code"] + ".csv"))]
    json.dump(old, open(meta, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return rc


def _s(v):
    return "" if v is None else ("%g" % v)


if __name__ == "__main__":
    sys.exit(main())
