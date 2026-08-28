# -*- coding: utf-8 -*-
"""记忆层测试（离线，无网络无LLM）：会话续接 + 备忘录检索 + 上下文渲染。

运行：python3 tests/test_memory.py
"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import memory  # noqa: E402


def setup():
    """测试沙盒：临时替换目录指向 tests 下的 fixture。"""
    base = Path(__file__).resolve().parent / "_mem_fixture"
    if base.exists():
        shutil.rmtree(base)
    (base / "memos").mkdir(parents=True)
    (base / "sessions").mkdir(parents=True)
    memory.SESSIONS_DIR = base / "sessions"
    memory.MEMOS_DIR = base / "memos"
    return base


def test_session_roundtrip():
    # 追加两轮 -> 加载 -> 渲染历史含两轮且answer截断生效
    memory.append_session("t1", "研究 600519 贵州茅台", "A" * 2000)
    memory.append_session("t1", "估值高吗", "不高")
    turns = memory.load_session("t1")
    assert len(turns) == 2, turns
    hist = memory.render_history("t1")
    assert "研究 600519" in hist and "估值高吗" in hist
    assert "A" * memory.MAX_TURN_CHARS in hist  # 截断后仍保留800字
    assert "A" * 900 not in hist  # 超出部分被截
    # 空会话渲染为空串
    assert memory.render_history("no_such") == ""
    # 失败轮（answer空）不入记忆
    memory.append_session("t1", "失败问题", "")
    assert len(memory.load_session("t1")) == 2
    print("session_roundtrip OK")


def test_memo_retrieval():
    # 备忘录按代码命中、最新在前、无关代码不命中
    (memory.MEMOS_DIR / "20260820_600519.md").write_text(
        "# 研究备忘录 600519\n\n---\n\n旧的茅台研究，现价1200元。", encoding="utf-8")
    (memory.MEMOS_DIR / "20260826_600519.md").write_text(
        "# 研究备忘录 600519\n\n---\n\n最新茅台研究，现价1302.80元。", encoding="utf-8")
    (memory.MEMOS_DIR / "20260826_000001.md").write_text(
        "# 研究备忘录 000001\n\n---\n\n平安银行。", encoding="utf-8")
    hits = memory.find_memos("研究 600519 贵州茅台")
    assert [h[0] for h in hits] == ["20260826", "20260820"], hits
    assert len(hits) <= memory.MAX_MEMOS
    ctx = memory.render_memos("再看看 600519")
    assert "1302.80" in ctx and "历史研究备忘录" in ctx
    # 任务无代码 -> 无命中
    assert memory.find_memos("今天大盘如何") == []
    print("memo_retrieval OK")


def test_build_context():
    ctx = memory.build_context("t1", "研究 600519 贵州茅台")
    assert "对话历史" in ctx and "历史研究备忘录" in ctx
    # 上下文预算：5轮×800 + 2×600 + 文案 < 8K 字符
    assert len(ctx) < 8000, len(ctx)
    print("build_context OK（历史+备忘录混合渲染，预算受控 %d字）" % len(ctx))


def test_bm25_semantic_fallback():
    # BM25兜底：无代码锚点的语义查询也能召回相关备忘录
    # fixture用贴近真实产出的内容（含行业语义，非仅代码）
    (memory.MEMOS_DIR / "20260826_600362.md").write_text(
        "# 研究备忘录 600362\n\n---\n\n江西铜业涨停，铜业周期量价齐升，超大单进攻。",
        encoding="utf-8")
    # 覆写600519备忘录为真实语义内容（白酒行业龙头）
    (memory.MEMOS_DIR / "20260826_600519.md").write_text(
        "# 研究备忘录 600519\n\n---\n\n贵州茅台，白酒行业绝对龙头，市盈率TTM 20倍，估值合理偏低。",
        encoding="utf-8")
    hits = memory.bm25_search("白酒龙头估值怎么样")
    assert hits and hits[0][1] == "600519", hits
    # 代码查询仍走精确匹配，BM25不抢戏
    hits2 = memory.find_memos("研究 000001 平安银行")
    assert hits2 and hits2[0][1] == "000001", hits2
    # 完全无关的查询返回空（不误召回）
    assert memory.bm25_search("量子计算机概念股") == []
    print("bm25_semantic_fallback OK")


def test_loop_context_injection():
    # 主循环context参数：注入内容须出现在LLM收到的首条user消息里
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from test_plumbing import GOOD_SCRIPT, MockLLM
    from agent.loop import Agent
    mock = MockLLM(GOOD_SCRIPT)
    agent = Agent(llm=mock, max_steps=10)
    agent.run("研究 600519", log_dir="runs/tests",
              context="【对话历史】\n用户：研究000001\n助手：平安银行…")
    first_user = [m for m in mock.messages_seen if m["role"] == "user"][0]
    assert "对话历史" in first_user["content"]
    assert "平安银行" in first_user["content"]
    assert "任务：研究 600519" in first_user["content"]
    print("loop_context_injection OK")


if __name__ == "__main__":
    setup()
    test_session_roundtrip()
    test_memo_retrieval()
    test_build_context()
    test_bm25_semantic_fallback()
    test_loop_context_injection()
    print("MEMORY OK")
