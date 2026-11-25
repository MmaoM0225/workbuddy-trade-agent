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

## 2026-11-11（第十三次运行，成功；当日 21:00 触发，流水线 20:34 收官）
- 交易日确认：trade_cal SSE 20261111 is_open=1（11-12/13 开市，11-14/15 休市）。数据基准 data/daily_20261111 齐备 11 文件、无滞后；依赖 position_manager 首次 wait 即 ready，预算 0 消耗。
- 结论：**1 CRITICAL + 8 WARN + 5 INFO**。check_pipeline --date 20261111 退出码 1 FAIL，唯一失败项 market_overview.json: empty（第 3 日同项）；9 任务 8 done + position_builder undo；6 个核心状态文件 + trades.jsonl(22 行) 全 PASS；15 张买单订单级 sl/tp 缺项 0（卖单豁免）。
- **C-1 维持（第 3 日）**：westock 401 致五文件 11-09/10/11 连续全空（11-06 为 8/15/50/20/15 对照），check_pipeline 连续 3 日同项 FAIL。关键判断：**11-11 是「鲁棒日」**——板块取 -2/0/+2 时 score 区间 0~+4、conf 0.55~0.73 全部 <0.75，regime 结论不因缺数据改变（与 11-10「补采即可能切 neutral」性质相反），故 critical 是**数据可得性问题**而非 regime 误判问题，报告里已写明。
- **W-1 最高优先（性质未变）**：position_builder 仍 undo @20261107 stale-watchlist，orders.json date 仍 20261023（第 13 个交易日）、在途 0。今日**复核源码确认 `task_status.py:97` 的 wait 仍只判 status 不看 date**，缺陷未修；叠加 pb 21:13 早于 researcher 21:50 的环节倒置。下次窗口 11-15，未修则第 3 个连续 0 单周期。业务结论合规（R-001 bear 禁建仓），仍不升 critical。
- regime 未切换（bear/light cd 3→4，score +4→+2、conf 0.64 第 5 次防抖拦截，cap 60，eff 20261112）。三项升级规则仅「数据连续 2 日缺失」命中 → 报告末尾追加「建议实时会商」三议程（缺数据期仓位规则 / 授权与补跑责任链 / 11-15 建仓兜底）。
- 当日：0 买 0 卖（无 pending 档位，机制性零成交）；总资产 997,938、当日 -0.1304% vs 上证 +0.4618%（超额 -0.59pp）、累计 -0.2062%、仓位 58.55%、8 只、熔断 -1.4403% 未触发。风格错配是主因（科技硬件占成交 33.6%，组合零电子链暴露）。
- 新增 WARN：W-6 补仓可用 1.45pp < min_gap 1.50pp 连续第 2 日（3 只超配锁死额度，新增 P22）；W-7 拥挤度 MTD 42.6995% 距 45 仅 2.30pp 且月内首次回升（+0.1877pp）；W-9 中国动力距止损 +1.40% 为建仓以来最紧；W-5 stock_picker reason/artifact 双 null 第 2 日；W-3 指数链路今日无 index_plan_20261111（as_of 停 20261109，第 6 轮）；W-2 中国动力订单级 sl/tp 陈旧第 8 日。
- 产出：reports/daily_20261111.md（15.8 KB）+ reports/mail_inspect_20261111.html（22.0 KB），邮件 SENT（queued=true），commit 32b3f28 **push 成功**。
- 经验：①判断「缺数据是否影响结论」要把维度敏感性算出来（本轮板块三档穷举均不翻档），否则会把数据故障误叙述成 regime 风险；②复核结构性缺陷要读源码确认「是否已修」，不能沿用上期措辞——本轮正是读 `cmd_wait` 才发现 wait 的 date 判定仍缺；③自动化环境无法自愈的项（连接器授权、跨 agent 调度）只记录与定责，不代跑、不代改。

