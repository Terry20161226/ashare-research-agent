#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""可选集成：从A股交易系统的研究队列.md（只读！）挑选自动研究对象写入TASK.txt。

设计约定：
- 只读队列文件，绝不修改交易系统的任何文件（零耦合）
- 队列格式变化/文件缺失 → 优雅退出，保留现有 TASK.txt
- 冷却去重：N 天内研究过的代码跳过（历史落 TASK.txt 同目录 researched.jsonl）
- 手动覆盖：TASK.txt 首行以 '!' 开头时本脚本跳过（wrapper 会剥掉 '!' 执行）
环境变量：ASHARE_QUEUE / AGENT_TASK_FILE / AGENT_N_TASKS / AGENT_COOLDOWN_DAYS
"""
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

QUEUE = "/root/ashare/研究队列.md"
TASK_FILE = "/root/Agent/TASK.txt"
N_TASKS = 3
COOLDOWN_DAYS = 5

import os
QUEUE = os.environ.get("ASHARE_QUEUE", QUEUE)
TASK_FILE = os.environ.get("AGENT_TASK_FILE", TASK_FILE)
N_TASKS = int(os.environ.get("AGENT_N_TASKS", str(N_TASKS)))
COOLDOWN_DAYS = int(os.environ.get("AGENT_COOLDOWN_DAYS", str(COOLDOWN_DAYS)))
HISTORY = Path(TASK_FILE).parent / "researched.jsonl"


def parse_candidates(text):
    """解析「## 一、可买候选」表格：[(code, name), ...] 按表内顺序（即优先级）。"""
    m = re.search(r"##[^\n]*可买候选[^\n]*\n(.*?)(?=\n## |\Z)", text, re.S)
    if not m:
        return []
    rows = []
    for line in m.group(1).splitlines():
        cells = [c.strip() for c in line.strip().split("|")]
        # | 代码 | 名称 | ... | -> 首尾空串 + 至少两列
        if len(cells) >= 3 and re.fullmatch(r"\d{6}", cells[1] or ""):
            rows.append((cells[1], cells[2]))
    return rows


def load_history():
    hist = {}
    try:
        for line in HISTORY.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                hist[r["code"]] = max(hist.get(r["code"], ""), r["date"])
            except (json.JSONDecodeError, KeyError):
                continue
    except OSError:
        pass
    return hist


def main():
    if not Path(QUEUE).exists():
        print("队列联动: 队列文件不存在(%s)，跳过" % QUEUE)
        return
    if Path(TASK_FILE).exists():
        first = Path(TASK_FILE).read_text(encoding="utf-8").splitlines()
        if first and first[0].startswith("!"):
            print("队列联动: 检测到手动任务(!前缀)，保留不动")
            return

    text = Path(QUEUE).read_text(encoding="utf-8")
    cands = parse_candidates(text)
    if not cands:
        print("队列联动: 未解析到可买候选（队列格式可能变化），保留现有任务")
        return

    hist = load_history()
    cutoff = (date.today() - timedelta(days=COOLDOWN_DAYS)).isoformat()
    fresh = [c for c in cands if hist.get(c[0], "") < cutoff]
    if not fresh:
        print("队列联动: %d 只候选均在%d天冷却期内，保留现有任务"
              % (len(cands), COOLDOWN_DAYS))
        return
    picked = fresh[:N_TASKS]

    Path(TASK_FILE).write_text(
        "\n".join("研究 %s %s" % (c, n) for c, n in picked) + "\n",
        encoding="utf-8")
    with open(HISTORY, "a", encoding="utf-8") as f:
        for c, _n in picked:
            f.write(json.dumps({"code": c, "date": date.today().isoformat()},
                               ensure_ascii=False) + "\n")
    print("队列联动: 今日自动研究对象 -> %s"
          % " / ".join("%s %s" % (c, n) for c, n in picked))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # 联动失败绝不阻断主流程
        print("队列联动: 异常退出(%s)，保留现有任务" % e)
        sys.exit(0)
