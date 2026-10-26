#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_daily_mcp.py - 数据员采集脚本（MCP 直连，落盘不进上下文）

按「每日数据员」采集清单生成 data/daily_<date>/ 下 9 个文件：
  indices.json / market_overview.json / sector_ranking.json / news.json /
  hot_news.json / hot_board.json / dragon_tiger.json / northbound.json / meta.json

用法：
  python scripts/fetch_daily_mcp.py [--date YYYYMMDD] [--force]

设计原则：
  - 大返回体（market_overview / sector_ranking / top_list）一律本地聚合后再写盘
  - 不用 data_hot 回看历史（实时榜），历史补跑在 meta.notes 标注时点偏差
  - 字段缺失显式记录，不猜测补数
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CST = timezone(timedelta(hours=8))

INDEX_LIST = [
    ("000001.SH", "上证指数"),
    ("399001.SZ", "深证成指"),
    ("399006.SZ", "创业板指"),
    ("000300.SH", "沪深300"),
    ("000905.SH", "中证500"),
]


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
            raise RuntimeError("HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:200]))

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
                                            "clientInfo": {"name": "data-officer", "version": "1.0"}})
            if "error" not in r:
                self.notify("notifications/initialized")
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
                return json.loads(text) if text else None
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError("%s failed: %s" % (name, last))


def get_client(key):
    cfg = json.loads(os.environ["CODEBUDDY_MCP_CONFIG"])
    srv = cfg["mcpServers"][key]
    c = McpClient(srv["url"], srv.get("headers", {}))
    c.initialize()
    return c


def to_cst(ts):
    try:
        return datetime.fromtimestamp(int(ts), CST).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def strip_comment(txt):
    if not isinstance(txt, str):
        return txt
    # 去掉 HTML 注释与【】标题前缀
    out = []
    depth = 0
    for ch in txt:
        if txt.startswith("<!--", len(out)):
            pass
        out.append(ch)
    s = txt
    while "<!--" in s:
        i = s.index("<!--")
        j = s.find("-->", i)
        s = s[:i] + (s[j + 3:] if j != -1 else "")
    return s.strip()


def unwrap(resp, label, notes):
    """westock 统一 {ok, data} 结构。"""
    if not isinstance(resp, dict):
        notes.append("%s: 返回非预期结构 %s" % (label, type(resp).__name__))
        return None
    if resp.get("ok") is False:
        notes.append("%s: ok=false" % label)
        return None
    return resp.get("data")


def fetch_indices(tu, date, notes):
    rows = []
    for code, name in INDEX_LIST:
        try:
            r = tu.call_tool("index_daily", {"ts_code": code, "trade_date": date})
            if isinstance(r, dict):
                r = r.get("items") or r.get("data") or []
            r = [x for x in (r or []) if x.get("trade_date")]
            if not r:
                start = (datetime.strptime(date, "%Y%m%d") - timedelta(days=7)).strftime("%Y%m%d")
                r = tu.call_tool("index_daily", {"ts_code": code, "start_date": start, "end_date": date})
                r = [x for x in (r or []) if x.get("trade_date")]
                r.sort(key=lambda x: x["trade_date"], reverse=True)
                if r:
                    notes.append("%s 当日无数据，回退取 %s" % (name, r[0]["trade_date"]))
            if not r:
                notes.append("%s: 无数据" % name)
                continue
            d = r[0]
            rows.append({
                "ts_code": code, "name": name, "trade_date": d.get("trade_date"),
                "close": d.get("close"), "open": d.get("open"),
                "high": d.get("high"), "low": d.get("low"),
                "pre_close": d.get("pre_close"), "change": d.get("change"),
                "pct_chg": d.get("pct_chg"), "vol": d.get("vol"), "amount": d.get("amount"),
            })
        except Exception as e:  # noqa: BLE001
            notes.append("%s: %s" % (name, str(e)[:80]))
        time.sleep(0.3)
    return rows


def fetch_market_overview(ws, date, notes):
    ymd = "%s-%s-%s" % (date[:4], date[4:6], date[6:])
    data = unwrap(ws.call_tool("data_market_overview", {"date": ymd, "type": "all"}),
                  "market_overview", notes)
    dims = []
    for item in (data or []):
        if not isinstance(item, dict):
            continue
        row = item.get("row") or {}
        dim = {
            "type": item.get("type"), "desc": item.get("desc"),
            "group": item.get("group"), "row": row,
            "schema": item.get("schema"),
        }
        if not row:
            dim["missing"] = True
            notes.append("market_overview.%s row 为空" % item.get("type"))
        dims.append(dim)
    if not dims:
        notes.append("market_overview: 无维度数据")
    return {"date": ymd, "source": "westock", "mode": "all", "dimensions": dims}