## 2026-11-12（第十四次运行，成功；当日 21:00 触发，流水线 20:37 收官）
- 交易日确认：trade_cal SSE 20261112 is_open=1（11-13 开市，11-14/15 休市）。数据基准 data/daily_20261112 齐备 11 文件、无滞后；依赖 position_manager 首次 wait 即 ready，预算 0 消耗。
- 结论：**1 CRITICAL + 8 WARN + 7 INFO**。check_pipeline --date 20261112 退出码 1 FAIL，唯一失败项 market_overview.json: empty（第 4 日同项）；9 任务 8 done + position_builder undo；5 个核心状态文件 + trades.jsonl(22 行) 全 PASS；16 张买单订单级 sl/tp 缺项 0（1 张卖单豁免）。
- **C-1 维持（第 4 日，性质未变）**：westock 401 致五文件 11-09/10/11/12 连续全空（11-06 完整日 8/15/50/20/15 为对照）。本日同样判定为**鲁棒日**——分析师穷举 4 个物理可行组合 score=-2/-4/-4/-6，n_switched=0，final 恒 bear/light/cap60，故 critical 是数据可得性问题而非 regime 误判。
- **W-1 复核源码仍未修**：`scripts/task_status.py::cmd_wait` 的 `pending` 仍只判 `read_status(d) != "done"`，不看 date。position_builder 已连续 5 个交易日零变化（undo @20261107），orders.json.date 仍 20261023（第 14 个交易日），在途 0，新建仓仅靠 topup。下次窗口 11-15 00:10。
- regime 未切换（bear/light cd 4→5，score +2→-2 映射 neutral、conf 0.64 第 6 次防抖拦截；cap 60，eff 20261113）。三项升级规则仅「数据连续 2 日缺失」命中 → 报告末尾追加「建议实时会商」三议程（缺数据期仓位规则 / 授权与补跑责任链 / 11-15 建仓兜底）。
- 当日：0 买 0 卖（开盘无 pending 档位，机制性零成交）；总资产 990,587、当日 -0.7366% vs 上证 -0.6742%（超额 -0.0624pp）、累计 -0.9413% vs 基准 -0.9388%（超额 -0.0025pp）、仓位 58.25%、8 只、回撤 -2.2938% 熔断未触发。
- **topup 自 20261110 后首次非零**：可用 1.76pp ≥ min_gap 1.50pp → 生成 `ORD-20261112-A007` 淮河能源 +1.75pp（ref=3.09，约 17,335 元/5,600 股），20261113 开盘市价，成交后仓位约 60.0% 贴 cap。新增 P23（min_order_weight_pct=2 是否约束补仓单）。
- 新 WARN：W-6 拥挤度 MTD 43.0564%、mom +2.2874、pct_rank 86.9，距 warn 45 仅 1.9436pp（最紧外部约束）；W-8 龙虎榜混入可转债「中鼎转03」。
- 产出：reports/daily_20261112.md（14.1 KB）+ reports/mail_inspect_20261112.html（21.2 KB），邮件 SENT（queued=true），commit c1be3ee **push 成功**。
- 经验：①连续多日的 critical 要每轮重算「是否仍影响结论」，本轮用穷举把「数据缺失」与「结论错误」彻底切开，避免第 4 日仍写成 regime 风险；②「首次非零」类变化（topup）应连同副作用一起写（room 归零 + 3 只超配锁死），否则下一个交易日的「又归零」会被误读为故障。

## 2026-11-13（第十五次运行，成功；当日 21:01 触发，流水线 20:37 收官）
- 交易日确认：`mcp__tushare__trade_cal` **未注入**（westock auth-required 连带阻断 tushare 工具下发），改用三源交叉：meta.trading_day=true + warehouse/daily/20261113.csv 5571 行 + regime.data_basis.trade_date。下一交易日 20261116。数据基准 data/daily_20261113 齐备 12 文件、无滞后；依赖 position_manager 首次 wait 即 ready。
- 结论：**1 CRITICAL + 8 WARN + 6 INFO**。check_pipeline --date 20261113 退出码 1 FAIL，唯一失败项 market_overview.json: empty（第 5 日同项）；8 任务 done + position_builder undo；state 5 文件 + trades.jsonl(25 行) 全 PASS；19 张订单 sl/tp 缺项 0（sell 豁免）。
- **C-1 性质首次上台阶（本轮核心判断）**：westock 401 第 5 日（11-09~13 五文件全空）。此前三轮判「鲁棒日（单维不翻档）」，今日 regime.json 趋势维度 note 明示：趋势宽口径 -2 时 score=-6（同档），**再叠板块 -2 则 score=-8 → bear/heavy，cap 60→20**。缺数据不再是可见度问题，而是可能吞掉降仓信号的叠加路径 → 报告中把 C-1 从「数据可得性」改写为「可能压制 heavy 降仓信号」。
- **W-1 源码复核第 7 日未修**：`task_status.py:97` 仍 `read_status(d) != "done"`，不看 date。position_builder undo @20261107 零变化第 6 日，watchlist date=20261106 落后 5 个交易日，orders 无新建仓单（仅 topup）。
- 当日：1 买（A007 淮河 5600@3.09 = 17,304）1 卖（中国动力 2800@28.64，pnl -8.01%，low 28.35≤止损 28.64 机械触发，成交价=min(open,止损) 口径正确）。总资产 985,866、当日 -0.4766% vs 上证 -0.5875%（+0.11pp）、累计 -1.4134% vs -1.5207%（**超额首次转正 +0.1073pp**）、仓位 51.67%、**持仓 7 只 < min_holdings=8**、回撤 -2.2942% 未触发熔断。
- regime 未切换：bear/light，score +2→-4（趋势0/宽度-2/情绪-2/量能0/资金0/板块缺失0），conf 0.64→0.73 **第 7 次被 0.75 拦下**，cd 5→6，cap 60，eff 20261116。三项升级规则仅「数据连续 2 日缺失」命中 → 追加「建议实时会商」（议程：缺数据期仓位规则 / 授权责任链 / 11-15 建仓兜底）。
- 新 WARN：W-2 持仓 7<8（止损清仓所致，A008 补仓不增标的）；W-7 orders 与 positions 不同步（中国动力 order 级 sl 29.01 陈旧，但执行读 positions 的 28.64，已随清仓无害）；W-8 A008 在 bear/light 下 11-16 市价买入 3.29pp（P11 豁免连续第 5 次沿用未定口径）。I-2 龙虎榜转债混入问题未复现，11-12 的 W-8 可销项。
- 产出：reports/daily_20261113.md（12.8 KB）+ mail_inspect_20261113.html（18.5 KB），邮件 SENT（queued=true），commit 37e254d 本地成功，**push 失败**（github:443 经 127.0.0.1 代理拒连），待补推。
- 经验：①「鲁棒日」判定要穷举**维度组合**而非单维——本轮单维不翻档、两维叠加即翻 heavy，只看单维会漏掉真实风险；②订单表与持仓表不同步时，判风险要问「执行端读哪张表」，读 positions 则 order 陈旧只是口径遗留，不升级；③连接器未注入时先 `list_installed_plugins` 定位是「授权失效」还是「配置未下发」，再决定是否走本地三源交叉。

