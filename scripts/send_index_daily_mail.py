#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把指数定投日更发到邮箱（agent-mail MCP 直连）。

默认行为（2026-10-29 起）：
  正文 = reports/index_valuation_<as_of>.html 完整看板，**邮件内可直接点**
  附件 = 无（除非显式 --attach）

为什么能在邮件里点：看板改为零 JS + 零 <style> 依赖，交互全部用 HTML 原生能力——
  · <details>/<summary> 折叠（按档位分组，点标题展开/收起）
  · <a href="#id"> 锚点跳转（顶部导航条直达各档位）
这两个都是浏览器内建行为，不靠脚本也不靠样式表，邮件客户端剥什么都还在跑。
筛选/搜索/排序这类必须 JS 的东西一律不做（旧版做了，发到邮箱全是死按钮）。

用法：
  python scripts/send_index_daily_mail.py                    # 默认：看板全文当正文 + 无附件
  python scripts/send_index_daily_mail.py --attach           # 额外附带 .html（方便再分享）
  python scripts/send_index_daily_mail.py --notice --attach  # 极简正文 + 看板附件
  python scripts/send_index_daily_mail.py --summary          # 680px 摘要邮件（无分位明细）
  python scripts/send_index_daily_mail.py --to a@b.com,c@d.com
  python scripts/send_index_daily_mail.py --dry-run          # 只渲染落盘，不发信