def fetch_sector(ws, date, notes):
    ymd = "%s-%s-%s" % (date[:4], date[4:6], date[6:])
    data = unwrap(ws.call_tool("data_sector", {"mode": "ranking", "kind": "industry",
                                              "type": "changePct", "date": ymd}),
                  "sector_ranking", notes)
    rows = (data or {}).get("rows") or []
    if not rows:
        notes.append("sector_ranking: rows 为空")
        return {"date": ymd, "source": "westock", "top_gainers": [],
                "bottom_losers": [], "main_inflow_top10": []}

    def fmt(r):
        leader = r.get("leader") or {}
        return {
            "name": r.get("name"), "code": r.get("code"),
            "changePct": r.get("changePct"),
            "upCount": r.get("upCount"),
            "mainNetInflow_wan": r.get("mainNetInflow"),
            "mainNetInflow5d_wan": r.get("mainNetInflow5d"),
            "leader": ("%s(%s)" % (leader.get("name"), leader.get("changePct"))
                       if leader.get("name") else None),
        }

    by_chg = sorted(rows, key=lambda r: r.get("changePct") or 0, reverse=True)
    by_inflow = sorted(rows, key=lambda r: r.get("mainNetInflow") or 0, reverse=True)
    return {
        "date": ymd, "source": "westock",
        "sector_count": len(rows),
        "up_sectors": sum(1 for r in rows if (r.get("changePct") or 0) > 0),
        "top_gainers": [fmt(r) for r in by_chg[:15]],
        "bottom_losers": [fmt(r) for r in by_chg[-10:]],
        "main_inflow_top10": [fmt(r) for r in by_inflow[:10]],
    }


def fetch_news(ws, notes):
    data = unwrap(ws.call_tool("data_flash_news_search", {"keyword": "", "limit": 50}),
                  "news", notes)
    items = (data or {}).get("news_list") or []
    out = []
    for r in items:
        content = strip_comment(r.get("content") or "")
        labels = [x.get("label_name") for x in (r.get("label_list") or []) if x.get("label_name")]
        title = r.get("title") or content[:40]
        out.append({
            "id": r.get("id"), "title": title,
            "source": (r.get("source_media") or "").strip(),
            "publish_time": to_cst(r.get("publish_time")),
            "labels": labels,
            "digest": content[:100],
        })
    if not out:
        notes.append("news: 快讯为空")
    return {"source": "westock", "note": "flash_news 仅覆盖近24小时", "items": out}


def fetch_hot(ws, kind, limit, notes):
    data = unwrap(ws.call_tool("data_hot", {"kind": kind, "limit": limit}), "hot_%s" % kind, notes)
    rows = (data or {}).get("rankResult") or []
    items = []
    for r in rows:
        if kind == "news":
            items.append({"rank": r.get("rank"), "title": r.get("news_title"),
                          "source": r.get("source"), "publish_time": to_cst(r.get("publish_time"))})
        else:
            items.append({"rank": r.get("rank"), "name": r.get("name"),
                          "zdf": r.get("zdf"), "zxj": r.get("zxj"),
                          "rankdelta": r.get("rankdelta")})
    if not items:
        notes.append("hot_%s: 空" % kind)
    return {"source": "westock", "note": "实时榜不可回看历史",
            "rank_time": (data or {}).get("rankTime"), "items": items}


def fetch_dragon_tiger(tu, date, notes):
    try:
        rows = tu.call_tool("top_list", {"trade_date": date})
    except Exception as e:  # noqa: BLE001
        notes.append("dragon_tiger: %s" % str(e)[:100])
        return {"date": date, "source": "tushare", "total_records": 0,
                "unique_stocks": 0, "net_buy_top10": [], "net_sell_top10": []}
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("data") or []
    rows = [r for r in (rows or []) if r.get("ts_code")]
    # 同股票多记录取 |net_amount| 最大的一条
    best = {}
    for r in rows:
        try:
            amt = abs(float(r.get("net_amount") or 0))
        except (TypeError, ValueError):
            amt = 0.0
        cur = best.get(r["ts_code"])
        if cur is None or amt > cur[1]:
            best[r["ts_code"]] = (r, amt)
    uniq = [v[0] for v in best.values()]

    def fmt(r):
        try:
            yi = round(float(r.get("net_amount") or 0) / 10000.0, 2)
        except (TypeError, ValueError):
            yi = None
        return {"name": r.get("name"), "code": r.get("ts_code"),
                "net_amount_yi": yi, "reason": r.get("reason")}

    srt = sorted(uniq, key=lambda r: float(r.get("net_amount") or 0), reverse=True)
    return {
        "date": date, "source": "tushare",
        "total_records": len(rows), "unique_stocks": len(uniq),
        "net_buy_top10": [fmt(r) for r in srt[:10]],
        "net_sell_top10": [fmt(r) for r in srt[-10:]][::-1],
    }


