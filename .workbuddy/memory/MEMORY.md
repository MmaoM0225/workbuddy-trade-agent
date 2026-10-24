# 项目长期记忆（E:/cashfree/agent）

## 项目定位
多 Agent 协同交易框架开发工作区。目标：WorkBuddy 内多智能体量化交易闭环（选股→优选→建仓→持仓管理→复盘→经验回流）。

## 已定架构决策（2026-10-24）
- 协同模式：混合模式 = 定时 automation 流水线（每日盘后/每周选股/每周复盘）+ TeamCreate 实时会商（critical 预警/regime 切换/净值波动±3% 时升级）。
- agent 间不直接对话，通过共享状态文件协同（单一写者原则）：state/{pool,watchlist,regime,positions,orders}.json + trades.jsonl(append-only) + reviews/ + knowledge/。
- 复盘经验必须回流：档案管理员维护 knowledge/rules.md（可执行规则）与 params_v{n}.json（参数版本化，可回滚）。
- 风控：单票≤15%、单行业≤30%、regime 基础仓位 bull80/neutral50/bear20；三级熔断（日亏-3% 停开新仓/回撤-8% 减半/回撤-12% 清仓评估）；实盘指令最高只能到 awaiting_human_confirm，人工确认后才执行，框架不代按确认键。

## 用户偏好（本项目）
- 产出文档放 D:\ClawOutputs（用户全局偏好，C 盘空间紧张）。
- 已连接数据源：Tushare MCP、腾讯自选股 MCP。

## 开放决策（待昴拍板）
1. 首发选股策略方向（动量/基本面/多因子/事件驱动）
2. 初始模拟资金规模
3. Tushare 积分权限级别
4. 实盘通道（推荐：框架出指令 + 人工复核手动下单）

## 关键文件
- 设计方案：D:\ClawOutputs\多Agent协同交易框架设计方案.md（v1.0）
- 实施路线：P0 骨架 → P1 选股链路 → P2 持仓链路 → P3 复盘闭环 → P4 优化

## P0 已交付（2026-10-24）
- 骨架：E:/cashfree/agent/{data,state,reviews,reports,knowledge,scripts}；state 五文件按 schema 初始化，trades.jsonl append-only。
- 校验脚本：scripts/check_pipeline.py（用 managed python：C:\Users\19204\.workbuddy\binaries\python\versions\3.13.12\python.exe）。
- automation（ACTIVE）：P0-每日数据员（工作日 15:35）、P0-每日总控巡检（工作日 15:50），首跑 2026-10-26。
- 数据源实测结论：tushare index_daily/trade_cal 可用；westock market_overview/flash_news 可用；**tushare news 无权限（40203）**，快讯一律走 westock。
- 首个数据快照：data/daily_20261023/（5 指数 + 市场总览 + 14 快讯），校验 PASS。

## P1 智能体编排（2026-10-24 完成）
- 10 个 agent 全部配好 automation。ACTIVE：数据员 19:30、市场分析师 19:40、持仓管家 20:00、总控 20:15（工作日）；复盘官周日 09:00、档案管理员周日 09:30。PAUSED（待激活）：卖出交易员 20:10、选股师周六 09:00、研究员 09:30、建仓经理 10:00。
- 执行模型：计划与执行分离。建仓经理/卖出交易员只写 planned 计划；持仓管家是唯一模拟执行者（当日收盘价成交，写 positions.json/trades.jsonl/orders.json 执行字段）。
- 每日流水线 19:30 起跑的原因：tushare index_daily 每天 19:00 更新。
- knowledge/ 种子文件：params_v1.0.json（默认多因子，默认模拟资金 100 万，待用户确认）、params_current.txt、rules.md（R-001~R-005 风控纪律）。
- 选股链路激活前置：用户确认首发策略方向 + 模拟资金规模。
