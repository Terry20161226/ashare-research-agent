# -*- coding: utf-8 -*-
"""上下文截断 adapter：工具结果进 messages 前的最后一道闸。

原则：进 context 的必须是消化过的东西。宁可截断后让 agent 用更小的
days 参数再查一次，也不要把 200 行原始数据裸灌进上下文。
"""


def truncate(text, limit=2000):
    text = str(text)
    if len(text) <= limit:
        return text
    # 按行保留，留 20% 余量给截断说明本身
    lines = text.split("\n")
    kept, n = [], 0
    for ln in lines:
        if n + len(ln) + 1 > int(limit * 0.8):
            break
        kept.append(ln)
        n += len(ln) + 1
    return ("%s\n...[输出过长已截断：原始共%d行/%d字符，仅保留前%d行。"
            "如需减少数据量可缩小 days 参数重新调用]"
            % ("\n".join(kept), len(lines), len(text), len(kept)))
