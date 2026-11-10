# 总控巡检（inspector）执行记忆

## 2026-10-26（首次自动化运行，成功）
- 交易日确认：tushare trade_cal SSE 20261026 is_open=1。数据基准 data/daily_20261026 齐备无滞后。
- 依赖等待：position_manager 首次 wait 即 ready，未触发重试预算。
- 结论：无 CRITICAL。check_pipeline.py --date 20261026 退出码 0 PASS；9 任务全 done；5 个 state 文件 + trades.jsonl 全 PASS；10 张订单止损止盈齐全（缺项 0）。
- 产出：reports/daily_20261026.md + reports/mail_inspect_20261026.html，邮件 SENT（1920442561@qq.com，queued=true），已 commit+push（2cbce5d）。
- 遗留 WARN（下轮需复查）：
  1. ORD-20261023-002/-008 订单级 status=filled 但 tranches[0].status 仍 pending，靠 filled_tranches=[1] 表达——明日执行有首档重复买入风险，需持仓管家统一口径。
  2. orders.json 今日被重建（git 9345043，持仓管家重写导致 ID 错位），单一写者原则被破坏，需明确 orders.json 写者边界；orders.json.bak_20261026 已入库。
  3. 仓位 4.74% vs 目标 50%（建仓期，跟踪 R-006 10 日过期倒计时，剩 9 个交易日）。
  4. 次档买点与止损线重叠（中国动力/中科三环），中科三环二档距收盘仅 -0.93%，明日大概率触发，待用户拍板方案 B。
  5. 趋势维度已判 bear（均线完全空头排列），总分 0 靠情绪 +2 拉回 neutral，跌破 -6 转 bear+light 将禁止新建仓。
- 经验：邮件正文回填行会造成"文件与邮件差一行"，下轮应在发送前把邮件状态行写成终稿再发，避免重发两次。

## 2026-10-27（第二次运行，成功；于 10-28 00:01 触发）
- 跨零点触发处理：时钟已过 00:00（10-28）但 data/daily_20261028 不存在、行情未产生，按步骤 1「取最新目录」规则将基准定为 20261027（与 position_manager done 日期一致），未命名 daily_20261028.md 以免次日被覆盖。此判定后续沿用。
- 交易日确认：trade_cal SSE 20261027/061028/061029/061030 均 is_open=1。
- 依赖等待：position_manager 首次 wait 即 ready（退出码 0），未消耗重试预算。
- 结论：无 CRITICAL。check_pipeline --date 20261027 退出码 0 PASS；日频 4 任务全 done；5 个 state 文件 + trades.jsonl 全 PASS；9 张订单缺项 0。
- 产出：reports/daily_20261027.md + reports/mail_inspect_20261027.html，邮件 SENT，已 commit+push（81d994f）。
- 上轮遗留 1、2 已修复：订单级 status 统一为 partially_filled 且 tranches 一一对应；orders.json 本日仅就地改单档，未整表重写。
- 本轮新触发项：regime 由 neutral 切 bear+light（score -6、conf 0.82，10-28 生效，cap 70→60）→ 命中升级规则，报告末尾追加「建议实时会商」。
- 遗留 WARN（下轮复查）：
  1. bear+light 下在途 16 档既有委托是否冻结，待昴拍板（10-28 开盘前需定论）。
  2. 仓位 38.07% vs 上限 70，缺口 31.93pct（建仓期）；R-006 有效期剩 8 个交易日。
  3. 中航机载 -4.24%，航空装备Ⅱ全市场跌幅榜首，5 日主力净流出 26.05 亿，距止损 7.48%。
  4. 振华重工 seq2（4.05，差 1.22%）、长源电力 seq2（3.70，差 1.60%）10-28 大概率触发；现金 61.9 万 vs 16 档全触发需约 66.1 万，资金略紧。
  5. 5 个周度任务仍 undo（replay-v29-reset），需在周六 21:30 窗口前复位，否则下周无新候补。
- 经验：邮件状态行本轮采用「先写终稿再发送」写法（预填 SENT），文件与邮件内容完全一致，未出现上轮的差一行问题，后续沿用。

