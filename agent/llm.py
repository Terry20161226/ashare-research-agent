# -*- coding: utf-8 -*-
"""LLM 客户端：requests 直连任意 OpenAI 兼容 /chat/completions。

不依赖 openai SDK——依赖越少，换供应商/部署越省事。
自带：JSON模式（供应商不支持时自动降级）、网络重试1次、token记账。
"""
import json
import re

import requests

from agent.config import get_config


class DecisionParseError(Exception):
    """LLM 输出无法解析为决策JSON。携带原文供日志排查。"""

    def __init__(self, raw):
        self.raw = raw
        super().__init__("LLM输出无法解析为决策JSON")


class LLMClient:
    def __init__(self):
        cfg = get_config()
        if not cfg["api_key"]:
            raise RuntimeError(
                "缺少 API key：复制 .env.example 为 .env，填入 AGENT_API_KEY。"
                "（DeepSeek: https://platform.deepseek.com）")
        self.base_url = cfg["base_url"].rstrip("/")
        self.api_key = cfg["api_key"]
        self.model = cfg["model"]
        self.total_tokens = 0

    def chat(self, messages, temperature=0.0, timeout=90):
        """返回模型文本输出。temperature=0：决策要确定性，不要创造性。"""
        url = self.base_url + "/chat/completions"
        headers = {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": "application/json",
        }
        base_payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        # 第一轮带JSON模式（DeepSeek/Qwen兼容模式都支持），
        # 供应商返回400时降级为普通模式再试
        attempts = [
            dict(base_payload, response_format={"type": "json_object"}),
            base_payload,
        ]
        last_err = None
        for payload in attempts:
            for _ in range(2):  # 每种模式网络级重试1次
                try:
                    r = requests.post(url, json=payload, headers=headers,
                                      timeout=timeout)
                    if r.status_code == 400:
                        last_err = "HTTP400: " + r.text[:300]
                        break  # 400大概率是response_format不支持，换payload
                    r.raise_for_status()
                    j = r.json()
                    self.total_tokens += (j.get("usage") or {}).get(
                        "total_tokens", 0)
                    return j["choices"][0]["message"]["content"]
                except requests.RequestException as e:
                    last_err = e
        raise RuntimeError("LLM调用失败（已重试）: %s" % last_err)

    def decide(self, messages):
        """取模型输出并解析为决策 dict。返回 (决策对象, 原始输出)。"""
        raw = self.chat(messages)
        return parse_decision_json(raw), raw


def _extract_first_json(text):
    """提取首个配平的JSON对象：从第一个{起跟踪深度/字符串状态，
    配平即截断——天然丢弃模型回声的后续对话文本。失败返回None。"""
    start = text.find("{")
    if start == -1:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
    return None


def _autoclose_loads(fragment):
    """兜底：内容完整但LLM漏数嵌套右括号（生产事故形态4）。
    状态机扫到结尾：不在字符串内且深度>0 -> 补齐缺失的}再loads（无损恢复）；
    在字符串中途截断（内容真被切断）-> 返回None走重试路径，不产出半截答案。"""
    depth, in_str, esc = 0, False, False
    for c in fragment:
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
    if in_str or depth <= 0:
        return None
    try:
        obj = json.loads(fragment + "}" * depth, strict=False)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def parse_decision_json(raw):
    """宽容解析：剥markdown围栏 -> 首个配平JSON对象(strict=False容忍
    字符串内真实换行) -> 兜底首尾大括号 -> 终极兜底补齐缺失右括号。
    LLM输出脏是常态，解析器负责兜住。"""
    text = (raw or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    cand = _extract_first_json(text)
    if cand:
        try:
            obj = json.loads(cand, strict=False)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    s = text.find("{")
    if s == -1:
        raise DecisionParseError(raw)
    e = text.rfind("}")
    # 注意：一个右括号都没有（漏两层以上）时 frag 取到串尾，仍交给 autoclose
    frag = text[s:e + 1] if e > s else text[s:]
    try:
        obj = json.loads(frag, strict=False)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    obj = _autoclose_loads(frag)
    if obj is not None:
        return obj
    raise DecisionParseError(raw)
