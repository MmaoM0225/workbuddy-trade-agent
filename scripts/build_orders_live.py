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
import sys
from datetime import datetime

ROOT = os.environ.get("AGENT_ROOT") or r"E:\cashfree\agent"   # 彩排时指向沙箱
_REPO = r"E:\cashfree\agent"
# 沙箱只隔离 state：warehouse / knowledge 缺失时回落到正式仓库（只读）
WH = os.path.join(ROOT, "data", "warehouse")
if not os.path.isdir(WH):
    WH = os.path.join(_REPO, "data", "warehouse")
KN = os.path.join(ROOT, "knowledge")
if not os.path.isdir(KN):
    KN = os.path.join(_REPO, "knowledge")
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
severity = regime.get("severity") or ("light" if regime_name == "bear" else None)
# v3.0：regime 基础仓位唯一真源 = params.regime.base_position_pct（旧镜像段 regime_base_position_pct 已删除）
base_pct = float((REG.get("base_position_pct") or {}).get(regime_name, 50))
# v2.2：市场分析师输出 position_cap_pct，已把「市场拥挤度」覆盖折扣算进去，优先采信；
# 缺失（旧版 regime.json）或越界时回退 params.regime.base_position_pct。
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

# ---------- 冷却期过滤（R-021，2026-10-28）----------
# 止损/止盈清仓后 N 个交易日内不得重新建仓：否则只要 watchlist 里还是 buy_watch，
# 下一轮就会把刚割掉的票原价买回来，止损白做还多付两趟成本。
COOLDOWN_TD = int(os.environ.get("COOLDOWN_TRADING_DAYS",
                                 (PARAMS.get("execution_queue") or {}).get("cooldown_trading_days", 20)))
cooldown = {}
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from order_queue import Ctx as _QCtx, recently_exited as _recently_exited
    cooldown = {k: v["days_since_exit"]
                for k, v in _recently_exited(_QCtx(ROOT, WH), base_date, COOLDOWN_TD).items()}
