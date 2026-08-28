#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 入口。

用法：
    python main.py "研究 600519 贵州茅台"                  # 四段式研究草稿
    python main.py "分析下 002017 后续最有可能的走势"        # 直接回答：结论+倾向+硬度标注
    python main.py "研究 000001 平安银行" --session demo   # 多轮：续接会话demo
    python main.py "它现在估值高吗" --session demo         # 追问（带历史上下文）
    python chat.py --session demo --llm hermes           # 交互REPL
"""
import argparse
import re
import time
from pathlib import Path

from agent import memory
from agent.llm import LLMClient
from agent.llm_hermes import HermesLLM
from agent.loop import Agent


def save_memo(task, run):
    """答案归档 memos/YYYYMMDD_代码.md（同日同代码覆盖，最新为准）。

    用途：交易候选的自动预研备忘录库——队列候选升级窗口确认时，
    历史研究草稿可直接回溯（文件可grep，优于聊天记录流）。
    """
    m = re.search(r"\b\d{6}\b", task)
    tag = m.group(0) if m else "misc"
    d = Path("memos")
    d.mkdir(exist_ok=True)
    path = d / (time.strftime("%Y%m%d") + "_" + tag + ".md")
    header = ("# 研究备忘录 %s\n\n- 任务：%s\n- 日期：%s\n"
              "- 运行：steps=%d stopped=%s\n\n---\n\n"
              % (tag, task, time.strftime("%Y-%m-%d %H:%M"),
                 run.steps, run.stopped))
    path.write_text(header + (run.answer or "(未产出答案)"),
                    encoding="utf-8")
    return path


def main():
    ap = argparse.ArgumentParser(description="A股研究员 Agent（裸循环版）")
    ap.add_argument("task", help='任务或问题，如："研究 600519 贵州茅台" 或 "分析下 002017 后续走势"')
    ap.add_argument("--max-steps", type=int, default=15,
                    help="步数硬顶，默认15（成本熔断）")
    ap.add_argument("--llm", choices=["api", "hermes"], default="api",
                    help="LLM通道：api=OpenAI兼容HTTP(.env配key)；"
                         "hermes=ECS gateway复用hermes -z（零API成本）")
    ap.add_argument("--protocol", choices=["json", "fc"], default="json",
                    help="决策协议：json=prompt-JSON（默认，含解析兜底）；"
                         "fc=原生function calling（仅api通道有效）")
    ap.add_argument("--verbose", action="store_true", help="打印每步决策")
    ap.add_argument("--save-memo", action="store_true",
                    help="答案另存 memos/YYYYMMDD_代码.md（同日同代码覆盖）")
    ap.add_argument("--approve-write", action="store_true",
                    help="人工授权：允许执行写工具（save_watchlist等）。"
                         "默认拒绝——cron/CI等无人值守场景天然只读")
    ap.add_argument("--session", metavar="ID",
                    help="会话id：自动注入同会话历史+标的历史备忘录作上下文，"
                         "本轮Q/A追加到 sessions/<ID>.jsonl（跨会话记忆）")
    args = ap.parse_args()

    try:
        llm = HermesLLM() if args.llm == "hermes" else LLMClient(protocol=args.protocol)
    except RuntimeError as e:
        print("[启动失败] %s" % e)
        raise SystemExit(1)
    print("[model] %s  [llm] %s  [max_steps] %d"
          % (llm.model, args.llm, args.max_steps))
    agent = Agent(llm=llm, max_steps=args.max_steps, verbose=args.verbose,
                  allow_write=args.approve_write)
    print("[prompt_hash] %s\n" % agent.prompt_hash)

    context = memory.build_context(args.session, args.task) if args.session else None
    if context:
        print("[session] %s（历史%d轮+备忘录上下文%d字）"
              % (args.session, len(memory.load_session(args.session)),
                 len(context)))
    run = agent.run(args.task, context=context)

    print("=" * 64)
    if run.answer:
        print(run.answer)
    else:
        print("[中止] stopped=%s，未产出答案。排查：cat %s" % (run.stopped, run.log_path))
    print("=" * 64)
    if args.save_memo and run.answer:
        print("[memo] %s" % save_memo(args.task, run))
    if args.session and run.answer:
        memory.append_session(args.session, args.task, run.answer,
                              {"steps": run.steps, "stopped": run.stopped})
        print("[session] 本轮已记入 %s" % memory.session_path(args.session))
    print("[统计] steps=%d stopped=%s tokens=%s log=%s"
          % (run.steps, run.stopped, run.tokens, run.log_path))


if __name__ == "__main__":
    main()
