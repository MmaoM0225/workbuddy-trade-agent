# -*- coding: utf-8 -*-
"""拥挤度邮件渲染彩排：完全隔离，不触碰正式 state/regime.json。

做法：把 M.ROOT 指向 test/ 目录，render_regime 只会读 test/state/regime.json。
（上一版踩过的坑：直接在正式文件上改再还原，渲染中途抛异常会留下污染。
  改用 ROOT 隔离后无此风险。）

用法：python test/scripts/test_crowding_mail.py
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(BASE, "scripts"))

import send_report_mail as M  # noqa: E402

REAL = os.path.join(BASE, "state", "regime.json")
SANDBOX = os.path.join(BASE, "test")           # 沙箱根目录
SANDBOX_REGIME = os.path.join(SANDBOX, "state", "regime.json")
OUTDIR = os.path.join(BASE, "test", "reports")

SCENARIOS = [
    # name, 值, level, band, mom, source, overlay, nature, position_cap
    ("watch_41", 41.18, "watch", "升温", -1.69, "mtd", "无干预", "reversal_concentration", 50),
    ("warn_47", 47.30, "warn", "极端抱团", 0.85, "mtd", "禁新建仓", "high_position", 50),
    ("alert_51", 51.20, "alert", "结构恶化", 2.40, "mtd", "降级neutral / 仓位-20pp", "high_position", 30),
    ("missing", None, None, None, None, None, None, None, 50),
]


def main():
    real = json.load(open(REAL, encoding="utf-8"))
    os.makedirs(os.path.dirname(SANDBOX_REGIME), exist_ok=True)
    os.makedirs(OUTDIR, exist_ok=True)

    # 关键隔离：render_regime 读 ROOT/state/regime.json
    M.ROOT = SANDBOX

    ok = 0
    for name, val, lvl, band, mom, src, overlay, nature, cap in SCENARIOS:
        d = dict(real)
        d["date"] = "20261026"
        d["position_cap_pct"] = cap
        if val is None:
            d.pop("crowding", None)
        else:
            d["crowding"] = {
                "value": val, "source": src, "band": band, "level": lvl,
                "prev_month": 42.87, "mom": mom, "pct_rank": 74.7,
                "top1_pct": 17.66, "top10_pct": 55.48,
                "nature": nature, "cleared": False, "overlay": overlay,
                "top_pct": 5, "warn_pct": 45, "alert_pct": 50,
                "sample_months": 84, "mtd_days": 13,
            }
        json.dump(d, open(SANDBOX_REGIME, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

        try:
            html, err = M.render_regime("20261026")
        except Exception as e:  # noqa: BLE001
            print("[FAIL] %s 渲染异常: %s: %s" % (name, type(e).__name__, e))
            continue
        if err:
            print("[FAIL] %s: %s" % (name, err))
            continue
        p = os.path.join(OUTDIR, "mail_regime_test_%s.html" % name)
        open(p, "w", encoding="utf-8").write(html)
        has = "市场拥挤度" in html
        print("[OK] %-9s -> %s (%d bytes, 含拥挤度区块=%s)" % (name, os.path.basename(p), len(html), has))
        ok += 1

    print("[OK] 成功 %d/%d；正式 state/regime.json 未被触碰" % (ok, len(SCENARIOS)))
    return 0 if ok == len(SCENARIOS) else 1


if __name__ == "__main__":
    sys.exit(main())
