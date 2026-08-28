# -*- coding: utf-8 -*-
"""多 agent 并行编排（orchestrator-worker）。

定位（如实，不吹成 AutoGen）：线程池级的批处理编排——dispatcher 把
N 个研究任务并行派发给 N 个独立 worker（每个 worker 是一个标准
Agent 实例，复用全部熔断/逐出/写门），失败隔离，聚合输出统计。

值得拆多 agent 的判断标准（本仓库的答案）：任务天然可分（多标的）、
单 agent 串行等待时间长（LLM 调用是 IO 等待，GIL 不构成瓶颈）。
"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from agent.loop import Agent


def run_worker(llm_factory, task, max_steps, log_dir, **agent_kwargs):
    """单个 worker：独立 Agent 实例 + 独立 LLM 连接（线程安全边界）。

    llm_factory 每线程新建（requests.Session 不跨线程共享），
    异常在 worker 内部消化——失败返回 stopped 字段，不抛出线程池。
    """
    t0 = time.time()
    try:
        agent = Agent(llm=llm_factory(), max_steps=max_steps, **agent_kwargs)
        agent.retry_sleep = 0  # 并行编排：通道故障立即熔断，不在池内睡眠重试
        run = agent.run(task, log_dir=log_dir)
        return {
            "task": task,
            "ok": run.stopped in ("done", "forced_final") and bool(run.answer),
            "stopped": run.stopped,
            "steps": run.steps,
            "secs": round(time.time() - t0, 1),
            "answer": run.answer or "",
            "log": run.log_path,
        }
    except Exception as e:
        # 兜底：worker 级任何异常（如 LLM 构造失败）都转为失败结果，
        # 不让单个 worker 拖垮整个编排
        return {"task": task, "ok": False, "stopped": "worker_error",
                "steps": 0, "secs": round(time.time() - t0, 1),
                "answer": "", "log": None, "error": str(e)[:200]}


def research_parallel(llm_factory, tasks, max_steps=12, workers=3,
                      log_dir=None, **agent_kwargs):
    """并行研究 N 个标的。返回 {stats, results}。

    stats: 总耗时/成功数/并行度（wall vs sum——并行收益一眼可见）。
    results: 每个 worker 的运行结果（按完成序）。
    """
    t0 = time.time()
    results = []
    workers = max(1, min(workers, len(tasks) or 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_worker, llm_factory, t, max_steps,
                               log_dir, **agent_kwargs): t for t in tasks}
        for fut in as_completed(futures):
            results.append(fut.result())
    # 按原任务顺序聚合（可复现输出）
    order = {t: i for i, t in enumerate(tasks)}
    results.sort(key=lambda r: order.get(r["task"], 999))
    wall = round(time.time() - t0, 1)
    total = round(sum(r["secs"] for r in results), 1)
    stats = {
        "n": len(tasks),
        "workers": workers,
        "wall_secs": wall,
        "sum_secs": total,
        "ok": sum(1 for r in results if r["ok"]),
        "speedup": round(total / wall, 2) if wall > 0 else 0,
    }
    return {"stats": stats, "results": results}


def render_report(payload):
    """聚合报告：对比表 + 每个标的的答案。"""
    stats, results = payload["stats"], payload["results"]
    lines = ["# 并行研究报告（%d workers × %d 任务）" % (
        stats["workers"], stats["n"]), ""]
    lines.append("| 指标 | 值 |")
    lines.append("|---|---|")
    lines.append("| 总耗时(wall) | %.1fs |" % stats["wall_secs"])
    lines.append("| 串行合计(sum) | %.1fs |" % stats["sum_secs"])
    lines.append("| 并行加速比 | %.2fx |" % stats["speedup"])
    lines.append("| 成功 | %d/%d |" % (stats["ok"], stats["n"]))
    lines.append("")
    lines.append("| 任务 | 状态 | 步数 | 耗时 |")
    lines.append("|---|---|---|---|")
    for r in results:
        lines.append("| %s | %s%s | %d | %.1fs |" % (
            r["task"], "✓" if r["ok"] else "✗", r["stopped"],
            r["steps"], r["secs"]))
    lines.append("")
    for r in results:
        lines.append("---\n\n## %s（%s，%d步，%.1fs）\n" % (
            r["task"], r["stopped"], r["steps"], r["secs"]))
        lines.append(r["answer"] or "（未产出答案）\n")
    return "\n".join(lines)
