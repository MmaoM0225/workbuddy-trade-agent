#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""task_status.py - 多 Agent 流水线任务状态管理（事件触发调度）

状态机：undo -> doing -> done。done 可带 reason=non-trading-day 表示当日跳过
（下游看到 done 即通过等待，再走自己的交易日校验自行 skip）。

单一写者原则：每个任务只写自己的 state/tasks/<task>.json，只读他人文件。

用法：
  set  <task> <undo|doing|done> [--date YYYYMMDD] [--reason ...] [--artifact ...]
  wait <task> --deps dep1,dep2 [--interval 1] [--max-wait 9]
  get  <task>
  list

wait 退出码：0 = 前置全部 done；1 = 本次等待窗口内未就绪（调用方应重复调用）；
2 = 参数错误。单次调用默认最多阻塞 9 分钟（受 Bash 工具 10 分钟超时限制），
调用方通过重复调用实现长轮询，自行控制总预算。
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
TASKS_DIR = BASE / "state" / "tasks"

TASKS = [
    "data_officer",      # 数据员
    "market_analyst",    # 市场分析师
    "position_manager",  # 持仓管家
    "inspector",         # 总控
    "stock_picker",      # 量化选股师
    "researcher",        # 个股研究员
    "position_builder",  # 建仓经理
    "reviewer",          # 复盘官
    "archivist",         # 档案管理员
]

# 依赖关系（与 README 流水线一致）：
#   data_officer -> market_analyst -> position_manager -> inspector
#   stock_picker -> researcher -> position_builder
#   reviewer -> archivist


def task_file(task):
    return TASKS_DIR / (task + ".json")


def read_status(task):
    f = task_file(task)
    if not f.exists():
        return "undo"
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("status", "undo")
    except Exception:
        return "undo"


def cmd_set(args):
    if args.task not in TASKS:
        print("unknown task: %s (valid: %s)" % (args.task, ",".join(TASKS)))
        return 2
    if args.status not in ("undo", "doing", "done"):
        print("invalid status: %s (must be undo/doing/done)" % args.status)
        return 2
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "task": args.task,
        "status": args.status,
        "date": args.date,
        "reason": args.reason,
        "artifact": args.artifact,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    tmp = task_file(args.task).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(task_file(args.task))
    print("task %s -> %s (date=%s reason=%s)" % (args.task, args.status, args.date, args.reason))
    return 0


def cmd_wait(args):
    if args.task not in TASKS:
        print("unknown task: %s" % args.task)
        return 2
    deps = [d.strip() for d in args.deps.split(",") if d.strip()]
    unknown = [d for d in deps if d not in TASKS]
    if unknown:
        print("unknown deps: %s (valid: %s)" % (unknown, ",".join(TASKS)))
        return 2
    deadline = time.monotonic() + args.max_wait * 60
    waited = 0.0
    while True:
        pending = [d for d in deps if read_status(d) != "done"]
        if not pending:
            print("task %s: deps ready [%s]" % (args.task, ",".join(deps)))
            return 0
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print("task %s: NOT-READY pending=[%s] waited=%.1fmin (caller may retry)"
                  % (args.task, ",".join(pending), waited))
            return 1
        time.sleep(min(args.interval * 60, remaining))
        waited += args.interval


def cmd_get(args):
    if args.task not in TASKS:
        print("unknown task: %s" % args.task)
        return 2
    f = task_file(args.task)
    if not f.exists():
        print("%s: undo (no file)" % args.task)
        return 0
    print(f.read_text(encoding="utf-8"))
    return 0


def cmd_list(args):
    for t in TASKS:
        print("%-18s %s" % (t, read_status(t)))
    return 0


def main():
    p = argparse.ArgumentParser(description="pipeline task status")
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("set")
    ps.add_argument("task")
    ps.add_argument("status", choices=["undo", "doing", "done"])
    ps.add_argument("--date")
    ps.add_argument("--reason")
    ps.add_argument("--artifact")
    ps.set_defaults(fn=cmd_set)

    pw = sub.add_parser("wait")
    pw.add_argument("task")
    pw.add_argument("--deps", required=True)
    pw.add_argument("--interval", type=float, default=1.0, help="minutes between checks")
    pw.add_argument("--max-wait", type=float, default=9.0, help="max minutes this call blocks")
    pw.set_defaults(fn=cmd_wait)

    pg = sub.add_parser("get")
    pg.add_argument("task")
    pg.set_defaults(fn=cmd_get)

    pl = sub.add_parser("list")
    pl.set_defaults(fn=cmd_list)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
