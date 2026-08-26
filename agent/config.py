# -*- coding: utf-8 -*-
"""配置加载：项目根目录 .env（gitignore）+ 环境变量兜底。

约定：所有配置用 AGENT_ 前缀，避免与其他项目的 .env 惯例冲突。
优先级：进程环境变量 > .env 文件 > 默认值。
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_dotenv()


def get_config():
    return {
        "api_key": os.environ.get("AGENT_API_KEY", ""),
        # 默认 DeepSeek；任意 OpenAI 兼容端点都行（改 .env 即可）
        "base_url": os.environ.get("AGENT_BASE_URL", "https://api.deepseek.com"),
        "model": os.environ.get("AGENT_MODEL", "deepseek-chat"),
    }
