# 指数估值定投 · 日更报告 20261028

**运行时间**：2026-10-28 23:20
**参数线**：knowledge/index_params.json v1.0
**交易日校验**：通过（data/warehouse/daily/20261028.csv，5570 只个股）

---

## 一、结论（先看这里）

**本次流水线在第 1 步中断，未能刷新 20261028 估值数据。**

- 失败点：`pull_index_valuation.py` → `KeyError: 'neodata'`
- 根因：本会话 MCP 配置中不存在 `neodata` 连接器（仅剩 connector-proxy / agent-mail / genie-baas / space-library / weixinpay / sheetagent），neodata 直连端点 `https://neodata.tencent.com/proxy/mcp` 返回 **HTTP 401 token 缺失或无效**
- 按执行规则「任一脚本非 0 退出即停止」，第 2~6 步均未执行，现场数据原样保留

**因此下列清单不是 20261028 新算结果**，而是账本内当前有效的上期计划：
**as_of = 20261027，生成时间 2026-10-28 22:11:15**（signal_history/20261027.json、index_orders.json）。

---

## 二、数据滞后说明

| 数据 | 最新日期 | 状态 |
|---|---|---|
| 指数估值 index_valuation（13 条宽基） | 20261027 | 缺 20261028 |
| 申万二级行业 sw_industry | 97 个文件（应 124） | 缺 20261028 |
| 指数信号 state/index_signal.json | as_of=20261027 | 滞后 1 个交易日 |
| 个股日线 daily | 20261028 | 最新 |

补充：今日 22:12 的上一次成功运行，其拉取结果同样止于 20261027，说明该估值源存在 **T+1 发布节奏**。故本次即使刷新成功，as_of 大概率为 20261027、计划内容与本清单一致——但此点**未经本次运行验证**。

---

## 三、本期买入清单（as_of 20261027）

共 11 笔，合计 360 元。

| # | 标的 | 类别 | 分位 | 倍数 | 金额 | 场外基金代码 | 基金名称 |
|---|---|---|---|---|---|---|---|
| 1 | 恒生科技 | 宽基 | 4.8 | 2.0x | 40 | 012804.OF | 广发恒生科技ETF联接(QDII)-A |
| 2 | 纳斯达克100 | 宽基 | 6.0 | 2.0x | 40 | 000834.OF | 大成纳斯达克100ETF联接(QDII)-A |
| 3 | 创业板指 | 宽基 | 17.0 | 1.5x | 30 | 003765.OF | 广发创业板ETF联接-A |
| 4 | 中证A500 | 宽基 | 28.6 | 1.0x | 20 | 022434.OF | 南方中证A500ETF联接-A |
| 5 | 中证1000 | 宽基 | 37.4 | 1.0x | 20 | 011860.OF | 南方中证1000ETF联接-A |
| 6 | 标普500 | 宽基 | 38.0 | 1.0x | 20 | 050025.OF | 博时标普500ETF联接(QDII)-A-CNY |
| 7 | 能源金属 | 行业 | 6.2 | 2.0x | 40 | 004432.OF | 南方有色金属ETF联接A |
| 8 | 动物保健Ⅱ | 行业 | 7.1 | 2.0x | 40 | 016077.OF | 华夏中证农业主题ETF发起式联接A |
| 9 | 电池 | 行业 | 7.6 | 2.0x | 40 | 013179.OF | 广发国证新能源车电池ETF发起联接A |
| 10 | 证券Ⅱ | 行业 | 9.5 | 2.0x | 40 | 004069.OF | 南方中证全指证券公司ETF联接A |
| 11 | 计算机设备 | 行业 | 14.8 | 1.5x | 30 | 001629.OF | 天弘中证计算机主题ETF联接A |

注：6 只 QDII（恒生科技/纳指100/标普500）需人工确认申赎状态与限购额度。

## 四、卖出清单

**无。**（总卖出金额 0；无标的同时满足 分位≥75 + 距上次卖出≥20 交易日）

## 五、账本三项

| 项目 | 金额（元） |
|---|---|
| 累计投入 | 0.00 |
| 已实现盈亏 | 0.00 |
| 未实现盈亏 | 0.00 |
| **总资产** | **0.00** |
| 收益率 | 0.00% |

账本为 20261028 新建空账（holdings 为空、history 为空），本期为首次建仓计划。

## 六、过滤与停投

- 行业共 124 个，其中综合分位 <40 的有 **75 个**
- 被 **隐含ROE(PB/PE) 同比 >15%** 条件挡掉 **64 个**（含 PE≤0 及 roe_chg 缺失视为不合格），典型：白酒Ⅱ(17.5)、中药Ⅱ(3.9)、普钢(34.2)、乘用车(0.4)、光伏设备(23.2)
- 因此行业端仅 5 个名额可买：能源金属、动物保健Ⅱ、电池、证券Ⅱ、计算机设备
- 全标的停投（mult=0）共 **56 个**

## 七、失败详情（保留现场）

```
$ python scripts/pull_index_valuation.py --start 20190101
Traceback (most recent call last):
  File "scripts/pull_index_valuation.py", line 255, in <module>
    sys.exit(main())
  File "scripts/pull_index_valuation.py", line 237, in main
    client = get_client()
  File "scripts/pull_index_valuation.py", line 103, in get_client
    srv = cfg["mcpServers"][key]
KeyError: 'neodata'
```

连通性探测（未落任何数据）：

| 数据源 | 端点 | 结果 |
|---|---|---|
| neodata | https://neodata.tencent.com/proxy/mcp | 401 token 缺失或无效 / token 错误 |
| tushare | https://api.tushare.pro/mcp/（本地 token） | 正常，258 个工具 |

结论：**tushare 通道正常，neodata 通道失权**。第 3 步（基金净值，仅依赖 tushare）本可执行，但因前置步骤失败按规则未继续。

恢复方式：在 WorkBuddy 连接器菜单中重新启用 / 授权「腾讯金融科技NeoData」连接器，使 `mcpServers.neodata` 重新出现在会话配置中。

---

**这是计划，需人工在下一交易日 15:00 前完成场外申购；成交后用 `python scripts/update_index_portfolio.py --commit` 登记。**
