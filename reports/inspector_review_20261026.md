# 总控巡检报告 20261026（重放模式 / v2.3）

- 巡检时间：2026-10-27 00:41（业务日 20261026，重放）
- 巡检对象：选股(1024) → 研究(1024) → 建仓(1025) → 市场分析(1026) → 持仓执行(1026)
- 脚本：`scripts/check_pipeline.py --date 20261026` → **退出码 0 / PASS**
- 邮件：**未发送**（重放模式，按指令跳过告警通道）

---

## 一、结论

**WARN**（CRITICAL 0 / WARN 4 / INFO 5）

- 账本恒等式、订单完整性、产物对账三项硬指标全部通过；上一轮出过问题的 **order_id ↔ trades.jsonl 对账本轮正确**（唯一成交单 TRD-20261026-001 → ORD-20261023-002 双向可查，且该单仍完整保留 `filled_partial` 与 fill 字段，未被重写丢失）。
- 无资金类风险，无订单丢失，无止损缺失，无数据缺口。
- 主要问题集中在**交付物一致性**与**流水线未闭环**：日报 `daily_20261026.md` 仍是旧轮次（v2.0/v2.1）产物、reviewer 卡在 doing 导致 archivist 停在 undo、仓位仅 3.12%（目标 50.01%）。

---

## 二、逐项检查表

### 2.1 九个任务状态（state/tasks/*.json）

| 任务 | status | date | reason | 判定 |
|---|---|---|---|---|
| data_officer | done | 20261026 | replay-reused-warehouse-has-1026 | PASS |
| market_analyst | done | 20261026 | replay-verified | PASS |
| position_manager | done | 20261026 | replay-v23-first-day | PASS |
| inspector | doing | 20261026 | —（本轮） | 正常（收尾置 done） |
| stock_picker | done | 20261024 | replay-v23-avoid41-pass9 | PASS |
| researcher | done | 20261024 | replay-v23-9buywatch | PASS |
| position_builder | done | 20261025 | replay-v23-9orders-50pct | PASS |
| reviewer | **doing** | 20261027 | null | **WARN（未收尾）** |
| archivist | **undo** | null | replay-reset | **WARN（随 reviewer 阻塞）** |

- 无 `status=doing` 的**陈旧**卡死（本轮 inspector 自身除外）；reviewer 的 `updated_at=2026-10-27T00:40:54` 与 inspector 置 doing 同一秒，判断为**并发启动、尚未收尾**，不是历史遗留。
- 无 `date` 陈旧的 done：done 的 date 落在 20261024–20261026，全部在本轮窗口（20261024–20261027）内。
- 全部 9 个 `updated_at` 均为 2026-10-27 00:37–00:40，说明状态由本轮重放统一改写，`date` 保留业务日，属预期语义。

### 2.2 产物新鲜度（date 字段 vs 文件 mtime）

| 文件 | date / as_of | mtime | 一致性 |
|---|---|---|---|
| state/pool.json | 20261023 | 10-27 00:35:54 | 一致（date=基准日，应为 20261023 ✅） |
| state/watchlist.json | 20261023（source_pool_date=20261023） | 10-27 00:35:56 | 一致，与 pool 同日 ✅ |
| state/orders.json | 20261023 | 10-27 00:39:27 | 一致（date=参考价基准日，见 W-4） |
| state/positions.json | as_of=20261026 | 10-27 00:39:27 | 一致（应为 20261026 ✅） |
| state/regime.json | 20261026 | 10-27 00:09:45 | 一致 ✅ |
| state/trades.jsonl | 1 行（20261026） | 10-27 00:39:27 | 一致 ✅ |

- 时间线自洽：pool(00:35) → watchlist(00:35) → orders(00:39 建仓) → regime(00:09 判定，00:38 复核) → positions/trades(00:39 执行)。
- regime.json 的 mtime（00:09）早于 market_analyst 置 done（00:38），与其 `reason=replay-verified`（复用+核验，非重算）相符；crowding 块 `manual_note` 亦注明为 10-27 补录，可追溯。

### 2.3 账本恒等式

| 项 | 值 |
|---|---|
| cash_cny | 968,770.00 |
| Σ market_value_cny | 31,230.00（600482.SH 1,000 股 × 31.23） |
| cash + Σmv | **1,000,000.00** |
| total_asset_cny | 1,000,000.00 |
| 偏差 | **0.0000%**（容差 0.1%）✅ |

