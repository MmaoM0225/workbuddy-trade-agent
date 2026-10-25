# 项目长期记忆（E:/cashfree/agent）

## 项目定位
多 Agent 协同交易框架开发工作区。目标：WorkBuddy 内多智能体量化交易闭环（选股→优选→建仓→持仓管理→复盘→经验回流）。

## 目录边界（2026-10-25 立规）
- `test/` = 彩排/测试专用（data/scripts/reports/state 四子目录）。所有非正式运行产物落这里，**禁止写正式 state/**。
- 硬规则：彩排 orders 只写 `test/state/orders.json`——持仓管家工作日 23:20 会自动执行 state/orders.json 的 planned 订单，脏写=计划外建仓。
- 正式 automation 只写 state/、data/、reports/；scripts/ 为生产脚本，彩排脚本放 test/scripts/。
- 历史彩跑数据：test/data/20261025/（2026-10-23 基准，含 v1.2 因子得分与 v1.3 universe 重选文件 universe_200_v13.csv / fresh_codes.txt）。

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
- automation（ACTIVE）：P0-每日数据员（工作日 23:00）、P0-每日总控巡检（工作日 23:40），已统一挪到 23:00 后闲时档（原 15:35/15:50 作废），首跑 2026-10-26。
- 数据源实测结论：tushare index_daily/trade_cal 可用；westock market_overview/flash_news 可用；**tushare news 无权限（40203）**，快讯一律走 westock。
- 首个数据快照：data/daily_20261023/（5 指数 + 市场总览 + 14 快讯），校验 PASS。

## P1 智能体编排（2026-10-24 完成）
- **9 个 agent** 全部配好 automation（2026-10-25 决策：卖出交易员合并进持仓管家，10→9），**排班（2026-10-25 按实测耗时重排）**：工作日——数据员 23:00、市场分析师 23:10、持仓管家 23:20、总控 23:50；周六夜——选股师 21:30、研究员 23:30、建仓经理周日 00:10；周日——复盘官 22:00、档案管理员 23:10。
- **实测耗时（排班依据）**：选股师 114 min（10-25 演示跑文件时间戳 13:25→15:19 实测）、研究员 30-60、复盘官 20-40、持仓管家 5-15、数据员 3-5、分析师 5-8、总控 5-8。原 10 分钟间隔对周六/周日线完全不够，故重排。
- 执行模型：计划与执行分离。建仓经理只写 planned 买单；**持仓管家集卖出决策+执行于一体**（卖出触发→planned 卖单→同轮收盘价成交→回写 positions/trades/orders），纪律靠 rules.md R-002 + 复盘官周度审计（报告须列每张卖单 trigger/reason）+ 自我披露兜底。
- 每日流水线起跑时间原因：tushare index_daily 每天 19:00 更新。
- knowledge/ 种子文件：params_v1.0.json（默认多因子，默认模拟资金 100 万，待用户确认）、params_current.txt、rules.md（R-001~R-005 风控纪律）。

## 调度模型：事件触发（2026-10-25 用户提出并落地）
- 原模型=纯时间触发（固定间隔），实测选股师 114 min vs 10 min 间隔会读到陈旧 pool，故升级为**时间兜底 + 事件驱动**。
- 任务状态机：state/tasks/<task>.json（9 个任务文件，单写者），status = undo/doing/done；每 agent 启动置 doing、收尾置 done（带 reason + artifact）。
- **非交易日 = done + reason=non-trading-day**（不是 undo），下游立即通过等待并自行 skip，避免空等。
- 下游用 scripts/task_status.py wait --deps ... 轮询：单次最多阻塞 9 min（受 Bash 10 min 上限），重复调用直到各自预算（选股师下游 20 次≈180 min，其余 4-7 次）；未就绪则记 skip_log reason=upstream-not-ready 并退出，严禁在陈旧产物上作业。
- DAG：data_officer→market_analyst→position_manager→inspector；stock_picker→researcher→position_builder；reviewer→archivist。
- check_pipeline.py 已加第 5 项校验（tasks 目录 + 9 文件 + 状态枚举），校验 PASS。
- 工具：scripts/task_status.py {set|wait|get|list}；wait 退出码 0 就绪 / 1 未就绪 / 2 参数错。

## P1 选股链路已激活（2026-10-25）
- 用户确认首发策略 = 量化多因子（开源因子模型参考），params 现为 **v1.2（status=confirmed）**：17 因子 6 组（动量4：5d/10d/20d/60d；波动风险2；技术量价3：区间位置/量价相关/成交额趋势；质量4：ROE/毛利率/净利率/营收增速；估值3：EP/BP/SP；流动性1：换手），流程 = MAD 去极值 → 横截面百分位 → log 市值中性化 → 加权求和。扩展思路：同一批数据衍生多因子。
- 选股师（周六 21:30）、个股研究员（周六 23:30）、建仓经理（周日 00:10）三个 automation 已切 ACTIVE；首跑 **2026-10-31（周六）21:30**。
- 卖出交易员已撤销（2026-10-25）：用户选 B 方案——职责合并进持仓管家。原 prompt 五触发条件（止损/止盈/逻辑破坏/bear降仓/权重超限）已植入持仓管家步骤 4，步骤 5 同轮执行。
- 资金规模未确认前建仓经理按默认 100 万执行（prompt 已锁定不得自行调整）。
- 参数版本线：v1.0 默认4因子 → v1.1 七因子（确认日）→ v1.2 十七因子（用户反馈因子少，同日扩展）。

## 演示跑与 prompt v3 修复（2026-10-25）
- 手动演示跑验证全链路：universe=市值top200，17/17 因子激活，产出见 D:\ClawOutputs\选股演示跑报告_20261025.md；Top50 画像=大盘低波动量价值蓝筹，质量组暴露偏低待 IC 检验。
- 选股师 prompt 已升 v3（实测修正）：① fina_indicator 必须带 ts_code（不支持全市场），报告期回退 Q3→H1→Q1；② daily/weekly/fina_indicator 支持 ts_code 逗号批量（25 只/批），**禁按 trade_date 逐日拉全市场**（上下文爆炸）；③ 20 日动量需 21 个收盘价；④ 流程=两段式：daily_basic 全市场初筛 top300 → 200 只批量取证，预算 35/40 次。
- 接口权限备忘：stk_factor / tushare news 无权限（40203）。
- 数据落盘习惯：全市场原始数据先写 CSV 再计算（demo 数据在 data/demo_20261025/）。

## 数据仓库架构（2026-10-25，全市场筛选的正解）
- **全市场筛选必须走本地仓库**，不能 API 逐批取证：5500 只 × 4 类数据 ≈ 900 次调用，上下文必爆；fina_indicator 有 200 次/分钟硬限流。
- 仓库 data/warehouse/（已 .gitignore 排除）：daily/<交易日>.csv（21 天）、weekly/、daily_basic/、fina/（q3_all + h1_all + h1_part3）、meta/（stock_basic 含 market 字段、suspend_<date>）。
- 四个脚本（全部 MCP 直连 JSON-RPC，落盘不进上下文，限速 0.45s/批）：update_warehouse.py（周增量）、compute_full_market.py（17 因子全市场打分，POOL_OUT 环境变量控制输出，默认 state/pool.json）、research_check_mcp.py（逐只排雷）、build_watchlist.py + build_orders.py。
- 选股师 prompt 已改仓库模式（v4）：跑 update_warehouse.py → compute_full_market.py → 校验 pool.json，禁止 MCP 逐批取证。
- **接口批量能力实测**：daily / weekly / fina_indicator 支持 ts_code 逗号批量（25 只/批）；**balancesheet / stk_holdertrade / fina_audit 不支持批量，必须逐只**。

## 因子与规则关键修正（2026-10-25）
- **双创排除必须含 301/689**：创业板 = 300+301（合计 1411 只），科创板 = 688+689（618 只）。只排 300/688 会漏 476 只。
- **财务数据缺失 = 股票出局，不是剔除因子**：否则质量组（20% 权重）因覆盖率 69% 被整体剔除，小盘垃圾股涌入 Top。
- **Tushare daily amount 单位是千元**：5000 万元日成交额门槛 = 50,000（不是 5,000 万）。
- 全市场 universe 漏斗（2026-10-23 实测）：5577 → 剔北交所 353 → 剔双创 2029 → 剔 ST 141 → 剔次新 32 → 剔停牌 2 → 剔无财务 859 → 剔流动性 359 → **1802 只**。

## Universe 收紧（2026-10-25，params v1.3）
- 用户要求默认全开三个排除：北交所（.BJ）、双创板（300 创业板/688 科创板）、ST。params 升至 v1.3，universe 段新增 exclude_bj/exclude_gem_star/exclude_st + rules_detail，选股师 prompt 3b 同步显式化。
- 池子规模实测（2026-10-25 全市场 5577 只）：剔北交所 353 → 5224；剔双创 1553（创业板936+科创板617）→ 3671；剔 ST 143 → 3528；再加原有 250 日次新过滤 → 3469。市值 top300 门槛 437 亿。
- 影响预告：旧演示 Top20 中 6 只双创被排除（迈瑞、金山办公、联影、同花顺、温氏、东财）；按新规则本地重排 Top5 = 五粮液、伊利、川投能源、兴业、交行。

## 并行执行决策（2026-10-25）
- 用户问"筛选定时任务能否多 agent 同时执行" → 结论：**不拆多个 automation，在选股师 prompt 内并行**（单一写者原则 + 横截面一致性不能拆）。
- 选股师 prompt 已加【并行执行策略】：因子取证阶段用 Agent 工具派 3-4 个并行子 agent（daily×2 / weekly×1 / fina×1），子 agent 只回报汇总不回传原始数据；fina 缺口由主 agent 补派回退子 agent。
- 不拆多 automation 的理由：① 横截面排名/市值中性化必须全 universe 一起算，拆开破坏一致性；② 多 automation 需额外汇总编排（时序+失败处理），链路变脆；③ 并发打同一数据源有触发限流风险。
- 未来值得真拆的信号：universe 从 top200 扩到全市场 5000+ 只（数据量 28 倍），届时配合数据本地化工程重构。

## 数据仓库 data/warehouse/（2026-10-25 建立）
- 全市场数据本地化落库，18MB：daily/（21 个交易日全市场日线）、weekly/、fina/（118 文件）、daily_basic/20261023.csv（5572 只）、meta/stock_basic.csv（5577）+ suspend、research/。
- **scores_full.csv = 1802 只 × 17 因子全量打分**（v1.3 口径：0 只双创/北交所/ST；全市场 5572 → 剔 2574 → 再剔次新/停牌/流动性<5000万/因子缺失 1196 → 1802）。
- **选股必须走全市场**：旧"市值 top300 → 200 只"口径与实际全量 Top50 仅重合 1 只（2%），存在极端大盘偏误（银行 11 只占 22% vs 全量最大行业仅 10%）。选股师正式链路应直接用 warehouse 全量打分，不再做市值 top300 截断。
- 跑选股/研究前先查 warehouse 数据日期，避免用 test/data 下的旧样本。

## 工程地基（2026-10-24）
- git 仓库：E:/cashfree/agent，远程 origin = https://github.com/MmaoM0225/workbuddy-trade-agent.git（main，凭据用系统已存，推送成功）。变更后记得 commit+push。
- check_pipeline.py：schema + 数据完整性 + 业务规则（仅查已 populate 文件）；支持 --base/--date；退出码 0/1。总控每日调用。
- 所有 agent 第一步校验 trade_cal，非交易日只追加 data/skip_log.jsonl 后退出；报告按运行日期命名（daily_<run_date>.md / position_review_<run_date>.md）。
- 告警：总控发现 critical → mcp__agent-mail__SendMessage 发邮件到 ikdp5836@agent.qq.com（skip_confirmation=true，日限 1 封）；关闭=删 prompt 告警段。
- automation 执行记忆写在 .workbuddy/memory/automations/<automation_id>/memory.md。
