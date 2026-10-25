#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把选股 HTML 报告发到指定邮箱（走 agent-mail MCP，内容不经过对话上下文）。

用法：
  python scripts/send_pick_report.py                       # 默认发 1920442561@qq.com
  python scripts/send_pick_report.py --to a@b.com --date 20261023
  python scripts/send_pick_report.py --html reports/pick_report_20261023.html
"""
import argparse
import json
import os
import sys

sys.path.insert(0, r"E:/cashfree/agent/scripts")
from update_warehouse import McpClient  # noqa: E402

ROOT = r"E:\cashfree\agent"
DEFAULT_TO = "1920442561@qq.com"


def send_mail(to, subject, html_body, skip_confirmation=True):
    cfg = json.loads(os.environ["CODEBUDDY_MCP_CONFIG"])
    srv = cfg["mcpServers"]["agent-mail"]
    c = McpClient(srv["url"], srv.get("headers", {}))
    c.initialize()
    args = {
        "to": [{"email": to}],
        "subject": subject,
        "body": html_body,
        "body_format": "HTML",
        "skip_confirmation": skip_confirmation,
    }
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
    ap.add_argument("--date", default=None)
    ap.add_argument("--html", default=None)
    ap.add_argument("--no-skip-confirm", action="store_true")
    a = ap.parse_args()

    html_path = a.html
    if not html_path:
        date = a.date
        if not date:
            pool = os.path.join(ROOT, "state", "pool.json")
            if os.path.exists(pool):
                date = json.load(open(pool, encoding="utf-8")).get("date")
        html_path = os.path.join(ROOT, "reports", "pick_report_%s.html" % date)

    if not os.path.exists(html_path):
        print("HTML not found:", html_path)
        sys.exit(1)

    html = open(html_path, encoding="utf-8").read()
    date = os.path.basename(html_path).replace("pick_report_", "").replace(".html", "")
    subject = "选股结果 %s · v1.8 · 计划买单报告" % date
    ok, msg = send_mail(a.to, subject, html, not a.no_skip_confirm)
    print("SENT" if ok else "FAILED", "->", a.to, "|", msg.replace("\n", " ")[:300])
    sys.exit(0 if ok else 2)


if __name__ == "__main__":
    main()
