import pymysql

from config.settings import MYSQL_CONFIG


def get_connection() -> pymysql.Connection:
    return pymysql.connect(
        **MYSQL_CONFIG,
        autocommit=False,
    )