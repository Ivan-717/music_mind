"""回填艺人元数据：country / type / 出道年 + genres。

用法：
    python backfill_artist_meta.py            # 只处理还没同步过的（可断点续跑）
    python backfill_artist_meta.py --limit 30 # 先跑一小批看看
    python backfill_artist_meta.py --all      # 全部重跑一遍

【为什么要它】artist 表原来只有名字。做用户画像需要「艺人来自哪里 / 什么年代出道 /
什么流派」，而这三样都要额外一次 MusicBrainz 请求。

【一个被实测推翻的假设】原计划是「回填 album_genre」—— 给没有流派的专辑重抓
release-group。实测 20 张专辑里 0 张能拿到：那些专辑（精选集 / 演唱会 / 原声带 /
再版）在 MusicBrainz 上**根本没有流派标签**，不是我们没抓，是上游没有。

但**艺人层的流派覆盖好得多**（抽样 60%，重要的艺人更高：vdev 的 Top10 里 8 个有）。
所以流派信号改从艺人层取，专辑层保持原样。

一次请求同时拿四样东西，这就是为什么它们合在一个脚本里：
    country      ISO 3166-1 alpha-2（CN/TW/JP…）—— 存代码不存国名，展示层映射
    type         Person / Group / Orchestra …
    begin_year   出道（个人）或成立（团体）年份
    genres       艺人流派 → artist_genre

限速由 client 内置（1 请求/秒），696 个艺人约 12 分钟。
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field

# 必须在任何 print 之前
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from config.settings import MUSICBRAINZ_CONFIG  # noqa: E402
from database.connection import get_connection  # noqa: E402
from musicbrainz import MusicBrainzClient  # noqa: E402
from musicbrainz.adapter import MusicBrainzDataAdapter  # noqa: E402
from musicbrainz.repository import (  # noqa: E402
    ArtistGenreRepository,
    ArtistRepository,
    GenreRepository,
)


@dataclass
class BackfillStats:

    total: int = 0
    processed: int = 0
    failed: int = 0

    with_country: int = 0
    with_type: int = 0
    with_begin_year: int = 0
    with_genres: int = 0

    genre_links: int = 0
    api_requests: int = 0

    start_time: float = field(default_factory=time.time)

    def elapsed(self) -> float:
        return time.time() - self.start_time

    def __str__(self) -> str:
        p = self.processed or 1
        return (
            "\n"
            "================ Backfill Summary ================\n"
            f"待处理          : {self.total}\n"
            f"已处理          : {self.processed}\n"
            f"失败            : {self.failed}\n"
            f"--- 拿到比例（分母=已处理）---\n"
            f"country         : {self.with_country:5}  ({self.with_country / p * 100:5.1f}%)\n"
            f"type            : {self.with_type:5}  ({self.with_type / p * 100:5.1f}%)\n"
            f"begin_year      : {self.with_begin_year:5}  ({self.with_begin_year / p * 100:5.1f}%)\n"
            f"genres          : {self.with_genres:5}  ({self.with_genres / p * 100:5.1f}%)\n"
            f"artist_genre 行 : {self.genre_links}\n"
            f"API 请求        : {self.api_requests}\n"
            f"耗时            : {self.elapsed():.1f}s\n"
            "=================================================="
        )


def parse_begin_year(artist_data: dict) -> int | None:
    """life-span.begin 可能是 '1965-03-21'、'1965-03'、'1965'，也可能没有"""
    begin = (artist_data.get("life-span") or {}).get("begin")
    if not begin:
        return None
    head = str(begin)[:4]
    return int(head) if head.isdigit() else None


def pending_artists(connection, limit: int | None, resync_all: bool) -> list[dict]:
    where = "" if resync_all else "WHERE meta_synced_at IS NULL"
    sql = f"""
        SELECT id, name, musicbrainz_id
        FROM artist
        {where}
        ORDER BY id
        {"LIMIT %s" if limit else ""}
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, (limit,) if limit else ())
        return cursor.fetchall()


def main() -> int:

    parser = argparse.ArgumentParser(description="回填艺人元数据")
    parser.add_argument("--limit", type=int, default=None, help="只处理前 N 个")
    parser.add_argument("--all", action="store_true", help="连同步过的也重跑")
    args = parser.parse_args()

    client = MusicBrainzClient(user_agent=MUSICBRAINZ_CONFIG["user_agent"])
    adapter = MusicBrainzDataAdapter()

    connection = get_connection()
    artist_repository = ArtistRepository(connection)
    artist_genre_repository = ArtistGenreRepository(connection)
    genre_repository = GenreRepository(connection)

    stats = BackfillStats()
    artists = pending_artists(connection, args.limit, args.all)
    stats.total = len(artists)

    print(f"待处理 {stats.total} 个艺人，限速 1 请求/秒…")

    for index, artist in enumerate(artists, start=1):

        try:
            data = client.get(
                f"/artist/{artist['musicbrainz_id']}",
                params={"inc": "genres"},
            )
            stats.api_requests += 1

        except Exception as e:
            stats.failed += 1
            print(f"  ✗ {artist['name']} 请求失败：{e}")
            # 【故意不打 meta_synced_at】失败的可能是网络抖动，不是这个艺人坏了。
            # 打上标记等于把一次超时永久记成「已处理」，续跑时再也不会重试它。
            # 留空的话重跑自动带上，代价只是几条请求
            continue

        country = data.get("country")
        artist_type = data.get("type")
        begin_year = parse_begin_year(data)

        artist_repository.update_meta(
            musicbrainz_id=artist["musicbrainz_id"],
            country_code=country,
            artist_type=artist_type,
            begin_year=begin_year,
            autocommit=False,
        )

        # 流派。解析复用 adapter，口径和整艺人导入时完全一致
        genres = adapter.genres_to_musicmind(data)
        for genre in genres:
            genre_id = genre_repository.upsert(genre["name"], autocommit=False)
            artist_genre_repository.upsert(
                artist_id=artist["id"],
                genre_id=genre_id,
                weight=genre["weight"],
                autocommit=False,
            )
            stats.genre_links += 1

        # 一个艺人一次提交：中途断了也只是丢掉当前这一个，不用从头再来
        connection.commit()

        stats.processed += 1
        stats.with_country += bool(country)
        stats.with_type += bool(artist_type)
        stats.with_begin_year += begin_year is not None
        stats.with_genres += bool(genres)

        if index % 50 == 0:
            print(
                f"  [{index}/{stats.total}] "
                f"genres {stats.with_genres} "
                f"({stats.with_genres / stats.processed * 100:.0f}%) "
                f"耗时 {stats.elapsed():.0f}s"
            )

    connection.close()
    print(stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
