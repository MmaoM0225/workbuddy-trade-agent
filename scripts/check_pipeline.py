#!/usr/bin/env python3
"""Pipeline integrity checker for the multi-agent trading framework.

Usage:
    python check_pipeline.py [--base E:/cashfree/agent] [--date 20261023]

Checks:
    1. state/*.json parse as JSON and contain required schema keys
    2. state/trades.jsonl every non-empty line is valid JSON
    3. data/daily_<date>/ exists with meta.json and non-empty core files
    4. business rules on populated state files (weight caps, stop/take sanity,
       regime enum, evidence count, order tranche rules, trade record sanity)
    5. state/tasks/*.json task status files (9 tasks, undo/doing/done enum,
       single-writer file per task)

Business rules only apply to files that have been populated (date/as_of set),
so the initial empty skeleton passes.

Exit code 0 = all pass, 1 = at least one FAIL.
"""
import argparse
import json
import sys
from pathlib import Path

STATE_SCHEMAS = {
    "pool.json": ["date", "strategy_version", "count", "stocks"],
    "watchlist.json": ["date", "source_pool_date", "items"],
    "regime.json": ["date", "regime", "confidence", "evidence",
                    "sector_signals", "risk_level", "confirmed_days"],
    # 2026-10-26：金额口径统一。金额字段为唯一权威，cash_pct 由 amount 推导
    "positions.json": ["as_of", "initial_capital_cny", "cash_cny",
                       "total_asset_cny", "cash_pct", "total_pnl_pct", "holdings"],
    "orders.json": ["orders"],
}

DATA_CORE_FILES = ["indices.json", "market_overview.json"]
DATA_OPTIONAL_FILES = ["news.json", "hot_news.json", "hot_board.json",
                       "sector_ranking.json", "dragon_tiger.json", "northbound.json"]

REGIMES = ("bull", "neutral", "bear")
TOL = 0.5

failures = []
STATE = None
DATA = None


def load_json(p):
    return json.loads(p.read_text(encoding="utf-8"))


def check_state():
    for fname, keys in STATE_SCHEMAS.items():
        p = STATE / fname
        if not p.exists():
            failures.append(f"missing state file: {p}")
            continue
        try:
            data = load_json(p)
        except Exception as e:
            failures.append(f"{fname}: invalid JSON ({e})")
            continue
        missing = [k for k in keys if k not in data]
        if missing:
            failures.append(f"{fname}: missing keys {missing}")
    trades = STATE / "trades.jsonl"
    if not trades.exists():
        failures.append("missing state/trades.jsonl")
    else:
        bad = 0
        total = 0
        for line in trades.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            total += 1
            try:
                json.loads(line)
            except Exception:
                bad += 1
        if bad:
            failures.append(f"trades.jsonl: {bad}/{total} lines are not valid JSON")
    print(f"[state] schema check done, {len(STATE_SCHEMAS)} files + trades.jsonl")


