"""make_index_valuation_report.py - 指数/行业估值分位全量看板（自包含单文件 HTML）

数据源：state/index_signal.json（分位与分档）、state/index_orders.json（本期计划）
输出：reports/index_valuation_<as_of>.html
用途：**直接作为邮件正文发送**（send_index_daily_mail.py 默认行为），也可本地浏览器打开。

## 三条硬约束（2026-10-29 重写）

1. **零 JS**。邮件网关 WAF 把 <script> 当 XSS 拦（实测 501），客户端也一律剥掉。
   所以表格行必须服务端静态渲染，筛选/搜索/排序这类 JS 交互一律不做。
2. **零 <style> 依赖**。全部样式内联，不写 <style> 块。邮件客户端若剥掉 <style>，
   页面仍然完整可读（只是丢掉折叠三角形之类的细节）。
3. **交互只用 HTML 原生能力**：
   - `<details>/<summary>` 折叠：浏览器原生行为，不依赖 CSS / JS。
   - `<a href="#id">` 锚点跳转：永远有效，最坏情况也只是"跳过去"而不是"点了没反应"。
   任何看起来能点、点了没反应的元素（button / input / 带 hover 的假按钮）禁止出现。

## 为什么不做筛选按钮

旧版有「全部/宽基/行业/本期买入/ROE挡掉/停投」7 个按钮 + 搜索框 + 表头排序，全由一段
<script> 驱动。发到邮箱 script 被剥，按钮变死按钮。现在改为：
  - 「筛选」→ 按档位分组成可折叠区块（深度低估 / 低估 / 偏低 / 正常 / 偏高 / 高估 / 极高估）
  - 「本期买入 / ROE挡掉 / 无场外基金」→ 行内彩色标记，不再需要单独筛选
  - 「宽基 vs 行业」→ 宽基单独一张 9 行小表，行业按档位分组
  - 搜索 / 排序 → 邮件环境做不了，取消；表格已按分位升序预排好

## 口径（与 scripts/index_plan.py 一致）

  - 行业隐含ROE同比 > execute.industry_roe_filter.roe_th 才买，None 视为不合格
  - 只买场外（.OF）或 LOF，场内 ETF 不下单
"""
import html as htmlmod
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIGNAL = os.path.join(ROOT, "state", "index_signal.json")
ORDERS = os.path.join(ROOT, "state", "index_orders.json")
PARAMS = os.path.join(ROOT, "knowledge", "index_params.json")
OUTDIR = os.path.join(ROOT, "reports")

ZONE_STYLE = {
    "深度低估": ("#047857", "#d1fae5"),
    "低估": ("#15803d", "#dcfce7"),
    "偏低": ("#4d7c0f", "#ecfccb"),
    "价格低位": ("#047857", "#d1fae5"),
    "价格偏低": ("#4d7c0f", "#ecfccb"),
    "正常": ("#6b7280", "#f3f4f6"),
    "偏高": ("#b45309", "#fef3c7"),
    "价格中性/偏高": ("#78716c", "#f5f5f4"),
    "高估": ("#dc2626", "#fee2e2"),
    "极高估": ("#991b1b", "#fecaca"),
    "—": ("#9ca3af", "#f3f4f6"),
}
ZONE_ORDER = ["深度低估", "低估", "偏低", "价格低位", "价格偏低", "正常",
              "价格中性/偏高", "偏高", "高估", "极高估", "—"]
# 默认展开的档位：这三档是可下手的区间，其余折叠
ZONE_OPEN = {"深度低估", "低估", "偏低", "价格低位", "价格偏低"}

FONT = ("-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',"
        "'Microsoft YaHei',sans-serif")

S_TABLE = "width:100%;border-collapse:collapse;"
S_TH = ('padding:9px 10px;border-bottom:1px solid #e5e7eb;background:#fafafa;text-align:left;'
        'font-weight:600;color:#6b7280;font-size:11.5px;white-space:nowrap;')
S_TH_R = S_TH + "text-align:right;"
S_TH_C = S_TH + "text-align:center;"
S_TD = "padding:8px 10px;border-bottom:1px solid #f1f2f4;font-size:12.5px;vertical-align:middle;"
S_TD_R = S_TD + "text-align:right;font-variant-numeric:tabular-nums;"
S_TD_C = S_TD + "text-align:center;"