"""
import argparse
import base64
import hashlib
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from update_warehouse import McpClient  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TO = "1920442561@qq.com"

C_DEEP, C_UNDER, C_LOW = "#047857", "#15803d", "#4d7c0f"
C_NORM, C_HIGH, C_SELL = "#6b7280", "#b45309", "#dc2626"


CAT_STYLE = {
    "国内宽基": ("#1d4ed8", "#e0e7ff"),
    "国外宽基": ("#7c3aed", "#ede9fe"),
    "行业": ("#5b21b6", "#f3f0ff"),
}


def cat_of(kind, market):
    """展示分类：国内宽基 / 国外宽基 / 行业。策略仍按 kind 两分法，不受影响。"""
    if kind == "industry":
        return "行业"
    return "国内宽基" if (market or "CN").startswith("CN") else "国外宽基"


def fnum(v, d=2):
    if v is None or v == "":
        return "—"
    try:
        return ("%." + str(d) + "f") % float(v)
    except (TypeError, ValueError):
        return "—"


def pct_color(p):
    if p is None:
        return C_NORM
    if p < 10:
        return C_DEEP
    if p < 25:
        return C_UNDER
    if p < 40:
        return C_LOW
    if p < 60:
        return C_NORM
    if p < 75:
        return C_HIGH
    return C_SELL


def td(v, align="right", color="#111827", bold=False, size="13px"):
    return ('<td align="%s" style="padding:7px 10px;border-bottom:1px solid #eef0f3;'
            'font-size:%s;color:%s;%sfont-family:-apple-system,\'PingFang SC\',\'Microsoft YaHei\',sans-serif;'
            'font-variant-numeric:tabular-nums;">%s</td>'
            % (align, size, color, "font-weight:600;" if bold else "", v))


def th(label, align="right"):
    return ('<th align="%s" style="padding:8px 10px;border-bottom:1px solid #e5e7eb;'
            'font-size:11px;color:#6b7280;font-weight:600;text-align:left;white-space:nowrap;'
            'font-family:-apple-system,\'PingFang SC\',\'Microsoft YaHei\',sans-serif;">%s</th>'
            % (align, label))


def stat_cell(label, value, color="#111827", sub=""):
    return ('<td width="25%" align="center" style="padding:14px 6px;border:1px solid #e5e7eb;border-radius:8px;'
            'font-family:-apple-system,\'PingFang SC\',\'Microsoft YaHei\',sans-serif;">'
            '<div style="font-size:11px;color:#6b7280;margin-bottom:5px;">' + label + '</div>'
            '<div style="font-size:19px;font-weight:650;color:' + color + ';letter-spacing:-.5px;">' + value
            + '<span style="font-size:11px;font-weight:400;color:#9ca3af;">' + sub + '</span></div></td>')


def build_body(orders, sig, params, as_of, data_date):
    items = sig["items"]
    buys = orders.get("buys", [])
    sells = orders.get("sells", [])
    total_buy = orders.get("total_buy_cny", 0)
    total_sell = orders.get("total_sell_cny", 0)

    rf = params.get("execute", {}).get("industry_roe_filter", {})
    roe_th = rf.get("roe_th", 0.15)

    n_stop = sum(1 for i in items if not i.get("mult"))
    ind = [i for i in items if i["kind"] == "industry"]
    n_roe = 0
    for i in ind:
        sc = i.get("score")
        if sc is not None and sc < 40:
            v = i.get("roe_chg")
            if not (v is not None and v > roe_th):
                n_roe += 1

    inc = orders.get("cumulative_invested_cny", 0)
    realized = orders.get("realized_pnl_cny", 0)
    unreal = orders.get("unrealized_pnl_cny", 0)
    total_pnl = orders.get("total_return_cny", 0)
    assets = inc + total_pnl
    ret = (total_pnl / inc * 100) if inc else 0.0

    # ---- 买入清单 ----
    if buys:
        rows = []
        for b in buys:
            rows.append(
                "<tr>"
                + td(b["name"], "left", bold=True)
                + td(cat_of(b["kind"], b.get("market")), "center", "#6b7280", size="12px")
                + td('<span style="color:%s;font-weight:600;">%.1f</span>' % (pct_color(b["score"]), b["score"]))
                + td("%.1fx" % b["mult"], "center")
                + td("¥%.0f" % b["amount_cny"], "right", bold=True)
                + td('<span style="color:#4b5563;">%s</span><br><span style="color:#9ca3af;font-size:11px;">%s</span>'
                     % (b["fund"], b["fund_name"]), "left", size="12px")
                + "</tr>")
        buy_table = (
            '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
            "<tr>" + th("标的", "left") + th("类别", "center") + th("分位", "right")
            + th("倍数", "center") + th("金额", "right") + th("场外基金", "left") + "</tr>"
            + "".join(rows) + "</table>")
    else:
        buy_table = ('<div style="padding:14px;color:#6b7280;font-size:13px;">'
                     '本期无买入（全部标的落在停投区间）</div>')

    # ---- 卖出 ----
    if sells:
        srows = []
        for s in sells:
            srows.append("<tr>" + td(s.get("name", ""), "left", bold=True)
                         + td("%.1f" % s.get("score", 0))
                         + td(s.get("label", s.get("stage", "")), "center", C_SELL)
                         + td("¥%.0f" % s.get("amount_cny", 0), "right", bold=True) + "</tr>")
        sell_block = ('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
                      "<tr>" + th("标的", "left") + th("分位") + th("动作", "center") + th("金额") + "</tr>"
                      + "".join(srows) + "</table>")
    else:
        sell_block = '<div style="padding:10px 0;color:#6b7280;font-size:13px;">无</div>'

    # ---- 分位速览：最低 12 / 最高 8 ----
    ranked = sorted([i for i in items if i.get("score") is not None], key=lambda x: x["score"])

    def rank_table(rs, title):
        rows = []
        for i in rs:
            fund = i.get("fund") or ""
            rows.append("<tr>"
                        + td(i["name"], "left", bold=True)
                        + td(cat_of(i["kind"], i.get("market")), "center", "#6b7280", size="11px")
                        + td('<span style="color:%s;font-weight:600;">%.1f</span>' % (pct_color(i["score"]), i["score"]))
                        + td(i.get("zone", "—"), "center", pct_color(i["score"]), size="12px")
                        + td("%.1fx" % (i.get("mult") or 0), "center")
                        + td('<span style="color:#6b7280;font-size:11px;">%s</span>' % (fund or "无"), "left", size="12px")
                        + "</tr>")
        return ('<div style="font-size:12.5px;font-weight:600;color:#374151;margin:18px 0 8px;">'
                + title + '</div>'
                '<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
                "<tr>" + th("标的", "left") + th("类别", "center") + th("分位") + th("档位", "center")
                + th("倍数", "center") + th("基金", "left") + "</tr>" + "".join(rows) + "</table>")

    low_tbl = rank_table(ranked[:12], "最便宜 12 个")
    high_tbl = rank_table(list(reversed(ranked[-8:])), "最贵 8 个")

    corp = "1920442561@qq.com"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = """<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f5f6f8;">
