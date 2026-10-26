# -*- coding: utf-8 -*-
"""建仓经理（正式版，params v1.7 规则）
watchlist → 建仓计划 → state/orders.json（status=planned，由持仓管家执行）

核心纪律（params v1.7）：
  1. 持仓数 N ∈ [min_holdings, max_holdings]，空仓时补足到默认 10
  2. 权重质量归一化 weight_i = base_pct × qs_i / Σqs，clamp[min_single, max_single] 后迭代归一
  3. 单行业 ≤ max_sector_weight_pct
  4. 买点 close_relative_ladder：ref=基准日收盘，tr1 触发 -1%，tr2 触发 -4%，-12% 以下不接
  5. 只给权重百分比，不给金额（R-011，金额由持仓管家按执行时实际总资产计算）
  6. 每张单必须带 stop_loss 与 take_profit（R-003）；**两者均锚定实际成交加权成本，ref 值仅作未成交预览**
     （v2.1：旧版锚 ref 且 min(low20×0.98) 会让次档成交即落在止损线下方，已修）
  7. 订单挂 10 个交易日未成交即 expired（R-006）

写入边界：本脚本只写 buy 单，不删改持仓管家写入的 sell 单。
"""
import csv
import glob
import json
import os
from datetime import datetime

ROOT = r"E:\cashfree\agent"
WH = os.path.join(ROOT, "data", "warehouse")
KN = os.path.join(ROOT, "knowledge")
WATCHLIST = os.environ.get("WATCHLIST_IN") or os.path.join(ROOT, "state", "watchlist.json")
REGIME = os.path.join(ROOT, "state", "regime.json")
POSITIONS = os.path.join(ROOT, "state", "positions.json")
ORDERS = os.path.join(ROOT, "state", "orders.json")
SCORES = os.path.join(WH, "scores_full.csv")

VERSION = open(os.path.join(KN, "params_current.txt"), encoding="utf-8").read().strip()
PARAMS = json.load(open(os.path.join(KN, f"params_{VERSION}.json"), encoding="utf-8"))
LIM = PARAMS["position_limits"]
RISK = PARAMS["risk"]
PZ = PARAMS["price_zone_rule"]
WA = PARAMS["weight_allocation"]
REG = PARAMS.get("regime", {})


