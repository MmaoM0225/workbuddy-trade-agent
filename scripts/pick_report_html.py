#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""选股结果 HTML 报告生成器。

读取 state/pool.json + watchlist.json + orders.json，产出可直接发邮件的单文件 HTML。
用法：python scripts/pick_report_html.py [--out <路径>]
"""
import argparse
import json
import os
from datetime import datetime

ROOT = r"E:\cashfree\agent"
STATE = os.path.join(ROOT, "state")


def load(name):
    p = os.path.join(STATE, name)
    if not os.path.exists(p):
        return {}
    return json.load(open(p, encoding="utf-8"))


def esc(x):
    return (str(x) if x is not None else "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


CSS = """
body{margin:0;padding:0;background:#f5f6f8;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;color:#1f2329;}
.wrap{max-width:920px;margin:0 auto;padding:24px 16px 48px;}
.card{background:#fff;border-radius:10px;padding:20px 22px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.06);}
h1{font-size:20px;margin:0 0 6px;font-weight:600;}
h2{font-size:15px;margin:0 0 14px;font-weight:600;color:#1f2329;border-left:3px solid #c8102e;padding-left:9px;}
.sub{color:#8a9099;font-size:12px;margin-bottom:2px;}
.metrics{display:flex;flex-wrap:wrap;gap:10px;}
.metric{flex:1 1 120px;background:#fafbfc;border:1px solid #eceef1;border-radius:8px;padding:12px 14px;}
.metric .k{font-size:11px;color:#8a9099;margin-bottom:5px;}
.metric .v{font-size:19px;font-weight:600;}
table{width:100%;border-collapse:collapse;font-size:13px;}
th{background:#f7f8fa;color:#646a73;font-weight:500;text-align:left;padding:9px 10px;border-bottom:1px solid #eceef1;font-size:12px;}
td{padding:9px 10px;border-bottom:1px solid #f2f3f5;}
tr:last-child td{border-bottom:none;}
.up{color:#c8102e;font-weight:600;}
.code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;color:#646a73;}
.tag{display:inline-block;background:#f2f3f5;color:#646a73;border-radius:4px;padding:1px 6px;font-size:11px;margin-left:4px;}
.avoid{color:#c8102e;}
.note{font-size:12px;color:#8a9099;line-height:1.7;}
.footer{text-align:center;color:#a8adb5;font-size:11px;margin-top:22px;}
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    pool = load("pool.json")
    wl = load("watchlist.json")
    od = load("orders.json")
    date = pool.get("date") or wl.get("date") or od.get("date") or datetime.now().strftime("%Y%m%d")

    out = a.out or os.path.join(ROOT, "reports", "pick_report_%s.html" % date)
    os.makedirs(os.path.dirname(out), exist_ok=True)

    orders = od.get("orders", []) or []
    items = wl.get("items", []) or []
    avoid = (wl.get("avoid") or wl.get("avoid_list")
             or (wl.get("notes") or {}).get("avoid_summary") or [])
    notes = pool.get("notes") if isinstance(pool.get("notes"), list) else []
    ver = pool.get("strategy_version") or od.get("params_version") or "?"

    total_w = sum((o.get("target_weight_pct") or o.get("weight") or 0) for o in orders)

    H = []
    H.append("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>")
    H.append("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    H.append("<title>选股结果 %s</title><style>%s</style></head><body><div class='wrap'>" % (esc(date), CSS))

    # header
    H.append("<div class='card'><h1>选股结果 · %s</h1>" % esc(date))
    H.append("<div class='sub'>参数版本 %s · regime %s · 生成于 %s</div></div>" % (
        esc(ver), esc(od.get("regime") or "—"), datetime.now().strftime("%Y-%m-%d %H:%M")))

    # metrics
    H.append("<div class='card'><h2>关键指标</h2><div class='metrics'>")
    for k, v in (("可选股票池", pool.get("universe_size") or "—"),
                 ("精选池", pool.get("count") or "—"),
                 ("排雷剔除", len(avoid)),
                 ("观察池", len(items)),
                 ("计划订单", len(orders)),
                 ("计划仓位", "%.1f%%" % total_w)):
        H.append("<div class='metric'><div class='k'>%s</div><div class='v'>%s</div></div>" % (esc(k), esc(v)))
    H.append("</div></div>")

    # orders
    if orders:
        H.append("<div class='card'><h2>计划买单（%d 只）</h2><table>"
                 "<tr><th>#</th><th>名称</th><th>代码</th><th>行业</th><th>权重</th>"
                 "<th>首档触发</th><th>二档触发</th><th>止损</th><th>止盈</th></tr>" % len(orders))
        for i, o in enumerate(orders, 1):
            tr = o.get("tranches") or [{}, {}]
            def trig(t):
                if t.get("trigger_price") is not None:
                    return t["trigger_price"]
                pz = t.get("price_zone") or [0]
                return pz[0]
            H.append("<tr><td>%d</td><td><b>%s</b></td><td class='code'>%s</td><td>%s</td>"
                     "<td class='up'>%.2f%%</td><td>%.2f</td><td>%.2f</td><td class='avoid'>%.2f</td><td class='up'>%.2f</td></tr>" % (
                         i, esc(o.get("name")), esc(o.get("code")),
                         esc(o.get("sector") or o.get("industry") or "—"),
                         o.get("target_weight_pct") or o.get("weight") or 0,
                         trig(tr[0]), trig(tr[1]) if len(tr) > 1 else 0,
                         o.get("stop_loss") or 0, o.get("take_profit") or 0))
        H.append("</table><div class='note' style='margin-top:10px'>买点规则：以基准日收盘价为锚，首档回落 1% 触发、二档回落 4% 触发，跌破 -12% 放弃买入；挂单 10 个交易日未成交即作废。</div></div>")

    # watchlist
    if items:
        H.append("<div class='card'><h2>观察池（%d 只，按质量分排序）</h2><table>"
                 "<tr><th>#</th><th>名称</th><th>代码</th><th>质量分</th><th>入选依据</th></tr>" % len(items))
        for i, x in enumerate(items, 1):
            H.append("<tr><td>%d</td><td><b>%s</b></td><td class='code'>%s</td><td class='up'>%s</td><td class='note'>%s</td></tr>" % (
                i, esc(x.get("name")), esc(x.get("code")),
                x.get("quality_score") if x.get("quality_score") is not None else "—",
                esc((x.get("thesis") or "")[:90])))
        H.append("</table></div>")

    # avoid
    if avoid:
        H.append("<div class='card'><h2>排雷剔除（%d 只）</h2><table><tr><th>名称</th><th>代码</th><th>原因</th></tr>" % len(avoid))
        for x in avoid:
            reason = x.get("reason") or "；".join(x.get("flags") or [])
            H.append("<tr><td>%s</td><td class='code'>%s</td><td class='avoid'>%s</td></tr>" % (
                esc(x.get("name")), esc(x.get("code")), esc(reason)))
        H.append("</table><div class='note' style='margin-top:10px'>一票否决项：商誉/净资产 &gt; 30%、审计非标、近 3 月大股东减持占总股本 &gt; 1%。</div></div>")

    # notes
    if notes:
        H.append("<div class='card'><h2>口径说明</h2><div class='note'>")
        for n in notes[:10]:
            H.append("· %s<br>" % esc(n))
        H.append("</div></div>")

    H.append("<div class='footer'>本报告由多 Agent 协同交易框架自动生成 · 仅为模拟盘研究记录，不构成投资建议</div>")
    H.append("</div></body></html>")

    open(out, "w", encoding="utf-8").write("\n".join(H))
    print(out)
    print("orders=%d items=%d avoid=%d ver=%s" % (len(orders), len(items), len(avoid), ver))


if __name__ == "__main__":
    main()
