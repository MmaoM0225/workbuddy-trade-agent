#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""probe_index_codes.py - 探测 neodata index_valuation 支持哪些指数代码（只读，不落盘）

用途：为「扩充国内/国外主流宽基」找可用估值源。对每个候选代码取最近 5 条，
有返回 = 支持；空 = 不支持（历史上标普500原始代码、日经、中证2000 都是空的）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "scripts"))
from pull_index_valuation import get_client, parse_result  # noqa: E402

FIELDS = "index_code,index_abbr,trading_day,pe_ttm,pb_lf,dividend_ratio"

CANDIDATES = [
    # ---- 国内主流宽基 ----
    ("000010.SH", "上证180"),
    ("000903.SH", "中证100"),
    ("000906.SH", "中证800"),
    ("000985.SH", "中证全指"),
    ("399001.SZ", "深证成指"),
    ("399673.SZ", "创业板50"),
    ("399303.SZ", "国证2000"),
    ("399102.SZ", "创业板综"),
    ("000698.SH", "科创100"),
    ("899050.BJ", "北证50"),
    ("932000.CSI", "中证2000"),
    ("930050.CSI", "中证A50"),
    ("000009.SH", "上证380"),
    ("000852.SH", "中证1000(核对)"),
    # ---- 国外主流宽基 ----
    ("DJI.GI", "道琼斯工业"),
    ("GDAXI.GI", "德国DAX"),
    ("FTSE.GI", "英国富时100"),
    ("FCHI.GI", "法国CAC40"),
    ("KOSPI.GI", "韩国综合"),
    ("TWSE.GI", "台湾加权"),
    ("RUT.GI", "罗素2000"),
    ("SPX.GI", "标普500(替代代码)"),
    ("HSI.HK", "恒生指数(核对)"),
    ("HSCEI.HK", "恒生国企(核对)"),
    ("IXIC.US", "纳斯达克综合(核对)"),
]


def main():
    c = get_client("neodata")
    ok, bad = [], []
    for code, name in CANDIDATES:
        try:
            text = c.call_tool("index_valuation", {
                "index_codes": code, "start_date": "20260801", "end_date": "20261027",
                "limit": 5, "output_fields": FIELDS,
            })
            rows = parse_result(text)
        except Exception as e:  # noqa: BLE001
            print("%-12s %-16s ERROR %s" % (code, name, str(e)[:80]))
            bad.append((code, name, "err"))
            continue
        if rows:
            last = rows[-1]
            print("%-12s %-16s OK   %s  pe=%s pb=%s  (%d 条)"
                  % (code, name, last.get("trading_day"), last.get("pe_ttm"),
                     last.get("pb_lf"), len(rows)))
            ok.append(code)
        else:
            print("%-12s %-16s EMPTY" % (code, name))
            bad.append((code, name, "empty"))
    print("\nOK=%d  FAIL=%d" % (len(ok), len(bad)))
    print("可用:", " ".join(ok))


if __name__ == "__main__":
    main()
