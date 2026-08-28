# -*- coding: utf-8 -*-
"""记忆层：会话记忆 + 跨会话研究记忆。零外部依赖（文件+检索，无向量库）。

两层设计（个人规模原则：文件+grep 撑到上限，不给未来预付复杂度）：

1. 会话记忆 sessions/<id>.jsonl —— 同一 session 的多轮问答追加落盘。
   续接时只渲染历史轮的「任务+answer摘要」，不重灌工具中间结果
   （上下文预算纪律：历史是结论不是流水）。

2. 跨会话研究记忆 memos/YYYYMMDD_代码.md —— 任务含股票代码时自动检索
   同代码历史备忘录（最近 N 份），注入为「历史研究上下文」。
   agent 因此能说"较 8/26 研究时现价+X%"——记研究结论，不记对话。

渲染预算：历史轮数≤5、每轮answer≤800字；历史备忘录≤2份、每份≤600字。
"""
import json
import math
import re
import time
from collections import Counter
from pathlib import Path

SESSIONS_DIR = Path("sessions")
MEMOS_DIR = Path("memos")
MAX_TURNS = 5        # 会话历史最多带最近几轮
MAX_TURN_CHARS = 800  # 每轮answer截断
MAX_MEMOS = 2         # 历史备忘录最多注入几份
MAX_MEMO_CHARS = 600


# ---------- 会话记忆 ----------

def session_path(sid):
    sid = re.sub(r"[^\w-]", "", str(sid))[:64] or "default"
    return SESSIONS_DIR / (sid + ".jsonl")


def load_session(sid):
    """读取会话历史：[{task, answer}, ...] 按时间序。"""
    p = session_path(sid)
    turns = []
    try:
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
                if r.get("task") and r.get("answer"):
                    turns.append({"task": r["task"], "answer": r["answer"]})
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return turns


def append_session(sid, task, answer, meta=None):
    """追加一轮到会话文件。answer 为空（运行失败）不记——失败轮不入记忆。"""
    if not answer:
        return
    SESSIONS_DIR.mkdir(exist_ok=True)
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M"), "task": task,
           "answer": answer}
    if meta:
        rec.update(meta)
    with open(session_path(sid), "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def render_history(sid):
    """把会话历史渲染成上下文块。无历史返回空串。

    含显式【指代锚点】：从最近历史轮提取标的代码注入——指代消解
    靠系统注入保证（确定性），不只靠 prompt 规则（概率性）。
    """
    turns = load_session(sid)
    if not turns:
        return ""
    lines = ["【对话历史】（同会话前几轮，历史工具明细已省略，只留结论）"]
    for t in turns[-MAX_TURNS:]:
        ans = t["answer"][:MAX_TURN_CHARS]
        if len(t["answer"]) > MAX_TURN_CHARS:
            ans += "...(截断)"
        lines.append("用户：%s" % t["task"])
        lines.append("助手：%s" % ans)
        lines.append("")
    # 指代锚点：最近一轮出现的6位代码（指代词"它/该股"应解析为此标的）
    for t in reversed(turns[-MAX_TURNS:]):
        codes = _extract_codes(t["task"]) or _extract_codes(t["answer"][:200])
        if codes:
            lines.append("【指代锚点】本会话最近研究的标的：%s（指代词应解析为它，"
                         "回答开头须点明）" % codes[0])
            break
    return "\n".join(lines).strip()


# ---------- 跨会话研究记忆 ----------

def _extract_codes(text):
    return re.findall(r"\b\d{6}\b", text)


def _tokenize(text):
    """零依赖中文分词：字符bigram + 6位代码/英文词单独成token。
    '平安银行' -> ['平安','安银','银行']；比单字粒度保留更多语义。"""
    tokens = re.findall(r"\b\d{6}\b|[A-Za-z][A-Za-z0-9_.]*", text)
    cjk = re.sub(r"[^\u4e00-\u9fff]", "", text)
    tokens += [cjk[i:i + 2] for i in range(len(cjk) - 1)]
    return tokens


def bm25_search(query, k=2, _k1=1.5, _b=0.75, min_score=2.0):
    """BM25全文检索备忘录：[(date, tag, body, score)] 按分数降序。
    语义兜底层——无代码锚点的查询（"白酒龙头估值"）也能召回相关备忘录。
    min_score=2.0：按当前7份memos库校准（真命中最低2.98/误召回最高1.82），
    库内容变化后须重跑 eval/bm25_compare.py 重新校准。"""
    if not MEMOS_DIR.exists():
        return []
    docs = []
    for p in MEMOS_DIR.glob("*.md"):
        m = re.match(r"(\d{8})_(\d{6}|misc)\.md", p.name)
        if not m:
            continue
        try:
            body = p.read_text(encoding="utf-8")
        except OSError:
            continue
        docs.append((m.group(1), m.group(2), body, Counter(_tokenize(body))))
    if not docs:
        return []
    q_tokens = Counter(_tokenize(query))
    N = len(docs)
    avgdl = sum(sum(tf.values()) for _, _, _, tf in docs) / N
    scores = []
    for date, tag, body, tf in docs:
        dl = sum(tf.values())
        score = 0.0
        for q in q_tokens:
            n_q = sum(1 for _, _, _, t in docs if t.get(q, 0) > 0)
            idf = math.log(1 + (N - n_q + 0.5) / (n_q + 0.5))
            f = tf.get(q, 0)
            score += idf * f * (_k1 + 1) / (f + _k1 * (1 - _b + _b * dl / max(avgdl, 1)))
        if score >= min_score:
            scores.append((date, tag, body, round(score, 3)))
    scores.sort(key=lambda x: x[3], reverse=True)
    return scores[:k]


def find_memos(task):
    """检索任务相关历史备忘录：[(日期, tag, body), ...] 最新在前。
    混合检索：代码精确匹配优先（确定性），无代码锚点时BM25语义兜底。"""
    hits = []
    codes = set(_extract_codes(task))
    if codes and MEMOS_DIR.exists():
        for p in sorted(MEMOS_DIR.glob("*.md"), reverse=True):
            m = re.match(r"(\d{8})_(\d{6}|misc)\.md", p.name)
            if not m:
                continue
            date, tag = m.groups()
            if tag in codes:
                try:
                    body = p.read_text(encoding="utf-8")
                except OSError:
                    continue
                hits.append((date, tag, body))
                if len(hits) >= MAX_MEMOS:
                    break
    if not hits:
        # 语义兜底：无代码/代码未命中时走BM25全文检索
        for date, tag, body, _ in bm25_search(task, k=MAX_MEMOS):
            hits.append((date, tag, body))
    return hits


def render_memos(task):
    """把历史备忘录渲染成上下文块。无命中返回空串。"""
    hits = find_memos(task)
    if not hits:
        return ""
    lines = ["【历史研究备忘录】（此前对该标的的研究结论，引用时注明当时日期；"
             "注意数据已过期，需重新取数核实）"]
    for date, tag, body in hits:
        # 剥备忘录自身的头部元信息，取正文
        content = body.split("---", 1)[-1].strip()
        if len(content) > MAX_MEMO_CHARS:
            content = content[:MAX_MEMO_CHARS] + "...(截断)"
        lines.append("— %s 研究 %s：\n%s" % (date, tag, content))
        lines.append("")
    return "\n".join(lines).strip()


def build_context(sid, task):
    """组装完整上下文块：会话历史 + 历史备忘录。空则返回空串。"""
    parts = [x for x in (render_history(sid), render_memos(task)) if x]
    return "\n\n".join(parts)
