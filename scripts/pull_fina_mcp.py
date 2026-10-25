#!/usr/bin/env python3
"""直连 tushare MCP 拉取 2026 中报财务指标（剩余 162 批），结果落盘不进上下文。"""
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FINA_DIR = os.path.join(ROOT, "data", "warehouse", "fina")
RAW_DIR = os.path.join(FINA_DIR, "_raw_h1")
OUT_CSV = os.path.join(FINA_DIR, "h1_all.csv")
FIELDS = ["ts_code", "roe", "grossprofit_margin", "netprofit_margin", "tr_yoy"]
BATCH_FILES = ["h1_batches_1.txt", "h1_batches_2.txt", "h1_batches_4.txt",
               "h1_batches_5.txt", "h1_batches_6.txt", "h1_batches_7.txt"]


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
                return resp.read().decode("utf-8"), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")

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

    def notify(self, method):
        self._post({"jsonrpc": "2.0", "method": method})

    def initialize(self):
        err = None
        for ver in ("2025-06-18", "2025-03-26", "2024-11-05"):
            try:
                r = self.request("initialize", {"protocolVersion": ver, "capabilities": {},
                                                "clientInfo": {"name": "fina-puller", "version": "1.0"}})
                if "error" in r:
                    err = r["error"]
                    continue
                self.notify("notifications/initialized")
                return r
            except Exception as e:
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
                    raise RuntimeError(f"tool isError: {str(result)[:300]}")
                text = "".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
                return json.loads(text) if text else []
            except Exception as e:
                last = e
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"call_tool {name} failed after {retries}: {last}")


def find_client():
    cfg = json.loads(os.environ["CODEBUDDY_MCP_CONFIG"])
    servers = cfg.get("mcpServers", {})
    for key in ("tushare", "tushareMcp"):
        srv = servers.get(key)
        if not srv or "url" not in srv:
            continue
        client = McpClient(srv["url"], srv.get("headers", {}))
        client.initialize()
        tools = client.request("tools/list", {})
        names = [t.get("name") for t in tools.get("result", {}).get("tools", [])]
        if "fina_indicator" in names:
            print(f"MCP server '{key}' ok, {len(names)} tools", flush=True)
            return client
    raise RuntimeError("no tushare MCP server exposing fina_indicator")


def load_batches():
    batches = []
    for fn in BATCH_FILES:
        p = os.path.join(FINA_DIR, fn)
        if not os.path.exists(p):
            continue
        for line in open(p, encoding="utf-8"):
            codes = [c.strip() for c in line.strip().split(",") if c.strip()]
            if codes:
                batches.append(codes)
    return batches


def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    batches = load_batches()
    print(f"total batches: {len(batches)}, stocks: {sum(len(b) for b in batches)}", flush=True)
    client = find_client()

    done = 0
    for i, codes in enumerate(batches):
        raw_path = os.path.join(RAW_DIR, f"b{i}.json")
        if os.path.exists(raw_path):
            done += 1
            continue
        rows = client.call_tool("fina_indicator", {"ts_code": ",".join(codes),
                                                   "period": "20260630", "fields": FIELDS})
        with open(raw_path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False)
        done += 1
        if (i + 1) % 10 == 0:
            print(f"progress {i+1}/{len(batches)}", flush=True)
    print(f"fetched batches: {done}", flush=True)

    # merge: dedupe by ts_code keeping last occurrence
    merged = {}
    for i in range(len(batches)):
        raw_path = os.path.join(RAW_DIR, f"b{i}.json")
        if not os.path.exists(raw_path):
            continue
        for r in json.load(open(raw_path, encoding="utf-8")):
            code = r.get("ts_code")
            if not code:
                continue
            merged[code] = r
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(FIELDS)
        for code, r in merged.items():
            w.writerow([code] + ["" if r.get(k) is None else r.get(k) for k in FIELDS[1:]])
    print(f"h1_all.csv stocks: {len(merged)} / requested {sum(len(b) for b in batches)}", flush=True)


if __name__ == "__main__":
    main()