## 2026-10-28（第三次运行，成功；当日 23:52 触发，无需跨零点处理）
- 交易日确认：trade_cal SSE 20261028 is_open=1。数据基准 data/daily_20261028 齐备（10 文件）无滞后；近四个交易日数据连续，未触发「连续 2 日缺失」。
- 依赖等待：position_manager 首次 wait 即 ready，未消耗重试预算。
- 结论：无 CRITICAL。check_pipeline --date 20261028 退出码 0 PASS；日频 4 任务全 done；6 个 state 文件 + trades.jsonl 全 PASS；9 单 27 档缺止损止盈 0。当日成交 0 买 0 卖（市场普涨，16 档限价全未触及）。
- 参数线已升到 v3.2（params_current.txt），v3.2 落地熔断「-15% 降到 40%、回到 -8% 解除、无冻结、不清仓」。
- regime 未切换（20261027 bear/light → 20261028 bear/light，防抖维持，confirmed_days 1→2；纯分数为 0 属 neutral 但 confidence 0.55 < 0.75），三项升级规则均不触发，本轮未追加「建议实时会商」。
- 产出：reports/daily_20261028.md + reports/mail_inspect_20261028.html，邮件 SENT，已 commit+push（39e1750，只提交本报告 3 个文件，未打包其他 agent 的未跟踪文件）。
- 上轮遗留跟踪：W-1（bear 下 16 档是否冻结）仍未拍板，已转 P11；W-2 仓位缺口转为「资金配额排满」（38.02+在途 31.07=69.09% > cap 60%）；W-3 中航机载反弹降级观察；W-5 周度 5 任务仍 undo。
- 遗留 WARN/info（下轮复查）：
  1. P11 未裁决：bear 期间既有订单剩余限价档是否放行（影响 16 档命运）。
  2. R-006 到期倒计时：9 单 20261106 集中到期，R-015 要求 T-5（约 20261030）出处置方案；持仓 9 只已在 min_holdings=8 下沿。
  3. 东华软件距止损 5.07%、中国动力 5.47%，为最近两只；两者同时也是最接近成交的档位（距 0.80%/2.34%）。
  4. 5 个周度任务仍 undo（周六 windows），若不复位于订单到期后无新候补。
  5. bull_rush_rule 已于 v3.3 打开但 pending P4 未销项（回撤 +5.5pp）。
  6. 指数定投链路（index_signal/index_orders/index_portfolio/nav_history）今日新上线，尚未纳入 check_pipeline 的 5 文件核验范围，需明确是否纳入或隔离。
- 经验：git 只 add 本任务产出的 3 个文件（工作区有大量其他 agent 的未跟踪文件），避免打成杂烩提交。

## 2026-10-29（第四次运行，成功；当日 23:56 触发）
- 交易日确认：trade_cal SSE 20261029 is_open=1。数据基准 data/daily_20261029 齐备（10 文件，含 hot_board.json），degraded=false；近三交易日连续，未触发「连续 2 日缺失」。
- 依赖等待：position_manager 首次 wait 即 ready，未消耗重试预算。
- 结论：无 CRITICAL。check_pipeline --date 20261029 退出码 0 PASS；日频 4 任务全 done；5 个 state 文件 + trades.jsonl 全 PASS；9 单订单级止损止盈缺项 0（注意：stop_loss/take_profit 在**订单级**，tranche 级没有该字段，按 tranche 遍历会误报 27 项缺失，下轮须按订单级核验）。
- regime 未切换（20261028 bear/light confirmed_days 2 → 20261029 bear/light confirmed_days 3），三项升级规则均不触发，未追加「建议实时会商」。
- 当日成交 2 笔（东华软件 seq3 6.23、长源电力 seq2 3.70，共 28,895 元），卖出 0 笔；总资产 998,336，仓位 40.85%，累计 -0.17%，当日跑赢上证 0.71pp。
- 产出：reports/daily_20261029.md + reports/mail_inspect_20261029.html，邮件 SENT。git 本地 commit 成功（605fa34），**push 失败**（github.com:443 代理连接超时），待网络恢复后补推。
- 遗留 WARN/info（下轮复查）：
  1. P11 仍未拍板：持仓管家本日改判 bear 下剩余限价档「不算新建仓、允许成交」，实际影响 2 档，需昴固化。
  2. 在途 28.17% + 已用 40.85% = 69.02% > cap 60%，补仓可用额度 0；转 bull 需先释放在途。
  3. regime 临近 heavy：score -6 距 -8 仅 2 分，risk_level 已升 high；次日若 ≤-8 且 confirmed≥2 将降仓至 20%。
  4. R-006 到期倒计时：9 单 20261106 到期，剩 5 个交易日，R-015 要求 20261030 前出处置方案。
  5. 东华软件 -5.07%，距止损 3.04%（三档已满仓 filled），为最近止损标的。
  6. 数据标签冲突 2 high（STOCK_WIDTH / SENTIMENT）+ margin 维度缺失，需反馈数据员。
  7. 5 个周度任务仍 undo（周六窗口）。