<table width="100%%" cellpadding="0" cellspacing="0" style="background:#f5f6f8;padding:24px 12px;">
<tr><td align="center">
<table width="680" cellpadding="0" cellspacing="0" style="max-width:680px;background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;">

<tr><td style="padding:24px 26px 18px;border-bottom:1px solid #f1f2f4;">
  <div style="font-size:20px;font-weight:650;color:#111827;letter-spacing:-.3px;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;">
    指数估值定投 · 日更</div>
  <div style="margin-top:8px;font-size:12px;color:#6b7280;line-height:1.7;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;">
    估值基准日 <b style="color:#111827;">%s</b> &nbsp;·&nbsp; 信号 as_of <b style="color:#111827;">%s</b> &nbsp;·&nbsp; 生成 %s<br>
    参数 index_params v1.0 &nbsp;·&nbsp; 1X = %s 元 &nbsp;·&nbsp; 每日定投
  </div>
</td></tr>

<tr><td style="padding:20px 26px 4px;">
  <table width="100%%" cellpadding="0" cellspacing="0" style="border-collapse:separate;border-spacing:8px 0;">
    <tr>
      %s
      %s
      %s
      %s
    </tr>
  </table>
</td></tr>

<tr><td style="padding:22px 26px 4px;">
  <div style="font-size:14px;font-weight:650;color:#111827;margin-bottom:10px;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;">
    本期买入清单 <span style="font-size:11px;font-weight:400;color:#9ca3af;">%d 笔 · 合计 ¥%.0f</span></div>
  %s
</td></tr>

<tr><td style="padding:20px 26px 4px;">
  <div style="font-size:14px;font-weight:650;color:#111827;margin-bottom:8px;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;">
    卖出清单 <span style="font-size:11px;font-weight:400;color:#9ca3af;">合计 ¥%.0f</span></div>
  %s
</td></tr>

<tr><td style="padding:20px 26px 4px;">
  <div style="font-size:14px;font-weight:650;color:#111827;margin-bottom:10px;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;">
    账本</div>
  <table width="100%%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1px solid #e5e7eb;border-radius:8px;">
    <tr>
      %s
      %s
      %s
    </tr>
    <tr>
      %s
      %s
      %s
    </tr>
  </table>
</td></tr>

<tr><td style="padding:20px 26px 4px;">
  <div style="padding:12px 14px;background:#fafbfc;border:1px solid #eef0f3;border-radius:8px;font-size:12px;color:#4b5563;line-height:1.8;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;">
    全市场 <b>%d</b> 个标的参与分位计算（国内宽基 %d / 国外宽基 %d / 行业 %d）；停投 <b>%d</b> 个；
    行业端另有 <b style="color:#b91c1c;">%d</b> 个因隐含 ROE 同比未达 %.0f%% 被挡掉。
  </div>
</td></tr>

<tr><td style="padding:16px 26px 4px;">
  %s
  %s
</td></tr>

<tr><td style="padding:22px 26px 26px;">
  <div style="padding:14px 16px;background:#fffbeb;border:1px solid #fde68a;border-radius:8px;font-size:12.5px;color:#78350f;line-height:1.8;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;">
    <b>本期计划已自动登记到账本，你只需在下一交易日 15:00 前按清单完成场外申购。</b>
  </div>
  <div style="margin-top:14px;font-size:11px;color:#9ca3af;line-height:1.8;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;">
    完整 %d 个标的分位明细见附件 index_valuation_%s.html（可筛选排序）。<br>
    分档：0-10 深度低估 2.0x / 10-25 低估 1.5x / 25-40 偏低 1.0x / 40-75 停投 / ≥75 分档减速卖出。<br>
    日经225、越南、印度、中韩半导体因全市场无 PE/PB 估值源，已自 2026-10-29 起停用，不再参与定投。
  </div>