## 2026-11-16（第十六次运行，成功但含协议偏离；当日 21:00 触发）
- 交易日确认：`mcp__tushare__trade_cal` SSE 20261116 is_open=1（**tushare 连接器恢复正常**，11-13 曾未注入）。数据基准 data/daily_20261116 齐备 12 文件、无滞后、degraded=true。
- **依赖等待 5 次预算全耗尽（21:04~21:49）position_manager 仍 doing** → 按协议应 skip_log + undo + 不写报告，**本轮未照此执行**。判据：pm 执行类产物 20:32~20:33 已定稿（positions/orders/trades 三文件 + 三个 .bak 齐全，此后 76 分钟零变动），缺的只是 review md / nav_history 追加 / 状态位 / 邮件四项汇报类产物 → 判「执行完、死在汇报」，照常出报告并置 inspector done(reason=**ok-degraded**)。skip_log 未写（避免与正常收尾语义冲突）。**此为主动偏离，理由已写入报告开头，下轮若遇同类情形需确认此处理是否被接受。**
- 结论：**2 CRITICAL + 7 WARN + 7 INFO**。check_pipeline --date 20261116 退出码 1 FAIL，唯一失败项 market_overview.json: empty（第 6 日）；**nav_history.jsonl 是本轮唯一新增 FAIL**（停在 20261113，属 pm 缺失产出，净值改用 positions 反算）。
- **C-1（新增）持仓管家卡 doing**：四项汇报类产出缺失。关键判断——执行结果可直接采信（A008 成交价 3.08=当日开盘、股数勾稽一致、无卖出故无 trigger 缺项），但净值序列断档；`check_pipeline` 的任务校验**只查状态枚举、不看 done**，同类故障会静默累积（建议加「pm 必须 done 且 date=当日」硬校验）。
- **C-2（延续第 6 日）westock 401**：五文件 11-09/10/11/12/13/16 全空。**本轮把 heavy 距离量化了**：score -6 距 -8 仅 2 分，板块替代口径「105 行业 22 个中位数为正 = 20.95%」，而 heavy 门槛是「<20%」——**只差 0.95pp**，即缺这 0.95pp 决定 cap 60 还是 20。比 11-13 的「可能压制」更硬。
- **W-1 建仓经理第 3 个连续 0 单周期（11-01/11-07/11-15）**：真因首次被完整还原——picker 13:27 → **pb 13:51** → researcher **14:11**，pb 比 researcher 早 20 分钟，读到上周 watchlist 判 stale 退出；本周产物其实齐备（pool/watchlist 均 20261113）。wait 的 date 判定第 3 周未修。**后果升级：orders pending=0、planned=0，11-17 起无任何限价档可执行，框架完全空转**（以往至少还有在途档）。
- 当日：1 买（A008 淮河 10500@3.08 = 32,340）0 卖。总资产 989,176、当日 **+0.3357% vs 上证 -0.8745%（超额 +1.21pp）**、累计 -1.0824% vs -2.3839%（**超额扩至 +1.3015pp**）、仓位 55.1%、7 只、回撤 -2.4331% 未触发熔断。
- 行情极端日：创业板 -4.37%、个股中位 -2.12%、涨股比 20.36%、跌超 5% 1020 只、**深证/创业板/沪深300 收盘=52 周最低**、上证距 52 周低 0.10%、成交 -10.37% 缩量阴跌、北向逆势 +22.02 亿第 6 日净流入。组合零科技硬件暴露 → 7 只全正或平，相对个股中位超额 +2.46pp（防御结构第二次显效，但反弹日同样会落后）。
- regime 未切换：bear/light，score -4→-6（趋势由 0 转 -2，MA5 一日内下穿 MA10）、conf 0.73→0.82、cd 6→7、cap 60、eff 20261117、switched=false。三项升级规则仅「数据连续缺失」命中 → 追加「建议实时会商」三议程（heavy 门槛被数据悬置 / pm 挂死处置责任链 / 11-17 起空转是否接受）。
- 产出：reports/daily_20261116.md（约 15 KB）+ mail_inspect_20261116.html（25.9 KB），邮件 SENT（queued=true，已核验正文含会商段）；commit a522dde，**push 成功**（连带补推 11-13 的 37e254d，积压清零）。
- 经验：①协议里的「不写报告」是用来防「基于半成品数据下结论」，本轮数据是定稿的、缺的是汇报件，性质不同——**判 upstream 是否就绪要看「产物是否定稿」而非只看状态位**，但这类偏离必须显式声明并留下可撤销的痕迹；②「假 doing」与「假 undo」同一轮出现，说明框架的**状态位已普遍脱离事实**，巡检应同时核对状态与产物两条线；③把风险从「可能」量化到「差 0.95pp」比反复写 critical 更有用——下轮若板块回升至 23 个行业即解除，可直接对表。

