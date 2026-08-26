# -*- coding: utf-8 -*-
"""HermesLLM：经 hermes -z CLI 复用 ECS gateway（Nous OAuth），零 API 成本。

仅部署在 ECS 上使用（本机无 hermes）。与 LLMClient 同接口：
decide(messages) -> (决策dict, 原始输出)，供 Agent 循环直接替换。

调用模式复刻自服务器 llm_helpers.py（2026-08-25 已在生产验证）：
  subprocess.run([HERMES_BIN, "-z", prompt, "--cli"], cwd="/root/.hermes")

差异：hermes -z 只吃单条 prompt（无 role 结构），故把 system+对话历史
渲染成一段自包含 prompt；通道故障抛 RuntimeError，由主循环预算内重试/熔断。
"""
import subprocess

from agent.llm import DecisionParseError, parse_decision_json

HERMES_BIN = "/root/.hermes/hermes-agent/venv/bin/hermes"
HERMES_CWD = "/root/.hermes"

RENDER_TAIL = """
【你的任务】
你就是【系统指令】中定义的研究员 agent。基于以上完整对话，决定你的下一步。
只输出一个 JSON 对象，禁止输出任何其他文字（不要解释、不要markdown围栏）。
调工具：{"thought": "一句话理由", "action": {"tool": "工具名", "args": {"code": "600519"}}}
结束：{"thought": "一句话总结", "action": {"done": true, "answer": "最终研究草稿全文"}}"""


class HermesLLM(object):
    def __init__(self, timeout=120, bin_path=HERMES_BIN, cwd=HERMES_CWD):
        self.bin = bin_path
        self.cwd = cwd
        self.timeout = timeout
        self.model = "hermes-gateway"
        self.total_tokens = 0  # gateway 不返回 token 记账，留0

    def decide(self, messages):
        raw = self._call(self._render(messages))
        return parse_decision_json(raw), raw

    def _render(self, messages):
        parts = []
        for m in messages:
            role, content = m["role"], m["content"]
            if role == "system":
                parts.append("【系统指令】\n" + content)
            elif role == "assistant":
                parts.append("【助手（你上一轮的决策）】\n" + content)
            else:
                parts.append("【用户】\n" + content)
        parts.append(RENDER_TAIL)
        return "\n\n".join(parts)

    def _call(self, prompt):
        try:
            r = subprocess.run(
                [self.bin, "-z", prompt, "--cli"],
                capture_output=True, text=True, timeout=self.timeout,
                cwd=self.cwd)
        except subprocess.TimeoutExpired:
            raise RuntimeError("hermes -z 超时(%ds)" % self.timeout)
        except OSError as e:
            raise RuntimeError("hermes 二进制不可用: %s" % e)
        if r.returncode != 0:
            raise RuntimeError("hermes -z rc=%d stderr=%s"
                               % (r.returncode, (r.stderr or "").strip()[:200]))
        out = (r.stdout or "").strip()
        if not out:
            raise RuntimeError("hermes -z 返回空输出")
        return out