- 经验：沿用「先写终稿再发送」的邮件状态行写法，文件与邮件一致；push 失败不阻塞任务收尾，但须在记忆与汇报中标注待补推。

## 2026-10-30（第五次运行，成功；于 10-31 00:53 触发）
- 跨零点补跑：触发时点已过周六 00:00（20261031 is_open=0），但 position_manager 00:51 才 done(20261030)、inspector 上一完成日 20261029 → 按「取最新数据目录」把基准定为 20261030，未按非交易日跳过（同 20261027 先例），报告命名 daily_20261030.md。
- 依赖等待：首次 wait 即 ready，未消耗重试预算。结论无 CRITICAL；check_pipeline --date 20261030 退出码 0 PASS；6 个 state 文件 + trades.jsonl(16 行) 全 PASS。
- **订单止损止盈核验口径修正**：orders.json 含 1 张卖单（ORD-20261030-S001 东华软件止损），卖单无 stop_loss/take_profit 属设计豁免，只核 9 张买单 → 缺项 0。此前「按 tranche 遍历误报」的坑已避免。
- 当日：上证 3599.02(-1.44%)，组合 -0.15%（超额 +1.29pp）；成交 2 买（中国动力 seq3、中航机载 seq2）1 卖（东华软件 -8.03%，进 20 日冷却）；仓位 38.92%，持仓 8 只。
- regime 未切换（bear/light confirmed_days 3→4），升级规则三项均不触发，未追加「建议实时会商」。
- 产出：reports/daily_20261030.md + mail_inspect_20261030.html，邮件 SENT，commit+push 成功（449e0dd，连带补推 10-29 积压提交）。
- 新触发 WARN：**market_analyst 卡 doing**（23:11 起无更新、artifact=null、缺 mail_regime_20261030.html；regime.json 23:30 已完整产出）。持仓管家等待 45 分钟耗尽后凭数据新鲜度自检继续执行。若 20261102 未复位升 critical。
- 延续 WARN：R-006 T-5 处置方案逾期（9 单 20261106 到期）；在途 23.98% 占满 cap（38.92+23.98=62.90% > 60，补仓为 0）；score -6 距 heavy 仅 2 分且 risk_level=high；数据标签冲突 2 high + margin 缺失 + 龙虎榜 net_amount 单位（万元 vs 亿）；周度 5 任务仍 undo（今晚 21:30 起窗口）。
- 待拍板：P11（bear 下剩余限价档放行，今日据此成 2 档）、P12（单季 ROE<0 且净利率<5% 是否写入逻辑破坏）、P2（veto 与卖出判据对齐）。
- 经验：只巡检不修状态——market_analyst 卡 doing 属其他 agent 的写者边界，本任务只记录并列入下一步动作，不代为置 done。

## 2026-11-02（第六次运行，成功；当日 21:00 触发，流水线 20:40 提前完成）
- 交易日确认：trade_cal SSE 20261102 is_open=1。数据基准 data/daily_20261102 齐备（10 文件含 hot_board），degraded=false，无滞后；连续 7 个交易日数据完整。
- 依赖等待：position_manager 首次 wait 即 ready，未消耗重试预算。
- 结论：无 CRITICAL。check_pipeline --date 20261102 退出码 0 PASS；9 任务中 8 done、1 undo；8 个 state 文件 + trades.jsonl 全 PASS；9 张买单止损止盈缺项 0（filled 卖单豁免）。
- 上期遗留 W-1（market_analyst 卡 doing）已复位：本日 done @20:35、artifact 完整、regime 邮件已发。
- **新 WARN W-1（本轮最重要）**：position_builder 20261101 undo(upstream-not-ready)——wait 仅 11 分钟放弃，researcher 16:04 才 done（晚 10 分钟），导致 20261030 的 17 项 watchlist 未转计划单，本周沿用 20261023 老计划集；若 11-08 再现升 critical。属「wait 预算过短」的结构性缺陷。
- regime 未切换（bear/light confirmed_days 4→5，score -6→+2，conf 0.64<0.75 被防抖拦下），三项升级规则均不触发，未追加「建议实时会商」。
- 产出：reports/daily_20261102.md + reports/mail_inspect_20261102.html，邮件 SENT，commit 8d20f48 已 push 成功。
- 遗留 WARN/info（下轮复查）：
  1. position_builder 复位与 wait 预算放宽（建议 ≥30min）——最高优先。
  2. R-006 处置方案逾期第 2 个交易日，9 单 20261106 到期（剩 4 个交易日），且无新增计划单可替补。
  3. 在途 23.98% + 已用 39.30% = 63.28% > cap 60%，topup 连续 3 日为 0（新增 P13 待拍板）。
  4. regime 反转临界：score +2 已入 neutral 区间，次日若 ≥6 则切 neutral（cap 60→70、解禁新建仓），与在途 24% 冲突。
  5. 数据质量：SECTOR_WIDTH 标签方向完全相反等 4 项标签失真 + margin 缺失，已连续多日。
  6. 数据员 20:29 提前取数，news/hot_news/hot_board 为 20:29 快照（缺 20:29~23:00 快讯）。
  7. 指数链路 index_signal/index_orders 停在 20261029，跨两个交易日未更新，需确认停用/周频/漏跑。
