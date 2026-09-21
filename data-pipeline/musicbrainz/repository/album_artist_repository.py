import pymysql


class AlbumArtistRepository:

    def __init__(self, connection: pymysql.Connection):
        self.connection = connection


    def upsert(
        self,
        album_id: int,
        artist_id: int,
        credited_name: str | None,
        join_phrase: str | None,
        autocommit: bool = True,
    ) -> None:


        sql = """
        INSERT INTO album_artist (
            album_id,
            artist_id,
            credited_name,
            join_phrase
        )
        VALUES (%s,%s,%s,%s) AS new
        ON DUPLICATE KEY UPDATE
            credited_name = new.credited_name,
            join_phrase = new.join_phrase
        """


        with self.connection.cursor() as cursor:

            cursor.execute(
                sql,
                (
                    album_id,
                    artist_id,
                    credited_name,
                    join_phrase,
                )
            )


        if autocommit:
            self.connection.commit()