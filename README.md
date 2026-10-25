# 多 Agent 协同交易框架（E:/cashfree/agent）

WorkBuddy 内的多智能体量化交易协同框架。完整闭环：

```
选股 → 优选 → 建仓 → 持仓管理（检视/减仓/清仓） → 复盘 → 经验回流
```

- **完整设计方案**：`D:\ClawOutputs\多Agent协同交易框架设计方案.md`（v1.0）
- **协同模式**：混合模式 = 定时 automation 流水线 + TeamCreate 实时会商（异常时升级）

## 目录结构

| 目录 | 内容 | 写者 |
|---|---|---|
| `data/daily_YYYYMMDD/` | 每日标准化数据集（9 文件：indices / market_overview(8维度) / sector_ranking / news(50) / hot_news / hot_board / dragon_tiger / northbound / meta） | 数据员 |
| `state/` | 共享状态文件（agent 间的唯一协同媒介） | 见下表 |
| `state/tasks/` | 任务状态文件（9 个，每任务一个，undo/doing/done） | 对应 agent 各自写 |
| `reports/` | 每日巡检报告 + 持仓检视报告 | 总控 / 持仓管家 |
| `reviews/` | 单笔复盘 + 周度总结 + index.jsonl | 复盘官 |
| `knowledge/` | 经验规则库 rules.md + 参数版本 params_v{n}.json + agent_scores.md | 档案管理员 |
| `scripts/` | 校验脚本 check_pipeline.py | 开发维护 |

## 智能体注册表（9 个，全部已配置 automation）

| 智能体 | 职责 | 调度 | 状态 |
|---|---|---|---|
| 数据员 | 采集指数/市场全景/快讯 → data/daily_* | 工作日 23:00 | ACTIVE |
| 市场分析师 | 判 regime → state/regime.json | 工作日 23:10 | ACTIVE |
| 持仓管家（卖出决策+模拟执行） | 卖出决策 + 模拟成交 + 检视预警 → reports/ + state | 工作日 23:20 | ACTIVE |
| 交易总监（总控） | 全链路巡检 → reports/daily_* | 工作日 23:50 | ACTIVE |
| 量化选股师 | 多因子选股 → pool.json | 周六 21:30 | ACTIVE（首跑 10-31） |
| 个股研究员 | 池内深筛排雷 → watchlist.json | 周六 23:30 | ACTIVE（首跑 10-31） |
| 建仓经理 | 建仓计划 → orders.json 买单 | 周日 00:10（周六夜延续） | ACTIVE（首跑 11-01） |
| 复盘官 | 单笔/周复盘 → reviews/ | 周日 22:00 | ACTIVE |
| 档案管理员 | 规则入库 + 参数版本 → knowledge/ | 周日 23:10 | ACTIVE |

流水线顺序（事件触发：下游启动后轮询前置任务 done 才开工，见下节）：
- 工作日：`数据员 23:00 → 市场分析师 23:10 → 持仓管家 23:20 → 总控 23:50`
- 周六夜：`量化选股师 21:30 →（实测需 90-120 分钟）→ 个股研究员 23:30 → 建仓经理 周日 00:10`
- 周日：`复盘官 22:00 → 档案管理员 23:10`

各 agent 实测/预估耗时与排班窗口：

| Agent | 耗时 | 说明 |
|---|---|---|
| 数据员 | 3–5 min | 7-9 次 MCP 调用 |
| 市场分析师 | 5–8 min | 单次深度推理 |
| 持仓管家 | 5–15 min | 随持仓数增长 |
| 总控 | 5–8 min | 校验 + 报告 |
| 量化选股师 | **90–120 min** | 2026-10-25 演示跑实测 114 min |
| 个股研究员 | 30–60 min | 20-30 只深研 |
| 建仓经理 | 10–20 min | 组合校验 + 下单 |
| 复盘官 | 20–40 min | 周汇总 + 纪律审计 |
| 档案管理员 | 10–20 min | 规则入库 + 参数版本 |

## state 文件契约（写者分工）

| 文件 | 写者 | 读者 |
|---|---|---|
| `pool.json` | 量化选股师 | 研究员、总控 |
| `watchlist.json` | 个股研究员 | 建仓经理、总控 |
| `regime.json` | 市场分析师 | 建仓经理、持仓管家、总控 |
| `positions.json` | 持仓管家（模拟成交记账） | 持仓管家、总控 |
| `orders.json` | 建仓经理（创建买单计划）+ 持仓管家（创建卖单计划 + 执行状态）+ 总控（人工闸门状态） | 总控、人工 |
| `trades.jsonl` | 持仓管家（append-only 成交记录） | 复盘官、总控 |
| `tasks/<task>.json` | 对应 agent 各自写（单写者） | 所有下游 agent、总控 |

执行模型：**计划与执行分离**——建仓经理只创建 `planned` 买单；持仓管家负责卖出决策（生成 `planned` 卖单）且是唯一执行者（按当日收盘价做模拟成交，记账到 positions/trades，回写 orders 执行状态）。卖出决策与执行同在一轮完成，纪律由 rules.md R-002（触发即执行）+ 复盘官周度审计兜底。实盘阶段指令最高到 `awaiting_human_confirm`，人工确认后才执行。

## 调度模型：事件触发（任务状态机）

