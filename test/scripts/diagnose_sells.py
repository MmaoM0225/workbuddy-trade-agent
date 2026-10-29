#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""diagnose_sells.py - 诊断回测里为什么卖出次数少（只读，不改任何状态）

复制 backtest_dca_v3 的买卖循环，但把每个卖出机会的拦截原因分开计数：
  - 从未持仓过
  - 持仓期间分数从未到 75
  - 到 75 但被「持有 <20 交易日」挡
  - 到 75 但被「距上次操作 <20 交易日」挡
  - 到 75 但阶段已用尽（已按该档卖过）
  - 真卖出
"""
import json
import os
import sys
from collections import Counter, defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import backtest_dca_v3 as bt  # noqa: E402


def main():
    with open(bt.PARAMS, encoding="utf-8") as f:
        params = json.load(f)
    ex = params["execute"]
    stages = sorted(ex["sell_stages"], key=lambda x: x["min_score"])
    d0 = os.path.join(bt.WD, "daily")
    cal = sorted(x[:-4] for x in os.listdir(d0) if x.endswith(".csv"))
    cal = [d for d in cal if "20201102" <= d <= "20261027"]

    items = bt.build(cal, params, 5)
    hold = {}
    cnt = Counter()
    stage_hist = Counter()
    max_score = {}
    sold_log = []

    seen_f_dist = {}

    for i, d in enumerate(cal):
        for c in list(hold):
            p = items[c]["nav"]
            if i > 0 and not np.isnan(p[i]) and not np.isnan(p[i - 1]) and p[i - 1] > 0:
                hold[c]["value"] *= p[i] / p[i - 1]

        sc = {c: it["score"][i] for c, it in items.items()
              if not np.isnan(it["score"][i]) and not np.isnan(it["nav"][i])}

        # 记录持仓期间的最高分
        for c in hold:
            if c in sc:
                max_score[c] = max(max_score.get(c, 0), sc[c])

        # ---- 卖出判定（逐档，与主脚本一致）----
        for c in list(hold):
            if c not in sc:
                continue
            s0 = sc[c]
            if s0 < stages[0]["min_score"]:
                continue
            cnt["持仓且分数>=75 的 标的天"] += 1
            st = None
            for s in stages:
                if s0 >= s["min_score"]:
                    st = s
            if not st or st["min_score"] <= hold[c]["stage"]:
                cnt["阶段已用尽（该档已卖过）"] += 1
                continue
            if hold[c]["first"] is not None and i - hold[c]["first"] < 20:
                cnt["被 持有<20交易日 挡住"] += 1
                continue
            if hold[c]["last"] is not None and i - hold[c]["last"] < ex["sell_interval_td"]:
                cnt["被 距上次操作<20交易日 挡住"] += 1
                continue
            amt = hold[c]["value"] * st["sell_current_ratio"]
            if amt <= 0:
                cnt["可卖金额<=0"] += 1
                continue
            cnt["★ 实际卖出"] += 1
            stage_hist[st["min_score"]] += 1
            sold_log.append((d, items[c]["name"], round(s0, 1), st["min_score"], round(amt)))
            cost_out = hold[c]["cost"] * st["sell_current_ratio"]
            hold[c]["value"] -= amt
            hold[c]["cost"] -= cost_out
            hold[c]["stage"] = st["min_score"]
            hold[c]["last"] = i
            if hold[c]["value"] < 0.01:
                hold.pop(c, None)

        # ---- 买入（只为了得到持仓集合）----
        seen_f = {}
        for c, it in items.items():
            if c not in sc:
                continue
            f = it["fund"]
            if f in seen_f:
                if sc[c] < sc[seen_f[f]]:
                    seen_f[f] = c
                continue
            seen_f[f] = c
        picked = list(seen_f.values())
        broad = sorted([c for c in picked if items[c]["kind"] == "broad" and sc[c] < 40
                        and items[c]["fund"]], key=lambda c: sc[c])
        ind_pool = [c for c in picked if items[c]["kind"] == "industry" and sc[c] < 40]
        keep = []
        for c in ind_pool:
            rv = items[c].get("roe_chg")
            v = rv[i] if rv is not None else np.nan
            if not np.isnan(v) and v > ex["industry_roe_filter"]["roe_th"]:
                keep.append(c)
        ind = sorted(keep, key=lambda c: sc[c])[:5]
        for c in broad + ind:
            mlt = items[c]["mult"][i]
            if np.isnan(mlt) or mlt <= 0:
                continue
            amt = 10 * mlt
            if c in hold:
                hold[c]["value"] += amt
                hold[c]["cost"] = hold[c].get("cost", 0) + amt
            else:
                hold[c] = {"value": amt, "cost": amt, "stage": 0, "first": i, "last": None}

    print("日历 %s ~ %s  %d 日" % (cal[0], cal[-1], len(cal)))
    print("曾持有过的标的：%d 只；期末仍持有 %d 只" % (len(max_score), len(hold)))
    print()
    for k, v in cnt.most_common():
        print("  %-28s %7d" % (k, v))
    print("\n 卖出档位分布：", dict(stage_hist))
    print("\n持仓期间最高分分布（曾持有过的标的）：")
    buckets = [(0, 40), (40, 50), (50, 60), (60, 70), (70, 75), (75, 85), (85, 101)]
    for lo, hi in buckets:
        n = sum(1 for v in max_score.values() if lo <= v < hi)
        print("   [%2d,%3d) %3d 只" % (lo, hi, n))
    from collections import Counter as _C
    by_year = _C(x[0][:4] for x in sold_log)
    print("\n按年卖出笔数：", dict(sorted(by_year.items())))
    print("卖出总额 %.0f 元" % sum(x[4] for x in sold_log))
    stuck = [c for c in hold if hold[c].get("stage", 0) > 0]
    print("期末仍持有且已被部分卖出（卡在某档）的标的：%d 只" % len(stuck))
    print("\n前 10 笔卖出：")
    for x in sold_log[:10]:
        print("   %s %-10s 分数%.1f 档%.0f 卖出%s元" % x)
    print("\n所有持仓的最高分排序（前 15）：")
    for c, v in sorted(max_score.items(), key=lambda kv: -kv[1])[:15]:
        print("   %-10s 最高分 %.1f" % (items[c]["name"], v))


if __name__ == "__main__":
    main()
