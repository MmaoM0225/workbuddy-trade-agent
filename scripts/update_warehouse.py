#!/usr/bin/env python3
"""全市场数据仓库增量更新（选股师每周六 23:00 第一步执行）。

- daily: 最近 5 个交易日（已存在则跳过）
- weekly: 最近 1 个交易周
- daily_basic: 最新交易日
- fina_indicator: 全市场三季报刷新（新披露的自动补入；限速 0.45s/批）
结果全部落 data/warehouse/，不进 Agent 上下文。
"""
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WH = os.path.join(ROOT, "data", "warehouse")
THROTTLE = 0.45


class McpClient:
    def __init__(self, url, headers):
        self.url, self.headers = url, dict(headers)
        self.headers["Content-Type"] = "application/json"
        self.headers["Accept"] = "application/json, text/event-stream"
        self.session_id, self._id = None, 0

    def _post(self, payload):
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode("utf-8"),
                                     headers=self.headers, method="POST")
        if self.session_id:
            req.add_header("Mcp-Session-Id", self.session_id)
        try:
            with urllib.request.urlopen(req, timeout=240) as resp:
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
        return self._parse(*self._post({"jsonrpc": "2.0", "id": self._id,
                                        "method": method, "params": params}))

    def notify(self, method):
        self._post({"jsonrpc": "2.0", "method": method})

    def initialize(self):
        for ver in ("2025-06-18", "2025-03-26", "2024-11-05"):
            r = self.request("initialize", {"protocolVersion": ver, "capabilities": {},
                                            "clientInfo": {"name": "wh-updater", "version": "1.0"}})
            if "error" not in r:
                self.notify("notifications/initialized")
                return
        raise RuntimeError("init failed")

    def call(self, name, args, retries=5):
        last = None
        for attempt in range(retries):
            try:
                r = self.request("tools/call", {"name": name, "arguments": args})
                if "error" in r:
                    raise RuntimeError(str(r["error"]))
                res = r.get("result", {})
                if res.get("isError"):
                    msg = str(res)
                    if "频率超限" in msg or "200次/分钟" in msg:
                        print("  rate limit, sleep 65s", flush=True)
                        time.sleep(65)
                        continue
                    raise RuntimeError(msg[:200])
                text = "".join(c.get("text", "") for c in res.get("content", [])
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


def read_csv(p):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--daily-only", action="store_true",
                    help="只增量更新 daily/*.csv（供数据员每日 23:00 调用，约 5 次 API）")
    args, _ = ap.parse_known_args()

    client = find_client()
    # 1. recent open dates
    cal = client.call("trade_cal", {"exchange": "SSE", "start_date": "20260801",
                                    "end_date": time.strftime("%Y%m%d")})
    opens = sorted([r["cal_date"] for r in cal if str(r.get("is_open")) == "1"], reverse=True)
    if not opens:
        print("no open dates"); return
    latest = opens[0]
    print(f"latest trading day: {latest}", flush=True)

    # 2. daily: last 5 trading days
    os.makedirs(os.path.join(WH, "daily"), exist_ok=True)
    for d in opens[:5]:
        p = os.path.join(WH, "daily", f"{d}.csv")
        if os.path.exists(p):
            continue
        rows = client.call("daily", {"trade_date": d,
                                     "fields": ["ts_code", "open", "high", "low", "close", "amount"]})
        with open(p, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ts_code", "open", "high", "low", "close", "amount"])
            for r in rows:
                w.writerow([r.get("ts_code"), r.get("open"), r.get("high"),
                            r.get("low"), r.get("close"), r.get("amount")])
        print(f"daily {d}: {len(rows)} rows", flush=True)
        time.sleep(THROTTLE)

    # 2b. daily-only 模式到此结束（数据员每日 23:00 用，供拥挤度/后续因子消费）
    if args.daily_only:
        meta_dir = os.path.join(WH, "meta")
        os.makedirs(meta_dir, exist_ok=True)
        summary = {"updated_at": time.strftime("%Y-%m-%d %H:%M"),
                   "latest_trading_day": latest, "mode": "daily-only"}
        with open(os.path.join(meta_dir, "last_daily_update.json"), "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print("warehouse daily-only done:", json.dumps(summary, ensure_ascii=False), flush=True)
        return

    # 3. weekly: latest week
    wpath = os.path.join(WH, "weekly", f"{latest}.csv")
    os.makedirs(os.path.join(WH, "weekly"), exist_ok=True)
    if not os.path.exists(wpath):
        rows = client.call("weekly", {"trade_date": latest, "fields": ["ts_code", "trade_date", "close"]})
        with open(wpath, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ts_code", "trade_date", "close"])
            for r in rows:
                w.writerow([r.get("ts_code"), r.get("trade_date"), r.get("close")])
        print(f"weekly {latest}: {len(rows)} rows", flush=True)
        time.sleep(THROTTLE)

    # 4. daily_basic latest
    bpath = os.path.join(WH, "daily_basic", f"{latest}.csv")
    os.makedirs(os.path.join(WH, "daily_basic"), exist_ok=True)
    if not os.path.exists(bpath):
        rows = client.call("daily_basic", {"trade_date": latest,
                                           "fields": ["ts_code", "close", "turnover_rate", "pe_ttm",
                                                      "pb", "ps_ttm", "total_mv", "circ_mv"]})
        with open(bpath, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ts_code", "close", "turnover_rate", "pe_ttm", "pb", "ps_ttm", "total_mv", "circ_mv"])
            for r in rows:
                w.writerow([r.get(k) for k in ["ts_code", "close", "turnover_rate", "pe_ttm",
                                               "pb", "ps_ttm", "total_mv", "circ_mv"]])
        print(f"daily_basic {latest}: {len(rows)} rows", flush=True)

    # 5. stock_basic + suspend refresh (weekly)
    basic_path = os.path.join(WH, "meta", "stock_basic.csv")
    if True:
        rows = client.call("stock_basic", {"list_status": "L",
                                           "fields": ["ts_code", "name", "industry", "list_date", "market"]})
        with open(basic_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ts_code", "name", "industry", "list_date", "market"])
            for r in rows:
                w.writerow([r.get("ts_code"), r.get("name"), r.get("industry"),
                            r.get("list_date"), r.get("market")])
        print(f"stock_basic: {len(rows)} rows", flush=True)
        time.sleep(THROTTLE)
    spath = os.path.join(WH, "meta", f"suspend_{latest}.csv")
    if not os.path.exists(spath):
        rows = client.call("suspend_d", {"trade_date": latest, "fields": ["ts_code", "suspend_type"]})
        codes = sorted({r.get("ts_code") for r in rows if r.get("ts_code")})
        with open(spath, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["ts_code"])
            for c in codes:
                w.writerow([c])
        print(f"suspend {latest}: {len(codes)}", flush=True)

    # 6. fina Q3 refresh for stocks missing Q3 (newly disclosed get filled)
    q3_path = os.path.join(WH, "fina", "q3_all.csv")
    have = set()
    if os.path.exists(q3_path):
        have = {r["ts_code"] for r in read_csv(q3_path)}
    all_codes = [r["ts_code"] for r in read_csv(basic_path)]
    todo = [c for c in all_codes if c not in have]
    print(f"fina Q3 refresh: {len(todo)} stocks pending", flush=True)
    batches = [todo[i:i + 25] for i in range(0, len(todo), 25)]
    new_rows = []
    for i, b in enumerate(batches, 1):
        try:
            rows = client.call("fina_indicator", {"ts_code": ",".join(b), "period": "20260930",
                                                  "fields": ["ts_code", "roe", "grossprofit_margin",
                                                             "netprofit_margin", "tr_yoy"]})
            uniq = {}
            for r in rows:
                uniq[r["ts_code"]] = r
            new_rows += list(uniq.values())
        except Exception as e:
            print(f"  fina batch {i} ERR {str(e)[:60]}", flush=True)
        time.sleep(THROTTLE)
        if i % 20 == 0:
            print(f"  fina progress {i}/{len(batches)} (+{len(new_rows)})", flush=True)

    if new_rows:
        mode = "a" if os.path.exists(q3_path) else "w"
        with open(q3_path, mode, newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if mode == "w":
                w.writerow(["ts_code", "roe", "grossprofit_margin", "netprofit_margin", "tr_yoy"])
            for r in new_rows:
                w.writerow([r.get("ts_code"), r.get("roe"), r.get("grossprofit_margin"),
                            r.get("netprofit_margin"), r.get("tr_yoy")])
    total_q3 = len(have) + len({r["ts_code"] for r in new_rows})
    print(f"fina Q3 total after refresh: {total_q3}", flush=True)

    summary = {"updated_at": time.strftime("%Y-%m-%d %H:%M"), "latest_trading_day": latest,
               "daily_days": opens[:5], "fina_q3_covered": total_q3,
               "fina_q3_new": len({r["ts_code"] for r in new_rows})}
    with open(os.path.join(WH, "meta", "last_update.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("warehouse update done:", json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
