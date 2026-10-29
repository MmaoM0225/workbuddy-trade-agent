#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pull_index_price.py - 指数日线收盘价采集（A股 index_daily / 海外 index_global）

回测需要「估值分位 + 点位」两条序列对齐。
输出：data/warehouse/index_price/<ts_code>.csv   trade_date,close

用法：
  python scripts/pull_index_price.py            # 全池
  python scripts/pull_index_price.py --codes 000300.SH
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "warehouse", "index_price")
POOL = os.path.join(ROOT, "data", "index_universe.json")

# tushare index_global 的代码口径与 neodata 不同
GLOBAL_MAP = {"HSI.HK": "HSI", "HSCEI.HK": "HSCEI", "HSTECH.HK": "HSTECH", "IXIC.US": "IXIC"}
# index_global 拿不到的，用跟踪 ETF 日线代替（价格含跟踪误差，比无数据强）
ETF_FALLBACK = {"HSCEI.HK": "510900.SH", "HSTECH.HK": "513130.SH"}


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
                                                      "clientInfo": {"name": "ip", "version": "1"}}):
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


def client(key):
    cfg = json.loads(os.environ["CODEBUDDY_MCP_CONFIG"])
    s = cfg["mcpServers"][key]
    c = Mcp(s["url"], s.get("headers", {}))
    c.init()
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", default="")
    ap.add_argument("--start", default="20190101")
    ap.add_argument("--end", default="20261027")
    args = ap.parse_args()

    with open(POOL, encoding="utf-8") as f:
        uni = json.load(f)["indices"]
    codes = [c.strip() for c in args.codes.split(",")] if args.codes else [x["code"] for x in uni]

    os.makedirs(OUT, exist_ok=True)
    ts = client("tushare")
    ok, fail = 0, []

    for code in codes:
        try:
            if code in GLOBAL_MAP:
                rows = ts.call("index_global", {"ts_code": GLOBAL_MAP[code],
                                                "start_date": args.start, "end_date": args.end,
                                                "fields": ["ts_code", "trade_date", "close"]})
                if not rows and code in ETF_FALLBACK:
                    rows = ts.call("fund_daily", {"ts_code": ETF_FALLBACK[code],
                                                  "start_date": args.start, "end_date": args.end,
                                                  "fields": ["ts_code", "trade_date", "close"]})
            else:
                rows = ts.call("index_daily", {"ts_code": code,
                                               "start_date": args.start, "end_date": args.end,
                                               "fields": ["ts_code", "trade_date", "close"]})
                if not rows and code.endswith(".SH"):
                    # 中证行业系列在 tushare 用 .CSI 后缀，neodata 用 .SH
                    rows = ts.call("index_daily", {"ts_code": code[:-3] + ".CSI",
                                                   "start_date": args.start, "end_date": args.end,
                                                   "fields": ["ts_code", "trade_date", "close"]})
            rows = rows or []
            data = {r["trade_date"]: r["close"] for r in rows if r.get("close") is not None}
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
            print("%-12s FAIL %s" % (code, str(e)[:100]), flush=True)
        time.sleep(0.25)

    print("\nDONE ok=%d fail=%s" % (ok, fail or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
