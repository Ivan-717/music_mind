"""配置。复用仓库根目录的 .env —— 和 data-pipeline、Spring Boot 同一份。"""

from __future__ import annotations

import os
from pathlib import Path

import pymysql
from dotenv import load_dotenv

# agent-service/musicmind_agent/config.py -> agent-service/ -> 仓库根
PROJECT_ROOT = Path(__file__).resolve().parents[2]

load_dotenv(PROJECT_ROOT / ".env")


MYSQL_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", ""),
    "database": os.getenv("MYSQL_DATABASE", "musicmind"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

# iTunes Search API。项目里 ④ 音频试听和音频特征管线共用同一个来源
ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
ITUNES_MIN_INTERVAL = float(os.getenv("ITUNES_MIN_INTERVAL", "2.5"))   # 限速约 20-25/分

# LLM。provider 注册表，加新家只需要在这里加一条，代码不用动。
#
# 【max_tokens 必须每家一个】它不是「越大越好」，而是有硬上限，
# 超了服务端直接 400 InvalidParameter，一次调用都发不出去。
# 实测：
#   deepseek-chat      8192 OK
#   qwen-math-turbo    [1, 3072]  ← 统一写 8192 的话千问这条链整个是死的，
#                                   而表现是「选了千问就报错」，不像配置问题
# 换模型时先确认这家的上限，或者用 .env 里的 *_MAX_TOKENS 覆盖
LLM_PROVIDERS = {
    "deepseek": {
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "model": os.getenv("DEEPSEEK_MODEL", ""),
        "max_tokens": int(os.getenv("DEEPSEEK_MAX_TOKENS", "8192")),
    },
    "qwen": {
        "base_url": os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "api_key": os.getenv("QWEN_API_KEY", ""),
        "model": os.getenv("QWEN_MODEL", ""),
        # 默认按 dashscope 兼容层最低的那档给。换个上限更高的模型时，
        # 在 .env 里加 QWEN_MAX_TOKENS=xxxx 覆盖即可，不用改代码
        "max_tokens": int(os.getenv("QWEN_MAX_TOKENS", "3072")),
    },
}
