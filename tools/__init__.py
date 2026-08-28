# -*- coding: utf-8 -*-
"""工具注册表：工具在此注册后即可被 agent 调用。

设计约定：
- 工具描述（desc/args）是 system prompt 的一部分——改描述等于改提示词，
  会影响模型路由决策，慎重改。
- execute() 永远返回字符串：成功返回数据，失败返回「写给LLM看的错误信息」，
  绝不裸抛异常（裸抛=LLM看不到错误=开始编造）。
- limit: 该工具结果进入上下文前的截断上限（字符）。
"""
import inspect
import traceback

from tools import fflow, finance, kline, quote, watchlist

TOOL_SPECS = {
    "get_quote": {
        "func": quote.get_quote,
        "desc": "获取股票实时行情快照：现价、涨跌幅、成交额、换手率、市盈率、"
                "市净率、流通市值、总市值。适合作为研究的第一步。",
        "args": {"code": "股票代码，6位数字字符串，如 600519"},
        "limit": 1200,
    },
    "get_kline": {
        "func": kline.get_kline,
        "desc": "获取日K线（前复权）：日期、开高低收、成交量。用于分析走势、"
                "计算区间涨跌幅和关键位置。",
        "args": {"code": "股票代码"},
        "optional_args": {"days": "取最近N个交易日，默认60，范围10~250"},
        "limit": 4000,
    },
    "get_fund_flow": {
        "func": fflow.get_fund_flow,
        "desc": "获取个股主力资金流（日频）：每日主力净流入、超大单、大单金额。"
                "用于判断近期主力资金动向。接口间歇性仅返回当日，历史由本地缓存"
                "每日累积；输出末行标注数据来源。",
        "args": {"code": "股票代码"},
        "optional_args": {"days": "取最近N个交易日，默认20，范围5~60"},
        "limit": 3000,
    },
    "get_finance": {
        "func": finance.get_finance,
        "desc": "获取财务摘要：最近4个报告期（季报/年报，倒序）的营业收入、"
                "归母净利润及同比增速。用于基本面画像与成长性判断。",
        "args": {"code": "股票代码"},
        "limit": 1200,
    },
    "save_watchlist": {
        "func": watchlist.save_watchlist,
        "write": True,  # 写操作：默认被审批门拦截，须运行方显式授权
        "desc": "把标的加入观察清单（写操作，落盘 watchlist.json）。"
                "仅当用户明确要求「加入观察/标记关注」时调用。",
        "args": {"code": "股票代码"},
        "optional_args": {"reason": "加入理由，一句话"},
        "limit": 600,
    },
}


def is_write_tool(name):
    """该工具是否为写操作（须过人工审批门）。"""
    return bool(TOOL_SPECS.get(name, {}).get("write"))


def openai_tools():
    """从注册表导出 OpenAI function calling 的 tools schema（单一事实源：
    同一份注册表既渲染 prompt 文本，也生成原生 function calling 的 schema）。
    参数类型由函数签名的类型注解推导。"""
    _TYPE_MAP = {str: "string", int: "integer", float: "number", bool: "boolean"}
    out = []
    for name, spec in TOOL_SPECS.items():
        params = dict(spec["args"], **spec.get("optional_args", {}))
        sig = inspect.signature(spec["func"])
        properties, required = {}, []
        for pname, desc in params.items():
            anno = sig.parameters[pname].annotation if pname in sig.parameters else str
            properties[pname] = {
                "type": _TYPE_MAP.get(anno if anno is not inspect.Parameter.empty
                                      else str, "string"),
                "description": desc,
            }
            if pname in spec["args"]:
                required.append(pname)
        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": spec["desc"],
                "parameters": {"type": "object", "properties": properties,
                               "required": required},
            },
        })
    return out


def execute(name, args):
    """执行工具。返回字符串：数据 或 可读错误信息。永不抛异常。

    必填参数缺失 -> 报错让LLM补；可选参数缺失 -> 不传，走函数默认值。
    """
    spec = TOOL_SPECS.get(name)
    if spec is None:
        return ("工具不存在: %r。可用工具: %s。请从列表中选择。"
                % (name, ", ".join(sorted(TOOL_SPECS))))
    if not isinstance(args, dict):
        args = {}
    required = spec["args"]
    optional = spec.get("optional_args", {})
    # 参数过滤：只传已声明的参数（防止LLM塞无关字段触发意外）
    clean = {k: args[k] for k in required if k in args}
    clean.update({k: args[k] for k in optional if k in args})
    missing = [k for k in required if k not in clean]
    if missing:
        return ("调用 %s 缺少参数: %s。参数说明: %s"
                % (name, ", ".join(missing),
                   dict(required, **optional)))
    try:
        return str(spec["func"](**clean))
    except Exception as e:
        tb = traceback.format_exc(limit=2)
        return ("工具 %s 执行失败: %s: %s\n建议：阅读上述错误，调整参数后重试；"
                "同一参数组合最多重试1次，仍失败请改用其他工具或基于已有数据继续。"
                "\n[debug] %s" % (name, type(e).__name__, e, tb.splitlines()[-1]))


def tool_prompt():
    """把工具清单渲染成 system prompt 片段（单一事实源）。"""
    lines = []
    for name, spec in TOOL_SPECS.items():
        parts = ["%s=%s" % (k, v) for k, v in spec["args"].items()]
        parts += ["%s=%s(可选)" % (k, v)
                  for k, v in spec.get("optional_args", {}).items()]
        lines.append("- %s(%s): %s" % (name, ", ".join(parts), spec["desc"]))
    return "\n".join(lines)
