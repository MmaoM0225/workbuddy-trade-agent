#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pull_sw_industry.py - 申万二级行业估值分位采集

为什么用申万板块而不是中证二级指数：
  neodata valuation 对申万行业板块（.PT）直接给出官方算好的 5 年分位
  （PE/PB/PS/股息率），比自算窗口更稳，且天然覆盖全部 134 个二级行业。

代码规律（已实测验证）：
  申万行业指数 801016.SI  →  板块 01801016.PT
  规则："0180" + index_code 前 6 位的后 4 位
  例：801016 → 0180+1016 = 01801016；801991 → 0180+1991 = 01801991

输出：data/warehouse/sw_industry/latest.json

用法：
  python scripts/pull_sw_industry.py
  python scripts/pull_sw_industry.py --level L1
"""
import argparse
import json
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "data", "warehouse", "sw_industry")


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
                                                      "clientInfo": {"name": "sw", "version": "1"}}):
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


def to_pt(index_code):
    """801016.SI → 01801016.PT（取前 6 位的后 4 位，前面补 0180）"""
    n = index_code.split(".")[0]
    if not n.startswith("801") or len(n) < 6:
        return None
    return "0180" + n[2:6] + ".PT"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--level", default="L2")
    args = ap.parse_args()

    ts, nd = client("tushare"), client("neodata")

    rows = ts.call("index_classify", {"src": "SW2021", "level": args.level}) or []
    print("申万 %s 行业 %d 个" % (args.level, len(rows)))

    targets = []
    for r in rows:
        if str(r.get("is_pub")) != "1":
            continue                        # 未发布的行业没有板块数据
        pt = to_pt(r["index_code"])
        if pt:
            targets.append({"pt": pt, "name": r["industry_name"],
                            "sw_code": r["index_code"], "industry_code": r.get("industry_code")})
    print("已发布可查 %d 个" % len(targets))

    out = {}
    for i in range(0, len(targets), 10):
        batch = targets[i:i + 10]
        try:
            res = nd.call("valuation", {
                "code": ",".join(x["pt"] for x in batch),
                "end_date": "20261027", "limit": 1,
            }) or []
        except Exception as e:  # noqa: BLE001
            print("  batch %d FAIL %s" % (i // 10, str(e)[:70]))
            continue
        if isinstance(res, dict):
            res = res.get("result") or []
        for r in res:
            h = (r.get("history") or [{}])[0]
            code = r.get("code")
            meta = next((x for x in batch if x["pt"] == code), {})
            if not h:
                continue
            out[code] = {
                "name": r.get("name") or meta.get("name"),
                "sw_code": meta.get("sw_code"),
                "date": h.get("date"),
                "pe_ttm": h.get("pe_ttm"),
                "pb_lf": h.get("pb_lf"),
                "ps_ttm": h.get("ps_ttm"),
                "dividend_yield_ttm": h.get("dividend_yield_ttm"),
                "pe_pct_5y": h.get("pe_percentile_5y"),
                "pb_pct_5y": h.get("pb_percentile_5y"),
                "ps_pct_5y": h.get("ps_percentile_5y"),
                "div_pct_5y": h.get("dividend_yield_percentile_5y"),
                "constituent_count": h.get("constituent_count"),
            }
        print("  batch %d/%d -> 累积 %d" % (i // 10 + 1, (len(targets) + 9) // 10, len(out)), flush=True)
        time.sleep(0.35)

    os.makedirs(OUT_DIR, exist_ok=True)

    def key_score(v):
        vals = [v["pb_pct_5y"], v["ps_pct_5y"]]
        vals = [x for x in vals if x is not None]
        return sum(vals) / len(vals) if vals else 999

    for v in out.values():
        v["score"] = round(key_score(v) * 100, 1)   # 原始是 0-1，转成 0-100
    with open(os.path.join(OUT_DIR, "latest.json"), "w", encoding="utf-8") as f:
        json.dump({"level": args.level, "as_of": "20261027", "count": len(out),
                   "map": out}, f, ensure_ascii=False, indent=2)

    print("\n%-14s %7s %7s %7s %7s %7s" % ("行业", "PB分位", "PS分位", "PE分位", "股息分位", "综合"))
    print("-" * 60)
    for v in sorted(out.values(), key=lambda x: x["score"])[:15]:
        print("%-14s %6.1f%% %6.1f%% %6.1f%% %6.1f%% %6.0f" % (
            v["name"][:12],
            (v["pb_pct_5y"] or 0) * 100, (v["ps_pct_5y"] or 0) * 100,
            (v["pe_pct_5y"] or 0) * 100, (v["div_pct_5y"] or 0) * 100, v["score"]))
    print("...(共 %d 个，最便宜的 15 个如上)" % len(out))
    print("\n写入 %s" % OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
