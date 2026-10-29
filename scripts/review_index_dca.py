#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""review_index_dca.py - 指数定投周度复盘

四块：
  1. 信号事后表现：历史快照里"建议买入"的标的，到现在的实际涨跌（衡量判据有没有用）
  2. 账本现状：投入/已实现/未实现/总资产/收益率
  3. 结构分析：宽基 vs 行业的资金分配与实际效率、持仓集中度
  4. 偏差与建议：账本实际 vs 同期回测基准

用法：
  python scripts/review_index_dca.py
"""
import csv
import glob
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(ROOT, "state", "signal_history")
PORT = os.path.join(ROOT, "state", "index_portfolio.json")
NAVD = os.path.join(ROOT, "data", "warehouse", "fund_nav")
MAP_OF = os.path.join(ROOT, "data", "index_fund_map_of.json")
IFM = os.path.join(ROOT, "data", "industry_fund_map.json")


def load(p, d=None):
    if not os.path.exists(p):
        return d
    with open(p, encoding="utf-8") as f:
        return json.load(f)


_nav_cache = {}


def nav_series(code):
    if code in _nav_cache:
        return _nav_cache[code]
    fp = os.path.join(NAVD, code + ".csv")
    out = []
    if os.path.exists(fp):
        with open(fp, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("unit_nav"):
                    out.append((r["nav_date"], float(r["unit_nav"])))
    _nav_cache[code] = out
    return out


def fund_of(code, kind):
    if kind == "industry":
        p = (load(IFM, {}).get("map", {}).get(code) or {}).get("primary")
        return p["fund_code"] if p else None
    p = (load(MAP_OF, {}).get("map", {}).get(code) or {}).get("primary")
    return p["fund_code"] if p else None


def nav_on(series, date):
    v = None
    for d, x in series:
        if d <= date:
            v = x
        else:
            break
    return v


def main():
    port = load(PORT, {"cumulative_invested_cny": 0, "realized_pnl_cny": 0, "holdings": {}})
    hold = port.get("holdings", {})

    print("=" * 84)
    print("指数定投 · 周度复盘   %s" % datetime.now().strftime("%Y-%m-%d %H:%M"))
    print("=" * 84)

    # ---------- 1. 信号事后表现 ----------
    snaps = sorted(glob.glob(os.path.join(HIST, "*.json")))
    print("\n[1] 信号事后表现（历史快照 → 至今）")
    if len(snaps) < 2:
        print("    历史快照 %d 个，样本不足（需至少 2 个交易日积累）。从今天开始每日归档，下周起可评估。" % len(snaps))
    else:
        rows = []
        for fp in snaps:
            d = json.load(open(fp, encoding="utf-8"))
            as_of = d["as_of"]
            buys = [x for x in d["items"] if x["action"] == "买入"]
            for b in buys:
                f = fund_of(b["code"], b["kind"])
                if not f:
                    continue
                s = nav_series(f)
                v0, v1 = nav_on(s, as_of), s[-1][1] if s else None
                if v0 and v1:
                    rows.append((as_of, b["name"], b["kind"], b["score"], v1 / v0 - 1))
        if rows:
            by_kind = {}
            for _, n, k, sc, r in rows:
                by_kind.setdefault(k, []).append(r)
            print("    样本 %d 条（每次快照的建议买入项）" % len(rows))
            for k in ("broad", "industry"):
                v = by_kind.get(k, [])
                if not v:
                    continue
                win = sum(1 for x in v if x > 0) / len(v) * 100
                print("      %-8s %3d 条  平均涨跌 %+6.2f%%  胜率 %.0f%%" % (
                    "宽基" if k == "broad" else "行业", len(v), sum(v) / len(v) * 100, win))
            worst = sorted(rows, key=lambda x: x[4])[:3]
            print("      最差 3 条：" + "；".join("%s(%s) %+.1f%%" % (n, d, r * 100) for d, n, k, s, r in worst))
        else:
            print("    快照存在但净值缺失，无法评估")

    # ---------- 2. 账本现状 ----------
    print("\n[2] 账本")
    mv = cost = 0.0
    for c, h in hold.items():
        s = nav_series(h.get("fund", ""))
        px = s[-1][1] if s else h.get("nav", 0)
        cur = h.get("shares", 0) * px
        mv += cur
        cost += h.get("cost", 0)
    inv = port.get("cumulative_invested_cny", 0)
    real = port.get("realized_pnl_cny", 0)
    unreal = mv - cost
    total = inv + real + unreal
    print("    累计投入 %s   已实现 %s   未实现 %s   总资产 %s" % (
        format(inv, ",.0f"), format(real, "+,.0f"), format(unreal, "+,.0f"), format(total, ",.0f")))
    if inv > 0:
        print("    收益率 %.2f%%   持仓 %d 只   成交登记 %d 期" % (
            (real + unreal) / inv * 100, len(hold), len(port.get("history", []))))
    else:
        print("    尚未开始建仓（账本为空）")

    # ---------- 3. 结构分析 ----------
    print("\n[3] 结构")
    if not hold:
        print("    无持仓，跳过")
    else:
        sig = load(os.path.join(ROOT, "state", "index_signal.json"), {"items": []})
        kind_of = {x["code"]: x["kind"] for x in sig.get("items", [])}
        agg = {"broad": [0.0, 0.0], "industry": [0.0, 0.0]}
        for c, h in hold.items():
            k = kind_of.get(c, "industry")
            s = nav_series(h.get("fund", ""))
            px = s[-1][1] if s else h.get("nav", 0)
            cur = h.get("shares", 0) * px
            agg[k][0] += cur
            agg[k][1] += h.get("cost", 0)
        tot = sum(v[0] for v in agg.values()) or 1
        for k, (v, ct) in agg.items():
            if ct <= 0:
                continue
            print("    %-6s 市值 %10s（%4.1f%%）  成本 %10s  盈亏 %+9s（%+.1f%%）" % (
                "宽基" if k == "broad" else "行业", format(v, ",.0f"), v / tot * 100,
                format(ct, ",.0f"), format(v - ct, "+,.0f"), (v - ct) / ct * 100))
        top = sorted(hold.items(), key=lambda x: -(x[1].get("shares", 0) * (nav_series(x[1].get("fund", ""))[-1][1] if nav_series(x[1].get("fund", "")) else 0)))[:3]
        share = 0.0
        for c, h in top:
            s = nav_series(h.get("fund", ""))
            share += h.get("shares", 0) * (s[-1][1] if s else 0)
        print("    前 3 大占比 %.1f%%（超过 50% 说明集中度偏高）" % (share / tot * 100))

    # ---------- 4. 建议 ----------
    print("\n[4] 提示")
    if inv == 0:
        print("    · 账本为空：先按最新计划申购，成交后务必 --commit 登记，否则复盘无数据")
    else:
        r = (real + unreal) / inv * 100 if inv else 0
        if r < -10:
            print("    · 账面亏损超过 10%%，检查是否有行业层超配（行业效率历史上远低于宽基）")
        elif r > 20:
            print("    · 账面收益超过 20%%，注意高估标的的减仓信号是否已执行")
        else:
            print("    · 账面正常区间，维持既有规则")
    pend = glob.glob(os.path.join(ROOT, "state", "orders_pending", "*.json"))
    if pend:
        print("    · 有 %d 个未登记的历史计划在 orders_pending/，需确认是否已成交" % len(pend))
    snaps_n = len(snaps)
    print("    · 信号快照已积累 %d 期%s" % (
        snaps_n, "，下周可开始评估判据有效性" if snaps_n < 5 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