def pct_color(p):
    if p is None:
        return "#9ca3af"
    if p < 10:
        return "#047857"
    if p < 25:
        return "#15803d"
    if p < 40:
        return "#4d7c0f"
    if p < 60:
        return "#9ca3af"
    if p < 75:
        return "#d97706"
    if p < 90:
        return "#dc2626"
    return "#991b1b"


def is_of(it):
    f = it.get("fund") or ""
    return f.endswith(".OF") or f.endswith(".SZ") or f.endswith(".SH")


# 展示分类：国内宽基 / 国外宽基 / 行业
# 注意：这只是**展示口径**，不参与策略。策略里仍然只有 kind（broad / industry）两分法，
# index_plan.py 的买入判定（宽基分位<40 就买、行业需过 ROE 且<40）完全不受影响。
CAT_CN_BROAD = "国内宽基"
CAT_OS_BROAD = "国外宽基"
CAT_INDUSTRY = "行业"
CAT_ORDER = [CAT_CN_BROAD, CAT_OS_BROAD, CAT_INDUSTRY]
CAT_STYLE = {
    CAT_CN_BROAD: ("#1d4ed8", "#e0e7ff"),
    CAT_OS_BROAD: ("#7c3aed", "#ede9fe"),
    CAT_INDUSTRY: ("#5b21b6", "#f3f0ff"),
}


def cat_of(kind, market):
    if kind == "industry":
        return CAT_INDUSTRY
    return CAT_CN_BROAD if (market or "CN").startswith("CN") else CAT_OS_BROAD


def fmt(v, d=2):
    if v is None or v == "":
        return '<span style="color:#9ca3af;">\u2014</span>'
    try:
        return ("%." + str(d) + "f") % float(v)
    except (TypeError, ValueError):
        return '<span style="color:#9ca3af;">\u2014</span>'


def bar_html(p):
    if p is None:
        return '<span style="color:#9ca3af;">\u2014</span>'
    c = pct_color(p)
    return ('<span style="display:inline-block;width:58px;height:5px;background:#eef0f3;'
            'border-radius:3px;overflow:hidden;vertical-align:middle;">'
            '<span style="display:inline-block;width:%d%%;height:5px;background:%s;"></span></span>'
            '<span style="display:inline-block;margin-left:7px;font-size:12px;font-weight:600;'
            'color:%s;vertical-align:middle;">%.1f</span>') % (max(2, int(round(p))), c, c, p)


def zone_html(z):
    fg, bg = ZONE_STYLE.get(z, ("#6b7280", "#f3f4f6"))
    return ('<span style="display:inline-block;font-size:11px;padding:2px 8px;border-radius:20px;'
            'white-space:nowrap;font-weight:500;color:%s;background:%s;">%s</span>'
            % (fg, bg, htmlmod.escape(z)))


TAG_STYLE = {
    "ROE过滤": ("#fee2e2", "#b91c1c"),
    "无场外基金": ("#fef3c7", "#92400e"),
    "价格分位": ("#e0e7ff", "#3730a3"),
    "主板PER代理": ("#fef3c7", "#92400e"),
    "主动基金代理": ("#ede9fe", "#6d28d9"),
    "本期买入": ("#d1fae5", "#065f46"),
}


def tag_html(t):
    bg, fg = TAG_STYLE.get(t, ("#f3f4f6", "#374151"))
    return ('<span style="display:inline-block;font-size:10px;padding:1px 5px;border-radius:3px;'
            'margin:1px 2px 1px 0;white-space:nowrap;background:%s;color:%s;">%s</span>'
            % (bg, fg, t))