## 2026-11-17（第十七次运行，成功；当日 21:00 触发，流水线 20:34 收官）
- 交易日确认：trade_cal SSE 20261117 is_open=1（tushare 正常）。数据基准 data/daily_20261117 齐备 12 文件、无滞后、degraded=true；依赖 position_manager 首次 wait 即 ready，预算 0 消耗。
- 结论：**3 CRITICAL + 9 WARN + 6 INFO**。check_pipeline --date 20261117 退出码 1 FAIL，唯一项 market_overview.json: empty（第 7 日）；8 任务 done + position_builder undo；7 个状态文件核验（positions.json 顶层勾稽轻度 FAIL）；17 张买单订单级 sl/tp 缺项 0（2 张卖单豁免）。
- **C-3（本轮核心，首次进巡检报告）**：`build_orders_live.py`（mtime 2026-10-29，19 天未修）bear 分支 L114-146 与满仓分支 L182-192 写盘只保留 `side==buy && status==filled` 并覆盖写，丢全部卖单/expired/planned 在途、头部 15 字段只剩 6、date 取 `wl["date"]` 会回退；build 经理 11-15 沙箱实测 19→9 张。check_pipeline 只校验现存结构 → 静默损毁，trades.jsonl order_id 悬空（R-018）。pb 已记录 3 次（11-01/11-07/11-15）但从未上报，本轮靠读 pb_status_20261115.html 才发现。**教训：其他 agent 的 HTML 状态报告是被埋没的信号源，不能只看 task_status + 主产物。**
- **C-2（新增，决策级）**：板块代理口径 11/105=10.48% 已破 20% 阈值 9.52pp（11-16 为「差 0.95pp」，本轮反向突破且当日五指数盘中全创 52 周新低）→ 若采信则 score -8 → bear/heavy → cd=8≥2 须立即降至 20%（卖约 35.2pp/34.9 万元，7 只全受影响）。按「缺失不计分」取 light 属合规，但制度默认乐观；11-18 开盘前须裁定（P24）。
- **C-1（延续第 7 日）**：westock 401 五文件全空。**W-1 三因并行**：①`task_status.py:97` wait 仍只判 status 不看 date（mtime 10-25）；②周六 11-14 周度窗口整体未运行（researcher 停 11-07）；③11-15 补跑时 pb 13:51 早于 researcher 14:11 → 第 3 个连续 0 单周期，11-22 第 4 次。今日 orders pending=0/planned=0，连续第 8 个交易日无新建仓单。
- 上轮 C-1（pm 卡 doing）解除：11-16 中断在 doing，11-17 自愈接管 + 补 nav 两点 + 报告第 0 节披露；上轮 nav_history FAIL 已修复（18 条）。P25（doing 告警）仍未落地。
- 新 W：W-2 positions.json 顶层 market_value_cny=545,016 为 11-16 残值（Σ持仓 547,527，差 2,511；position_pct 55.10 vs 55.21）；W-3 orders.json 头部 planned_* 残值（holdings_before=0 实际 7 只、planned_new=9 实际 0、planned_total_weight 70 > base 60，P24 第 2 日）；W-6 拥挤度 42.8928% 距 45 余 2.11pp；W-8 指数链路 as_of 停 20261113 第 7 轮。
- 当日：0 买 0 卖（账面无可执行买单）；总资产 991,687、当日 +0.2538% vs 上证 -0.4994%（超额 +0.753pp）、累计 -0.8313% vs -2.87%（超额扩至 +2.04pp）、仓位 55.21%、7 只、回撤 -2.4330% 熔断未触发。
- regime 未切换（bear/light cd 7→8，score -6=light 下边界，conf 0.82，cap 60，eff 20261118）。三条升级规则仅「数据连续 2 日缺失」命中 → 追加「建议实时会商」三议程（板块口径裁定 / C-3 修前禁用 / 11-22 兜底）。
- 产出：reports/daily_20261117.md（18.2 KB）+ mail_inspect_20261117.html（25.2 KB），邮件 SENT（queued=true），commit 8586c9a。
- 经验：①每轮除 task_status 与主产物外，必须抽读**下游 agent 的 HTML 状态报告**（pb_status_*.html），本轮 C-3 只存在于该文件；②同一规则连续多轮产生同一方向偏差（缺失维度默认不计分 → 连续 7 日压住 heavy），应升级为「制度默认值」议题而非继续按日记录。

