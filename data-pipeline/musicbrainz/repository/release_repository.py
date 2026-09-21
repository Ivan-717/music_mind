from typing import Any

import pymysql


class ReleaseRepository:

    def __init__(self, connection: pymysql.Connection):
        self.connection = connection


    def upsert(
        self,
        release: dict[str, Any],
        autocommit: bool = True,
    ) -> int:

        sql = """
        INSERT INTO music_release (
            musicbrainz_id,
            album_id,
            title,
            release_date,
            country,
            status
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s
        ) AS new
        ON DUPLICATE KEY UPDATE
            album_id = new.album_id,
            title = new.title,
            release_date = new.release_date,
            country = new.country,
            status = new.status
        """


        with self.connection.cursor() as cursor:

            cursor.execute(
                sql,
                (
                    release["musicbrainz_id"],
                    release["album_id"],
                    release["title"],
                    release.get("release_date"),
                    release.get("country"),
                    release.get("status"),
                ),
            )


            cursor.execute(
                """
                SELECT id
                FROM music_release
                WHERE musicbrainz_id = %s
                """,
                (
                    release["musicbrainz_id"],
                ),
            )

            row = cursor.fetchone()


        if autocommit:
            self.connection.commit()


        return row["id"]