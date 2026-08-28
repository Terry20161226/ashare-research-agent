# -*- coding: utf-8 -*-
"""function calling 协议单元测试（离线，无网络）：parse_fc 转换正确性
+ openai_tools schema 导出。运行：python3 tests/test_fc.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.llm import LLMClient  # noqa: E402


def make_client():
    """绕过 __init__ 的 key 校验，构造一个纯解析用的实例。"""
    c = object.__new__(LLMClient)
    c.protocol = "fc"
    c.total_tokens = 0
    return c


def test_parse_fc_tool_call():
    c = make_client()
    resp = {"choices": [{"message": {"tool_calls": [
        {"function": {"name": "get_kline",
                      "arguments": '{"code": "600519", "days": 60}'}}]}}]}
    raw = c._parse_fc(resp)
    obj = json.loads(raw)
    assert obj["action"]["tool"] == "get_kline"
    assert obj["action"]["args"] == {"code": "600519", "days": 60}
    print("parse_fc_tool_call OK")


def test_parse_fc_finish():
    c = make_client()
    resp = {"choices": [{"message": {"tool_calls": [
        {"function": {"name": "finish",
                      "arguments": '{"answer": "最终答案"}'}}]}}]}
    obj = json.loads(c._parse_fc(resp))
    assert obj["action"]["done"] is True
    assert obj["action"]["answer"] == "最终答案"
    print("parse_fc_finish OK")


def test_parse_fc_fallbacks():
    c = make_client()
    # 模型没调工具直接输出文本 -> 兜底返回文本
    resp = {"choices": [{"message": {"tool_calls": [],
                                     "content": '{"thought":"t","action":{"done":true,"answer":"x"}}'}}]}
    raw = c._parse_fc(resp)
    assert json.loads(raw)["action"]["answer"] == "x"
    # arguments 不是合法JSON -> 参数置空而非崩溃
    resp2 = {"choices": [{"message": {"tool_calls": [
        {"function": {"name": "get_quote", "arguments": "not-json"}}]}}]}
    obj = json.loads(c._parse_fc(resp2))
    assert obj["action"]["tool"] == "get_quote"
    assert obj["action"]["args"] == {}
    print("parse_fc_fallbacks OK")


def test_openai_tools_schema():
    from tools import openai_tools
    tools = openai_tools()
    names = [t["function"]["name"] for t in tools]
    assert "get_quote" in names and "get_kline" in names
    assert "get_fund_flow" in names and "get_finance" in names
    assert "save_watchlist" in names
    kline = next(t for t in tools if t["function"]["name"] == "get_kline")
    params = kline["function"]["parameters"]
    assert params["properties"]["code"]["type"] == "string"
    assert params["properties"]["days"]["type"] == "integer"
    assert params["required"] == ["code"]
    print("openai_tools_schema OK（%d个工具schema导出）" % len(tools))


if __name__ == "__main__":
    test_parse_fc_tool_call()
    test_parse_fc_finish()
    test_parse_fc_fallbacks()
    test_openai_tools_schema()
    print("FC OK")