- 经验：日报「运行时间」行可直接写实际触发时点；本轮按「先写终稿（预填 SENT）→ 发送 → 结果一致」做法，文件与邮件无差行问题，继续沿用。

## 2026-11-03（第七次运行，成功；当日 21:00 触发，流水线 20:33 提前完成）
- 交易日确认：trade_cal SSE 20261103 is_open=1，下一交易日 20261104。数据基准 data/daily_20261103 齐备（10 文件含 hot_board），无滞后；连续 5 个交易日完整。
- 依赖等待：position_manager 首次 wait 即 ready，未消耗重试预算。
- 结论：**首次出现 CRITICAL**。check_pipeline --date 20261103 退出码 0 PASS；8 任务 done、1 undo（position_builder）；8 个状态文件 + trades.jsonl 全 PASS；9 张买单止损止盈缺项 0（卖单豁免）。
- **C-1 升级（本轮核心）**：position_builder 连续 2 个周度周期失败（10-25、11-01，复盘官侧记录佐证 11-01 那条），orders.json 计划集停在 20261023 且按 neutral 70% 编制，与当前 bear cap 60% 不同口径；12 档全触发将达 63.72% 超 cap 3.72pp；R-006 到期 20261106 剩 3 个交易日。上期曾承诺 11-08 再现才升 critical，本期以「连续 2 周期 + 到期窗口 3 日 + wait 预算未修」为由提前升级，报告中已写明升级依据。
- 新 WARN W-2：orders.json 中国动力订单级 sl=29.01/tp=37.84 未随 20261030 第三档成交重算（实际应 28.64/37.36），属数值陈旧非缺失，不触发会商；已列下一步动作由持仓管家校正。
- W-3：数据员 20:02 提前取数致 market_overview 七维度整块 stale（6 项 11-02、valuation 10-29），meta.market_overview_stale=true 但 degraded=false 口径不一致；市场分析师改用 tushare+仓库自算，处置正确。
- regime 未切换（bear/light，score +2→-6，confirmed 5→6，switched=false）；三项升级规则均不触发，未追加「建议实时会商」。
- 指数链路 as_of 推进到 20261030（此前 20261029），仍跨 11-02/11-03 两日未更新，仍未纳入 check_pipeline。
- 产出：reports/daily_20261103.md + reports/mail_inspect_20261103.html，邮件 SENT，commit 78df60d 已 push 成功。
- 遗留（下轮复查）：① C-1 必须在 20261104 前闭环，否则下周无买单；② R-006 到期 20261106，T-5 方案逾期 4 日；③ 在途 23.98% 占满 cap，topup 连续 4 日为 0；④ score -6 距 heavy 仅 2 分；⑤ 数据标签失真连续 6 日；⑥ 指数链路三选一；⑦ P13/P11/P12/P2 待拍板。
- 经验：critical 升级与既往承诺冲突时，在报告里显式写出「提前升级的理由」，比默默改判或死守旧承诺都更有用。