def render_row(r, idx, cols):
    """按 cols 指定的列顺序渲染一行。cols 里每个值对应下面 _cell 的分支。"""
    def _cell(k):
        if k == "idx":
            return '<td style="%s"><span style="color:#9ca3af;">%d</span></td>' % (S_TD, idx + 1)
        if k == "name":
            return ('<td style="%s"><b style="font-weight:600;color:#111827;">%s</b><br>'
                    '<span style="color:#9ca3af;font-size:10.5px;">%s</span></td>'
                    % (S_TD, htmlmod.escape(r["name"]), r["code"]))
        if k == "kind":
            kb_bg = "#f3f0ff" if r["kind"] == "industry" else "#eef2f7"
            kb_fg = "#5b21b6" if r["kind"] == "industry" else "#475569"
            return ('<td style="%s"><span style="display:inline-block;font-size:10.5px;'
                    'padding:1px 6px;border-radius:4px;background:%s;color:%s;">%s</span></td>'
                    % (S_TD_C, kb_bg, kb_fg, "行业" if r["kind"] == "industry" else "宽基"))
        if k == "score":
            return "<td style=\"%s\">%s</td>" % (S_TD, bar_html(r["score"]))
        if k == "zone":
            return "<td style=\"%s\">%s</td>" % (S_TD, zone_html(r["zone"]))
        if k == "mult":
            if r["mult"] > 0:
                v = ('<span style="font-weight:650;font-variant-numeric:tabular-nums;">%.1fx</span>'
                     ' <span style="color:#4b5563;font-variant-numeric:tabular-nums;">¥%.0f</span>'
                     % (r["mult"], r["amount"]))
            else:
                v = '<span style="color:#9ca3af;font-variant-numeric:tabular-nums;">0.0x</span>'
            return "<td style=\"%s\">%s</td>" % (S_TD_R, v)
        if k == "pe":
            return '<td style="%s">%s</td>' % (S_TD_R, fmt(r["pe"]))
        if k == "pb":
            return '<td style="%s">%s</td>' % (S_TD_R, fmt(r["pb"]))
        if k == "detail":
            if r["isPrice"]:
                v = '<span style="color:#3730a3;font-size:11.5px;">价格分位 %.1f</span>' % (r["score"] or 0)
            else:
                parts = ['PE %s' % fmt(r["pePct"], 1), 'PB %s' % fmt(r["pbPct"], 1)]
                if r["psPct"] is not None:
                    parts.append('PS %s' % fmt(r["psPct"], 1))
                if r.get("divPct") is not None:
                    parts.append('股息 %s' % fmt(r["divPct"], 1))
                v = ('<span style="color:#4b5563;font-size:11.5px;">'
                     + '<span style="color:#d1d5db;margin:0 3px;">\u00b7</span>'.join(parts) + '</span>')
            return "<td style=\"%s\">%s</td>" % (S_TD, v)
        if k == "roe":
            if r["roe"] is None:
                v = '<span style="color:#9ca3af;">\u2014</span>'
            else:
                v = ('<span style="color:%s;">%.1f%%</span>'
                     % ("#15803d" if r["roe"] > 0.15 else "#b91c1c", r["roe"] * 100))
            return "<td style=\"%s\">%s</td>" % (S_TD_R, v)
        if k == "fund":
            if r["fund"]:
                v = ('<span style="color:#4b5563;">%s</span><br>'
                     '<span style="color:#9ca3af;font-size:11px;line-height:1.35;">%s</span>'
                     % (r["fund"], htmlmod.escape(r["fundName"])))
            else:
                v = '<span style="color:#9ca3af;">无</span>'
            return "<td style=\"%s\">%s</td>" % (S_TD, v)
        if k == "model":
            if not r.get("model"):
                return '<td style="%s"><span style="color:#9ca3af;">\u2014</span></td>' % S_TD
            return ('<td style="%s"><span style="display:inline-block;font-size:10px;padding:1px 5px;'
                    'border-radius:3px;background:#eef2ff;color:#3730a3;white-space:nowrap;">%s</span></td>'
                    % (S_TD_C, r["model"]))
        if k == "tags":
            return "<td style=\"%s\">%s</td>" % (S_TD, "".join(tag_html(t) for t in r["tags"]))
        raise ValueError("unknown col " + k)

    tr_bg = "background:#f0fdfa;" if r["buy"] else ""
    return "<tr%s>%s</tr>" % (tr_bg, "".join(_cell(k) for k in cols))


COL_HEAD = {
    "idx": ("#", S_TH),
    "name": ("标的", S_TH),
    "kind": ("类别", S_TH_C),
    "model": ("估值模型", S_TH_C),
    "score": ("综合分位", S_TH),
    "zone": ("档位", S_TH),
    "mult": ("倍数 / 金额", S_TH_R),
    "pe": ("PE", S_TH_R),
    "pb": ("PB", S_TH_R),
    "detail": ("分位明细", S_TH),
    "roe": ("ROE同比", S_TH_R),
    "fund": ("场外基金", S_TH),
    "tags": ("标记", S_TH),
}


def build_table(rows, cols, idx_base=0):
    head = "".join("<th style=\"%s\">%s</th>" % (COL_HEAD[c][1], COL_HEAD[c][0]) for c in cols)
    body = "\n".join(render_row(r, i + idx_base, cols) for i, r in enumerate(rows))
    return ('<table style="%s"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>'
            % (S_TABLE, head, body))


