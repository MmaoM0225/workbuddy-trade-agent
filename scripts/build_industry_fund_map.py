#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_industry_fund_map.py - 为申万二级行业自动匹配可买基金

难点：申万行业指数（801xxx.SI）与基金跟踪的指数（中证/国证系列）代码完全不同，
      不能像宽基那样靠 tracking_index_code 精确验证。只能靠语义匹配 + 分级标注。

做法：
  1. 行业名去「Ⅱ」作为精确关键词；匹配不到退到申万一级行业名作为宽泛关键词
  2. 在 tushare fund_basic（场外 .OF 池 + 场内 .SH/.SZ）的 name + benchmark 里搜
  3. 候选过 neodata fund_benchmark 拿真实 tracking_index_name + 年化跟踪误差
  4. 按「跟踪指数名与行业名的语义关系」定级：
       exact  跟踪指数名含该行业名       —— 基本就是同一个东西
       near   含行业名前 2-3 字或已人工指定的别名
       loose  只匹配到申万一级行业       —— 大概率是广谱行业基金，不是纯这个细分
       none   完全找不到
  5. 同级内按 (跟踪误差, 成立日期) 选优

输出：data/industry_fund_map.json

用法：
  python scripts/build_industry_fund_map.py
  python scripts/build_industry_fund_map.py --only 半导体,医疗器械
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
SW = os.path.join(ROOT, "data", "warehouse", "sw_industry", "latest.json")
META = os.path.join(ROOT, "data", "warehouse", "meta")
OUT = os.path.join(ROOT, "data", "industry_fund_map.json")

