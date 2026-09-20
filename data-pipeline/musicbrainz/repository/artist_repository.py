from typing import Any

import pymysql


class ArtistRepository:

    def __init__(
        self,
        connection: pymysql.Connection
    ):
        self.connection = connection


    def upsert(
        self,
        artist: dict[str, Any]
    ) -> int:

        sql = """
        INSERT INTO artist (
            musicbrainz_id,
            name,
            sort_name,
            disambiguation
        )
        VALUES (%s,%s,%s,%s)

        ON DUPLICATE KEY UPDATE

            name = VALUES(name),
            sort_name = VALUES(sort_name),
            disambiguation = VALUES(disambiguation)
        """

        with self.connection.cursor() as cursor:

            cursor.execute(
                sql,
                (
                    artist["musicbrainz_id"],
                    artist["name"],
                    artist.get("sort_name"),
                    artist.get("disambiguation"),
                )
            )

            cursor.execute(
                """
                SELECT id
                FROM artist
                WHERE musicbrainz_id=%s
                """,
                (
                    artist["musicbrainz_id"],
                )
            )

            result = cursor.fetchone()


        self.connection.commit()

        return result[0]