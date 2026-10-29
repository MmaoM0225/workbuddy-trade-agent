#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pull_index_valuation_ext.py - 外部源补指数估值（neodata 覆盖不到的市场）

## 为什么需要这个脚本

neodata index_valuation 只支持 A股 / 港股 / 美股主要指数。日本、印度在
neodata / tushare / westock 都没有 PE/PB 序列（2026-10-29 已穷举）。
越南三个市场都没有免费源，已撤出定投池。本脚本把能拿到的补进来。

## 当前覆盖

| 标的 | 代码 | 源 | 频率 | 取哪一列 |
|---|---|---|---|---|
| 印度NIFTY50 | NIFTY50.NS | downstox.com（聚合 NSE 官方读数） | 月度 | PE / PB / 股息率 |
| 日经225 | N225.GZ | JPX 官方《市場別 加権平均PER・PBR》月报 | 月度 | 加权平均 PER / PBR |

### 日经225 为什么要用「主板加权PER」代理

日经官网 indexes.nikkei.co.jp 只有点位，**连 PER 字段都没有**；Nikkei 的日经225 估值
只在付费终端（QUICK/ Bloomberg）有。JPX 的月报有「プライム市場 総合」的**加权平均 PER**，
即 Σ总市值 ÷ Σ净利润 —— 这个算法等于 TOPIX 的 PE，是日本主板的真估值，但不是日经225
指数自身的 PE（日经是价格加权、科技权重高）。

用户 2026-10-29 拍板：接受这个代理，保留「日经225」名义。所以：
  - 估值分位讲的是「日本主板」，买卖载体是日经225 联接 020712.OF
  - 报告里该行会打「主板PER代理」标签，不许当成日经225 自己的 PE

## 月度 → 日度

上游都是月度读数，但下游 index_valuation_signal.build_broad 按"行数"算滚动分位
（window_days≈1250 行）。所以这里做**前向填充**：按 A股交易日历把每月读数铺满，
使 1250 行 ≈ 5 年，分位口径与日度序列一致。原始月度序列另存一份供审计。

## 失败处理

月度数据，晚一天无影响，所以网络失败**不返回非 0**，只打 WARN 并保留旧文件。
真正的数据缺失由 index_valuation_signal 的 missing 列表报出来。

用法：
  python scripts/pull_index_valuation_ext.py            # 全员增量
  python scripts/pull_index_valuation_ext.py --code N225.GZ
"""
import argparse
import csv
import json
import os
import re
import sys
import urllib.request
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WD = os.path.join(ROOT, "data", "warehouse", "index_valuation")
RAW = os.path.join(ROOT, "data", "warehouse", "index_valuation_ext")
JPX_CACHE = os.path.join(RAW, "jpx_cache")
HEADER = ("trade_date,pe_ttm,pe_ttm_ex_neg,pb_lf,pb_mrq,"
          "dividend_ratio,total_mv,index_nc,loss_nc")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0 Safari/537.36")
JPX_PAGE = "https://www.jpx.co.jp/markets/statistics-equities/misc/04.html"


def fetch(url, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 数据源实现

def src_downstox(spec):
    """downstox 月度 CSV：# 注释 + 'Month,PE,PB,DividendYield'，1999-01 起。"""
    text = fetch(spec["url"]).decode("utf-8", "replace")
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        p = [x.strip() for x in line.split(",")]
        if len(p) < 4 or not p[0][:4].isdigit():
            continue
        ym = p[0][:7]
        if len(ym) != 7:
            continue
        out.append((ym, _f(p[1]), _f(p[2]), _f(p[3])))
    out.sort(key=lambda x: x[0])
    return out


def jpx_links():
    html = fetch(JPX_PAGE).decode("utf-8", "replace")
    pairs = re.findall(
        r'href="(/markets/statistics-equities/misc/[^"]+/perpbr(\d{6})\.xlsx)"', html)
    seen = {}
    for path, ym in pairs:
        seen[ym] = "https://www.jpx.co.jp" + path
    return [(ym, seen[ym]) for ym in sorted(seen)]


def _num(v):
    """JPX 老文件把数值存成公式串 '=17.2'，data_only=True 会读出 None，这里兼容两种。"""
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().lstrip("=").strip()
        try:
            return float(s)
        except ValueError:
            return None
    return None


# 2022-04 东证改制：市场一部 → プライム市場。估值序列需要跨改制连续，故两者等价处理。
JPX_PRIME_NAMES = ("プライム市場", "市場一部")


def _jpx_row(ws):
    """在「規模別・業種別（連結）」里找主板総合那一行，返回 (month, pe_raw, pb_raw)。"""
    for row in ws.iter_rows(min_row=1, max_row=min(400, ws.max_row), values_only=True):
        if len(row) < 12:
            continue
        a, b, d = row[0], row[1], row[3]
        if not isinstance(a, str) or not re.match(r"^\d{4}/\d{2}$", a.strip()):
            continue
        if b not in JPX_PRIME_NAMES or d != "総合":
            continue
        return a.strip().replace("/", "-"), row[10], row[11]
    return None


def parse_jpx_book(path):
    """返回 (YYYY-MM, 加权平均PER, 加权平均PBR) —— 取主板「総合」（改制前为市场一部）。

    两级读取：先 data_only=True 拿缓存值；拿不到再 data_only=False 解 '=17.2' 这样的
    公式串（JPX 老文件普遍这么存，缓存值缺失）。
    """
    import openpyxl
    for data_only in (True, False):
        wb = openpyxl.load_workbook(path, data_only=data_only, read_only=True)
        try:
            got = _jpx_row(wb["規模別・業種別（連結）"])
        finally:
            wb.close()
        if not got:
            return None
        month, pe_raw, pb_raw = got
        pe, pb = _num(pe_raw), _num(pb_raw)
        if pe is not None:
            return month, pe, pb
    return month, None, None


