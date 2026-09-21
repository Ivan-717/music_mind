from typing import Any

import pymysql


class ArtistRepository:

    def __init__(self, connection: pymysql.Connection):
        self.connection = connection


    def upsert(
        self,
        artist: dict[str, Any],
        autocommit: bool = True,
    ) -> int:

        sql = """
        INSERT INTO artist (
            musicbrainz_id,
            name,
            sort_name,
            disambiguation
        )
        VALUES (%s, %s, %s, %s) AS new
        ON DUPLICATE KEY UPDATE
            name = new.name,
            sort_name = new.sort_name,
            disambiguation = new.disambiguation
        """

        with self.connection.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    artist["musicbrainz_id"],
                    artist["name"],
                    artist.get("sort_name"),
                    artist.get("disambiguation"),
                ),
            )

            cursor.execute(
                """
                SELECT id
                FROM artist
                WHERE musicbrainz_id=%s
                """,
                (
                    artist["musicbrainz_id"],
                ),
            )

            result = cursor.fetchone()

        if autocommit:
            self.connection.commit()

        return result["id"]



    def ensure_stub(
        self,
        musicbrainz_id: str,
        name: str | None,
        autocommit: bool = True,
    ) -> int:

        """
        确保 artist 存在。

        如果不存在：
            插入最小数据

        如果已经存在：
            不更新任何业务字段

        只利用 LAST_INSERT_ID(id)
        获取已有记录的 id。

        防止 stub 数据覆盖完整 artist 数据。
        """

        sql = """
        INSERT INTO artist (
            musicbrainz_id,
            name
        )
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE
            id = LAST_INSERT_ID(id)
        """

        with self.connection.cursor() as cursor:

            cursor.execute(
                sql,
                (
                    musicbrainz_id,
                    name or musicbrainz_id,
                ),
            )

            artist_id = cursor.lastrowid


        if autocommit:
            self.connection.commit()

        return artist_id