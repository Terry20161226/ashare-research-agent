#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 入口。

用法：
    python main.py "研究 600519 贵州茅台"                  # 四段式研究草稿
    python main.py "分析下 002017 后续最有可能的走势"        # 直接回答：结论+倾向+硬度标注
    python main.py "研究 000001 平安银行" --verbose --max-steps 10
"""
import argparse

from agent.llm import LLMClient
from agent.llm_hermes import HermesLLM
from agent.loop import Agent


def main():
    ap = argparse.ArgumentParser(description="A股研究员 Agent（裸循环版）")
    ap.add_argument("task", help='任务或问题，如："研究 600519 贵州茅台" 或 "分析下 002017 后续走势"')
    ap.add_argument("--max-steps", type=int, default=15,
                    help="步数硬顶，默认15（成本熔断）")
    ap.add_argument("--llm", choices=["api", "hermes"], default="api",
                    help="LLM通道：api=OpenAI兼容HTTP(.env配key)；"
                         "hermes=ECS gateway复用hermes -z（零API成本）")
    ap.add_argument("--verbose", action="store_true", help="打印每步决策")
    args = ap.parse_args()

    try:
        llm = HermesLLM() if args.llm == "hermes" else LLMClient()
    except RuntimeError as e:
        print("[启动失败] %s" % e)
        raise SystemExit(1)
    print("[model] %s  [llm] %s  [max_steps] %d"
          % (llm.model, args.llm, args.max_steps))
    agent = Agent(llm=llm, max_steps=args.max_steps, verbose=args.verbose)
    print("[prompt_hash] %s\n" % agent.prompt_hash)

    run = agent.run(args.task)

    print("=" * 64)
    if run.answer:
        print(run.answer)
    else:
        print("[中止] stopped=%s，未产出答案。排查：cat %s" % (run.stopped, run.log_path))
    print("=" * 64)
    print("[统计] steps=%d stopped=%s tokens=%s log=%s"
          % (run.steps, run.stopped, run.tokens, run.log_path))


if __name__ == "__main__":
    main()
