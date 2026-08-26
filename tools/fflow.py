# -*- coding: utf-8 -*-
"""工具3：东财个股主力资金流（日频历史）。

三级回退链 push2 → push2his → push2delay：东财对单IP间歇性限流，
不同 host 健康度不同步（实测 push2/push2his 会直接断连，delay 稳定但
只返回当日1天）。

自累积缓存 stockdata/fflow_cache.json（standalone，不依赖外部环境）：
- 接口返回≥2天历史 → 以接口为准刷新缓存（权威数据）
- 接口只返回当日1天 → 当日行并入缓存，输出合并后的历史
- 接口全挂且缓存非空 → 回落缓存
输出末行标注数据来源，上层引用时如实转述（研究草稿的诚实纪律）。
"""
import json
from pathlib import Path

import requests

from tools.symbols import em_secid

_UT = "b2884a393a59ad64002292a3e90d46a5"  # 东财公开token，非私有凭证
# fields2: f51日期 f52主力 f53小单 f54中单 f55大单 f56超大单 ...
_FIELDS2 = ",".join("f%d" % i for i in range(51, 66))
_HEADERS = {"User-Agent": "Mozilla/5.0"}
CACHE_PATH = (Path(__file__).resolve().parent.parent
              / "stockdata" / "fflow_cache.json")
_CACHE_KEEP = 120  # 每只股票最多缓存的交易日数


def _load_cache():
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(cache):
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass  # 缓存读写失败不影响主流程


def _prune(ckey):
    """每只股票只保留最近 _CACHE_KEEP 个交易日。"""
    if len(ckey) > _CACHE_KEEP:
        for d in sorted(ckey)[:-_CACHE_KEEP]:
            ckey.pop(d, None)


def _fetch_api(code):
    """返回 (rows, err)。rows=[(日期, 主力亿, 超大亿, 大单亿)]；无数据时 rows=None。"""
    params = {
        "lmt": "0", "klt": "101",
        "fields1": "f1,f2,f3,f7", "fields2": _FIELDS2,
        "secid": em_secid(code), "ut": _UT,
    }
    last_err = None
    for host in ("push2", "push2his", "push2delay"):
        url = "https://%s.eastmoney.com/api/qt/stock/fflow/kline/get" % host
        try:
            r = requests.get(url, params=params, timeout=10,
                             headers=_HEADERS)
            klines = ((r.json().get("data") or {}).get("klines")) or None
            if klines:
                rows = []
                for line in klines:
                    p = line.split(",")
                    try:
                        rows.append((p[0], float(p[1]) / 1e8,
                                     float(p[5]) / 1e8, float(p[4]) / 1e8))
                    except (ValueError, IndexError):
                        continue
                if rows:
                    return rows, None
            last_err = "%s 返回空数据" % host
        except Exception as e:
            last_err = "%s: %s" % (host, str(e)[:60])
    return None, last_err


def get_fund_flow(code: str, days: int = 20) -> str:
    code = str(code).strip()
    days = max(5, min(int(days), 60))
    rows, err = _fetch_api(code)
    cache = _load_cache()
    ckey = cache.setdefault(code, {})

    if rows and len(rows) >= 2:
        for d, m, x, b in rows:
            ckey[d] = [m, x, b]
        _prune(ckey)
        _save_cache(cache)
        src = "东财接口历史（%d日）" % len(rows)
    elif rows:
        ckey[rows[0][0]] = [rows[0][1], rows[0][2], rows[0][3]]
        _prune(ckey)
        _save_cache(cache)
        src = ("东财接口当日 + 本地累积缓存（共%d日；接口间歇性仅返回当日，"
               "历史由每日运行累积）" % len(ckey))
    elif ckey:
        src = "本地缓存（共%d日；东财接口当前不可用：%s）" % (len(ckey), err)
    else:
        raise ValueError(
            "资金流接口当前不可用（%s）且本地无缓存。建议：改用 get_kline "
            "获取行情数据，资金流稍后再查。" % err)

    merged = sorted((d, v[0], v[1], v[2]) for d, v in ckey.items())
    merged = merged[-days:]
    out = ["日期        主力净流入(亿)  超大单(亿)  大单(亿)"]
    for d, m, x, b in merged:
        out.append("%s  %12.2f  %10.2f  %8.2f" % (d, m, x, b))
    out.append("[数据来源: %s]" % src)
    return "\n".join(out)
