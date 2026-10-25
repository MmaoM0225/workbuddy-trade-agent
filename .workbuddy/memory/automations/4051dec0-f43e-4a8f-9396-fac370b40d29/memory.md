# 复盘官 automation（每周日 22:00）执行记忆

## 2026-10-25（首次运行）
- 输入状态：state/trades.jsonl 空、positions 空仓、orders 10 张 buy 全 planned → **0 笔平仓交易**。
- 分支：走「无平仓」路径，周报主体改为数据管道健康度 + 卖出纪律审计。产出 `reviews/weekly_202643.md`；task reviewer → done(reason=ok)。reviews/index.jsonl 保持不创建（无交易不写空条目）。
- 耗时约 5 分钟（远低于 20-40 分钟预估，因无逐笔复盘）。
- 健康度实测：快照覆盖率 20%(1/5)、degraded 0、巡检异常 3 条全 info、check_pipeline PASS、skip_log 1 条。
- 已固化的口径（后续沿用）：
  - 快照覆盖率：2026-10-26 automation 首跑前记为 baseline-not-established 不告警，之后 <100% 判异常。
  - 卖出纪律审计：无样本记 N/A，不得写成「通过」。
  - 范围：只读 state/ + reports/ + data/；test/ 彩排回放不计入正式绩效。

## 下次运行注意
- 2026-10-26 起若 10 张买单触发成交，W44 起应有真实持仓与可能的平仓交易，需按 reviews/<平仓日期>_<code>.md 结构逐笔复盘并追加 index.jsonl。
- 关注待拍板的开放决策 5（次档买点与止损线重叠），建仓后成实地风险。
