# 参数索引（knowledge/params_INDEX.md）

## 1. 唯一真源

| 项 | 说明 |
|---|---|
| 当前版本 | `v3.3`（见 `knowledge/params_current.txt`） |
| 唯一真源 | `knowledge/params_v3.3.json` |
| 生效日期 | 2026-10-28 |
| 校验入口 | `python scripts/check_pipeline.py` → `[params]` 段；任何一条不过即退出码 1 |

**规则**：同一概念在参数文件里只允许出现一次；脚本只从 `params_{params_current.txt}.json` 读取，硬编码默认值仅作异常兜底且必须与文件一致；任何文档/提示语/注释不得复述数值副本（R-014）。

## 2. 版本沿革

| 版本 | 关键变更 | 状态 |
|---|---|---|
| v1.0 | 4 因子加权求和 | 归档只读 |
| v1.2 | 扩到 17 因子 | 归档只读 |
| v1.3 | universe 收紧（双创/ST/流动性） | 归档只读 |
| v1.4 | 持仓数 8-12，两档买点 | 归档只读 |
| v1.7 | regime 分层（bull/neutral/bear） | 归档只读 |
| v1.8 | 财务因子迁研究员 | 归档只读 |
| v1.9 | 关闭换仓（rotation） | 归档只读 |
| v2.0 | **排除器 + 目标区间（target_zone）**，六年 +78.7%（旧口径） | 归档只读 |
| v2.1 | 止损锚实际成交成本；新增 veto（AND/5%） | 归档只读 |
| v2.2 | 市场拥挤度覆盖层（第 7 维） | 归档只读 |
| v2.3 | veto 改 OR；净利率 5%→2% | 归档只读 |
| v2.4~v2.7 | **未单独编号**，混写进 v2.3 文件：限价成交口径 / 熔断对齐实盘 / 三档买点 / R-022~R-025 | 内容并入 v3.x |
| v3.0 | **参数收敛**：消除重复定义、待决项显式化、回测默认值改为读参数。策略零改动 | 快照只读（同日被 v3.1 取代） |
| v3.1 | 排序口径变更：删除研究员财务质量分排序，`quality_score` = 选股分。六年 +20.65% → +46.94% | 快照只读 |
| v3.2 | 熔断口径变更：−8%减半/−12%清仓 → −15%降到40%/回到−8%解除/不清仓。+46.94% → +60.14% | 快照只读 |
| **v3.3** | **四项变更**：veto 改 AND/5%（扩候选池）｜止盈改一次减半+移动止损12%｜bull_rush 打开｜每日补仓+牛市集中6只。+60.14% → **+203.06%**（年化 7.11%→17.55%） | **生效中** |

### 历史文件处理
- `params_v1.0.json` ~ `params_v2.3.json`：**只读归档**，禁止修改、禁止作为真源引用、禁止新增。
- `params_v3.0.json` ~ `params_v3.2.json`：同日中间态快照，只读，禁止作为真源引用。
- `data/index_params.json`：指数定投线旧文件，内容已并入 `index_dca` 段。脚本优先读 v3.x 的 `index_dca`，读不到才回退它；确认稳定后可删除。
- 一次性彩排快照脚本（`test/scripts/run_position_builder_*.py` 等）仍引用旧字段名，已冻结不维护，不得在生产链路调用。

## 3. 域速查

| 域 | 字段路径 | 说明 |
|---|---|---|
| 选股范围 | `strategy.universe` | 北交所/双创/ST/上市天数/流动性门槛 |
| 选股方法 | `selection_method` | 排除器 + target_zone 打分（**唯一选股真源**，v3.1 定案 5 因子） |
| 因子权重 | `strategy.factors` | **legacy**，仅因子计算口径 + 回退模式使用 |
| 排序口径 | `researcher_quality.ranking_basis` | **v3.1 = selection_score**，强制 |
| 研究员职责 | `researcher_quality.role` | v3.1 起只排雷，`formula.active=picker_only` |
| 否决权 | `researcher_veto` | logic/roe_below/net_margin_below（P2） |
| 资金 | `capital` | 初始模拟资金（P9） |
| 仓位限制 | `position_limits` | 单票/单行业/持仓数 |
| regime | `regime.base_position_pct` / `.severity_action` | **唯一真源，无镜像段** |
| 风控熔断 | `risk.circuit` | 分档降仓（−15%→40%）、不清仓 + 单票止损止盈 |
| 止盈 | `risk.take_profit_trailing` | 只减一次 50% + 移动止损 12% |
| 补仓 | `execution_queue.topup` | 每日补到 cap/持仓数 |
| 集中 | `position_limits.bull_concentration` | bull 时只留前 6 只 |
| 权重分配 | `weight_allocation` | 质量归一化，qs = 选股分 |
| 买点 | `price_zone_rule` | 三档 + 成交口径 + bull_rush（关闭） |
| 拥挤度 | `crowding` | MTD 口径 + 覆盖规则 |
| 换仓 | `rotation` | 关闭 |
| 队列 | `execution_queue` | 挂单过期 / 队列有效期 / 冷却期 |
| 指数定投 | `index_dca` | 并入自 index_params.json |
| 待决 | `pending_decisions` | P1 已 resolved，其余待拍板 |
| 回测 | `backtest_registry` | 口径 + 结果对照，标明哪条可作预期 |

## 4. 架构分工（v3.1，R-026）

| 层 | 负责 | 产出 | 权限 |
|---|---|---|---|
| 选股师 | 技术反转 zone 打分 | `pool.json` 的 `score` | **唯一排序分来源** |
| 研究员 | 排雷 + 文字依据 | `avoid` 名单、thesis/risks | 只决定去留，**不打分不排序** |
| 建仓经理 | 跑脚本 + 校验 | `orders.json` | 权重按 `quality_score`（=选股分） |
| 持仓管家 | 成交/卖出/熔断 | `positions.json` | 按 params 阈值执行 |

财务判断只允许从两个口子进入：①`selection_method.target_zone` 的因子区间；②`researcher_veto` 硬否决。

## 5. 待决清单（摘要）

| ID | 议题 | 当前生效 | 状态 / 建议 |
|---|---|---|---|
| P1 | 排序口径 | **选股分（picker_only）** | **resolved v3.1** |
| P2 | veto 口径 | OR / 2% | 待拍板；AND/5% 回测 +57.93% vs OR/2% +46.44%（旧排序口径） |
| P3 | regime 仓位 90/70/60 | 90/70/60 | 待做对照回测 |
| P4 | bull_rush | **启用（confirmed ≥ 2）** | **resolved v3.3** |
| P5 | buy_watch 门槛 | 前 20 无门槛 | 保持 |
| P6 | 熔断口径 | **−15% 降到 40%、−8% 解除、不清仓** | **resolved v3.2**（+13.2pp，回撤几乎不变） |
| P7 | 行业上限 30% | 现行 | 与 P2 联动 |
| P8 | 队列有效期 | 已参数化 | 关闭 |
| P9 | 初始资金 | 100 万 | 待确认 |
| P10 | 实盘通道 | 人工下单 | 待确认 |

## 6. 回测口径警告

`backtest_registry.deprecated_basis` 的旧口径（收盘价判定成交 + 收盘价成交）结果**全部作废**：基线虚高约 27pp，且会放大参数间差异。引用任何回测数字前先确认 `basis` 与 `ranking`——v3.1 前后排序口径不同，**不可混排对比**。
