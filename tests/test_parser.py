# -*- coding: utf-8 -*-
"""解析器回归测试（纯离线，无网络无LLM）——CI 也跑这一层。

五种生产事故形态的脏输出复现：
1. answer字符串内真实换行  2. JSON后跟回声上下文  3. markdown围栏
4. 漏数嵌套右括号（内容完整） 5. 字符串中途截断（不救，走重试）
运行：python3 tests/test_parser.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.llm import DecisionParseError, parse_decision_json  # noqa: E402


def test_dirty_outputs():
    # 形态1：answer字符串内含真实换行
    raw1 = ('{"thought": "成稿", "action": {"done": true, "answer": "第一段'
            '\n第二段\n第三段"}}')
    obj = parse_decision_json(raw1)
    assert obj["action"]["done"] is True
    assert "\n" in obj["action"]["answer"]

    # 形态2：决策JSON后跟回声的对话上下文
    raw2 = ('{"thought": "重试", "action": {"tool": "get_fund_flow", '
            '"args": {"code": "600519", "days": 60}}}\n\n'
            '[工具 get_fund_flow 执行结果]\n日期 主力净流入\n'
            '2026-08-26 0.73\n\n【助手（你上一轮的决策）】\n{"thought": "旧决策"}')
    obj = parse_decision_json(raw2)
    assert obj["action"]["tool"] == "get_fund_flow"
    assert obj["action"]["args"]["days"] == 60

    # 形态3：markdown围栏包裹
    raw3 = '```json\n{"thought": "ok", "action": {"done": true, "answer": "x"}}\n```'
    obj = parse_decision_json(raw3)
    assert obj["action"]["answer"] == "x"

    # 正常输入不受影响
    obj = parse_decision_json('{"thought": "t", "action": {"tool": "get_quote", "args": {"code": "000001"}}}')
    assert obj["action"]["args"]["code"] == "000001"
    print("dirty_outputs OK（换行/回声/围栏三种脏形态全兜住）")


def test_missing_braces():
    # 形态4：内容完整但漏数嵌套右括号——补齐后无损恢复
    raw4 = ('{"thought": "成稿", "action": {"done": true, '
            '"answer": "完整内容，结尾自然。数据截至2026-08-26。"}')
    obj = parse_decision_json(raw4)
    assert obj["action"]["done"] is True
    assert obj["action"]["answer"].endswith("数据截至2026-08-26。")

    # 漏两层括号
    raw4b = '{"thought": "t", "action": {"done": true, "answer": "x"'
    obj = parse_decision_json(raw4b)
    assert obj["action"]["answer"] == "x"

    # 形态5：字符串中途截断——不救，抛错走重试路径（绝不产出半截答案）
    raw5 = '{"thought": "x", "action": {"done": true, "answer": "内容被截'
    try:
        parse_decision_json(raw5)
        raise AssertionError("中途截断应抛DecisionParseError")
    except DecisionParseError:
        pass

    # 完全无JSON
    try:
        parse_decision_json("这不是JSON，随便说说")
        raise AssertionError("无JSON应抛DecisionParseError")
    except DecisionParseError:
        pass
    print("missing_braces OK（漏括号无损恢复/中途截断走重试）")


if __name__ == "__main__":
    test_dirty_outputs()
    test_missing_braces()
    print("PARSER OK")
