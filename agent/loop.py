# -*- coding: utf-8 -*-
"""Agent 主循环——整个项目的核心，刻意保持在 200 行以内。

结构：任务 -> LLM决策(调哪个工具) -> 执行工具 -> 结果回灌 -> 再决策
      -> ... -> LLM判定数据足够 -> done(answer)

工程三件套（第一天就带的，其余等撞墙再补）：
1. 步数硬顶 max_steps：agent 最贵的行为是「再试一次」，必须熔断
2. 工具结果截断：所有工具输出进 messages 前过 truncate()
3. 运行日志 jsonl 落盘：出问题先看日志（对齐 cron 排障习惯）
"""
import hashlib
import json
import os
import time
from pathlib import Path

from agent.llm import DecisionParseError, LLMClient
from agent.trunc import truncate
from tools import TOOL_SPECS, execute, is_write_tool, tool_prompt

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "researcher.txt"

PARSE_RETRY_HINT = (
    "你上一条输出无法解析为决策JSON。请只输出一个JSON对象，不要输出任何其他文字，"
    '格式为：{"thought": "一句话理由", "action": {"tool": "工具名", "args": {参数}}} '
    '或 {"thought": "一句话总结", "action": {"done": true, "answer": "最终草稿全文"}}')


class RunLog:
    """运行日志：jsonl 落盘，每步一条。含 prompt_hash 与 token 记账。"""

    def __init__(self, log_dir, meta):
        d = Path(log_dir) if log_dir else Path("runs")
        d.mkdir(parents=True, exist_ok=True)
        # 文件名带pid：同秒多进程并行运行（如测试与真实任务同秒启动）不会
        # 以append模式写进同一个文件
        ts = time.strftime("%Y%m%d_%H%M%S")
        self.path = d / ("run_%s_%d.jsonl" % (ts, os.getpid()))
        self._f = open(self.path, "a", encoding="utf-8")
        self.write(0, "meta", meta)

    def write(self, step, typ, payload):
        rec = {"ts": time.strftime("%H:%M:%S"), "step": step, "type": typ}
        if isinstance(payload, dict):
            rec.update(payload)
        else:
            rec["data"] = str(payload)[:2000]
        self._f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._f.flush()

    def close(self):
        self._f.close()


class AgentRun(object):
    """一次 run 的结果。answer 为 None = 未产出（查 log_path）。"""


def _context_chars(messages):
    """当前上下文总字符数（system+历史+工具结果）。"""
    return sum(len(m.get("content", "")) for m in messages)


def _evict_old_tool_results(messages, keep=3):
    """上下文逐出：工具结果只保留最近 keep 条原文，更早的折叠为一行桩。

    权衡：旧数据原文驻留换取注意力聚焦与负载稳定（实测16步任务工具
    结果占上下文86%）。桩明示「如需引用请重新调用」，agent 不会误以为
    数据还在。forced_final 收尾时已拿到 answer 所需结论，逐出无损。
    """
    idx = [i for i, m in enumerate(messages)
           if m.get("role") == "user"
           and m.get("content", "").startswith("[工具 ")
           and "执行结果]" in m.get("content", "")[:30]]
    for i in idx[:-keep] if keep > 0 else idx:
        head = messages[i]["content"].split("\n", 1)
        stub = head[0] + "（已折叠省略——如需引用其中数据，请重新调用该工具）"
        messages[i]["content"] = stub