</td></tr>

</table>
</td></tr></table>
</body></html>
""" % (
        data_date, as_of, now, params.get("execute", {}).get("unit_amount_cny", 10),
        stat_cell("本期买入", "%d" % len(buys), C_UNDER, " 笔"),
        stat_cell("本期金额", "%.0f" % total_buy, "#111827", " 元"),
        stat_cell("卖出", "%.0f" % total_sell, "#6b7280", " 元"),
        stat_cell("停投标的", "%d" % n_stop, "#6b7280", " 个"),
        len(buys), total_buy, buy_table,
        total_sell, sell_block,
        stat_cell("累计投入", "%.0f" % inc, "#111827", " 元"),
        stat_cell("已实现盈亏", "%+.0f" % realized, C_UNDER if realized >= 0 else C_SELL, " 元"),
        stat_cell("未实现盈亏", "%+.0f" % unreal, C_UNDER if unreal >= 0 else C_SELL, " 元"),
        stat_cell("总资产", "%.0f" % assets, "#111827", " 元"),
        stat_cell("总收益", "%+.0f" % total_pnl, C_UNDER if total_pnl >= 0 else C_SELL, " 元"),
        stat_cell("收益率", "%+.2f%%" % ret, C_UNDER if ret >= 0 else C_SELL, ""),
        len(items),
        sum(1 for i in items if cat_of(i["kind"], i.get("market")) == "国内宽基"),
        sum(1 for i in items if cat_of(i["kind"], i.get("market")) == "国外宽基"),
        len(ind),
        n_stop, n_roe, roe_th * 100,
        low_tbl, high_tbl,
        len(items), as_of,
    )
    return html


def build_notice(orders, sig, params, as_of, data_date, attach_name, attach_kb=0.0):
    """默认正文：极简纯静态提示。不含任何按钮/输入框/script/大表。

    设计原则：邮件正文只负责「告诉你去看哪个文件」，所有可交互的东西都在附件里。
    正文出现按钮 = 用户点了没反应 = 比没有还糟。
    """
    items = sig["items"]
    buys = orders.get("buys", [])
    sells = orders.get("sells", [])
    total_buy = orders.get("total_buy_cny", 0)
    total_sell = orders.get("total_sell_cny", 0)

    rf = params.get("execute", {}).get("industry_roe_filter", {})
    roe_th = rf.get("roe_th", 0.15)
    roe_on = rf.get("enabled", False)

    n_stop = sum(1 for i in items if not i.get("mult"))
    n_roe = 0
    for i in items:
        if i["kind"] != "industry":
            continue
        sc = i.get("score")
        if sc is not None and sc < 40:
            v = i.get("roe_chg")
            if not (v is not None and v > roe_th):
                n_roe += 1
    n_cn = sum(1 for i in items if cat_of(i["kind"], i.get("market")) == "国内宽基")
    n_os = sum(1 for i in items if cat_of(i["kind"], i.get("market")) == "国外宽基")
    n_ind = len(items) - n_cn - n_os

    inc = orders.get("cumulative_invested_cny", 0)
    realized = orders.get("realized_pnl_cny", 0)
    unreal = orders.get("unrealized_pnl_cny", 0)
    total_pnl = orders.get("total_return_cny", 0)
    assets = inc + total_pnl
    ret = (total_pnl / inc * 100) if inc else 0.0

    F = "font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;"
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    unit = params.get("execute", {}).get("unit_amount_cny", 10)

    def cell(label, value, color="#111827", sub=""):
        return ('<td width="25%%" align="center" style="padding:13px 4px;border:1px solid #e5e7eb;'
                'border-radius:8px;%s">'
                '<div style="font-size:11px;color:#6b7280;margin-bottom:4px;">%s</div>'
                '<div style="font-size:19px;font-weight:650;color:%s;letter-spacing:-.5px;">%s'
                '<span style="font-size:11px;font-weight:400;color:#9ca3af;">%s</span></div></td>'
                % (F, label, color, value, sub))

    sell_line = ("本期卖出 <b>%d</b> 笔 · 合计 <b>¥%.0f</b>" % (len(sells), total_sell)
                 if sells else "本期无卖出")
    roe_line = ("行业端 <b>%d</b> 个因隐含 ROE 同比未达 %.0f%% 被挡掉" % (n_roe, roe_th * 100)
                if roe_on else "ROE 过滤已关闭")

    size_txt = ("（%.0f KB）" % attach_kb) if attach_kb else ""
    if attach_name and attach_kb:
        attach_head = "完整看板在附件里 → %s %s" % (attach_name, size_txt)
        attach_tip = ("<b>下载后用浏览器打开</b>：档位折叠 + 锚点跳转、"
                      "搜索框、点表头排序，全部可用。<br>"
                      "直接在邮件里预览或内嵌阅读不会执行脚本，按钮是灰的——所以正文不再放看板。")
    else:
        attach_head = "本次只发了摘要，没带看板文件"
        attach_tip = ("完整看板请本地打开 reports/index_valuation_<as_of>.html，"
                      "或下次带 --attach 重发。")
    return """<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f5f6f8;">
