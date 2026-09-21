import json
from typing import Any

import pymysql


class AlbumRepository:

    def __init__(
        self,
        connection: pymysql.Connection
    ):
        self.connection = connection


    def upsert(
        self,
        album: dict[str, Any],
        autocommit: bool = True,
    ) -> int:

        sql = """
        INSERT INTO album (
            musicbrainz_id,
            name,
            release_date,
            primary_type,
            secondary_types
        )
        VALUES (%s, %s, %s, %s, %s) AS new

        ON DUPLICATE KEY UPDATE

            name = new.name,
            release_date = new.release_date,
            primary_type = new.primary_type,
            secondary_types = new.secondary_types
        """


        with self.connection.cursor() as cursor:

            cursor.execute(
                sql,
                (
                    album["musicbrainz_id"],
                    album["name"],
                    album.get("release_date"),
                    album.get("primary_type"),
                    json.dumps(
                        album.get("secondary_types") or [],
                        ensure_ascii=False,
                    ),
                )
            )


            cursor.execute(
                """
                SELECT id
                FROM album
                WHERE musicbrainz_id=%s
                """,
                (
                    album["musicbrainz_id"],
                )
            )


            result = cursor.fetchone()

        if autocommit:
            self.connection.commit()


        return result["id"]