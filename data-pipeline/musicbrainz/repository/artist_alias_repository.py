from typing import Any

import pymysql


class ArtistAliasRepository:

    def __init__(self, connection: pymysql.Connection):
        self.connection = connection


    def upsert(
        self,
        artist_id: int,
        alias: dict[str, Any],
        autocommit: bool = True,
    ) -> None:

        sql = """
        INSERT INTO artist_alias (
            artist_id,
            name,
            locale,
            is_primary
        )
        VALUES (%s,%s,%s,%s) AS new
        ON DUPLICATE KEY UPDATE
            is_primary = new.is_primary
        """

        with self.connection.cursor() as cursor:

            cursor.execute(
                sql,
                (
                    artist_id,
                    alias["name"],
                    alias.get("locale") or "",
                    alias.get("is_primary", False),
                )
            )


        if autocommit:
            self.connection.commit()