def main():
    sig = json.load(open(SIGNAL, encoding="utf-8"))
    orders = json.load(open(ORDERS, encoding="utf-8"))
    params = json.load(open(PARAMS, encoding="utf-8"))
    # 1X 金额唯一真源在 knowledge/index_params.json，任何地方不许再写死数字
    unit = params.get("execute", {}).get("unit_amount_cny", 10)
    rf = params.get("execute", {}).get("industry_roe_filter", {})
    roe_on = rf.get("enabled", False)
    roe_th = rf.get("roe_th", 0.15)

    as_of = sig["as_of"]
    items = sig["items"]
    buy_names = {(b["code"], b["kind"]) for b in orders.get("buys", [])}

    rows = []
    for it in items:
        kind = it["kind"]
        score = it.get("score")
        is_price = (it.get("metric") or "") == "价格分位"
        roe = it.get("roe_chg")
        tags = []
        if is_price:
            tags.append("价格分位")
        elif (it.get("metric") or "").strip():
            # 非价格分位的自定义口径（如日经的「主板PER代理」）必须显式标出来，
            # 不能让人把代理口径的 PE 当成该指数自己的 PE。
            tags.append(it["metric"].strip())
        if it.get("proxy_active_fund"):
            tags.append("主动基金代理")
        roe_blocked = False
        if kind == "industry" and roe_on and score is not None and score < 40:
            if not (roe is not None and roe > roe_th):
                roe_blocked = True
                tags.append("ROE过滤")
        if kind == "industry" and score is not None and score < 40 and not is_of(it):
            tags.append("无场外基金")
        bought = (it["code"], kind) in buy_names
        if bought:
            tags.append("本期买入")
        rows.append({
            "code": it["code"], "name": it["name"], "kind": kind,
            "cat": cat_of(kind, it.get("market")),
            "score": score, "zone": it.get("zone") or "—",
            "mult": it.get("mult") or 0, "amount": round(unit * (it.get("mult") or 0), 2),
            "pe": it.get("pe"), "pb": it.get("pb"),
            "pePct": it.get("pe_pct"), "pbPct": it.get("pb_pct"), "psPct": it.get("ps_pct"),
            "divPct": it.get("div_pct"),
            "roe": roe, "fund": it.get("fund") or "", "fundName": it.get("fund_name") or "",
            "model": it.get("val_model_short") or "", "modelLabel": it.get("val_model_label") or "",
            "date": it.get("date") or "", "isPrice": is_price,
            "roeBlocked": roe_blocked, "buy": bought, "tags": tags,
        })

    rows.sort(key=lambda r: (CAT_ORDER.index(r["cat"]),
                             r["score"] if r["score"] is not None else 999))

    cn_broad_rows = [r for r in rows if r["cat"] == CAT_CN_BROAD]
    os_broad_rows = [r for r in rows if r["cat"] == CAT_OS_BROAD]
    ind_rows = [r for r in rows if r["cat"] == CAT_INDUSTRY]

    n_cn, n_os, n_ind = len(cn_broad_rows), len(os_broad_rows), len(ind_rows)
    n_broad = n_cn + n_os
    n_buy = len(orders.get("buys", []))
    n_stop = sum(1 for r in rows if r["mult"] == 0)
    n_roe = sum(1 for r in rows if r["roeBlocked"])
    n_price = sum(1 for r in rows if r["isPrice"])
    total_amt = orders.get("total_buy_cny", 0)

    # ---- 本期买入卡片（内联样式，邮件可读）----
    cards = []
    for b in orders.get("buys", []):
        fg, bg = CAT_STYLE.get(cat_of(b["kind"], b.get("market")), ("#6b7280", "#f3f4f6"))
        kind_txt = cat_of(b["kind"], b.get("market"))
        cards.append(
            '<td width="50%" style="padding:0 0 10px 0;vertical-align:top;">'
            '<table width="100%" cellpadding="0" cellspacing="0" style="border:1px solid #e5e7eb;'
            'border-left:3px solid #0f766e;border-radius:8px;"><tr><td style="padding:11px 13px;">'
            '<div style="font-size:13.5px;font-weight:600;color:#111827;">' + htmlmod.escape(b["name"]) +
            '<span style="font-size:10.5px;font-weight:400;background:%s;color:%s;'
            'border-radius:4px;padding:1px 6px;margin-left:6px;">%s</span></div>' % (bg, fg, kind_txt) +
            '<div style="margin-top:7px;font-size:12px;color:#6b7280;">'
            '<span style="color:#0f766e;font-weight:600;">分位 ' + ("%.1f" % b["score"]) + '</span>'
            '<span style="margin:0 8px;color:#d1d5db;">|</span><b>' + ("%.1fx" % b["mult"]) + '</b>'
            '<span style="margin:0 8px;color:#d1d5db;">|</span><b>¥' + ("%.0f" % b["amount_cny"]) + '</b></div>'
            '<div style="margin-top:5px;font-size:11px;color:#9ca3af;line-height:1.4;">' +
            b["fund"] + ' · ' + htmlmod.escape(b["fund_name"]) + '</div>'
            '</td></tr></table></td>')

    card_rows = []
    for i in range(0, len(cards), 2):
        pair = cards[i:i + 2]
        if len(pair) == 1:
            pair.append('<td width="50%"></td>')
        card_rows.append("<tr>" + "".join(pair) + "</tr>")
    buy_html = ('<table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
                + "".join(card_rows) + "</table>") if cards else \
        '<div style="color:#9ca3af;padding:8px 0;">本期无买入</div>'

    # ---- 档位统计条 + 锚点导航 ----
    zones = {}
    for r in rows:
        zones[r["zone"]] = zones.get(r["zone"], 0) + 1
    izones = {}
    for r in ind_rows:
        izones[r["zone"]] = izones.get(r["zone"], 0) + 1
    present = [z for z in ZONE_ORDER if zones.get(z)]
    present_ind = [z for z in ZONE_ORDER if izones.get(z)]

    legend = "".join(
        '<span style="display:inline-block;margin:0 12px 6px 0;font-size:11.5px;color:#4b5563;">'
        '<span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:%s;'
        'margin-right:5px;"></span>%s \u00b7 %d</span>' % (ZONE_STYLE[z][0], z, zones[z])
        for z in present)

    def zid(z):
        return "z%d" % ZONE_ORDER.index(z)

    nav_items = ['<a href="#buy" style="display:inline-block;margin:0 6px 6px 0;padding:6px 12px;'
                 'border:1px solid #d1fae5;background:#f0fdfa;border-radius:7px;font-size:12.5px;'
                 'color:#0f766e;text-decoration:none;font-weight:600;">本期买入 %d</a>' % n_buy]
    for cid, cname, crows in (("cn-broad", CAT_CN_BROAD, cn_broad_rows),
                              ("os-broad", CAT_OS_BROAD, os_broad_rows)):
        if not crows:
            continue
        cfg, cbg = CAT_STYLE[cname]
        nav_items.append(
            '<a href="#%s" style="display:inline-block;margin:0 6px 6px 0;padding:6px 12px;'
            'border:1px solid %s;background:%s;border-radius:7px;font-size:12.5px;color:%s;'
            'text-decoration:none;font-weight:600;">%s %d</a>'
            % (cid, cbg, cbg, cfg, cname, len(crows)))
    for z in present_ind:
        fg, bg = ZONE_STYLE[z]
        nav_items.append(
            '<a href="#%s" style="display:inline-block;margin:0 6px 6px 0;padding:6px 12px;'
            'border:1px solid #e5e7eb;border-radius:7px;font-size:12.5px;color:%s;'
            'text-decoration:none;">%s %d</a>' % (zid(z), fg, z, izones[z]))
    nav_html = "".join(nav_items)

    # ---- 国内宽基 / 国外宽基：各一张小表，固定展开 ----
    BROAD_COLS = ["idx", "name", "model", "score", "zone", "mult", "pe", "pb", "detail", "fund", "tags"]

    def cat_section(anchor, cname, crows, hint):
        if not crows:
            return ""
        cfg, cbg = CAT_STYLE[cname]
        return ('<div id="%s" style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;'
                'padding:16px 18px;margin-bottom:16px;">'
                '<div style="font-size:14px;font-weight:650;color:#111827;margin-bottom:4px;">'
                '<span style="display:inline-block;width:9px;height:9px;border-radius:2px;'
                'background:%s;margin-right:8px;"></span>%s %d 个'
                '<span style="font-size:11.5px;font-weight:400;color:#9ca3af;margin-left:8px;">'
                '%s \u00b7 全部列出 \u00b7 按分位升序</span></div>'
                '<div style="padding-top:10px;">%s</div></div>'
                % (anchor, cfg, cname, len(crows), hint, build_table(crows, BROAD_COLS)))

    cn_broad_html = cat_section("cn-broad", CAT_CN_BROAD, cn_broad_rows,
                               "沪深300 / A500 / 中证1000 / 创业板指 / 红利 / 红利低波")
    os_broad_html = cat_section("os-broad", CAT_OS_BROAD, os_broad_rows,
                               "QDII，含汇率与跟踪误差，倍数与国内同口径")

    # ---- 行业按档位折叠 ----
    zone_blocks = []
    for z in present_ind:
        rs = [r for r in ind_rows if r["zone"] == z]
        if not rs:
            continue
        fg, bg = ZONE_STYLE[z]
        sc = [x["score"] for x in rs if x["score"] is not None]
        rng = ("分位 %.1f\u2013%.1f" % (min(sc), max(sc))) if sc else ""
        op = " open" if z in ZONE_OPEN else ""
        zone_blocks.append(
            '<details id="%s"%s style="margin-bottom:10px;border:1px solid #e5e7eb;'
            'border-radius:10px;background:#fff;overflow:hidden;">'
            '<summary style="padding:12px 14px;cursor:pointer;font-size:13.5px;font-weight:650;'
            'color:#111827;list-style:none;background:#fafbfc;border-left:3px solid %s;">'
            '<span style="display:inline-block;width:9px;height:9px;border-radius:2px;'
            'background:%s;margin-right:8px;"></span>%s'
            '<span style="font-weight:400;color:#6b7280;font-size:12px;margin-left:8px;">'
            '%d 个 \u00b7 %s</span>'
            '<span style="float:right;font-weight:400;color:#9ca3af;font-size:11.5px;">'
            '%s</span></summary>'
            '<div style="padding:2px 2px 2px;">%s</div></details>'
            % (zid(z), op, fg, fg, z, len(rs), rng,
               "已展开 \u00b7 点标题收起" if z in ZONE_OPEN else "已收起 \u00b7 点标题展开",
               build_table(rs, ["idx", "name", "model", "score", "mult", "pe", "pb", "detail",
                                "roe", "fund", "tags"])))

    ind_html = ('<div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;'
                'padding:16px 18px;margin-bottom:16px;">'
                '<div style="font-size:14px;font-weight:650;color:#111827;margin-bottom:4px;">'
                '行业 %d 个 \u00b7 按档位分组'
                '<span style="font-size:11.5px;font-weight:400;color:#9ca3af;margin-left:8px;">'
                '点标题展开 / 收起 \u00b7 组内按分位升序 \u00b7 绿色行 = 本期买入</span></div>'
                '<div style="font-size:11.5px;color:#9ca3af;margin-bottom:12px;">'
                '邮件里不支持搜索和多列排序，所以不再提供按钮；档位就是最实用的筛选维度。</div>'
                '%s</div>' % (n_ind, "".join(zone_blocks)))

    # ---- 统计卡 / 账本 ----
    def stat(label, val, color, sub):
        return ('<td width="25%" align="center" style="padding:13px 6px;border:1px solid #e5e7eb;'
                'border-radius:8px;">'
                '<div style="font-size:11px;color:#6b7280;margin-bottom:4px;">' + label + '</div>'
                '<div style="font-size:20px;font-weight:650;color:' + color +
                ';letter-spacing:-.5px;">' + val +
                '<span style="font-size:11px;font-weight:400;color:#9ca3af;">' + sub +
                '</span></div></td>')

    stats = (stat("研究标的", str(len(rows)), "#111827", " 个")
             + stat("国内 / 国外 / 行业",
                    "%d<small>/</small>%d<small>/</small>%d" % (n_cn, n_os, n_ind),
                    "#111827", "")
             + stat("本期买入", str(n_buy), "#0f766e", " 笔")
             + stat("本期金额", "%.0f" % total_amt, "#111827", " 元"))

    port = {}
    ppath = os.path.join(ROOT, "state", "index_portfolio.json")
    if os.path.exists(ppath):
        try:
            port = json.load(open(ppath, encoding="utf-8"))
        except (ValueError, OSError):
            port = {}
    hold = port.get("holdings", {}) or {}
    inv = float(port.get("cumulative_invested_cny") or 0)
    real = float(port.get("realized_pnl_cny") or 0)
    mv = sum(float(h.get("value") or 0) for h in hold.values())
    cost = sum(float(h.get("cost") or 0) for h in hold.values())
    # 盯市缺口：有成本却算不出市值（nav 缺失／update_index_portfolio 没跑过）。
    # 此时绝不能把 mv=0 当成「跌到 0」——那会显示未实现 -360、总资产 0、收益率 -100%，
    # 是假警报。一律显示「—」并在下面挂提示。
    unmarked = [k for k, h in hold.items()
                if float(h.get("cost") or 0) > 0 and not float(h.get("value") or 0) > 0]
    if unmarked:
        unreal = None
        book = (stat("累计投入", format(inv, ",.0f"), "#111827", " 元")
                + stat("已实现盈亏", format(real, "+,.2f"),
                       "#b91c1c" if real >= 0 else "#15803d", " 元")
                + stat("未实现盈亏", "—", "#9ca3af", " 未盯市")
                + stat("总资产", "—", "#9ca3af", " 未盯市"))
        book_note = (
            '<tr><td colspan="4" style="padding:10px 12px;background:#fffbeb;'
            'border:1px solid #fde68a;border-radius:8px;font-size:12px;color:#78350f;'
            'line-height:1.7;">'
            '<b>账本未盯市：%d 只持仓缺市值，未实现盈亏与总资产暂不计算。</b>'
            '先跑 <code>python scripts/update_index_portfolio.py</code> 补盯市，'
            '否则任何 -100%% 之类的数字都不作数。</td></tr>' % len(unmarked))
    else:
        unreal = mv - cost
        total = inv + real + unreal
        rr = ((real + unreal) / inv * 100) if inv > 0 else 0.0
        pc = "#b91c1c" if (real + unreal) >= 0 else "#15803d"  # 中国习惯：盈利红、亏损绿
        book = (stat("累计投入", format(inv, ",.0f"), "#111827", " 元")
            + stat("已实现盈亏", format(real, "+,.2f"), pc, " 元")
            + stat("未实现盈亏", format(unreal, "+,.2f"), pc, " 元")
            + stat("总资产", format(total, ",.0f"), "#111827", " 元 \u00b7 " + format(rr, "+.2f") + "%"))
        book_note = ""

    data_date = next((r["date"] for r in rows if r["date"]), as_of)

    page = build_page(
        as_of=as_of, data_date=data_date,
        generated=datetime.now().strftime("%Y-%m-%d %H:%M"),
        n_all=len(rows), n_broad=n_broad, n_ind=n_ind, n_buy=n_buy,
        n_stop=n_stop, n_roe=n_roe, n_price=n_price, total_amt=total_amt,
        roe_th=roe_th * 100, unit=unit,
        buy_html=buy_html, cn_broad_html=cn_broad_html,
        os_broad_html=os_broad_html, ind_html=ind_html,
        legend=legend, nav=nav_html, stats=stats, book=book, book_note=book_note,
    )

    os.makedirs(OUTDIR, exist_ok=True)
    path = os.path.join(OUTDIR, "index_valuation_%s.html" % as_of)
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    print("OUT", path)
    print("rows=%d broad=%d industry=%d buys=%d stop=%d roe_blocked=%d price_metric=%d size=%.0fKB"
          % (len(rows), n_broad, n_ind, n_buy, n_stop, n_roe, n_price,
             len(page.encode()) / 1024.0))
    return 0