<table width="100%%" cellpadding="0" cellspacing="0" style="background:#f5f6f8;padding:24px 12px;">
<tr><td align="center">
<table width="640" cellpadding="0" cellspacing="0" style="max-width:640px;background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;">

<tr><td style="padding:24px 26px 16px;border-bottom:1px solid #f1f2f4;">
  <div style="font-size:20px;font-weight:650;color:#111827;letter-spacing:-.3px;%(F)s">指数估值定投 · 日更</div>
  <div style="margin-top:8px;font-size:12px;color:#6b7280;line-height:1.7;%(F)s">
    估值基准日 <b style="color:#111827;">%(data_date)s</b> &nbsp;·&nbsp;
    信号 as_of <b style="color:#111827;">%(as_of)s</b> &nbsp;·&nbsp; 生成 %(now)s<br>
    参数 index_params v1.0 &nbsp;·&nbsp; 1X = %(unit)s 元 &nbsp;·&nbsp; 每日定投
  </div>
</td></tr>

<tr><td style="padding:20px 26px 4px;">
  <table width="100%%" cellpadding="0" cellspacing="0" style="border-collapse:separate;border-spacing:8px 0;">
    <tr>
      %(c1)s
      %(c2)s
      %(c3)s
      %(c4)s
    </tr>
  </table>
</td></tr>

<tr><td style="padding:20px 26px 4px;">
  <table width="100%%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin-top:6px;">
    <tr>
      <td width="33%%" align="center" style="padding:11px 4px;background:#fafbfc;border:1px solid #eef0f3;border-radius:8px;%(F)s">
        <div style="font-size:11px;color:#6b7280;margin-bottom:4px;">累计投入</div>
        <div style="font-size:15px;font-weight:600;color:#111827;">¥%(inc)s</div></td>
      <td width="4%%"></td>
      <td width="33%%" align="center" style="padding:11px 4px;background:#fafbfc;border:1px solid #eef0f3;border-radius:8px;%(F)s">
        <div style="font-size:11px;color:#6b7280;margin-bottom:4px;">盈亏（已实现 + 未实现）</div>
        <div style="font-size:15px;font-weight:600;color:%(pc)s;">%(pnl)s</div></td>
      <td width="4%%"></td>
      <td width="33%%" align="center" style="padding:11px 4px;background:#fafbfc;border:1px solid #eef0f3;border-radius:8px;%(F)s">
        <div style="font-size:11px;color:#6b7280;margin-bottom:4px;">总资产 · 收益率</div>
        <div style="font-size:15px;font-weight:600;color:#111827;">¥%(assets)s <span style="color:%(pc)s;font-size:13px;">%(ret)s</span></div></td>
    </tr>
  </table>
</td></tr>

<tr><td style="padding:22px 26px 4px;">
  <table width="100%%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;border:1px solid #d1fae5;background:#f0fdfa;border-radius:10px;">
    <tr><td style="padding:16px 18px;">
      <div style="font-size:13.5px;font-weight:650;color:#065f46;margin-bottom:8px;%(F)s">
        %(attach_head)s
      </div>
      <div style="font-size:12.5px;color:#0f766e;line-height:1.85;%(F)s">
        %(attach_tip)s
      </div>
    </td></tr>
  </table>