# 少数行业靠规则匹配不到，人工指定更贴切的搜索词
MANUAL_ALIAS = {
    "旅游及景区": ["旅游"],
    "酒店餐饮": ["旅游", "餐饮"],
    "调味发酵品": ["调味"],
    "非白酒": ["食品饮料", "酒"],
    "特钢": ["钢铁"],
    "照明设备": ["照明"],
    "饲料": ["农业", "畜牧"],
    "养殖业": ["畜牧", "农业"],
    "种植业": ["农业"],
    "农产品加工": ["农业"],
    "渔业": ["农业"],
    "林业": ["农业"],
    "动物保健": ["农业", "畜牧"],
    "乘用车": ["汽车"],
    "商用车": ["汽车"],
    "汽车零部件": ["汽车"],
    "汽车服务": ["汽车"],
    "摩托车及其他": ["汽车"],
    "白色家电": ["家电"],
    "黑色家电": ["家电"],
    "小家电": ["家电"],
    "厨卫电器": ["家电"],
    "家电零部件": ["家电"],
    "化妆品": ["美容", "化妆品"],
    "个护用品": ["美容", "个护"],
    "医疗美容": ["医疗"],
    "化学原料": ["化工"],
    "化学制品": ["化工"],
    "化学纤维": ["化工"],
    "塑料": ["化工"],
    "橡胶": ["化工"],
    "农化制品": ["化工", "农业"],
    "非金属材料": ["材料", "建材"],
    "冶钢原料": ["钢铁"],
    "普钢": ["钢铁"],
    "金属新材料": ["有色", "材料"],
    "工业金属": ["有色"],
    "贵金属": ["黄金", "有色"],
    "小金属": ["有色"],
    "能源金属": ["有色", "锂"],
    "元件": ["电子"],
    "光学光电子": ["电子"],
    "其他电子": ["电子"],
    "消费电子": ["电子"],
    "电子化学品": ["电子", "化工"],
    "游戏": ["游戏", "传媒"],
    "广告营销": ["传媒"],
    "影视院线": ["传媒", "影视"],
    "数字媒体": ["传媒"],
    "社交": ["传媒"],
    "出版": ["传媒"],
    "电视广播": ["传媒"],
    "通信服务": ["通信"],
    "通信设备": ["通信"],
    "计算机设备": ["计算机"],
    "IT服务": ["计算机"],
    "软件开发": ["计算机", "软件"],
    "房地产服务": ["地产"],
    "专业工程": ["建筑"],
    "工程咨询服务": ["建筑"],
    "装修装饰": ["建筑"],
    "基础建设": ["基建", "建筑"],
    "房屋建设": ["建筑"],
    "水泥": ["建材"],
    "玻璃玻纤": ["建材"],
    "装修建材": ["建材"],
    "环境治理": ["环保"],
    "环保设备": ["环保"],
    "燃气": ["公用", "燃气"],
    "电力": ["电力", "公用"],
    "航运港口": ["航运", "港口"],
    "航空机场": ["航空", "机场"],
    "铁路公路": ["交运"],
    "物流": ["物流"],
    "国有大型银行": ["银行"],
    "股份制银行": ["银行"],
    "城商行": ["银行"],
    "农商行": ["银行"],
    "其他银行": ["银行"],
    "证券": ["证券公司", "全指证券"],
    "保险": ["保险"],
    "多元金融": ["金融"],
    "一般零售": ["零售", "商贸"],
    "专业连锁": ["零售"],
    "互联网电商": ["电商", "互联网"],
    "贸易": ["商贸"],
    "旅游零售": ["旅游", "零售"],
    "教育": ["教育"],
    "专业服务": ["服务"],
    "综合": ["综合"],
    "体育": ["体育"],
    "本地生活服务": ["消费", "服务"],
    "食品加工": ["食品"],
    "休闲食品": ["食品"],
    "饮料乳品": ["食品饮料"],
    "白酒": ["白酒", "酒"],
    "中药": ["中药", "医药"],
    "化学制药": ["医药", "制药"],
    "生物制品": ["生物", "医药"],
    "医药商业": ["医药"],
    "医疗器械": ["医疗器械", "医药"],
    "医疗服务": ["医疗"],
    "光伏设备": ["光伏"],
    "风电设备": ["风电"],
    "电池": ["电池", "新能源"],
    "电网设备": ["电网", "电力设备"],
    "电机": ["电机", "电力设备"],
    "其他电源设备": ["电源", "电力设备"],
    "通用设备": ["机械"],
    "专用设备": ["机械"],
    "轨交设备": ["机械", "轨交"],
    "工程机械": ["机械"],
    "自动化设备": ["机器人", "自动化", "机械"],
    "航天装备": ["军工", "航天"],
    "航空装备": ["军工", "航空"],
    "地面兵装": ["军工"],
    "航海装备": ["军工"],
    "军工电子": ["军工"],
    "半导体": ["半导体", "芯片"],
    "元件": ["电子"],
    "煤炭开采": ["煤炭"],
    "焦炭": ["煤炭"],
    "油气开采": ["石油", "油气"],
    "油服工程": ["石油", "油气"],
    "炼化及贸易": ["石油", "化工"],
    "造纸": ["轻工"],
    "包装印刷": ["轻工"],
    "家居用品": ["轻工", "家居"],
    "文娱用品": ["轻工"],
    "纺织制造": ["纺织"],
    "服装家纺": ["纺织", "服装"],
    "饰品": ["珠宝", "饰品"],
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
                                                      "clientInfo": {"name": "ifm2", "version": "1"}}):
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



def to_neodata_code(ts_code, name):
    """tushare 与 neodata 的基金代码口径不同：
    LOF 在 tushare 是 .SZ/.SH（如 161725.SZ 招商白酒A），neodata 认 .OF（161725.OF）。
    场内 ETF 两边一致，不转换。
    """
    if ts_code.endswith(".OF"):
        return ts_code
    if "ETF" in (name or ""):
        return ts_code
    return ts_code[:6] + ".OF"


def clean(name):
    return re.sub(r"[ⅡⅢⅠ]", "", name).strip()