## 2026-11-04（第八次运行，成功；当日 21:00 触发，流水线 20:33 提前完成）
- 交易日确认：trade_cal SSE 20261104/05/06 均 is_open=1。数据基准 data/daily_20261104 齐备（10 文件含 hot_board），degraded=false，无滞后。
- 依赖等待：position_manager 首次 wait 即 ready，未消耗重试预算。
- 结论：**1 CRITICAL（C-1 延续）+ 7 WARN + 4 INFO**；check_pipeline --date 20261104 退出码 0 PASS；8 任务 done、1 undo（position_builder）；6 个状态文件 + trades.jsonl(16 行) 全 PASS；9 张买单止损止盈缺项 0（卖单豁免）。
- **C-1 加重而非新升**：position_builder 仍 undo @20261101（状态零变化），但 7 张在挂单 20261106 即第 10 个交易日到期（T-3→T-2），到期后 12 档全废且无新计划单递补 → 组合只剩 8 只存量、框架空转。报告中写明「维持 critical 而非新升」的理由。
- 当日：0 买 0 卖（连续第 3 个零成交日），组合 +0.33% vs 上证 +2.16%（超额 -1.83pp），累计 +1.38% vs -0.12%（超额 +1.50pp），净值创高 1,013,843 回撤归零；仓位 39.94%，在途 23.98% → 63.92% > cap 60。
- regime 未切换：score +4（六维 -2/0/0/+2/+2/+2），纯分数映射 bull → 趋势钳制（close 3686.17 < MA20 3707.63）降 neutral → conf 0.73 < 0.75 拦下，维持 bear/light，confirmed_days 7。三项升级规则均不触发，未追加会商。
- 新 WARN：W-1 中国动力订单级 sl/tp 仍陈旧（29.01/37.84 vs 应 28.64/37.36，第 2 日未修，属数值陈旧）；W-5 指数链路 as_of 仍停 20261102（滞后 2 个交易日）；W-6 数据员连续第 3 日 20:01 提前取数；W-7 score 差 0.02 即切 neutral，与在途 24% 冲突（P14）。
- 产出：reports/daily_20261104.md + reports/mail_inspect_20261104.html，邮件 SENT（queued=true），git 本地 commit 1098602 成功，**push 两次均失败**（github.com:443 代理 127.0.0.1 无法连接），待网络恢复后随次日提交补推。
- 经验：巡检脚本 check_pipeline 的 dragon_tiger 计数只读 net_buy_top10 长度（10），与 meta 的 84 条/72 只不冲突，报告中须显式说明避免误判为数据缺失。

## 2026-11-05（第九次运行，成功；当日 21:00 触发，流水线 20:34 提前完成）
- 交易日确认：trade_cal SSE 20261105 is_open=1。数据基准 data/daily_20261105 齐备（10 文件含 hot_board），degraded=false，无滞后；market_overview_stale=false（较 11-03/04 的整块泛化有改善）。
- 依赖等待：position_manager 首次 wait 即 ready，未消耗重试预算。结论：**1 CRITICAL + 7 WARN + 4 INFO**；check_pipeline --date 20261105 退出码 0 PASS；8 任务 done、1 undo（position_builder）；6 个状态文件 + trades.jsonl(16 行) 全 PASS；9 张买单订单级止损止盈缺项 0（已完成卖单豁免）。
- **regime 首次切换（本轮核心，命中升级规则）**：bear/light（10-27 起连 7 日）→ neutral，score +2→+8、conf 0.73→0.85、confirmed_days 重置 1、cap 60→70、**effective_from=20261106**。前两次尝试（11-02 conf 0.64、11-04 conf 0.73）被 anti-flip 拦下。报告末尾已按规则追加「建议实时会商」，并列 3 条议程（建仓节奏 / cap70×在途 / C-1 与到期赛跑）。
- **C-1 性质变化（关键判断）**：position_builder 仍 undo @20261101，但 regime 切 neutral 后 orders.json 顶层 neutral/70 口径**自动对齐**，「12 档全触发 63.91% 超 cap」的超限风险消解；真正未消解的是「计划集停在 20261023 参考价」+「11-09 盘前 R-006 失效」。按"超过 10 日"口径今日为第 9 个交易日 → **11-08 00:10 是 position_builder 最后一次机会**。报告中写明维持 critical 而非新升的理由。
- 当日：0 买 0 卖（连续第 4 个零成交日，最紧淮河能源 seq2 差 2.96%），组合 −0.02% vs 上证 +0.10%（超额 −0.12pp），累计 +1.36% vs −0.02%（超额 +1.38pp），回撤 0.00%；仓位 39.93%，在途 23.98% → 63.91%，明日 cap 70 后 room = 6.09pp（topup 连续 6 日为 0 后首次可出单）。
- 新 WARN：**W-3 R-006 口径未统一（P13）**——params 写"超过 10 日"（11-09 失效）vs 持仓管家写"满 10 日"（11-06 到期），两读法对应明日 room 分别为 6.09pp 与 30.07pp，必须先定；W-7 拥挤度**日频 45.09% 首破 warn_pct 45**（MTD 40.77% 仍升温档，新增 P15）；W-5 指数链路 as_of 停 20261103（滞后 2 日，index_plan_20261104.md 已出但 state 未推进）；W-6 数据员连续第 4 日 20:01 取数；W-1 中国动力 sl/tp 陈旧第 3 日；margin 两融缺失第 7 日。
- 产出：reports/daily_20261105.md + reports/mail_inspect_20261105.html，邮件 SENT（queued=true）。git 本地 commit b8f4e84 成功，**push 失败**（schannel SSL/TLS handshake failed），与 11-04 的 1098602 一并待补推。
- 经验：① regime 切换会使旧计划集的"口径错误"自动转为正确，判断 C-1 影响时必须重算而非照抄上期措辞；② orders.json 顶层 regime 只是编制时快照，核验"口径是否一致"要看当日 cap 而非顶层字符串；③ 巡检报告里的"顺序决定额度"（先作废 vs 先补仓）是可执行结论，比单列风险更有用。

