import pymysql


class AlbumGenreRepository:

    def __init__(self, connection: pymysql.Connection):
        self.connection = connection

    def upsert(
        self,
        album_id: int,
        genre_id: int,
        weight: int = 0,
        autocommit: bool = True,
    ) -> None:
        sql = """
            INSERT INTO album_genre (
                album_id,
                genre_id,
                weight
            )
            VALUES (%s, %s, %s) AS new
            ON DUPLICATE KEY UPDATE
                weight = new.weight
        """

        with self.connection.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    album_id,
                    genre_id,
                    weight,
                ),
            )

        if autocommit:
            self.connection.commit()