class Agent:
    def __init__(self, llm=None, max_steps=15, verbose=False, evict_keep=3,
                 allow_write=False):
        self.llm = llm or LLMClient()
        self.max_steps = max_steps
        self.verbose = verbose
        self.retry_sleep = 3  # LLM通道故障重试间隔（测试置0）
        self.evict_keep = evict_keep  # 工具结果原文保留最近N条，更早的折叠为桩
        self.allow_write = allow_write  # 写工具授权（人工审批门，默认拒绝）
        self._system = self._build_system()
        # prompt版本指纹：行为突变时先对hash，再查是谁改了提示词
        self.prompt_hash = hashlib.md5(self._system.encode()).hexdigest()[:10]

    def _build_system(self):
        tpl = PROMPT_PATH.read_text(encoding="utf-8")
        return tpl.replace("{{TOOLS}}", tool_prompt())

    def run(self, task, log_dir=None, context=None):
        """执行一次任务。context: 可选上下文块（会话历史/历史备忘录），
        由 agent/memory.py 组装——主循环保持无状态，记忆是外围层。"""
        run = AgentRun()
        run.task = task
        run.model = getattr(self.llm, "model", "mock")
        user_content = "任务：" + task
        if context:
            user_content = context + "\n\n" + user_content
        messages = [
            {"role": "system", "content": self._system},
            {"role": "user", "content": user_content},
        ]
        log = RunLog(log_dir, {
            "task": task, "model": run.model, "prompt_hash": self.prompt_hash,
            "max_steps": self.max_steps,
            "context_chars": len(context or "")})
        parse_fails = 0
        llm_errors = 0
        stopped, answer, step = "max_steps", None, 0

        for step in range(1, self.max_steps + 1):
            # ---- 1. LLM 决策 ----
            # 上下文记账：发给LLM的真实负载（逐出机制的效果可从日志观测）
            log.write(step, "context", {"chars": _context_chars(messages),
                                        "msgs": len(messages)})
            try:
                decision, raw = self.llm.decide(messages)
            except DecisionParseError as e:
                parse_fails += 1
                log.write(step, "parse_error", e.raw[:2000])
                if parse_fails >= 3:
                    stopped = "parse_failures"
                    break
                messages.append({"role": "assistant", "content": e.raw[:2000]})
                messages.append({"role": "user", "content": PARSE_RETRY_HINT})
                continue
            except RuntimeError as e:
                # LLM通道故障（网络/超时/网关5xx）：原地重试，连续3次熔断
                llm_errors += 1
                log.write(step, "llm_error", str(e)[:500])
                if llm_errors >= 3:
                    stopped = "llm_error"
                    break
                time.sleep(self.retry_sleep)
                continue
            parse_fails = 0
            llm_errors = 0

            thought = str(decision.get("thought", ""))
            action = decision.get("action")
            if not isinstance(action, dict):
                log.write(step, "bad_action", raw[:300])
                messages.append({"role": "user", "content": PARSE_RETRY_HINT})
                continue
            log.write(step, "decision", {"thought": thought, "action": action})

            # ---- 2. done 则收尾 ----
            if action.get("done"):
                answer = str(action.get("answer", "")).strip()
                stopped = "done"
                break

            # ---- 3. 执行工具 ----
            tool = str(action.get("tool", ""))
            args = action.get("args") if isinstance(action.get("args"), dict) else {}
            messages.append({"role": "assistant",
                             "content": json.dumps(decision, ensure_ascii=False)})
            # 写操作审批门：写工具默认拒绝（cron/CI等无人值守场景天然只读），
            # 显式 --approve-write 才放行；拦截信息写给LLM看，它应继续只读完成
            if is_write_tool(tool) and not self.allow_write:
                result = ("写操作被拦截：工具 %s 需要运行方显式授权（--approve-write）"
                          "才能执行。请基于已有只读数据继续完成任务，并在最终回答中"
                          "如实注明「写操作未执行：待人工授权」。" % tool)
                log.write(step, "write_blocked", {"tool": tool, "args": args})
            else:
                result = truncate(execute(tool, args),
                                  TOOL_SPECS.get(tool, {}).get("limit", 2000))
            messages.append({"role": "user",
                             "content": "[工具 %s 执行结果]\n%s" % (tool, result)})
            _evict_old_tool_results(messages, keep=self.evict_keep)
            log.write(step, "tool_result",
                      {"tool": tool, "chars": len(result),
                       "context_chars": _context_chars(messages),
                       "preview": result[:300]})
            if self.verbose:
                print("  step%02d %-16s %s" % (step, tool, thought[:50]))

        # ---- 步数耗尽：给最后一次「无工具」收尾机会 ----
        if answer is None and stopped == "max_steps":
            messages.append({
                "role": "user",
                "content": "步数预算已耗尽，禁止再调用工具。请立即输出最终JSON："
                           '{"thought":"收尾","action":{"done":true,'
                           '"answer":"基于已获取数据写出的完整研究草稿"}}'})
            try:
                decision, _ = self.llm.decide(messages)
                action = decision.get("action") or {}
                if action.get("done"):
                    answer = str(action.get("answer", "")).strip()
                    stopped = "forced_final"
            except (DecisionParseError, RuntimeError):
                pass

        run.answer = answer
        run.steps = step
        run.stopped = stopped
        run.tokens = getattr(self.llm, "total_tokens", 0)
        run.log_path = str(log.path)
        log.write(step, "final",
                  {"stopped": stopped, "answer_len": len(answer or ""),
                   "tokens": run.tokens})
        log.close()
        return run
