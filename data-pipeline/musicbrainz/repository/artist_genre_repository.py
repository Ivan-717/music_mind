import pymysql


class ArtistGenreRepository:

    def __init__(self, connection: pymysql.Connection):
        self.connection = connection

    def upsert(
        self,
        artist_id: int,
        genre_id: int,
        weight: int = 0,
        autocommit: bool = True,
    ) -> None:
        sql = """
            INSERT INTO artist_genre (
                artist_id,
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
                    artist_id,
                    genre_id,
                    weight,
                ),
            )

        if autocommit:
            self.connection.commit()