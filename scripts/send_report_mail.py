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
            flush_ul(); out.append("<h3>%s</h3>" % inline(s[4:]))
        elif s.startswith("## "):
            flush_ul(); out.append("<h2>%s</h2>" % inline(s[3:]))
        elif s.startswith("# "):
            flush_ul(); out.append("<h1>%s</h1>" % inline(s[2:]))
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
    return ("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>%s</title><style>%s</style></head><body><div class='wrap'>"
            "<div class='card'>%s%s</div>"
            "<div class='footer'>多 Agent 协同交易框架自动生成 · 模拟盘研究记录，不构成投资建议</div>"
            "</div></body></html>" % (title, CSS,
                                      "<h1>%s</h1>" % title,
                                      ("<p style='color:#8a9099;font-size:12px;margin:0'>%s</p>" % subtitle) if subtitle else ""))


def render_regime(date):
    p = os.path.join(ROOT, "state", "regime.json")
    if not os.path.exists(p):
        return None, "regime.json 不存在"
    d = json.load(open(p, encoding="utf-8"))
    sev = d.get("severity")
    rows = [("regime", d.get("regime")), ("severity", sev or "—"),
            ("confidence", d.get("confidence")), ("总分", d.get("score")),
            ("已确认天数", d.get("confirmed_days")), ("风险级别", d.get("risk_level")),
            ("仓位提示", d.get("position_hint"))]
    cards = "".join("<div><div class='k'>%s</div><div class='v'>%s</div></div>" % (k, v if v is not None else "—")
                    for k, v in rows[:4])
    html = ["<div class='metric'>%s</div>" % cards, "<h2>判定依据</h2><ul>"]
    for e in (d.get("evidence") or []):
        html.append("<li>%s</li>" % inline(str(e)))
    html.append("</ul>")
    dims = d.get("dimensions") or {}
    if dims:
        html.append("<h2>六维打分</h2><table><tr><th>维度</th><th>取值</th></tr>")
        for k, v in dims.items():
            html.append("<tr><td>%s</td><td>%s</td></tr>" % (k, inline(json.dumps(v, ensure_ascii=False)[:200])))
        html.append("</table>")
    if d.get("tag_conflicts"):
        html.append("<h2>标签与数值冲突</h2><ul>")
        for t in d["tag_conflicts"]:
            html.append("<li>%s</li>" % inline(str(t)))
        html.append("</ul>")
    extra = [("风险级别", d.get("risk_level")), ("仓位提示", d.get("position_hint")),
             ("已确认天数", d.get("confirmed_days"))]
    html.append("<h2>操作含义</h2><ul>")
    for k, v in extra:
        if v is not None:
            html.append("<li><b>%s</b>：%s</li>" % (k, inline(str(v))))
    html.append("</ul>")
    title = "市场环境判断 %s · %s%s" % (d.get("date"), d.get("regime"), ("/" + sev) if sev else "")
    return wrap(title, "\n".join(html), "基准日 %s · 生成于 %s" % (d.get("date"), "now")), None


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
