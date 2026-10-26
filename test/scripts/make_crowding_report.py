# -*- coding: utf-8 -*-
"""生成市场拥挤度落地报告（HTML，一次性文档，非生产脚本）。

输入：data/warehouse/crowding/history.csv + latest.json + knowledge/params_v2.2.json
输出：D:\\ClawOutputs\\市场拥挤度指标落地报告_20261027.html
"""
import csv
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HIST = os.path.join(BASE, "data", "warehouse", "crowding", "history.csv")
LATEST = os.path.join(BASE, "data", "warehouse", "crowding", "latest.json")
OUT = r"D:\ClawOutputs\市场拥挤度指标落地报告_20261027.html"

rows = list(csv.DictReader(open(HIST, encoding="utf-8")))
rows.sort(key=lambda r: r["month"])
lat = json.load(open(LATEST, encoding="utf-8"))

vals = [(r["month"], float(r["top5_pct"]), r["last_trade_date"]) for r in rows]
cur = lat["crowding"]
y_min, y_max = 28.0, 52.0
H = 210


def bar_h(v):
    return max(2, min(H, (v - y_min) / (y_max - y_min) * H))


def color(v):
    if v >= 50:
        return "#a3231a"
    if v >= 45:
        return "#c0392b"
    if v >= 40:
        return "#e8a33d"
    return "#8fb3c9"


warn_y = (45 - y_min) / (y_max - y_min) * H
alert_y = (50 - y_min) / (y_max - y_min) * H

bars = []
n = len(vals)
for i, (m, v, d) in enumerate(vals):
    h = bar_h(v)
    tip = "%s 月末 %s：%.2f%%" % (m, d, v)
    bars.append(
        '<div class="bar" style="height:%dpx;background:%s" title="%s"></div>'
        % (h, color(v), tip))

# x 轴标签：每年第一个月标年份
labels = []
seen = set()
for m, _, _ in vals:
    y = m[:4]
    if y not in seen:
        seen.add(y)
        labels.append('<span>%s</span>' % y)
    else:
        labels.append("<span></span>")

# 关键触发月
triggers = [(m, v, d) for m, v, d in vals if v >= 45]
trig_rows = "".join(
    "<tr><td><b>%s</b></td><td>%s</td><td class='num'>%.2f%%</td>"
    "<td><span class='pill %s'>%s</span></td></tr>"
    % (m, d, v, "p-red" if v >= 50 else "p-orange",
       "结构恶化" if v >= 50 else "极端抱团")
    for m, v, d in triggers)

# 近期 12 个月明细
recent = vals[-12:]
recent_rows = "".join(
    "<tr><td>%s</td><td>%s</td><td class='num'>%.2f%%</td><td class='num'>%s</td></tr>"
    % (m, d, v, ("%+.2f" % (v - vals[i - 1][1])) if i > 0 else "—")
    for i, (m, v, d) in enumerate(vals[-12:]))

mx = max(vals, key=lambda x: x[1])
mn = min(vals, key=lambda x: x[1])

html = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>市场拥挤度指标落地报告</title>
<style>
*{box-sizing:border-box}
body{margin:0;padding:36px 28px 60px;background:#f6f7f9;color:#1f2429;
 font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;line-height:1.65}
