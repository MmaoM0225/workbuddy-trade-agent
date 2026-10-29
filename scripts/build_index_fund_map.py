#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_index_fund_map.py - 建立「指数 → 可买基金」映射

思路（不是瞎猜基金代码，靠数据互相验证）：
  1. tushare fund_basic 拉全量场内/场外基金，按 benchmark 业绩基准字符串匹配指数名
  2. 候选基金逐个过 neodata fund_benchmark，拿它【真实跟踪指数代码】+ 年化跟踪误差
  3. 只保留 tracking_index_code 与目标指数完全一致的，再按跟踪误差从小到大选
  4. 附带 tushare 管理费/托管费/上市日期，便于比成本

输出：data/index_fund_map.json

用法：
  python scripts/build_index_fund_map.py            # 全池
  python scripts/build_index_fund_map.py --markets E
"""
import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_ETF = os.path.join(ROOT, "data", "index_fund_map_etf.json")
OUT_OF = os.path.join(ROOT, "data", "index_fund_map_of.json")
META = os.path.join(ROOT, "data", "warehouse", "meta")
POOL = os.path.join(ROOT, "data", "index_universe.json")

# 指数名 → 业绩基准里可能出现的关键词（宁可多匹配，后面靠 tracking_index_code 精确筛）
ALIAS = {
    "000510.SH": ["中证A500", "A500"],
    "H30269.CS": ["红利低波", "低波"],
    "N225.GZ": ["日经225"],
    "931790.CS": ["中韩半导体"],
    "000016.SH": ["上证50"],
    "000300.SH": ["沪深300"],
    "000905.SH": ["中证500"],
    "000852.SH": ["中证1000"],
    "399006.SZ": ["创业板"],
    "000688.SH": ["科创50", "科创板50"],
    "000922.SH": ["红利"],
    "000928.SH": ["800能源", "中证能源", "中证800能源"],
    "000929.SH": ["800材料", "中证材料", "中证800材料"],
    "000930.SH": ["800工业", "中证工业", "中证800工业"],
    "000931.SH": ["800可选", "中证可选", "中证800可选"],
    "000932.SH": ["800消费", "主要消费", "中证800消费"],
    "000933.SH": ["800医药", "医药卫生", "中证800医药"],
    "000934.SH": ["800金融", "金融地产", "中证800金融"],
    "000935.SH": ["800信息", "信息技术", "中证800信息"],
    "000936.SH": ["800电信", "电信业务", "中证800电信"],
    "000937.SH": ["800公用", "公用事业", "中证800公用"],
    "000986.SH": ["全指能源"],
    "000987.SH": ["全指材料"],
    "000990.SH": ["全指消费"],
    "000991.SH": ["全指医药"],
    "000993.SH": ["全指信息"],
    "399975.SZ": ["证券公司", "全指证券"],
    "399967.SZ": ["军工"],
    "000827.SH": ["环保"],
    "HSI.HK": ["恒生指数"],
    "HSCEI.HK": ["恒生中国企业", "恒生国企", "H股"],
    "HSTECH.HK": ["恒生科技"],
    "SPTR500N.GI": ["标普500"],
    "NDX.US": ["纳斯达克100", "纳指100"],
    "IXIC.US": ["纳斯达克"],
}


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
                                                      "clientInfo": {"name": "ifm", "version": "1"}}):
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
                if not txt:
                    return None
                try:
                    return json.loads(txt)
                except ValueError:
                    # 超长返回体被分片拼接，逐个 raw_decode
                    dec, idx, acc = json.JSONDecoder(), 0, []
                    txt_s = txt.strip()
                    while idx < len(txt_s):
                        obj, end = dec.raw_decode(txt_s, idx)
                        if isinstance(obj, list):
                            acc.extend([x for x in obj if isinstance(x, dict)])
                        elif isinstance(obj, dict):
                            acc.append(obj)
                        idx = end
                        while idx < len(txt_s) and txt_s[idx] in " \r\n\t,":
                            idx += 1
                    return acc
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


def pull_fund_basic(ts, market, page=2000):
    """分页拉取。场外基金上万只，一次性拉返回体会被截断。"""
    path = os.path.join(META, "fund_basic_%s.csv" % market)
    if os.path.exists(path) and os.path.getsize(path) > 10000:
        with open(path, encoding="utf-8") as f:
            return list(csv.DictReader(f))
    rows, offset = [], 0
    while True:
        got = ts.call("fund_basic", {
            "market": market, "limit": page, "offset": offset,
            "fields": ["ts_code", "name", "fund_type", "invest_type", "m_fee", "c_fee",
                       "benchmark", "found_date", "list_date", "issue_amount", "status"],
        }) or []
        if not got:
            break
        rows.extend(got)
        print("  offset=%d +%d" % (offset, len(got)), flush=True)
        if len(got) < page:
            break
        offset += page
        if offset > 50000:
            break
        time.sleep(0.2)
    if not rows:
        return []
    os.makedirs(META, exist_ok=True)
    keys = ["ts_code", "name", "fund_type", "invest_type", "m_fee", "c_fee",
            "benchmark", "found_date", "list_date", "issue_amount", "status"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--markets", default="E,O")
    args = ap.parse_args()

    with open(POOL, encoding="utf-8") as f:
        uni = json.load(f)["indices"]
    targets = [x for x in uni if x["group"] != "benchmark"]

    ts = client("tushare")
    nd = client("neodata")

    funds = []
    for mk in args.markets.split(","):
        try:
            got = pull_fund_basic(ts, mk.strip())
        except Exception as e:  # noqa: BLE001
            print("fund_basic market=%s 拉取失败：%s" % (mk, str(e)[:100]))
            p = os.path.join(META, "fund_basic_%s.csv" % mk.strip())
            if os.path.exists(p) and os.path.getsize(p) > 10000:
                with open(p, encoding="utf-8") as f:
                    got = list(csv.DictReader(f))
                print("  改用已落盘缓存 %d 条" % len(got))
            else:
                got = []
        print("fund_basic market=%s  %d 条" % (mk, len(got)))
        funds.extend(got)

    # 1. 按业绩基准关键词缩小候选
    EXCLUDE_TYPE = ("混合型", "债券型", "货币型", "灵活配置型", "QDII-混合")
    cand = {}
    for t in targets:
        code = t["code"]
        keys = ALIAS.get(code, [t["name"]])
        hits = []
        for f in funds:
            bm = (f.get("benchmark") or "") + " " + (f.get("name") or "")
            nm = f.get("name") or ""
            if not any(k in bm for k in keys):
                continue
            if f.get("status") not in (None, "", "L"):
                continue
            ft = f.get("invest_type") or f.get("fund_type") or ""
            if any(x in ft for x in EXCLUDE_TYPE):
                continue
            # 场外份额纪律：只要 A 类 + 人民币份额
            # 命名如 博时标普500ETF联接(QDII)-A-CNY / 华夏恒生ETF联接(QDII)-A-USD-现汇
            sm = re.search(r"-([ACDEIH])(?:-(?:CNY|USD))?(?:-(?:现汇|现钞))?$", nm)
            if sm and sm.group(1) != "A":
                continue                      # C/D/E/I/H 类不要
            if "USD" in nm.upper() or "美元" in nm:
                continue                      # 美元份额不要
            hits.append(f)
        # 候选太多时优先留成立早的（历史净值长、能回测），再留规模大的
        hits.sort(key=lambda x: (x.get("found_date") or "99999999"))
        cand[code] = hits[:12] + [h for h in sorted(hits[12:], key=lambda x: -float(x.get("issue_amount") or 0))][:6]
        cand[code] = cand[code][:18]
        print("%-14s %-14s 候选 %d" % (code, t["name"], len(hits)))

    # 2. 用 fund_benchmark 验证真实跟踪指数
    all_codes = []
    for hits in cand.values():
        all_codes.extend(f["ts_code"] for f in hits)
    fund_meta = {f["ts_code"]: f for f in funds}
    print("\n验证 %d 只基金的真实跟踪指数..." % len(all_codes))

    verified = {}
    for i in range(0, len(all_codes), 10):
        batch = all_codes[i:i + 10]
        try:
            res = nd.call("fund_benchmark", {
                "fund_codes": ",".join(batch), "limit": len(batch),
                "output_fields": "fund_code,fund_abbr,tracking_index_code,tracking_index_name,tracking_error",
            }) or []
        except Exception as e:  # noqa: BLE001
            print("  batch fail %s" % str(e)[:80])
            continue
        if isinstance(res, dict):
            res = res.get("result") or []
        print("  batch %d/%d -> %d 条" % (i // 10 + 1, (len(all_codes) + 9) // 10, len(res)))
        for r in res:
            if not isinstance(r, dict):
                continue
            fc = r.get("fund_code")
            ti = r.get("tracking_index_code")
            te = None
            for t in (r.get("tracking_error") or []):
                if t.get("annualized_tracking_error_1y") is not None:
                    te = t["annualized_tracking_error_1y"]
            verified[fc] = {"idx": ti, "idx_name": r.get("tracking_index_name"), "te1y": te}
        time.sleep(0.3)

    # 3. 匹配 + 排序选优
    out = {}
    for t in targets:
        code = t["code"]
        ok = []
        for f in cand[code]:
            v = verified.get(f["ts_code"])
            if not v or v["idx"] != code:
                continue
            try:
                size = float(f.get("issue_amount") or 0)
            except (TypeError, ValueError):
                size = 0
            ok.append({
                "fund_code": f["ts_code"], "fund_name": f.get("name"),
                "m_fee": f.get("m_fee"), "c_fee": f.get("c_fee"),
                "list_date": f.get("list_date"), "found_date": f.get("found_date"),
                "tracking_error_1y": v["te1y"], "issue_amount": size,
            })
        ok.sort(key=lambda x: (x["tracking_error_1y"] if x["tracking_error_1y"] is not None else 99,
                               x.get("found_date") or "99999999"))
        out[code] = {
            "index_name": t["name"], "group": t["group"],
            "primary": ok[0] if ok else None,
            "candidates": ok[:4],
        }

    out_path = OUT_OF if "O" in args.markets else OUT_ETF
    result = {"version": "v1.0", "updated": "2026-10-28",
              "market": args.markets,
              "note": "primary 为跟踪误差最小者；tracking_error_1y 单位 %，来自 neodata fund_benchmark",
              "map": out}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n%-14s %-14s %-12s %-24s %7s %7s" % ("指数", "名称", "基金代码", "基金名称", "跟踪误差", "管理费"))
    print("-" * 88)
    miss = []
    for t in targets:
        m = out[t["code"]]
        p = m["primary"]
        if not p:
            miss.append(t["name"])
            print("%-14s %-14s %-12s %-24s %7s %7s" % (t["code"], t["name"], "-", "无匹配基金", "-", "-"))
        else:
            print("%-14s %-14s %-12s %-24s %6s%% %6s%%" % (
                t["code"], t["name"], p["fund_code"], (p["fund_name"] or "")[:22],
                p["tracking_error_1y"], p["m_fee"]))
    if miss:
        print("\n无基金覆盖：%s" % "、".join(miss))
    print("\n写入 %s" % out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