## 2026-11-06（第十次运行，成功；于 11-07 13:26 周六补跑）
- **补跑判定（本轮最关键）**：触发时点 13:26 为周六非交易日，但 20261106（周五）流水线 20:40 已全部收官而 `reports/daily_20261106.md` 缺失（inspector 上次 done=20261105）→ 按步骤 1「取最新数据目录」补跑 20261106，报告名与 task_status date 均取**数据基准日** 20261106，未按非交易日跳过、未写 skip_log（沿用 10-27/10-30 先例）。判据：存在「未巡检的交易日 + 完整数据 + 下游已 done」就必须出报告，否则该交易日永久丢失。
- **trade_cal 不可用**：`mcp__tushare__trade_cal` 未注入（westock-mcp auth-required 连带阻断连接器配置下发）。未改脚本、未用 mcp.json 直连兜底，改由三源交叉确认交易日：warehouse CSV 存在 + meta.trading_day + regime.data_basis 的 trade_cal 记录。
- 依赖等待：position_manager 首次 wait 即 ready，预算 0 消耗。结论：**1 CRITICAL + 8 WARN + 3 INFO**；check_pipeline --date 20261106 退出码 0 PASS；8 任务 done、1 undo（position_builder）；6 个 state 文件 + trades.jsonl(16) 全 PASS；10 张买单订单级 sl/tp 缺项 0（已完成卖单豁免）；R-023 逐个核对 12 档挂单价均高于止损线。
- **C-1 维持 critical（第 4 日，性质第二次变化）**：position_builder 仍 undo @20261101 零变化，orders.json 顶层 date 仍 20261023（已运行 11 个交易日）。11-05 切 neutral 曾让「超 cap」风险消解，**11-06 又切回 bear/light(cap60) 且 12 档 11-09 全到期** → 风险形态由「超限」转为「**11-09 起无单可执行、框架空转**」。窗口只剩 11-08 00:10 一次。
- **regime 第 3 次 whipsaw（命中升级规则）**：neutral 仅维持 1 日即切回 bear/light，score +8→-6、conf 0.82、cap 70→60、confirmed_days 重置 1、**effective_from=20261109**；当日交易仍按 regime_prev(neutral/70)，防前视正确。报告末尾追加「建议实时会商」三议程（11-09 三事件顺序 / C-1 兜底 / P13+P17 口径固化）。
- **11-09 = 三事件叠加日**：bear cap60 生效 + 12 档到期释放 23.98% 在途 + 2 张 A 单（6.37pp）开盘成交，同日发生，额度顺序未定。
- 本轮新记录：P19 补仓单「单档 100%」与 check_pipeline「每买单 ≥2 档」互斥（持仓管家以 2 档×50% 同价同日绕过并通过）；P18 concentrate 写 trades.jsonl 用扁平结构、首个 bull 日必 FAIL；P16 qs_map 读 watchlist 而 8 只持仓全不在其中、topup 排序退化为原序。
- 当日：0 买 0 卖（连续第 5 个零成交日），组合 -0.4657% vs 上证 -1.1039%（超额 +0.64pp），累计 +0.89% vs -1.12%（超额 +2.01pp），仓位 39.65%、8 只、回撤 -0.48%；topup 首次落地。
- 产出：reports/daily_20261106.md + reports/mail_inspect_20261106.html，邮件 SENT（queued=true，已核验正文含会商段）。commit 7e3752b 本地成功，**push 失败**（github.com:443 经 127.0.0.1 代理拒连），与 11-04 的 1098602、11-05 的 b8f4e84 一并待补推（已连续 3 次）。
- 经验：① 补跑时「今天是否交易日」与「是否存在未巡检交易日」是两个问题，后者优先；② 连接器不可用不等于任务阻塞，指标能用本地三源交叉验证就不该停；③ 升级规则按**数据基准日**的事件判（11-06 的 regime 切换），不按触发日判（11-07）。

