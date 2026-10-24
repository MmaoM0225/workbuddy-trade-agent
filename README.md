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
| `data/daily_YYYYMMDD/` | 每日标准化数据集（指数行情/市场全景/资讯 + meta.json） | 数据员 |
| `state/` | 共享状态文件（agent 间的唯一协同媒介） | 见下表 |
| `reports/` | 每日巡检报告 + 持仓检视报告 | 总控 / 持仓管家 |
| `reviews/` | 单笔复盘 + 周度总结 + index.jsonl | 复盘官 |
| `knowledge/` | 经验规则库 rules.md + 参数版本 params_v{n}.json + agent_scores.md | 档案管理员 |
| `scripts/` | 校验脚本 check_pipeline.py | 开发维护 |

## 智能体注册表（10 个，全部已配置 automation）

| 智能体 | 职责 | 调度 | 状态 |
|---|---|---|---|
| 数据员 | 采集指数/市场全景/快讯 → data/daily_* | 工作日 19:30 | ACTIVE |
| 市场分析师 | 判 regime → state/regime.json | 工作日 19:40 | ACTIVE |
| 持仓管家（兼模拟执行） | 模拟成交 + 检视预警 → reports/ + state 执行字段 | 工作日 20:00 | ACTIVE |
| 卖出交易员 | 卖出触发决策 → orders.json 卖单 | 工作日 20:10 | PAUSED（P2 激活） |
| 交易总监（总控） | 全链路巡检 → reports/daily_* | 工作日 20:15 | ACTIVE |
| 量化选股师 | 多因子选股 → pool.json | 周六 09:00 | PAUSED（待确认策略） |
| 个股研究员 | 池内深筛排雷 → watchlist.json | 周六 09:30 | PAUSED（待确认策略） |
| 建仓经理 | 建仓计划 → orders.json 买单 | 周六 10:00 | PAUSED（待确认策略） |
| 复盘官 | 单笔/周复盘 → reviews/ | 周日 09:00 | ACTIVE |
| 档案管理员 | 规则入库 + 参数版本 → knowledge/ | 周日 09:30 | ACTIVE |

流水线顺序（晚间跑的原因：Tushare 指数日线每天 19:00 更新，早跑只能拿到前一日数据）：
`数据员 19:30 → 市场分析师 19:40 → 持仓管家 20:00 → 卖出交易员 20:10 → 总控 20:15`

## state 文件契约（写者分工）

| 文件 | 写者 | 读者 |
|---|---|---|
| `pool.json` | 量化选股师 | 研究员、总控 |
| `watchlist.json` | 个股研究员 | 建仓经理、总控 |
| `regime.json` | 市场分析师 | 建仓/卖出/持仓管家、总控 |
| `positions.json` | 持仓管家（模拟成交记账） | 持仓管家、总控 |
| `orders.json` | 建仓经理/卖出交易员（创建计划）+ 持仓管家（执行状态）+ 总控（人工闸门状态） | 总控、人工 |
| `trades.jsonl` | 持仓管家（append-only 成交记录） | 复盘官、总控 |

执行模型：**计划与执行分离**——建仓经理/卖出交易员只创建 `planned` 计划；持仓管家是唯一执行者（按当日收盘价做模拟成交，记账到 positions/trades，回写 orders 执行状态）。实盘阶段指令最高到 `awaiting_human_confirm`，人工确认后才执行。

## 风控纪律（已编码进各 agent prompt + rules.md）

- 仓位公式：目标仓位 = regime 基础仓位（bull 80 / neutral 50 / bear 20）× 评分/100；单票 ≤15%、单行业 ≤30%
- 三级熔断：日亏 -3% 停开新仓 / 回撤 -8% 减半 / 回撤 -12% 清仓评估 + 冻结 5 日
- bear regime 禁止新建仓；止损触发即执行，禁止"再等等"
- 所有订单必须带 stop_loss + take_profit，缺失即作废重做

## 当前进度

- [x] **P0 骨架**：目录 + state schema + 校验脚本 + 数据员/总控
- [x] **P1 编排**：10 个 agent 的 automation 全部配置完成；知识库种子（params_v1.0 默认多因子 / rules.md R-001~R-005）
- [ ] P1 激活：选股链路 4 个任务处于 PAUSED，待确认首发策略方向 + 模拟资金规模后激活
- [ ] P2 持仓链路激活：卖出交易员（P1 跑出持仓后开启）
- [x] **P3 复盘闭环**：复盘官 + 档案管理员已激活（周日运转）
- [ ] P4 优化：参数寻优 + agent 评分

## 手动校验

```bash
C:\Users\19204\.workbuddy\binaries\python\versions\3.13.12\python.exe E:/cashfree/agent/scripts/check_pipeline.py --date 20261023
```

退出码 0 = 全部通过；1 = 存在 FAIL（详见输出）。
