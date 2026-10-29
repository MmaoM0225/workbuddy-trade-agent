#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pull_sw_industry_history.py - 拉申万行业板块的历史估值分位序列（回测用）

valuation 接口每个交易日都返回【当日算出的 5 年分位】，所以历史序列无前视。
分段拉取：单代码 limit=1000（接口按每代码各取 N 条），6 年约需 2 段。

输出：data/warehouse/sw_industry/<pt>.csv
       date,pe_ttm,pb_lf,ps_ttm,pe_pct,pb_pct,ps_pct,div_pct

用法：
  python scripts/pull_sw_industry_history.py
  python scripts/pull_sw_industry_history.py --only 01801193.PT
"""
import argparse
import json
import os
import time
import urllib.request
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "warehouse", "sw_industry")
LATEST = os.path.join(OUT, "latest.json")
FUNDMAP = os.path.join(ROOT, "data", "industry_fund_map.json")


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
        with urllib.request.urlopen(req, timeout=240) as r:
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
                                                      "clientInfo": {"name": "swh", "version": "1"}}):
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
    ap.add_argument("--start", default="20190601")
    ap.add_argument("--end", default="20261027")
    ap.add_argument("--only", default="")
    ap.add_argument("--all", action="store_true", help="含无基金的行业")
    args = ap.parse_args()

    with open(LATEST, encoding="utf-8") as f:
        sw = json.load(f)["map"]
    targets = {}
    if args.only:
        targets = {args.only: sw.get(args.only, {"name": args.only})}
    elif args.all:
        targets = sw
    else:
        with open(FUNDMAP, encoding="utf-8") as f:
            fm = json.load(f)["map"]
        for code, v in sw.items():
            p = (fm.get(code) or {}).get("primary")
            if p and p.get("venue") in ("场外", "LOF"):
                targets[code] = v
    print("待拉取行业 %d 个" % len(targets))

    cfg = json.loads(os.environ["CODEBUDDY_MCP_CONFIG"])
    s = cfg["mcpServers"]["neodata"]
    nd = Mcp(s["url"], s.get("headers", {}))
    nd.init()

    ok, fail = 0, []
    for idx, (code, v) in enumerate(targets.items(), 1):
        rows = {}
        seg_end = args.end
        calls = 0
        while True:
            try:
                res = nd.call("valuation", {"code": code, "start_date": args.start,
                                            "end_date": seg_end, "limit": 1000}) or []
            except Exception as e:  # noqa: BLE001
                print("  %s FAIL %s" % (code, str(e)[:60]))
                break
            if isinstance(res, dict):
                res = res.get("result") or []
            if not res:
                break
            calls += 1
            hist = res[0].get("history") or []
            for h in hist:
                rows[h.get("date")] = h
            if len(hist) < 1000:
                break
            earliest = min(h.get("date") for h in hist if h.get("date"))
            nxt = (datetime.strptime(earliest, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
            if nxt <= args.start:
                break
            seg_end = nxt
            time.sleep(0.3)

        if not rows:
            fail.append(code)
            print("[%d/%d] %-14s EMPTY" % (idx, len(targets), v.get("name", code)[:12]))
            continue
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, code + ".csv"), "w", encoding="utf-8", newline="") as f:
            f.write("date,pe_ttm,pb_lf,ps_ttm,pe_pct,pb_pct,ps_pct,div_pct\n")
            for d in sorted(rows):
                h = rows[d]
                def g(k, mul=1):
                    x = h.get(k)
                    return "" if x is None else round(x * mul, 4)
                f.write("%s,%s,%s,%s,%s,%s,%s,%s\n" % (
                    d, g("pe_ttm"), g("pb_lf"), g("ps_ttm"),
                    g("pe_percentile_5y", 100), g("pb_percentile_5y", 100),
                    g("ps_percentile_5y", 100), g("dividend_yield_percentile_5y", 100)))
        ok += 1
        print("[%d/%d] %-14s %4d bars (%d calls) %s->%s" % (
            idx, len(targets), (v.get("name") or code)[:12], len(rows), calls,
            min(rows), max(rows)), flush=True)
        time.sleep(0.25)

    print("\nDONE ok=%d fail=%d %s" % (ok, len(fail), fail[:6]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