def read_csv(p):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def fnum(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


wl = json.load(open(WATCHLIST, encoding="utf-8"))
regime = json.load(open(REGIME, encoding="utf-8"))
positions = json.load(open(POSITIONS, encoding="utf-8"))
scores = {r["ts_code"]: r for r in read_csv(SCORES)}
base_date = wl["date"]

regime_name = regime.get("regime", "neutral")
severity = "light" if regime_name == "bear" else None
base_pct = float(PARAMS["regime_base_position_pct"].get(regime_name, 50))
# v2.2：市场分析师输出 position_cap_pct，已把「市场拥挤度」覆盖折扣算进去，优先采信；
# 缺失（旧版 regime.json）或越界时回退 params 的 regime_base_position_pct。
_cap = regime.get("position_cap_pct")
if isinstance(_cap, (int, float)) and 0 < float(_cap) <= 100:
    if abs(float(_cap) - base_pct) > 0.01:
        print(f"position_cap_pct={_cap}% (含拥挤度覆盖) 覆盖 base_position={base_pct}%")
    base_pct = float(_cap)

# 空头/重度熊市：禁止新建仓（R-001）
if regime_name == "bear":
    heavy = float(REG.get("bear_heavy_max_score", -8))
    # regime.json 未给总分时无法分级 → 保守按 light（只禁买，不降仓）
    print(f"regime=bear -> 按 R-001 禁止新建仓（severity={severity}），本轮 0 单")

print(f"params={VERSION} regime={regime_name} base_position={base_pct}% base_date={base_date}")

# ---------- 现有持仓 ----------
holdings = positions.get("holdings") or []
held = {h.get("code") for h in holdings}
H = len(holdings)
print(f"current holdings={H} ({sorted(held)})")

if regime_name == "bear":
    orders_out = {"date": base_date, "regime": regime_name, "orders": [],
                  "notes": {"reason": "R-001 bear 禁止新建仓", "params_version": VERSION}}
    json.dump(orders_out, open(ORDERS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"wrote {ORDERS} (0 orders)")
    raise SystemExit

# 满仓保护：H>=max 输出 0 单；8<=H<12 只补足到 max；H<8 补到默认 10
max_h, min_h = int(LIM["max_holdings"]), int(LIM["min_holdings"])
default_n = 10
if H >= max_h:
    print(f"H={H} >= max_holdings={max_h} → 满仓保护，本轮 0 单（换仓由持仓管家负责）")
    orders_out = {"date": base_date, "regime": regime_name, "orders": [],
                  "notes": {"reason": f"满仓保护 H={H}>={max_h}", "params_version": VERSION}}
    json.dump(orders_out, open(ORDERS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"wrote {ORDERS} (0 orders)")
    raise SystemExit

target_n = default_n if H < min_h else max_h
need = target_n - H

# ---------- 候选：buy_watch 且未持有，按 quality_score 降序 ----------
cands = [i for i in wl["items"] if i["verdict"] == "buy_watch" and i["code"] not in held]
cands.sort(key=lambda x: -x["quality_score"])
if not cands:
    print("no buy_watch candidates")
    raise SystemExit

# ---------- 日线：ref = 基准日收盘，20 日高低（price zone 用 close_relative，止损用 20 日低点）----------
daily = {}
for p in sorted(glob.glob(os.path.join(WH, "daily", "*.csv"))):
    d = os.path.basename(p)[:-4]
    for r in read_csv(p):
        daily.setdefault(r["ts_code"], []).append(
            (d, fnum(r["close"]), fnum(r["high"]), fnum(r["low"])))
for c in daily:
    daily[c].sort()


def alloc(qs_list, base):
    """质量归一化权重 + clamp[min,max] + 迭代归一到 base 总和；不可行返回 None"""
    lo, hi = float(LIM["min_single_weight_pct"]), float(LIM["max_single_weight_pct"])
    n = len(qs_list)
    if n == 0:
        return None
    if lo * n > base + 1e-9:   # 最小权重下限已超过可用仓位
        return None
    if hi * n < base - 1e-9:   # 只数太少，顶格也吃不满基础仓位
        return None
    w = [base * q / sum(qs_list) for q in qs_list]
    fixed = [None] * n
    for _ in range(50):
        free = [i for i in range(n) if fixed[i] is None]
        if not free:
            break
        used = sum(v for v in fixed if v is not None)
        remain = base - used
        tot = sum(w[i] for i in free)
        if tot <= 0:
            break
        for i in free:
            w[i] = remain * w[i] / tot
        changed = False
        for i in free:
            if w[i] > hi:
                w[i], fixed[i], changed = hi, hi, True
            elif w[i] < lo:
                w[i], fixed[i], changed = lo, lo, True
        if not changed:
            break
    final = w if any(v is None for v in fixed) else fixed
    if abs(sum(final) - base) > 0.01:
        return None
    return final


# ---------- 选股：按 quality 降序 + 行业上限（用 base/N 粗估）凑够 need 只 ----------
max_sec = float(LIM["max_sector_weight_pct"])
approx = base_pct / need
selected, sector_approx = [], {}
for i in cands:
    if len(selected) >= need:
        break
    sec = (scores.get(i["code"]) or {}).get("industry", "未知")
    if sector_approx.get(sec, 0) + approx > max_sec + 1e-9:
        print(f"  skip {i['name']} ({sec}) 行业上限（粗估）")
        continue
    selected.append(i)
    sector_approx[sec] = sector_approx.get(sec, 0) + approx

# 用真实权重复核行业上限：超限则剔除该行业最低分标的并补入次优
while True:
    w_try = alloc([x["quality_score"] for x in selected], base_pct)
    if w_try is not None:
        sec_real = {}
        for x, wv in zip(selected, w_try):
            s = (scores.get(x["code"]) or {}).get("industry", "未知")
            sec_real[s] = sec_real.get(s, 0) + wv
        over = [s for s, v in sec_real.items() if v > max_sec + 1e-9]
        if not over:
            break
        drop_sec = over[0]
        drop = min([x for x in selected if (scores.get(x["code"]) or {}).get("industry") == drop_sec],
                   key=lambda x: x["quality_score"])
        print(f"  drop {drop['name']} ({drop_sec}) 真实行业权重超限")
        selected = [x for x in selected if x["code"] != drop["code"]]
        for i in cands:
            if len(selected) >= need:
                break
            if i["code"] in {x["code"] for x in selected}:
                continue
            selected.append(i)
        continue
    if len(selected) <= LIM["min_holdings"]:
        raise RuntimeError(f"权重分配失败且无可再减标的（当前 {len(selected)} 只）")
    # 权重不可行：剔除末位继续尝试
    selected = selected[:-1]

if len(selected) < need:
    print(f"  警告：仅补到 {len(selected)} 只（目标 {need}），候选不足/行业受限")

w_final = alloc([x["quality_score"] for x in selected], base_pct)
if w_final is None:
    raise RuntimeError("权重分配失败")

sector_total = {}
for x, wv in zip(selected, w_final):
    s = (scores.get(x["code"]) or {}).get("industry", "未知")
    sector_total[s] = sector_total.get(s, 0) + wv

# ---------- 生成订单 ----------
# 重建 orders.json 时必须保留历史已成交买单，且新单序号接续，否则会：
#   ① 抹掉成交记录（trades.jsonl 里的 order_id 指向已不存在的单）
#   ② 新单复用旧 ID（ORD-20261023-002 既是已成交的中国动力又是新计划）
#   2026-10-26 曾因此错位，手工 fix_orders.py 才救回来，这里从根上修。
t1, t2 = PZ["tranche1"], PZ["tranche2"]
guard = float(PZ["guard_drop_pct"]) / 100.0
hist_filled, next_seq = [], 1
if os.path.exists(ORDERS):
    try:
        _old = json.load(open(ORDERS, encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _old = {}
    for _o in (_old.get("orders") or []):
        _tail = str(_o.get("id") or "").rsplit("-", 1)[-1]
        if _tail.isdigit():
            next_seq = max(next_seq, int(_tail) + 1)
        if _o.get("side") == "buy" and _o.get("status") == "filled":
            # 已成交单的止损止盈同样按实际成交价对齐（v2.1），与 positions.json 口径保持一致
            _fp = _o.get("fill_price")
            if isinstance(_fp, (int, float)) and _fp > 0:
                _o["stop_loss"] = round(_fp * (1 - RISK["single_stop_loss_pct"] / 100.0), 2)
                _o["take_profit"] = round(_fp * (1 + RISK["single_take_profit_pct"] / 100.0), 2)
                _o["stop_loss_basis"] = "actual_fill_price"
                _o["stop_loss_formula"] = f"成交价 {_fp} × (1-{RISK['single_stop_loss_pct']:g}%)"
            hist_filled.append(_o)
if hist_filled:
    print(f"保留历史已成交买单 {len(hist_filled)} 张，新单起始序号 {next_seq:03d}")

out_orders = list(hist_filled)
for idx, (i, w) in enumerate(zip(selected, w_final), next_seq):
    code = i["code"]
    sec = (scores.get(code) or {}).get("industry", "未知")
    bars = daily.get(code, [])
    if not bars:
        print(f"  skip {code}: no daily bars")
        continue
    ref = bars[-1][1]
    if not ref:
        continue
    w20 = bars[-20:]
    lows20 = [b[3] for b in w20 if b[3] is not None]
    low20 = min(lows20) if lows20 else ref

    def zone(offsets):
        return [round(ref * (1 + offsets[0] / 100.0), 2), round(ref * (1 + offsets[1] / 100.0), 2)]

    # ---------- 止损/止盈：锚定「实际成交成本」，ref 只做未成交前的预览（v2.1 修正） ----------
    # 旧写法 stop = min(ref×0.92, low20×0.98) 有两个致命问题：
    #   ① 锚 ref 而非成交价：次档下沿到 -12%，在 -8%~-12% 区间成交时买入瞬间已在止损线下方（10/10 张单全中）
    #   ② 用 min 取的是更宽松的一条，与规则文案「取更严者」语义相反，20 日低会把止损往下拽
    # 修正后：止损/止盈都只认成交加权成本；20 日低退化为风险提示字段，不参与计算。
    sl_pct = RISK["single_stop_loss_pct"] / 100.0
    tp_pct = RISK["single_take_profit_pct"] / 100.0
    tr2_floor = zone(t2["zone_offset_pct"])[0]
    stop_preview = round(ref * (1 - sl_pct), 2)
    tp_preview = round(ref * (1 + tp_pct), 2)
    stop_at_floor = round(tr2_floor * (1 - sl_pct), 2)

    out_orders.append({
        "id": f"ORD-{base_date}-{idx:03d}",
        "side": "buy",
        "code": code,
        "name": i["name"],
        "industry": sec,
        "target_weight_pct": round(w, 2),
        "weight_basis": "pct_of_total_assets",
        "amount_note": "不预置金额，由持仓管家按执行时总资产计算（R-011）",
        "ref_price": round(ref, 2),
        "tranches": [
            {"pct": int(t1["weight_share"] * 100), "trigger_pct": t1["offset_pct"],
             "price_zone": zone(t1["zone_offset_pct"]), "status": "pending"},
            {"pct": int(t2["weight_share"] * 100), "trigger_pct": t2["offset_pct"],
             "price_zone": zone(t2["zone_offset_pct"]), "status": "pending"},
        ],
        "fill_logic": PZ["fill_logic"],
        "guard_price": round(ref * (1 + guard), 2),
        "stop_loss": stop_preview,
        "take_profit": tp_preview,
        "stop_loss_basis": "actual_fill_price",
        "stop_loss_formula": f"成交加权成本 × (1-{RISK['single_stop_loss_pct']:g}%)；成交回写时必须重算，禁止沿用上面 stop_loss 预览值（R-011）",
        "stop_loss_recalc_required": True,
        "stop_loss_if_tranche2_floor_filled": stop_at_floor,
        "take_profit_basis": "actual_fill_price",
        "take_profit_formula": f"成交加权成本 × (1+{RISK['single_take_profit_pct']:g}%)",
        "twenty_day_low": round(low20, 2),
        "twenty_day_low_note": "风险提示字段，不参与止损计算（v2.1：旧版 min(low20×0.98) 会反向放宽止损）",
        "quality_score": i["quality_score"],
        "rationale": i["thesis"],
        "risks": i["risks"],
        "expires_after_trading_days": 10,
        "expire_rule": "R-006 挂 10 个交易日未成交即 expired，禁止上移 price_zone",
        "status": "planned",
        "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    })

total_w = sum(o["target_weight_pct"] for o in out_orders if o.get("status") == "planned")
orders_doc = {
    "date": base_date,
    "mode": "production",
    "params_version": VERSION,
    "regime": regime_name,
    "base_position_pct": base_pct,
    "holdings_before": H,
    "target_holdings": target_n,
    "planned_new_orders": len([o for o in out_orders if o.get("status") == "planned"]),
    "filled_orders_carried": len(hist_filled),
    "planned_total_weight_pct": round(total_w, 2),
    "cash_reserve_pct": round(100 - total_w, 2),
    "sector_weights": {k: round(v, 2) for k, v in sector_total.items()},
    "orders": out_orders,
    "notes": {
        "weight_formula": WA["formula"],
        "price_zone_rule": f"close_relative_ladder: ref={base_date} 收盘价，tr1={t1['offset_pct']}%，tr2={t2['offset_pct']}%，保护线 {PZ['guard_drop_pct']}%",
        "stop_loss_rule": "实际成交加权成本 × (1-8%)；未成交前 orders.stop_loss 只是 ref 预览值，成交回写必须重算（v2.1 修复「次档买了就在止损线下方」）",
        "take_profit_rule": "实际成交加权成本 × (1+20%)",
        "hard_rules": "R-003 必带止损止盈 / R-006 10 日过期 / R-011 不给金额 / R-012 止损锚定成交成本",
        "writer": "position_builder 只写 buy 单，不删改持仓管家的 sell 单",
    },
}
with open(ORDERS, "w", encoding="utf-8") as f:
    json.dump(orders_doc, f, ensure_ascii=False, indent=2)

print(f"\norders={len(out_orders)} total_weight={total_w:.2f}% cash={100 - total_w:.2f}%")
for o in out_orders:
    t = o["tranches"]
    print(f"  {o['name']:<8} {o['code']} w={o['target_weight_pct']:.2f}% ref={o['ref_price']} "
          f"tr1={t[0]['price_zone']} tr2={t[1]['price_zone']} SL={o['stop_loss']} TP={o['take_profit']}")
print(f"\nsector: {orders_doc['sector_weights']}")
print(f"wrote {ORDERS}")