</td></tr>

<tr><td style="padding:18px 26px 4px;">
  <div style="padding:12px 14px;background:#fafbfc;border:1px solid #eef0f3;border-radius:8px;font-size:12px;color:#4b5563;line-height:1.8;%(F)s">
    全市场 <b>%(n_all)d</b> 个标的参与分位（国内宽基 %(n_cn)d / 国外宽基 %(n_os)d / 行业 %(n_ind)d）；停投 <b>%(n_stop)d</b> 个；%(roe_line)s。<br>
    %(sell_line)s
  </div>
</td></tr>

<tr><td style="padding:18px 26px 24px;">
  <div style="padding:14px 16px;background:#fffbeb;border:1px solid #fde68a;border-radius:8px;font-size:12.5px;color:#78350f;line-height:1.8;%(F)s">
    <b>本期计划已自动登记到账本，你只需在下一交易日 15:00 前按附件清单完成场外申购。</b>
  </div>
  <div style="margin-top:12px;font-size:11px;color:#9ca3af;line-height:1.8;%(F)s">
    分档：0-10 深度低估 2.0x / 10-25 低估 1.5x / 25-40 偏低 1.0x / 40-75 停投 / ≥75 分档减速卖出。<br>
    日经225、越南、印度、中韩半导体因全市场无 PE/PB 估值源，已自 2026-10-29 起停用。
  </div>
</td></tr>