- 市值口径用 20261026 收盘价 31.23，与成本相同 → 当日浮盈 0.00%，`total_pnl_pct=0.0` 合理（非"按成本偷懒计价"）。
- 持仓权重 3.12% = 31,230/1,000,000 ✅；`cash_pct` 96.88% ✅。
- 单只持仓：`stop_loss 28.73 < cost 31.23 < take_profit 37.48` ✅；且 28.73 = round(31.23×0.92,2)、37.48 = round(31.23×1.20,2)，符合 R-012 按实际成交成本重算（orders 原预览值 29.30/38.22 未被抄入）✅。

### 2.4 订单完整性

| 检查项 | 结果 | 判定 |
|---|---|---|
| 订单数 | 9 张（ORD-001~009），与 watchlist 9 只 buy_watch 一一对应 | PASS |
| order_id 唯一 | 无重复 | PASS |
| tranches 合计 100% | 9/9 张均为 100 | PASS |
| 单票权重 ≤15% | 最大 7.28%（601919），最小 3.82% | PASS |
| 单行业 ≤30% | 最大 火力发电 8.86%（淮河 5.04 + 长源 3.82） | PASS |
| 权重合计 | 50.01% = `planned_total_weight_pct` 50.01，≤ regime `position_cap_pct` 50 | PASS |
| 每单带 stop_loss / take_profit | 9/9；且均满足 stop<ref<tp | PASS |
| 每单带 10 日有效期 | 9/9（expires_after_trading_days=10，首个到期日 20261106） | PASS |
| **已成交单保留** | ORD-20261023-002 存在，status=filled_partial，tranche1 含 fill_date/fill_price/fill_shares/fill_amount，tranche2 仍 pending，其余 8 单未被删改 | PASS |
| **order_id ↔ trades.jsonl** | trades 唯一行 `order_id=ORD-20261023-002`，在 orders 中存在；orders 中唯一有 filled 档位的单也是 002 → **双向一一对应，0 孤儿** | PASS |
| trade 字段完整性 | buy、tranche=1、price 31.23、shares 1000、amount 31230.0、close=null、pnl=null（未平仓不填 pnl） | PASS |

### 2.5 数据源健康

| 项 | 结果 |
|---|---|
| data/warehouse/daily 最新日期 | 20261026.csv（5,570 行）；前一日 20261023（5,572 行） |
| data/daily_20261026/ 文件齐备 | 10/10：indices / market_overview / sector_ranking / news / hot_news / hot_board / dragon_tiger / northbound / cross_check / meta |
| meta.json | date=20261026，trading_day=true，fetched_at 2026-10-26T23:19:56，tushare+westock 双通道，record_counts 与 check_pipeline 实测一致（indices 5 / overview 8 / sector 124 / news 50 / hot_news 20 / hot_board 15 / dragon_tiger 89 / northbound 1） |
| research 三件套 | goodwill.csv 50 行、reduction.csv 50 行、audit.csv 50 行；对 pool 50 只 **coverage 100%/100%/100%**，`check_research_fresh.py` 退出码 0 = FRESH |
| 研究排雷结论 | 扫 50 只 → avoid 41 / buy_watch 9（`researcher_veto` 双条件 AND，符合 R-011） |
| regime | neutral，confidence 0.55，confirmed_days 2，evidence 10 条，risk_level medium，**position_cap_pct 50**（建仓已按 cap 而非 80 取数，符合 R-013） |
| 拥挤度 | 41.18%（mtd 口径，84 月样本），band=升温 / level=watch，mom -1.69 → 落 35-45 档，**规则 f 不干预**，与建仓用 50% 仓位不冲突 |
| skip_log | 末行为 20261024 non-trading-day，本轮无 skip 记录 |

---

## 三、预警清单

### CRITICAL
无。

### WARN

| ID | 问题 | 证据 | 影响 |
|---|---|---|---|
| W-1 | **日报 `reports/daily_20261026.md` 是旧轮次产物，与当前 state 矛盾** | 该文件生成于 10-26 23:53，正文写"参数 v2.0/v2.1"、"20 只 buy_watch / 30 只 avoid"、"orders.json 10 张 planned 买单"、"regime evidence 9 条"、"审查官 done / 档案员 done"；实际为 v2.3、9 只 / 41 avoid、9 张单、evidence 10 条、reviewer doing、archivist undo | 官方交付物失真，直接对外引用即误报 |
| W-2 | **流水线未闭环**：reviewer 停在 doing(20261027)，archivist 停在 undo(null) | `state/tasks/reviewer.json`、`archivist.json` 原始内容；`knowledge/rules.md` mtime 10-27 00:12，晚于 v2.3 参数但早于本轮执行 | 本周复盘与经验入库缺失，v2.3 首日实操教训（W-3 类）无法沉淀为规则 |
| W-3 | **建仓进度严重落后**：实际仓位 3.12% vs 目标 50.01%，缺口 46.89% | 18 档中仅 1 档触发；8 张单因 10-26 反弹未入 zone（振华 4.16 vs 4.14、东华 6.61 vs 6.56 仅差 1-2 分钱） | 资金 96.88% 闲置；R-006 首个到期日 20261106，若持续不触价将集中过期，需重设 ref 或接受长期低仓 |
| W-4 | **orders.json 顶层 `date` 字段语义混用**：date=20261023（参考价基准日），但同文件 `created_at`=2026-10-27、position_builder 任务 date=20261025 | `state/orders.json` 头部与 order 体 | 下游/复盘若用 `orders.date` 判新鲜度，会把一份 10-27 生成的订单误判为 10-23 陈旧产物；建议增加 `built_date` 或 `ref_date` 显式区分 |

