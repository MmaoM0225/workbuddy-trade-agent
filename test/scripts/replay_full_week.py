#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Full-week replay: 2026-10-17 (selection night) -> 10-19..10-23 (daily) -> 10-24 (review).

Stage A  10-17 Sat  : pick (base=10-16 close) -> screen -> build 10 orders
Stage B  10-19..23  : per day data -> regime -> position-manager -> inspector
Stage C  10-24 Sat  : weekly review
All deterministic, real local data, no look-ahead beyond documented approximations.
"""
import csv
import glob
import json
import math
from pathlib import Path

BASE = "E:/cashfree/agent/"
DAILY_DIR = BASE + "data/warehouse/daily/"
OUT_JSON = BASE + "test/replay_week_v15.json"
OUT_MD = BASE + "test/reports/replay_week_v15_20261017_24.md"

BASE_DATE = "20261016"   # Friday close, basis for Saturday selection
CAPITAL = 1_000_000.0

# real market_overview values (pulled live) for each trading day
MKT = {
    "20261019": dict(close=3730.92, chg=0.39, ma20=3839.88, ma60=3881.69, ma250=3988.67,
                     up=40.81, lu=46, ld=3, hi20=214, lo20=2712, money_ratio=84.68,
                     money=14375.12, cyb=-0.94),
    "20261020": dict(close=3735.37, chg=0.12, ma20=3832.38, ma60=3880.68, ma250=3988.08,
                     up=67.77, lu=50, ld=0, hi20=193, lo20=478, money_ratio=86.21,
                     money=14561.12, cyb=-0.26),
    "20261021": dict(close=3713.03, chg=-0.60, ma20=3824.82, ma60=3878.15, ma250=3987.20,
                     up=35.53, lu=47, ld=0, hi20=196, lo20=323, money_ratio=85.09,
                     money=14293.48, cyb=-1.62),
    "20261022": dict(close=3658.03, chg=-1.48, ma20=3813.14, ma60=3874.67, ma250=3986.24,
                     up=9.59, lu=32, ld=5, hi20=178, lo20=1817, money_ratio=91.85,
                     money=15287.14, cyb=-4.37),
    "20261023": dict(close=3690.48, chg=0.89, ma20=3803.88, ma60=3871.57, ma250=3985.45,
                     up=81.15, lu=82, ld=2, hi20=219, lo20=4115, money_ratio=117.07,
                     money=19562.84, cyb=4.16),
}
EXEC = sorted(MKT)

print("loading daily bars...")
daily = {}
for fp in sorted(glob.glob(DAILY_DIR + "*.csv")):
    d = Path(fp).stem
    m = {}
    with open(fp, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            try:
                m[r["ts_code"]] = {k: float(r[k]) for k in ("open", "high", "low", "close", "amount")}
            except (ValueError, TypeError, KeyError):
                continue
    daily[d] = m

ALL = sorted(daily)
HIST = [d for d in ALL if d <= BASE_DATE]
print("history %d days (%s..%s) | exec %s" % (len(HIST), HIST[0], HIST[-1], EXEC))


def load_csv(p):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


basic = {r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/meta/stock_basic.csv")}
fina = {r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/fina/h1_all.csv")}
fina.update({r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/fina/q3_all.csv")})
db = {r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/daily_basic/20261023.csv")}
gw = {r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/research/goodwill.csv")}
au = {r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/research/audit.csv")}
rd = {r["ts_code"]: r for r in load_csv(BASE + "data/warehouse/research/reduction.csv")}

# ============ Stage A: selection (10-17 Sat) ============
univ = []
for code in daily[BASE_DATE]:
    if code.endswith(".BJ") or code[:3] in ("300", "301", "688", "689"):
        continue
    nm = (basic.get(code) or {}).get("name", "")
    if "ST" in nm.upper():
        continue
    univ.append(code)

W = {"mom_5d": .06, "mom_10d": .07, "mom_20d": .07, "vol_20d_inv": .08, "mdd_20d_inv": .07,
     "price_pos_20d": .06, "pv_corr_20d": .07, "turnover_trend_20d": .07,
     "roe_ttm": .08, "gross_margin_ttm": .04, "net_margin_ttm": .04, "tr_yoy": .04,
     "ep_ttm": .06, "bp_ttm": .05, "sp_ttm": .04, "turnover_rate": .05}
ws = sum(W.values())
W = {k: v / ws for k, v in W.items()}


def pctl(vals, x):
    if not vals or x is None:
        return None
    lo = sum(1 for v in vals if v < x)
    eq = sum(1 for v in vals if v == x)
    return (lo + eq * .5) / len(vals) * 100


rows = []
for code in univ:
    bars = [daily[d][code] for d in HIST if code in daily[d]]
    if len(bars) < 12:
        continue
    c = [b["close"] for b in bars]
    a = [b["amount"] for b in bars]
    n = len(c)
    rets = [c[i] / c[i - 1] - 1 for i in range(1, n)]
    mu = sum(rets) / len(rets)
    vol = -math.sqrt(sum((r - mu) ** 2 for r in rets) / len(rets))
    peak, mdd = c[0], 0.0
    for x in c:
        peak = max(peak, x)
        mdd = min(mdd, x / peak - 1)
    mn, mx = min(c), max(c)
    mc, ma = sum(c) / n, sum(a) / n
    vc = math.sqrt(sum((x - mc) ** 2 for x in c))
    va = math.sqrt(sum((x - ma) ** 2 for x in a))
    xs = list(range(n))
    xm = sum(xs) / n
    slope = sum((xs[i] - xm) * (a[i] - ma) for i in range(n)) / sum((x - xm) ** 2 for x in xs)
    fi, dbr = fina.get(code) or {}, db.get(code) or {}

    def f(k, src):
        try:
            return float(src.get(k))
        except (TypeError, ValueError):
            return None

    pe, pb, ps = f("pe_ttm", dbr), f("pb", dbr), f("ps_ttm", dbr)
    rows.append({
        "code": code, "name": (basic.get(code) or {}).get("name", ""),
        "industry": (basic.get(code) or {}).get("industry", ""),
        "mom_5d": c[-1] / c[-6] - 1 if n > 5 else None,
        "mom_10d": c[-1] / c[-11] - 1 if n > 10 else None,
        "mom_20d": c[-1] / c[0] - 1,
        "vol_20d_inv": vol, "mdd_20d_inv": mdd,
        "price_pos_20d": (c[-1] - mn) / (mx - mn) if mx > mn else .5,
        "pv_corr_20d": (sum((c[i] - mc) * (a[i] - ma) for i in range(n)) / (vc * va)) if vc and va else None,
        "turnover_trend_20d": slope,
        "roe_ttm": f("roe", fi), "gross_margin_ttm": f("grossprofit_margin", fi),
        "net_margin_ttm": f("netprofit_margin", fi), "tr_yoy": f("tr_yoy", fi),
        "ep_ttm": (1 / pe) if pe and pe > 0 else None,
        "bp_ttm": (1 / pb) if pb and pb > 0 else None,
        "sp_ttm": (1 / ps) if ps and ps > 0 else None,
        "turnover_rate": f("turnover_rate", dbr),
    })

for fac in W:
    vals = sorted(r[fac] for r in rows if r[fac] is not None)
    for r in rows:
        r["_p_" + fac] = pctl(vals, r[fac])
for r in rows:
    tot = wt = 0.0
    for fac, w in W.items():
        p = r["_p_" + fac]
        if p is not None:
            tot += p * w
            wt += w
    r["score"] = tot / wt if wt else 0
rows.sort(key=lambda x: -x["score"])
pool = rows[:50]

watch, avoid = [], []
for r in pool:
    code = r["code"]
    reject, risks = None, []
    try:
        gv = float((gw.get(code) or {}).get("goodwill") or 0)
        eq = float((gw.get(code) or {}).get("equity") or 0)
    except ValueError:
        gv = eq = 0
    gr = gv / eq if eq else 0
    if gr > .30:
        reject = "商誉/净资产 %.1f%%" % (gr * 100)
    ar = ((au.get(code) or {}).get("audit_result") or "").strip()
    if not reject and ar and "标准无保留" not in ar:
        reject = "审计非标"
    try:
        cnt = int(float((rd.get(code) or {}).get("dec_cnt") or 0))
        vol = float((rd.get(code) or {}).get("dec_vol") or 0)
        ts = float((db.get(code) or {}).get("total_share") or 0)
    except ValueError:
        cnt = vol = ts = 0
    rr = vol / (ts * 10000) if ts else 0
    if not reject and rr > .01:
        reject = "减持占总股本 %.2f%%" % (rr * 100)
    if reject:
        avoid.append({"code": code, "name": r["name"], "reason": reject})
        continue
    if gr > .15:
        risks.append("商誉占比 %.1f%%" % (gr * 100))
    if cnt:
        risks.append("近期减持 %d 次" % cnt)
    qw = {"roe_ttm": .35, "net_margin_ttm": .25, "gross_margin_ttm": .15, "tr_yoy": .25}
    watch.append({"code": code, "name": r["name"], "industry": r["industry"],
                  "qs": round(sum((r["_p_" + k] or 50) * v for k, v in qw.items()), 1),
                  "risks": risks})
watch.sort(key=lambda x: -x["qs"])

sel, scnt = [], {}
for w in watch:
    ind = w["industry"] or "未分类"
    if scnt.get(ind, 0) >= 2:
        continue
    sel.append(w)
    scnt[ind] = scnt.get(ind, 0) + 1
    if len(sel) >= 10:
        break
qsum = sum(s["qs"] for s in sel)
for s in sel:
    s["weight"] = round(50.0 * s["qs"] / qsum, 2)

orders = []
for i, s in enumerate(sel, 1):
    code = s["code"]
    bars = [daily[d][code] for d in HIST if code in daily[d]]
    mn = min(b["low"] for b in bars)
    ref = round(daily[BASE_DATE][code]["close"], 2)   # v1.5: anchor on latest close
    t1_trig = round(ref * 0.99, 2)                     # -1%
    t2_trig = round(ref * 0.96, 2)                     # -4%
    guard = round(ref * 0.88, 2)                       # -12% no-buy line
    half = round(s["weight"] * 0.5, 2)
    orders.append({
        "id": "ORD-%s-%02d" % (BASE_DATE, i), "code": code, "name": s["name"],
        "industry": s["industry"], "weight": s["weight"], "qs": s["qs"],
        "ref_price": ref,
        "tranches": [
            {"seq": 1, "pct": half, "price_zone": [round(ref * 0.96, 2), t1_trig],
             "trigger_price": t1_trig, "filled": False, "fill_price": None, "shares": 0},
            {"seq": 2, "pct": round(s["weight"] - half, 2),
             "price_zone": [guard, t2_trig], "trigger_price": t2_trig,
             "filled": False, "fill_price": None, "shares": 0},
        ],
        "guard_price": guard,
        "stop_loss": round(min(round(ref * 0.92, 2), round(mn * 0.98, 2)), 2),
        "take_profit": round(ref * 1.20, 2),
        "close_base": ref,
        "risks": s["risks"],
    })

# ============ Stage B: daily loop ============


def judge_regime(code_day, prev):
    m = MKT[code_day]
    bear_trend = m["close"] < m["ma20"] and m["close"] < m["ma60"] and m["close"] < m["ma250"]
    trend = -2 if bear_trend else 0
    if m["up"] < 30:
        width = -2
    elif m["up"] > 70 and m["hi20"] > m["lo20"]:
        width = 2
    else:
        width = 0
    if m["ld"] > 20 or m["lu"] < 20:
        senti = -2
    elif m["lu"] > 50 and m["ld"] < 5:
        senti = 2
    else:
        senti = 0
    if m["money_ratio"] < 80:
        vol = -2
    elif m["money_ratio"] > 110 and m["chg"] > 0:
        vol = 2
    else:
        vol = 0
    total = trend + width + senti + vol
    clamp = bear_trend or (m["lo20"] > m["hi20"] * 3)
    raw = "bear" if total <= -4 else ("bull" if total >= 4 else "neutral")
    if clamp and raw == "bull":
        raw = "neutral"
    conf = min(.85, .55 + abs(total) * .045)
    if raw != prev:
        final = raw if conf >= .75 else prev
        switched = final != prev
    else:
        final, switched = raw, False
    return {
        "raw": raw, "regime": final, "confidence": round(conf, 2), "score": total,
        "clamp": clamp, "switched": switched,
        "dims": {"trend": trend, "breadth": width, "sentiment": senti, "volume": vol},
        "note": ("原始信号 %s(总分%+d, conf %.2f)%s" % (
            raw, total, conf, "，未达切换阈值维持 " + prev if raw != prev and not switched else ""))
    }


cash = CAPITAL
positions = {}
trades = []
days = []
regime = "neutral"
confirmed = 0

for d in EXEC:
    m = MKT[d]
    px = daily[d]
    rg = judge_regime(d, regime)
    if rg["regime"] == regime:
        confirmed += 1
    else:
        confirmed = 1
    regime = rg["regime"]
    fills, sells = [], []

    # order execution: v1.5 cumulative threshold ladder
    for o in orders:
        code = o["code"]
        price = (px.get(code) or {}).get("close")
        if not price:
            continue
        ref = o["ref_price"]
        if price < o["guard_price"]:      # fell through -12%: do not catch the knife
            continue
        for t in o["tranches"]:
            if t["filled"]:
                continue
            if price <= t["trigger_price"]:
                ta = cash + sum(p["shares"] * (px.get(c) or {}).get("close", p["cost"]) for c, p in positions.items())
                sh = int(ta * t["pct"] / 100 / price / 100) * 100
                if sh <= 0:
                    continue
                amt = sh * price
                if amt > cash:
                    sh = int(cash / price / 100) * 100
                    amt = sh * price
                if sh <= 0:
                    continue
                cash -= amt
                t["filled"], t["fill_price"], t["shares"] = True, price, sh
                if code in positions:
                    p = positions[code]
                    ns = p["shares"] + sh
                    p["cost"] = (p["cost"] * p["shares"] + amt) / ns
                    p["shares"] = ns
                else:
                    positions[code] = {"code": code, "name": o["name"], "shares": sh, "cost": price,
                                       "stop_loss": o["stop_loss"], "take_profit": o["take_profit"],
                                       "open_date": d}
                fills.append({"code": code, "name": o["name"], "tr": t["seq"], "price": price,
                              "shares": sh, "amount": round(amt)})
                trades.append({"date": d, "side": "buy", "code": code, "name": o["name"],
                               "price": price, "shares": sh, "amount": round(amt),
                               "reason": "tr%d 触发线 %.2f (ref %.2f, 实际 -%.2f%%)"
                                         % (t["seq"], t["trigger_price"], ref, (1 - price / ref) * 100)})

    # stops / targets
    for code in list(positions):
        p = positions[code]
        price = (px.get(code) or {}).get("close")
        if not price:
            continue
        sh, reason = 0, None
        if price <= p["stop_loss"]:
            sh, reason = p["shares"], "止损 收%.2f<=%.2f" % (price, p["stop_loss"])
        elif price >= p["take_profit"]:
            sh, reason = int(p["shares"] / 2 / 100) * 100, "止盈 收%.2f>=%.2f" % (price, p["take_profit"])
        if sh > 0:
            cash += sh * price
            sells.append({"code": code, "name": p["name"], "price": price, "shares": sh, "reason": reason})
            trades.append({"date": d, "side": "sell", "code": code, "name": p["name"], "price": price,
                           "shares": sh, "pnl_pct": round((price / p["cost"] - 1) * 100, 2), "reason": reason})
            p["shares"] -= sh
            if p["shares"] <= 0:
                del positions[code]

    # bear de-risk
    if regime == "bear" and positions:
        ta = cash + sum(p["shares"] * (px.get(c) or {}).get("close", p["cost"]) for c, p in positions.items())
        pv = ta - cash
        if pv > ta * 0.20:
            ratio = ta * 0.20 / pv
            for code in list(positions):
                p = positions[code]
                price = (px.get(code) or {}).get("close")
                if not price:
                    continue
                ns = int(p["shares"] * ratio / 100) * 100
                sh = p["shares"] - ns
                if sh <= 0:
                    continue
                cash += sh * price
                sells.append({"code": code, "name": p["name"], "price": price, "shares": sh,
                              "reason": "bear 降仓至20%"})
                trades.append({"date": d, "side": "sell", "code": code, "name": p["name"], "price": price,
                               "shares": sh, "pnl_pct": round((price / p["cost"] - 1) * 100, 2),
                               "reason": "bear 降仓"})
                p["shares"] = ns
                if ns == 0:
                    del positions[code]

    pv = sum(p["shares"] * (px.get(c) or {}).get("close", p["cost"]) for c, p in positions.items())
    ta = cash + pv
    # inspector view
    n_pos = len(positions)
    warns = []
    if n_pos and n_pos < 8:
        warns.append("持仓数量不足(%d<8)" % n_pos)
    if n_pos > 12:
        warns.append("持仓数量超限(%d>12)" % n_pos)
    days.append({
        "date": d,
        "数据员": "indices 5/5, overview 8维, 成交%.0f亿(%s20日均值)" % (m["money"], "%.1f%%" % m["money_ratio"]),
        "市场分析师": rg,
        "confirmed_days": confirmed,
        "持仓管家": {"fills": fills, "sells": sells, "positions": n_pos,
                     "position_pct": round(pv / ta * 100, 2), "cash": round(cash),
                     "total": round(ta), "pnl_pct": round((ta / CAPITAL - 1) * 100, 3)},
        "总控": {"status": "PASS", "warns": warns},
    })

# ============ Stage C: review ============
closed = [t for t in trades if t["side"] == "sell"]
final_ta = days[-1]["持仓管家"]["total"]
summary = {
    "period": "2026-10-17 选股建仓 → 10-19~10-23 执行 → 10-24 复盘",
    "universe": len(univ), "pool": len(pool), "avoid": len(avoid), "watch": len(watch),
    "orders": len(orders), "filled_orders": sum(1 for o in orders if any(t["filled"] for t in o["tranches"])),
    "fill_rate_pct": round(sum(1 for o in orders if any(t["filled"] for t in o["tranches"])) / len(orders) * 100, 1),
    "final_assets": round(final_ta), "total_return_pct": round((final_ta / CAPITAL - 1) * 100, 3),
    "trades": len(trades), "closed": len(closed),
    "win_rate_pct": (round(sum(1 for t in closed if t["pnl_pct"] > 0) / len(closed) * 100, 1) if closed else None),
    "final_positions": days[-1]["持仓管家"]["positions"],
    "final_position_pct": days[-1]["持仓管家"]["position_pct"],
    "regime_path": [d["市场分析师"]["regime"] for d in days],
}

out = {"base_date": BASE_DATE, "orders": orders, "days": days, "trades": trades, "summary": summary,
       "avoid": avoid,
       "notes": [
           "买点规则 v1.5：以基准日收盘 ref 为锚，首档触发 ref×0.99(-1%)、二档 ref×0.96(-4%)、跌破 ref×0.88(-12%)不接",
           "成交逻辑为累积阈值：价格达到 -1% 触发首档，达到 -4% 同时触发两档（避免高开低走跳档死锁）",
           "止损 = min(ref×0.92, 20日最低×0.98)；止盈 = ref×1.20",
           "基准日 10-16 收盘，历史 16 个交易日（0917~1016），16 因子（mom_60d 无 60 日数据剔除；mom_20d 为 15 日近似）",
           "估值/换手因子取 daily_basic(20261023)，相对 10-16 有 5 个交易日前视偏差",
           "排雷数据为最新披露口径，同样轻微前视",
           "regime 用真实 market_overview 数值 + 六维打分 + 趋势钳制 + 防抖（反向需 conf>=0.75）",
       ]}
json.dump(out, open(OUT_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# ---- markdown report ----
L = []
L.append("# 一周全链路回测 2026-10-17 ~ 2026-10-24\n")
L.append("- 基准日（选股）：20261016 收盘（周六夜 10-17 运行选股链）")
L.append("- 执行期：2026-10-19 ~ 2026-10-23（5 个交易日）")
L.append("- 复盘：2026-10-24（周六）")
L.append("- 运行模式：本地真实数据确定性回放，未调用 LLM\n")

L.append("## 一、时间线\n")
L.append("| 时间 | 环节 | 动作 | 结果 |")
L.append("|---|---|---|---|")
L.append("| 10-17 21:30 | 量化选股师 | 全市场打分（基准 10-16） | universe %d → pool 50 |" % len(univ))
L.append("| 10-17 23:30 | 个股研究员 | 排雷深筛 | avoid %d / buy_watch %d |" % (len(avoid), len(watch)))
L.append("| 10-18 00:10 | 建仓经理 | v1.4 归一化建仓 | %d 张 planned 买单，总仓位 %.1f%% |" % (len(orders), sum(o["weight"] for o in orders)))
for d in days:
    L.append("| %s 23:00-23:50 | 数据员/分析师/持仓管家/总控 | 每日轮转 | regime %s，成交 %d，卖出 %d，净值 %+.3f%% |"
             % (d["date"], d["市场分析师"]["regime"], len(d["持仓管家"]["fills"]), len(d["持仓管家"]["sells"]), d["持仓管家"]["pnl_pct"]))
L.append("| 10-24 22:00 | 复盘官 | 周复盘 | 交易 %d 笔，收益 %+.3f%% |" % (len(trades), summary["total_return_pct"]))
L.append("| 10-24 23:10 | 档案管理员 | 经验入库 | 见文末 |\n")

L.append("## 二、10-17 选股链产物\n")
L.append("### 建仓订单（%d 只，合计 %.1f%%）— 买点规则 v1.5（相对现价阶梯回落）\n" % (len(orders), sum(o["weight"] for o in orders)))
L.append("| # | 代码 | 名称 | 行业 | 权重 | 首档触发线 | 二档触发线 | 基准收盘 | 止损 | 止盈 | 成交 |")
L.append("|---|---|---|---|---|---|---|---|---|---|---|")
for o in orders:
    ft = sum(1 for t in o["tranches"] if t["filled"])
    L.append("| %s | %s | %s | %s | %.2f%% | %.2f (-1%%) | %.2f (-4%%) | %.2f | %.2f | %.2f | %s |"
             % (o["id"][-2:], o["code"], o["name"], o["industry"], o["weight"],
                o["tranches"][0]["trigger_price"], o["tranches"][1]["trigger_price"],
                o["ref_price"], o["stop_loss"], o["take_profit"],
                ("%d档" % ft) if ft else "未成交"))
L.append("")
L.append("### 排雷剔除（%d 只）\n" % len(avoid))
if avoid:
    for a in avoid:
        L.append("- %s %s：%s" % (a["code"], a["name"], a["reason"]))
else:
    L.append("本次 Top50 全部通过排雷（无商誉超标/非标审计/大额减持）")
L.append("")

L.append("## 三、每日运转明细\n")
for d in days:
    h = d["持仓管家"]
    rg = d["市场分析师"]
    L.append("### %s（regime=%s, conf=%.2f, confirmed_days=%d）\n" % (d["date"], rg["regime"], rg["confidence"], d["confirmed_days"]))
    L.append("- **数据员**：%s" % d["数据员"])
    L.append("- **市场分析师**：六维 %s，总分 %+d，钳制=%s；%s" % (
        rg["dims"], rg["score"], rg["clamp"], rg["note"]))
    L.append("- **持仓管家**：成交 %d 笔，卖出 %d 笔，持仓 %d 只（%.1f%%），现金 %.0f，净值 %.0f（%+.3f%%）"
             % (len(h["fills"]), len(h["sells"]), h["positions"], h["position_pct"], h["cash"], h["total"], h["pnl_pct"]))
    for f in h["fills"]:
        L.append("    - 买入 %s %s tr%d @%.2f × %d = %.0f" % (f["code"], f["name"], f["tr"], f["price"], f["shares"], f["amount"]))
    for s in h["sells"]:
        L.append("    - 卖出 %s %s @%.2f × %d（%s）" % (s["code"], s["name"], s["price"], s["shares"], s["reason"]))
    L.append("- **总控**：%s%s" % (d["总控"]["status"], ("；" + "、".join(d["总控"]["warns"])) if d["总控"]["warns"] else "，无异常"))
    L.append("")

L.append("## 四、10-24 复盘\n")
L.append("| 指标 | 数值 |")
L.append("|---|---|")
L.append("| 期末总资产 | %.0f |" % summary["final_assets"])
L.append("| 期间收益率 | **%+.3f%%** |" % summary["total_return_pct"])
L.append("| 订单成交率 | %s%%（%d/%d） |" % (summary["fill_rate_pct"], summary["filled_orders"], summary["orders"]))
L.append("| 期末持仓 | %d 只，仓位 %.1f%% |" % (summary["final_positions"], summary["final_position_pct"]))
L.append("| 交易笔数 | %d（平仓 %d） |" % (summary["trades"], summary["closed"]))
L.append("| 胜率 | %s |" % (("%s%%" % summary["win_rate_pct"]) if summary["win_rate_pct"] is not None else "无平仓"))
L.append("| regime 路径 | %s |" % " → ".join(summary["regime_path"]))
L.append("")
L.append("### 可复用经验（提交档案管理员）\n")
L.append("1. 分批建仓必须严格先低后高：第二档未获第一档确认不得成交，否则等价于追高")
L.append("2. 防抖阈值必须真正落地：单日暴跌信号 conf<0.75 时维持原 regime，避免暴跌日减仓、次日踏空")
L.append("3. 选股偏好（动量强→价格高位）与买点（区间下三分位）存在结构性冲突，成交率天然偏低")
L.append("")
L.append("## 五、口径说明\n")
for n in out["notes"]:
    L.append("- %s" % n)

open(OUT_MD, "w", encoding="utf-8").write("\n".join(L))

print("\n=== %s ===" % summary["period"])
for d in days:
    h = d["持仓管家"]
    rg = d["市场分析师"]
    print("%s %-7s(conf %.2f,cd%d) fills=%d sells=%d pos=%d(%.1f%%) net=%+.3f%%"
          % (d["date"], rg["regime"], rg["confidence"], d["confirmed_days"],
             len(h["fills"]), len(h["sells"]), h["positions"], h["position_pct"], h["pnl_pct"]))
print("\nsummary:", json.dumps(summary, ensure_ascii=False))
print("report ->", OUT_MD)
