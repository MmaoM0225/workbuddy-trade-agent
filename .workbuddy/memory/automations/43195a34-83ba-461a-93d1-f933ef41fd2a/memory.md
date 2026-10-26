# market_analyst 自动化执行记忆

## 2026-10-26（首次正式运行）
- 交易日校验通过（tushare trade_cal is_open=1）；data_officer 已于 23:10 done，wait 一次即通过，无需等待。
- 基准日 20261026，数据齐全（meta.json degraded=false，9 个文件齐备）。
- 判定结果：**regime=neutral，severity=null，score=0，confidence=0.55，confirmed_days=2**（与 20261023 的 neutral 同向，未切换）。
- 六维：趋势 -2（空头排列+20日 -5.48%）、宽度 0、情绪 +2（涨停53/跌停3）、量能 0（20日均值 97.65%）、资金 0（北向 +25.39 亿）、板块 0（上涨行业 48.39%，资金净流出）。
- 邮件 SENT 成功；check_pipeline.py PASS。

### 2026-10-26 二次运行（23:25，重跑）
- 触发原因：首跑后 market_analyst 被置 undo（reason=rerun-required-manual-backfill-invalid），data_officer 于 23:20 重新取数 done 后重跑。
- 重跑结果与原判定完全一致：neutral / severity=null / score=0 / confidence=0.55 / confirmed_days=2 / risk=medium。数据值未变（同一交易日的同批数据），验证了判定可复核。
- 固化做法：重跑同一交易日时，confirmed_days 按「上一判断日(20261023)=1 → +1 = 2」计算，**不要**在自己作废产物的基础再 +1（会重复计数）。
- 邮件 SENT 成功，产物 reports/mail_regime_20261026.html。

### 经验要点（下次沿用）
- 本次触发 3 条标签冲突：SECTOR_WIDTH「全面下跌」vs 实际 48.39% 板块上涨；STOCK_WIDTH「普涨」vs 涨股比仅 40.38%（跌多涨少）；VOLUME「缩量震荡」掩盖了 120/250 日均值仅 64.76%/68.20% 的中期缩量。已按数值判定并记入 tag_conflicts。
- 「涨停>50 且 跌停<5」会给情绪 +2，但当日可能同时出现跌多涨少——属结构性躁动，需靠 risk_level 与 tag_conflicts 做平衡，不要仅凭该标签下调风险。
- 龙虎榜口径：净买 Top10 与净卖 Top10 求和对比（本次 +11.78 亿 vs -18.55 亿）比单看榜首更稳。
- 板块资金方向用「流入 Top10 合计 vs 跌幅榜净流出合计」对比（本次 +50.26 亿 vs -201.59 亿），比看上涨行业占比更能反映资金面。
- 邮件脚本 send_report_mail.py --type regime --date <YYYYMMDD> 一次成功，失败不阻塞。