### INFO

| ID | 说明 |
|---|---|
| I-1 | 首档股数取整偏保守：预算 1,000,000×6.79%×50% = 33,950 元 → 理论 1,087.1 股，实际成交 1,000 股（-8.0%），档位权重 3.12% vs 目标 3.395%；若按整百手取整，1,100 股（-0.05 万元）更贴近目标 |
| I-2 | 8 张在途单的**次档下沿低于当前 stop_loss**（如 001 次档下沿 13.95 < 止损 14.58；002 下沿 28.03 < 28.73）。已有 `stop_loss_if_tranche2_floor_filled` 兜底且 `stop_loss_recalc_required=true`，属 R-012 设计内；**但次档一旦成交必须重算，禁止沿用预览止损**，下轮持仓管家须复核 |
| I-3 | 回放口径未计佣金/印花税/滑点，成交价直接取 10-26 收盘价（31.23）；真实执行成本会使成本上移、仓位略低于名义值 |
| I-4 | 数据员未重拉数据（`reason=replay-reused-warehouse-has-1026`），复用 10-26 23:19 快照；meta `degraded=false`、10 个文件齐全，重放场景可接受，但意味着**本轮未验证数据通道可用性** |
| I-5 | `check_pipeline._record_count()` 在 payload 无 `records/items/dimensions/top_gainers/net_buy_top10` 键时**回退返回 1**，导致 indices.json（实际 5 只指数）、dragon_tiger.json（实际 89 条 / 73 只）均被打印成"1 records"。数据本身完好，但该兜底会把"只剩 1 条"的退化也判成 PASS，属监控盲点，建议改为按 `count` / `total_records` / `indices` / `data` 显式取数，取不到则 FAIL |

---

## 四、需要人介入的事项

1. **reviewer 收尾**（对应 W-2）：确认 2026-10-27 00:40 之后是否仍有 reviewer 进程在跑。若已死，执行 `task_status.py set reviewer undo --date 20261027 --reason stale-doing` 后重跑；**不得让它长期占用 doing**，否则 archivist 永远等不到 done。
2. **日报重生成**（对应 W-1）：`reports/daily_20261026.md` 需按 v2.3 现状（9 只 buy_watch、9 张单、evidence 10 条、reviewer/archivist 真实状态）整篇重写，或明确标注"10-26 23:53 版，已被 10-27 重放覆盖"。当前版本不可直接对外。
3. **建仓缺口决策**（对应 W-3）：3.12% 仓位是否接受"不追价、等回落"？若接受，则 20261106 前后需专门评估 8 张单的过期处置（重新取 ref 并重建 zone 须总控批准）；若不接受，需调整 ref 锚定口径（当前锚 20261023 收盘，与 10-26 反弹存在 10 天错位）。
4. **orders 日期字段口径**（对应 W-4）：是否给 orders.json 增补 `ref_date` / `built_date`，供下一轮复盘与总控做新鲜度判定时使用。

---

## 五、附录：check_pipeline 原始输出

```
[state] schema check done, 5 files + trades.jsonl
[state] business rules checked (populated files only)
[tasks] 9 task states checked
[crowding] history.csv 84 months
[crowding] 20261026 = 41.18% (watch / 升温)
[data] indices.json: 1 records
[data] market_overview.json: 8 records
[data] news.json: 50 records
[data] hot_news.json: 20 records
[data] hot_board.json: 15 records
[data] sector_ranking.json: 15 records
[data] dragon_tiger.json: 1 records
[data] northbound.json: 1 records

=== RESULT: PASS ===
exit code = 0
```

> 注：输出中的 `indices.json: 1 records`、`dragon_tiger.json: 1 records`、`northbound.json: 1 records` 为脚本计数口径缺陷，非数据缺失。实测：indices `count=5`（上证/深证/创业板等，全部 trade_date=20261026 命中）、dragon_tiger `total_records=89`（unique_stocks=73）、northbound `data` 10 个字段、sector_ranking `total_industries=124`（脚本打 15 = top_gainers 长度）。详见 INFO I-5。
