import pymysql


class GenreRepository:

    def __init__(self, connection: pymysql.Connection):
        self.connection = connection

    def upsert(
        self,
        name: str,
        autocommit: bool = True,
    ) -> int:
        if not name:
            raise ValueError("genre name 不能为空")

        sql = """
            INSERT INTO genre (name)
            VALUES (%s)
            ON DUPLICATE KEY UPDATE
                id = LAST_INSERT_ID(id)
        """

        with self.connection.cursor() as cursor:
            cursor.execute(sql, (name,))
            genre_id = cursor.lastrowid

        if autocommit:
            self.connection.commit()

        return genre_id