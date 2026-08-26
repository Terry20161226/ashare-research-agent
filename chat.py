#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交互式多轮对话 REPL（--session 机制的薄壳）。

用法：
    python3 chat.py                          # 默认通道，会话=日期（如 20260826）
    python3 chat.py --session demo --llm hermes --max-steps 12
指令：/new 开新会话 | /history 看历史轮 | /exit 退出

每轮仍是独立的 Agent 运行（熔断/预算隔离不变），历史通过
sessions/<id>.jsonl 续接注入——进程退出会话不丢，下次同 id 继续。
"""
import argparse
import time

from agent import memory
from agent.llm import LLMClient
from agent.llm_hermes import HermesLLM
from agent.loop import Agent


def main():
    ap = argparse.ArgumentParser(description="A股研究员 Agent（多轮对话）")
    ap.add_argument("--session", default=None,
                    help="会话id，默认按日期自动（如 20260826）")
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--llm", choices=["api", "hermes"], default="api")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    sid = args.session or time.strftime("%Y%m%d")
    try:
        llm = HermesLLM() if args.llm == "hermes" else LLMClient()
    except RuntimeError as e:
        print("[启动失败] %s" % e)
        raise SystemExit(1)

    agent = Agent(llm=llm, max_steps=args.max_steps, verbose=args.verbose)
    print("A股研究员Agent 多轮对话 | session=%s | model=%s" % (sid, llm.model))
    print("指令：/new 开新会话  /history 看历史  /exit 退出\n")

    while True:
        try:
            task = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            break
        if not task:
            continue
        if task == "/exit":
            print("再见。会话保存在 %s" % memory.session_path(sid))
            break
        if task == "/new":
            sid = time.strftime("%Y%m%d_%H%M%S")
            print("[已切换新会话 %s]\n" % sid)
            continue
        if task == "/history":
            turns = memory.load_session(sid)
            if not turns:
                print("（无历史）\n")
            for i, t in enumerate(turns, 1):
                print("%d. %s\n   -> %s...\n" % (i, t["task"], t["answer"][:80]))
            continue

        context = memory.build_context(sid, task)
        run = agent.run(task, context=context, log_dir="runs/chat")
        print("\n助手> " + (run.answer or
               "[中止] stopped=%s，日志：%s" % (run.stopped, run.log_path)))
        if run.answer:
            memory.append_session(sid, task, run.answer,
                                  {"steps": run.steps, "stopped": run.stopped})
        print("[steps=%d stopped=%s]\n" % (run.steps, run.stopped))


if __name__ == "__main__":
    main()
