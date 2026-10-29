#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""index_valuation_signal.py - 估值分位与定投分档信号（v2.0）

两层结构：
  broad    宽基 13 个（昴指定清单）—— 自算滚动分位：PE(剔负值) + PB，按风格加权
  industry 申万二级 124 个 —— 直接用申万官方 5 年分位：PB 0.5 + PS 0.5

为什么行业用申万现成分位而不是自算：
  申万板块 5 年分位由官方维护，覆盖全部二级行业，同时给 PE/PB/PS/股息率四维。
  行业层面 PE 失真严重（盈利周期扰动），所以只取 PB + PS。

规则（v2.0，不看本金）：分位 <10→2.0x，10-25→1.5x，25-40→1.0x，40-75→停投，
  75-90→减仓，>=95→清仓。金额 = execute.unit_amount_cny x 倍数，不设本金上限。

用法：
  python scripts/index_valuation_signal.py
  python scripts/index_valuation_signal.py --date 20261027
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WD = os.path.join(ROOT, "data", "warehouse", "index_valuation")
SW = os.path.join(ROOT, "data", "warehouse", "sw_industry", "latest.json")
IFM = os.path.join(ROOT, "data", "industry_fund_map.json")
NAV = os.path.join(ROOT, "data", "warehouse", "fund_nav")
SWD = os.path.join(ROOT, "data", "warehouse", "sw_industry")
POOL = os.path.join(ROOT, "data", "index_universe.json")


def load_index_params():
    """指数估值定投线参数（唯一真源）：knowledge/index_params.json
    与个股线 knowledge/params_v*.json 完全独立，不再混用。"""
    p = os.path.join(ROOT, "knowledge", "index_params.json")
    if not os.path.exists(p):
        raise SystemExit("缺少 knowledge/index_params.json（指数线唯一真源）")
    with open(p, encoding="utf-8") as f:
        return json.load(f)

CYCLICAL = {"000986.SH", "399975.SZ", "000318.CSI"}
GROWTH = {"399006.SZ", "000688.SH", "000935.SH", "HSTECH.HK", "IXIC.US", "NDX.US", "000933.SH"}


def fnum(v):
    try:
        return float(v) if v not in ("", None, "--") else None
    except (TypeError, ValueError):
        return None


def style_weights(code):
    if code in CYCLICAL:
        return 0.3, 0.7
    if code in GROWTH:
        return 0.7, 0.3
    return 0.5, 0.5


def read_series(code):
    path = os.path.join(WD, code + ".csv")
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        hdr = next(f).strip().split(",")
        for line in f:
            if not line.strip():
                continue
            parts = line.rstrip("\n").split(",")
            if len(parts) == len(hdr):
                rows.append(dict(zip(hdr, parts)))
    rows.sort(key=lambda r: r["trade_date"])
    return rows


def pct_rank(series, window, min_periods):
    out = [None] * len(series)
    for i, v in enumerate(series):
        if v is None:
            continue
        hist = [x for x in series[max(0, i - window + 1):i + 1] if x is not None]
        if len(hist) < min_periods:
            continue
        less = sum(1 for x in hist if x < v)
        eq = sum(1 for x in hist if x == v)
        out[i] = (less + 0.5 * eq) / len(hist) * 100.0
    return out


def pick_zone(score, params, pb=None, div=None):
    capped = None
    if score >= 75:
        hit = []
        if pb is not None and pb < params["pb_floor_no_high"]:
            hit.append("PB<%.1f" % params["pb_floor_no_high"])
        if div is not None and div >= params["div_yield_no_high"]:
            hit.append("股息>=%.1f%%" % params["div_yield_no_high"])
        if hit:
            score = min(score, 74.9)
            capped = "/".join(hit) + " 否决减仓→停投"
    for z in params["zones"]:
        if z["lo"] <= score < z["hi"]:
            return z, capped, score
    return params["zones"][-1], capped, score