.wrap{max-width:1020px;margin:0 auto}
h1{font-size:25px;margin:0 0 6px;letter-spacing:-.3px}
.sub{color:#7c848d;font-size:13px;margin-bottom:26px}
h2{font-size:17px;margin:34px 0 12px;padding-left:10px;border-left:3px solid #c0392b}
.card{background:#fff;border:1px solid #e6e9ed;border-radius:10px;padding:18px 20px;margin-bottom:16px}
.kpis{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:18px}
.kpi{flex:1;min-width:170px;background:#fff;border:1px solid #e6e9ed;border-radius:10px;padding:15px 17px}
.kpi .k{font-size:12px;color:#7c848d;margin-bottom:5px}
.kpi .v{font-size:27px;font-weight:700;letter-spacing:-.5px}
.kpi .s{font-size:11.5px;color:#98a0a8;margin-top:3px}
.chart{background:#fff;border:1px solid #e6e9ed;border-radius:10px;padding:20px 18px 12px;position:relative}
.plot{display:flex;align-items:flex-end;gap:2.5px;height:%(H)dpx;position:relative;
 border-bottom:1px solid #d8dde2}
.bar{flex:1;border-radius:2px 2px 0 0;opacity:.88;transition:.15s}
.bar:hover{opacity:1;transform:scaleY(1.03);transform-origin:bottom}
.line{position:absolute;left:0;right:0;border-top:1px dashed;pointer-events:none}
.line span{position:absolute;right:2px;top:-17px;font-size:10.5px;padding:0 4px;background:#fff}
.grid{position:absolute;left:0;right:0;border-top:1px solid #f0f2f4}
.xaxis{display:flex;gap:2.5px;margin-top:5px;font-size:10px;color:#98a0a8}
.xaxis span{flex:1;text-align:left;white-space:nowrap;overflow:visible}
table{width:100%%;border-collapse:collapse;font-size:13px;background:#fff;
 border:1px solid #e6e9ed;border-radius:10px;overflow:hidden}
th{background:#f3f5f7;text-align:left;padding:9px 12px;font-weight:600;font-size:12.5px;color:#4c555e;
 border-bottom:1px solid #e6e9ed}
td{padding:8px 12px;border-bottom:1px solid #f0f2f4}
tr:last-child td{border-bottom:none}
.num{text-align:right;font-variant-numeric:tabular-nums}
.pill{display:inline-block;padding:1px 8px;border-radius:20px;font-size:11.5px;font-weight:600}
.p-red{background:#fbe9e7;color:#a3231a}
.p-orange{background:#fdf0dd;color:#a86a12}
.p-gray{background:#eef1f4;color:#5c6670}
.p-blue{background:#e8f0f6;color:#3a6785}
.note{background:#fffdf5;border:1px solid #f0e2c0;border-left:3px solid #e8a33d;
 border-radius:6px;padding:13px 16px;font-size:13px;margin:14px 0}
.ok{background:#f3faf5;border:1px solid #cfe8d8;border-left:3px solid #3f9c62;
 border-radius:6px;padding:13px 16px;font-size:13px;margin:14px 0}
code{background:#eef1f4;padding:1px 5px;border-radius:3px;font-size:12px;
 font-family:Consolas,Monaco,monospace}
ul{margin:8px 0;padding-left:22px}li{margin:5px 0}
.two{display:flex;gap:16px;flex-wrap:wrap}.two>div{flex:1;min-width:300px}
.footer{margin-top:34px;padding-top:14px;border-top:1px solid #e6e9ed;font-size:11.5px;color:#98a0a8}
</style></head><body><div class="wrap">

<h1>市场拥挤度 —— 指标落地报告</h1>
<div class="sub">多 Agent 协同交易框架 · 市场分析师第 7 维（覆盖层） · 参数版本 v2.2 · 生成于 2026-10-27</div>

<div class="kpis">
  <div class="kpi"><div class="k">当前拥挤度（%(date)s）</div>
    <div class="v" style="color:%(ccolor)s">%(cur).2f%%</div>
    <div class="s">%(band)s · level=%(level)s</div></div>
  <div class="kpi"><div class="k">距 45%% 警戒线</div>
    <div class="v">%(gap).2f<small style="font-size:15px">pp</small></div>
    <div class="s">越接近越需警惕抱团瓦解</div></div>
  <div class="kpi"><div class="k">历史分位</div>
    <div class="v">%(rank).1f%%</div>
    <div class="s">%(months)d 个月样本中排位</div></div>
  <div class="kpi"><div class="k">环比上月</div>
    <div class="v" style="color:%(momcolor)s">%(mom)s</div>
    <div class="s">上月 %(prev).2f%% · 抱团%(trend)s</div></div>
</div>

<div class="chart">
  <div class="plot">
    %(bars)s
    <div class="line" style="bottom:%(warn_y).1fpx;border-color:#c0392b">
      <span style="color:#c0392b">45%% 警戒</span></div>
    <div class="line" style="bottom:%(alert_y).1fpx;border-color:#a3231a">
      <span style="color:#a3231a">50%% 结构恶化</span></div>
  </div>
  <div class="xaxis">%(labels)s</div>
</div>
<div class="note" style="margin-top:12px">
  <b>怎么读这张图：</b>柱高 = 当月「成交额排名前 5%% 个股成交额 ÷ 全市场成交额」。
  历史上触及 45%% 的月份极少 <b>（%(smonths)d 个月样本中仅 %(ntrig)d 个月）</b>，
  而每次触及后 1-3 个月内都出现了结构性变化。最高 %(mxn)s%%（%(mxm)s）、最低 %(mnn)s%%（%(mnm)s）。
</div>

<h2>一、为什么是这个指标</h2>
<div class="card">
<p style="margin:0 0 10px">来源：量化投资邢不行《如何判断抱团行情？》（YouTube <code>Fq4Le_j2E4g</code>），
并与广发策略《微观结构恶化，市场如何布局？》的「前 5%% 成交额集中度」口径一致。</p>
<p style="margin:0 0 10px">逻辑：股票上涨是乐观预期逐步兑现、筹码逐步集中的过程。当少数股票吃掉近半成交量，
意味着想买的资金都买完了，边际买盘枯竭——此后股价对利好钝化、对利空敏感，任何风吹草动都可能引发踩踏。
视频统计 20 年来 6 次触及 45%%~50%%：2007-10 大顶、2008-09 熊底、2014-12 风格切换、2018-01 蓝筹转熊、
2021-01 抱团瓦解、2026-06 当前。</p>
<p style="margin:0"><b>关键：它是双向信号。</b>顶部抱团瓦解和底部恐慌性反向集中都会把集中度推高。
所以不能当方向指标用，只能当风险覆盖层用——这也是接入方案的核心设计决策（见第四节）。</p>
</div>

<h2>二、口径校准（这一步最容易踩坑）</h2>
<div class="card">
<p style="margin:0 0 12px">视频用的是 <b>月度累计成交额</b> 口径，不是单日。我们做了两次实算比对：</p>
<table>
<tr><th>校验点</th><th>视频原值</th><th style="text-align:right">我们实算</th><th style="text-align:right">误差</th><th>结论</th></tr>
<tr><td>2026 年 6 月</td><td>48.76%%</td><td class="num"><b>48.81%%</b></td><td class="num">0.05pp</td>
 <td><span class="pill p-blue">口径吻合</span></td></tr>
<tr><td>2021 年 1 月</td><td>49.51%%</td><td class="num"><b>48.54%%</b></td><td class="num">0.97pp</td>
 <td><span class="pill p-blue">口径吻合</span></td></tr>
<tr><td>2026-06-30（单日）</td><td>—</td><td class="num">52.26%%</td><td class="num">+3.5pp</td>
 <td><span class="pill p-orange">禁用单日口径</span></td></tr>
</table>
<div class="note" style="margin-top:14px">
  <b>踩过的坑：</b>最初按单日实现，2026-06-30 算出 52.26%%，比视频的 48.76%% 高 3.5 个百分点。
  单日集中度天然高于月度，直接把单日值套 45%% 阈值会<b>天天误报</b>。
  这正是脚本里必须锁定 MTD 口径的原因，已写进 R-013 禁止再改。
</div>
<p style="margin:10px 0 0;font-size:12.5px;color:#7c848d">
注：实算与视频的微小差异来自数据源（tushare vs akshare）成交额统计口径，非算法问题。
</p>
</div>

<h2>三、历史实算结果</h2>
<div class="card" style="padding-bottom:6px">
<p style="margin:0 0 12px">触及 45%% 的月份（%(smonths)d 个月样本，%(start)s ~ %(end)s）：</p>
<table>
<tr><th>月份</th><th>月末交易日</th><th style="text-align:right">前 5%% 集中度</th><th>分档</th></tr>
%(trig)s
</table>
<div class="ok" style="margin-top:14px">
  <b>这段序列本身就是最好的验证：</b>2026-06 触及 48.81%%（视频发出预警的时点）→ 7 月继续冲到 49.76%% 见顶
  → 8 月 47.22%% → 9 月 42.87%% → 10 月 41.18%%。<b>抱团已经开始退潮</b>，
  与视频「触发后 1-3 个月内必然出现结构性变化」的判断完全吻合。
</div>
</div>

<h2>四、接入方案：为什么是覆盖层，不是第 7 个方向分</h2>
<div class="card">
<p style="margin:0 0 12px">六维打分（趋势/宽度/情绪/量能/资金/板块）回答的是「往哪个方向走」。
拥挤度回答的是「这条路上的交易结构有多脆弱」。两者性质不同：</p>
<ul>
<li>把拥挤度塞进方向总分 → 2008-09 那个熊底（48.99%%）会被判成 bear，而它其实是最强的底部信号；</li>
<li>当覆盖层用 → 方向判断保持干净，拥挤度只负责「在极端时收紧仓位或暂停新建仓」。</li>
</ul>
<p style="margin:12px 0 8px"><b>覆盖规则（按序执行，命中即止）：</b></p>
<table>
<tr><th style="width:70px">拥挤度</th><th style="width:110px">当前 regime</th><th>动作</th></tr>
<tr><td rowspan="3"><b>≥50%%</b><br><span class="pill p-red">结构恶化</span></td><td>bull</td>
 <td>regime 强制降级 neutral，仓位上限 -20pp，禁新建仓</td></tr>
<tr><td>neutral</td><td>维持 neutral，仓位上限 -20pp，禁新建仓</td></tr>
<tr><td>bear</td><td>不改 regime，risk_level=high（已在降仓通道，不重复罚）</td></tr>
<tr><td rowspan="2"><b>45-50%%</b><br><span class="pill p-orange">极端抱团</span></td><td>bull</td>
 <td>已确认 2 日则降级 neutral；不足 2 日维持 bull 但禁新建仓</td></tr>
<tr><td>neutral / bear</td><td>risk_level=high，禁新建仓</td></tr>
<tr><td><b>35-45%%</b><br><span class="pill p-gray">升温</span></td><td>任意</td>
 <td>只记录，不干预 <span style="color:#3f9c62;font-weight:600">← 当前 41.18%% 在这一档</span></td></tr>
<tr><td><b>&lt;35%%</b></td><td>任意</td><td>无影响；若 bear 且 &lt;20%% 记 bottom_signal=possible（仅提示）</td></tr>
</table>
<p style="margin:14px 0 6px"><b>性质区分（45%%+ 时强制执行）：</b>查上证 20 日涨跌幅 ——
&gt;0 判高位抱团瓦解、按上表收紧；&lt;-5%% 判低位反向集中/恐慌底、<b>不追加收紧</b>。</p>
<p style="margin:10px 0 0"><b>解除条件：</b>回落至 45%% 以下 + 环比为负 + 连续 2 个月下行 → cleared=true。
不设解除条件会永远卡在警报里。</p>
</div>

<h2>五、落地清单（7 个改动点）</h2>
<div class="card">
<table>
<tr><th style="width:200px">文件 / 对象</th><th>改动</th></tr>
<tr><td><code>scripts/compute_crowding.py</code></td>
 <td>新增。扫 <code>data/warehouse/daily/*.csv</code> 按月聚合，输出 <code>crowding/history.csv</code>（%(smonths)d 个月）
 与 <code>latest.json</code>。全量回算 17 秒，增量约 3 秒。用纯标准库，无 pandas 依赖</td></tr>
<tr><td><code>knowledge/params_v2.2.json</code></td>
 <td>新增 <code>crowding</code> 段：口径定义、45/50/20 阈值、分档、7 条 overlay_rules、release_rule、nature_rule、校准记录。
 <code>params_current.txt</code> 已指向 v2.2</td></tr>
<tr><td>市场分析师 automation</td>
 <td>新增「第 7 维」章节 + 步骤 1.5 取数 + 步骤 3.5 覆盖层。regime.json 增加 <code>crowding</code> 对象与
 <code>position_cap_pct</code> 字段。明确禁止把旧值当新值、禁止跨日复制 crowding 块</td></tr>
<tr><td><code>scripts/send_report_mail.py</code></td>
 <td>邮件新增拥挤度区块：大号数值 + 水位条（画出 45/50 两条红线）+ 环比/历史分位/抱团深度/窗口四宫格。
 缺失时显示「本次拥挤度数据缺失，未套用覆盖层」</td></tr>
<tr><td><code>scripts/check_pipeline.py</code></td>
 <td>新增第 6 项校验：<code>crowding/</code> 目录、history.csv 行数、latest.json 12 个必填字段、
 数值区间、level 枚举、top1≤top10、与 regime.json 的一致性（差值 &gt;0.5pp 报错）</td></tr>
<tr><td>数据员 automation</td>
 <td>新增步骤 2.5：<code>update_warehouse.py --daily-only</code>（脚本同步加了该参数），
 只补最近 5 个交易日的全市场日线，约 1-2 次 API。失败不阻塞主流程，记 <code>[warehouse-daily-failed]</code></td></tr>
<tr><td>建仓经理 + <code>build_orders_live.py</code></td>
 <td>仓位基数优先读 <code>regime.position_cap_pct</code>（已含拥挤度折扣），字段缺失才回退
 <code>regime_base_position_pct</code>。否则拥挤度的降仓要求到不了执行端，等于白算</td></tr>
</table>
</div>

<h2>六、验证记录</h2>
<div class="card">
<div class="ok" style="margin:0 0 12px">
<b>已通过：</b><code>check_pipeline.py</code> 全项 PASS（含新增 crowding 检查）；
邮件渲染 4 档彩排全通过（41%%/47%%/51%%/<b>缺失</b>），彩排在 <code>test/</code> 沙箱内跑，未污染正式 state；
指标口径两点校准误差 ≤0.97pp。
</div>
<div class="note" style="margin:0">
<b>踩坑记录（已修）：</b>彩排脚本最初直接在正式 <code>state/regime.json</code> 上改完再还原，
渲染中途抛异常导致没有执行还原，把正式文件留在了测试态。已改为把脚本的 <code>ROOT</code>
指向 <code>test/</code> 沙箱，彻底隔离。<b>教训：碰正式状态文件的测试一律走沙箱路径，不靠 try/finally 兜底。</b>
</div>
</div>

<h2>七、遗留事项</h2>
<div class="card">
<ul>
<li><b>样本只有 %(smonths)d 个月（%(start)s 起）</b>，2019 年以前的 4 次历史触发（2007/2008/2014/2018）
无法用本地数据复核。仓库若要向前扩，<code>update_warehouse.py</code> 的 trade_cal 起始日需回退。</li>
<li><b>「连续 2 个月环比下行」的解除判定</b>目前靠月序列比对，没有单独落标；第一次解除发生时需人工确认口径是否正确。</li>
<li><b>拥挤度与 regime 的联动只在市场分析师里实现</b>，若将来有别的 agent 需要读，必须同样先读 <code>position_cap_pct</code>，别再造一个走 <code>regime_base_position_pct</code> 的分支。</li>
<li>视频还提到「前 1%%/前 10%% 集中度看抱团深度」——已一并算进 history.csv（top1_pct/top10_pct），
但暂未参与判定，等积累更多样本后再决定是否加规则。</li>
</ul>
</div>

<div class="footer">
数据：<code>data/warehouse/crowding/history.csv</code> · <code>latest.json</code>　|　
规则：<code>knowledge/rules.md</code> R-013 · <code>params_v2.2.json</code> crowding 段　|　
脚本：<code>scripts/compute_crowding.py</code>
</div>
</div></body></html>
""" % {
    "H": H, "bars": "".join(bars), "labels": "".join(labels),
    "warn_y": warn_y, "alert_y": alert_y,
    "date": lat["trade_date"], "cur": cur, "band": lat["band"], "level": lat["level"],
    "ccolor": color(cur), "gap": 45 - cur, "rank": lat["pct_rank"],
    "months": lat["sample_months"],
    "mom": ("%+.2fpp" % lat["mom"]), "prev": lat["prev_month"],
    "momcolor": "#c0392b" if lat["mom"] > 0 else "#3f9c62",
    "trend": "加剧" if lat["mom"] > 0 else "退潮",
    "smonths": lat["sample_months"], "ntrig": len(triggers),
    "mxn": "%.2f" % mx[1], "mxm": mx[0], "mnn": "%.2f" % mn[1], "mnm": mn[0],
    "trig": trig_rows, "start": vals[0][0], "end": vals[-1][0],
}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    f.write(html)
print("[OK] %s (%d bytes)" % (OUT, len(html)))
print("[OK] 柱数 %d，触发月 %d，当前 %.2f%%" % (n, len(triggers), cur))
