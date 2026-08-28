#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多标的并行研究 CLI。

用法：
    python3 research.py "研究 600519" "研究 000001 平安银行" "研究 600036 招商银行"
    python3 research.py "研究 600519" "研究 000001" --workers 2 --llm hermes
"""
import argparse
import re
import time
from pathlib import Path

from agent.llm import LLMClient
from agent.llm_hermes import HermesLLM
from agent.orchestrator import render_report, research_parallel


def save_memo(task, result):
    """worker结果归档备忘录（与 main.save_memo 同格式，标注并行编排）。"""
    m = re.search(r"\b\d{6}\b", task)
    tag = m.group(0) if m else "misc"
    d = Path("memos")
    d.mkdir(exist_ok=True)
    p = d / ("%s_%s.md" % (time.strftime("%Y%m%d"), tag))
    p.write_text(
        "# 研究备忘录 %s\n\n- 任务：%s\n- 日期：%s\n- 运行：steps=%d "
        "stopped=%s（并行编排）\n\n---\n\n%s"
        % (tag, task, time.strftime("%Y-%m-%d %H:%M"),
           result["steps"], result["stopped"], result["answer"]),
        encoding="utf-8")
    return p


def main():
    ap = argparse.ArgumentParser(description="多标的并行研究（orchestrator-worker）")
    ap.add_argument("tasks", nargs="+", help='研究任务列表，每个一条')
    ap.add_argument("--workers", type=int, default=3, help="并行worker数，默认3")
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--llm", choices=["api", "hermes"], default="api")
    ap.add_argument("--save-memo", action="store_true")
    args = ap.parse_args()

    llm_factory = HermesLLM if args.llm == "hermes" else LLMClient

    print("[orchestrator] %d 任务 × %d workers，通道=%s\n"
          % (len(args.tasks), args.workers, args.llm))
    payload = research_parallel(llm_factory, args.tasks,
                                max_steps=args.max_steps,
                                workers=args.workers)
    print(render_report(payload))
    if args.save_memo:
        for r in payload["results"]:
            if r["ok"]:
                print("[memo] %s" % save_memo(r["task"], r))
    s = payload["stats"]
    print("\n[编排统计] wall=%.1fs sum=%.1fs 加速比=%.2fx 成功=%d/%d"
          % (s["wall_secs"], s["sum_secs"], s["speedup"], s["ok"], s["n"]))


if __name__ == "__main__":
    main()
