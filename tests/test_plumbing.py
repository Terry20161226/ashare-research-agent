# -*- coding: utf-8 -*-
"""全链路管道测试：假 LLM（脚本化决策）+ 真主循环 + 真工具 + 真日志。

不需要 API key。验证：决策解析、工具执行、结果回灌、截断、
步数硬顶、forced_final、jsonl 落盘。
运行：python tests/test_plumbing.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.loop import Agent  # noqa: E402


class MockLLM:
    """脚本化决策：行情 -> K线 -> 资金流 -> done。记录见到的 messages。"""

    def __init__(self, script):
        self.script = script
        self.i = 0
        self.total_tokens = 0
        self.messages_seen = None
        self.model = "mock"

    def decide(self, messages):
        self.messages_seen = list(messages)
        obj = self.script[min(self.i, len(self.script) - 1)]
        self.i += 1
        return obj, json.dumps(obj, ensure_ascii=False)


GOOD_SCRIPT = [
    {"thought": "先看行情快照", "action": {"tool": "get_quote", "args": {"code": "600519"}}},
    {"thought": "看近10日走势", "action": {"tool": "get_kline", "args": {"code": "600519", "days": 10}}},
    {"thought": "看主力资金", "action": {"tool": "get_fund_flow", "args": {"code": "600519", "days": 5}}},
    {"thought": "数据足够，成稿", "action": {"done": True, "answer": "MOCK研究草稿：管道验证用，含真实数据引用。"}},
]

# 永远要求调工具，测步数硬顶 + forced_final 收尾
NEVER_DONE = [{"thought": "还要查", "action": {"tool": "get_quote", "args": {"code": "600519"}}}]


class LoopMock(object):
    """前 n_tools 次决策永远返回工具调用，之后返回 done。
    用于精确控制「第几次决策才开始收尾」。"""

    def __init__(self, n_tools, answer="FORCED最终稿"):
        self.n_tools = n_tools
        self.i = 0
        self.total_tokens = 0
        self.model = "mock"
        self.messages_seen = None
        self.answer = answer

    def decide(self, messages):
        self.messages_seen = list(messages)
        if self.i < self.n_tools:
            obj = {"thought": "还要查",
                   "action": {"tool": "get_quote", "args": {"code": "600519"}}}
        else:
            obj = {"thought": "收尾",
                   "action": {"done": True, "answer": self.answer}}
        self.i += 1
        return obj, json.dumps(obj, ensure_ascii=False)


def test_happy_path():
    mock = MockLLM(GOOD_SCRIPT)
    agent = Agent(llm=mock, max_steps=10)
    run = agent.run("研究 600519 贵州茅台", log_dir=None)
    assert run.stopped == "done", run.stopped
    assert "MOCK" in run.answer
    assert run.steps == 4, run.steps
    # 验证消息结构：tool 结果确实回灌给了 LLM
    msgs = mock.messages_seen
    tool_msgs = [m for m in msgs if m["role"] == "user" and "执行结果" in m["content"]]
    assert len(tool_msgs) == 3, "应有3条工具结果回灌，实际%d" % len(tool_msgs)
    # 最后一次决策（done步）看到的最后一条消息 = 资金流工具结果
    assert "[工具 get_fund_flow 执行结果]" in msgs[-1]["content"]
    # 日志落盘且含meta/final
    log_text = Path(run.log_path).read_text(encoding="utf-8")
    assert '"type": "meta"' in log_text and '"prompt_hash"' in log_text
    assert '"type": "final"' in log_text
    print("happy_path OK  steps=%d log=%s" % (run.steps, run.log_path))


def test_max_steps_forced_final():
    # 前5次决策永远要查数据 -> 5步耗尽 -> forced_final 一次无工具收尾
    mock = LoopMock(n_tools=5)
    agent = Agent(llm=mock, max_steps=5)
    run = agent.run("研究 600519", log_dir=None)
    assert run.steps == 5, run.steps
    assert run.stopped == "forced_final", run.stopped
    assert run.answer == "FORCED最终稿"
    # 硬顶生效：工具最多被执行5次（第6次调用是收尾，不算工具步）
    tool_msgs = [m for m in mock.messages_seen
                 if m["role"] == "user" and "执行结果" in m["content"]]
    assert len(tool_msgs) == 5, "工具执行次数应被硬顶在5，实际%d" % len(tool_msgs)
    print("max_steps_forced_final OK  steps=%d stopped=%s" % (run.steps, run.stopped))


def test_max_steps_runaway():
    # 收尾机会仍然不听话（永远要查）：answer 为 None，日志可查，不崩
    mock = LoopMock(n_tools=999)
    agent = Agent(llm=mock, max_steps=5)
    run = agent.run("研究 600519", log_dir=None)
    assert run.stopped == "max_steps", run.stopped
    assert run.answer is None
    assert Path(run.log_path).exists()
    print("max_steps_runaway OK  stopped=%s（失控被熔断，未产出答案）" % run.stopped)


def test_parse_error_recovery():
    # 第一次输出无法解析的垃圾，之后恢复正常：应通过提示词纠偏恢复而不是崩
    from agent.llm import DecisionParseError

    class FlakyMock(MockLLM):
        def decide(self, messages):
            if self.i == 1:  # 第一次调用抛解析错误
                self.i += 1
                raise DecisionParseError("这不是JSON，随便说说")
            return super().decide(messages)

    mock = FlakyMock(GOOD_SCRIPT)
    agent = Agent(llm=mock, max_steps=10)
    run = agent.run("研究 600519", log_dir=None)
    assert run.stopped == "done", run.stopped
    assert run.answer and "MOCK" in run.answer
    print("parse_error_recovery OK  steps=%d" % run.steps)


def test_parse_failures_circuit_breaker():
    # 连续3次解析失败 -> 熔断中止，answer=None，不无限烧步数
    from agent.llm import DecisionParseError

    class GarbageMock(object):
        model = "mock"
        total_tokens = 0

        def decide(self, messages):
            raise DecisionParseError("垃圾输出" * 100)

    agent = Agent(llm=GarbageMock(), max_steps=10)
    run = agent.run("研究 600519", log_dir=None)
    assert run.stopped == "parse_failures", run.stopped
    assert run.answer is None
    assert run.steps <= 3, "熔断应在3步内生效，实际%d" % run.steps
    print("parse_failures_circuit_breaker OK  stopped=%s steps=%d"
          % (run.stopped, run.steps))


def test_llm_error_recovery():
    # LLM通道故障2次后恢复：原地重试（不追加消息），最终正常done
    class DownThenUp(MockLLM):
        def __init__(self, script, n_down):
            MockLLM.__init__(self, script)
            self.n_down = n_down

        def decide(self, messages):
            if self.i < self.n_down:
                self.i += 1
                raise RuntimeError("gateway超时模拟")
            return MockLLM.decide(self, messages)

    mock = DownThenUp(GOOD_SCRIPT, n_down=2)
    agent = Agent(llm=mock, max_steps=10)
    agent.retry_sleep = 0
    run = agent.run("研究 600519", log_dir=None)
    assert run.stopped == "done", run.stopped
    assert run.steps == 4, run.steps  # 2次错误+2次正常，预算内消化
    print("llm_error_recovery OK  steps=%d" % run.steps)


def test_llm_error_circuit_breaker():
    # 通道彻底挂掉：连续3次RuntimeError熔断，answer=None，不烧穿步数
    class DeadLLM(object):
        model = "mock"
        total_tokens = 0

        def decide(self, messages):
            raise RuntimeError("gateway挂了")

    agent = Agent(llm=DeadLLM(), max_steps=10)
    agent.retry_sleep = 0
    run = agent.run("研究 600519", log_dir=None)
    assert run.stopped == "llm_error", run.stopped
    assert run.answer is None
    assert run.steps <= 3, "熔断应在3步内生效，实际%d" % run.steps
    print("llm_error_circuit_breaker OK  stopped=%s steps=%d"
          % (run.stopped, run.steps))


def test_parser_dirty_outputs():
    # 解析器脏输出回归已抽到 tests/test_parser.py（离线，CI也跑）
    pass


if __name__ == "__main__":
    test_happy_path()
    test_max_steps_forced_final()
    test_max_steps_runaway()
    test_parse_error_recovery()
    test_parse_failures_circuit_breaker()
    test_llm_error_recovery()
    test_llm_error_circuit_breaker()
    print("PLUMBING OK")
