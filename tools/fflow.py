# -*- coding: utf-8 -*-
"""工具3：东财个股主力资金流（日频历史）。push2 主站 + push2delay 回退。

本工具同时是「结构化错误返回」的示范：接口间歇性挂掉时，
错误信息写给 LLM 看（含下一步建议），而不是裸抛异常让 agent 编造结果。
"""
import requests

from tools.symbols import em_secid

_UT = "b2884a393a59ad64002292a3e90d46a5"  # 东财公开token，非私有凭证
# fields2: f51日期 f52主力 f53小单 f54中单 f55大单 f56超大单 ...
_FIELDS2 = ",".join("f%d" % i for i in range(51, 66))


def get_fund_flow(code: str, days: int = 20) -> str:
    secid = em_secid(code)
    days = max(5, min(int(days), 60))
    params = {
        "lmt": "0", "klt": "101",
        "fields1": "f1,f2,f3,f7", "fields2": _FIELDS2,
        "secid": secid, "ut": _UT,
    }
    klines = None
    last_err = None
    for host in ("push2", "push2delay"):  # 限流回退链：主站挂了走delay
        url = "https://%s.eastmoney.com/api/qt/stock/fflow/kline/get" % host
        try:
            r = requests.get(url, params=params, timeout=10)
            klines = ((r.json().get("data") or {}).get("klines")) or None
            if klines:
                break
            last_err = "%s 返回空数据" % host
        except Exception as e:
            klines = None
            last_err = "%s: %s" % (host, e)
    if not klines:
        raise ValueError(
            "资金流接口当前不可用（%s）。建议：改用 get_kline 获取行情数据，"
            "资金流稍后再查。" % last_err)

    out = ["日期        主力净流入(亿)  超大单(亿)  大单(亿)"]
    for line in klines[-days:]:
        p = line.split(",")
        try:
            date = p[0]
            main = float(p[1]) / 1e8   # f52 主力净流入(元)
            xl = float(p[5]) / 1e8     # f56 超大单(元)
            big = float(p[4]) / 1e8    # f55 大单(元)
        except (ValueError, IndexError):
            continue
        out.append("%s  %12.2f  %10.2f  %8.2f" % (date, main, xl, big))
    return "\n".join(out)
