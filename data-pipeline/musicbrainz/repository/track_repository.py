from typing import Any

import pymysql


class TrackRepository:

    def __init__(self, connection: pymysql.Connection):
        self.connection = connection


    def upsert(
        self,
        track: dict[str, Any],
        autocommit: bool = True,
    ) -> int:

        sql = """
        INSERT INTO track (
            musicbrainz_recording_id,
            name,
            duration_ms
        )
        VALUES (%s,%s,%s) AS new
        ON DUPLICATE KEY UPDATE
            name = new.name,
            duration_ms = new.duration_ms
        """

        with self.connection.cursor() as cursor:

            cursor.execute(
                sql,
                (
                    track["musicbrainz_recording_id"],
                    track["name"],
                    track.get("duration_ms"),
                )
            )

            cursor.execute(
                """
                SELECT id
                FROM track
                WHERE musicbrainz_recording_id=%s
                """,
                (
                    track["musicbrainz_recording_id"],
                )
            )

            result = cursor.fetchone()


        if autocommit:
            self.connection.commit()


        return result["id"]