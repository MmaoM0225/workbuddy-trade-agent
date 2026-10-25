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
1. ~~首发选股策略方向~~ → 已定（2026-10-25）：量化多因子，参考开源因子模型（WorldQuant 101 / Alpha191 常用子集）
2. 初始模拟资金规模（暂按默认 100 万跑，确认后新建 params v1.2 修正）
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
- 10 个 agent 全部配好 automation，**全部排在 23:00 以后**（闲时成本，用户要求）：ACTIVE——数据员 23:00、市场分析师 23:10、持仓管家 23:20、总控 23:40（工作日）、复盘官周日 23:00、档案管理员周日 23:10；PAUSED——卖出交易员 23:30、选股师周六 23:00、研究员 23:10、建仓经理 23:20。
- 执行模型：计划与执行分离。建仓经理/卖出交易员只写 planned 计划；持仓管家是唯一模拟执行者（当日收盘价成交，写 positions.json/trades.jsonl/orders.json 执行字段）。
- 每日流水线 19:30 起跑的原因：tushare index_daily 每天 19:00 更新。
- knowledge/ 种子文件：params_v1.0.json（默认多因子，默认模拟资金 100 万，待用户确认）、params_current.txt、rules.md（R-001~R-005 风控纪律）。

## P1 选股链路已激活（2026-10-25）
- 用户确认首发策略 = 量化多因子（开源因子模型参考），params 现为 **v1.2（status=confirmed）**：17 因子 6 组（动量4：5d/10d/20d/60d；波动风险2；技术量价3：区间位置/量价相关/成交额趋势；质量4：ROE/毛利率/净利率/营收增速；估值3：EP/BP/SP；流动性1：换手），流程 = MAD 去极值 → 横截面百分位 → log 市值中性化 → 加权求和。扩展思路：同一批数据衍生多因子。
- 选股师（周六 23:00）、个股研究员（周六 23:10）、建仓经理（周六 23:20）三个 automation 已切 ACTIVE；首跑 **2026-10-31（下周六）23:00**。
- 卖出交易员仍 PAUSED：等 positions.json 非空后再激活。
- 资金规模未确认前建仓经理按默认 100 万执行（prompt 已锁定不得自行调整）。
- 参数版本线：v1.0 默认4因子 → v1.1 七因子（确认日）→ v1.2 十七因子（用户反馈因子少，同日扩展）。

## 演示跑与 prompt v3 修复（2026-10-25）
- 手动演示跑验证全链路：universe=市值top200，17/17 因子激活，产出见 D:\ClawOutputs\选股演示跑报告_20261025.md；Top50 画像=大盘低波动量价值蓝筹，质量组暴露偏低待 IC 检验。
- 选股师 prompt 已升 v3（实测修正）：① fina_indicator 必须带 ts_code（不支持全市场），报告期回退 Q3→H1→Q1；② daily/weekly/fina_indicator 支持 ts_code 逗号批量（25 只/批），**禁按 trade_date 逐日拉全市场**（上下文爆炸）；③ 20 日动量需 21 个收盘价；④ 流程=两段式：daily_basic 全市场初筛 top300 → 200 只批量取证，预算 35/40 次。
- 接口权限备忘：stk_factor / tushare news 无权限（40203）。
- 数据落盘习惯：全市场原始数据先写 CSV 再计算（demo 数据在 data/demo_20261025/）。

## 并行执行决策（2026-10-25）
- 用户问"筛选定时任务能否多 agent 同时执行" → 结论：**不拆多个 automation，在选股师 prompt 内并行**（单一写者原则 + 横截面一致性不能拆）。
- 选股师 prompt 已加【并行执行策略】：因子取证阶段用 Agent 工具派 3-4 个并行子 agent（daily×2 / weekly×1 / fina×1），子 agent 只回报汇总不回传原始数据；fina 缺口由主 agent 补派回退子 agent。
- 不拆多 automation 的理由：① 横截面排名/市值中性化必须全 universe 一起算，拆开破坏一致性；② 多 automation 需额外汇总编排（时序+失败处理），链路变脆；③ 并发打同一数据源有触发限流风险。
- 未来值得真拆的信号：universe 从 top200 扩到全市场 5000+ 只（数据量 28 倍），届时配合数据本地化工程重构。

## 工程地基（2026-10-24）
- git 仓库：E:/cashfree/agent，远程 origin = https://github.com/MmaoM0225/workbuddy-trade-agent.git（main，凭据用系统已存，推送成功）。变更后记得 commit+push。
- check_pipeline.py：schema + 数据完整性 + 业务规则（仅查已 populate 文件）；支持 --base/--date；退出码 0/1。总控每日调用。
- 所有 agent 第一步校验 trade_cal，非交易日只追加 data/skip_log.jsonl 后退出；报告按运行日期命名（daily_<run_date>.md / position_review_<run_date>.md）。
- 告警：总控发现 critical → mcp__agent-mail__SendMessage 发邮件到 ikdp5836@agent.qq.com（skip_confirmation=true，日限 1 封）；关闭=删 prompt 告警段。
- automation 执行记忆写在 .workbuddy/memory/automations/<automation_id>/memory.md。