## 2026-11-09（第十一次运行，成功；当日 21:01 触发，流水线 20:42 提前完成）
- 交易日确认：trade_cal SSE 20261109 is_open=1（tushare 连接器恢复正常，上一轮 11-06 是未注入）。数据基准 data/daily_20261109 齐备 11 文件、无滞后，但 **degraded=true**。
- 依赖等待：position_manager 首次 wait 即 ready，预算 0 消耗。
- 结论：**0 CRITICAL + 6 WARN + 6 INFO**（本轮首次无 critical）。check_pipeline --date 20261109 **退出码 1 FAIL**，唯一失败项 market_overview.json: empty；答案在于是**单日缺失**（11-05/06 均 8 维度完整），未过「连续 2 日」critical 门槛。9 任务 8 done + position_builder undo。
- **C-1 首次降级（本轮核心判断）**：position_builder `undo @20261107 21:13 reason=stale-watchlist`。读 reports/pb_status_20261107.html 后发现 0 单是三条独立阻断的共同结果，其中 **R-001「bear/light 禁止新建仓」单独就足以判定 0 单** —— 建仓经理**业务结论正确，错的是状态语义**（规则性禁买应记 done(reason=regime-blocked) 而非 undo）。叠加订单侧风险已被 R-006 到期出清 + topup 4 张 A 单（13.30pp）消解，故由 critical 降 warn 并写明理由。**教训：此前 4 轮 critical 部分是误判，根因是把「没跑」和「跑了但按规则禁买」混为一谈；判 C-1 必须先读 pb_status 报告，不能只看 task_status。**
- 订单侧重大变化：7 张 ORD-20261023-* 第 11 个交易日按 R-006 全部 expired，**12 档作废、在途 23.98%→0**；最紧淮河能源 seq2 挂单 3.04 vs low 3.16（差 3.95%）不成交，到期与成交机会无冲突。topup 首次有额度（14.30pp）→ 出 4 张 A 单 13.30pp（龙佰/国货航/长源/振华）。
- 当日成交：2 买 0 卖（中远海控 1900@17.45、中航机载 2500@11.61，均开盘价市价）。总资产 1,006,903，当日 -0.2007% vs 上证 +0.3183%（超额 -0.52pp），累计 +0.6903% vs 基准 -0.80%（超额 +1.49pp），仓位 45.70%、8 只、熔断未触发（回撤 -0.4847%）。
- regime 未切换（bear/light，score -6→+2，conf 0.64 仍 <0.75 被防抖拦下，cd 1→2，cap 60，eff 20261110，switched=false）。三项升级规则全不触发，本轮**不追加会商**。
- 新 WARN：W-1 westock-mcp 401 → market_overview/sector_ranking/news/hot_news/hot_board **五文件全空**（11-05/06 完整，单日缺失）；W-3 **订单级成交回写不完整**——A001/A002 今日成交但 actual_cost/actual_shares=null、sl/tp 仍为预览值，中国动力陈旧第 6 日，3 张均带 recalc_required=true（非缺失，不升级）；W-4 指数链路 as_of 停 20261104（滞后 3 日，连续第 4 轮）；W-5 数据员 20:06 提前取数第 5 日；W-6 position_builder 21:13 早于 researcher 21:50（37 分钟）。
- 产出：reports/daily_20261109.md + reports/mail_inspect_20261109.html（20.8 KB），邮件 SENT（queued=true），inspector 置 done(date=20261109, reason=ok)。
- 经验：① 数据「文件存在但内容为空（missing=true）」要按降级算而非缺失，判断连续天数要看前一日 record_counts 而非只看 meta.degraded；② 弱化历史 critical 时必须回读**被指控方的原始报告**，本轮正是靠 pb_status_20261107.html 才推翻了自己前 4 轮的定性；③ 当规则本身禁止某动作时，「0 产出」是合规而非故障，巡检不应把合规计入失败。

