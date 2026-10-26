#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""拉取全市场历史财务（westock data_finance，带 InfoPublDate）→ 落盘供回测按时点回放。

输出：data/warehouse/fina/history.csv
字段：ts_code, end_date, pub_date, roe_ttm, net_margin, gross_margin, rev_yoy

只拉 income 表——ROE(TTM)/净利率/毛利率/营收同比 都在里面，无需 balance。
支持断点续传（已存在的 ts_code 跳过）。
"""
import csv
import json
import os
import sys
import time

sys.path.insert(0, r"E:/cashfree/agent/scripts")
from update_warehouse import McpClient  # noqa: E402

ROOT = r"E:\cashfree\agent"
WH = os.path.join(ROOT, "data", "warehouse")
OUT = os.path.join(WH, "fina", "history.csv")
BATCH = 30
PERIODS = 28          # 28 期 ≈ 7 年，覆盖 2019-2026
THROTTLE = 10.0    # 限频较严：10s/批约 6 次/分钟

HEADER = ["ts_code", "end_date", "pub_date", "roe_ttm", "net_margin", "gross_margin", "rev_yoy"]


def westock_code(ts_code):
    """600519.SH -> sh600519 ; 000001.SZ -> sz000001 ; .BJ 返回 None"""
    if ts_code.endswith(".SH"):
        return "sh" + ts_code[:6]
    if ts_code.endswith(".SZ"):
        return "sz" + ts_code[:6]
    return None


def fnum(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def main():
    cfg = json.loads(os.environ["CODEBUDDY_MCP_CONFIG"])
    srv = cfg["mcpServers"]["westock-mcp"]
    c = McpClient(srv["url"], srv.get("headers", {}))
    c.initialize()

    # universe: 全市场（含已拉过的跳过）
    basic_path = os.path.join(WH, "meta", "stock_basic.csv")
    with open(basic_path, encoding="utf-8-sig") as f:
        all_codes = [r["ts_code"] for r in csv.DictReader(f)]
    # 只拉回测会用到的主板非 ST（回调不覆盖北交所/双创，省一半调用）
    all_codes = [c for c in all_codes if not c.endswith(".BJ")
                 and c[:3] not in ("300", "301", "688", "689")]
    pairs = [(tc, westock_code(tc)) for tc in all_codes]
    pairs = [(tc, wc) for tc, wc in pairs if wc]
    print("total codes:", len(pairs), flush=True)

    done = set()
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8-sig") as f:
            done = {r["ts_code"] for r in csv.DictReader(f)}
        print("already have:", len(done), flush=True)

    todo = [(tc, wc) for tc, wc in pairs if tc not in done]
    print("to fetch:", len(todo), flush=True)

    new_file = not os.path.exists(OUT)
    f = open(OUT, "a", newline="", encoding="utf-8")
    w = csv.writer(f)
    if new_file:
        w.writerow(HEADER)

    ok = fail = rows_total = 0
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        codes = ",".join(wc for _, wc in chunk)
        try:
            r = c.request("tools/call", {"name": "data_finance",
                                         "arguments": {"codes": codes, "type": "income", "num": PERIODS}})
            txt = "".join(x.get("text", "") for x in r.get("result", {}).get("content", [])
                          if x.get("type") == "text")
            if not txt.startswith("{"):
                # 服务限频：等待后重试同一批
                print("  batch %d RATE-LIMITED (%s), sleep 90s" % (i // BATCH + 1, txt[:40]), flush=True)
                time.sleep(90)
                r = c.request("tools/call", {"name": "data_finance",
                                             "arguments": {"codes": codes, "type": "income", "num": PERIODS}})
                txt = "".join(x.get("text", "") for x in r.get("result", {}).get("content", [])
                              if x.get("type") == "text")
                if not txt.startswith("{"):
                    print("  batch %d STILL LIMITED, skip" % (i // BATCH + 1), flush=True)
                    fail += len(chunk)
                    continue
            d = json.loads(txt) if txt else {}
            data = (d.get("data") or {}).get("data") or {}
        except Exception as e:
            print("  batch %d ERROR %s" % (i // BATCH + 1, str(e)[:120]), flush=True)
            fail += len(chunk)
            time.sleep(1.5)
            continue

        for tc, wc in chunk:
            rows = data.get(wc) or []
            if not rows:
                fail += 1
                continue
            for x in rows:
                w.writerow([tc, x.get("EndDate"), (x.get("InfoPublDate") or "")[:10],
                            fnum(x.get("ROETTM")) if fnum(x.get("ROETTM")) is not None else fnum(x.get("ROE")),
                            fnum(x.get("NetProfitRatio")),
                            fnum(x.get("GrossIncomeRatio")),
                            fnum(x.get("OperatingRevenueGrowRate_Q"))])
                rows_total += 1
            ok += 1
        if (i // BATCH + 1) % 10 == 0:
            f.flush()
            print("  batch %d/%d  ok=%d fail=%d rows=%d" % (
                i // BATCH + 1, (len(todo) + BATCH - 1) // BATCH, ok, fail, rows_total), flush=True)
        time.sleep(THROTTLE)

    f.close()
    print("DONE ok=%d fail=%d rows=%d -> %s" % (ok, fail, rows_total, OUT), flush=True)


if __name__ == "__main__":
    main()
