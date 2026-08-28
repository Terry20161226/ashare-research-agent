# -*- coding: utf-8 -*-
"""工具5（写工具）：把标的加入观察清单——全项目唯一的写操作，用于演示
人工审批门（HITL governance）：只读工具自由跑，写操作默认拒绝，
须运行方显式授权（--approve-write）才执行。
"""
import json
import time
from pathlib import Path

WATCHLIST = Path("watchlist.json")


def save_watchlist(code: str, reason: str = "") -> str:
    code = str(code).strip()
    reason = str(reason).strip()
    if len(code) != 6 or not code.isdigit():
        raise ValueError("股票代码格式错误: %r，应为6位数字字符串" % code)
    try:
        data = json.loads(WATCHLIST.read_text(encoding="utf-8"))
    except Exception:
        data = []
    if any(x.get("code") == code for x in data):
        return "已在观察清单中（%s），未重复添加。" % code
    data.append({"code": code, "reason": reason,
                 "added_at": time.strftime("%Y-%m-%d %H:%M")})
    WATCHLIST.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    return "已加入观察清单：%s（理由：%s）。清单现共 %d 只。" % (
        code, reason or "未注明", len(data))
