# -*- coding: utf-8 -*-
"""订单队列（order_queue）—— 候选存档 + 空位触发建仓（含六年回测结论）

⚠ 回测结论（2026-10-28，6 年 1672 交易日）：
  **自动补位已被否决，不要接入 automation。**
    基线（无队列）           +55.90%
    每日补位 TTL20           +48.52%
    每日补位 TTL5+质量门      +45.49%
    并池 union TTL5          +32.07%
  且前段(19-22)/后段(23-26) 双向一致更差。原因：quality_score 时效性短，
  补位买的是几天到几周前的推荐（按买入来源拆解，平均平仓收益 40.4% → 31.6%）；
  空位又几乎都来自止损/降仓，补位等于下跌途中接续买入（止损 66→86）。
  → merge 保留（存档/审计）；promote 仅作手工调仓工具，执行前必须 --dry-run。
  → 真正有效的是 R-021 清仓冷却期：+55.90% → +74.42%，见 rules.md。

解决的问题：每周重建 orders.json 时，满仓/禁买导致新选出的票直接丢失。
本脚本让候选跨周存续、可追溯、可审计。

机制：
  merge   —— 每周由建仓经理调用：把 watchlist 的 buy_watch 并入常驻队列
             （去重、刷新分数与收盘价、清理已持有/冷却/过期/降级标的）
  promote —— 手工工具（不接 automation）：检查「只数空位 + 资金余量」，
             有空位就按 quality_score 优先级从队列头部取票，重算 ref/买点后
             追加为 orders.json 的 planned 单；没空位则 0 单并写 reason

与旧逻辑的差别（重要）：
  1. orders.json 不再被整份覆盖，promote 只做「追加 + 去重」，历史成交单永久保留
  2. 建仓可用资金 = regime 仓位上限 − 已用市值 − 在途未成交档位，三项都算，
     不再只看持仓只数
  3. 权重分配永不抛异常：资金不足就买够 min_single 的只数，顶到 max_single
     后余额留现金，不再出现 "权重分配失败"
  4. 队列票轮到时用最新收盘重算 ref（这是新建单，不是 R-006 禁止的
     「上移 price_zone 续命」）

禁止项：
  - 队列只补位，不促成换仓：不得因为队列里有高分票就卖出未触发退出条件的持仓
  - regime=bear 时队列一律不消费（R-001 优先于队列优先级）
  - 不得把 promote 接进 automation（见上回测结论）
"""
import argparse
import csv
import glob
import json
import math
import os
import sys
from datetime import datetime

DEFAULT_ROOT = r"E:\cashfree\agent"
QUEUE_VERSION = "q1"


# ---------------------------------------------------------------- 基础读写
def load(p, default=None):
    if not os.path.exists(p):
        return {} if default is None else default
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {} if default is None else default


