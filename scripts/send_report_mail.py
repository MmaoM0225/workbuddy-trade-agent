#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""统一报告邮件发送器：把各 agent 的报告转成 HTML 邮件发出。

用法：
  python scripts/send_report_mail.py --type regime   --date 20261023
  python scripts/send_report_mail.py --type position --date 20261023
  python scripts/send_report_mail.py --type inspect  --date 20261023
  python scripts/send_report_mail.py --type review
  python scripts/send_report_mail.py --type pick     --date 20261023
可选：--to（默认 1920442561@qq.com）、--dry-run（只生成 HTML 不发）

type 说明：
  regime   市场分析师  → state/regime.json
  position 持仓管家    → reports/position_review_<date>.md
  inspect  总控巡检    → reports/daily_<date>.md
  review   复盘官      → reviews/weekly_*.md（取最新）
  pick     建仓经理    → 直接复用 reports/pick_report_<date>.html
"""
import argparse
import datetime
import glob
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, r"E:/cashfree/agent/scripts")
from send_pick_report import send_mail  # noqa: E402

ROOT = r"E:\cashfree\agent"
DEFAULT_TO = "1920442561@qq.com"

CSS = """
body{margin:0;padding:0;background:#f5f6f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;color:#1f2329;}
.wrap{max-width:880px;margin:0 auto;padding:24px 16px 44px;}
.card{background:#fff;border-radius:10px;padding:20px 22px;margin-bottom:14px;box-shadow:0 1px 3px rgba(0,0,0,.06);}
h1{font-size:19px;margin:0 0 14px;font-weight:600;border-left:3px solid #c8102e;padding-left:10px;}
h2{font-size:14px;margin:18px 0 10px;font-weight:600;color:#1f2329;}
h3{font-size:13px;margin:14px 0 8px;font-weight:600;color:#646a73;}
h4{font-size:12.5px;margin:12px 0 6px;font-weight:600;color:#8a9099;}
p{font-size:13px;line-height:1.75;margin:6px 0;color:#2b3038;}
ul{margin:6px 0;padding-left:20px;}
li{font-size:13px;line-height:1.75;color:#2b3038;}
table{width:100%;border-collapse:collapse;font-size:12.5px;margin:8px 0;}
th{background:#f7f8fa;color:#646a73;font-weight:500;text-align:left;padding:8px 10px;border-bottom:1px solid #eceef1;}
td{padding:8px 10px;border-bottom:1px solid #f2f3f5;vertical-align:top;}
code{background:#f2f3f5;border-radius:3px;padding:1px 5px;font-size:12px;font-family:ui-monospace,Menlo,monospace;}
.metric{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:6px;}
.metric div{flex:1 1 130px;background:#fafbfc;border:1px solid #eceef1;border-radius:8px;padding:11px 13px;}
.metric .k{font-size:11px;color:#8a9099;margin-bottom:4px;}
.metric .v{font-size:17px;font-weight:600;}
.footer{text-align:center;color:#a8adb5;font-size:11px;margin-top:18px;}
.mt{width:100%;border-collapse:separate;border-spacing:7px 0;margin:0 -7px 10px;}
.mt td{background:#fafbfc;border:1px solid #eceef1;border-radius:8px;padding:11px 13px;vertical-align:top;border-bottom:1px solid #eceef1;}
.mt .k{font-size:11px;color:#8a9099;margin-bottom:5px;font-weight:400;}
.mt .v{font-size:18px;font-weight:600;line-height:1.2;}
.mt .s{font-size:11px;color:#8a9099;margin-top:3px;}
.up{color:#c8102e;}
.down{color:#0a8f4d;}
.badge{display:inline-block;padding:2px 9px;border-radius:10px;font-size:11px;font-weight:600;line-height:1.6;}
.b-bull{background:#fdecef;color:#c8102e;}
.b-bear{background:#e8f6ee;color:#0a8f4d;}
.b-neutral{background:#f1f2f4;color:#646a73;}
.warnbox{background:#fffbf0;border-left:3px solid #f0a020;border-radius:0 6px 6px 0;padding:10px 14px;margin:8px 0;}
.warnbox ul{margin:2px 0;padding-left:18px;}
.warnbox li{font-size:12.5px;line-height:1.7;margin:3px 0;}
.strategy{background:#f6f9ff;border-left:3px solid #3b6ef0;border-radius:0 6px 6px 0;padding:12px 14px;margin:8px 0;}
.strategy p{margin:4px 0;font-size:13px;}
.sig{display:inline-block;min-width:46px;padding:1px 7px;border-radius:4px;font-size:11px;font-weight:600;margin-right:6px;}
.sig-short{background:#e8f6ee;color:#0a8f4d;}
.sig-long{background:#fdecef;color:#c8102e;}
.sig-neutral{background:#f1f2f4;color:#646a73;}
.dimrow td{font-size:12.5px;}
.detail{color:#4e5561;font-size:12.5px;line-height:1.7;}
hr.sep{border:0;border-top:1px dashed #e6e8eb;margin:16px 0;}
"""


def inline(s):
    s = (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def md_to_html(md):
    lines = md.replace("\r", "").split("\n")
    out, ul_open, tbl = [], False, []

    def flush_ul():
        nonlocal ul_open
        if ul_open:
            out.append("</ul>")
            ul_open = False

    def flush_tbl():
        nonlocal tbl
        if not tbl:
            return
        rows = [r for r in tbl if not re.match(r"^\|[\s\-:|]+\|$", r.strip())]
        if rows:
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
            out.append("<table>")
            out.append("<tr>" + "".join("<th>%s</th>" % inline(c) for c in cells[0]) + "</tr>")
            for row in cells[1:]:
                out.append("<tr>" + "".join("<td>%s</td>" % inline(c) for c in row) + "</tr>")
            out.append("</table>")
        tbl = []

    for raw in lines:
        s = raw.rstrip()
        if s.startswith("|"):
            flush_ul()
            tbl.append(s)
            continue
        flush_tbl()
        if not s.strip():
            flush_ul()
            continue
        if s.startswith("### "):
            flush_ul(); out.append("<h4>%s</h4>" % inline(s[4:]))
        elif s.startswith("## "):
            flush_ul(); out.append("<h3>%s</h3>" % inline(s[3:]))
        elif s.startswith("# "):
            flush_ul(); out.append("<h2>%s</h2>" % inline(s[2:]))
        elif s.startswith(("- ", "* ")):
            if not ul_open:
                out.append("<ul>"); ul_open = True
            out.append("<li>%s</li>" % inline(s[2:]))
        elif s.startswith("> "):
            flush_ul(); out.append("<p><i>%s</i></p>" % inline(s[2:]))
        else:
            flush_ul(); out.append("<p>%s</p>" % inline(s))
    flush_tbl(); flush_ul()
    return "\n".join(out)


def wrap(title, body_html, subtitle="", prepend=""):
    """第一张卡放标题；prepend 里的卡片依次插在标题之后、正文之前；正文单独成卡。"""
    sub = ("<p style='color:#8a9099;font-size:12px;margin:0'>%s</p>" % subtitle) if subtitle else ""
    return ("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>%s</title><style>%s</style></head><body><div class='wrap'>"
            "<div class='card'><h1>%s</h1>%s</div>%s<div class='card'>%s</div>"
            "<div class='footer'>多 Agent 协同交易框架自动生成 · 模拟盘研究记录，不构成投资建议</div>"
            "</div></body></html>" % (title, CSS, title, sub, prepend, body_html))


VERDICT_CN = {"bull": "看多", "bear": "看空", "neutral": "中性"}
DIM_CN = {"trend": "趋势", "breadth": "宽度", "sentiment": "情绪",
          "volume": "量能", "capital": "资金", "sector": "板块"}
BADGE = {"bull": "b-bull", "bear": "b-bear", "neutral": "b-neutral"}
KEY_CN = {
    "close_szzs": "上证收盘", "MA5": "MA5", "MA20": "MA20", "MA60": "MA60",
    "MA250": "MA250", "RSI_12": "RSI12", "MACD": "MACD",
    "CHG_5D_SZZS": "上证5日", "CHG_20D_SZZS": "上证20日", "CHG_60D_SZZS": "上证60日",
    "MONEY": "两市成交额", "RATIO_UP": "上涨占比", "RATIO_UPDOWN": "涨跌比",
    "CNT_REACH_UPLIMIT": "涨停数", "CNT_REACH_DNLIMIT": "跌停数",
    "north_money_yi": "北向净额",
}
PCT_KEYS = {"RATIO_UP", "RATIO_UPDOWN", "CHG_5D_SZZS", "CHG_20D_SZZS",
            "CHG_60D_SZZS", "CHG_120D_SZZS", "CHG_250D_SZZS"}


def _num_text(k, v):
    if not isinstance(v, (int, float)):
        return str(v)
    if k in PCT_KEYS:
        cls = "up" if v > 0 else ("down" if v < 0 else "")
        return "<span class='%s'>%+.2f%%</span>" % (cls, v)
    if k == "north_money_yi":
        cls = "up" if v > 0 else ("down" if v < 0 else "")
        return "<span class='%s'>%+.2f 亿</span>" % (cls, v)
    if k == "MONEY":
        return "%.0f 亿" % v
    if k.startswith("MA") or k == "close_szzs":
        return "%.2f" % v
    return ("%g" % v)


def _regime_sentence(regime, sev, hint):
    base = {"bull": "六维综合偏强，趋势与量能共振向上。",
            "neutral": "六维综合中性，多空分歧，未见趋势性方向。",
            "bear": "六维综合偏弱，趋势与资金面承压。"}.get(regime, "六维综合中性。")
    if regime == "bear" and sev == "light":
        base += "轻度熊市（light）：只禁止新建仓，不强制降仓。"
    elif regime == "bear" and sev == "heavy":
        base += "重度熊市（heavy）：禁止新建仓，连续 2 日确认后降至 20%。"
    return "%s按规则建议总仓位 %s。" % (base, hint)


def render_regime(date):
    p = os.path.join(ROOT, "state", "regime.json")
    if not os.path.exists(p):
        return None, "regime.json 不存在"
    d = json.load(open(p, encoding="utf-8"))
    regime = (d.get("regime") or "neutral").lower()
    sev = d.get("severity")
    badge = BADGE.get(regime, "b-neutral")
    conf = d.get("confidence")
    score = d.get("score")
    hint = d.get("position_hint") or "—"

    cells = [
        ("市场状态", "%s%s" % (regime.upper(), (" / " + sev) if sev else ""),
         "六维总分 %s" % (score if score is not None else "—")),
        ("置信度", ("%.2f" % conf) if isinstance(conf, (int, float)) else "—",
         "已确认 %s 个交易日" % d.get("confirmed_days", "—")),
        ("风险级别", str(d.get("risk_level") or "—").upper(), "风险敞口评估"),
        ("建议仓位", hint, "rules.md 仓位映射"),
    ]
    html = ["<table class='mt'><tr>" + "".join(
        "<td><div class='k'>%s</div><div class='v'>%s</div><div class='s'>%s</div></td>"
        % (k, inline(str(v)), inline(str(s))) for k, v, s in cells) + "</tr></table>"]

    html.append("<div class='strategy'><p style='margin:0 0 5px'>当前判定 "
                "<span class='badge %s'>%s</span></p><p style='margin:0'>%s</p></div>"
                % (badge, VERDICT_CN.get(regime, regime),
                   inline(_regime_sentence(regime, sev, hint))))

    dims = d.get("dimensions") or {}
    if dims:
        html.append("<h2>六维打分</h2><table><tr><th style='width:56px'>维度</th>"
                    "<th style='width:58px'>判定</th><th style='width:48px'>得分</th>"
                    "<th>依据</th></tr>")
        for k, v in dims.items():
            if not isinstance(v, dict):
                continue
            vd = (v.get("verdict") or "neutral").lower()
            sc = v.get("score")
            sc_cls = ""
            if isinstance(sc, (int, float)):
                sc_cls = "up" if sc > 0 else ("down" if sc < 0 else "")
            html.append(
                "<tr class='dimrow'><td><b>%s</b></td><td><span class='badge %s'>%s</span></td>"
                "<td class='%s'><b>%s</b></td><td class='detail'>%s</td></tr>"
                % (DIM_CN.get(k, k), BADGE.get(vd, "b-neutral"), VERDICT_CN.get(vd, vd),
                   sc_cls, ("%+d" % sc) if isinstance(sc, (int, float)) else "—",
                   inline(str(v.get("detail") or ""))))
        html.append("</table>")

    # 市场拥挤度（v2.2 第 7 维，覆盖层）
    cr = d.get("crowding")
    cv = None
    if isinstance(cr, dict) and cr.get("value") is not None:
        try:
            cv = float(cr["value"])
        except (TypeError, ValueError):
            cv = None
    if cv is not None:
        lvl = (cr.get("level") or "normal").lower()
        lvl_cn = {"normal": "正常", "watch": "偏高", "warn": "警戒", "alert": "极端"}.get(lvl, lvl)
        warn_p = float(cr.get("warn_pct") or 45)
        alert_p = float(cr.get("alert_pct") or 50)
        mom = cr.get("mom")
        mom_txt = ("%+.2fpp" % mom) if isinstance(mom, (int, float)) else "—"
        mom_cls = "up" if isinstance(mom, (int, float)) and mom > 0 else "down"
        prev = cr.get("prev_month")
        pr = cr.get("pct_rank")
        top1, top10 = cr.get("top1_pct"), cr.get("top10_pct")
        src = {"mtd": "当月累计", "prev_month": "上月完整值"}.get(
            str(cr.get("source") or ""), str(cr.get("source") or "—"))
        overlay = cr.get("overlay") or "无干预"
        nature_cn = {"high_position": "高位抱团瓦解风险",
                     "reversal_concentration": "低位反向集中（恐慌底特征）",
                     "unclear": "性质不明"}.get(str(cr.get("nature") or ""), "")
        bar_cls = "b-bear" if lvl in ("warn", "alert") else "b-neutral"

        html.append("<h2>市场拥挤度 <span style='font-weight:400;color:#8a9099;font-size:12px'>"
                    "成交额前 %s%% 集中度 · %s</span></h2>" % (cr.get("top_pct") or 5, src))
        html.append("<div class='strategy' style='margin-bottom:8px'><p style='margin:0 0 5px'>"
                    "<span style='font-size:26px;font-weight:700'>%.2f%%</span> "
                    "<span class='badge %s'>%s · %s</span>"
                    "%s</p><p style='margin:0;font-size:12px;color:#5a626b'>覆盖判定：<b>%s</b></p></div>"
                    % (cv, bar_cls, inline(str(cr.get("band") or "—")), lvl_cn,
                       (" <span style='font-size:12px;color:#8a9099'>%s</span>" % inline(nature_cn)) if nature_cn else "",
                       inline(str(overlay))))

        # 水位条：0-60% 映射，标出 45 警戒 / 50 警报
        scale, pos = 60.0, min(100.0, cv / 60.0 * 100.0)
        wp, ap = min(100.0, warn_p / 60.0 * 100.0), min(100.0, alert_p / 60.0 * 100.0)
        html.append(
            "<div style='position:relative;height:20px;background:#eef1f4;border-radius:4px;margin:6px 0 2px'>"
            "<div style='position:absolute;left:0;top:0;height:100%%;width:%.1f%%;"
            "background:linear-gradient(90deg,#8fb3c9,#e8a33d 62%%,#c0392b);border-radius:4px'></div>"
            "<div style='position:absolute;left:%.1f%%;top:-3px;height:26px;width:2px;background:#c0392b'></div>"
            "<div style='position:absolute;left:%.1f%%;top:-3px;height:26px;width:2px;background:#7c1d13'></div>"
            "</div><div style='font-size:11px;color:#8a9099;margin-bottom:8px'>"
            "0%%<span style='float:right'>60%%</span>"
            "红线 %g%% 警戒 · %g%% 警报 · 色条为当前水位</div>"
            % (pos, wp, ap, warn_p, alert_p))

        cells2 = [
            ("环比", mom_txt, "上月 %s" % (("%.2f%%" % prev) if isinstance(prev, (int, float)) else "—")),
            ("历史分位", ("%.1f%%" % pr) if isinstance(pr, (int, float)) else "—",
             "%s 个月样本" % (cr.get("sample_months") or "—")),
            ("抱团深度", "%.1f / %.1f" % (top1, top10) if isinstance(top1, (int, float)) and isinstance(top10, (int, float)) else "—",
             "前1% / 前10% 占比"),
            ("窗口", "%s 日" % (cr.get("mtd_days") or "—"), "当月已累计交易日"),
        ]
        html.append("<table class='mt'><tr>" + "".join(
            "<td><div class='k'>%s</div><div class='v' style='font-size:16px'>%s</div>"
            "<div class='s'>%s</div></td>" % (k, v, inline(str(s))) for k, v, s in cells2) + "</tr></table>")
        if isinstance(mom, (int, float)):
            html.append("<p class='detail' style='color:#8a9099;font-size:11.5px;margin:4px 0 0'>"
                        "口径：月度累计成交额前 5%% 集中度（与邢不行视频 45%%/50%% 阈值可比，"
                        "单日口径不可套用）。环比 %s 表示%s。</p>"
                        % (("<span class='%s'>%s</span>" % (mom_cls, mom_txt)),
                           "抱团加剧" if mom > 0 else "抱团退潮"))
    elif isinstance(cr, dict):
        html.append("<h2>市场拥挤度</h2><div class='warnbox'>本次拥挤度数据缺失，未套用覆盖层。</div>")

    kv = []
    for v in dims.values():
        if not isinstance(v, dict):
            continue
        for kk, vv in (v.get("values") or {}).items():
            if kk in KEY_CN and isinstance(vv, (int, float)) and len(kv) < 8:
                kv.append((KEY_CN[kk], _num_text(kk, vv)))
    if kv:
        html.append("<h2>关键数值</h2><table class='mt'><tr>" + "".join(
            "<td><div class='k'>%s</div><div class='v' style='font-size:15px'>%s</div></td>"
            % (k, v) for k, v in kv) + "</tr></table>")

    if d.get("evidence"):
        html.append("<h2>判定依据</h2><ol style='margin:6px 0;padding-left:20px'>")
        for e in d["evidence"]:
            html.append("<li style='font-size:12.5px;line-height:1.8'>%s</li>" % inline(str(e)))
        html.append("</ol>")

    sigs = d.get("sector_signals") or []
    if sigs:
        html.append("<h2>板块信号</h2><table>")
        for s in sigs:
            if not isinstance(s, dict):
                continue
            dr = (s.get("direction") or "neutral").lower()
            html.append("<tr><td style='width:92px'><b>%s</b><br><span class='sig sig-%s'>%s</span></td>"
                        "<td class='detail'>%s</td></tr>"
                        % (inline(str(s.get("sector") or "—")), dr,
                           {"long": "看多", "short": "看空"}.get(dr, "中性"),
                           inline(str(s.get("note") or ""))))
        html.append("</table>")

    if d.get("tag_conflicts"):
        html.append("<h2>标签与数值冲突（%d 条）</h2><div class='warnbox'><ul>" % len(d["tag_conflicts"]))
        for t in d["tag_conflicts"]:
            html.append("<li>%s</li>" % inline(str(t)))
        html.append("</ul></div>")

    html.append("<hr class='sep'><p class='detail' style='color:#8a9099;font-size:11.5px'>"
                "数据来源：data/daily_%s/（indices / market_overview / sector_ranking / "
                "dragon_tiger / northbound）。判定规则见 knowledge/params_current.txt 与 rules.md。</p>"
                % inline(str(d.get("date") or date)))

    title = "市场环境判断 %s · %s%s" % (d.get("date"), regime,
                                        ("/" + sev) if sev else "")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return wrap(title, "\n".join(html),
                "基准日 %s · 生成于 %s" % (d.get("date"), now)), None


def _nav_rows():
    """读 state/nav_history.jsonl（update_nav.py 维护的每日净值序列）。"""
    p = os.path.join(ROOT, "state", "nav_history.jsonl")
    rows = []
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    rows.sort(key=lambda r: r.get("date") or "")
    return rows


def _svg_nav(rows, w=800, h=230):
    """组合 vs 上证 的收益率曲线（A 股配色：红涨绿跌）。点数少也照画。"""
    if len(rows) < 2:
        return ("<p style='color:#8a9099;font-size:13px;padding:16px 0;margin:0'>"
                "净值记录不足 2 个交易日，曲线将在下一交易日后生成。</p>")

    pad_l, pad_r, pad_t, pad_b = 48, 14, 14, 30
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b
    port = [float(r.get("pnl_pct") or 0) for r in rows]
    bmk = [float(r.get("benchmark_pct") or 0) for r in rows]
    vals = port + bmk + [0.0]
    lo, hi = min(vals), max(vals)
    if hi - lo < 0.6:                       # 点位太密时撑开，避免压成一条直线
        mid = (hi + lo) / 2
        lo, hi = mid - 0.3, mid + 0.3
    pad = (hi - lo) * 0.12
    lo, hi = lo - pad, hi + pad
    span = hi - lo or 1.0

    def px(i):
        return pad_l + iw * i / (len(rows) - 1)

    def py(v):
        return pad_t + ih * (hi - v) / span

    def path(series):
        return "M " + " L ".join("%.1f %.1f" % (px(i), py(v)) for i, v in enumerate(series))

    grid, ticks = [], 5
    for k in range(ticks):
        v = lo + span * k / (ticks - 1)
        y = py(v)
        grid.append("<line x1='%d' y1='%.1f' x2='%d' y2='%.1f' stroke='#eef1f4' stroke-width='1'/>"
                    % (pad_l, y, pad_l + iw, y))
        grid.append("<text x='%d' y='%.1f' fill='#98a2b3' font-size='10' text-anchor='end'>%+.1f%%</text>"
                    % (pad_l - 6, y + 3.5, v))
    # 零轴
    y0 = py(0.0)
    zero = ("<line x1='%d' y1='%.1f' x2='%d' y2='%.1f' stroke='#c8ced8' stroke-width='1' "
            "stroke-dasharray='3,3'/>" % (pad_l, y0, pad_l + iw, y0))

    # X 轴标签：超过 8 个点抽样
    step = max(1, len(rows) // 8)
    xlab = []
    for i, r in enumerate(rows):
        if i % step == 0 or i == len(rows) - 1:
            d = r.get("date") or ""
            xlab.append("<text x='%.1f' y='%d' fill='#98a2b3' font-size='10' text-anchor='middle'>%s-%s</text>"
                        % (px(i), h - 10, d[4:6], d[6:8]))

    # 数据点
    dots = []
    for i, r in enumerate(rows):
        c = "#c8102e" if port[i] >= 0 else "#0a8f4d"
        dots.append("<circle cx='%.1f' cy='%.1f' r='3' fill='%s'/>" % (px(i), py(port[i]), c))

    area = ("<path d='%s L %.1f %.1f L %.1f %.1f Z' fill='#c8102e' opacity='0.07'/>"
            % (path(port), px(len(rows) - 1), y0, px(0), y0))

    legend = (
        "<g font-size='11'>"
        "<rect x='%d' y='2' width='10' height='3' fill='#c8102e'/>"
        "<text x='%d' y='7' fill='#4b5563'>组合</text>"
        "<rect x='%d' y='2' width='10' height='3' fill='#8b95a5'/>"
        "<text x='%d' y='7' fill='#4b5563'>上证指数</text>"
        "</g>" % (pad_l, pad_l + 14, pad_l + 58, pad_l + 72))

    return ("<svg viewBox='0 0 %d %d' width='100%%' style='max-width:%dpx;height:auto;display:block' "
            "xmlns='http://www.w3.org/2000/svg' role='img' aria-label='组合与基准收益率曲线'>"
            "%s%s%s<path d='%s' fill='none' stroke='#8b95a5' stroke-width='1.6' stroke-dasharray='4,3'/>"
            "<path d='%s' fill='none' stroke='#c8102e' stroke-width='2'/>%s%s%s</svg>"
            % (w, h, w, "".join(grid), zero, area, path(bmk), path(port),
               "".join(dots), "".join(xlab), legend))


def render_position_cards():
    """持仓邮件的【收益概览】+【收益率曲线】两个板块，插在正文最前面。"""
    rows = _nav_rows()
    if not rows:
        return ("<div class='card'><h2>收益概览</h2>"
                "<p style='color:#8a9099;font-size:13px;margin:0'>尚无净值记录，"
                "持仓管家下次运行将自动生成。</p></div>")

    last = rows[-1]
    pnl = float(last.get("pnl_pct") or 0)
    bmk = float(last.get("benchmark_pct") or 0)
    excess = round(pnl - bmk, 2)
    day = round(pnl - float(rows[-2].get("pnl_pct") or 0), 2) if len(rows) >= 2 else 0.0
    peak, mdd = -1e18, 0.0
    for r in rows:
        v = float(r.get("total_asset") or 0)
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, (v / peak - 1) * 100)

    def tone(v):
        return "#c8102e" if v > 0 else ("#0a8f4d" if v < 0 else "#4b5563")

    def box(label, value, sub, color="#1f2329"):
        return ("<div style='flex:1 1 118px;min-width:112px;background:#fafbfc;border:1px solid #eef1f4;"
                "border-radius:8px;padding:11px 13px'>"
                "<div style='color:#8a9099;font-size:11.5px;margin-bottom:3px'>%s</div>"
                "<div style='font-size:19px;font-weight:600;color:%s;line-height:1.25'>%s</div>"
                "<div style='color:#a0a7b4;font-size:11px;margin-top:2px'>%s</div></div>"
                % (label, color, value, sub))

    cards = (
        box("累计收益", "%+.2f%%" % pnl, "本金 %s 元" % format(int(last.get("total_asset") or 0), ","), tone(pnl))
        + box("当日收益", "%+.2f%%" % day, "前一交易日至今", tone(day))
        + box("相对上证", "%+.2f%%" % excess, "同期基准 %+.2f%%" % bmk, tone(excess))
        + box("最大回撤", "%.2f%%" % mdd, "峰值至谷底", "#0a8f4d" if mdd < -0.001 else "#4b5563")
        + box("当前仓位", "%.2f%%" % float(last.get("position_pct") or 0),
              "持仓 %d 只" % int(last.get("holdings") or 0))
    )

    return (
        "<div class='card'><h2>收益概览</h2>"
        "<div style='display:flex;gap:9px;flex-wrap:wrap;margin:6px 0 2px'>%s</div>"
        "<p style='color:#a0a7b4;font-size:11px;margin:9px 0 0'>口径：累计收益 = 总资产/初始本金−1；"
        "相对上证以建仓基期为起点；净值由 update_nav.py 每交易日落盘。</p></div>"
        "<div class='card'><h2>收益率曲线</h2>%s"
        "<p style='color:#a0a7b4;font-size:11px;margin:8px 0 0'>数据点 %d 个交易日"
        "（%s ~ %s），基准为上证指数 000001.SH。</p></div>"
        % (cards, _svg_nav(rows), len(rows),
           (rows[0].get("date") or "")[:4] + "-" + (rows[0].get("date") or "")[4:6] + "-" + (rows[0].get("date") or "")[6:8],
           (rows[-1].get("date") or "")[:4] + "-" + (rows[-1].get("date") or "")[4:6] + "-" + (rows[-1].get("date") or "")[6:8])
    )


def _equity_svg(eq, w=820, h=280):
    """回测净值曲线：累计收益率（%），带基准可选。"""
    if len(eq) < 2:
        return "<p style='color:#8a9099'>数据不足</p>"
    port = [float(e.get("pnl_pct") or 0) for e in eq]
    lo, hi = min(port + [0.0]), max(port + [0.0])
    pad = (hi - lo) * 0.10 or 1
    lo, hi = lo - pad, hi + pad
    span = hi - lo or 1
    pad_l, pad_r, pad_t, pad_b = 56, 16, 16, 30
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b

    def px(i):
        return pad_l + iw * i / (len(eq) - 1)

    def py(v):
        return pad_t + ih * (hi - v) / span

    path = "M " + " L ".join("%.1f %.1f" % (px(i), py(v)) for i, v in enumerate(port))
    grid, ticks = [], 5
    for k in range(ticks):
        v = lo + span * k / (ticks - 1)
        y = py(v)
        grid.append("<line x1='%d' y1='%.1f' x2='%d' y2='%.1f' stroke='#eef1f4'/>" % (pad_l, y, pad_l + iw, y))
        grid.append("<text x='%d' y='%.1f' fill='#98a2b3' font-size='10' text-anchor='end'>%+.0f%%</text>"
                    % (pad_l - 6, y + 3.5, v))
    y0 = py(0.0)
    zero = ("<line x1='%d' y1='%.1f' x2='%d' y2='%.1f' stroke='#c8ced8' stroke-dasharray='3,3'/>"
            % (pad_l, y0, pad_l + iw, y0))
    area = ("<path d='%s L %.1f %.1f L %.1f %.1f Z' fill='#c8102e' opacity='0.06'/>"
            % (path, px(len(eq) - 1), y0, px(0), y0))
    step = max(1, len(eq) // 7)
    xlab = []
    for i, e in enumerate(eq):
        if i % step == 0 or i == len(eq) - 1:
            dt = e.get("date") or ""
            xlab.append("<text x='%.1f' y='%d' fill='#98a2b3' font-size='10' text-anchor='middle'>%s/%s</text>"
                        % (px(i), h - 10, dt[:4], dt[4:6]))
    return ("<svg viewBox='0 0 %d %d' width='100%%' style='max-width:%dpx;height:auto;display:block' "
            "xmlns='http://www.w3.org/2000/svg'>%s%s%s<path d='%s' fill='none' stroke='#c8102e' stroke-width='2'/>"
            "%s</svg>" % (w, h, w, "".join(grid), zero, area, path, "".join(xlab)))


def render_backtest(pick_path=None):
    """六年回测报告（默认读 test/replay_6y_v29.json）。"""
    cand = pick_path or os.path.join(ROOT, "test", "replay_6y_v29.json")
    if not os.path.exists(cand):
        return None, "回测结果不存在: %s" % cand
    d = json.load(open(cand, encoding="utf-8"))
    s, eq, trades = d["summary"], d["equity"], d["trades"]
    years = len(eq) / 244.0

    tot = s["total_return_pct"] / 100
    ann = (1 + tot) ** (1 / years) - 1
    # 用总资产序列重算复合回撤，不依赖 summary 里的历史字段
    pk, mdd = 0.0, 0.0
    for e in eq:
        v = float(e.get("total") or 0)
        pk = max(pk, v)
        if pk > 0:
            mdd = min(mdd, v / pk - 1)
    mdd_pct = mdd * 100
    calmar = ann / abs(mdd) if mdd else 0

    sells = [t for t in trades if t["side"] == "sell"]
    wins = [t for t in sells if (t.get("pnl_pct") or 0) > 0]
    win_rate = len(wins) / len(sells) * 100 if sells else 0
    avg_pos = sum(float(e.get("pos_pct") or 0) for e in eq) / len(eq)

    # 年度收益
    yr = {}
    for e in eq:
        yr[e["date"][:4]] = e["total"]
    yearly, prev = [], None
    for k in sorted(yr):
        if prev:
            yearly.append((k, (yr[k] / prev - 1) * 100))
        prev = yr[k]

    # 卖出构成
    from collections import Counter
    reason_cn = {"stop_loss": "止损", "take_profit": "止盈", "derisk_heavy": "熊市降仓",
                 "derisk_light": "轻度降仓", "circuit": "回撤熔断"}
    cnt = Counter(reason_cn.get(t["why"], t["why"]) for t in sells)

    def kpi(label, val, sub="", color="#1f2329"):
        return ("<div style='flex:1 1 120px;min-width:114px;background:#fafbfc;border:1px solid #eef1f4;"
                "border-radius:8px;padding:12px 14px'><div style='color:#8a9099;font-size:11.5px'>%s</div>"
                "<div style='font-size:20px;font-weight:600;color:%s;margin-top:3px'>%s</div>"
                "<div style='color:#a0a7b4;font-size:11px;margin-top:2px'>%s</div></div>" % (label, color, val, sub))

    t_color = "#c8102e" if s["total_return_pct"] > 0 else "#0a8f4d"
    kpis = (kpi("累计收益", "%+.2f%%" % s["total_return_pct"], "期末 %.0f 万" % (s["final_assets"] / 1e4), t_color)
            + kpi("年化收益", "%.2f%%" % (ann * 100), "%.1f 年（%d 交易日）" % (years, len(eq)), t_color)
            + kpi("最大回撤", "%.2f%%" % mdd_pct, "复合口径", "#0a8f4d")
            + kpi("Calmar", "%.2f" % calmar, "年化 / 回撤")
            + kpi("胜率", "%.1f%%" % win_rate, "%d 笔平仓" % len(sells))
            + kpi("平均仓位", "%.2f%%" % avg_pos, "交易 %d 笔" % len(trades)))

    yrow = "".join("<tr><td>%s</td><td class='num' style='color:%s;font-weight:600'>%+.2f%%</td></tr>"
                   % (y, "#c8102e" if v > 0 else "#0a8f4d", v) for y, v in yearly)
    ytbl = ("<table><thead><tr><th>年度</th><th style='text-align:right'>收益</th></tr></thead><tbody>%s</tbody></table>"
            % yrow)
    rrow = "".join("<tr><td>%s</td><td class='num'>%d 笔</td></tr>" % (k, v) for k, v in cnt.most_common())

    sub = "%s · 参数 v2.9 · 三档买点（竞价 50%% / −3%% 25%% / −6%% 25%%）+ 牛市连续 3 日补齐 + 仓位 90/70/60" % s["period"]
    body = ("<div class='card'><h2>核心指标</h2>"
            "<div style='display:flex;gap:9px;flex-wrap:wrap;margin:6px 0'>%s</div>"
            "<p style='color:#a0a7b4;font-size:11px;margin:8px 0 0'>回撤为总资产相对历史峰值的复合回撤；"
            "未扣除手续费与滑点。</p></div>"
            "<div class='card'><h2>净值曲线</h2>%s"
            "<p style='color:#a0a7b4;font-size:11px;margin:8px 0 0'>横轴为交易日，纵轴为累计收益率。</p></div>"
            "<div class='card'><h2>年度收益</h2>%s</div>"
            "<div class='card'><h2>卖出构成</h2>"
            "<table><thead><tr><th>原因</th><th style='text-align:right'>笔数</th></tr></thead><tbody>%s</tbody></table>"
            "</div>" % (kpis, _equity_svg(eq), ytbl, rrow))
    return wrap("六年回测报告 · 牛市补齐版", body, sub), None


def render_md(path, title, subtitle="", prepend_html=""):
    if not os.path.exists(path):
        return None, "报告不存在: %s" % path
    md = open(path, encoding="utf-8").read()
    return wrap(title, md_to_html(md), subtitle, prepend=prepend_html), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", required=True, choices=["regime", "position", "inspect", "review", "pick", "backtest"])
    ap.add_argument("--date", default=None)
    ap.add_argument("--to", default=DEFAULT_TO)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    date = a.date
    if not date:
        p = os.path.join(ROOT, "state", "pool.json")
        if os.path.exists(p):
            date = json.load(open(p, encoding="utf-8")).get("date")
    prefix = {"regime": "[市场]", "position": "[持仓]", "inspect": "[巡检]", "review": "[复盘]", "pick": "[选股]", "backtest": "[回测]"}

    if a.type == "regime":
        html, err = render_regime(date)
        subject = "%s 市场环境判断 %s" % (prefix[a.type], date)
    elif a.type == "position":
        # 发信前自动落一次净值（幂等，同日覆盖），保证曲线不依赖 agent 手动执行 update_nav.py
        if date:
            try:
                subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "update_nav.py"),
                                "--date", date], check=False, capture_output=True, timeout=120)
            except (OSError, subprocess.SubprocessError):
                pass
        html, err = render_md(os.path.join(ROOT, "reports", "position_review_%s.md" % date),
                              "持仓检视 %s" % date, "生成于 %s" % date,
                              prepend_html=render_position_cards())
        subject = "%s 持仓检视 %s" % (prefix[a.type], date)
    elif a.type == "inspect":
        html, err = render_md(os.path.join(ROOT, "reports", "daily_%s.md" % date),
                              "总控巡检 %s" % date, "生成于 %s" % date)
        subject = "%s 总控巡检 %s" % (prefix[a.type], date)
    elif a.type == "backtest":
        html, err = render_backtest()
        subject = "%s 六年回测报告 · 牛市补齐版" % prefix[a.type]
    elif a.type == "review":
        files = sorted(glob.glob(os.path.join(ROOT, "reviews", "weekly_*.md")))
        if not files:
            print("FAILED no weekly review found"); sys.exit(2)
        f = files[-1]
        wk = os.path.basename(f).replace("weekly_", "").replace(".md", "")
        html, err = render_md(f, "周度复盘 %s" % wk, "报告 %s" % os.path.basename(f))
        subject = "%s 周度复盘 %s" % (prefix[a.type], wk)
    else:  # pick
        p = os.path.join(ROOT, "reports", "pick_report_%s.html" % date)
        if not os.path.exists(p):
            print("FAILED pick report not found:", p); sys.exit(2)
        html = open(p, encoding="utf-8").read()
        err = None
        subject = "%s 选股结果 %s" % (prefix[a.type], date)

    if err:
        print("FAILED", err); sys.exit(2)

    out_html = os.path.join(ROOT, "reports", "mail_%s_%s.html" % (a.type, date or "latest"))
    open(out_html, "w", encoding="utf-8").write(html)
    if a.dry_run:
        print("DRY-RUN wrote", out_html); return

    ok, msg = send_mail(a.to, subject, html)
    print(("SENT" if ok else "FAILED"), "->", a.to, "|", subject, "|", str(msg).replace("\n", " ")[:200])
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
