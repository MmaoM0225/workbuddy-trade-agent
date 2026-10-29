#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pull_fund_nav.py - 场外基金复权净值采集

场外基金没有二级市场价格，定投按当日净值（T日15:00前申购）确认，
用 tushare fund_nav 的 adj_nav（复权净值，含分红再投资）做回测最贴近实际。

输出：data/warehouse/fund_nav/<fund_code>.csv   nav_date,adj_nav

用法：
  python scripts/pull_fund_nav.py
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "warehouse", "fund_nav")
POOL = os.path.join(ROOT, "data", "index_universe.json")
MAP_OF = os.path.join(ROOT, "data", "index_fund_map_of.json")


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
                                                      "clientInfo": {"name": "fn", "version": "1"}}):
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

    if args.codes:
        codes = [c.strip() for c in args.codes.split(",")]
    else:
        with open(MAP_OF, encoding="utf-8") as f:
            mp = json.load(f)["map"]
        codes = []
        for v in mp.values():
            p = v.get("primary")
            if p and p["fund_code"].endswith(".OF"):
                codes.append(p["fund_code"])

    os.makedirs(OUT, exist_ok=True)
    cfg = json.loads(os.environ["CODEBUDDY_MCP_CONFIG"])
    s = cfg["mcpServers"]["tushare"]
    ts = Mcp(s["url"], s.get("headers", {}))
    ts.init()

    ok, fail = 0, []
    for code in codes:
        try:
            rows = ts.call("fund_nav", {"ts_code": code, "start_date": args.start,
                                        "end_date": args.end,
                                        "fields": ["ts_code", "nav_date", "unit_nav", "adj_nav"]}) or []
            data = {}
            for r in rows:
                v = r.get("adj_nav") or r.get("unit_nav")
                if r.get("nav_date") and v:
                    data[r["nav_date"]] = v
            if not data:
                fail.append(code)
                print("%-12s EMPTY" % code, flush=True)
                continue
            with open(os.path.join(OUT, code + ".csv"), "w", encoding="utf-8", newline="") as f:
                f.write("nav_date,adj_nav\n")
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