except Exception as _e:      # 冷却期算不出来时宁可本轮停手，也不放行可疑仓位
    print(f"!! 冷却期过滤不可用（{_e}），为安全起见本轮 0 单")
    json.dump({"date": base_date, "regime": regime_name, "target_holdings": H, "orders": [],
               "notes": {"reason": f"cooldown_filter_unavailable: {_e}", "params_version": VERSION}},
              open(ORDERS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    raise SystemExit
if cooldown:
    print(f"cooldown 过滤 {len(cooldown)} 只（退出未满 {COOLDOWN_TD} 交易日）: "
          f"{sorted(cooldown.items())}")

if regime_name == "bear":
    # 保留历史已成交买单，避免 trades.jsonl 的 order_id 悬空（R-018）
    _hb = json.load(open(ORDERS, encoding="utf-8")).get("orders") if os.path.exists(ORDERS) else []
    _kept, _dropped, _cc = [], 0, 0
    for _o in (_hb or []):
        if _o.get("side") == "buy" and _o.get("status") == "filled":
            _kept.append(_o)
        elif _o.get("side") == "buy" and _o.get("status") in ("planned", "partially_filled"):
            if _o.get("code") in cooldown:
                # R-022：标的已清仓进冷却期 → 未成交档位直接作废
                _o["status"] = "cancelled"
                _o["cancel_reason"] = "exit_cooldown_cancelled"
                _cc += 1
                print(f"  R-022 作废 {_o['id']} {_o.get('name')}：标的已清仓（冷却期），未成交档位作废")
                continue
            _dropped += 1      # bear 禁新建仓，在途单处置（冻结/作废）待用户拍板，本轮不写入 orders.json
    if _dropped or _cc:
        # 防丢失：被本轮丢弃的在途单先归档，巡检可追溯（禁止静默蒸发）
        _arch = os.path.join(ROOT, "state", f"orders_dropped_{base_date}.json")
        json.dump({"date": base_date, "reason": "bear_regime_rebuild",
                   "dropped_planned": _dropped, "cancelled_cooldown": _cc,
                   "orders": [_o for _o in (_hb or []) if _o.get("side") == "buy"
                              and _o.get("status") in ("planned", "partially_filled")]},
                  open(_arch, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"  在途单处置：作废 {_cc} 张（冷却期），另有 {_dropped} 张未写入，已归档 {_arch}")
    orders_out = {"date": base_date, "regime": regime_name,
                  "target_holdings": H, "orders": _kept,
                  "filled_orders_carried": len(_kept),
                  "notes": {"reason": "R-001 bear 禁止新建仓", "params_version": VERSION,
                            "queue_hint": "队列不消费，见 R-020"}}
    json.dump(orders_out, open(ORDERS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"wrote {ORDERS} (0 new orders, {len(_kept)} filled carried)")
    raise SystemExit

# 满仓保护：H>=max 输出 0 单；8<=H<12 只补足到 max；H<8 补到默认目标数
max_h, min_h = int(LIM["max_holdings"]), int(LIM["min_holdings"])
default_n = int(LIM.get("default_target_holdings", 10))
PENDING_TD = int((PARAMS.get("execution_queue") or {}).get("order_pending_trading_days", 10))

# ---------- 可用仓位（2026-10-28 补仓修正）----------
# 旧版直接拿 regime 仓位上限当 base，补仓时会出现两个致命问题：
#   ① H=6~11 时 max_single(15%) × need < base(70%)，alloc 必然返回 None → RuntimeError 崩溃
#   ② 不扣在途档位，新票会抢走老单 tr2/tr3 的钱，最后只数和权重全错
# 现在：base = cap − 已用市值 − 在途未成交档位；不足单票下限则本轮 0 单。
_used_pct = float(positions.get("position_pct") or 0.0)
_inflight_pct = 0.0
if os.path.exists(ORDERS):
    try:
        _od = json.load(open(ORDERS, encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _od = {}
    for _o in _od.get("orders") or []:
        if _o.get("side") != "buy" or _o.get("status") not in ("planned", "partially_filled"):
            continue
        _tw = float(_o.get("target_weight_pct") or 0)
        for _t in _o.get("tranches") or []:
            if _t.get("status") != "filled":
                _inflight_pct += _tw * float(_t.get("pct") or 0) / 100.0
if H > 0:
    _free = base_pct - _used_pct - _inflight_pct
    print(f"available = cap {base_pct:.2f}% - used {_used_pct:.2f}% - "
          f"inflight {_inflight_pct:.2f}% = {_free:.2f}%")
    base_pct = max(0.0, _free)

if H >= max_h or base_pct < float(LIM["min_single_weight_pct"]):
    reason = (f"满仓保护 H={H}>={max_h}" if H >= max_h
              else f"无可用仓位 {base_pct:.2f}% < 单票下限 {LIM['min_single_weight_pct']}%")
    print(f"{reason} → 本轮 0 单")
    # 保留历史已成交买单：直接写空数组会让 trades.jsonl 的 order_id 悬空（R-018）
    _hist = [_o for _o in (json.load(open(ORDERS, encoding="utf-8")).get("orders") or [])
             ] if os.path.exists(ORDERS) else []
    _hist = [_o for _o in _hist if _o.get("side") == "buy" and _o.get("status") == "filled"]
    orders_out = {"date": base_date, "regime": regime_name,
                  "target_holdings": H, "orders": list(_hist),
                  "filled_orders_carried": len(_hist),
                  "notes": {"reason": reason, "params_version": VERSION,
                            "queue_hint": "补仓候选请走 scripts/order_queue.py promote（R-020）"}}
    json.dump(orders_out, open(ORDERS, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"wrote {ORDERS} (0 new orders, {len(_hist)} filled carried)")
    raise SystemExit

# v3.3 牛市集中：regime=bull 时只数上限压到 bull_max_holdings，把资金集中到质量最高的头部
_conc = LIM.get("bull_concentration") or {}
if _conc.get("enabled") and regime_name == "bull":
    _mh = int(_conc.get("bull_max_holdings", max_h))
    print(f"bull 集中持仓：只数上限 {max_h} → {_mh}（path position_limits.bull_concentration）")
else:
    _mh = max_h
target_n = default_n if H < min_h else _mh
need = target_n - H

# ---------- 候选：buy_watch 且未持有、不在冷却期，按 quality_score 降序 ----------
cands = [i for i in wl["items"]
         if i["verdict"] == "buy_watch" and i["code"] not in held
         and i["code"] not in cooldown]
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
    if hi * n < base - 1e-9:
        # 票太少、顶格也吃不满目标仓位 → 按 max_single 顶格分配，余额留现金。
        # 旧版直接 return None，导致 H=6~11 的补仓场景必然抛 RuntimeError（2026-10-28 修）
        base = hi * n
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
t3 = PZ.get("tranche3") or {}   # v2.7 三档买点
guard = float(PZ["guard_drop_pct"]) / 100.0
# R-024 连续牛市直接买入：regime=bull 且确认持续 >=2 个交易日 → tr2/tr3 不等回调，次日开盘市价补足
_br = PZ.get("bull_rush_rule") or {}
BULL_RUSH_ON = bool(_br.get("enabled", False))
BULL_RUSH_DAYS = int(os.environ.get("BULL_RUSH_DAYS", 2))
try:
    _conf_days = int(regime.get("confirmed_days") or regime.get("confirm_days") or 0)
except (TypeError, ValueError):
    _conf_days = 0
BULL_RUSH_ACTIVE = bool(BULL_RUSH_ON and regime_name == "bull" and _conf_days >= BULL_RUSH_DAYS)
if BULL_RUSH_ON:
    print(f"R-024 bull_rush: regime={regime_name} confirmed_days={_conf_days} "
          f"-> {'直接买入生效' if BULL_RUSH_ACTIVE else '未触发（等回调）'}")
carried, next_seq = [], 1
_cancelled_now = 0
if os.path.exists(ORDERS):
    try:
        _old = json.load(open(ORDERS, encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _old = {}
    for _o in (_old.get("orders") or []):
        _tail = str(_o.get("id") or "").rsplit("-", 1)[-1]
        if _tail.isdigit():
            next_seq = max(next_seq, int(_tail) + 1)
        if _o.get("side") != "buy":
            continue
        _st = _o.get("status")
        if _st == "filled":
            # 已成交单的止损止盈同样按实际成交价对齐（v2.1），与 positions.json 口径保持一致
            _fp = _o.get("fill_price")
            if isinstance(_fp, (int, float)) and _fp > 0:
                _o["stop_loss"] = round(_fp * (1 - RISK["single_stop_loss_pct"] / 100.0), 2)
                _o["take_profit"] = round(_fp * (1 + RISK["single_take_profit_pct"] / 100.0), 2)
                _o["stop_loss_basis"] = "actual_fill_price"
                _o["stop_loss_formula"] = f"成交价 {_fp} × (1-{RISK['single_stop_loss_pct']:g}%)"
            carried.append(_o)
        elif _st in ("planned", "partially_filled"):
            # R-022 止损即删单：标的已清仓进入冷却期 → 未成交档位直接作废，
            # 禁止「止损割肉后剩余档位还挂着、回弹又原样买回」
            if _o.get("code") in cooldown:
                _o["status"] = "cancelled"
                _o["cancel_reason"] = "exit_cooldown_cancelled"
                _o["cancelled_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
                _cancelled_now += 1
                print(f"  R-022 作废 {_o['id']} {_o.get('name')}：标的已清仓（冷却期 {cooldown.get(_o.get('code'))} 个交易日），未成交档位作废")
                continue
            # 其余在途单原样保留（R-006 10 日有效期内），到期处置归持仓管家（R-015）。
            # 旧版只保留 filled、把在途单静默蒸发——在途档位占着资金配额却从文件里消失，口径全错
            carried.append(_o)
        elif _st == "cancelled":
            carried.append(_o)   # 保留作废记录，供巡检追溯
_hist_filled_n = sum(1 for _o in carried if _o.get("status") == "filled")
_carried_planned_n = sum(1 for _o in carried if _o.get("status") in ("planned", "partially_filled"))
if carried:
    print(f"保留历史买单 {len(carried)} 张（已成交 {_hist_filled_n}，在途 {_carried_planned_n}，"
          f"本轮作废 {_cancelled_now}），新单起始序号 {next_seq:03d}")

out_orders = list(carried)
for idx, (i, w) in enumerate(zip(selected, w_final), next_seq):
    code = i["code"]
    sec = (scores.get(code) or {}).get("industry", "未知")
    bars = daily.get(code, [])
    if not bars:
        print(f"  skip {code}: no daily bars")
        continue
    # 只取「基准日及之前」的行情：daily 里含 base_date 之后的数据时，
    # 直接取 bars[-1] 会拿到最新交易日价格，导致 ref / 买点区间 / 止损全部与基准日错位（2026-10-27 修）
    hist = [b for b in bars if b[0] <= base_date]
    if not hist:
        print(f"  skip {code}: no bars <= {base_date}")
        continue
    ref = hist[-1][1]
    if not ref:
        continue
    w20 = hist[-20:]
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
        # 三档买点：50% 开盘竞价市价 + 25% 挂 −3% + 25% 挂 −6%
        # 首档不设限价（市价），避免牛市里等回调等不到而整轮踏空。
        # 注：2026-10-27 旧引擎曾报「牛市补齐 +236% vs 不补齐 +105%」，该数字已作废
        # （旧熔断 -15%→40% 目标 + 旧成交口径）；同机制在实盘熔断口径下重测仅 +1.7pp，
        # 详见 params.backtest_registry 与 pending_decisions P4。
        "tranches": [
            {"seq": 1, "pct": int(t1["weight_share"] * 100), "type": "market_open",
             "limit_price": None, "trigger_pct": None, "price_zone": None, "status": "pending",
             "note": "开盘竞价市价买入，成交价=当日开盘价；仅当 open < guard_price 时放弃"},
            {"seq": 2, "pct": int(t2["weight_share"] * 100), "type": "limit",
             "trigger_pct": t2["offset_pct"], "limit_price": zone(t2["zone_offset_pct"])[1],
             "price_zone": zone(t2["zone_offset_pct"]), "status": "pending"},
            {"seq": 3, "pct": int(t3.get("weight_share", 0) * 100), "type": "limit",
             "trigger_pct": t3.get("offset_pct"), "limit_price": zone(t3["zone_offset_pct"])[1] if t3 else None,
             "price_zone": zone(t3["zone_offset_pct"]) if t3 else None, "status": "pending"},
        ],
        "fill_logic": PZ["fill_logic"],
        "guard_price": round(ref * (1 + guard), 2),
        "stop_loss": stop_preview,
        "take_profit": tp_preview,
        "stop_loss_basis": "actual_fill_price",
        "stop_loss_formula": f"成交加权成本 × (1-{RISK['single_stop_loss_pct']:g}%)；成交回写时必须重算，禁止沿用上面 stop_loss 预览值（R-011）",
        "stop_loss_recalc_required": True,
        "stop_loss_if_tranche3_floor_filled": stop_at_floor,   # v2.7: 三档全成时的成本下沿参考
        "take_profit_basis": "actual_fill_price",
        "take_profit_formula": f"成交加权成本 × (1+{RISK['single_take_profit_pct']:g}%)",
        "twenty_day_low": round(low20, 2),
        "twenty_day_low_note": "风险提示字段，不参与止损计算（v2.1：旧版 min(low20×0.98) 会反向放宽止损）",
        "quality_score": i["quality_score"],
        "rationale": i["thesis"],
        "risks": i["risks"],
        "expires_after_trading_days": PENDING_TD,
        "expire_rule": f"R-006 挂 {PENDING_TD} 个交易日未成交即 expired，禁止上移 price_zone",
        "bull_rush_rule": "R-024：regime=bull 且 confirmed_days>=2 → tr2/tr3 未成交档次日开盘直接市价补足（不等回调）；tr1 不受影响；open<guard_price 当天仍不买",
        "bull_rush_active_at_build": BULL_RUSH_ACTIVE,
        "status": "planned",
        "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    })

# 只统计「本轮新建」的 planned 单：carried 在途单的权重已在上文 available 扣减中体现，
# 混进来会把 planned_total_weight_pct 算重
new_planned = [o for o in out_orders
               if o.get("status") == "planned" and str(o.get("id", "")).startswith(f"ORD-{base_date}")]
total_w = sum(o["target_weight_pct"] for o in new_planned)
orders_doc = {
    "date": base_date,
    "mode": "production",
    "params_version": VERSION,
    "regime": regime_name,
    "base_position_pct": base_pct,
    "holdings_before": H,
    "target_holdings": target_n,
    "planned_new_orders": len(new_planned),
    "filled_orders_carried": _hist_filled_n,
    "carried_planned_orders": _carried_planned_n,
    "planned_total_weight_pct": round(total_w, 2),
    "cash_reserve_pct": round(100 - total_w, 2),
    "sector_weights": {k: round(v, 2) for k, v in sector_total.items()},
    "orders": out_orders,
    "notes": {
        "weight_formula": WA["formula"],
        "price_zone_rule": f"market_open_plus_ladder(v2.7): ref={base_date} 收盘价；tr1=开盘竞价市价(50%)，tr2={t2['offset_pct']}%(25%)，tr3={t3.get('offset_pct')}%(25%)，保护线 {PZ['guard_drop_pct']}%",
        "stop_loss_rule": "实际成交加权成本 × (1-8%)；未成交前 orders.stop_loss 只是 ref 预览值，成交回写必须重算（v2.1 修复「次档买了就在止损线下方」）",
        "take_profit_rule": "实际成交加权成本 × (1+20%)",
        "hard_rules": "R-003 必带止损止盈 / R-006 10 日过期 / R-011 不给金额 / R-012 止损锚定成交成本 / R-022 止损即删单 / R-023 档位-止损一致性 / R-024 连续牛市直接买入",
        "bull_rush": (f"regime={regime_name} confirmed_days={_conf_days} → "
                      f"{'tr2/tr3 直接市价补足（R-024 生效）' if BULL_RUSH_ACTIVE else 'tr2/tr3 等回调成交'}"),
        "writer": "position_builder 只写 buy 单，不删改持仓管家的 sell 单",
    },
}
with open(ORDERS, "w", encoding="utf-8") as f:
    json.dump(orders_doc, f, ensure_ascii=False, indent=2)

print(f"\norders={len(new_planned)} new, total_weight={total_w:.2f}% cash={100 - total_w:.2f}%")
for o in out_orders:
    if o.get("status") != "planned" or not str(o.get("id", "")).startswith(f"ORD-{base_date}"):
        continue
    t = o.get("tranches") or []

    def _lp(k, _t=t):
        return _t[k].get("limit_price") if len(_t) > k and isinstance(_t[k], dict) else "-"
    print(f"  {o['name']:<8} {o['code']} w={o['target_weight_pct']:.2f}% ref={o['ref_price']} "
          f"tr1=竞价 tr2={_lp(1)} tr3={_lp(2)} SL={o['stop_loss']} TP={o['take_profit']}")
print(f"\nsector: {orders_doc['sector_weights']}")
print(f"wrote {ORDERS}")