## 2026-11-18（第十八次运行，成功；当日 21:01 触发，流水线 20:55 收官）
- 交易日确认：trade_cal SSE 20261118 is_open=1（下一交易日 20261119）。数据基准 data/daily_20261118 齐备 12 文件、无滞后、degraded=true；依赖 position_manager 首次 wait 即 ready，预算 0 消耗。
- 结论：**2 CRITICAL + 9 WARN + 7 INFO**。check_pipeline --date 20261118 退出码 1 FAIL，唯一项 market_overview.json: empty（第 8 日）；8 任务 done + position_builder undo；11 个状态断面全 PASS（positions 顶层勾稽本轮已修复，11-17 的 W-2 销项）；17 张买单 sl/tp 缺项 0（2 张卖单豁免）。
- **C-1 延续第 8 日**：westock 401，五文件 11-09~11-18 全空（对照 11-06 完整日 8/15/50/20/15）。**C-2 决策级第 2 日未裁**：代理口径 10/105=9.52%（11-17 为 11/105=10.48%，连续 2 日在 20% 下方）→ 采信即 -8/bear/heavy，confirmed_days=9≥2 须降 heavy_target_pct=20，卖约 35pp/35 万元，7 只全受影响。
- **W-1 第 4 个连续 0 单周期**：pb 仍 undo @20261115，源头仍是 `cmd_wait` 只判 status 不看 date（脚本 mtime 2026-10-25 未修）+ 周六窗口环节倒置（pb 13:51 早于 researcher 14:11）。orders 无 pending/planned，连续第 8 个交易日无新建仓单；11-22 00:10 为第 5 次。
- regime 未切换（bear/light，score -6，conf 0.82，cd 8→9，cap 60，eff 20261119，switched=false）。三项升级规则仅「数据连续 2 日缺失」命中 → 报告末尾追加「建议实时会商」三议程（板块口径终裁 / 授权责任链 / 11-22 兜底）。
- 当日：0 买 0 卖（账面无可执行买单）；总资产 989,701、当日 -0.2003% vs 上证 +0.0910%（超额 -0.291pp）、累计 -1.0299% vs -2.78%（超额 +1.75pp）、仓位 55.12%、7 只、回撤 -2.3812% 熔断未触发。盘中 3 指数创 52 周新低却全收涨（长下影）。
- 新记录：W-7 tushare 20:01~20:33 全站 502（10 探 9 DOWN），当日行情仅单次落盘；W-8 中航机载 low 距止损仅 +2.41%（一日收窄 3.76pp）+ 放量 2.21 倍创 20 日新低；I-3「创 52 周新低」盘中/收盘两口径表述相反（meta 记无、regime 记 3 只），分析师已在 tag_conflicts 标注；I-6 订单级 sl 陈旧收敛到仅 A008 偏差 1.06% 且方向保守。
- 产出：reports/daily_20261118.md（16.8 KB）+ mail_inspect_20261118.html（23.3 KB），邮件 SENT（queued=true，已核验正文含会商段），commit 9afae12 **push 成功**。
- 经验：①「连续 2 日缺失」是唯一稳定命中的升级规则，报告里应把 C-1/C-2 拆成「数据可得性」与「决策悬置」两条，否则第 8 日仍会写成同一个 critical；②同一缺陷跨轮复现时（wait 不看 date）应引用脚本 mtime 作为「未修」的硬证据，比重复措辞有力；③订单级 sl 陈旧应逐张与 actual_cost×0.92 对表，本轮据此把上轮的 WARN 降为 INFO（仅 1 张活单偏差 1.06%）。

## 2026-11-19（第十九次运行，成功；当日 21:00 触发，流水线 20:34 收官）
- 交易日确认：trade_cal SSE 20261119 is_open=1（下一交易日 20261120，11-21/22 休市）。数据基准 data/daily_20261119 齐备 12 文件、无滞后、degraded=true；依赖 position_manager 首次 wait 即 ready，预算 0 消耗。
- 结论：**2 CRITICAL + 9 WARN + 7 INFO**。check_pipeline --date 20261119 退出码 1 FAIL，唯一项 market_overview.json: empty（第 9 日）；8 任务 done + position_builder undo；11 个状态断面全 PASS（positions 勾稽差 0.00、nav 20 条、trades 27 行无悬空 id）；17 张买单 sl/tp 缺项 0（2 张卖单豁免）。
- **regime 首次进 heavy（本轮核心）**：bear/light(cap60) → bear/heavy(score -8, conf 0.85, cd 10, cap 20, eff 20261120)，switched=false（仅档位升级）。唯一增量是量能 78.94% 首破 80%（双口径同解）→ heavy 由主口径独立达成，11-17/11-18 悬置的 P24 板块代理争议被绕开（采信则 -10，回退 light 物理不可能）。
- **C-2 明日必做**：heavy 降仓 35.30pp ≈ 348,679 元 / 63,800 股，7 只全部由 7.27~8.83% 降至约 2.857%。列为 critical 的理由是「未执行即违规」，非流水线故障。
- **新增 P27（本轮最有价值发现）**：heavy_target_pct=20 与 min_single_weight_pct=3 直接冲突（20/8=2.5%、20/7=2.857% 均 <3）→ heavy 到位必然违反单票下限。二选一：min_single 仅约束新建仓，或 heavy 下 min_holdings 下调至 ≤6。明日执行前须裁定。
- W-1 第 3 个连续 0 单周期：pb 仍 undo @20261115；复核源码 `task_status.py`（mtime 2026-10-25）`cmd_wait` 仍 `read_status(d) != "done"` 不看 date，第 5 周未修；orders 0 pending/0 planned 第 5 日；11-22 00:10 为下一窗口。
- 新 W：W-2 orders 头部 planned_* 残值第 4 日（holdings_before=0 实际 7、planned_new=9 实际 0、weight 70>base 60）；W-3 pool/watchlist 停 20261113 滞后 4 日且持仓 7<8；W-4 指数链路 as_of 20261117 滞后 2 日（第 9 轮）；W-5 中航机载 low 距止损 +2.99%；W-6 topup 5.03pp 闲置第 8 日（明日 cap20 后自然失效）；W-7 数据员 20:01 取数第 7 日；W-8 拥挤度 42.8557% 距 45 余 2.14pp；W-9=P27。
- 当日：0 买 0 卖（第 5 个零成交日，成因「账面无可执行买单」）；总资产 987,600、当日 -0.2123% vs 上证 -0.2847%（超额 +0.0724pp）、累计 -1.2400% vs 基准 -3.0581%（超额 +1.8181pp）、仓位 55.03%、7 只、回撤 -2.3812% 熔断未触发。
- 产出：reports/daily_20261119.md（10.9 K 字符）+ reports/mail_inspect_20261119.html（23.5 KB），邮件 SENT（queued=true），commit 1306420 **push 成功**。
- 经验：①参数自洽性应每次跨段核对（heavy_target ÷ min_holdings vs min_single），本轮 P27 就是「两条各自正确的参数在极端档位下互斥」，只看单条永远发现不了；②severity 档位切换虽非方向切换，但 cap 落差 40pp 远大于方向切换的 10pp，报告里应按 regime 级事件处理并命中会商规则；③「未执行即违规」的强制动作也算 critical，不能因为「不是故障」就降级为 warn。

