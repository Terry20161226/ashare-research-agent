#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""BM25 vs 代码精确匹配 对照实验——在真实 memos/ 上跑，产出可引用结论。

四类查询：代码精确 / 语义无锚 / 主题词 / 混淆词。
对每个查询分别跑两种检索，输出命中对照表。
运行：python3 eval/bm25_compare.py（须在含 memos/ 的目录下）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import memory  # noqa: E402

QUERIES = [
    # (查询, 期望命中的代码tag, 类别)
    # 注意：600519 不在当前 memos 库中（它来自手动测试未归档），故期望"应空"
    ("研究 600519 贵州茅台", None, "代码精确(库中无此票→应空)"),
    ("白酒龙头的估值水平", None, "语义无锚(库中无白酒票→应空)"),
    ("铜业的资金动向", "600362", "主题词"),
    ("平安银行的走势", "000001", "主题词"),
    ("新大陆的涨停分析", "000997", "主题词"),
    ("大盘指数情况", None, "无锚泛化(应空)"),
    ("固态电池概念股", None, "混淆（应全空）"),
]


def code_exact(query):
    """纯代码匹配（旧逻辑）。"""
    codes = set(memory._extract_codes(query))
    if not codes or not memory.MEMOS_DIR.exists():
        return []
    hits = []
    for p in sorted(memory.MEMOS_DIR.glob("*.md"), reverse=True):
        import re
        m = re.match(r"(\d{8})_(\d{6}|misc)\.md", p.name)
        if m and m.group(2) in codes:
            hits.append(m.group(2))
    return hits


def bm25_only(query):
    return [tag for _, tag, _, _ in memory.bm25_search(query, k=2)]


def hybrid(query):
    return [tag for _, tag, _ in memory.find_memos(query)]


def main():
    print("memos 库存量：%d 份\n" % len(list(memory.MEMOS_DIR.glob('*.md'))))
    print("%-4s %-16s | %-14s | %-14s | %-14s | %s"
          % ("#", "查询", "代码精确", "BM25", "混合", "期望"))
    print("-" * 88)
    win = {"代码精确": 0, "BM25": 0, "混合": 0}
    for i, (q, expect, cat) in enumerate(QUERIES, 1):
        a, b, h = code_exact(q), bm25_only(q), hybrid(q)
        exp = expect or "(应空)"
        mark = lambda r: ("✓" if (expect in r if expect else not r) else "✗")
        if mark(a) == "✓":
            win["代码精确"] += 1
        if mark(b) == "✓":
            win["BM25"] += 1
        if mark(h) == "✓":
            win["混合"] += 1
        print("%-4d %-16s | %-14s | %-14s | %-14s | %s"
              % (i, q[:14], str(a)[:14], str(b)[:14], str(h)[:14], exp))
        print("     类别:%s  判定:%s %s %s" % (cat, mark(a), mark(b), mark(h)))
    print("-" * 88)
    print("命中数：代码精确 %d/%d | BM25 %d/%d | 混合 %d/%d"
          % (win["代码精确"], len(QUERIES), win["BM25"], len(QUERIES),
             win["混合"], len(QUERIES)))


if __name__ == "__main__":
    main()
