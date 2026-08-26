# -*- coding: utf-8 -*-
"""工具2：腾讯日K线（前复权）。接口稳定、无鉴权。"""
import requests

from tools.symbols import tx_symbol


def get_kline(code: str, days: int = 60) -> str:
    sym = tx_symbol(code)
    days = max(10, min(int(days), 250))  # 参数防御：10~250日之间
    url = ("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           "?param=%s,day,,,%d,qfq" % (sym, days))
    r = requests.get(url, timeout=10)
    data = (r.json().get("data") or {}).get(sym) or {}
    rows = data.get("qfqday") or data.get("day")
    if not rows:
        raise ValueError("未获取到K线数据，请确认代码 %s 是否正确" % code)

    out = ["日期        开盘     收盘     最高     最低   成交量(手)"]
    for row in rows[-days:]:
        # 每行: [日期, 开, 收, 高, 低, 成交量(手)]，个别行末尾多一列成交额，取前6列
        cells = [str(c) for c in row[:6]]
        out.append("  ".join(cells))
    return "\n".join(out)
