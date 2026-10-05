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

# MusicBrainz。**和 Java、data-pipeline 读的是同一个 .env 变量** ——
# backend/application.yaml 里是 ${MUSICBRAINZ_USER_AGENT:...}，
# data-pipeline/config/settings.py 也是同一个名字。
#
# 【不写死一个假 URL】MusicBrainz 的 User-Agent 政策要求带上真实联系方式，
# 他们据此联系。编一个不存在的地址比留空更糟 —— 2026 年会因此被限流甚至封。
# 兜底值和 Java 那边保持一致，格式对了但看得出来是没配
MUSICBRAINZ_USER_AGENT = os.getenv("MUSICBRAINZ_USER_AGENT") or "MusicMind/1.0 (unknown@example.com)"

MUSICBRAINZ_API = os.getenv("MUSICBRAINZ_API", "https://musicbrainz.org/ws/2")

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

# Wikipedia。**和 MusicBrainz 一样，他们要求 UA 里带联系方式**
WIKI_USER_AGENT = os.getenv("WIKI_USER_AGENT") or MUSICBRAINZ_USER_AGENT