def fetch_northbound(tu, date, notes):
    try:
        r = tu.call_tool("moneyflow_hsgt", {"trade_date": date})
    except Exception as e:  # noqa: BLE001
        notes.append("northbound: %s" % str(e)[:100])
        return {"date": date, "source": "tushare", "north_money_yi": None}
    if isinstance(r, dict):
        r = r.get("items") or r.get("data") or []
    r = [x for x in (r or []) if x.get("trade_date")]
    if not r:
        notes.append("northbound: 当日无数据")
        return {"date": date, "source": "tushare", "north_money_yi": None}
    d = dict(r[0])
    try:
        d["north_money_yi"] = round(float(d.get("north_money") or 0) / 10000.0, 2)
    except (TypeError, ValueError):
        d["north_money_yi"] = None
    d["source"] = "tushare"
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=datetime.now(CST).strftime("%Y%m%d"))
    ap.add_argument("--force", action="store_true", help="非交易日也采集")
    args = ap.parse_args()
    date = args.date
    out_dir = os.path.join(ROOT, "data", "daily_" + date)

    notes = []
    tu = get_client("tushare")
    ws = get_client("westock-mcp")

    # 1. 交易日校验
    cal = tu.call_tool("trade_cal", {"start_date": date, "end_date": date, "exchange": "SSE"})
    if isinstance(cal, dict):
        cal = cal.get("items") or cal.get("data") or []
    is_open = bool(cal) and str((cal[0] or {}).get("is_open")) == "1"
    if not is_open and not args.force:
        print("SKIP non-trading-day %s" % date)
        skip_log = os.path.join(ROOT, "data", "skip_log.jsonl")
        with open(skip_log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"date": date, "agent": "数据员",
                                "reason": "non-trading-day"}, ensure_ascii=False) + "\n")
        return 0

    os.makedirs(out_dir, exist_ok=True)

    def dump(name, obj):
        p = os.path.join(out_dir, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
        print("  wrote %-24s %6d bytes" % (name, os.path.getsize(p)))

    print("[1/8] indices")
    indices = fetch_indices(tu, date, notes)
    dump("indices.json", indices)

    print("[2/8] market_overview")
    mo = fetch_market_overview(ws, date, notes)
    dump("market_overview.json", mo)

    print("[3/8] sector_ranking")
    sec = fetch_sector(ws, date, notes)
    dump("sector_ranking.json", sec)

    print("[4/8] news")
    news = fetch_news(ws, notes)
    dump("news.json", news)

    print("[5/8] hot_news")
    hot_news = fetch_hot(ws, "news", 20, notes)
    dump("hot_news.json", hot_news)

    print("[6/8] hot_board")
    hot_board = fetch_hot(ws, "board", 15, notes)
    dump("hot_board.json", hot_board)

    print("[7/8] dragon_tiger")
    dt = fetch_dragon_tiger(tu, date, notes)
    dump("dragon_tiger.json", dt)

    print("[8/8] northbound")
    nb = fetch_northbound(tu, date, notes)
    dump("northbound.json", nb)

    degraded = len(indices) < 4 or not mo.get("dimensions")
    if degraded:
        notes.append("[degraded] 核心文件缺失（indices=%d, overview_dims=%d）"
                     % (len(indices), len(mo.get("dimensions") or [])))

    meta = {
        "date": date,
        "fetched_at": datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"),
        "trading_day": is_open,
        "source_script": "scripts/fetch_daily_mcp.py",
        "sources": {"indices": "tushare/index_daily", "market_overview": "westock/data_market_overview",
                    "sector_ranking": "westock/data_sector", "news": "westock/data_flash_news_search",
                    "hot_news": "westock/data_hot", "hot_board": "westock/data_hot",
                    "dragon_tiger": "tushare/top_list", "northbound": "tushare/moneyflow_hsgt"},
        "record_counts": {
            "indices": len(indices),
            "market_overview_dimensions": len(mo.get("dimensions") or []),
            "sector_top_gainers": len(sec.get("top_gainers") or []),
            "sector_bottom_losers": len(sec.get("bottom_losers") or []),
            "news": len(news.get("items") or []),
            "hot_news": len(hot_news.get("items") or []),
            "hot_board": len(hot_board.get("items") or []),
            "dragon_tiger_unique": dt.get("unique_stocks"),
            "northbound": 1 if nb.get("north_money_yi") is not None else 0,
        },
        "degraded": degraded,
        "notes": notes,
    }
    dump("meta.json", meta)
    print("DONE degraded=%s notes=%d" % (degraded, len(notes)))
    for n in notes[:10]:
        print("  note:", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
