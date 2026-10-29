# -*- coding: utf-8 -*-
"""研究员：pool top50 排雷 + 质量打分 → watchlist.json

排雷三件套（来自 warehouse/research/，由 research_check_mcp.py 取证）：
  - 商誉/净资产 > 30%      → avoid
  - 审计意见非"标准"        → avoid
  - 近 3 月减持占总股本 >1% → avoid（次数只作风险提示，不作否决）
经营质量否决（阈值与 logic 一律读 params.researcher_veto，本文件不写死）：
  - 否决条件按 params 的 logic（OR/AND）组合 roe_below 与 net_margin_below 两个阈值
质量分 = ROE / 净利率 / 毛利率 / 营收同比 的全市场横截面百分位加权（权重读 params.researcher_quality.weights）

正式跑：POOL_IN=state/pool.json WATCHLIST_OUT=state/watchlist.json
彩排跑：默认读写 test/state/
"""
import csv
import json
import os

ROOT = r"E:\cashfree\agent"
WH = os.path.join(ROOT, "data", "warehouse")
KN = os.path.join(ROOT, "knowledge")
POOL = os.environ.get("POOL_IN") or os.path.join(ROOT, "test", "state", "pool.json")
OUT = os.environ.get("WATCHLIST_OUT") or os.path.join(ROOT, "test", "state", "watchlist.json")
SCORES = os.path.join(WH, "scores_full.csv")
GOODWILL_MAX = 0.30
REDUCTION_MAX = 0.01

# 所有阈值一律从 params_{params_current.txt}.json 读取（v3.0 起 params_v3.0.json 为唯一真源）
_CUR_VER = open(os.path.join(KN, "params_current.txt"), encoding="utf-8").read().strip()
try:
    _P = json.load(open(os.path.join(KN, f"params_{_CUR_VER}.json"), encoding="utf-8"))
except FileNotFoundError:
    _P = {}
_VETO = _P.get("researcher_veto") or {}
ROE_VETO_BELOW = float(_VETO.get("roe_below", 0.0))
NM_VETO_BELOW = float(_VETO.get("net_margin_below", 2.0))
VETO_ENABLED = bool(_VETO.get("enabled", True))
# logic: "OR" = 任一条件命中即否决（严）；"AND" = 两条同时满足才否决（松）
VETO_LOGIC = str(_VETO.get("logic", "OR")).upper()

# 候选扫描深度 = 选股池大小（v3.0 修正：此处曾写死 150，与 pool_size=50 矛盾）
TOP_N = int((_P.get("strategy") or {}).get("pool_size", 50))

# 质量分权重（唯一真源 researcher_quality.weights）
_QW = (_P.get("researcher_quality") or {}).get("weights") or {}
W_ROE = float(_QW.get("roe_ttm", 0.35))
W_NM = float(_QW.get("net_margin_ttm", 0.25))
W_GM = float(_QW.get("gross_margin_ttm", 0.15))
W_TR = float(_QW.get("tr_yoy", 0.25))

