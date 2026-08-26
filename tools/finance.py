# -*- coding: utf-8 -*-
"""工具4：东财 datacenter 财务摘要——最近4个报告期的营收/归母净利及同比。

数据源：RPT_LICO_FN_CPD（业绩报表），按报告期倒序。字段：
TOTAL_OPERATE_INCOME 营业收入(元)、PARENT_NETPROFIT 归母净利(元)、
YSTZ 营收同比%、SJLTZ 净利同比%。同比字段个别期为 None（未披露）→ 显示N/A。
"""
import requests

_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_COLS = ("SECURITY_CODE,SECURITY_NAME_ABBR,REPORTDATE,"
         "TOTAL_OPERATE_INCOME,PARENT_NETPROFIT,YSTZ,SJLTZ")


def _fmt(v, pct=False):
    if v is None:
        return "N/A"
    return "%.2f" % v


def get_finance(code: str) -> str:
    code = str(code).strip()
    params = {
        "reportName": "RPT_LICO_FN_CPD",
        "columns": _COLS,
        "filter": '(SECURITY_CODE="%s")' % code,
        "pageSize": "4",
        "sortColumns": "REPORTDATE",
        "sortTypes": "-1",
    }
    r = requests.get(_URL, params=params, timeout=10, headers=_HEADERS)
    data = ((r.json().get("result") or {}).get("data")) or []
    if not data:
        raise ValueError(
            "未获取到 %s 的财务数据（代码可能有误，或该股尚未披露业绩报表）。"
            "建议：核对代码后重试；或基于行情/资金流数据继续研究。" % code)
    name = data[0].get("SECURITY_NAME_ABBR") or code
    out = ["股票: %s (%s) 最近4个报告期（按报告期倒序）" % (name, code),
           "报告期        营收(亿)   营收同比%   归母净利(亿)  净利同比%"]
    for row in data:
        date = str(row.get("REPORTDATE", ""))[:10]
        inc = row.get("TOTAL_OPERATE_INCOME")
        np_ = row.get("PARENT_NETPROFIT")
        out.append("%s  %9.2f  %10s  %11.2f  %9s" % (
            date,
            (inc or 0) / 1e8,
            _fmt(row.get("YSTZ")),
            (np_ or 0) / 1e8,
            _fmt(row.get("SJLTZ"))))
    return "\n".join(out)
