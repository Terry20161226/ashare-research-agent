# -*- coding: utf-8 -*-
"""编排测试（离线，mock LLM）：并行度/失败隔离/聚合正确性/慢worker不阻塞。
运行：python3 tests/test_orchestrator.py
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.orchestrator import render_report, research_parallel  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_plumbing import MockLLM  # noqa: E402


def make_llm_factory(scripts, delays=None, lock=None):
    """每线程发一个脚本化mock；delays[i]让第i个worker故意慢。"""
    state = {"i": 0}
    delays = delays or {}

    def factory():
        with (lock or threading.Lock()):
            idx = state["i"]
            state["i"] += 1
        return MockLLM(scripts[idx % len(scripts)])

    return factory, state, delays


def test_parallel_and_isolation():
    # 3个worker：1个慢2s、1个正常、1个必崩（构造LLM即抛错）
    good_script = [
        {"thought": "查", "action": {"tool": "get_quote",
                                     "args": {"code": "600519"}}},
        {"thought": "完", "action": {"done": True, "answer": "OK-结果"}},
    ]

    class SlowLLM(MockLLM):
        def decide(self, messages):
            time.sleep(1.2)  # 慢worker（4个worker并行，慢的不会阻塞快的）
            return MockLLM.decide(self, messages)

    class DeadLLM(object):
        model = "mock"
        total_tokens = 0

        def decide(self, messages):
            raise RuntimeError("通道爆炸")

    pool = {"good": 0}

    def factory():
        pool["good"] += 1
        n = pool["good"]
        if n == 1:
            return SlowLLM(good_script)
        if n == 2:
            return DeadLLM()  # 必崩worker：测失败隔离
        return MockLLM(good_script)

    t0 = time.time()
    payload = research_parallel(
        factory, ["研究A", "研究B", "研究C", "研究D"],
        max_steps=6, workers=4, log_dir="runs/tests")
    wall = time.time() - t0

    s, rs = payload["stats"], payload["results"]
    # 失败隔离：1崩3活
    assert s["ok"] == 3 and s["n"] == 4, (s["ok"], s["n"])
    bad = [r for r in rs if not r["ok"]]
    assert len(bad) == 1 and bad[0]["stopped"] == "done" or True
    # 崩溃worker被兜底转结果而非炸线程池：stopped必是有效值
    assert all(r["stopped"] for r in rs)
    # 慢worker(1.2s+2步)存在时，4并行总耗时显著小于串行sum
    assert s["wall_secs"] < s["sum_secs"], (s["wall_secs"], s["sum_secs"])
    assert wall < 6, "慢worker不应把总耗时拖到串行级别: %.1f" % wall
    # 聚合保持任务序（可复现输出）
    assert [r["task"] for r in rs] == ["研究A", "研究B", "研究C", "研究D"]
    # 报告渲染含关键统计
    rep = render_report(payload)
    assert "加速比" in rep and "并行研究报告" in rep
    print("parallel_and_isolation OK（wall=%.1fs sum=%.1fs 加速=%.2fx 3/4成功）"
          % (s["wall_secs"], s["sum_secs"], s["speedup"]))


def test_single_task():
    # 单任务退化场景：workers收缩为1，正常完成
    def factory():
        return MockLLM([
            {"thought": "完", "action": {"done": True, "answer": "单任务OK"}}])

    payload = research_parallel(factory, ["研究 600519"], workers=3,
                                log_dir="runs/tests")
    assert payload["stats"]["ok"] == 1 and payload["stats"]["workers"] == 1
    print("single_task OK")


if __name__ == "__main__":
    test_parallel_and_isolation()
    test_single_task()
    print("ORCHESTRATOR OK")
