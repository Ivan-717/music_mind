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



    def update_meta(
        self,
        musicbrainz_id: str,
        country_code: str | None,
        artist_type: str | None,
        begin_year: int | None,
        autocommit: bool = True,
    ) -> None:
        """
        回填艺人元数据，并打上同步时刻。

        【为什么不并进 upsert】upsert 在整艺人导入时跑，那时手里只有 search 的结果，
        没有 country / type / begin —— 那要额外一次 inc=genres 的请求。
        所以单独一条路径，由 backfill_artist_meta.py 驱动。

        【为什么用 COALESCE 而不是直接赋值】MusicBrainz 上这三个字段是稀疏的
        （抽样：country 80% / type 93% / begin 70%）。某次请求没返回某个字段时，
        不该把之前已经填好的值清成 NULL。

        meta_synced_at 无条件更新：它记的是「问过了」，不是「问到了」。
        没有它，上游本来就空的那些艺人在每次续跑时都会被重新问一遍。
        """
        sql = """
        UPDATE artist
           SET country_code   = COALESCE(%s, country_code),
               type           = COALESCE(%s, type),
               begin_year     = COALESCE(%s, begin_year),
               meta_synced_at = NOW()
         WHERE musicbrainz_id = %s
        """

        with self.connection.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    country_code,
                    artist_type,
                    begin_year,
                    musicbrainz_id,
                ),
            )

        if autocommit:
            self.connection.commit()

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