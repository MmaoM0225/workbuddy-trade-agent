#!/usr/bin/env python3
"""研究员排雷取证（逐只版）：balancesheet / stk_holdertrade / fina_audit。
实测这三个接口不支持多 ts_code 批量，必须逐只调用。限速 0.45s。
"""
import csv
import json
import os
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WH = os.path.join(ROOT, "data", "warehouse")
OUT_DIR = os.path.join(WH, "research")
POOL = os.path.join(ROOT, "test", "state", "pool.json")
TOP_N = 60
THROTTLE = 0.45


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
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
                return resp.read().decode("utf-8"), resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")

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
        for ver in ("2025-06-18", "2025-03-26", "2024-11-05"):
            r = self.request("initialize", {"protocolVersion": ver, "capabilities": {},
                                            "clientInfo": {"name": "research", "version": "1.0"}})
            if "error" not in r:
                self.notify("notifications/initialized")
                return
        raise RuntimeError("initialize failed")

    def call_tool(self, name, arguments, retries=5):
        last = None
        for attempt in range(retries):
            try:
                r = self.request("tools/call", {"name": name, "arguments": arguments})
                if "error" in r:
                    raise RuntimeError(str(r["error"]))
                result = r.get("result", {})
                if result.get("isError"):
                    msg = str(result)
                    if "频率超限" in msg or "200次/分钟" in msg:
                        print("  rate limit, sleep 65s", flush=True)
                        time.sleep(65)
                        continue
                    raise RuntimeError(msg[:200])
                text = "".join(c.get("text", "") for c in result.get("content", [])
                               if c.get("type") == "text")
                return json.loads(text) if text else []
            except Exception as e:
                last = e
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"{name} failed: {last}")


def find_client():
    cfg = json.loads(os.environ["CODEBUDDY_MCP_CONFIG"])
    for key in ("tushare", "tushareMcp"):
        srv = cfg.get("mcpServers", {}).get(key)
        if srv and "url" in srv:
            c = McpClient(srv["url"], srv.get("headers", {}))
            c.initialize()
            return c
    raise RuntimeError("no tushare MCP")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    pool = json.load(open(POOL, encoding="utf-8"))
    codes = [s["code"] for s in pool["stocks"][:TOP_N]]
    print(f"codes: {len(codes)}", flush=True)
    c = find_client()

    gw_rows, red_rows, au_rows = [], [], []
    for i, code in enumerate(codes, 1):
        # 1) goodwill (latest period in window)
        try:
            rows = c.call_tool("balancesheet", {
                "ts_code": code, "start_date": "20250101", "end_date": "20261023",
                "fields": ["ts_code", "end_date", "goodwill", "total_hldr_eqy_exc_min_int"]})
            rows = [r for r in rows if r.get("end_date")]
            rows.sort(key=lambda r: r["end_date"], reverse=True)
            if rows:
                gw_rows.append(rows[0])
        except Exception as e:
            print(f"  {code} goodwill ERR {str(e)[:60]}", flush=True)
        time.sleep(THROTTLE)

        # 2) holder trade, last 3 months
        try:
            rows = c.call_tool("stk_holdertrade", {
                "ts_code": code, "start_date": "20260725", "end_date": "20261023",
                "fields": ["ts_code", "ann_date", "in_de", "change_vol"]})
            dec = [r for r in rows if r.get("in_de") == "DE"]
            vol = 0.0
            for r in dec:
                try:
                    vol += abs(float(r.get("change_vol") or 0))
                except ValueError:
                    pass
            red_rows.append({"ts_code": code, "dec_cnt": len(dec), "dec_vol": vol})
        except Exception as e:
            print(f"  {code} holdertrade ERR {str(e)[:60]}", flush=True)
        time.sleep(THROTTLE)

        # 3) audit opinion (latest)
        try:
            rows = c.call_tool("fina_audit", {
                "ts_code": code, "fields": ["ts_code", "end_date", "audit_result"]})
            rows = [r for r in rows if r.get("end_date")]
            rows.sort(key=lambda r: r["end_date"], reverse=True)
            if rows:
                au_rows.append(rows[0])
        except Exception as e:
            print(f"  {code} audit ERR {str(e)[:60]}", flush=True)
        time.sleep(THROTTLE)

        if i % 10 == 0:
            print(f"progress {i}/{len(codes)} (gw={len(gw_rows)} red={len(red_rows)} au={len(au_rows)})", flush=True)

    with open(os.path.join(OUT_DIR, "goodwill.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts_code", "end_date", "goodwill", "equity"])
        for r in gw_rows:
            w.writerow([r.get("ts_code"), r.get("end_date"), r.get("goodwill"),
                        r.get("total_hldr_eqy_exc_min_int")])
    with open(os.path.join(OUT_DIR, "reduction.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts_code", "dec_cnt", "dec_vol"])
        for r in red_rows:
            w.writerow([r["ts_code"], r["dec_cnt"], r["dec_vol"]])
    with open(os.path.join(OUT_DIR, "audit.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ts_code", "end_date", "audit_result"])
        for r in au_rows:
            w.writerow([r.get("ts_code"), r.get("end_date"), r.get("audit_result")])

    print(f"done: goodwill={len(gw_rows)} reduction={len(red_rows)} audit={len(au_rows)}", flush=True)


if __name__ == "__main__":
    main()