## 2026-11-10（第十二次运行，成功；当日 21:00 触发，流水线 20:34 收官）
- 交易日确认：trade_cal SSE 20261110 is_open=1（后续 11-11/12/13 均开市）。数据基准 data/daily_20261110 齐备 11 文件、无滞后；依赖 position_manager 首次 wait 即 ready。
- 结论：**1 CRITICAL + 8 WARN + 6 INFO**。check_pipeline --date 20261110 退出码 1 FAIL，唯一失败项 market_overview.json: empty（同 11-09）。9 任务 8 done + position_builder undo；7 个状态文件 + trades.jsonl(22 行) 全 PASS；15 张买单 sl/tp 缺项 0（卖单 ORD-20261030-S001 豁免）。
- **C-1 升级（本轮核心）**：westock 401 致 market_overview/sector_ranking/news/hot_news/hot_board 五文件在 11-09、11-10 **连续 2 个交易日**全空 → 达规则门槛，由上期 warn 升 critical（上期已承诺「明仍缺则升」）。影响三层：①板块维度缺失不计分，分析师测算补采 +2 则 score +4→+6/conf 0.82 → 切 neutral cap 60→70，即当前 bear 可能是缺数据压制出的假性维持；②逻辑破坏检测盲 2 日（个股级负面不可识别）；③定性标签/板块结构/估值全失。解除需人工重授权 westock 后补跑两日（news/hot 历史不可回溯）。
- **W-1 根因定位（本轮最有价值发现）**：position_builder undo @20261107 stale-watchlist 不变，但真因是两个独立调度缺陷——①`task_status.py wait` **只看 status 不看 date**，11-07 21:13 时 researcher 仍是上周 done(date=20261030)，wait 秒过；②**流水线整体提前到 20:00-21:00 后环节倒置**，researcher 21:10 触发/21:50 完成，而 pb 21:13 触发，比上游早 37 分钟。结论：pb 业务结论正确（三重阻断 R-001 bear 禁买 / watchlist 落后 5 日 / available -10.00%），0 单合规且不写盘正确；必须在 11-15 前修 wait 的 date 判定，否则第 3 个周期仍是 0 单。
- 当日：4 张 A 单全按开盘价成交 133,133 元（v2.4 口径正确），0 卖；总资产 999,241、当日 -0.7609% vs 上证 +0.0801%（超额 -0.84pp）、累计 -0.0759% vs 基准 -0.72%（超额 +0.65pp）、仓位 45.70%→58.61%、8 只、熔断 -0.6845% 未触发。
- regime 未切换（bear/light cd 2→3，score +2→+4、conf 0.73<0.75 第 4 次防抖拦截，与 20261104 同型 +4/0.73；cap 60，eff 20261111）。三项升级规则中仅「数据连续 2 日缺失」命中 → 报告末尾追加「建议实时会商」三议程（缺数据期仓位规则 / C-1 授权与补跑责任链 / W-1 修复归属）。
- 新 WARN：W-2 orders.json 计划集停 20261023 第 12 日、0 在途（9 filled/7 expired）、重建全靠 11-15；W-3 7 张已成交买单 sl/tp 为预览值（recalc_required=true），中国动力第 7 日（29.01/37.84 vs 28.64/37.36）；W-4 指数链路 as_of 停 20261106（滞后 2 日，连续第 5 轮）；W-5 数据员 20:05 取数第 6 日；W-6 stock_picker done 但 reason/artifact 双 null；W-7 拥挤度 MTD 42.5118% 距 warn 45 仅 2.49pp（pct_rank 84.5）；W-8 仓位距 cap 仅 1.39pp，topup 卡 min_gap 1.5pp 通道关闭。
- 产出：reports/daily_20261110.md + reports/mail_inspect_20261110.html（30.6 KB），邮件 SENT（queued=true），commit 8f5ca0f **push 成功**（上轮积压已清）。
- 经验：①「连续 2 日」的判据必须回读前一日 record_counts 逐项比对，不能只看当日 degraded——本轮正是靠 11-06(8/15/50/20/15) vs 11-09/11-10(全 0) 的对照才把 warn 升成 critical；②对 undo 类任务要区分「结论错」与「调度错」，本轮 pb 结论全对、错在调度，写报告时把责任归到具体缺陷（wait 不看 date / 环节倒置）比笼统记 warn 有用；③缺数据的影响方向要量化（补采 +2 → 切 neutral → cap +10pp），否则「降级」只是形容词。