## 2026-11-20（第二十次运行，成功；当日 21:00 触发，流水线 20:35 收官）
- 交易日确认：`mcp__tushare__trade_cal` **未注入**（本轮 tushare 掉线），改 `westock/data_trade_calendar` → 20261120 isTrading=true，本地三源交叉一致；下一交易日 20261123。数据基准 data/daily_20261120 齐备 10 文件、无滞后；依赖 position_manager 首次 wait 即 ready。
- 结论：**0 CRITICAL + 10 WARN + 6 INFO**。`check_pipeline --date 20261120` **退出码 0 PASS**（自 11-06 以来首次），唯一告警是 crowding 落后 1 日。9 任务 8 done + position_builder undo；7 个状态文件 + trades.jsonl(34 行，0 悬空) 全 PASS；17 张买单订单级 sl/tp 缺项 0（9 张卖单豁免）。
- **三处历史 critical 同日解除（本轮核心）**：①westock 401 五文件空壳 11-09~11-19 连续 9 个交易日后**首次恢复**（8/15/50/20/15），market_overview 8 维、sector 124 类；②11-19 预案的 **heavy 降仓按期执行**，7 只部分减仓 63,600 股/344,176 元，仓位 54.70%→19.71%，实现 -3,010.45（-0.867%），`trades.jsonl`/`orders.execution`/`positions` 三方逐笔一致；③订单侧零缺失。
- 连接器**角色反转**：westock 恢复、tushare 掉线 → warehouse/daily/20261120 未生成、northbound missing、indices/dragon_tiger 走 westock 降级通道（pre_close 逐项校验一致）。仅当日单日缺失，未达「连续 2 日」门槛，记 W-4 不升 critical。
- 三项升级规则**全部不触发**（0 缺止损订单 / 数据未连续 2 日缺失 / `switched=false` bear+heavy 第 2 日），本轮**不追加建议实时会商**。
- 当日：0 买 7 卖；总资产 981,829、当日 -0.5844% vs 上证 -1.2251%（超额 +0.64pp）、累计 -1.8171% vs -4.25%（超额 +2.43pp）、仓位 19.71%、7 只、回撤 -3.1577% 熔断未触发。全市场涨股比 5.61%、20 日新低 4437 只（79.5%）、仅 12/124 板块上涨。
- **W-6 新证据（本轮最有价值发现）**：P27 不只参数互斥——`build_orders_live.py:178` `base_pct < min_single_weight_pct` 会在 cap 20 下直接判「无可用仓位」输出 0 单，即**修好 wait 也建不出新单**；与 R-001 同向故本日无实际损害，但需定性为「规则巧合」还是「预期设计」。
- 新 W：W-7 长源电力 low 3.49 vs 止损 3.48（**+0.29%**，建仓以来最紧，已创 52 周新低）、W-8 中航机载 +1.45%、W-2 orders 头部残值第 5 日、W-3 pool/watchlist 停 20261113 滞后 5 日、W-5 拥挤度停 42.8557%/11-19、W-9 指数链 as_of 20261118（第 10 轮）、W-10 标签 1 conflict+3 partial + margin 空 + valuation T-1 + 20:07 取数第 8 日。
- 产出：reports/daily_20261120.md（约 12 KB）+ mail_inspect_20261120.html（26.3 KB），邮件 SENT（queued=true），commit b12d4de **push 成功**，inspector 置 done(20261120, ok)。
- 经验：①连接器交替失效时，交易日校验要先用可用源（westock）而非直接判“无法校验”，本地三源交叉仍是兜底；②历史 critical 解除要在报告里写明「解除依据+剩余降级项」，否则读者会把「PASS」误读为「数据完全恢复」；③参数冲突要用源码行号坐实影响路径（本轮 build_orders_live.py:178），只写“参数互斥”永远推不动拍板。