def _dl(url, path):
    try:
        raw = fetch(url, timeout=60)
        with open(path, "wb") as f:
            f.write(raw)
        return True
    except Exception as e:  # noqa: BLE001
        print("    WARN 下载失败 %s：%s" % (os.path.basename(path), str(e)[:80]))
        return False


def src_jpx_prime(spec):
    """JPX 月报：每期一个 xlsx，抓页面上的全部月份链接，本地缓存后逐期解析。

    单文件约 12 秒（JPX 限速），串行跑 82 期要十几分钟，所以缺的期数并发预取。
    已缓存的直接跳过，中断后重跑可续。
    """
    from concurrent.futures import ThreadPoolExecutor

    os.makedirs(JPX_CACHE, exist_ok=True)
    links = jpx_links()
    miss = []
    for ym, url in links:
        path = os.path.join(JPX_CACHE, "perpbr%s.xlsx" % ym)
        if not (os.path.exists(path) and os.path.getsize(path) > 5000):
            miss.append((url, path))
    if miss:
        print("    预取 %d 期（并发 6）…" % len(miss))
        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(lambda t: _dl(*t), miss))

    out = []
    for ym, url in links:
        path = os.path.join(JPX_CACHE, "perpbr%s.xlsx" % ym)
        if not os.path.exists(path):
            continue
        try:
            got = parse_jpx_book(path)
        except Exception as e:  # noqa: BLE001
            print("    WARN %s 解析失败：%s" % (ym, str(e)[:80]))
            continue
        if got:
            out.append((got[0], got[1], got[2], None))
    out.sort(key=lambda x: x[0])
    return out


PROVIDERS = {"downstox": src_downstox, "jpx_prime": src_jpx_prime}

SOURCES = [
    {
        "code": "NIFTY50.NS",
        "name": "印度NIFTY50",
        "provider": "downstox",
        "url": "https://downstox.com/api/index-pe/nifty-50/download",
        "credit": "Downstox https://downstox.com/nifty-pe/nifty-50 （上游 NSE 官方读数）",
    },
    {
        "code": "N225.GZ",
        "name": "日经225（主板加权PER代理）",
        "provider": "jpx_prime",
        "credit": "JPX《市場別 PER・PBR》月报 プライム市場・総合・加权平均（≈TOPIX 口径）",
    },
]


# ---------------------------------------------------------------- 月度 → 日度

def trading_days():
    """用 A股沪深300 的已有估值序列当交易日历（本地，无网络）。"""
    p = os.path.join(WD, "000300.SH.csv")
    if not os.path.exists(p):
        return []
    ds = []
    with open(p, encoding="utf-8") as f:
        next(f, None)
        for line in f:
            if line.strip():
                ds.append(line.split(",")[0])
    return ds


def build_daily(monthly, days):
    """月度读数前向填充到日度。返回 {trade_date: (pe, pb, dy)}。"""
    if not monthly:
        return {}
    out, i, cur = {}, 0, None
    for d in days:
        ym = d[:4] + "-" + d[4:6]
        while i < len(monthly) and monthly[i][0] <= ym:
            cur = monthly[i]
            i += 1
        if cur:
            out[d] = (cur[1], cur[2], cur[3])
    return out


def _s(v):
    return "" if v is None else ("%g" % v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", default="", help="只跑某个代码，缺省全跑")
    a = ap.parse_args()

    os.makedirs(RAW, exist_ok=True)
    os.makedirs(WD, exist_ok=True)
    days = trading_days()
    if not days:
        print("FAILED 找不到交易日历 data/warehouse/index_valuation/000300.SH.csv")
        return 1

    touched = []
    for spec in SOURCES:
        if a.code and spec["code"] != a.code:
            continue
        code = spec["code"]
        try:
            monthly = PROVIDERS[spec["provider"]](spec)
            monthly = [r for r in monthly if r[1] is not None]
            if len(monthly) < 60:
                raise RuntimeError("只拿到 %d 条可用月度读数" % len(monthly))
        except Exception as e:  # noqa: BLE001
            print("WARN %s 拉取失败，保留旧文件：%s" % (code, str(e)[:160]))
            continue

        raw_path = os.path.join(RAW, code + "_monthly.csv")
        with open(raw_path, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["month", "pe", "pb", "dividend_yield"])
            w.writerows(monthly)

        daily = build_daily(monthly, days)
        path = os.path.join(WD, code + ".csv")
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(HEADER + "\n")
            for d in sorted(daily):
                pe, pb, dy = daily[d]
                f.write("%s,%s,%s,%s,%s,%s,,,\n"
                        % (d, _s(pe), _s(pe), _s(pb), _s(pb), _s(dy)))

        touched.append(code)
        last = monthly[-1]
        print("%s <- %s  月度 %d 条（%s..%s） 日度 %d 行  最新 %s PE=%s PB=%s"
              % (code, spec["name"], len(monthly), monthly[0][0], last[0],
                 len(daily), last[0], last[1], last[2]))
        print("    源：%s" % spec["credit"])

    meta = os.path.join(RAW, "last_update.json")
    try:
        old = json.load(open(meta, encoding="utf-8")) if os.path.exists(meta) else {}
    except (ValueError, OSError):
        old = {}
    old[datetime.now().strftime("%Y-%m-%d %H:%M")] = touched
    json.dump(old, open(meta, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