def load_funds():
    """只保留指数型基金：主动基金没有 tracking_index，进来只会污染候选。"""
    funds = []
    for mk in ("O", "E"):
        p = os.path.join(META, "fund_basic_%s.csv" % mk)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    # 只认 fund_type/invest_type 里明确标了「指数型」的
                    # 不能用 benchmark 判断：主动基金的基准也含"沪深300指数"，
                    # 更坑的是"上海证券交易所"含"证券"两字，会把券商ETF挤掉
                    it = (r.get("invest_type") or "") + "/" + (r.get("fund_type") or "")
                    if "指数" not in it:
                        continue
                    nm = r.get("name") or ""
                    core = nm.rstrip("）) ").rstrip()
                    # 份额类别：兼容 "-A-CNY" 和 "指数C" / "联接C" 两种写法
                    sm = re.search(r"-([ACDEIH])(?:-(?:CNY|USD))?(?:-(?:现汇|现钞))?$", nm)
                    if sm and sm.group(1) != "A":
                        continue
                    if core and core[-1] in "CDEIH" and "ETF" not in core[-6:]:
                        continue                      # 指数C / 联接C 这类
                    if "USD" in nm.upper() or "美元" in nm:
                        continue
                    if "分级" in nm or "B级" in nm:
                        continue                      # 分级基金已退出历史舞台
                    r["_mk"] = mk
                    funds.append(r)
    return funds


def variants(nm):
    """行业名 → 可搜索变体：去通用后缀得到上位词（房地产开发→房地产，乘用车→乘用…）。"""
    vs = {nm}
    for suf in ("开发", "制造", "服务", "设备", "及其他", "其他", "开采", "加工",
                "零售", "连锁", "用品", "家纺", "玻纤", "制品", "材料"):
        if nm.endswith(suf) and len(nm) > len(suf) + 1:
            vs.add(nm[:-len(suf)])
    if nm.endswith("车") and len(nm) >= 3:
        vs.add(nm[:2])
    return vs


