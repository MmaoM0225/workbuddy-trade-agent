# -*- coding: utf-8 -*-
"""研究员：pool top50 排雷 + 质量打分 → watchlist.json

排雷三件套（来自 warehouse/research/，由 research_check_mcp.py 取证）：
  - 商誉/净资产 > 30%      → avoid
  - 审计意见非"标准"        → avoid
  - 近 3 月减持占总股本 >1% → avoid（次数只作风险提示，不作否决）
质量分 = ROE 35% + 净利率 25% + 毛利率 15% + 营收同比 25%（全市场横截面百分位加权）

正式跑：POOL_IN=state/pool.json WATCHLIST_OUT=state/watchlist.json
彩排跑：默认读写 test/state/
"""
import csv
import json
import os

ROOT = r"E:\cashfree\agent"
WH = os.path.join(ROOT, "data", "warehouse")
POOL = os.environ.get("POOL_IN") or os.path.join(ROOT, "test", "state", "pool.json")
OUT = os.environ.get("WATCHLIST_OUT") or os.path.join(ROOT, "test", "state", "watchlist.json")
SCORES = os.path.join(WH, "scores_full.csv")
TOP_N = 60
GOODWILL_MAX = 0.30
REDUCTION_MAX = 0.01


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
base_date = pool["date"]
cands = pool["stocks"][:TOP_N]
_mode = "production" if os.path.abspath(OUT).startswith(os.path.abspath(os.path.join(ROOT, "state"))) else "rehearsal"
print(f"candidates: {len(cands)} base_date={base_date} mode={_mode}")

all_rows = {r["ts_code"]: r for r in read_csv(SCORES)}


def pct_rank(value, values):
    if value is None or not values:
        return None
    below = sum(1 for v in values if v < value)
    return below / max(len(values) - 1, 1)


def pool_of(fac):
    return [fnum(r.get(fac)) for r in all_rows.values() if fnum(r.get(fac)) is not None]


roe_all = pool_of("roe_ttm")
nm_all = pool_of("net_margin_ttm")
gm_all = pool_of("gross_margin_ttm")
try_all = pool_of("tr_yoy")
ep_all = pool_of("ep_ttm")

# 总股本（万股），用于减持比例换算
db_path = os.path.join(WH, "daily_basic", f"{base_date}.csv")
shares = {}
if os.path.exists(db_path):
    for r in read_csv(db_path):
        shares[r["ts_code"]] = fnum(r.get("total_share"))

gw, red, aud = {}, {}, {}
for name, box in (("goodwill.csv", gw), ("reduction.csv", red), ("audit.csv", aud)):
    p = os.path.join(WH, "research", name)
    if os.path.exists(p):
        for r in read_csv(p):
            box[r["ts_code"]] = r
print(f"dd data: goodwill={len(gw)} reduction={len(red)} audit={len(aud)} shares={len(shares)}")