def build_page(**k):
    return PAGE.replace("__AS_OF__", k["as_of"]) \
               .replace("__DATA_DATE__", k["data_date"]) \
               .replace("__GENERATED__", k["generated"]) \
               .replace("__N_ALL__", str(k["n_all"])) \
               .replace("__N_BROAD__", str(k["n_broad"])) \
               .replace("__N_IND__", str(k["n_ind"])) \
               .replace("__N_BUY__", str(k["n_buy"])) \
               .replace("__N_STOP__", str(k["n_stop"])) \
               .replace("__N_ROE__", str(k["n_roe"])) \
               .replace("__TOTAL_AMT__", ("%.0f" % k["total_amt"])) \
               .replace("__ROE_TH__", ("%.0f" % k["roe_th"])) \
               .replace("__UNIT__", str(k["unit"])) \
               .replace("__STATS__", k["stats"]) \
               .replace("__BOOK__", k["book"]) \
               .replace("__BOOK_NOTE__", k.get("book_note", "")) \
               .replace("__BUY_HTML__", k["buy_html"]) \
               .replace("__CN_BROAD_HTML__", k["cn_broad_html"]) \
               .replace("__OS_BROAD_HTML__", k["os_broad_html"]) \
               .replace("__IND_HTML__", k["ind_html"]) \
               .replace("__NAV__", k["nav"]) \
               .replace("__LEGEND__", k["legend"])


PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>指数估值分位全览 · __AS_OF__</title>
</head>
<body style="margin:0;padding:0;background:#f5f6f8;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f6f8;">
<tr><td style="padding:24px 16px 40px;">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:1500px;margin:0 auto;font-family:__FONT__;font-size:14px;color:#111827;">

<tr><td style="padding:0 0 14px;">
  <div style="font-size:22px;font-weight:650;letter-spacing:-.2px;">指数 · 行业估值分位全览</div>
  <div style="margin-top:8px;font-size:13px;color:#4b5563;line-height:1.7;">
    估值基准日 <b style="color:#111827;">__DATA_DATE__</b> &nbsp;\u00b7&nbsp;
    信号 as_of <b style="color:#111827;">__AS_OF__</b> &nbsp;\u00b7&nbsp;
    生成于 <b style="color:#111827;">__GENERATED__</b> &nbsp;\u00b7&nbsp;
    参数 <b style="color:#111827;">index_params v1.0</b>
  </div>
</td></tr>

<tr><td style="padding:0 0 14px;">
  <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate;border-spacing:8px 0;background:#fff;border:1px solid #e5e7eb;border-radius:12px;">
    <tr><td style="padding:14px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate;border-spacing:8px 0;">
        <tr>__STATS__</tr>
        <tr><td colspan="4" style="height:8px;"></td></tr>
        <tr>__BOOK__</tr>
        __BOOK_NOTE__
      </table>
    </td></tr>
  </table>
