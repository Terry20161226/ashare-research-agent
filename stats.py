#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行观测画像：从 runs/ 日志聚合出系统的真实运行状态。

面试官问"你的 agent 跑得怎么样"时的数据答案：done率、步数分布、
parse_error 率、上下文峰值、工具调用分布、写门拦截次数、日期分布。

用法：
    python3 stats.py            # 全部日志（含 tests/ 与 eval/）
    python3 stats.py --prod     # 只看生产运行（runs/ 根目录）
    python3 stats.py --json     # 输出机器可读JSON
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

RUNS_DIR = Path("runs")


def scan(run_dir):
    """解析单个 jsonl 日志文件，返回运行画像 dict。"""
    rec = {"file": run_dir.name, "task": None, "steps": 0, "stopped": None,
           "parse_errors": 0, "llm_errors": 0, "write_blocked": 0,
           "context_peak": 0, "tools": Counter(), "tokens": 0,
           "first_ts": None, "last_ts": None}
    try:
        for line in run_dir.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            typ = r.get("type")
            if typ == "meta":
                rec["task"] = r.get("task")
            elif typ == "decision":
                rec["steps"] = max(rec["steps"], r.get("step", 0))
            elif typ == "tool_result":
                rec["tools"][r.get("tool", "?")] += 1
            elif typ == "parse_error":
                rec["parse_errors"] += 1
            elif typ == "llm_error":
                rec["llm_errors"] += 1
            elif typ == "write_blocked":
                rec["write_blocked"] += 1
            elif typ == "context":
                rec["context_peak"] = max(rec["context_peak"],
                                          r.get("chars", 0))
            elif typ == "final":
                rec["stopped"] = r.get("stopped")
                rec["tokens"] = r.get("tokens", 0)
            ts = r.get("ts")
            if ts:
                if rec["first_ts"] is None:
                    rec["first_ts"] = ts
                rec["last_ts"] = ts
    except OSError:
        pass
    return rec


def aggregate(recs):
    n = len(recs)
    done = sum(1 for r in recs if r["stopped"] in ("done", "forced_final"))
    pe = sum(r["parse_errors"] for r in recs)
    steps = [r["steps"] for r in recs if r["steps"] > 0]
    ctx = sorted(r["context_peak"] for r in recs if r["context_peak"] > 0)
    tools = Counter()
    for r in recs:
        tools.update(r["tools"])
    agg = {
        "runs": n,
        "done_rate": round(done / n, 3) if n else 0,
        "parse_errors": pe,
        "parse_error_rate": round(pe / n, 3) if n else 0,
        "avg_steps": round(sum(steps) / len(steps), 1) if steps else 0,
        "context_peak_p50": ctx[len(ctx) // 2] if ctx else 0,
        "context_peak_max": ctx[-1] if ctx else 0,
        "write_blocked": sum(r["write_blocked"] for r in recs),
        "tool_calls": dict(tools.most_common()),
        "total_tokens": sum(r["tokens"] for r in recs),
    }
    return agg


def report(agg, title):
    lines = ["## %s" % title, "",
             "| 指标 | 值 |", "|---|---|",
             "| 运行数 | %d |" % agg["runs"],
             "| done率 | %.1f%% |" % (agg["done_rate"] * 100),
             "| parse_error 总数/率 | %d / %.1f%% |" % (
                 agg["parse_errors"], agg["parse_error_rate"] * 100),
             "| 平均步数 | %.1f |" % agg["avg_steps"],
             "| 上下文峰值 p50/max | %d / %d 字符 |" % (
                 agg["context_peak_p50"], agg["context_peak_max"]),
             "| 写门拦截 | %d 次 |" % agg["write_blocked"],
             "| LLM token 合计 | %d |" % agg["total_tokens"],
             "| 工具调用分布 | %s |" % ", ".join(
                 "%s×%d" % kv for kv in agg["tool_calls"].items())]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="运行观测画像")
    ap.add_argument("--prod", action="store_true",
                    help="只看生产运行（runs/根目录，排除tests/与eval/）")
    ap.add_argument("--json", action="store_true", help="输出JSON")
    args = ap.parse_args()

    if args.prod:
        files = [f for f in RUNS_DIR.glob("*.jsonl")]
        title = "生产运行画像（runs/）"
    else:
        files = sorted(RUNS_DIR.rglob("*.jsonl"))
        title = "全量运行画像（runs/ 含测试与评估）"
    if not files:
        print("无运行日志。")
        return
    recs = [scan(f) for f in files]
    recs = [r for r in recs if r["task"] is not None]
    agg = aggregate(recs)
    if args.json:
        print(json.dumps(agg, ensure_ascii=False, indent=2))
    else:
        print(report(agg, title))
        print()


if __name__ == "__main__":
    sys.exit(main())
