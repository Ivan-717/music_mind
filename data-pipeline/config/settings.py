"""
集中配置。

敏感值（数据库密码、邮箱）不写在代码里，统一放在项目根目录的 .env。
.env 已被 .gitignore 忽略，不会提交到 Git。
参考 .env.example 了解需要哪些变量。
"""

import os
from pathlib import Path

import pymysql
from dotenv import load_dotenv

# config/settings.py -> config/ -> data-pipeline/ -> 项目根目录
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

MUSICBRAINZ_CONFIG = {
    "user_agent": os.getenv("MUSICBRAINZ_USER_AGENT", ""),
}