def load_l1(ts):
    rows = ts.call("index_classify", {"src": "SW2021", "level": "L1"}) or []
    m = {}
    for r in rows:
        m[str(r.get("industry_code"))] = r.get("industry_name")
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--per", type=int, default=12, help="每个行业最多验证几个候选")
    args = ap.parse_args()

    with open(SW, encoding="utf-8") as f:
        sw = json.load(f)["map"]
    ts, nd = client("tushare"), client("neodata")
    l1 = load_l1(ts)
    funds = load_funds()
    print("行业 %d 个 / 基金 %d 只 / 申万一级 %d 个" % (len(sw), len(funds), len(l1)))

    want = [x.strip() for x in args.only.split(",") if x.strip()]
    items = {k: v for k, v in sw.items() if not want or clean(v["name"]) in want}

    # 1. 为每个行业生成候选
    cand = {}
    for code, v in items.items():
        nm = clean(v["name"])
        lvl = "exact"
        kws = list(variants(nm))
        hits = [f for f in funds
                if any(k in (f.get("name") or "") + " " + (f.get("benchmark") or "") for k in kws)]
        if not hits:
            alias = MANUAL_ALIAS.get(nm, [])
            if alias:
                lvl = "near"
                kws = alias
                hits = [f for f in funds
                        if any(k in (f.get("name") or "") + " " + (f.get("benchmark") or "") for k in kws)]
        if not hits:
            lvl = "loose"
            parent = None
            for f in funds:
                pass
            hits = []
        hits.sort(key=lambda x: (0 if any(k in (x.get("name") or "") for k in kws) else 1,
                                 -float(x.get("issue_amount") or 0)))
        of_hits = [f for f in hits if f["ts_code"].endswith(".OF")]
        etf_hits = [f for f in hits if not f["ts_code"].endswith(".OF")]
        cand[code] = {"name": nm, "level": lvl, "kws": kws,
                      "hits": of_hits[:args.per] + etf_hits[:4]}

    # 2. 批量验证
    allf = {}
    for c in cand.values():
        for f in c["hits"]:
            allf[f["ts_code"]] = f
    allc = list(allf.keys())
    print("验证 %d 只候选..." % len(allc))
    verified = {}
    for i in range(0, len(allc), 10):
        batch = allc[i:i + 10]
        nc2orig, ncodes = {}, []
        for tc in batch:
            nc = to_neodata_code(tc, allf[tc].get("name"))
            nc2orig[nc] = tc
            ncodes.append(nc)
        try:
            res = nd.call("fund_benchmark", {
                "fund_codes": ",".join(ncodes), "limit": len(ncodes),
                "output_fields": "fund_code,fund_abbr,tracking_index_code,tracking_index_name,tracking_error",
            }) or []
        except Exception as e:  # noqa: BLE001
            print("  batch fail %s" % str(e)[:60])
            continue
        if isinstance(res, dict):
            res = res.get("result") or []
        for r in res:
            if not isinstance(r, dict):
                continue
            te = None
            for t in (r.get("tracking_error") or []):
                if t.get("annualized_tracking_error_1y") is not None:
                    te = t["annualized_tracking_error_1y"]
            orig = nc2orig.get(r.get("fund_code"), r.get("fund_code"))
            verified[orig] = {"idx_name": r.get("tracking_index_name"),
                              "idx_code": r.get("tracking_index_code"),
                              "abbr": r.get("fund_abbr"), "te": te}
        time.sleep(0.28)

    # 3. 定级选优
    out = {}
    stat = {"exact": 0, "near": 0, "loose": 0, "none": 0}
    for code, c in cand.items():
        nm = c["name"]
        best = None
        for f in c["hits"]:
            v = verified.get(f["ts_code"])
            if not v:
                continue
            idxn = clean(v["idx_name"] or "")
            if nm and nm in idxn:
                lv, sc = "exact", 100
            elif any(len(k) >= 2 and k in idxn for k in c["kws"] if k != nm):
                lv, sc = "near", 75
            elif any(k in idxn for k in c["kws"]):
                lv, sc = "near", 70
            else:
                continue          # 跟踪指数名与行业关键词毫无交集 → 误配，直接弃
            te = v["te"] if v["te"] is not None else 99
            is_of = f["ts_code"].endswith(".OF") or "ETF" not in (f.get("name") or "")
            # 场外优先：+60 分足以让任何场外压过同等条件的场内
            score = sc - min(te, 20) * 2 + (60 if is_of else 0)
            if best is None or score > best["score"]:
                best = {"fund_code": f["ts_code"], "fund_name": v["abbr"] or f.get("name"),
                        "tracking_index": v["idx_name"], "tracking_index_code": v["idx_code"],
                        "tracking_error_1y": v["te"], "m_fee": f.get("m_fee"),
                        "venue": ("场外" if f["ts_code"].endswith(".OF")
                                  else ("场内ETF" if "ETF" in (f.get("name") or "") else "LOF")),
                        "match_level": lv, "score": round(score, 1)}
        if best:
            stat[best["match_level"]] += 1
        else:
            stat["none"] += 1
        out[code] = {"name": nm, "primary": best}

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"version": "v1.0", "updated": "2026-10-28",
                   "note": "exact=跟踪指数名含行业名；near=含别名/前几字；loose=只到广谱行业，大概率不纯；none=无基金",
                   "stat": stat, "map": out}, f, ensure_ascii=False, indent=2)

    print("\n匹配结果：exact %d / near %d / loose %d / none %d" % (
        stat["exact"], stat["near"], stat["loose"], stat["none"]))
    print("\n%-16s %-6s %-12s %-26s %7s" % ("行业", "质量", "基金代码", "基金名", "跟踪误差"))
    print("-" * 78)
    for code, v in sorted(out.items(), key=lambda x: x[1]["name"]):
        p = v["primary"]
        if not p:
            print("%-16s %-6s %s" % (v["name"][:14], "none", "无可买基金"))
        else:
            print("%-16s %-6s %-12s %-26s %6s%%" % (
                v["name"][:14], p["match_level"], p["fund_code"],
                (p["fund_name"] or "")[:24], p["tracking_error_1y"]))
    print("\n写入 %s" % OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
