# -*- coding: utf-8 -*-
"""代码转接口符号：腾讯行情用 shXXXXXX/szXXXXXX，东财用 1.XXXXXX/0.XXXXXX。"""


def _clean_code(code):
    code = str(code).strip()
    if not (len(code) == 6 and code.isdigit()):
        raise ValueError(
            "股票代码格式错误: %r，应为6位数字字符串，例如 600519" % (code,))
    return code


def tx_symbol(code):
    """腾讯接口符号：6开头沪市前缀 sh，其余深市前缀 sz。"""
    code = _clean_code(code)
    return ("sh" if code.startswith("6") else "sz") + code


def em_secid(code):
    """东财接口 secid：沪市 1.XXXXXX，深市 0.XXXXXX。"""
    code = _clean_code(code)
    market = "1" if code.startswith("6") else "0"
    return market + "." + code
