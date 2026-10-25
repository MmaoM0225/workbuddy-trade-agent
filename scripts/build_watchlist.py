# -*- coding: utf-8 -*-
"""研究员：对 pool top60 排雷 + 质量打分 → test/state/watchlist.json"""
import csv
import json
import os
import statistics

ROOT = r"E:\cashfree\agent"
WH = os.path.join(ROOT, "data", "warehouse")
POOL = os.path.join(ROOT, "test", "state", "pool.json")
OUT = os.path.join(ROOT, "test", "state", "watchlist.json")
SCORES = os.path.join(WH, "scores_full.csv")
TOP_N = 60


def read_csv(p):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def fnum(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


pool = json.load(open(POOL, encoding="utf-8"))
cands = pool["stocks"][:TOP_N]
print(f"candidates: {len(cands)}")

# full-market scores for cross-sectional quality/valuation percentile
all_rows = {r["ts_code"]: r for r in read_csv(SCORES)}


def pct_rank(value, values):
    if value is None or not values:
        return None
    below = sum(1 for v in values if v < value)
    return below / max(len(values) - 1, 1)


roe_all = [fnum(r["roe_ttm"]) for r in all_rows.values() if fnum(r["roe_ttm"]) is not None]
try_all = [fnum(r["tr_yoy"]) for r in all_rows.values() if fnum(r["tr_yoy"]) is not None]
nm_all = [fnum(r["net_margin_ttm"]) for r in all_rows.values() if fnum(r["net_margin_ttm"]) is not None]
ep_all = [fnum(r["ep_ttm"]) for r in all_rows.values() if fnum(r["ep_ttm"]) is not None]
bp_all = [fnum(r["bp_ttm"]) for r in all_rows.values() if fnum(r["bp_ttm"]) is not None]

# due diligence data
gw = {}
p = os.path.join(WH, "research", "goodwill.csv")
if os.path.exists(p):
    for r in read_csv(p):
        gw[r["ts_code"]] = r
red = {}
p = os.path.join(WH, "research", "reduction.csv")
if os.path.exists(p):
    for r in read_csv(p):
        red[r["ts_code"]] = r
aud = {}
p = os.path.join(WH, "research", "audit.csv")
if os.path.exists(p):
    for r in read_csv(p):
        aud[r["ts_code"]] = r
print(f"dd data: goodwill={len(gw)} reduction={len(red)} audit={len(aud)}")

items = []
avoid = []
for c in cands:
    code, name = c["code"], c["name"]
    r = all_rows.get(code, {})
    roe, tryy, nm = fnum(r.get("roe_ttm")), fnum(r.get("tr_yoy")), fnum(r.get("net_margin_ttm"))
    ep, bp = fnum(r.get("ep_ttm")), fnum(r.get("bp_ttm"))

    # --- 排雷 ---
    flags = []
    g = gw.get(code)
    g_ratio = None
    if g:
        gv, eq = fnum(g.get("goodwill")), fnum(g.get("equity"))
        if gv and eq and eq > 0:
            g_ratio = gv / eq
            if g_ratio > 0.30:
                flags.append(f"商誉/净资产 {g_ratio:.1%} >30%")
    rd = red.get(code)
    dec_cnt = int(fnum(rd.get("dec_cnt")) or 0) if rd else 0
    if dec_cnt >= 3:
        flags.append(f"近3月减持 {dec_cnt} 次")
    a = aud.get(code)
    if a and a.get("audit_result") and "标准" not in str(a.get("audit_result")):
        flags.append(f"审计意见：{a.get('audit_result')}")

    # --- 质量分（横截面百分位加权） ---
    parts = []
    for v, arr, w in [(roe, roe_all, 0.5), (tryy, try_all, 0.3), (nm, nm_all, 0.2)]:
        pr = pct_rank(v, arr)
        if pr is not None:
            parts.append((pr, w))
    q = sum(p * w for p, w in parts) / sum(w for _, w in parts) if parts else 0.5

    # 减持扣分
    if dec_cnt == 1:
        q -= 0.05
    elif dec_cnt == 2:
        q -= 0.10

    quality_score = round(max(0.0, min(1.0, q)) * 100, 1)

    if flags:
        verdict = "avoid"
        avoid.append({"code": code, "name": name, "flags": flags})
        continue

    verdict = "buy_watch" if quality_score >= 55 else "watch"

    thesis_bits = []
    if roe is not None:
        thesis_bits.append(f"ROE {roe:.1f}%（横截面{pct_rank(roe, roe_all):.0%}分位）")
    if tryy is not None:
        thesis_bits.append(f"营收同比 {tryy:+.1f}%")
    if ep is not None:
        thesis_bits.append(f"EP 百分位 {pct_rank(ep, ep_all):.0%}")
    thesis_bits.append(f"因子总分 {c['score']:.3f}（池内 #{[x['code'] for x in cands].index(code)+1}）")

    risks = []
    if g_ratio is None:
        risks.append("商誉数据缺失，未能排查")
    elif g_ratio > 0.15:
        risks.append(f"商誉/净资产 {g_ratio:.1%}，需关注减值风险")
    if dec_cnt:
        risks.append(f"近3月股东减持 {dec_cnt} 次")
    if tryy is not None and tryy < 0:
        risks.append(f"营收同比下滑 {tryy:.1f}%")
    if ep is None:
        risks.append("PE 为负（亏损），估值因子缺失")
    if not risks:
        risks.append("短期动量回落风险（动量因子为横截面相对强度，非绝对上涨趋势）")

    items.append({
        "code": code, "name": name, "quality_score": quality_score, "verdict": verdict,
        "thesis": "；".join(thesis_bits), "risks": risks,
        "veto_flags": [],
    })

items.sort(key=lambda x: -x["quality_score"])
buy = [i for i in items if i["verdict"] == "buy_watch"][:20]

out = {
    "date": "20261023",
    "source_pool_date": pool["date"],
    "items": buy,
    "notes": {
        "mode": "rehearsal",
        "candidates_scanned": len(cands),
        "avoid_count": len(avoid),
        "avoid_summary": avoid[:15],
        "watch_count": len([i for i in items if i["verdict"] == "watch"]),
        "due_diligence_coverage": {"goodwill": len(gw), "reduction": len(red), "audit": len(aud)},
        "quality_formula": "ROE .5 / 营收增速 .3 / 净利率 .2 横截面百分位加权，减持次数扣分",
    },
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print(f"\nbuy_watch: {len(buy)}, avoid: {len(avoid)}, watch: {out['notes']['watch_count']}")
print("\nTOP buy_watch:")
for i in buy[:12]:
    print(f"  {i['name']:<8} {i['code']} q={i['quality_score']:.1f}")
print(f"\navoid samples: {[(a['name'], a['flags'][0][:20]) for a in avoid[:5]]}")
print(f"wrote {OUT}")