items, avoid = [], []
for c in cands:
    code, name = c["code"], c["name"]
    r = all_rows.get(code, {})
    roe = fnum(r.get("roe_ttm"))
    tryy = fnum(r.get("tr_yoy"))
    nm = fnum(r.get("net_margin_ttm"))
    gm = fnum(r.get("gross_margin_ttm"))
    ep = fnum(r.get("ep_ttm"))

    # ---------- 排雷 ----------
    flags = []
    g = gw.get(code)
    g_ratio = None
    if g:
        gv, eq = fnum(g.get("goodwill")), fnum(g.get("equity"))
        if eq and eq > 0:
            gv = gv or 0.0  # goodwill 字段为空 = 无商誉科目，按 0 处理（不是数据缺失）
            g_ratio = gv / eq
            if g_ratio > GOODWILL_MAX:
                flags.append(f"商誉/净资产 {g_ratio:.1%} >{GOODWILL_MAX:.0%}")

    rd = red.get(code)
    dec_cnt = int(fnum(rd.get("dec_cnt")) or 0) if rd else 0
    dec_vol = (fnum(rd.get("dec_vol")) or 0.0) if rd else 0.0
    dec_pct = None
    ts = shares.get(code)
    if ts and ts > 0:
        # change_vol 单位为「股」，total_share 单位为「万股」→ 需 ×10000，否则放大 1 万倍
        dec_pct = dec_vol / (ts * 10000)
        if dec_pct > REDUCTION_MAX:
            flags.append(f"近3月减持占总股本 {dec_pct:.2%} >{REDUCTION_MAX:.0%}")

    a = aud.get(code)
    audit_note = (a or {}).get("audit_result")
    if audit_note and "标准" not in str(audit_note):
        flags.append(f"审计意见：{audit_note}")

    # ---------- 质量分：全市场横截面百分位加权 ----------
    parts = []
    for v, arr, w in ((roe, roe_all, 0.35), (nm, nm_all, 0.25), (gm, gm_all, 0.15), (tryy, try_all, 0.25)):
        pr = pct_rank(v, arr)
        if pr is not None:
            parts.append((pr, w))
    q = sum(p * w for p, w in parts) / sum(w for _, w in parts) if parts else 0.5
    if dec_cnt == 1:
        q -= 0.03
    elif dec_cnt >= 2:
        q -= 0.06
    quality_score = round(max(0.0, min(1.0, q)) * 100, 1)

    if flags:
        avoid.append({"code": code, "name": name, "flags": flags,
                      "goodwill_ratio": None if g_ratio is None else round(g_ratio, 4),
                      "reduction_pct": None if dec_pct is None else round(dec_pct, 4)})
        continue

    verdict = "buy_watch" if quality_score >= 55 else "watch"

    thesis = []
    if roe is not None:
        thesis.append(f"ROE {roe:.1f}%（横截面{pct_rank(roe, roe_all):.0%}分位）")
    if nm is not None:
        thesis.append(f"净利率 {nm:.1f}%")
    if tryy is not None:
        thesis.append(f"营收同比 {tryy:+.1f}%")
    if ep is not None:
        thesis.append(f"EP 百分位 {pct_rank(ep, ep_all):.0%}")
    thesis.append(f"因子总分 {c['score']:.3f}（池内 #{[x['code'] for x in cands].index(code) + 1}）")

    risks = []
    if g_ratio is None:
        risks.append("商誉/净资产数据未取到（财报未覆盖），未能排查")
    elif g_ratio > 0.15:
        risks.append(f"商誉/净资产 {g_ratio:.1%}，需关注减值风险")
    if dec_cnt:
        risks.append(f"近3月股东减持 {dec_cnt} 次" + (f"，占总股本 {dec_pct:.2%}" if dec_pct else ""))
    if tryy is not None and tryy < 0:
        risks.append(f"营收同比下滑 {tryy:.1f}%")
    if ep is None:
        risks.append("PE 为负（亏损），估值因子缺失")
    if not risks:
        risks.append("短期动量回落风险（动量因子为横截面相对强度，非绝对上涨趋势）")

    items.append({
        "code": code, "name": name, "quality_score": quality_score, "verdict": verdict,
        "goodwill_ratio": None if g_ratio is None else round(g_ratio, 4),
        "reduction_pct": None if dec_pct is None else round(dec_pct, 4),
        "thesis": "；".join(thesis), "risks": risks, "veto_flags": [],
    })

items.sort(key=lambda x: -x["quality_score"])
# v1.8: 池内相对排名取前 20 为 buy_watch（新池子由纯量价因子选出，财务绝对分整体偏低，
# 用固定 55 分门槛会导致 buy_watch 恒为 0，故改为相对排名）
buy = [dict(i, verdict="buy_watch") for i in items[:20]]
watch_cnt = len([i for i in items if i["verdict"] == "watch"])

out = {
    "date": base_date,
    "source_pool_date": pool["date"],
    "items": buy,
    "notes": {
        "mode": _mode,
        "strategy_version": pool.get("strategy_version"),
        "candidates_scanned": len(cands),
        "avoid_count": len(avoid),
        "avoid_summary": avoid,
        "watch_count": watch_cnt,
        "pass_count": len(items),
        "due_diligence_coverage": {"goodwill": len(gw), "reduction": len(red), "audit": len(aud)},
        "dd_rules": {
            "goodwill_max": GOODWILL_MAX,
            "reduction_max_of_total_share": REDUCTION_MAX,
            "audit": "非标准无保留即 avoid",
            "unit_fix": "dec_vol(股) / (total_share(万股)*10000)",
        },
        "quality_formula": "ROE .35 / 净利率 .25 / 毛利率 .15 / 营收增速 .25 全市场横截面百分位加权，减持次数扣分",
    },
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print(f"\npass={len(items)} buy_watch={len(buy)} avoid={len(avoid)} watch={watch_cnt}")
print("\navoid 明细:")
for a in avoid:
    print(f"  {a['name']:<8} {a['code']} -> {'; '.join(a['flags'])}")
print("\nTOP buy_watch:")
for i in buy[:12]:
    print(f"  {i['name']:<8} {i['code']} q={i['quality_score']:.1f}")
print(f"\nwrote {OUT}")
