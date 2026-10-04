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

# LLM。provider 注册表，加新家只需要在这里加一条，代码不用动
LLM_PROVIDERS = {
    "deepseek": {
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
        "model": os.getenv("DEEPSEEK_MODEL", ""),
    },
    "qwen": {
        "base_url": os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        "api_key": os.getenv("QWEN_API_KEY", ""),
        "model": os.getenv("QWEN_MODEL", ""),
    },
}