def check_business():
    regime = load_json(STATE / "regime.json")
    if regime.get("date"):
        if regime.get("regime") not in REGIMES:
            failures.append(f"regime.json: regime={regime.get('regime')!r} not in {REGIMES}")
        c = regime.get("confidence")
        if not (isinstance(c, (int, float)) and 0 <= c <= 1):
            failures.append(f"regime.json: confidence={c!r} out of [0,1]")
        if len(regime.get("evidence") or []) < 2:
            failures.append("regime.json: fewer than 2 evidence items")

    pool = load_json(STATE / "pool.json")
    if pool.get("date"):
        stocks = pool.get("stocks") or []
        if pool.get("count") != len(stocks):
            failures.append(f"pool.json: count={pool.get('count')} != len(stocks)={len(stocks)}")
        if not pool.get("strategy_version"):
            failures.append("pool.json: strategy_version missing")

    wl = load_json(STATE / "watchlist.json")
    if wl.get("date"):
        for it in wl.get("items") or []:
            if it.get("verdict") == "buy_watch":
                if not it.get("thesis"):
                    failures.append(f"watchlist.json: {it.get('code')} buy_watch without thesis")
                if not (it.get("risks") or []):
                    failures.append(f"watchlist.json: {it.get('code')} buy_watch without risks")

    pos = load_json(STATE / "positions.json")
    if pos.get("as_of"):
        holdings = pos.get("holdings") or []
        total_w = sum(h.get("weight_pct", 0) or 0 for h in holdings)
        if total_w > 100 + TOL:
            failures.append(f"positions.json: holdings weight sum {total_w:.1f}% > 100%")
        cash = pos.get("cash_pct") or 0
        if abs(cash + total_w - 100) > 1.0:
            failures.append(f"positions.json: cash {cash:.1f}% + weights {total_w:.1f}% != 100%")
        for h in holdings:
            code = h.get("code")
            w = h.get("weight_pct") or 0
            if w > 15 + TOL:
                failures.append(f"positions.json: {code} weight {w:.1f}% exceeds 15% cap")
            cost, sl, tp = h.get("cost"), h.get("stop_loss"), h.get("take_profit")
            if cost and sl and sl >= cost:
                failures.append(f"positions.json: {code} stop_loss {sl} >= cost {cost}")
            if cost and tp and tp <= cost:
                failures.append(f"positions.json: {code} take_profit {tp} <= cost {cost}")
        # 金额口径一致性（金额为权威，cash_pct 由金额推导）
        cash_cny = pos.get("cash_cny")
        ta = pos.get("total_asset_cny")
        if isinstance(cash_cny, (int, float)) and isinstance(ta, (int, float)) and ta > 0:
            mv = sum((h.get("market_value_cny") or 0) for h in holdings)
            if abs(cash_cny + mv - ta) > max(1.0, ta * 0.001):
                failures.append(
                    f"positions.json: cash_cny {cash_cny:.2f} + market_value {mv:.2f} "
                    f"!= total_asset_cny {ta:.2f}")
            calc_pct = cash_cny / ta * 100
            if abs(calc_pct - (pos.get("cash_pct") or 0)) > 1.0:
                failures.append(
                    f"positions.json: cash_pct {pos.get('cash_pct') or 0:.2f} 与 "
                    f"cash_cny/total_asset 推导值 {calc_pct:.2f} 不一致")

    orders = (load_json(STATE / "orders.json")).get("orders") or []
    for o in orders:
        oid = o.get("id", "?")
        if o.get("side") == "buy":
            trs = o.get("tranches") or []
            if len(trs) < 2:
                failures.append(f"orders.json: {oid} has {len(trs)} tranches (<2)")
            # tranches[].pct 是该档占本单目标仓位的比例（合计应为 100），不是仓位上限
            pct_sum = sum(t.get("pct", 0) or 0 for t in trs)
            if pct_sum > 100 + TOL:
                failures.append(f"orders.json: {oid} tranche pct sum {pct_sum:.1f}% > 100%")
            tw = o.get("target_weight_pct")
            if isinstance(tw, (int, float)) and tw > 15 + TOL:
                failures.append(f"orders.json: {oid} target_weight {tw}% exceeds single cap 15%")
            if not (o.get("stop_loss") and o.get("take_profit")):
                failures.append(f"orders.json: {oid} missing stop_loss/take_profit")
            # ---- v2.4 限价单口径断言（low 触及即成交，成交价 = min(open, limit)）----
            guard = o.get("guard_price")
            for ti, t in enumerate(trs, 1):
                # v2.7/v2.9 首档为「开盘竞价市价」：不设 price_zone 与限价，单独断言
                if t.get("type") == "market_open":
                    if t.get("limit_price") is not None:
                        failures.append(f"orders.json: {oid} tr{ti} market_open 档不应设 limit_price")
                    if t.get("status") not in ("filled", "pending"):
                        failures.append(f"orders.json: {oid} tr{ti} status {t.get('status')!r} invalid")
                    continue
                zone = t.get("price_zone") or []
                if len(zone) != 2:
                    failures.append(f"orders.json: {oid} tr{ti} missing price_zone[lo,hi]")
                    continue
                lo_z, hi_z = zone
                if not (isinstance(lo_z, (int, float)) and isinstance(hi_z, (int, float))):
                    failures.append(f"orders.json: {oid} tr{ti} price_zone not numeric")
                    continue
                if lo_z >= hi_z:
                    failures.append(f"orders.json: {oid} tr{ti} price_zone not ascending {zone}")
                limit = t.get("limit_price", hi_z)
                if abs(limit - hi_z) > 0.011:
                    failures.append(
                        f"orders.json: {oid} tr{ti} limit_price {limit} != price_zone 上沿 {hi_z}")
                if t.get("status") not in ("filled", "pending"):
                    failures.append(f"orders.json: {oid} tr{ti} status {t.get('status')!r} invalid")
                fp = t.get("fill_price")
                if fp is None:
                    continue
                if fp > limit + 0.011:
                    failures.append(
                        f"orders.json: {oid} tr{ti} fill_price {fp} > limit {limit}（限价单不可能高于挂单价成交）")
                if isinstance(guard, (int, float)) and fp < guard - 0.011:
                    failures.append(
                        f"orders.json: {oid} tr{ti} fill_price {fp} < guard {guard}（破保护线仍成交）")
                op = t.get("day_open")
                if isinstance(op, (int, float)):
                    expect = round(min(op, limit), 2)
                    if abs(fp - expect) > 0.011:
                        failures.append(
                            f"orders.json: {oid} tr{ti} fill_price {fp} != min(open {op}, limit {limit})"
                            f" = {expect}（v2.4 成交价口径错误）")
                low = t.get("day_low")
                if isinstance(low, (int, float)) and low > limit + 0.011:
                    failures.append(
                        f"orders.json: {oid} tr{ti} 已成交但 day_low {low} > limit {limit}（未触及不应成交）")
        elif o.get("side") == "sell":
            if not (o.get("reason") and o.get("trigger")):
                failures.append(f"orders.json: {oid} sell order missing reason/trigger")

    for line in (STATE / "trades.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            t = json.loads(line)
        except Exception:
            continue
        tid = t.get("trade_id", "?")
        if (t.get("open") or {}).get("price", 0) <= 0:
            failures.append(f"trades.jsonl: {tid} open price <= 0")
        if t.get("side") == "buy":
            op_px = (t.get("open") or {}).get("price", 0)
            lim = t.get("limit")
            if isinstance(lim, (int, float)) and op_px > lim + 0.011:
                failures.append(
                    f"trades.jsonl: {tid} buy price {op_px} > limit {lim}（限价单成交价不合法）")
        if t.get("close"):
            if (t["close"] or {}).get("price", 0) <= 0:
                failures.append(f"trades.jsonl: {tid} close price <= 0")
            if t.get("pnl_pct") is None:
                failures.append(f"trades.jsonl: {tid} closed without pnl_pct")
    print("[state] business rules checked (populated files only)")


TASK_NAMES = [
    "data_officer", "market_analyst", "position_manager", "inspector",
    "stock_picker", "researcher", "position_builder", "reviewer", "archivist",
]
TASK_STATUSES = ("undo", "doing", "done")


def check_tasks():
    """state/tasks/*.json: one file per task (single-writer), status enum valid."""
    tasks_dir = STATE / "tasks"
    if not tasks_dir.exists():
        failures.append(f"missing tasks dir: {tasks_dir}")
        return
    for name in TASK_NAMES:
        p = tasks_dir / f"{name}.json"
        if not p.exists():
            failures.append(f"missing task state: {name}.json")
            continue
        try:
            t = load_json(p)
        except Exception as e:
            failures.append(f"tasks/{name}.json: invalid JSON ({e})")
            continue
        st = t.get("status")
        if st not in TASK_STATUSES:
            failures.append(f"tasks/{name}.json: invalid status {st!r}")
        if t.get("task") and t.get("task") != name:
            failures.append(f"tasks/{name}.json: task field mismatch ({t.get('task')})")
    print("[tasks] %d task states checked" % len(TASK_NAMES))


CROWDING_LEVELS = ("normal", "watch", "warn", "alert")
CROWDING_KEYS = ["crowding", "level", "band", "prev_month", "mom", "pct_rank",
                 "top1_pct", "top10_pct", "mtd_days", "sample_months",
                 "warn_pct", "alert_pct"]


def check_params():
    """参数唯一真源校验（v3.0）。

    目的：不允许再出现「多版本混用 / 同一阈值三处不同数值 / 脚本硬编码绕过参数」。
    任一条不过 = 参数体系已被污染，必须先修参数再跑流水线。
    """
    kn = Path(STATE).parent / "knowledge"
    cur = kn / "params_current.txt"
    if not cur.exists():
        failures.append("params: knowledge/params_current.txt 缺失")
        return
    ver = cur.read_text(encoding="utf-8").strip()
    pfile = kn / f"params_{ver}.json"
    if not pfile.exists():
        failures.append(f"params: params_current.txt={ver} 但 {pfile.name} 不存在")
        return
    try:
        p = load_json(pfile)
    except Exception as e:
        failures.append(f"params: {pfile.name} 解析失败 ({e})")
        return

    if p.get("version") != ver:
        failures.append(f"params: 文件名版本 {ver} 与内部 version={p.get('version')} 不一致")

    # ① 禁止镜像段：regime 基础仓位只允许存在于 regime.base_position_pct
    if "regime_base_position_pct" in p:
        failures.append("params: 存在 regime_base_position_pct 镜像段（v3.0 已废止，唯一真源=regime.base_position_pct）")
    rp = (p.get("regime") or {}).get("base_position_pct") or {}
    for k in ("bull", "neutral", "bear"):
        v = rp.get(k)
        if not isinstance(v, (int, float)) or not (0 < v <= 100):
            failures.append(f"params: regime.base_position_pct.{k} 非法（{v}）")

    # ② 选股：target_zone 每个键必须是 2 元素数值区间，不得夹带说明键
    tz = (p.get("selection_method") or {}).get("target_zone") or {}
    if not tz:
        failures.append("params: selection_method.target_zone 为空")
    for k, v in tz.items():
        if not (isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, (int, float)) for x in v)):
            failures.append(f"params: target_zone.{k} 非 [lo,hi] 区间（{v}）——不得在 target_zone 内放说明键")

    # ③ 质量分权重归一（v3.1 起 weights 已 retired，仅当仍在使用时才校验）
    rq = p.get("researcher_quality") or {}
    w = rq.get("weights") or {}
    if w.get("_status") != "retired_v3_1":
        ws = sum(float(w.get(k, 0)) for k in ("roe_ttm", "net_margin_ttm", "gross_margin_ttm", "tr_yoy"))
        if abs(ws - 1.0) > 1e-6:
            failures.append(f"params: researcher_quality.weights 四因子权重和 = {ws:.4f}，应为 1.0")

    # ③b 排序口径（v3.1）：研究员不得再承担排序，必须听选股分
    f_act = (rq.get("formula") or {}).get("active")
    if f_act != "picker_only":
        failures.append(f"params: researcher_quality.formula.active = {f_act}，v3.1 起必须为 picker_only（排序听选股分）")
    if (rq.get("ranking_basis") or "") != "selection_score":
        failures.append("params: researcher_quality.ranking_basis 必须为 selection_score（财务不得再参与排名）")

    # ④ 三档买点份额归一
    pz = p.get("price_zone_rule") or {}
    ts = sum(float((pz.get(f"tranche{i}") or {}).get("weight_share", 0)) for i in (1, 2, 3))
    if abs(ts - 1.0) > 1e-6:
        failures.append(f"params: price_zone_rule 三档 weight_share 和 = {ts:.4f}，应为 1.0")
    if float(pz.get("guard_drop_pct", 0)) >= float((pz.get("tranche3") or {}).get("offset_pct", 0)):
        failures.append("params: guard_drop_pct 必须低于 tr3 偏移（否则保护线失效）")

    # ⑤ 因子权重归一（compute_full_market 无条件读取，缺 weight 会 KeyError）
    fac = ((p.get("strategy") or {}).get("factors") or {})
    bad = [k for k, v in fac.items() if not isinstance(v, dict) or "weight" not in v]
    if bad:
        failures.append(f"params: strategy.factors 含非因子键 {bad}（会导致 compute_full_market KeyError）")
    else:
        fw = sum(float(v["weight"]) for v in fac.values())
        if abs(fw - 1.0) > 1e-6:
            failures.append(f"params: strategy.factors 权重和 = {fw:.4f}，应为 1.0")

    # ⑤b 熔断口径（v3.2）：分档降仓、不清仓
    circ = (p.get("risk") or {}).get("circuit") or {}
    if not circ:
        failures.append("params: risk.circuit 段缺失（v3.2 起熔断口径唯一真源）")
    else:
        steps = circ.get("steps") or []
        if not steps:
            failures.append("params: risk.circuit.steps 为空")
        for st in steps:
            if not isinstance(st.get("drawdown_pct"), (int, float)):
                failures.append(f"params: circuit.steps 缺 drawdown_pct（{st}）")
            tgt = st.get("target_position_pct")
            if not isinstance(tgt, (int, float)) or not (0 < tgt < 100):
                failures.append(f"params: circuit.steps.target_position_pct 非法（{tgt}），必须 0<t<100（清仓应走 liquidate_pct）")
        rraw = circ.get("rearm_drawdown_pct")
        if not isinstance(rraw, (int, float)):
            failures.append("params: circuit.rearm_drawdown_pct 缺失")
        elif steps and isinstance(steps[0].get("drawdown_pct"), (int, float)) and rraw <= steps[0]["drawdown_pct"]:
            failures.append(f"params: circuit.rearm_drawdown_pct({rraw}) 必须浅于首个触发档({steps[0]['drawdown_pct']})，否则永不解除")
        if circ.get("mode") != "step_down_no_liquidate":
            failures.append(f"params: circuit.mode = {circ.get('mode')}，v3.2 起必须为 step_down_no_liquidate")
        if "drawdown_halve_pct" in (p.get("risk") or {}):
            failures.append("params: risk 下仍存在 drawdown_halve_pct 旧字段（v3.2 已废止，改由 circuit.steps 表达）")

    # ⑤c v3.3 四项变更落地校验
    _vet = p.get("researcher_veto") or {}
    if _vet.get("logic") != "AND" or _vet.get("net_margin_below") != 5.0:
        failures.append(f"params: researcher_veto 应为 AND / 5.0（v3.3 放宽以扩大候选池），当前 {_vet.get('logic')} / {_vet.get('net_margin_below')}")
    _tpt = (p.get("risk") or {}).get("take_profit_trailing") or {}
    if not _tpt.get("enabled"):
        failures.append("params: risk.take_profit_trailing.enabled 必须为 true（v3.3 止盈改为一次减半+移动止损）")
    elif int(_tpt.get("max_rounds") or 0) != 1:
        failures.append(f"params: take_profit_trailing.max_rounds 必须为 1（禁止反复减半），当前 {_tpt.get('max_rounds')}")
    if not (p.get("execution_queue") or {}).get("topup", {}).get("enabled"):
        failures.append("params: execution_queue.topup 应启用（每日补仓，v3.3）")
    _bc = (p.get("position_limits") or {}).get("bull_concentration") or {}
    if not _bc.get("enabled"):
        failures.append("params: position_limits.bull_concentration 应启用（牛市集中持仓，v3.3）")
    else:
        _n = _bc.get("bull_max_holdings")
        _mx = (p.get("position_limits") or {}).get("max_holdings")
        if not isinstance(_n, int) or _n <= 0:
            failures.append(f"params: bull_concentration.bull_max_holdings 非法（{_n}）")
        elif isinstance(_mx, int) and _n > _mx:
            failures.append(f"params: bull_max_holdings({_n}) 不得大于 max_holdings({_mx})")
    if not (p.get("price_zone_rule") or {}).get("bull_rush_rule", {}).get("enabled"):
        failures.append("params: bull_rush_rule.enabled 应为 true（v3.3 打开牛市追涨）")

    # ⑤d v3.3 执行脚本必须存在（补仓/集中由持仓管家每日调用，缺脚本则策略无法落地）
    _root = Path(STATE).parent
    for _rel in ("scripts/daily_position_manage.py",):
        if not (_root / _rel).exists():
            failures.append(f"params: 缺少执行脚本 {_rel}（v3.3 的每日补仓/集中依赖它，缺则回测结论无法在实盘复现）")

    # ⑥ 脚本不得再访问已废止的镜像字段（防回归）
    scripts = Path(STATE).parent / "scripts"
    if scripts.is_dir():
        import re
        pat = re.compile(r"""(\[\s*["']regime_base_position_pct["']\s*\]|\.get\(\s*["']regime_base_position_pct["'])""")
        for fp in sorted(scripts.glob("*.py")):
            try:
                src = fp.read_text(encoding="utf-8")
            except Exception:
                continue
            for i, line in enumerate(src.splitlines(), 1):
                if pat.search(line):
                    failures.append(f"params: {fp.name}:{i} 仍读取已废止字段 regime_base_position_pct")

    print(f"[params] current={ver} ({pfile.name}) 校验完成")


