# -*- coding: utf-8 -*-
"""工具2：腾讯日K线（前复权）——统计摘要化输出。

上下文纪律：进 context 的是消化过的东西。不裸灌全表，而是
「区间统计 + 近10日明细 + 量能标注」——agent 判断走势需要的
区间高低点/分位/量比在统计行里直接给出，避免它再调工具重查。
"""
import requests

from tools.symbols import tx_symbol

_DETAIL_DAYS = 10   # 明细保留最近N个交易日
_VOL_SPIKE = 2.0    # 量比超过该值标注为放量日


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

    # 行结构: [日期, 开, 收, 高, 低, 成交量(手)]
    k = [(str(x[0]), float(x[1]), float(x[2]),
          float(x[3]), float(x[4]), float(x[5])) for x in rows]
    n = len(k)
    avg_vol = sum(x[5] for x in k) / n
    first, last = k[0], k[-1]
    hi = max(k, key=lambda x: x[3])   # 区间最高价
    lo = min(k, key=lambda x: x[4])   # 区间最低价
    pos = (last[2] - lo[4]) / max(hi[3] - lo[4], 1e-9) * 100  # 现价区间分位
    pct = (last[2] / first[1] - 1) * 100  # 区间涨跌（首日开盘->末日收盘）

    out = ["K线区间统计（%s ~ %s，共%d个交易日，前复权）" % (first[0][5:], last[0][5:], n)]
    out.append("区间收盘: %.2f -> %.2f (%+.1f%%)；最高 %.2f(%s) 最低 %.2f(%s)；"
               "现价位于区间 %.0f%% 分位" % (
                   first[1], last[2], pct, hi[3], hi[0][5:], lo[4], lo[0][5:], pos))
    out.append("区间日均量 %.0f 手；放量日(量比>%.0f)：%s" % (
        avg_vol, _VOL_SPIKE,
        "; ".join("%s %.0f手(%.1f倍)" % (x[0][5:], x[5], x[5] / avg_vol)
                  for x in k if x[5] > avg_vol * _VOL_SPIKE) or "无"))
    out.append("近%d日明细（日期 开 收 高 低 量(手) 量比）：" % _DETAIL_DAYS)
    for x in k[-_DETAIL_DAYS:]:
        out.append("%s  %.2f  %.2f  %.2f  %.2f  %.0f  %.1f" % (
            x[0], x[1], x[2], x[3], x[4], x[5], x[5] / avg_vol))
    out.append("[数据截至 %s 收盘；如需更早区间请指定更大 days 重新调用]" % last[0])
    return "\n".join(out)
