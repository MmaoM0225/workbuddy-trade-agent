#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pull_fund_price.py - 拉取标的基金的二级市场日线（场内 ETF 口径）

定投买的是基金，不是指数。用基金价格回测才能体现：
  - 管理费/托管费（已扣在净值里，反映在价格上）
  - 跟踪误差（QDII 年化 2.5-4.7%，A股 ETF 0.3-0.9%）
  - 折溢价波动

输出：data/warehouse/fund_price/<fund_code>.csv   trade_date,close

用法：
  python scripts/pull_fund_price.py
  python scripts/pull_fund_price.py --codes 510330.SH
"""
import argparse
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "warehouse", "fund_price")
POOL = os.path.join(ROOT, "data", "index_universe.json")


class Mcp:
    def __init__(self, url, headers):
        self.url, self.headers = url, dict(headers)
        self.headers.update({"Content-Type": "application/json",
                             "Accept": "application/json, text/event-stream"})
        self.sid, self._id = None, 0

    def _post(self, payload):
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(),
                                     headers=self.headers, method="POST")
        if self.sid:
            req.add_header("Mcp-Session-Id", self.sid)
        with urllib.request.urlopen(req, timeout=180) as r:
            if r.headers.get("Mcp-Session-Id"):
                self.sid = r.headers["Mcp-Session-Id"]
            return r.read().decode(), r.headers.get("Content-Type", "")

    def req(self, method, params):
        self._id += 1
        raw, ct = self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        if "text/event-stream" in ct:
            obj = None
            for line in raw.splitlines():
                if line.startswith("data:"):
                    obj = json.loads(line[5:].strip())
            return obj
        return json.loads(raw)

    def init(self):
        for v in ("2025-06-18", "2025-03-26", "2024-11-05"):
            if "error" not in self.req("initialize", {"protocolVersion": v, "capabilities": {},
                                                      "clientInfo": {"name": "fp", "version": "1"}}):
                self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
                return
        raise RuntimeError("init failed")

    def call(self, name, args, retries=3):
        last = None
        for i in range(retries):
            try:
                r = self.req("tools/call", {"name": name, "arguments": args})
                if "error" in r:
                    raise RuntimeError(str(r["error"])[:200])
                res = r.get("result", {})
                txt = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
                if res.get("isError"):
                    raise RuntimeError(txt[:200])
                return json.loads(txt) if txt else None
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(1.5 * (i + 1))
        raise RuntimeError(str(last)[:160])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", default="")
    ap.add_argument("--start", default="20190101")
    ap.add_argument("--end", default="20261027")
    args = ap.parse_args()

    with open(POOL, encoding="utf-8") as f:
        uni = json.load(f)["indices"]
    if args.codes:
        codes = [c.strip() for c in args.codes.split(",")]
    else:
        codes = [x["fund"] for x in uni if x.get("tradable") and x.get("fund")]

    os.makedirs(OUT, exist_ok=True)
    cfg = json.loads(os.environ["CODEBUDDY_MCP_CONFIG"])
    s = cfg["mcpServers"]["tushare"]
    ts = Mcp(s["url"], s.get("headers", {}))
    ts.init()

    ok, fail = 0, []
    for code in codes:
        try:
            rows = ts.call("fund_daily", {"ts_code": code, "start_date": args.start,
                                          "end_date": args.end,
                                          "fields": ["ts_code", "trade_date", "close"]}) or []
            data = {r["trade_date"]: r["close"] for r in rows if r.get("close")}
            if not data:
                fail.append(code)
                print("%-12s EMPTY" % code, flush=True)
                continue
            with open(os.path.join(OUT, code + ".csv"), "w", encoding="utf-8", newline="") as f:
                f.write("trade_date,close\n")
                for d in sorted(data):
                    f.write("%s,%s\n" % (d, data[d]))
            ok += 1
            print("%-12s %5d bars  %s -> %s" % (code, len(data), min(data), max(data)), flush=True)
        except Exception as e:  # noqa: BLE001
            fail.append(code)
            print("%-12s FAIL %s" % (code, str(e)[:90]), flush=True)
        time.sleep(0.25)

    print("\nDONE ok=%d fail=%s" % (ok, fail or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