def check_crowding():
    """data/warehouse/crowding/: 市场拥挤度序列与快照（v2.2 第 7 维）。"""
    wh = STATE.parent / "data" / "warehouse" / "crowding"
    if not wh.exists():
        failures.append("missing crowding dir: %s (run scripts/compute_crowding.py)" % wh)
        return

    hist_p = wh / "history.csv"
    if not hist_p.exists():
        failures.append("crowding/history.csv missing")
    else:
        rows = [x for x in hist_p.read_text(encoding="utf-8").splitlines() if x.strip()]
        if len(rows) < 2:
            failures.append("crowding/history.csv has no data rows")
        else:
            print("[crowding] history.csv %d months" % (len(rows) - 1))

    latest_p = wh / "latest.json"
    if not latest_p.exists():
        failures.append("crowding/latest.json missing")
        return
    try:
        c = load_json(latest_p)
    except Exception as e:
        failures.append("crowding/latest.json invalid JSON (%s)" % e)
        return

    for k in CROWDING_KEYS:
        if k not in c:
            failures.append("crowding/latest.json missing key: %s" % k)

    v = c.get("crowding")
    if not isinstance(v, (int, float)) or not (0 < v < 100):
        failures.append("crowding/latest.json: crowding out of range (%r)" % (v,))
    if c.get("level") not in CROWDING_LEVELS:
        failures.append("crowding/latest.json: invalid level %r" % (c.get("level"),))
    t1, t10 = c.get("top1_pct"), c.get("top10_pct")
    if isinstance(t1, (int, float)) and isinstance(t10, (int, float)) and t1 > t10:
        failures.append("crowding/latest.json: top1_pct > top10_pct (抱团深度口径倒置)")

    reg_p = STATE / "regime.json"
    if reg_p.exists():
        try:
            reg = load_json(reg_p)
            rc = reg.get("crowding")
            if isinstance(rc, dict) and isinstance(rc.get("value"), (int, float)) \
                    and isinstance(v, (int, float)):
                if abs(rc["value"] - v) > 0.5:
                    failures.append("regime.json crowding.value %.2f != latest.json %.2f"
                                    % (rc["value"], v))
                if rc.get("level") not in CROWDING_LEVELS:
                    failures.append("regime.json: invalid crowding.level %r" % (rc.get("level"),))
            if reg.get("date") and c.get("trade_date") and str(c["trade_date"]) < str(reg["date"]):
                print("[crowding] WARN latest.json trade_date %s 落后 regime date %s"
                      % (c["trade_date"], reg["date"]))
        except Exception as e:
            failures.append("regime.json crowding consistency check failed (%s)" % e)

    print("[crowding] %s = %.2f%% (%s / %s)" % (c.get("trade_date"), v, c.get("level"), c.get("band")))