def build_price_item(m, params, target_date):
    """无估值序列的标的（日经/越南/印度/中韩半导体）降级方案：
    用跟踪基金的复权净值算滚动分位。这不是估值分位，只是价格位置，
    所以规则更保守——只在低位买 1.0x，不翻倍、不产生卖出信号。
    """
    navf = m.get("nav_fund")
    if not navf:
        return None, "无可用净值基金"
    path = os.path.join(NAV, navf + ".csv")
    if not os.path.exists(path):
        return None, "净值文件缺失 %s" % navf
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    rows.sort(key=lambda r: r["nav_date"])
    if len(rows) < 250:
        return None, "净值仅 %d 条" % len(rows)
    dates = [r["nav_date"] for r in rows]
    vals = [fnum(r["adj_nav"]) for r in rows]
    win = min(params["window_days"], len(rows))
    mp = min(params["min_periods"], max(250, len(rows) // 2))
    pct = pct_rank(vals, win, mp)[-1]
    if pct is None:
        return None, "分位无法计算"
    if pct < 20:
        zone, action, mult = "价格低位", "买入", 1.0
    elif pct < 40:
        zone, action, mult = "价格偏低", "买入", 1.0
    else:
        zone, action, mult = "价格中性/偏高", "停投", 0.0
    return {
        "kind": "broad", "code": m["code"], "name": m["name"], "group": m["group"],
        "family": m.get("family", m["code"]), "market": m.get("market"),
        "date": dates[-1], "pe": None, "pb": None, "div": None,
        "pe_pct": None, "pb_pct": None,
        "price_pct": round(pct, 1),
        "score": round(pct, 1), "zone": zone, "action": action,
        "mult": mult, "caps": "", "metric": "价格分位",
        "nav_fund": navf, "nav_name": m.get("nav_name", ""),
        "proxy_active_fund": bool(m.get("proxy_active_fund")),
        "note": m.get("note", ""),
        "fund": m.get("of_fund", ""), "fund_name": m.get("of_fund_name", ""),
        "tracking_error_1y": m.get("of_te"),
    }, None


def build_broad(uni, params, target_date):
    items, missing = [], []
    for m in uni["indices"]:
        code = m["code"]
        if m.get("enabled") is False:
            continue  # 人工停用（如无估值源的价格分位标的），不产生信号
        if m.get("datasource") == "price":
            it, why = build_price_item(m, params, target_date)
            if it:
                items.append(it)
            else:
                missing.append((code, m["name"], m.get("market"), "价格分位失败：%s" % why))
            continue
        if m.get("datasource") == "none":
            missing.append((code, m["name"], m.get("market"), "库内无该国指数估值序列"))
            continue
        rows = read_series(code)
        if len(rows) < 120:
            missing.append((code, m["name"], m.get("market"), "估值序列仅 %d 条" % len(rows)))
            continue
        dates = [r["trade_date"] for r in rows]
        td = target_date or dates[-1]
        idx = dates.index(td) if td in dates else max((i for i, d in enumerate(dates) if d <= td),
                                                      default=len(dates) - 1)
        pe_s = [fnum(r["pe_ttm_ex_neg"]) for r in rows]
        pb_s = [fnum(r["pb_lf"]) for r in rows]
        win = min(params["window_days"], len(rows))
        mp = min(params["min_periods"], max(120, len(rows) // 2))
        pep, pbp = pct_rank(pe_s, win, mp)[idx], pct_rank(pb_s, win, mp)[idx]
        if pep is None and pbp is None:
            missing.append((code, m["name"], m.get("market"), "分位无法计算"))
            continue
        wp, wb = style_weights(code)
        if pep is None:
            score = pbp
        elif pbp is None:
            score = pep
        else:
            score = wp * pep + wb * pbp
        pe, pb, div = pe_s[idx], pb_s[idx], fnum(rows[idx]["dividend_ratio"])
        zone, capped, score = pick_zone(score, params, pb, div)
        # 载体是主动基金（非纯指数敞口，含 alpha 与基金经理偏离）时，倍数封顶 1.0x：
        # 估值分位讲的是指数，买的是主动基金，2.0x 加码等于放大一个不成立的假设。
        mult = zone["mult"]
        if m.get("proxy_active_fund") and mult > 1.0:
            mult = 1.0
            capped = "/".join(x for x in (capped, "主动基金代理 倍数封顶1.0x") if x)
        items.append({
            "kind": "broad", "code": code, "name": m["name"], "group": m["group"],
            "family": m.get("family", code), "market": m.get("market"),
            "date": dates[idx], "pe": pe, "pb": pb, "div": div,
            "pe_pct": None if pep is None else round(pep, 1),
            "pb_pct": None if pbp is None else round(pbp, 1),
            "score": round(score, 1), "zone": zone["name"], "action": zone["action"],
            "mult": mult, "caps": capped or "", "note": m.get("note", ""),
            "metric": m.get("metric", ""),
            "proxy_active_fund": bool(m.get("proxy_active_fund")),
            "fund": m.get("of_fund", ""), "fund_name": m.get("of_fund_name", ""),
            "tracking_error_1y": m.get("of_te"),
        })
    return items, missing


def build_industry(params, target_date):
    if not os.path.exists(SW):
        return [], []
    with open(SW, encoding="utf-8") as f:
        sw = json.load(f)
    fmap = {}
    if os.path.exists(IFM):
        with open(IFM, encoding="utf-8") as f:
            fmap = json.load(f).get("map", {})
    items, missing = [], []
    for code, v in sw["map"].items():
        pb_pct, ps_pct = v.get("pb_pct_5y"), v.get("ps_pct_5y")
        vals = [x for x in (pb_pct, ps_pct) if x is not None]
        if not vals:
            missing.append((code, v["name"], "SW", "无 PB/PS 分位"))
            continue
        score = sum(vals) / len(vals) * 100.0
        # 隐含 ROE 同比（PB/PE），用于"盈利改善"过滤
        roe_chg = None
        hp = os.path.join(SWD, code + ".csv")
        if os.path.exists(hp):
            hrows = []
            with open(hp, encoding="utf-8") as hf:
                hrows = list(csv.DictReader(hf))
            if len(hrows) > 245:
                def _roe(r):
                    a, b = fnum(r.get("pb_lf")), fnum(r.get("pe_ttm"))
                    return a / b if (a and b and b > 0) else None
                r0, r1 = _roe(hrows[-1]), _roe(hrows[-245])
                if r0 is not None and r1:
                    roe_chg = r0 / r1 - 1.0
        pb, div = v.get("pb_lf"), v.get("dividend_yield_ttm")
        zone, capped, score = pick_zone(score, params, pb, div)
        items.append({
            "kind": "industry", "code": code, "name": v["name"], "group": "cn_industry",
            "family": code, "market": "CN", "date": v.get("date") or target_date,
            "pe": v.get("pe_ttm"), "pb": pb, "div": div,
            "pe_pct": None if v.get("pe_pct_5y") is None else round(v["pe_pct_5y"] * 100, 1),
            "pb_pct": None if pb_pct is None else round(pb_pct * 100, 1),
            "ps_pct": None if ps_pct is None else round(ps_pct * 100, 1),
            "div_pct": None if v.get("div_pct_5y") is None else round(v["div_pct_5y"] * 100, 1),
            "score": round(score, 1), "zone": zone["name"], "action": zone["action"],
            "mult": zone["mult"], "caps": capped or "",
            "constituents": v.get("constituent_count"),
            "fund": (fmap.get(code) or {}).get("primary", {}).get("fund_code", "") if fmap.get(code, {}).get("primary") else "",
            "fund_name": (fmap.get(code) or {}).get("primary", {}).get("fund_name", "") if fmap.get(code, {}).get("primary") else "",
            "match_level": (fmap.get(code) or {}).get("primary", {}).get("match_level", "none") if fmap.get(code, {}).get("primary") else "none",
            "fund_tracking_index": (fmap.get(code) or {}).get("primary", {}).get("tracking_index", "") if fmap.get(code, {}).get("primary") else "",
            "fund_venue": (fmap.get(code) or {}).get("primary", {}).get("venue", "") if fmap.get(code, {}).get("primary") else "",
            "roe_chg": None if roe_chg is None else round(roe_chg, 4),
        })
    return items, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    params = load_index_params()
    with open(POOL, encoding="utf-8") as f:
        uni = json.load(f)

    broad, miss_b = build_broad(uni, params, args.date)
    ind, miss_i = build_industry(params, args.date)
    items = broad + ind
    if not items:
        print("无可用信号")
        return 1
    as_of = max((i["date"] for i in items if i.get("date")), default=args.date)

    print("=" * 80)
    print("宽基 %d 个    基准日 %s" % (len(broad), as_of))
    print("=" * 80)
    print("%-14s %-8s %7s %7s %6s %6s %6s  %s" % ("名称", "市场", "PE", "PB", "PE%", "PB%", "综合", "档位/动作"))
    for it in sorted(broad, key=lambda x: x["score"]):
        if it.get("metric") == "价格分位":
            print("%-14s %-8s %7s %7s %6s %6s %6s  %s|%s %.1fx  [价格分位]" % (
                it["name"][:12], it["market"], "-", "-", "-", "-",
                "%.0f" % it["score"], it["zone"], it["action"], it["mult"]))
            continue
        print("%-14s %-8s %7s %7s %6s %6s %6s  %s|%s %.1fx%s" % (
            it["name"][:12], it["market"],
            "-" if it["pe"] is None else "%.1f" % it["pe"],
            "-" if it["pb"] is None else "%.2f" % it["pb"],
            "-" if it["pe_pct"] is None else "%.0f" % it["pe_pct"],
            "-" if it["pb_pct"] is None else "%.0f" % it["pb_pct"],
            "%.0f" % it["score"], it["zone"], it["action"], it["mult"],
            ("  << " + it["caps"]) if it["caps"] else ""))

    print("\n" + "=" * 80)
    print("申万二级行业 %d 个  —— 最便宜的 20 个" % len(ind))
    print("=" * 80)
    print("%-16s %7s %7s %7s %6s  %s" % ("行业", "PB", "PB%", "PS%", "综合", "档位"))
    for it in sorted(ind, key=lambda x: x["score"])[:20]:
        print("%-16s %7s %6s %6s %6s  %s|%.1fx" % (
            it["name"][:14],
            "-" if it["pb"] is None else "%.2f" % it["pb"],
            "-" if it["pb_pct"] is None else "%.1f" % it["pb_pct"],
            "-" if it["ps_pct"] is None else "%.1f" % it["ps_pct"],
            "%.0f" % it["score"], it["zone"], it["mult"]))

    print("\n最贵的 10 个：")
    for it in sorted(ind, key=lambda x: -x["score"])[:10]:
        print("  %-16s 综合%4.0f  PB分位%5.1f  PS分位%5.1f  %s|%.1fx" % (
            it["name"][:14], it["score"],
            -1 if it["pb_pct"] is None else it["pb_pct"],
            -1 if it["ps_pct"] is None else it["ps_pct"],
            it["zone"], it["mult"]))

    if miss_b:
        print("\n[宽基缺数据]")
        for code, name, mk, why in miss_b:
            print("  %-14s %-6s %s" % (name, mk, why))

    payload = {"as_of": as_of, "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "params_version": params.get("version"),
               "unit_amount_cny": params["execute"]["unit_amount_cny"],
               "count": {"broad": len(broad), "industry": len(ind)},
               "items": items}
    out = args.json or os.path.join(ROOT, "state", "index_signal.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print("\n写入 %s" % out)
    # 归档快照：周度复盘要用"当时的判断"对比事后表现
    hist = os.path.join(ROOT, "state", "signal_history")
    os.makedirs(hist, exist_ok=True)
    with open(os.path.join(hist, "%s.json" % as_of), "w", encoding="utf-8") as f:
        json.dump({"as_of": as_of, "items": [
            {"code": i["code"], "name": i["name"], "kind": i["kind"],
             "score": i["score"], "action": i["action"], "mult": i["mult"]}
            for i in items]}, f, ensure_ascii=False)
    print("归档 state/signal_history/%s.json" % as_of)
    return 0


if __name__ == "__main__":
    sys.exit(main())
