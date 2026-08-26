# -*- coding: utf-8 -*-
"""工具层实测：本地直连真实数据接口，不依赖 LLM 和 API key。

运行：python tests/test_tools.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import execute  # noqa: E402

CASES = [
    ("get_quote", {"code": "600519"}),
    ("get_kline", {"code": "600519", "days": 10}),
    ("get_fund_flow", {"code": "600519", "days": 5}),
    # 错误路径也要测：坏代码、不存在的工具
    ("get_quote", {"code": "60051"}),          # 格式错 -> 结构化错误
    ("get_kline", {"code": "600519"}),          # 缺 days -> 应该用默认值成功
    ("no_such_tool", {"code": "600519"}),       # 未知工具 -> 结构化错误
]


def main():
    for name, args in CASES:
        result = execute(name, args)
        head = "\n".join(result.splitlines()[:4])
        print("== %s(%s) ==" % (name, args))
        print(head)
        print()
    # 核心断言：成功案例必须真拿到数据，失败案例必须返回可读错误而非抛异常
    ok_quote = execute("get_quote", {"code": "600519"})
    assert "现价" in ok_quote, ok_quote
    ok_kline = execute("get_kline", {"code": "600519", "days": 10})
    assert len(ok_kline.splitlines()) >= 10, ok_kline
    # 可选参数缺失走函数默认值（days=60），而不是报错
    ok_default = execute("get_kline", {"code": "600519"})
    assert len(ok_default.splitlines()) >= 30, ok_default[:200]
    bad = execute("get_quote", {"code": "abc"})
    assert "失败" in bad or "错误" in bad, bad
    assert "建议" in bad, "错误信息必须包含下一步建议，当前: %r" % bad
    print("TOOLS OK")


if __name__ == "__main__":
    main()
