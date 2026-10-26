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


def wrap(title, body_html, subtitle=""):
    sub = ("<p style='color:#8a9099;font-size:12px;margin:0'>%s</p>" % subtitle) if subtitle else ""
    return ("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>%s</title><style>%s</style></head><body><div class='wrap'>"
            "<div class='card'><h1>%s</h1>%s%s</div>"
            "<div class='footer'>多 Agent 协同交易框架自动生成 · 模拟盘研究记录，不构成投资建议</div>"
            "</div></body></html>" % (title, CSS, title, sub, body_html))


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


def render_md(path, title, subtitle=""):
    if not os.path.exists(path):
        return None, "报告不存在: %s" % path
    md = open(path, encoding="utf-8").read()
    return wrap(title, md_to_html(md), subtitle), None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", required=True, choices=["regime", "position", "inspect", "review", "pick"])
    ap.add_argument("--date", default=None)
    ap.add_argument("--to", default=DEFAULT_TO)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    date = a.date
    if not date:
        p = os.path.join(ROOT, "state", "pool.json")
        if os.path.exists(p):
            date = json.load(open(p, encoding="utf-8")).get("date")
    prefix = {"regime": "[市场]", "position": "[持仓]", "inspect": "[巡检]", "review": "[复盘]", "pick": "[选股]"}

    if a.type == "regime":
        html, err = render_regime(date)
        subject = "%s 市场环境判断 %s" % (prefix[a.type], date)
    elif a.type == "position":
        html, err = render_md(os.path.join(ROOT, "reports", "position_review_%s.md" % date),
                              "持仓检视 %s" % date, "生成于 %s" % date)
        subject = "%s 持仓检视 %s" % (prefix[a.type], date)
    elif a.type == "inspect":
        html, err = render_md(os.path.join(ROOT, "reports", "daily_%s.md" % date),
                              "总控巡检 %s" % date, "生成于 %s" % date)
        subject = "%s 总控巡检 %s" % (prefix[a.type], date)
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