</td></tr>

<tr><td style="padding:0 0 14px;">__NAV__</td></tr>

<tr><td>
  <div id="buy" style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:18px;margin-bottom:16px;">
    <div style="font-size:15px;font-weight:650;margin-bottom:4px;">本期买入清单
      <span style="font-size:12px;color:#9ca3af;font-weight:400;margin-left:8px;">
        1X = __UNIT__ 元 \u00b7 合计 __TOTAL_AMT__ 元 \u00b7 仅场外 .OF / LOF</span></div>
    <div style="font-size:11.5px;color:#9ca3af;margin-bottom:12px;">
      已自动登记账本，需人工在下一交易日 15:00 前完成申购</div>
    __BUY_HTML__
  </div>
</td></tr>

<tr><td>__CN_BROAD_HTML__</td></tr>
<tr><td>__OS_BROAD_HTML__</td></tr>
<tr><td>__IND_HTML__</td></tr>

<tr><td style="padding:0;">
  <div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:16px 18px;">
    <div style="font-size:12.5px;font-weight:600;color:#374151;margin-bottom:10px;">
      档位图例 <span style="font-weight:400;color:#9ca3af;font-size:11.5px;">全部 __N_ALL__ 个标的</span></div>
    <div>__LEGEND__</div>
    <div style="margin-top:14px;padding:11px 14px;background:#fffbeb;border:1px solid #fde68a;border-radius:8px;color:#78350f;font-size:12.5px;line-height:1.7;">
      <b>本期计划已自动登记到账本，需人工在下一交易日 15:00 前按清单完成场外申购。</b>
    </div>
    <div style="margin-top:14px;padding-top:12px;border-top:1px solid #e5e7eb;font-size:11.5px;color:#9ca3af;line-height:1.9;">
      口径：综合分位为 PE/PB/PS/股息率加权后的百分位得分，越低越便宜；分档 0-10 深度低估 2.0x、10-25 低估 1.5x、25-40 偏低 1.0x、40-75 停投、\u226575 分档减速卖出。<br>
      行业需隐含 ROE（PB/PE）同比 &gt; __ROE_TH__% 且分位 &lt; 40 才入选，每期取分位最低 5 个；ROE 缺失视为不合格。本期 ROE 挡掉 __N_ROE__ 个，停投 __N_STOP__ 个。<br>
      口径差异（2026-10-29）：<b>日经225 / 越南胡志明</b> 无公开指数级 PE/PB，降级用跟踪ETF复权净值的滚动分位，
      标 <b>价格分位</b> 标签、倍数锁 1.0x、不产生卖出信号；<b>印度NIFTY50</b> 用 NSE 官方月度 PE/PB（经前向填充成日度），
      但载体是世界内唯一印度 QDII 主动基金，倍数同样封顶 1.0x；印度原 SENSEX、中韩半导体仍停用（无可用估值源）。
    </div>
  </div>
</td></tr>

</table>
</td></tr></table>
</body>
</html>
"""

PAGE = PAGE.replace("__FONT__", FONT)

if __name__ == "__main__":
    sys.exit(main())
