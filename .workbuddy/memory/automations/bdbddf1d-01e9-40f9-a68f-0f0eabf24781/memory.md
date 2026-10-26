# 持仓管家 automation 执行记忆

## 2026-10-26（首跑，建仓首日）
- 交易日校验通过；market_analyst 已 done，直接开工（未触发等待）。
- regime=neutral / severity=null / confirmed_days=2 → 目标仓位 50%，无降仓动作。
- 10 张建仓买单（ref=20261023）按 v1.5 阶梯执行：仅 2 只回落达标并成交首档——中国动力 900 股@31.23、中科三环 1800 股@10.72；其余 8 只未触发，全部高于 -12% 保护线。
- 结果：仓位 4.74%、现金 95.26%、累计收益 0%、持仓 2 只（<下限 8，warn）；含在途 12 只（恰达上限）。
- 卖出：五类触发全未命中，未生成 sell 单。换仓按 v1.9 关闭，未做任何 rotate 比较。
- 邮件已发（queued=true），HTML 正文已复核非空。check_pipeline --date 20261026 = PASS。
- 遗留暴露：**次档买点与止损线重叠**（中国动力二档 [28.03,30.58] vs 止损 28.82；中科三环二档 [9.73,10.62] vs 止损 10.10），中科三环距二档仅 -0.93%，明日大概率触发，需人工拍板方案 B（止损锚定成交成本×0.92）。

## 复用要点
- 成交价一律取 data/warehouse/daily/<date>.csv 的 close；仓库当日文件存在即无需调 MCP。
- 写 positions.json 后必须让 cash_cny + Σ market_value_cny == total_asset_cny，且 cash_pct 由金额推导，否则 check_pipeline FAIL。
- 部分成交的买单状态写 "partial"，并在 tranche 上回写 fill_date/fill_price/fill_shares/fill_amount。
- 邮件发完必须打开 reports/mail_position_<date>.html 复核正文（曾出现空壳 bug）。