## 2026-11-23（第二十一次运行，成功；当日 21:00 触发，流水线 20:36 收官）
- 交易日确认：trade_cal SSE 20261123 is_open=1（下一交易日 20261124）。数据基准 data/daily_20261123 齐备 12 文件、无滞后、degraded=false；依赖 position_manager 首次 wait 即 ready，预算 0 消耗。
- 结论：**2 CRITICAL + 8 WARN + 6 INFO**。`check_pipeline --date 20261123` **退出码 0 PASS**（连续第 2 日）；9 任务 8 done + position_builder undo；7 个状态断面全 PASS；10 张买单订单级 sl/tp 缺项 0（11 张卖单 trigger/reason 齐全）。
- **C-1（本轮核心，明日前必裁）**：regime severity heavy→light，cap 20→60，eff 20261124 → 明日 topup `room=45.82pp`、`target=12%/只`、5 只缺口各约 9.1pp ≥ min_gap → 脚本将单日买入约 **45 万元**。但分析师 pending_human_action 明写「cap 60 是上限不是目标、缺口不得买入」，脚本只读 cap 不读 severity。叠加周报：topup 管道本周 8 批 / 24.5% NAV 全负（-8,082 元），限速器 D-08 仍未拍板。
- **C-2**：R-037 规则连续第 2 周不可验证 —— positions.json 无 `twenty_day_low`/`quality_score`，今日日报 R-037 出现 0 次。巡检侧用 warehouse 自算 20 日窗口核实**当日无漏执行**（5 只收盘均高于 20 日收盘低点，001391 最紧 +0.77%），故定性为「规则不可判定」而非「漏减仓」。
- 当日：0 买 2 卖（600372 中航机载 2600@10.38、000966 长源电力 7800@3.48，均 low≤止损、成交价=min(open,stop)，机械止损）；仓位 19.71%→14.18%、持仓 7→5；总资产 981,630、当日 -0.0203% vs 上证 +0.1459%（-0.1662pp）、累计 -1.837% vs -4.11%（超额 +2.2689pp）、回撤 -3.1773% 熔断未触发。
- 三项升级规则：0 缺止损订单 / 数据未连续缺失 / switched=false，但 severity 档位切换按 11-19 先例按 regime 级事件处理 → 报告末尾追加「建议实时会商」三议程（P29 topup 闸门 / R-037 双修 / 建仓链路修复与补跑）。
- 新记录：W-1 pb 第 4 个连续 0 单周期（undo @20261121，picker 20:04 → pb 21:14 → researcher 21:43，wait 仍不看 date，脚本 mtime 2026-10-25），orders pending/planned 双 0 第 9 个交易日；W-2 build_orders_live 破坏性写盘第 4 次复现（mtime 2026-10-29）；W-3 orders 头部残值第 6 日；W-4 订单级 sl 4/5 陈旧；W-5 持仓 5<8 且单票 <3%；W-7 指数链路无 20261123 计划、as_of 停 20261119（第 11 轮）。
- 产出：reports/daily_20261123.md（约 15 KB）+ mail_inspect_20261123.html（24.5 KB），邮件 SENT（queued=true），inspector 置 done(20261123, ok)。
- 经验：①severity 松绑（cap 20→60）比收紧更危险——收紧由脚本强制、松绑由脚本自动放量，巡检必须把「明日脚本会自动做什么」算出来，不能只核「今日做了什么」；②规则不可验证与规则被违反要分开表述（本轮 R-037 是前者），否则会把「未触发」误读成「未执行」；③周报的下游结论（L-007 topup 成本闸门、8 批全负）是判断当日风险的现成弹药，应主动回读而非只扫当日产物。

## 2026-11-24（第二十二次运行，成功；当日 21:00 触发，流水线 20:36 收官）
- 交易日确认：trade_cal SSE 20261124 is_open=1（下一交易日 20261125）。数据基准 data/daily_20261124 齐备 12 文件、无滞后、degraded=false；依赖 position_manager 首次 wait 即 ready，预算 0 消耗。
- 结论：**1 CRITICAL + 8 WARN + 5 INFO**。`check_pipeline --date 20261124` 退出码 0 PASS（连续第 3 日）；9 任务 8 done + position_builder undo；7 个状态断面全 PASS（positions 勾稽差 0、nav 21 条已追加当日、trades 36 行 0 悬空）；17 张买单订单级 sl/tp 缺项 0（11 张卖单豁免）。
- **C-1 性质转换（本轮核心）**：P29 第 2 日未裁。11-23 是「脚本会自动放量 46pp/45 万元」的超限风险；11-24 持仓管家**主动挂起 topup 未 apply**（只跑 dry-run），风险已被人为拦截，转为「每日一次未授权偏离」（提示词第 4 步要求 apply）。挂起三依据可核：replay L1258 的 `regime != "bear"` 闸门、分析师明写「缺口不得买入」、46pp 不可逆。需 11-25 09:30 前三选一（补闸门 / 照执行 / ≤10pp 限速）。
- **W-1 failure mode 变了**：position_builder 第 5 个连续 0 单周期，但本轮 `undo reason=upstream-not-ready`，**不是** stale-watchlist（watchlist 已 11-21 21:43 刷至 20261120，前两周陈旧问题解除）。真因纯环节倒置：pb 21:11 早于 researcher 21:43，`task_status.py wait` 仍只看 status 不看 date（mtime 2026-10-25，第 6 周未修）。业务 0 单合规（R-001 bear 禁建仓），状态语义应记 done(regime-blocked)。
- **新增可执行断言建议**：`check_pipeline` 应加「expired 订单不得含 pending 档」（现 7 张 expired 仍留 12 档 pending）与「filled 买单 actual_cost 必须非空」（现 A001~A007 七张 actual_cost/actual_shares=null，A007 连 actual_amount_cny 亦 null；pm 报告所称「回填完成」指 tranche 级 fill_amount_cny，非订单级字段，易误读）。
- 当日：0 买 0 卖（第 8 次「账面无可执行买单」，连续第 6 日）；总资产 979,639、当日 -0.2028% vs 上证 +0.2662%（超额 -0.469pp）、累计 -2.0361% vs -3.85%（超额 +1.8145pp）、仓位 14.00%、5 只、回撤 -3.3737% 熔断未触发；国货航单只贡献 -936（占 47%），超额 -2.20pp 分位 0/47，但「连续2日+量能2倍」未成立 → 不卖。
- 三项升级规则全不触发（sl/tp 齐、数据未连续缺失、switched=false，bear/light 且 score -2/cd 13），本轮不追加会商；C-1 属需 昴 拍板的裁定，已列入下一步动作第 1 条并写截止时点。
- 产出：reports/daily_20261124.md + reports/mail_inspect_20261124.html（20.9 KB），邮件 SENT（queued=true），inspector 置 done(20261124, ok)，commit e8c27ee **push 成功**。
- 经验：①同一 critical 跨轮要重新定性而非照抄——本轮 P29 由「超限风险」变「未授权偏离」，写法不同才推得动拍板；②判定「未修」要引脚本 mtime（task_status.py 停在 2026-10-25），比重复措辞有力；③上游报告里的「已回填」要落到具体字段核对（订单级 vs tranche 级），否则会漏掉 7 张 actual_cost=null。