# buy_watch 入选规则（唯一真源 researcher_quality.buy_watch_rule）
_BWR = (_P.get("researcher_quality") or {}).get("buy_watch_rule") or {}
BUY_N = int(_BWR.get("top_n", 20))
_MIN_QS = _BWR.get("min_quality_score")
MIN_QS = None if _MIN_QS is None else float(_MIN_QS)


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

    # ---------- 经营质量否决（v2.1）----------
    # v2.0 的 target_zone 刻意选低 ROE / 低净利率分位（困境反转），但"亏损/不赚钱"必须挡在买点外。
    # logic=OR（当前）：ROE<0 或 净利率<5% 任一命中即 avoid——严，直接对抗 target_zone。
    # logic=AND：两条同时满足才 avoid——松，只挡"亏损且薄利"。
    if VETO_ENABLED and roe is not None and nm is not None:
        hit_roe = roe < ROE_VETO_BELOW
        hit_nm = nm < NM_VETO_BELOW
        trigger = (hit_roe or hit_nm) if VETO_LOGIC.startswith("OR") else (hit_roe and hit_nm)
        if trigger:
            parts = []
            if hit_roe:
                parts.append(f"ROE {roe:.2f}% < {ROE_VETO_BELOW:g}%")
            if hit_nm:
                parts.append(f"净利率 {nm:.1f}% < {NM_VETO_BELOW:g}%")
            flags.append(f"经营质量否决（{VETO_LOGIC}）：" + " 或 ".join(parts))

    # ---------- v3.1：排序分 = 选股分（技术反转 zone 分），财务不再单独打分 ----------
    # 变更理由：研究员原来另算一套财务质量分（ROE .35/净利率 .25/毛利率 .15/营收 .25），
    # 用来排序和分配权重。但选股层的 target_zone 刻意要"财务最差的 20%"（困境反转），
    # 两把尺子方向相反——财务排序会系统性把技术面最强的票压到最后、补仓时永远轮不到。
    # 六年回测（QS_MODE=score vs fin）见 params.backtest_registry。
    # 财务因子不再在这里打分，改为并入选股层的 target_zone（选股师统一负责）。
    quality_score = round(float(c.get("score") or 0) * 100, 1)

    if flags:
        avoid.append({"code": code, "name": name, "flags": flags,
                      "goodwill_ratio": None if g_ratio is None else round(g_ratio, 4),
                      "reduction_pct": None if dec_pct is None else round(dec_pct, 4)})
        continue

    # 初始 verdict 只标注是否过绝对门槛；最终 buy_watch 由排序分取前 BUY_N 决定（见下方）
    if MIN_QS is None:
        verdict = "pass"
    else:
        verdict = "buy_watch" if quality_score >= MIN_QS else "watch"

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
# buy_watch 入选：按排序分（=选股分）取前 BUY_N（params.researcher_quality.buy_watch_rule.top_n）
# v3.0 修掉「quality_score>=55」死代码；v3.1 起排序分改为选股分，财务不再参与排名。
buy = [dict(i, verdict="buy_watch") for i in items[:BUY_N]]
# 修正（v2.1）：items 内 verdict 未被覆盖，原写法统计会与 buy 重复计数（曾出现 20+41 > pass 45）
watch_cnt = max(0, len(items) - len(buy))

out = {
    "date": base_date,
    "source_pool_date": pool["date"],
    "items": buy,
    "notes": {
        "mode": _mode,
        "strategy_version": pool.get("strategy_version"),
        "params_version": _CUR_VER,
        "candidates_scanned": len(cands),
        "avoid_count": len(avoid),
        "avoid_summary": avoid,
        "watch_count": watch_cnt,
        "pass_count": len(items),
        "buy_watch_count": len(buy),
        "due_diligence_coverage": {"goodwill": len(gw), "reduction": len(red), "audit": len(aud)},
        "dd_rules": {
            "goodwill_max": GOODWILL_MAX,
            "reduction_max_of_total_share": REDUCTION_MAX,
            "audit": "非标准无保留即 avoid",
            "researcher_veto": {
                "enabled": VETO_ENABLED,
                "logic": VETO_LOGIC,
                "rule": f"ROE < {ROE_VETO_BELOW:g}% {'或' if VETO_LOGIC.startswith('OR') else '且'} 净利率 < {NM_VETO_BELOW:g}% → avoid",
                "logic_note": "OR=任一命中即否决（严）；AND=两条同时满足才否决（松）",
                "rationale": "v2.0 target_zone 刻意选低 ROE 分位，但 ROE 为负 = 主营未盈利，配低 PB/PS 属价值陷阱",
            },
            "unit_fix": "dec_vol(股) / (total_share(万股)*10000)",
        },
        "quality_formula": "v3.1 起 quality_score = 选股分（pool.json 的 zone 分）×100；财务因子已并入选股层 target_zone，本层不打分、不影响排名。排雷与否决只决定去留（avoid），不参与排序。",
        "ranking_basis": "selection_score",
        "buy_watch_rule": f"通过排雷后按 quality_score 降序取前 {BUY_N} 只"
                          + (f"，且 quality_score >= {MIN_QS:g}" if MIN_QS is not None else "（min_quality_score=null，无绝对门槛）"),
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
