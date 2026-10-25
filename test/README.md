# test/ — 彩排与测试专用目录

## 用途

所有**非正式运行**（手动彩排、链路验证、prompt 调试、参数试算）的产物全部落在这里，与正式运行目录物理隔离。

## 与正式目录的边界（硬规则）

| 正式（automation 写入） | 彩排（手动测试写入） |
|---|---|
| `state/pool.json`、`state/watchlist.json`、`state/orders.json` 等 | `test/state/` 下同名文件 |
| `data/`（每日数据快照、fetch 中间文件） | `test/data/<日期>/` |
| `scripts/`（生产脚本） | `test/scripts/`（彩排脚本） |
| `reports/`（agent 正式报告） | `test/reports/` |

**为什么必须隔离**：持仓管家（工作日 23:20）会自动读取 `state/orders.json` 中的 planned 订单并以收盘价成交。彩排订单若写入 `state/` 会被当真执行，造成计划外建仓。彩排的 orders 只能写 `test/state/orders.json`。

## 目录结构

```
test/
  README.md
  data/20261025/     # 2026-10-23 数据基准的彩排原始数据（日线/周线/财务/初筛）
  scripts/           # 彩排计算脚本（demo_score_20261025.py 等）
  reports/           # 彩排过程报告
  state/             # 彩排状态文件（pool/watchlist/orders 的 demo 版）
```

## 当前内容（2026-10-25）

- `data/20261025/`：选股师演示跑全量数据（200 只 universe 的日线 21 天、周线 17 周、财务指标、全市场 daily_basic/stock_basic/停牌名单、因子得分明细 factor_scores_200.csv）
- `scripts/demo_score_20261025.py`：17 因子打分脚本（params v1.2 规则；v1.3 的 universe 收紧版重跑时改用 universe_200_v13.csv）

## 彩排标准流程

1. 数据落 `test/data/<基准日期>/`
2. 脚本产 `test/state/pool.json`（含 notes 标注"彩排跑"）
3. 深筛产 `test/state/watchlist.json`
4. 建仓计划产 `test/state/orders.json`（**永远不写 state/orders.json**）
5. 汇总报告可交付到 `D:\ClawOutputs\`（用户全局产出目录）
