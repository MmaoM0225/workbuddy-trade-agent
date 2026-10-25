# Agent 产出统计与知识库健康度（agent_scores.md）

维护者：档案管理员。每周日 23:10 复盘官之后更新，只写 knowledge/。
口径：正式数据只取 `state/` `reports/` `data/` `reviews/`；`test/` 下彩排产物不计入。

---

## 2026-W43（2026-10-19 ~ 2026-10-25）· 入库周

**入库判定：** 复盘官 done（artifact=reviews/weekly_202643.md，22:05），本周有复盘输入 → 执行规则入库 + 参数评估 + 统计。

### 1. 本周各 agent 产出统计

| Agent | 指标 | 本周值 | 判定 |
|---|---|---|---|
| 数据员 | 周内交易日数 | 5（10/19~10/23） | — |
| 数据员 | 快照目录数 / 覆盖率 | 1 / 20% | `baseline-not-established`（automation 首跑 10-26 前不告警，见 R-009） |
| 数据员 | meta.json degraded 天数 | **0** | PASS |
| 数据员 | skip_log 记录 | 1（20261024 non-trading-day） | 预期内 |
| 数据员 | 已知降级点 | tushare news 40203 → westock 兜底（info，已闭环） | 已按 R-010 写入 meta.json |
| 市场分析师 | regime 判定 | neutral（base 50%） | PASS |
| 选股师 | 全市场 universe → Top50 | 5577 → 1810 → 50 | 手动跑（10-25 18:41） |
| 选股师 | 因子激活数 | 17 / 17 | PASS |
| 研究员 | 排雷覆盖 | 50 / 50（商誉、减持、审计 三项全查） | PASS |
| 研究员 | **池子被淘汰率（avoid / scanned）** | **8 / 50 = 16.0%** | 4 商誉超标 + 4 减持超标 |
| 研究员 | pass → buy_watch | 42 → 20 | 淘汰后余量充足 |
| 建仓经理 | planned 买单 / buy_watch | 10 / 20（取质量分前 10） | PASS |
| 建仓经理 | **orders 缺止损计数** | **0**（10/10 全部带 stop_loss） | PASS |
| 建仓经理 | 计划总仓位 | 49.99%（regime=neutral base 50%，单票 4.64~5.46%） | PASS |
| 持仓管家 | 在途订单处理 | 10 张 planned，未成交（空仓） | 无样本 |
| 持仓管家 | 卖单数 | 0（空仓） | N/A，非「通过」 |
| 总控巡检 | **critical 数** | **0**（3 条异常全为 info：手动 dry-run / 空壳文件预期 / regime 内部信号矛盾） | PASS |
| 总控巡检 | check_pipeline | PASS（退出码 0） | PASS |
| 复盘官 | 周报产出 | 1 份（reviews/weekly_202643.md） | PASS |
| 复盘官 | 平仓交易复盘 | 0 笔（空仓，非数据缺失） | 按 R-008 转健康度 + 纪律审计 |

### 2. 知识库入库情况

| 项 | 结果 |
|---|---|
| 复盘提交经验数 | 3（E-001 / E-002 / E-003） |
| **入库数** | **3**（R-008 / R-009 / R-010，全部新增 active） |
| **退回数** | **0** |
| 合并/退役 | 0（无重复、无矛盾） |
| 规则库总量 | R-001 ~ R-010，全部 active |

入库明细：
- E-001 空仓期复盘不空转 → **R-008**（有触发条件「trades.jsonl 无新增 close」+ 有动作）
- E-002 快照覆盖率基线判定 → **R-009**（有触发条件「快照数<交易日数」+ 有动作）
- E-003 数据源降级必须写进 meta.json → **R-010**（有触发条件「数据源切换兜底」+ 有动作）

### 3. 参数版本评估

| 项 | 结果 |
|---|---|
| 当前版本 | **v1.7**（未变更，params_current.txt 仍指向 v1.7） |
| 本周是否新建版本 | **否** |
| 理由 | 复盘未提出含数值的具体参数修改建议。第五节的「次档与止损线重叠」为**待拍板开放决策**（方案 A/B/C，B 推荐），非已定建议，故不擅自变更参数。待用户拍板后再按「一次只改一项」新建 v1.8 |

### 4. 调度健康度（任务状态 + skip_log）

| 任务 | 状态 | date | reason |
|---|---|---|---|
| data_officer | undo | 20261025 | reset-after-selftest |
| market_analyst | undo | 20261025 | init |
| position_manager | undo | 20261025 | init |
| inspector | undo | 20261025 | init |
| stock_picker | **done** | 20261025 | manual-weekend-run-full-market-17f-universe1810-v1.7 |
| researcher | **done** | 20261025 | manual-run-8avoid-42pass-20buywatch |
| position_builder | **done** | 20261025 | manual-run-10orders-49.99pct-neutral |
| reviewer | **done** | 20261025 | ok |
| archivist | **done** | 20261025 | ok（本周运行） |

- **skip_log `upstream-not-ready` 次数：0**（本周无因上游未就绪而空等的情形）
- skip_log 仅 1 条且为 `non-trading-day`（预期内，不计调度缺陷）
- 事件触发等待机制首次实战：档案管理员 wait reviewer → 一次就绪（退出码 0），无等待重试
- undo 的 4 个任务均为未到排班时间（首跑 10-26），非失败

### 5. 移交下周（2026-W44）的观察项

1. 10-26 起 automation 接管，快照覆盖率应达 100%，届时不足即按 R-009 判为真实异常
2. 首笔成交后开启真实卖出纪律审计（卖单须逐张带 trigger + reason）
3. 开放决策 5（次档 [-12%,-4%] 与止损 ref×0.92 重叠）待用户拍板，拍板后档案管理员按单项变更新建 params v1.8
4. 交易类经验（选股/择时/执行/风控归因）从 W44 起进入 reviews/index.jsonl，届时规则库将进入交易规则积累期
