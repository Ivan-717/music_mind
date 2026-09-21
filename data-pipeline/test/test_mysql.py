import pymysql
from config.settings import MYSQL_CONFIG

def main():
    connection =  pymysql.connect(**MYSQL_CONFIG)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE()")
            result = cursor.fetchone()
            print("当前数据库：", result["db"])
    finally:
        connection.close()


if __name__ == "__main__":
    main()