</table>
</td></tr></table>
</body></html>
""" % {
        "F": F,
        "data_date": data_date, "as_of": as_of, "now": now, "unit": unit,
        "c1": cell("本期买入", "%d" % len(buys), C_UNDER, " 笔"),
        "c2": cell("本期金额", "%.0f" % total_buy, "#111827", " 元"),
        "c3": cell("卖出", "%.0f" % total_sell, C_NORM, " 元"),
        "c4": cell("停投标的", "%d" % n_stop, C_NORM, " 个"),
        "inc": format(inc, ",.0f"),
        "pnl": format(realized + unreal, "+,.0f"),
        "assets": format(assets, ",.0f"),
        "ret": format(ret, "+.2f") + "%",
        "pc": C_UNDER if (realized + unreal) >= 0 else C_SELL,
        "attach_name": attach_name, "size_txt": size_txt,
        "attach_head": attach_head, "attach_tip": attach_tip,
        "n_all": len(items), "n_cn": n_cn, "n_os": n_os, "n_ind": n_ind,
        "n_stop": n_stop, "roe_line": roe_line, "sell_line": sell_line,
    }



    srv = cfg["mcpServers"]["agent-mail"]
    c = McpClient(srv["url"], srv.get("headers", {}))
    c.initialize()
    args = {
        "to": [{"email": x} for x in to_list],
        "subject": subject,
        "body": html_body,
        "body_format": "HTML",
        "skip_confirmation": skip_confirmation,
    }
    if attachments:
        args["attachments"] = attachments
    res = c.request("tools/call", {"name": "SendMessage", "arguments": args})
    if isinstance(res, dict) and res.get("isError"):
        text = "".join(x.get("text", "") for x in res.get("content", []) if x.get("type") == "text")
        return False, text[:600]
    result = res.get("result", res)
    text = "".join(x.get("text", "") for x in result.get("content", []) if x.get("type") == "text")
    return True, text[:600]


def send_mail(cfg, to_list, subject, html_body, attachments=None, skip_confirmation=True):
    srv = cfg["mcpServers"]["agent-mail"]
    c = McpClient(srv["url"], srv.get("headers", {}))
    c.initialize()
    args = {
        "to": [{"email": x} for x in to_list],
        "subject": subject,
        "body": html_body,
        "body_format": "HTML",
        "skip_confirmation": skip_confirmation,
    }
    if attachments:
        args["attachments"] = attachments
    res = c.request("tools/call", {"name": "SendMessage", "arguments": args})
    if isinstance(res, dict) and res.get("isError"):
        text = "".join(x.get("text", "") for x in res.get("content", []) if x.get("type") == "text")
        return False, text[:600]
    result = res.get("result", res)
    text = "".join(x.get("text", "") for x in result.get("content", []) if x.get("type") == "text")
    return True, text[:600]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", default=DEFAULT_TO)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--notice", action="store_true",
                    help="极简纯文字正文（~6KB），看板需配合 --attach")
    ap.add_argument("--summary", action="store_true",
                    help="680px 摘要邮件（买入/卖出/账本全在正文，无分位明细）")
    ap.add_argument("--attach", action="store_true",
                    help="额外附带看板 HTML（默认正文已含完整看板，一般不需要）")
    ap.add_argument("--html", default=None, help="看板 HTML 路径，缺省按 as_of 推断")
    a = ap.parse_args()

    orders = json.load(open(os.path.join(ROOT, "state", "index_orders.json"), encoding="utf-8"))
    sig = json.load(open(os.path.join(ROOT, "state", "index_signal.json"), encoding="utf-8"))
    params = json.load(open(os.path.join(ROOT, "knowledge", "index_params.json"), encoding="utf-8"))

    as_of = sig["as_of"]
    data_date = next((i.get("date") for i in sig["items"] if i.get("date")), as_of)
    board = a.html or os.path.join(ROOT, "reports", "index_valuation_%s.html" % as_of)

    subj_buy = "买入%d笔 ¥%.0f" % (len(orders.get("buys", [])), orders.get("total_buy_cny", 0))
    subject = "指数定投日更 %s · %s" % (as_of, subj_buy)
    attach_name = os.path.basename(board)
    attach_kb = 0.0

    if a.summary:
        body = build_body(orders, sig, params, as_of, data_date)
        print("body: 680px 摘要版 %.1fKB" % (len(body.encode()) / 1024.0))
    elif a.notice:
        if os.path.exists(board):
            attach_kb = os.path.getsize(board) / 1024.0
        body = build_notice(orders, sig, params, as_of, data_date, attach_name, attach_kb)
        print("body: 极简提示 %.1fKB（看板请配合 --attach）" % (len(body.encode()) / 1024.0))
    else:
        if not os.path.exists(board):
            print("FAILED 看板不存在，先跑 make_index_valuation_report.py：", board)
            return 1
        body = open(board, encoding="utf-8").read()
        # 看板已改为纯 HTML 原生交互（<details> 折叠 + 锚点跳转），本身不含 script。
        # 这里保留一次防御性剥离：万一以后有人往模板里塞回 JS，别把死按钮发出去。
        if re.search(r"<script\b", body, flags=re.I):
            print("WARN 看板里检测到 <script>，已剥离（邮件环境不执行，网关也会拦）")
            body = re.sub(r"<script\b.*?</script>", "", body, flags=re.S | re.I)
        print("body: 看板全文（邮件原生交互）%.1fKB <- %s"
              % (len(body.encode()) / 1024.0, attach_name))

    attachments = []
    if a.attach:
        if not os.path.exists(board):
            print("FAILED 看板不存在，附件无法生成：", board)
            return 1
        raw = open(board, "rb").read()
        attachments.append({
            "filename": attach_name,
            "content_type": "text/html",
            "content": base64.b64encode(raw).decode("ascii"),
            "size": len(raw),
            "sha1": hashlib.sha1(raw).hexdigest(),
        })
        print("attach:", attach_name, "%.1fKB" % (len(raw) / 1024.0))

    if a.dry_run:
        out = os.path.join(ROOT, "reports", "_mail_preview_%s.html" % as_of)
        open(out, "w", encoding="utf-8").write(body)
        print("DRY-RUN 预览:", out)
        print("subject:", subject)
        print("to:", a.to)
        print("attachments:", [x["filename"] for x in attachments])
        return 0

    to_list = [x.strip() for x in a.to.split(",") if x.strip()]
    cfg = json.loads(os.environ["CODEBUDDY_MCP_CONFIG"])
    ok, msg = send_mail(cfg, to_list, subject, body, attachments)
    print("SENT" if ok else "FAILED", "->", ",".join(to_list), "|", msg.replace("\n", " ")[:400])
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