def latest_data_date():
    if not DATA.exists():
        return None
    dirs = sorted(d.name.replace("daily_", "") for d in DATA.glob("daily_*") if d.is_dir())
    return dirs[-1] if dirs else None


def _record_count(payload):
    """Best-effort record count across the daily_* file shapes."""
    if isinstance(payload, list):
        return len(payload)
    for k in ("records", "items", "dimensions", "top_gainers", "net_buy_top10"):
        v = payload.get(k)
        if isinstance(v, (list, dict)):
            return len(v)
    return 1


def check_data(date_str):
    d = DATA / f"daily_{date_str}"
    if not d.exists():
        failures.append(f"data dir missing: {d}")
        return
    meta_p = d / "meta.json"
    if not meta_p.exists():
        failures.append(f"{d}/meta.json missing")
        return
    try:
        meta = load_json(meta_p)
    except Exception as e:
        failures.append(f"meta.json invalid JSON ({e})")
        return
    if meta.get("degraded"):
        print(f"[data] {date_str} marked degraded: {meta.get('notes')}")
    for f in DATA_CORE_FILES:
        p = d / f
        if not p.exists():
            failures.append(f"core data file missing: {f}")
            continue
        try:
            payload = load_json(p)
        except Exception as e:
            failures.append(f"{f}: invalid JSON ({e})")
            continue
        n = _record_count(payload)
        if n == 0:
            failures.append(f"{f}: empty")
        else:
            print(f"[data] {f}: {n} records")
    for f in DATA_OPTIONAL_FILES:
        p = d / f
        if not p.exists():
            print(f"[data] {f}: absent (non-core)")
            continue
        try:
            payload = load_json(p)
            n = _record_count(payload)
            print(f"[data] {f}: {n} records")
        except Exception as e:
            failures.append(f"{f}: invalid JSON ({e})")


def main():
    global STATE, DATA
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="E:/cashfree/agent")
    ap.add_argument("--date", default=None)
    args = ap.parse_args()

    STATE = Path(args.base) / "state"
    DATA = Path(args.base) / "data"

    date_str = args.date or latest_data_date()

    check_state()
    check_business()
    check_tasks()
    check_params()
    check_crowding()
    if date_str:
        check_data(date_str)
    else:
        print("[data] no daily_* data dir found, skipping data check")

    if failures:
        print("\n=== RESULT: FAIL ===")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("\n=== RESULT: PASS ===")
    sys.exit(0)


if __name__ == "__main__":
    main()
