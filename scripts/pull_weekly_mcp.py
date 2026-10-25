#!/usr/bin/env python3
"""拉取全市场 A 股周线（20260817-20261023）并落盘 part1.csv。

数据源与 mcp__tushare__weekly 完全一致：直接用 Python 作为 MCP 客户端
调用 CODEBUDDY_MCP_CONFIG 中 tushare 服务端的 weekly 工具，避免把约
5.5 万行结果逐行转录进 Agent 上下文。仅输出计数信息，不打印行情数据。
"""
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "data", "warehouse", "weekly", "_raw")
OUT_CSV = os.path.join(ROOT, "data", "warehouse", "weekly", "part1.csv")
WEEK_DATES = [
    "20260821", "20260828", "20260904", "20260911", "20260918",
    "20260924", "20260930", "20261009", "20261016", "20261023",
]
FIELDS = ["ts_code", "trade_date", "close"]


class McpClient:
    def __init__(self, url, headers):
        self.url = url
        self.headers = dict(headers)
        self.headers["Content-Type"] = "application/json"
        self.headers["Accept"] = "application/json, text/event-stream"
        self.session_id = None
        self._id = 0

    def _post(self, payload):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.url, data=data, headers=self.headers, method="POST")
        if self.session_id:
            req.add_header("Mcp-Session-Id", self.session_id)
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
                raw = resp.read().decode("utf-8")
                ct = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:500]
            raise RuntimeError(f"HTTP {e.code}: {body}")
        return raw, ct

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
        raw, ct = self._post(
            {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        )
        return self._parse(raw, ct)

    def notify(self, method):
        self._post({"jsonrpc": "2.0", "method": method})

    def initialize(self):
        err = None
        for ver in ("2025-06-18", "2025-03-26", "2024-11-05"):
            try:
                r = self.request(
                    "initialize",
                    {
                        "protocolVersion": ver,
                        "capabilities": {},
                        "clientInfo": {"name": "weekly-puller", "version": "1.0"},
                    },
                )
                if "error" in r:
                    err = r["error"]
                    continue
                self.notify("notifications/initialized")
                return r
            except Exception as e:  # noqa: BLE001
                err = e
        raise RuntimeError(f"initialize failed: {err}")

    def call_tool(self, name, arguments, retries=3):
        last = None
        for attempt in range(retries):
            try:
                r = self.request("tools/call", {"name": name, "arguments": arguments})
                if "error" in r:
                    raise RuntimeError(f"tool error: {r['error']}")
                result = r.get("result", {})
                if result.get("isError"):
                    raise RuntimeError(f"tool isError: {result}")
                text = "".join(
                    c.get("text", "")
                    for c in result.get("content", [])
                    if c.get("type") == "text"
                )
                return json.loads(text)
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"call_tool {name} failed after {retries} tries: {last}")


def find_weekly_client():
    cfg = json.loads(os.environ["CODEBUDDY_MCP_CONFIG"])
    servers = cfg.get("mcpServers", {})
    for key in ("tushare", "tushareMcp"):
        if key not in servers:
            continue
        srv = servers[key]
        try:
            client = McpClient(srv["url"], srv["headers"])
            client.initialize()
            tools = client.request("tools/list", {})
            names = [t.get("name") for t in tools.get("result", {}).get("tools", [])]
            if "weekly" in names:
                print(f"using MCP server '{key}' ({len(names)} tools)")
                return client
            print(f"server '{key}' has no weekly tool")
        except Exception as e:  # noqa: BLE001
            print(f"server '{key}' failed: {e}")
    raise RuntimeError("no tushare MCP server exposing weekly tool")


def fetch_week(client, trade_date, force=False):
    path = os.path.join(RAW_DIR, f"weekly_{trade_date}.json")
    if os.path.exists(path) and not force:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), True
    rows = client.call_tool("weekly", {"trade_date": trade_date, "fields": FIELDS})
    os.makedirs(RAW_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False)
    return rows, False


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    client = find_weekly_client()

    if mode == "test":
        for code in ("000001.SZ", "600000.SH"):
            rows = client.call_tool(
                "weekly",
                {
                    "ts_code": code,
                    "start_date": "20260817",
                    "end_date": "20261023",
                    "fields": FIELDS,
                },
            )
            dates = sorted({r["trade_date"] for r in rows})
            print(f"probe {code}: {len(rows)} bars, dates={dates}")
        rows, cached = fetch_week(client, "20260821")
        counts = {}
        for r in rows:
            counts[r["trade_date"]] = counts.get(r["trade_date"], 0) + 1
        print(f"week 20260821: {len(rows)} rows (cached={cached}), dates={counts}")
        return

    total = 0
    for d in WEEK_DATES:
        rows, cached = fetch_week(client, d)
        dates = {r["trade_date"] for r in rows}
        if dates != {d}:
            raise RuntimeError(f"unexpected trade_dates for {d}: {sorted(dates)}")
        if len(rows) >= 6000:
            raise RuntimeError(f"{d} hit 6000-row cap: {len(rows)}")
        total += len(rows)
        print(f"{d}: {len(rows)} rows (cached={cached})")
    print(f"total rows: {total}")

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts_code", "trade_date", "close"])
        for d in WEEK_DATES:
            with open(os.path.join(RAW_DIR, f"weekly_{d}.json"), "r", encoding="utf-8") as rf:
                rows = json.load(rf)
            for r in rows:
                close = r.get("close")
                w.writerow(
                    [r.get("ts_code", ""), r.get("trade_date", ""), "" if close is None else close]
                )

    with open(OUT_CSV, "r", encoding="utf-8") as f:
        lines = f.read().splitlines()
    data_lines = lines[1:]
    print(f"part1.csv data rows: {len(data_lines)}")
    print(f"distinct trade_date: {len({l.split(',')[1] for l in data_lines})}")
    print(f"distinct ts_code: {len({l.split(',')[0] for l in data_lines})}")


if __name__ == "__main__":
    main()
