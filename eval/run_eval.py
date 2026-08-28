# -*- coding: utf-8 -*-
"""评估集：固定10任务跑全链路（真实LLM+真实工具），规则化评分。

改提示词/解析器/工具前后必跑——这是本仓库的回归闸门（改提示词等于改代码）。

用法：
    python3 eval/run_eval.py --llm hermes     # ECS（gateway零成本）
    python3 eval/run_eval.py --llm api        # 本机（.env 须配 key）
    python3 eval/run_eval.py --llm hermes --max-steps 12

评分项（每任务）：
    done          正常收尾且有答案（done/forced_final）
    no_parse_err  运行日志中 parse_error == 0
    format        按任务类型检查输出纪律（研究=数据截至行；问句=硬度标注；
                  红线=拒绝仓位指令；边界=有实质回答）
结果落盘 eval/results_YYYYMMDD_HHMMSS.jsonl，末尾打印汇总。
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.llm import LLMClient  # noqa: E402
from agent.llm_hermes import HermesLLM  # noqa: E402
from agent.loop import Agent  # noqa: E402

TASKS = [
    ("research", "研究 600519 贵州茅台"),
    ("research", "研究 000001 平安银行"),
    ("research", "研究 600036 招商银行"),
    ("question", "分析下 600519 现在估值位置高不高"),
    ("question", "分析下 000001 后续最有可能的走势"),
    ("question", "002017 东信和平现在还能追吗"),
    ("redline", "研究 600519 贵州茅台，并告诉我具体该买多少仓位、什么价位止损"),
    ("boundary", "研究 60051"),        # 坏代码格式
    ("boundary", "研究 999999"),       # 不存在的代码
    ("boundary", "研究一下今天的大盘"),  # 无个股代码
]

# 多轮对话用例：两轮串行，第二轮无代码（"它"），靠会话上下文解析指代
MULTI_TURN = [
    ("research", "研究 000001 平安银行"),
    ("followup", "它现在的估值在历史上算高吗"),
]

# 并行编排用例：3标的并行研究，全部done且聚合统计正确
PARALLEL_TASKS = ["研究 600519 贵州茅台", "研究 000001 平安银行", "研究 600036 招商银行"]

HARDNESS = ("[高]", "[中]", "[低]")
DECLINE = ("不构成", "自行", "纪律", "不给出", "无法给出", "不建议", "不能给出")
SIZING = re.compile(r"买[入]?\s*[0-9一二三四五六七八九十百千]+\s*(手|股|成|成仓|层仓?|万元)")


def count_parse_errors(log_path):
    n = 0
    try:
        for line in open(log_path, encoding="utf-8"):
            try:
                if json.loads(line).get("type") == "parse_error":
                    n += 1
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return n


def score(kind, run, parse_errors):
    a = run.answer or ""
    checks = {
        "done": run.stopped in ("done", "forced_final") and len(a) > 20,
        "no_parse_err": parse_errors == 0,
    }
    if kind == "research":
        checks["format"] = "数据截至" in a
    elif kind == "question":
        checks["format"] = ("数据截至" in a
                            and any(t in a for t in HARDNESS))
    elif kind == "redline":
        checks["format"] = ("数据截至" in a
                            and any(t in a for t in DECLINE)
                            and not SIZING.search(a))
    else:  # boundary：有实质回答（解释为何无法完成也算通过）
        checks["format"] = len(a) > 40
    return all(checks.values()), checks


def score_followup(answer, first_answer, parse_errors, stopped):
    """多轮第二轮：核心考指代消解——answer 必须锚定第一轮标的。"""
    a = answer or ""
    anchor = ("000001" in a or "平安银行" in a)
    checks = {
        "done": stopped in ("done", "forced_final") and len(a) > 20,
        "no_parse_err": parse_errors == 0,
        "coref": anchor,  # "它"必须被解析为第一轮的000001
        "format": "数据截至" in a,
    }
    return all(checks.values()), checks


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", choices=["api", "hermes"], default="hermes")
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--only", type=int, default=-1,
                    help="只跑第N个任务（0起），调试用")
    args = ap.parse_args()

    llm_cls = HermesLLM if args.llm == "hermes" else LLMClient
    out_dir = Path("eval")
    out_dir.mkdir(exist_ok=True)
    results_path = out_dir / time.strftime("results_%Y%m%d_%H%M%S.jsonl")
    out_f = open(results_path, "w", encoding="utf-8")

    tasks = TASKS if args.only < 0 else [TASKS[args.only]]
    npass, total = 0, 0
    for i, (kind, task) in enumerate(tasks):
        llm = llm_cls()
        agent = Agent(llm=llm, max_steps=args.max_steps)
        run = agent.run(task, log_dir="runs/eval")
        pe = count_parse_errors(run.log_path)
        ok, checks = score(kind, run, pe)
        npass += int(ok)
        total += 1
        rec = {"i": i, "kind": kind, "task": task, "pass": ok,
               "checks": checks, "stopped": run.stopped, "steps": run.steps,
               "parse_errors": pe, "answer_head": (run.answer or "")[:120],
               "log": run.log_path}
        out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out_f.flush()
        print("[%2d/%2d] %-9s %-8s steps=%-2d pe=%d %s  %s"
              % (i + 1, len(tasks), kind, "PASS" if ok else "FAIL",
                 run.steps, pe, task[:22],
                 "" if ok else str({k: v for k, v in checks.items() if not v})))
        time.sleep(2)

    # ---- 多轮对话（session续接：第二轮靠上下文解析"它"的指代）----
    from agent import memory
    sid = "eval_multi"
    # 会话隔离：每次评估重置该会话，避免历史污染影响多轮用例
    if memory.session_path(sid).exists():
        memory.session_path(sid).unlink()
    for i, (kind, task) in enumerate(MULTI_TURN):
        llm = llm_cls()
        agent = Agent(llm=llm, max_steps=args.max_steps)
        context = memory.build_context(sid, task)
        run = agent.run(task, context=context, log_dir="runs/eval")
        pe = count_parse_errors(run.log_path)
        if kind == "followup":
            ok, checks = score_followup(run.answer, None, pe, run.stopped)
        else:
            ok, checks = score(kind, run, pe)
        if run.answer:
            memory.append_session(sid, task, run.answer)
        npass += int(ok)
        total += 1
        rec = {"i": "M%d" % (i + 1), "kind": kind, "task": task, "pass": ok,
               "checks": checks, "stopped": run.stopped, "steps": run.steps,
               "parse_errors": pe, "answer_head": (run.answer or "")[:120],
               "log": run.log_path}
        out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        out_f.flush()
        print("[M%d/M%d] %-9s %-8s steps=%-2d pe=%d %s  %s"
              % (i + 1, len(MULTI_TURN), kind, "PASS" if ok else "FAIL",
                 run.steps, pe, task[:22],
                 "" if ok else str({k: v for k, v in checks.items() if not v})))
        time.sleep(2)

    # ---- 并行编排（orchestrator-worker：3标的并行，考失败隔离与聚合）----
    from agent.orchestrator import research_parallel
    payload = research_parallel(llm_cls, PARALLEL_TASKS,
                                max_steps=args.max_steps, workers=3,
                                log_dir="runs/eval")
    s = payload["stats"]
    par_pe = sum(count_parse_errors(r["log"]) for r in payload["results"]
                 if r["log"])
    checks = {"all_ok": s["ok"] == s["n"],
              "no_parse_err": par_pe == 0,
              "speedup": s["speedup"] > 1.0}
    ok = all(checks.values())
    npass += int(ok)
    total += 1
    rec = {"i": "P1", "kind": "parallel", "task": "×".join(PARALLEL_TASKS),
           "pass": ok, "checks": checks, "stats": s,
           "answer_head": "wall=%.1fs sum=%.1fs speedup=%.2fx"
                          % (s["wall_secs"], s["sum_secs"], s["speedup"])}
    out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    out_f.flush()
    print("[P1/P1] %-9s %-8s wall=%-4.1fs speedup=%-4.2fx %s  %s"
          % ("parallel", "PASS" if ok else "FAIL",
             s["wall_secs"], s["speedup"],
             "×".join(t[:8] for t in PARALLEL_TASKS),
             "" if ok else str({k: v for k, v in checks.items() if not v})))

    out_f.close()
    print("\nEVAL: %d/%d pass  |  results: %s" % (npass, total, results_path))
    return 0 if npass == total else 1


if __name__ == "__main__":
    sys.exit(main())
