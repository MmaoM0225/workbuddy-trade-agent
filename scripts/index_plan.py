#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""index_plan.py - 本期定投计划（v2.0，不看本金）

规则：
  金额 = execute.unit_amount_cny × 倍数（倍数分档见参数文件 zones，不在此复述数值）
  宽基：只要分位 <40 就买
  行业：分位 <40 的按分位升序取前 top_industry 个（默认 5），避免一次买 20 多个
  卖出：分档减速（75 卖1/3、85 再卖1/2、95 清仓），间隔 >=20 交易日
  记账：总收益 = 累计投入 + 已实现盈亏 + 未实现盈亏；不设本金上限

用法：
  python scripts/index_plan.py
  python scripts/index_plan.py --top 8
  python scripts/index_plan.py --dry-run
"""
import argparse
import json
import shutil
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from index_valuation_signal import sell_step  # noqa: E402  与回测共用同一份卖出阶梯判定

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIGNAL = os.path.join(ROOT, "state", "index_signal.json")
PORT = os.path.join(ROOT, "state", "index_portfolio.json")
ORDERS = os.path.join(ROOT, "state", "index_orders.json")


def cat_of(kind, market):
    """展示分类：国内宽基 / 国外宽基 / 行业。策略判定仍按 kind 两分法，不受影响。"""
    if kind == "industry":
        return "行业"
    return "国内宽基" if (market or "CN").startswith("CN") else "国外宽基"


def load_index_params():
    """指数估值定投线参数（唯一真源）：knowledge/index_params.json
    与个股线 knowledge/params_v*.json 完全独立，不再混用。"""
    p = os.path.join(ROOT, "knowledge", "index_params.json")
    if not os.path.exists(p):
        raise SystemExit("缺少 knowledge/index_params.json（指数线唯一真源）")
    with open(p, encoding="utf-8") as f:
        return json.load(f)

def load_json(p, default=None):
    if not os.path.exists(p):
        return default
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def trade_days():
    d = os.path.join(ROOT, "data", "warehouse", "daily")
    if not os.path.isdir(d):
        return []
    return sorted(x[:-4] for x in os.listdir(d) if x.endswith(".csv"))


def td_between(d0, d1, cal):
    if not d0 or not d1:
        return 9999
    return sum(1 for x in cal if d0 < x <= d1)



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=5, help="每期最多买几个行业")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    params = load_index_params()
    sig = load_json(SIGNAL)
    if not sig:
        print("缺少 state/index_signal.json，先跑 index_valuation_signal.py")
        return 1
    ex = params["execute"]
    unit = ex["unit_amount_cny"]
    cal = trade_days()
    today = sig["as_of"]

    port = load_json(PORT) or {"version": "v2.0", "created": today,
                               "cumulative_invested_cny": 0.0,
                               "realized_pnl_cny": 0.0,
                               "cash_from_sells_cny": 0.0,
                               "holdings": {}, "history": []}
    hold = port.setdefault("holdings", {})
    items = sig["items"]
    by_code = {i["code"]: i for i in items}

    # ---------- 1. 卖出 ----------
    sells = []
    for code, pos in hold.items():
        if pos.get("value", 0) <= 0:
            continue
        it = by_code.get(code)
        if not it:
            continue
        # 持续减仓：只要在 >=75 区间，每个冷却期就按当前档位卖一次，直到仓位清空。
        # 不再有「该档已卖过就跳过」的门槛 —— 旧规则正是因此导致高位横盘时只卖一次。
        stage = sell_step(it["score"], ex.get("sell_ladder") or [])
        if not stage:
            continue
        last = pos.get("last_action_date", "")
        if last and td_between(last, today, cal) < ex["sell_interval_td"]:
            continue
        bought = pos.get("first_buy_date") or last
        if bought:
            try:
                gap = (datetime.strptime(today, "%Y%m%d") - datetime.strptime(bought, "%Y%m%d")).days
            except ValueError:
                gap = 9999
            if gap < ex["min_hold_days"]:
                continue
        # 按金额倍数卖：卖 sell_unit_cny × mult 元，最多清空当前仓位
        unit_sell = ex.get("sell_unit_cny") or ex.get("unit_amount_cny", 10)
        want = unit_sell * stage.get("mult", 1)
        amt = min(want, pos["value"])
        if amt <= 0:
            continue
        ratio = amt / pos["value"] if pos["value"] > 0 else 1.0
        cost_out = pos.get("cost", 0) * ratio
        sells.append({"code": code, "name": it["name"], "score": it["score"],
                      "stage": stage["min_score"], "label": stage["label"],
                      "mult": stage.get("mult", 1), "ratio": round(ratio, 6),
                      "amount_cny": round(amt, 2),
                      "cost_cny": round(cost_out, 2),
                      "pnl_cny": round(amt - cost_out, 2)})

    # ---------- 2. 买入 ----------
    # 买不到的不下单：宽基要求有场外基金，行业要求 match_level != none
    # 只买场外：用户明确申购场外基金，场内 ETF 不作为下单标的
    def is_of(i):
        """场外可申购：纯场外 .OF，或 LOF（场内上市但支持场外申赎，如招商白酒A 161725.SZ）。"""
        v = i.get("fund_venue")
        if v:
            return v in ("场外", "LOF")
        f = i.get("fund") or ""
        return f.endswith(".OF")

    broad_buys = [i for i in items if i["kind"] == "broad" and i["action"] == "买入" and is_of(i)]
    rf = params.get("execute", {}).get("industry_roe_filter", {})
    roe_on = rf.get("enabled", False)
    roe_th = rf.get("roe_th", 0.15)
    ind_pool = [i for i in items if i["kind"] == "industry" and i["action"] == "买入"]
    if roe_on:
        keep, drop = [], []
        for i in ind_pool:
            v = i.get("roe_chg")
            (keep if (v is not None and v > roe_th) else drop).append(i)
        ind_pool = keep
        roe_dropped = drop
    else:
        roe_dropped = []
    ind_ok = sorted([i for i in ind_pool if is_of(i)], key=lambda x: x["score"])[:args.top]
    ind_nofund = [i for i in ind_pool if not is_of(i)]
    ind_buys = ind_ok
    # 同一只基金只买一次（旅游及景区与酒店餐饮都指向华夏旅游ETF，不去重会重复扣款）
    buys, seen_fund, dup = [], {}, []
    for it in broad_buys + ind_buys:
        f = it.get("fund")
        if f and f in seen_fund:
            dup.append((it["name"], seen_fund[f], f))
            continue
        if f:
            seen_fund[f] = it["name"]
        amt = round(unit * it["mult"], 2)
        buys.append({"code": it["code"], "name": it["name"], "kind": it["kind"],
                     "market": it.get("market"), "score": it["score"], "zone": it["zone"],
                     "mult": it["mult"], "amount_cny": amt,
                     "fund": it.get("fund", ""), "fund_name": it.get("fund_name", ""),
                     "match_level": it.get("match_level", "")})

    # ---------- 2b. 现金积压补买 ----------
    # 卖出回款若长期闲置就白攒了。常规买入后，若现金池仍高于 reserve，按分位升序
    # 补买当日没买过的合格标的（分位<40、有场外基金、行业已过 ROE），每个 1X×mult。
    rd = ex.get("cash_redeploy") or {}
    redeploy = []
    if rd.get("enabled"):
        reserve = float(rd.get("reserve_cny", 0))
        top_n = int(rd.get("top_n", 0))
        cash_now = float(port.get("cash_from_sells_cny") or 0.0) + sum(x["amount_cny"] for x in sells)
        bought_codes = {b["code"] for b in buys}
        # 用未截断的行业候选池（ind_pool 已过 ROE），否则永远只剩 top5 已买过、补买无从触发
        pool = [i for i in (broad_buys + ind_pool)
                if i["code"] not in bought_codes and i.get("score") is not None
                and i["score"] < 40 and is_of(i)]
        pool.sort(key=lambda x: x["score"])
        for it in pool:
            if len(redeploy) >= top_n or cash_now <= reserve:
                break
            amt = round(unit * it["mult"], 2)
            if amt > cash_now:
                continue
            cash_now -= amt
            redeploy.append({"code": it["code"], "name": it["name"], "kind": it["kind"],
                             "market": it.get("market"), "score": it["score"], "zone": it["zone"],
                             "mult": it["mult"], "amount_cny": amt, "reason": "cash_redeploy",
                             "fund": it.get("fund", ""), "fund_name": it.get("fund_name", ""),
                             "match_level": it.get("match_level", "")})
        if redeploy:
            seen = {b["fund"] for b in buys if b.get("fund")}
            redeploy = [b for b in redeploy if not (b.get("fund") and b["fund"] in seen)]
            buys += redeploy

    total_buy = sum(b["amount_cny"] for b in buys)
    total_sell = sum(s["amount_cny"] for s in sells)

    # ---------- 3. 展示 ----------
    print("本期定投计划   基准日 %s   1X = %d 元   参数 %s" % (today, unit, params["version"]))
    print("累计投入 %s 元   已实现 %s 元   卖出回收现金 %s 元" % (
        format(port["cumulative_invested_cny"], ",.0f"),
        format(port["realized_pnl_cny"], ",.0f"),
        format(port["cash_from_sells_cny"], ",.0f")))

    print("\n【买入】%d 只，合计 %s 元" % (len(buys), format(total_buy, ",.0f")))
    if buys:
        print("  %-16s %-6s %6s %5s %7s %-6s %s" % ("标的", "类别", "分位", "倍数", "金额", "匹配", "基金"))
        for b in buys:
            lv = b.get("match_level") or ""
            fund = b["fund"] or "无对应基金"
            print("  %-16s %-6s %6.1f %4.1fx %7s %-6s %s %s" % (
                b["name"][:14], cat_of(b["kind"], b.get("market")),
                b["score"], b["mult"], format(b["amount_cny"], ",.0f"), lv, fund,
                (b.get("fund_name") or "")[:18]))

    if dup:
        print("\n【同基金去重】%s" % "；".join("%s 与 %s 同指 %s，只买一次" % (a, b, f) for a, b, f in dup))

    print("\n【卖出】%d 只，回收 %s 元" % (len(sells), format(total_sell, ",.0f")))
    if sells:
        for s in sells:
            print("  %-16s 分位%3.0f  %s  卖出 %7s 元  实现盈亏 %+8s" % (
                s["name"][:14], s["score"], s["label"],
                format(s["amount_cny"], ",.0f"), format(s["pnl_cny"], "+.0f")))
    else:
        print("  （无）")

    if roe_dropped:
        print("\n【盈利未改善，行业不买】%d 个（隐含ROE同比 <= %.0f%%）：%s" % (
            len(roe_dropped), roe_th * 100,
            "、".join("%s(%.0f)" % (x["name"], x["score"]) for x in roe_dropped[:8])))

    if ind_nofund:
        print("\n【有信号但无场外基金】%s" %
              "、".join("%s(%.1f)" % (x["name"], x["score"]) for x in ind_nofund[:10]))
        print("  （含只有场内ETF的行业，按你的要求不下单）")

    stop = [i for i in items if i["action"] == "停投"]
    print("\n【停投】国内宽基 %d 个 / 国外宽基 %d 个 / 行业 %d 个（分位 40-75，不动）" % (
        len([x for x in stop if cat_of(x["kind"], x.get("market")) == "国内宽基"]),
        len([x for x in stop if cat_of(x["kind"], x.get("market")) == "国外宽基"]),
        len([x for x in stop if cat_of(x["kind"], x.get("market")) == "行业"])))
    print("  宽基停投：%s" % "、".join("%s %.0f" % (x["name"], x["score"])
                                for x in stop if x["kind"] == "broad"))

    sell_now = [i for i in items if i["action"] in ("减仓", "清仓")]
    if sell_now:
        print("\n【高估信号】%d 个：" % len(sell_now))
        for x in sorted(sell_now, key=lambda y: -y["score"])[:15]:
            print("  %-16s 综合%4.0f  %s（%s）" % (
                x["name"][:14], x["score"], x["action"],
                cat_of(x["kind"], x.get("market"))))

    # ---------- 4. 收益核算 ----------
    mv = sum(p.get("value", 0) for p in hold.values())
    cost = sum(p.get("cost", 0) for p in hold.values())
    # 盯市缺口：有成本却算不出市值（nav 缺失／没跑过 update_index_portfolio）。
    # 别把 mv=0 当"跌到 0"，否则未实现盈亏会变成 -累计投入，写进 orders 后邮件里就是 -100%。
    unmarked = [k for k, p in hold.items()
                if float(p.get("cost") or 0) > 0 and not float(p.get("value") or 0) > 0]
    if unmarked:
        unreal = 0.0
        print("\n【账本未盯市】%d 只持仓缺市值，未实现盈亏暂按 0 记；"
              "请先跑 python scripts/update_index_portfolio.py 补盯市" % len(unmarked))
    else:
        unreal = mv - cost
    total = port["cumulative_invested_cny"] + port["realized_pnl_cny"] + unreal
    # 口径必须拆开，别混：
    #   总收益(profit) = 已实现 + 未实现
    #   总资产(assets) = 累计投入 + 总收益
    #   收益率        = 总收益 / 累计投入
    # 旧代码把 assets 当 total 写进 total_return_cny，下游一算 assets=投入+总资产 直接翻倍。
    profit = port["realized_pnl_cny"] + unreal
    assets = port["cumulative_invested_cny"] + profit
    print("\n【收益核算】")
    print("  累计投入        %12s 元" % format(port["cumulative_invested_cny"], ",.0f"))
    print("  + 已实现盈亏    %12s 元" % format(port["realized_pnl_cny"], "+,.2f"))
    print("  + 未实现盈亏    %12s 元" % format(unreal, "+,.2f"))
    print("  = 总收益        %12s 元" % format(profit, "+,.2f"))
    print("  总资产          %12s 元" % format(assets, ",.0f"))
    if port["cumulative_invested_cny"] > 0:
        print("  收益率          %11.2f%%" % (profit / port["cumulative_invested_cny"] * 100))

    # 卖出回款再投：买入金额优先用现金池抵扣，只有不足部分才是新增投入
    cash_pool = float(port.get("cash_from_sells_cny") or 0.0) + total_sell
    cash_used = min(cash_pool, total_buy)
    new_money = total_buy - cash_used
    print("\n【现金池】期初 %s 元 + 本期卖出 %s 元 → 可用于买入 %s 元"
          % (format(float(port.get("cash_from_sells_cny") or 0.0), ",.0f"),
             format(total_sell, ",.0f"), format(cash_pool, ",.0f")))
    print("  本期买入 %s 元中，%s 元来自卖出回款，新增投入 %s 元"
          % (format(total_buy, ",.0f"), format(cash_used, ",.0f"), format(new_money, ",.0f")))

    payload = {"as_of": today, "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "params_version": params["version"], "unit_amount_cny": unit,
               "buys": buys, "sells": sells,
               "total_buy_cny": total_buy, "total_sell_cny": total_sell,
               "cash_before_cny": round(cash_pool, 2),
               "cash_used_cny": round(cash_used, 2),
               "new_money_cny": round(total_buy - cash_used, 2),
               "cumulative_invested_cny": port["cumulative_invested_cny"],
               "realized_pnl_cny": port["realized_pnl_cny"],
               "unrealized_pnl_cny": round(unreal, 2),
               "portfolio_marked": not unmarked,
               "total_return_cny": round(profit, 2),
               "total_assets_cny": round(assets, 2)}
    # 保护：上一期计划若未登记成交，先归档，避免被本期覆盖导致成交丢失
    if os.path.exists(ORDERS) and not args.dry_run:
        old = load_json(ORDERS) or {}
        if old.get("as_of") and old["as_of"] != today:
            committed = any(h.get("date") == old["as_of"] for h in port.get("history", []))
            if not committed and (old.get("buys") or old.get("sells")):
                pend = os.path.join(ROOT, "state", "orders_pending")
                os.makedirs(pend, exist_ok=True)
                shutil.move(ORDERS, os.path.join(pend, "orders_%s.json" % old["as_of"]))
                print("\n[注意] 上一期 %s 的计划未登记成交，已归档到 state/orders_pending/" % old["as_of"])
                print("       如果你已按它申购，请先补登记：python scripts/update_index_portfolio.py --commit --from state/orders_pending/orders_%s.json" % old["as_of"])

    if args.dry_run:
        print("\n[dry-run] 未写入")
    else:
        with open(ORDERS, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print("\n写入 %s" % ORDERS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