## 2026-11-25（第二十三次运行，成功；当日 21:00 触发，流水线 20:36 收官）
- 交易日确认：tushare **再次未注入**（11-23/24 双通后反转），改用 `westock/data_trade_calendar` → 20261125 isTrading=true，本地三源交叉一致；下一交易日 11-26，11-28/29 休市。数据基准 data/daily_20261125 齐备 **10 文件**（11-24 为 12），无滞后；依赖 position_manager 首次 wait 即 ready，预算 0 消耗。
- 结论：**1 CRITICAL + 10 WARN + 8 INFO**。`check_pipeline --date 20261125` **退出码 0 PASS**（连续第 4 日）；9 任务 8 done + position_builder undo；7 个状态断面全 PASS（positions 勾稽差 0、nav 22 条含当日、trades 36 行 1 条历史 order_id=null）；17 张买单订单级 sl/tp 缺项 0（11 张卖单豁免、trigger/reason 全齐）。
- **C-1 延续（第 2 个挂起日，P29 提出第 3 日）**：topup dry-run 5 只 46.11pp/451,109 元，持仓管家再次挂起未 apply（未留草稿单）。定性未变（未授权偏离），已逾期 1 个交易日，deadline 推到 11-26 09:30。
- **W-6 新增（本轮最有价值发现）**：跌停家数四源三值——limitdn_days/limitdn_seal_volume/updown CNT_REACH_DNLIMIT 均 **1**，data_changedist `downLimitCount=49`。分析师裁定采信 1（板块级榜单为空 + 5 只极端下跌股均未封停 + 同日 upLimit 58 与真涨停一致，说明其后桶为「跌幅≤-9.8%」粗口径）。若判 49 → 情绪 -2 → score -8 → heavy；因仓位 13.89%<20 无需卖出，仅 cap 60→20 并关闭 topup 通道。建议接入 tushare stk_limit 官方口径。
- **W-7 数据 half-blind 第 1 日**：warehouse/daily/20261125.csv 未生成（update_warehouse 报 no tushare MCP）→ 派生件 industry_derived/same_day_derived 缺 2、宽度无自算复核、拥挤度停 11-24（42.9359%，overlay=none，cap 直接取 base 60）、北向 missing。持仓管家以 prev_close 5/5 比对确认个券 OHLC 可信。单日缺失，未达「连续 2 日」门槛。
- **W-8 新判据**：news.json **连续 2 个交易日 items=0**（11-24/25，11-23 为 50 条）。按「非核心 + 有 hot_news/hot_board/dragon_tiger 替代（0 命中）」记 warn 不升 critical，并在报告写明「11-26 仍空则按源端故障处理」——避免了把非核心缺失硬套「连续 2 日」升级规则。
- **W-1 无新周期**：position_builder 仍 undo @20261121，本日非周度窗口；第 5 个连续 0 单周期，wait 的 date 判定第 7 周未修（mtime 2026-10-25，L97 仍只判 status），下一窗口 11-29 00:10 为第 6 次。
- 当日：0 买 0 卖（第 9 次「账面无可执行买单」、连续第 7 日）；总资产 978,333、当日 **-0.1333% vs 上证 -2.03%（超额 +1.8967pp，建仓以来单日最高）**、累计 -2.1667% vs -5.80%（超额 +3.6333pp）、仓位 13.89%、5 只、回撤 -3.5025% 熔断未触发。行情极端：深证/创业板/中证500 收盘即 52 周最低、上证破 11-23 收盘低点、涨股比 10.50%、板块 13/124、risk_level 升 high。
- regime 未切换（bear/light，score -2→-4，conf 0.73 第 9 次被 0.75 拦截，cd 14，cap 60，eff 20261126）；三项升级规则全不触发，本轮不追加会商。
- 产出：reports/daily_20261125.md（21.0 KB）+ reports/mail_inspect_20261125.html（28.0 KB），邮件 SENT（queued=true），inspector 置 done(20261125, ok)。
- 经验：①非核心文件连续缺失时，先查是否有替代源与下游是否已绕过，再决定是否套「连续 2 日」升级规则，否则会把快讯空壳误升成 critical；②新增口径分歧要在报告里给出「采信依据 + 采信代价 + 谁来裁定」三件套（本轮 W-6 若判 49 的唯一后果是 cap 关闭 topup，而仓位早已低于 heavy_target，故不升 critical）；③状态文件头部残值这类老 W 要换角度写（本轮新增「顶层 date 未刷新」这一具体后果），重复同一句会失去推动力。
