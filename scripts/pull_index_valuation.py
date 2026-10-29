#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pull_index_valuation.py - 指数估值历史采集（neodata MCP 直连，落盘不进上下文）

用途：为「指数估值定投」线提供 PE/PB/股息率 日度历史，供分位数与分档信号计算。

数据源：neodata index_valuation
  - 支持 A股宽基/中证行业/全指行业/港股/纳指综合
  - 不支持：标普500、日经225、中证2000、中证A500（代码探测无返回）
  - limit 上限 500，按指数逐只分段拉取

输出：data/warehouse/index_valuation/<ts_code>.csv
字段：trade_date,pe_ttm,pe_ttm_ex_neg,pb_lf,pb_mrq,dividend_ratio,total_mv,index_nc,loss_nc

用法：
  python scripts/pull_index_valuation.py                 # 全池增量
  python scripts/pull_index_valuation.py --codes 000300.SH
  python scripts/pull_index_valuation.py --start 20160101 --force
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "warehouse", "index_valuation")
POOL_FILE = os.path.join(ROOT, "data", "index_universe.json")

FIELDS = ("index_code,index_abbr,trading_day,pe_ttm,pe_ttm_ex_neg,pb_lf,pb_mrq,"
          "dividend_ratio,total_mv,index_nc,loss_nc")
HEADER = "trade_date,pe_ttm,pe_ttm_ex_neg,pb_lf,pb_mrq,dividend_ratio,total_mv,index_nc,loss_nc"


class McpClient:
    def __init__(self, url, headers):
        self.url = url
        self.headers = dict(headers)
        self.headers["Content-Type"] = "application/json"
        self.headers["Accept"] = "application/json, text/event-stream"
        self.session_id = None
        self._id = 0

    def _post(self, payload):
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode("utf-8"),
                                     headers=self.headers, method="POST")
        if self.session_id:
            req.add_header("Mcp-Session-Id", self.session_id)
        with urllib.request.urlopen(req, timeout=180) as resp:
            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                self.session_id = sid
            return resp.read().decode("utf-8"), resp.headers.get("Content-Type", "")

    @staticmethod
    def _parse(raw, ct):
        if "text/event-stream" in ct:
            obj = None
            for line in raw.splitlines():
                if line.startswith("data:"):
                    obj = json.loads(line[len("data:"):].strip())
            return obj
        return json.loads(raw)

    def request(self, method, params):
        self._id += 1
        raw, ct = self._post({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params})
        return self._parse(raw, ct)

    def initialize(self):
        for ver in ("2025-06-18", "2025-03-26", "2024-11-05"):
            r = self.request("initialize", {"protocolVersion": ver, "capabilities": {},
                                            "clientInfo": {"name": "index-valuation", "version": "1.0"}})
            if "error" not in r:
                self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
                return
        raise RuntimeError("initialize failed")

    def call_tool(self, name, arguments, retries=3):
        last = None
        for attempt in range(retries):
            try:
                r = self.request("tools/call", {"name": name, "arguments": arguments})
                if "error" in r:
                    raise RuntimeError(str(r["error"])[:200])
                result = r.get("result", {})
                text = "".join(c.get("text", "") for c in result.get("content", [])
                               if c.get("type") == "text")
                if result.get("isError"):
                    raise RuntimeError(text[:200])
                return text
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError("%s failed: %s" % (name, last))


def get_client(key="neodata"):
    cfg = json.loads(os.environ["CODEBUDDY_MCP_CONFIG"])
    srv = cfg["mcpServers"][key]
    c = McpClient(srv["url"], srv.get("headers", {}))
    c.initialize()
    return c


def parse_result(text):
    """MCP 返回带 result(JSON) + output(markdown)；只取 result 数组。"""
    try:
        obj = json.loads(text)
    except (TypeError, ValueError):
        return []
    if isinstance(obj, dict):
        rows = obj.get("result")
        if isinstance(rows, list):
            return rows
        return []
    return obj if isinstance(obj, list) else []


