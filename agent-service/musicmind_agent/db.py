"""数据库连接。

【只读约定】这个包只写 Agent 侧的表（见 schema-agent.sql 头注释）。
音乐侧和用户侧的表在这里只 SELECT。
"""

from __future__ import annotations

import pymysql

from musicmind_agent.config import MYSQL_CONFIG


def get_connection() -> pymysql.Connection:
    # autocommit=True：批量脚本每首算完立刻提交，中断了也不用从头再来。
    # data-pipeline 那边默认 False 是因为它按 release 为单位做事务回滚，
    # 这里没有需要原子性的多步写入
    return pymysql.connect(**{**MYSQL_CONFIG, "autocommit": True})