时间排班只是"最早启动时间"，真正的先后由任务状态决定。每个任务有独立状态文件 `state/tasks/<task>.json`：

```json
{"task": "data_officer", "status": "done", "date": "20261026",
 "reason": "ok", "artifact": "data/daily_20261026", "updated_at": "..."}
```

- 状态机：`undo → doing → done`。agent 启动即置 doing，正常收尾置 done（带 reason 与产物路径）。
- 非交易日不是 undo，而是 `done + reason=non-trading-day`——下游看到 done 会立即通过等待，然后走自己的交易日校验自行 skip，不会出现"上游 skip 导致下游空等"。
- 下游启动后轮询前置任务，用 `scripts/task_status.py wait`（单次调用最多等 9 分钟，重复调用直到各自预算上限）。前置未就绪 → 记 skip_log（reason=upstream-not-ready）后退出，**绝不在陈旧产物上作业**。
- 依赖图（DAG）：

```
data_officer → market_analyst → position_manager → inspector
stock_picker → researcher → position_builder
reviewer → archivist
```

| 任务 | 依赖 | 等待预算 |
|---|---|---|
| data_officer | — | — |
| market_analyst | data_officer | 4 次 × 9 min |
| position_manager | market_analyst | 5 次 × 9 min |
| inspector | position_manager | 5 次 × 9 min |
| stock_picker | — | — |
| researcher | stock_picker | 20 次 × 9 min（覆盖选股师 P99） |
| position_builder | researcher | 7 次 × 9 min |
| reviewer | — | — |
| archivist | reviewer | 7 次 × 9 min |

工具：`python scripts/task_status.py {set|wait|get|list}`（`set` 原子写、`wait` 返回 0 就绪 / 1 未就绪 / 2 参数错）。

## 风控纪律（已编码进各 agent prompt + rules.md）

- 仓位公式：目标仓位 = regime 基础仓位（bull 80 / neutral 50 / bear 20）× 评分/100；单票 ≤15%、单行业 ≤30%
- 三级熔断：日亏 -3% 停开新仓 / 回撤 -8% 减半 / 回撤 -12% 清仓评估 + 冻结 5 日
- bear regime 禁止新建仓；止损触发即执行，禁止"再等等"
- 所有订单必须带 stop_loss + take_profit，缺失即作废重做

## 当前进度

- [x] **P0 骨架**：目录 + state schema + 校验脚本 + 数据员/总控
- [x] **P1 编排**：agent 的 automation 全部配置完成；知识库种子（params_v1.0 默认多因子 / rules.md R-001~R-005）
- [x] **工程地基**：git 仓库 + 远程推送、业务规则校验、全链路交易日校验（节假日不覆盖报告）、critical 邮件告警
- [x] **架构决策（10-25）**：卖出交易员职责合并进持仓管家（卖出决策+执行同轮完成），agent 数 10 → 9；选股链路（选股师/研究员/建仓经理）已 ACTIVE
- [x] **调度重构（10-25）**：时间排班按实测耗时重排（选股师 21:30、研究员 23:30、建仓经理周日 00:10、复盘官 22:00、总控 23:50）；新增任务状态机（state/tasks + scripts/task_status.py），流水线由时间触发升级为事件触发
- [ ] P1 激活收尾：选股链路首跑 2026-10-31（周六 21:30 选股师）；模拟资金规模待用户确认后建 params v1.4
- [x] **P3 复盘闭环**：复盘官 + 档案管理员已激活（周日运转）
- [ ] P4 优化：参数寻优 + agent 评分

## 运维

- **版本控制**：git 仓库已初始化，远程 `origin` = https://github.com/MmaoM0225/workbuddy-trade-agent.git（main 分支，已推送）。每次框架变更后提交并推送。
- **故障告警**：总控巡检发现 critical 异常时自动发邮件到 1920442561@qq.com（agent-mail，每日最多 1 封，无 critical 不发）。关闭方法：编辑「P0-每日总控巡检」prompt，删掉告警段即可。
- **节假日行为**：所有 agent 第一步都校验 trade_cal，非交易日只往 `data/skip_log.jsonl` 记一行后退出，不产生报告、不覆盖文件（2026-10-24 数据员首次实跑已验证）。
- **数据滞后**：Tushare 指数日线每天 19:00 更新；下游 agent 优先用当日数据，取不到自动回退最近数据日并标注 [数据滞后]。
- **调度策略**：两层。时间层——全部任务排在闲时（工作日 23:00-23:50、周六 21:30-次日 00:10、周日 22:00-23:10），23:00 时当日指数数据已更新完毕；逻辑层——事件触发（state/tasks 状态机），下游等前置 done 才开工，前置失败/超时则安全跳过，不会在陈旧数据上出决策。

## 手动校验

```bash
C:\Users\19204\.workbuddy\binaries\python\versions\3.13.12\python.exe E:/cashfree/agent/scripts/check_pipeline.py [--date 20261023] [--base <路径>]
```

校验内容：state schema 合法性 + trades.jsonl 行合法性 + 数据目录完整性 + **业务规则**（仅检查已 populate 的文件）：regime 枚举与证据数、positions 权重合计与单票 15% cap 与止损止盈 sanity、orders 档数与止损完备性、trades 价格与 pnl 完整性。

退出码 0 = 全部通过；1 = 存在 FAIL（详见输出）。`--base` 可指向测试副本。
