# -*- coding: utf-8 -*-
"""工具1：腾讯实时行情快照。接口稳定、无鉴权、GBK编码。"""
import requests

from tools.symbols import tx_symbol

# 腾讯返回字段索引（~分隔）
# 1=名称 3=现价 31=涨跌额 32=涨跌幅% 37=成交额(万元) 38=换手率%
# 39=市盈率TTM 44=流通市值(亿) 45=总市值(亿) 46=市净率


def get_quote(code: str) -> str:
    sym = tx_symbol(code)
    url = "https://qt.gtimg.cn/q=" + sym
    r = requests.get(url, timeout=10)
    r.encoding = "gbk"  # 腾讯接口返回GBK，不设会乱码
    fields = r.text.split("~")
    if len(fields) < 40:
        raise ValueError(
            "行情接口未返回有效数据（字段数=%d），请确认代码 %s 是否正确、是否已停牌"
            % (len(fields), code))

    def f(i):
        return fields[i] if i < len(fields) else "N/A"

    lines = [
        "股票: %s (%s)" % (f(1), code),
        "现价: %s  涨跌: %s (%s%%)" % (f(3), f(31), f(32)),
        "成交额: %s万元  换手率: %s%%" % (f(37), f(38)),
        "市盈率TTM: %s  市净率: %s" % (f(39), f(46)),
        "流通市值: %s亿  总市值: %s亿" % (f(44), f(45)),
    ]
    return "\n".join(lines)
