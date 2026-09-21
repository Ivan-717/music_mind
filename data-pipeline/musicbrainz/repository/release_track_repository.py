import logging
import pymysql


logger = logging.getLogger(__name__)


class ReleaseTrackRepository:

    def __init__(self, connection: pymysql.Connection):
        self.connection = connection


    def upsert(
        self,
        release_id: int,
        track_id: int,
        track_number: int | None,
        disc_number: int | None = 1,
        autocommit: bool = True,
    ) -> None:


        if track_number is None:
            logger.warning(
                "skip release_track because track_number is None"
            )
            return None


        sql = """
        INSERT INTO release_track (
            release_id,
            track_id,
            track_number,
            disc_number
        )
        VALUES (%s,%s,%s,%s) AS new
        ON DUPLICATE KEY UPDATE
            track_id = new.track_id;
        """


        with self.connection.cursor() as cursor:

            cursor.execute(
                sql,
                (
                    release_id,
                    track_id,
                    track_number,
                    disc_number or 1,
                )
            )


        if autocommit:
            self.connection.commit()