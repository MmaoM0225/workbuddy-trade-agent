import shutil

SRC = "E:/cashfree/agent/knowledge/rules.md"
DST = "E:/cashfree/agent/test/knowledge/rules.md"

shutil.copyfile(SRC, DST)

new_rules = [
    ("R-007", "**定性标签让位于数值**：判定引用 market_overview 的 summary 标签（如\"缩量震荡\"\"价值主导\"\"板块全面下跌\"）时，必须改为引用同接口的数值维度（trade/updown/rotation/sector_ranking）；标签与数值矛盾时在 tag_conflicts 中留痕，不得只引标签",
     "2026-W43 复盘：10-23 三处标签与实测矛盾（缩量 vs 放量117%、价值主导 vs 成长领涨、板块全面下跌 vs 84%行业上涨）", "2026-10-25", "active"),
    ("R-008", "**比例异常即单位错误**：任一计算出的占比 >100%（如\"减持占总股本 190%\"）→ 立即核查两侧单位。已知：tushare stk_holdertrade.change_vol 单位为「股」，daily_basic.total_share 单位为「万股」，比值须除以 10000",
     "2026-W43 复盘：研究员误把减持量(股)当万股，误杀排名第 2 的柳工", "2026-10-25", "active"),
    ("R-009", "**筛选层决定结果**：选股链路存在市值/数量截断层（如\"市值 top300 → 200 只\"）→ 改为全市场打分后再筛；若截断层结果与全量结果重合率 <50%，判定该筛选层失效必须移除",
     "2026-W43 复盘：top300 口径与全市场 1802 只打分 Top50 仅重合 1 只(2%)", "2026-10-25", "active"),
    ("R-010", "**预算耗尽不等于标的不足**：建仓因\"总仓位已满\"少建标的 → 核对持仓数量是否达 params.min_holdings(8)；未达须从候选池补入次优标的，并在 notes 记录替换原因",
     "2026-W43 复盘：v1.3 公式下 target 全部撞 15% 上限，组合只剩 3-4 只", "2026-10-25", "active"),
    ("R-011", "**订单不给金额**：建仓经理生成买单时只写 target_weight_pct 与 tranches[].pct，禁止写金额/股数；金额与股数由持仓管家执行时按实际总资产（现金+持仓市值）计算",
     "2026-W43 复盘：v1.3 订单预置固定金额，与执行时点净值脱节", "2026-10-25", "active"),
]

lines = [
    "| %s | %s | %s | %s | %s |" % r for r in new_rules
]

with open(DST, "a", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")

print("appended %d rules -> %s" % (len(new_rules), DST))
