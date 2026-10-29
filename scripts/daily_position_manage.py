#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""每日仓位管理（v3.3）

两个动作：
  concentrate  —— 牛市集中：regime=bull 时只保留质量最高的前 N 只，超配按 qs 升序卖出
  topup        —— 每日补仓：把未止盈的持仓补到 cap/持仓数（受单票/行业上限约束）

为什么必须每日做（回测证据）：
  按周补仓完全无效——补了 435 次，仓位 52.4% vs 52.5% 纹丝不动，收益从 +183% 腰斩到 +88%。
  因为钱的总量固定：补了老票就少买新票。只有日频才能补上周中止损/止盈掉下去的仓位。

用法：
  python scripts/daily_position_manage.py concentrate --date 20261029 [--apply]
  python scripts/daily_position_manage.py topup       --date 20261029 [--apply]

默认 dry-run（只打印计划），加 --apply 才写入 state/。
"""
import argparse
import csv
import glob
import json
import os
import sys
from datetime import datetime

ROOT = os.environ.get("AGENT_ROOT") or r"E:\cashfree\agent"
_REPO = r"E:\cashfree\agent"
STATE = os.path.join(ROOT, "state")
WH = os.path.join(ROOT, "data", "warehouse")
if not os.path.isdir(WH):
    WH = os.path.join(_REPO, "data", "warehouse")
KN = os.path.join(ROOT, "knowledge")
if not os.path.isdir(KN):          # 沙箱只隔离 state，knowledge 回落到正式仓库（只读）
    KN = os.path.join(_REPO, "knowledge")

VERSION = open(os.path.join(KN, "params_current.txt"), encoding="utf-8").read().strip()
P = json.load(open(os.path.join(KN, "params_%s.json" % VERSION), encoding="utf-8"))
LIM = P["position_limits"]
EQ = P.get("execution_queue") or {}
CONC = LIM.get("bull_concentration") or {}
TOPUP = EQ.get("topup") or {}

POSITIONS = os.path.join(STATE, "positions.json")
ORDERS = os.path.join(STATE, "orders.json")
REGIME_PREV = os.path.join(STATE, "regime_prev.json")
REGIME = os.path.join(STATE, "regime.json")
WATCHLIST = os.path.join(STATE, "watchlist.json")
TRADES = os.path.join(STATE, "trades.jsonl")


def fnum(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def read_csv(p):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load(p, default=None):
    if not os.path.exists(p):
        return default
    return json.load(open(p, encoding="utf-8"))


def close_of(code, date):
    """取 <= date 的最后一根收盘价"""
    rows = []
    for fp in sorted(glob.glob(os.path.join(WH, "daily", "*.csv"))):
        d = os.path.basename(fp)[:-4]
        if d > date:
            continue
        for r in read_csv(fp):
            if r["ts_code"] == code:
                rows.append((d, fnum(r.get("close"))))
    rows.sort()
    return rows[-1][1] if rows else None


def industry_map():
    p = os.path.join(WH, "scores_full.csv")
    if not os.path.exists(p):
        return {}
    return {r["ts_code"]: r.get("industry", "未知") for r in read_csv(p)}


def qs_map():
    wl = load(WATCHLIST, {}) or {}
    return {i["code"]: i.get("quality_score") for i in (wl.get("items") or [])}


def inflight_pct(orders):
    """未成交档位占用的仓位额度（%）"""
    tot = 0.0
    for o in (orders.get("orders") or []):
        if o.get("side") != "buy" or o.get("status") not in ("planned", "partially_filled"):
            continue
        tw = float(o.get("target_weight_pct") or 0)
        for t in (o.get("tranches") or []):
            if t.get("status") != "filled" and not t.get("cancelled"):
                tot += tw * float(t.get("pct") or 0) / 100.0
    return tot


def cap_of():
    r = load(REGIME_PREV) or load(REGIME) or {}
    c = r.get("position_cap_pct")
    if isinstance(c, (int, float)) and 0 < float(c) <= 100:
        return float(c), r.get("regime", "neutral")
    return float(P["regime"]["base_position_pct"].get(r.get("regime", "neutral"), 50)), r.get("regime", "neutral")


def cmd_concentrate(ap):
    pos = load(POSITIONS, {})
    if not pos or not (pos.get("holdings") or []):
        print("无持仓，跳过集中")
        return
    if not CONC.get("enabled"):
        print("bull_concentration 未启用（params）")
        return
    cap, regime = cap_of()
    if regime != "bull":
        print("regime=%s，不触发集中（仅 bull）" % regime)
        return
    n_max = int(CONC.get("bull_max_holdings", 6))
    hs = pos["holdings"]
    if len(hs) <= n_max:
        print("持仓 %d 只 ≤ 上限 %d，无需集中" % (len(hs), n_max))
        return
    qs = qs_map()
    order = sorted(hs, key=lambda h: qs.get(h.get("code")) or 0)
    drop = order[: len(hs) - n_max]
    print("【牛市集中】regime=bull，持仓 %d → %d 只，卖出 %d 只：" % (len(hs), n_max, len(drop)))
    total = float(pos.get("total_asset_cny") or 0)
    for h in drop:
        px = close_of(h["code"], ap.date) or h.get("cost")
        amt = h.get("shares", 0) * px
        pnl = (px / h["cost"] - 1) * 100 if h.get("cost") else 0
        print("  卖出 %-8s %-6s %6d股 @%.2f  回收 %.0f  盈亏 %+.1f%%（qs=%s）"
              % (h.get("name"), h.get("code"), h.get("shares", 0), px, amt, pnl, qs.get(h.get("code"))))
    if not ap.apply:
        print("\n[dry-run] 加 --apply 才会写 positions.json / trades.jsonl")
        return
    drop_codes = {h["code"] for h in drop}
    cash = float(pos.get("cash_cny") or 0)
    for h in drop:
        px = close_of(h["code"], ap.date) or h.get("cost")
        cash += h.get("shares", 0) * px
        with open(TRADES, "a", encoding="utf-8") as f:
            f.write(json.dumps({"date": ap.date, "side": "sell", "code": h["code"], "name": h.get("name"),
                                "price": round(px, 2), "shares": h.get("shares", 0),
                                "amount": round(h.get("shares", 0) * px),
                                "pnl_pct": round((px / h["cost"] - 1) * 100, 2) if h.get("cost") else 0,
                                "why": "concentration"}, ensure_ascii=False) + "\n")
    pos["holdings"] = [h for h in hs if h["code"] not in drop_codes]
    pos["cash_cny"] = round(cash, 2)
    json.dump(pos, open(POSITIONS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("[apply] 已卖出 %d 只，positions.json 更新，trades.jsonl 追加" % len(drop))


def cmd_topup(ap):
    pos = load(POSITIONS, {})
    hs = pos.get("holdings") or []
    if not hs:
        print("无持仓，跳过补仓")
        return
    if not TOPUP.get("enabled"):
        print("topup 未启用（params）")
        return
    cap, regime = cap_of()
    total = float(pos.get("total_asset_cny") or 0)
    if total <= 0:
        print("total_asset 异常")
        return
    used = sum(float(h.get("market_value_cny") or 0) for h in hs) / total * 100
    infl = inflight_pct(load(ORDERS, {"orders": []}))
    room = max(cap - used - infl, 0)
    min_gap = float(TOPUP.get("min_gap_pp", 1.5))
    print("【每日补仓】regime=%s cap=%.1f%% 已用=%.1f%% 在途=%.1f%% 可用=%.1f%%"
          % (regime, cap, used, infl, room))
    if room < min_gap:
        print("可用缺口 %.2fpp < 最小补仓缺口 %.2fpp，本轮不补" % (room, min_gap))
        return
    target = cap / len(hs)
    qs = qs_map()
    ind = industry_map()
    max_s = float(LIM.get("max_single_weight_pct", 15))
    max_sec = float(LIM.get("max_sector_weight_pct", 30))
    sec_used = {}
    for h in hs:
        s = ind.get(h.get("code"), "未知")
        sec_used[s] = sec_used.get(s, 0.0) + float(h.get("market_value_cny") or 0) / total * 100

    plans = []
    left = room
    for h in sorted(hs, key=lambda x: -(qs.get(x.get("code")) or 0)):
        if left < min_gap:
            break
        if h.get("take_profit_moved"):
            continue                      # 已止盈减仓的票不补
        cur = float(h.get("market_value_cny") or 0) / total * 100
        s = ind.get(h.get("code"), "未知")
        gap = min(target - cur, max_s - cur, left, max_sec - sec_used.get(s, 0.0))
        if gap < min_gap:
            continue
        plans.append((h, gap, s))
        left -= gap
        sec_used[s] = sec_used.get(s, 0.0) + gap
    if not plans:
        print("无满足条件的补仓标的（可能都已止盈/触顶/行业受限）")
        return
    print("计划补仓 %d 只，合计 %.2fpp，剩余可用 %.2fpp：" % (len(plans), room - left, left))
    for h, gap, s in plans:
        px = close_of(h["code"], ap.date) or h.get("cost")
        print("  买入 %-8s %-6s +%.2fpp → 目标 %.2f%%  ref=%.2f  行业=%s"
              % (h.get("name"), h.get("code"), gap, target, px, s))
    if not ap.apply:
        print("\n[dry-run] 加 --apply 才会写入 orders.json（status=planned，次日开盘成交）")
        return
    doc = load(ORDERS, {"date": ap.date, "orders": []})
    seq = 1
    for o in (doc.get("orders") or []):
        tail = str(o.get("id") or "").rsplit("-", 1)[-1]
        if tail.startswith("A") and tail[1:].isdigit():
            seq = max(seq, int(tail[1:]) + 1)
    for h, gap, s in plans:
        px = close_of(h["code"], ap.date) or h.get("cost")
        doc["orders"].append({
            "id": "ORD-%s-A%03d" % (ap.date, seq),
            "side": "buy", "code": h["code"], "name": h.get("name"), "industry": s,
            "target_weight_pct": round(gap, 2),
            "weight_basis": "pct_of_total_assets",
            "amount_note": "补仓单：金额与股数由持仓管家执行时按实际总资产计算（v3.3 topup）",
            "ref_price": round(px, 2),
            "tranches": [{"seq": 1, "pct": 100, "type": "market_open", "limit_price": None,
                          "trigger_pct": None, "price_zone": None, "status": "pending",
                          "note": "补仓按次日开盘竞价市价买入，成交价=当日开盘价"}],
            "fill_logic": "market_open_topup（补仓不看回调，直接市价补到目标权重）",
            "stop_loss": round(float(h.get("cost")) * (1 - P["risk"]["single_stop_loss_pct"] / 100.0), 2) if h.get("cost") else None,
            "take_profit": round(float(h.get("cost")) * (1 + P["risk"]["single_take_profit_pct"] / 100.0), 2) if h.get("cost") else None,
            "stop_loss_basis": "actual_fill_price",
            "stop_loss_recalc_required": True,
            "stop_loss_formula": "补仓成交后按新加权成本重算",
            "rationale": "daily_topup：把未止盈持仓补到 cap/持仓数",
            "expires_after_trading_days": int(EQ.get("order_pending_trading_days", 10)),
            "status": "planned",
            "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        })
        seq += 1
    doc["params_version"] = VERSION
    json.dump(doc, open(ORDERS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("[apply] 已写入 %d 张补仓单（planned）" % len(plans))


def main():
    global ROOT, STATE, POSITIONS, ORDERS, REGIME_PREV, REGIME, WATCHLIST, TRADES, WH
    ap_ = argparse.ArgumentParser(description="每日仓位管理（牛市集中 / 每日补仓）")
    ap_.add_argument("cmd", choices=["concentrate", "topup"])
    ap_.add_argument("--date", required=True, help="数据基准日 YYYYMMDD")
    ap_.add_argument("--apply", action="store_true", help="实际写入 state/（默认 dry-run）")
    ap_.add_argument("--root", default=ROOT)
    a = ap_.parse_args()
    ROOT = a.root
    STATE = os.path.join(ROOT, "state")
    WH = os.path.join(ROOT, "data", "warehouse")
    if not os.path.isdir(WH):
        WH = os.path.join(_REPO, "data", "warehouse")
    POSITIONS = os.path.join(STATE, "positions.json")
    ORDERS = os.path.join(STATE, "orders.json")
    REGIME_PREV = os.path.join(STATE, "regime_prev.json")
    REGIME = os.path.join(STATE, "regime.json")
    WATCHLIST = os.path.join(STATE, "watchlist.json")
    TRADES = os.path.join(STATE, "trades.jsonl")
    print("params=%s date=%s mode=%s" % (VERSION, a.date, "apply" if a.apply else "dry-run"))
    if a.cmd == "concentrate":
        cmd_concentrate(a)
    else:
        cmd_topup(a)


if __name__ == "__main__":
    sys.exit(main())