def dump(p, obj):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def read_csv_rows(p):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def fnum(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def recently_exited(ctx, asof, cooldown_days):
    """冷却期内不得重新建仓的标的（止损/止盈/逻辑破坏清仓后 N 个交易日内）

    不加这条会出现致命循环：刚止损清仓的票，只要 watchlist 里还是 buy_watch，
    下一轮建仓就原价买回来，等于止损白做、还多付两趟手续费。
    """
    p = os.path.join(ctx.state, "trades.jsonl")
    last = {}
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                t = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not t.get("code"):
                continue
            # 形态一：买单结构被填了 close（平仓），退出日 = close.date
            c = t.get("close")
            if isinstance(c, dict) and c.get("date"):
                d = str(c["date"])[:10].replace("-", "")
                last[t["code"]] = max(last.get(t["code"], ""), d)
                continue
            # 形态二：独立的卖出流水
            act = str(t.get("action") or t.get("side") or "").lower()
            if act not in ("sell", "close", "exit", "stop_loss", "take_profit"):
                continue
            d = (t.get("date") or t.get("trade_date") or t.get("ts")
                 or (t.get("open") or {}).get("date"))
            d = str(d)[:10].replace("-", "") if d else None
            if d:
                last[t["code"]] = max(last.get(t["code"], ""), d)
    days = ctx.trading_days()
    out = {}
    for code, d in last.items():
        n = len([x for x in days if d < x <= (asof or d)])
        if n < cooldown_days:
            out[code] = {"exit_date": d, "days_since_exit": n}
    return out


class Ctx:
    """一次调用的全部上下文与路径"""

    def __init__(self, root, warehouse=None, knowledge=None):
        self.root = root
        # 沙箱只隔离 state：warehouse / knowledge 默认回落到正式仓库（只读）
        self.wh = warehouse or os.path.join(root, "data", "warehouse")
        if not os.path.isdir(self.wh):
            self.wh = os.path.join(DEFAULT_ROOT, "data", "warehouse")
        self.kn = knowledge or os.path.join(root, "knowledge")
        if not os.path.isdir(self.kn):
            self.kn = os.path.join(DEFAULT_ROOT, "knowledge")
        self.state = os.path.join(root, "state")
        self.queue = os.path.join(self.state, "order_queue.json")
        self.orders = os.path.join(self.state, "orders.json")
        self.positions = os.path.join(self.state, "positions.json")
        self.regime = os.path.join(self.state, "regime.json")
        self.watchlist = os.path.join(self.state, "watchlist.json")
        self.scores_csv = os.path.join(self.wh, "scores_full.csv")
        self.daily_dir = os.path.join(self.wh, "daily")

        self.version = (open(os.path.join(self.kn, "params_current.txt"),
                             encoding="utf-8").read().strip()
                        if os.path.exists(os.path.join(self.kn, "params_current.txt")) else "v2.3")
        pfile = os.path.join(self.kn, f"params_{self.version}.json")
        self.params = load(pfile)
        self.lim = self.params.get("position_limits", {})
        self.risk = self.params.get("risk", {})
        self.pz = self.params.get("price_zone_rule", {})
        self.regime_cfg = self.params.get("regime", {})

    # 交易日 = daily 快照文件名
    def trading_days(self):
        if not os.path.isdir(self.daily_dir):
            return []
        return sorted(os.path.basename(p)[:-4]
                      for p in glob.glob(os.path.join(self.daily_dir, "*.csv")))

    def latest_day(self, not_after=None):
        days = self.trading_days()
        if not_after:
            days = [d for d in days if d <= not_after]
        return days[-1] if days else None

    def daily_bars(self, code, upto, lookback=25):
        """单只票的近期行情（只扫最近 lookback 个交易日文件，避免全历史扫描）"""
        return self.prefetch([code], upto, lookback).get(code, [])

    def prefetch(self, codes, upto, lookback=25):
        """批量取近期行情，返回 {code: [(date, close, high, low), ...]}

        只读最近 lookback 个交易日快照：ref 与 20 日低最多需要 20 根，
        遍历 1693 个快照 × 全市场会导致单次调用读几百 MB（曾因此被系统杀掉）。
        """
        day_list = [d for d in self.trading_days() if d <= upto][-lookback:]
        want = set(codes)
        out = {c: [] for c in want}
        for d in day_list:
            p = os.path.join(self.daily_dir, f"{d}.csv")
            if not os.path.exists(p):
                continue
            for r in read_csv_rows(p):
                c = r.get("ts_code")
                if c in want:
                    out[c].append((d, fnum(r.get("close")), fnum(r.get("high")), fnum(r.get("low"))))
        for c in out:
            out[c].sort()
        return out

    def industry_map(self):
        if not os.path.exists(self.scores_csv):
            return {}
        return {r["ts_code"]: r.get("industry", "未知") for r in read_csv_rows(self.scores_csv)}


# ---------------------------------------------------------------- 空位与资金
def capacity(ctx, orders_doc, positions_doc, regime_doc):
    """算出本轮可用的只数空位与资金余量（核心：在途档位也算占用）"""
    regime_name = regime_doc.get("regime", "neutral")
    cap = regime_doc.get("position_cap_pct")
    if not isinstance(cap, (int, float)) or not (0 < float(cap) <= 100):
        # v3.0：唯一真源 params.regime.base_position_pct（旧镜像段 regime_base_position_pct 已删除）
        cap = (ctx.params.get("regime") or {}).get("base_position_pct", {}).get(regime_name, 50)
    cap = float(cap)

    holdings = positions_doc.get("holdings") or []
    held = {h.get("code") for h in holdings if h.get("code")}
    used_pct = float(positions_doc.get("position_pct") or 0.0)

    inflight_pct, inflight_codes = 0.0, set()
    for o in orders_doc.get("orders") or []:
        if o.get("side") != "buy" or o.get("status") not in ("planned", "partially_filled"):
            continue
        tw = float(o.get("target_weight_pct") or 0)
        sub = 0.0
        for t in o.get("tranches") or []:
            if t.get("status") != "filled":
                sub += tw * float(t.get("pct") or 0) / 100.0
        if sub > 0:
            inflight_pct += sub
            inflight_codes.add(o.get("code"))

    max_h = int(ctx.lim.get("max_holdings", 12))
    slots = max_h - len(holdings)
    free_pct = cap - used_pct - inflight_pct

    return {
        "regime": regime_name,
        "cap_pct": round(cap, 2),
        "used_pct": round(used_pct, 2),
        "inflight_pct": round(inflight_pct, 2),
        "free_pct": round(free_pct, 2),
        "holdings": len(holdings),
        "slots": slots,
        "held": held,
        "inflight_codes": inflight_codes,
    }


def alloc_soft(qs_list, target, lo, hi):
    """质量归一化 + clamp 迭代。永不失败：票太少就顶格，余额留现金。"""
    n = len(qs_list)
    if n == 0 or target <= 0:
        return [], 0.0
    n = min(n, max(1, int(target // lo))) if lo > 0 else n
    qs = qs_list[:n]
    total = sum(qs) or float(n)
    budget = min(target, hi * n)
    w = [budget * q / total for q in qs]
    fixed = [None] * n
    for _ in range(50):
        free = [i for i in range(n) if fixed[i] is None]
        if not free:
            break
        used = sum(v for v in fixed if v is not None)
        remain = budget - used
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
    return [round(v, 2) for v in final], round(sum(final), 2)


# ---------------------------------------------------------------- merge
def cmd_merge(ctx, args):
    wl = load(ctx.watchlist)
    if not wl.get("items"):
        print("watchlist 为空，跳过 merge")
        return 1
    base_date = wl.get("date") or ctx.latest_day()
    days = ctx.trading_days()
    hold_days = int(args.valid_trading_days)
    # 有效期用「交易日计数」而非日历日：今天就是最新交易日时，按日历算会立刻过期。
    # 估算值只用于展示，判定一律数 queued_date 之后实际走过的交易日。
    latest = ctx.latest_day()
    approx = base_date
    if days and base_date in days:
        approx = days[min(days.index(base_date) + hold_days, len(days) - 1)]

    q = load(ctx.queue, {"version": QUEUE_VERSION, "items": []})
    items = {i["code"]: i for i in q.get("items", [])}
    pos = load(ctx.positions)
    held = {h.get("code") for h in (pos.get("holdings") or []) if h.get("code")}
    ind = ctx.industry_map()
    cool = recently_exited(ctx, base_date, int(args.cooldown_trading_days))

    added, refreshed, dropped = [], [], []
    need_codes = [it["code"] for it in wl["items"]
                  if it.get("verdict") == "buy_watch" and it["code"] not in held]
    bars_map = ctx.prefetch(need_codes, base_date)
    for it in wl["items"]:
        code = it["code"]
        if it.get("verdict") != "buy_watch":
            if code in items and items[code].get("status") == "queued":
                items[code]["status"] = "dropped"
                items[code]["drop_reason"] = f"watchlist verdict={it.get('verdict')}"
                dropped.append(code)
            continue
        if code in held:
            if code in items:
                items[code]["status"] = "held"
            continue
        if code in cool:
            # 冷却票也入队留痕（便于审计「为什么没买」），但状态为 cooldown，不参与 promote
            _why = (f"冷却期：{cool[code]['exit_date']} 退出，已过 "
                    f"{cool[code]['days_since_exit']} 个交易日（上限 {args.cooldown_trading_days}）")
            if code in items:
                items[code].update(status="cooldown", drop_reason=_why,
                                   quality_score=it["quality_score"],
                                   last_refreshed=base_date)
            else:
                items[code] = {
                    "code": code, "name": it["name"],
                    "industry": ind.get(code, it.get("industry") or "未知"),
                    "quality_score": it["quality_score"], "verdict": it["verdict"],
                    "queued_date": base_date, "first_queued_date": base_date,
                    "last_refreshed": base_date, "ref_price": None,
                    "valid_trading_days": hold_days, "valid_until_estimate": approx,
                    "thesis": it.get("thesis"), "risks": it.get("risks"),
                    "status": "cooldown", "drop_reason": _why,
                    "promoted_order_id": None, "promoted_date": None,
                }
            dropped.append(code)
            continue
        bars = bars_map.get(code, [])
        ref = bars[-1][1] if bars else None
        if code in items:
            rec = items[code]
            rec.update({
                "quality_score": it["quality_score"],
                "last_refreshed": base_date,
                "ref_price": ref,
                "verdict": it["verdict"],
                "thesis": it.get("thesis"),
                "risks": it.get("risks"),
                # 本周选股师重新评估仍为 buy_watch → 视为新一次机会，重排有效期。
                # 这不是 R-006 禁止的「续命」：promote 时会用最新收盘重算 ref，
                # 不存在上移旧 price_zone 的问题。first_queued_date 保留原始入队日供审计。
                "queued_date": base_date,
                "valid_trading_days": hold_days,
                "valid_until_estimate": approx,
            })
            rec.setdefault("first_queued_date", rec.get("queued_date"))
            # 走到这里说明该票当前未持有。过期/降级/冷却期满重新评上/曾 promote 但已被清仓
            # → 一律恢复排队；否则 promoted 状态会把这只票永久卡死
            if rec.get("status") in ("expired", "dropped", "cooldown", "promoted"):
                rec["status"] = "queued"
                rec["drop_reason"] = None
                rec["promoted_order_id"] = None
            refreshed.append(code)
        else:
            items[code] = {
                "code": code,
                "name": it["name"],
                "industry": ind.get(code, it.get("industry") or "未知"),
                "quality_score": it["quality_score"],
                "verdict": it["verdict"],
                "queued_date": base_date,
                "first_queued_date": base_date,
                "last_refreshed": base_date,
                "ref_price": ref,
                "valid_trading_days": hold_days,
                "valid_until_estimate": approx,
                "thesis": it.get("thesis"),
                "risks": it.get("risks"),
                "status": "queued",
                "promoted_order_id": None,
                "promoted_date": None,
            }
            added.append(code)

    # 过期判定：数 queued_date 之后实际走过的交易日，≥ valid_trading_days 即出队
    age = dict()
    for rec in items.values():
        qd = rec.get("queued_date")
        n = len([d for d in days if qd and qd < d <= (latest or qd)])
        rec["age_trading_days"] = n
        age[rec["code"]] = n
        if rec.get("status") == "queued" and n >= int(rec.get("valid_trading_days") or hold_days):
            rec["status"] = "expired"
            rec["drop_reason"] = f"排队已满 {n} 个交易日未等到空位（上限 {rec.get('valid_trading_days')}）"

    q = {
        "version": QUEUE_VERSION,
        "updated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "params_version": ctx.version,
        "source_date": base_date,
        "valid_trading_days": hold_days,
        "valid_until_estimate": approx,
        "counts": {},
        "items": sorted(items.values(), key=lambda x: -float(x.get("quality_score") or 0)),
    }
    for rec in q["items"]:
        q["counts"][rec["status"]] = q["counts"].get(rec["status"], 0) + 1

    if not args.dry_run:
        dump(ctx.queue, q)

    print(f"[merge] source={base_date} valid={hold_days}个交易日(约至 {approx}) "
          f"新增={len(added)} 刷新={len(refreshed)} 降级={len(dropped)}")
    print(f"[merge] 队列状态={q['counts']}{' (dry-run 未写入)' if args.dry_run else ''}")
    for rec in q["items"][:12]:
        if rec["status"] in ("queued",):
            print(f"  Q {rec['code']:<10}{rec['name']:<8} score={rec['quality_score']:<5} "
                  f"ref={rec['ref_price']} industry={rec['industry']} "
                  f"age={rec.get('age_trading_days')}/{rec.get('valid_trading_days')}d")
    return 0


# ---------------------------------------------------------------- promote
def cmd_promote(ctx, args):
    q = load(ctx.queue)
    orders_doc = load(ctx.orders, {"orders": []})
    pos = load(ctx.positions)
    reg = load(ctx.regime)
    asof = ctx.latest_day(args.asof)
    if not asof:
        print("[promote] 无可用行情，退出")
        return 1

    cap = capacity(ctx, orders_doc, pos, reg)
    print(f"[promote] asof={asof} regime={cap['regime']} cap={cap['cap_pct']}% "
          f"used={cap['used_pct']}% inflight={cap['inflight_pct']}% "
          f"free={cap['free_pct']}% holdings={cap['holdings']} slots={cap['slots']}")

    lo = float(ctx.lim.get("min_single_weight_pct", 3))
    hi = float(ctx.lim.get("max_single_weight_pct", 15))
    max_sec = float(ctx.lim.get("max_sector_weight_pct", 30))

    blocked = None
    if cap["regime"] == "bear":
        blocked = "R-001 bear 禁止新建仓，队列不消费"
    elif cap["slots"] <= 0:
        blocked = f"只数已满 holdings={cap['holdings']}>=max"
    elif cap["free_pct"] <= 0:
        blocked = (f"无资金余量 free={cap['free_pct']}% "
                   f"(cap {cap['cap_pct']} - used {cap['used_pct']} - inflight {cap['inflight_pct']})")
    elif cap["free_pct"] < lo:
        blocked = f"资金余量 {cap['free_pct']}% 低于单票下限 {lo}%"

    # 已在 orders 里的 planned / 已持有的，不再重复下单；冷却期内的也不碰
    cool = recently_exited(ctx, asof, int(args.cooldown_trading_days))
    busy = set(cap["held"]) | set(cap["inflight_codes"]) | set(cool)
    cands = [i for i in q.get("items", [])
             if i.get("status") == "queued" and i["code"] not in busy]
    cands.sort(key=lambda x: (-float(x.get("quality_score") or 0), x.get("queued_date") or ""))

    if blocked is None and not cands:
        blocked = "队列无可用候选（全部已持有/在途/过期）"

    if blocked:
        doc = dict(orders_doc)
        doc.setdefault("notes", {})["promote"] = {
            "asof": asof,
            "orders": 0,
            "blocked_reason": blocked,
            "capacity": {k: (sorted(v) if isinstance(v, set) else v)
                         for k, v in cap.items()},
            "queue_queued": len([i for i in q.get("items", []) if i.get("status") == "queued"]),
            "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if not args.dry_run:
            dump(ctx.orders, doc)
        print(f"[promote] 0 单 —— {blocked}")
        return 0

    # 行业已占用权重
    sec_used = {}
    for h in pos.get("holdings") or []:
        s = h.get("industry") or "未知"
        sec_used[s] = sec_used.get(s, 0) + float(h.get("weight_pct") or 0)
    for o in orders_doc.get("orders") or []:
        if o.get("status") in ("planned", "partially_filled"):
            s = o.get("industry") or "未知"
            sec_used[s] = sec_used.get(s, 0) + float(o.get("target_weight_pct") or 0)

    # 按优先级取票，受行业上限约束
    target = min(cap["free_pct"], hi * cap["slots"])
    picked, sec_add = [], {}
    est = max(lo, target / max(1, min(cap["slots"], len(cands))))
    for c in cands:
        if len(picked) >= cap["slots"]:
            break
        s = c.get("industry") or "未知"
        if sec_used.get(s, 0) + sec_add.get(s, 0) + est > max_sec + 1e-9:
            continue
        picked.append(c)
        sec_add[s] = sec_add.get(s, 0) + est
    if not picked:
        print("[promote] 候选全部被行业上限拦下，0 单")
        return 0

    weights, total_w = alloc_soft([float(c["quality_score"]) for c in picked],
                                  min(target, cap["free_pct"]), lo, hi)
    picked = picked[:len(weights)]
    if not picked:
        print("[promote] 权重分配为空，0 单")
        return 0

    # 接续订单序号，保留历史单一律不动
    next_seq = 1
    for o in orders_doc.get("orders") or []:
        tail = str(o.get("id") or "").rsplit("-", 1)[-1]
        if tail.isdigit():
            next_seq = max(next_seq, int(tail) + 1)

    t1 = ctx.pz.get("tranche1", {"weight_share": 0.5})
    t2 = ctx.pz.get("tranche2", {"weight_share": 0.25, "offset_pct": -3.0,
                                 "zone_offset_pct": [-12.0, -3.0]})
    t3 = ctx.pz.get("tranche3") or {"weight_share": 0.25, "offset_pct": -6.0,
                                    "zone_offset_pct": [-12.0, -6.0]}
    guard = float(ctx.pz.get("guard_drop_pct", -12)) / 100.0
    sl_pct = float(ctx.risk.get("single_stop_loss_pct", 8)) / 100.0
    tp_pct = float(ctx.risk.get("single_take_profit_pct", 20)) / 100.0

    new_orders = []
    bars_map = ctx.prefetch([c["code"] for c in picked], asof)
    for idx, (c, w) in enumerate(zip(picked, weights), next_seq):
        bars = bars_map.get(c["code"], [])
        if not bars or not bars[-1][1]:
            print(f"  skip {c['code']}: 无行情")
            continue
        ref = bars[-1][1]
        w20 = bars[-20:]
        lows = [b[3] for b in w20 if b[3] is not None]

        def zone(offs):
            return [round(ref * (1 + offs[0] / 100.0), 2), round(ref * (1 + offs[1] / 100.0), 2)]

        oid = f"ORD-{asof}-{idx:03d}"
        new_orders.append({
            "id": oid,
            "side": "buy",
            "code": c["code"],
            "name": c["name"],
            "industry": c.get("industry") or "未知",
            "target_weight_pct": w,
            "weight_basis": "pct_of_total_assets",
            "amount_note": "不预置金额，由持仓管家按执行时总资产计算（R-011）",
            "ref_price": round(ref, 2),
            "ref_date": asof,
            "queue_queued_date": c.get("queued_date"),
            "queue_source": "order_queue.promote",
            "tranches": [
                {"seq": 1, "pct": int(t1["weight_share"] * 100), "type": "market_open",
                 "limit_price": None, "trigger_pct": None, "price_zone": None,
                 "status": "pending",
                 "note": "开盘竞价市价买入；仅当 open < guard_price 时放弃"},
                {"seq": 2, "pct": int(t2["weight_share"] * 100), "type": "limit",
                 "trigger_pct": t2.get("offset_pct"),
                 "limit_price": zone(t2["zone_offset_pct"])[1],
                 "price_zone": zone(t2["zone_offset_pct"]), "status": "pending"},
                {"seq": 3, "pct": int(t3["weight_share"] * 100), "type": "limit",
                 "trigger_pct": t3.get("offset_pct"),
                 "limit_price": zone(t3["zone_offset_pct"])[1],
                 "price_zone": zone(t3["zone_offset_pct"]), "status": "pending"},
            ],
            "fill_logic": ctx.pz.get("fill_logic"),
            "guard_price": round(ref * (1 + guard), 2),
            "stop_loss": round(ref * (1 - sl_pct), 2),
            "take_profit": round(ref * (1 + tp_pct), 2),
            "stop_loss_basis": "actual_fill_price",
            "stop_loss_formula": "成交加权成本 × (1-8%)；成交回写必须重算，禁止沿用预览值（R-012）",
            "stop_loss_recalc_required": True,
            "twenty_day_low": round(min(lows), 2) if lows else None,
            "twenty_day_low_note": "风险提示字段，不参与止损计算（v2.1）",
            "quality_score": c["quality_score"],
            "rationale": c.get("thesis"),
            "risks": c.get("risks"),
            "expires_after_trading_days": 10,
            "expire_rule": "R-006 挂 10 个交易日未成交即 expired，禁止上移 price_zone",
            "status": "planned",
            "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        })

    orders_doc["orders"] = list(orders_doc.get("orders") or []) + new_orders
    orders_doc.setdefault("notes", {})["promote"] = {
        "asof": asof,
        "orders": len(new_orders),
        "picked": [c["code"] for c in picked[:len(new_orders)]],
        "blocked_reason": None,
        "capacity": {k: (sorted(v) if isinstance(v, set) else v) for k, v in cap.items()},
        "total_weight_pct": round(sum(o["target_weight_pct"] for o in new_orders), 2),
        "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    orders_doc["planned_new_orders"] = len([o for o in orders_doc["orders"]
                                            if o.get("status") == "planned"])

    if not args.dry_run:
        dump(ctx.orders, orders_doc)
        for c, o in zip(picked, new_orders):
            c["status"] = "promoted"
            c["promoted_order_id"] = o["id"]
            c["promoted_date"] = asof
        q["updated_at"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        q["counts"] = {}
        for rec in q.get("items", []):
            q["counts"][rec["status"]] = q["counts"].get(rec["status"], 0) + 1
        dump(ctx.queue, q)

    print(f"[promote] 生成 {len(new_orders)} 单，合计 {orders_doc['notes']['promote']['total_weight_pct']}%"
          f"{' (dry-run 未写入)' if args.dry_run else ''}")
    for o in new_orders:
        print(f"  {o['id']} {o['name']:<8} {o['code']} w={o['target_weight_pct']}% "
              f"ref={o['ref_price']} tr2={o['tranches'][1]['limit_price']} "
              f"tr3={o['tranches'][2]['limit_price']} SL={o['stop_loss']}")
    return 0


# ---------------------------------------------------------------- show
def cmd_show(ctx, args):
    q = load(ctx.queue)
    cap = capacity(ctx, load(ctx.orders), load(ctx.positions), load(ctx.regime))
    days = ctx.trading_days()
    latest = ctx.latest_day()
    print(f"队列 {q.get('updated_at')} source={q.get('source_date')} counts={q.get('counts')}")
    print(f"仓位 cap={cap['cap_pct']}% used={cap['used_pct']}% inflight={cap['inflight_pct']}% "
          f"free={cap['free_pct']}% holdings={cap['holdings']} slots={cap['slots']}")
    for i in q.get("items", []):
        fq = i.get("first_queued_date") or i.get("queued_date")
        total_age = len([d for d in days if fq and fq < d <= (latest or fq)])
        print(f"  [{i['status']:<9}] {i['code']:<10}{i['name']:<8} score={i['quality_score']:<6} "
              f"queued={i.get('queued_date')} age={i.get('age_trading_days')}/"
              f"{i.get('valid_trading_days')}d 累计排队={total_age}d "
              f"order={i.get('promoted_order_id')}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="订单队列：候选排队 + 空位触发建仓")
    ap.add_argument("cmd", choices=["merge", "promote", "show"])
    ap.add_argument("--root", default=os.environ.get("AQ_ROOT", DEFAULT_ROOT))
    ap.add_argument("--warehouse", default=os.environ.get("AQ_WAREHOUSE"),
                    help="行情仓库目录，默认 <root>/data/warehouse，沙箱下回落到正式仓库")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--valid-trading-days", type=int, default=None,
                    help="入队后有效交易日数（默认读 params.execution_queue.queue_valid_trading_days）")
    ap.add_argument("--cooldown-trading-days", type=int, default=None,
                    help="止损/止盈清仓后禁止重新建仓的交易日数（默认读 params.execution_queue.cooldown_trading_days）")
    ap.add_argument("--asof", default=None, help="promote 基准日，默认最新交易日")
    args = ap.parse_args()
    ctx = Ctx(args.root, args.warehouse)
    _eq = ctx.params.get("execution_queue") or {}
    if args.valid_trading_days is None:
        args.valid_trading_days = int(_eq.get("queue_valid_trading_days", 20))
    if args.cooldown_trading_days is None:
        args.cooldown_trading_days = int(_eq.get("cooldown_trading_days", 20))
    return {"merge": cmd_merge, "promote": cmd_promote, "show": cmd_show}[args.cmd](ctx, args)


if __name__ == "__main__":
    sys.exit(main())