COLMAP = {
    "trade_date": "trading_day",
    "pe_ttm": "pe_ttm",
    "pe_ttm_ex_neg": "pe_ttm_ex_neg",
    "pb_lf": "pb_lf",
    "pb_mrq": "pb_mrq",
    "dividend_ratio": "dividend_ratio",
    "total_mv": "total_mv",
    "index_nc": "index_nc",
    "loss_nc": "loss_nc",
}


def row_to_line(r):
    out = []
    for col in HEADER.split(","):
        v = r.get(COLMAP.get(col, col))
        out.append("" if v is None or v == "--" else str(v))
    return ",".join(out)


def load_existing(code):
    path = os.path.join(OUT_DIR, code + ".csv")
    if not os.path.exists(path):
        return None, set()
    dates = set()
    with open(path, "r", encoding="utf-8") as f:
        next(f, None)
        for line in f:
            if line.strip():
                dates.add(line.split(",")[0])
    return path, dates


def pull_one(client, code, start, end, force=False):
    """neodata limit 硬上限 100 条/次，且返回区间内【最新】100 条 → 从 end 往前倒推分页。"""
    os.makedirs(OUT_DIR, exist_ok=True)
    path, have = load_existing(code)
    if force and path:
        have = set()
        os.remove(path)
        path = None

    # 增量：已有数据则只补最后一天之后
    if have and not force:
        start = max(max(have), start)

    rows = {}
    seg_end = end
    calls = 0
    while True:
        text = client.call_tool("index_valuation", {
            "index_codes": code,
            "start_date": start,
            "end_date": seg_end,
            "limit": 100,
            "output_fields": FIELDS,
        })
        calls += 1
        batch = parse_result(text)
        if not batch:
            break
        dates = []
        for r in batch:
            d = str(r.get("trading_day") or "")
            if d:
                rows[d] = row_to_line(r)
                dates.append(d)
        if len(batch) < 100 or not dates:
            break  # 区间已取完
        earliest = min(dates)
        nxt = (datetime.strptime(earliest, "%Y%m%d") - timedelta(days=1)).strftime("%Y%m%d")
        if nxt < start:
            break
        seg_end = nxt
        time.sleep(0.25)

    new_rows = {d: v for d, v in rows.items() if d not in have}
    if not new_rows and have:
        return 0, calls

    all_rows = {}
    if path:
        with open(path, "r", encoding="utf-8") as f:
            next(f, None)
            for line in f:
                if line.strip():
                    all_rows[line.split(",")[0]] = line.rstrip("\n")
    all_rows.update(new_rows)

    mode = "a" if (path and new_rows) else "w"
    with open(os.path.join(OUT_DIR, code + ".csv"), mode, encoding="utf-8", newline="") as f:
        if mode == "w":
            f.write(HEADER + "\n")
        for d in sorted(all_rows):
            f.write(all_rows[d] + "\n")
    return len(new_rows), calls


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--codes", default="", help="逗号分隔，缺省读 data/index_universe.json")
    ap.add_argument("--start", default="20160101")
    ap.add_argument("--end", default=datetime.now().strftime("%Y%m%d"))
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.codes:
        codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    else:
        with open(POOL_FILE, "r", encoding="utf-8") as f:
            uni = json.load(f)
        codes = [x["code"] for x in uni["indices"]]

    client = get_client()
    total_new, total_calls, failed = 0, 0, []
    for i, code in enumerate(codes, 1):
        try:
            n, c = pull_one(client, code, args.start, args.end, args.force)
            total_new += n
            total_calls += c
            print("[%d/%d] %s  +%d rows  (%d calls)" % (i, len(codes), code, n, c), flush=True)
        except Exception as e:  # noqa: BLE001
            failed.append(code)
            print("[%d/%d] %s  FAILED: %s" % (i, len(codes), code, str(e)[:120]), flush=True)
        time.sleep(0.3)

    print("\nDONE  new_rows=%d  calls=%d  failed=%s" % (total_new, total_calls, failed or "none"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
