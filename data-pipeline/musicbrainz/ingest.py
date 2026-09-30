"""按 Release 入库的共用逻辑。

整艺人导入（main.py）和按需入库（ingest_release.py）都走这里，不复制第二份。

【为什么必须抽出来】
release 内部的写入顺序有硬性要求：album 必须先于 release，
track 必须先于 track_artist / release_track —— 后两者要拿前者的本地自增 id 当外键。
这段逻辑要是存在两份，任何一处修复都会静默漂移，
而漂移出来的 bug 表现为「某些歌莫名其妙查不到」，极难定位。

搬移自 main.py 的 import_artist 循环体，只搬运不改良。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from musicbrainz.adapter import MusicBrainzDataAdapter
from musicbrainz.client import MusicBrainzClient
from musicbrainz.repository import (
    AlbumArtistRepository,
    AlbumGenreRepository,
    AlbumRepository,
    ArtistRepository,
    GenreRepository,
    ReleaseRepository,
    ReleaseTrackRepository,
    TrackArtistRepository,
    TrackRepository,
)

if TYPE_CHECKING:
    # 只在类型检查时导入。运行时不能导 —— main.py 会 import 本模块，反过来就成环了。
    from main import ImportStats


@dataclass
class ReleaseIngestContext:
    """仓库句柄 + 跨 release 复用的缓存。一次导入建一次，所有 release 共享。"""

    artist_repository: ArtistRepository
    album_repository: AlbumRepository
    album_artist_repository: AlbumArtistRepository
    album_genre_repository: AlbumGenreRepository
    track_repository: TrackRepository
    track_artist_repository: TrackArtistRepository
    release_repository: ReleaseRepository
    release_track_repository: ReleaseTrackRepository
    genre_repository: GenreRepository

    # 本次导入生命周期内的 id 缓存（MBID → 本地自增 id）
    artist_ids: dict[str, int] = field(default_factory=dict)
    album_ids: dict[str, int] = field(default_factory=dict)
    track_ids: dict[str, int] = field(default_factory=dict)

    # 关系表的唯一键是 (album_id, artist_id) / (track_id, artist_id)。
    # 一张专辑底下有多个 release，一首歌会出现在多张专辑里，
    # 同一对 id 会被反复算出来 —— 用 set 挡掉重复写入。
    # （不影响正确性，upsert 本来也幂等，纯粹是别白跑 SQL）
    seen_album_artists: set[tuple[int, int]] = field(default_factory=set)
    seen_track_artists: set[tuple[int, int]] = field(default_factory=set)
    seen_album_genres: set[tuple[int, int]] = field(default_factory=set)

    def forget_uncommitted(self) -> None:
        """清空全部缓存。【事务回滚之后必须调】。

        缓存里的值是 upsert 当场返回的本地自增 id，而 rollback() 只回滚数据库、
        回滚不了内存 —— 更麻烦的是 MySQL 的自增值不会后退，所以缓存里留下的是
        一个「永远不会有行占用」的死 id。

        不清的后果：同一个 release-group 的下一个 release 会直接复用这个死 id
        （连 album 都不再 upsert），撞 fk_music_release_album 外键错；
        stale 的 track_id / artist_id 同理。而且因为失败的那个 release 已经被
        跳过，这套死 id 会一路错到本次导入结束 —— 控制台只剩一串外键错误。

        清空的代价只是多跑几条 upsert（本来就幂等），远小于一路外键错。
        seen_* 一起清：它们记的是「这一对 id 写过了」，id 都作废了，记录自然失效。
        """
        self.artist_ids.clear()
        self.album_ids.clear()
        self.track_ids.clear()
        self.seen_album_artists.clear()
        self.seen_track_artists.clear()
        self.seen_album_genres.clear()


def build_release_ingest_context(connection) -> ReleaseIngestContext:
    """建一套仓库句柄。

    按需入库是「一个进程一个 release」，缓存注定是空的 ——
    但仍然走这个函数，两条路径共用同一份代码，不需要「批量模式」和「单条模式」两套。
    """
    return ReleaseIngestContext(
        artist_repository=ArtistRepository(connection),
        album_repository=AlbumRepository(connection),
        album_artist_repository=AlbumArtistRepository(connection),
        album_genre_repository=AlbumGenreRepository(connection),
        track_repository=TrackRepository(connection),
        track_artist_repository=TrackArtistRepository(connection),
        release_repository=ReleaseRepository(connection),
        release_track_repository=ReleaseTrackRepository(connection),
        genre_repository=GenreRepository(connection),
    )


def ingest_release(
    connection,
    client: MusicBrainzClient,
    adapter: MusicBrainzDataAdapter,
    ctx: ReleaseIngestContext,
    release_mbid: str,
    stats: ImportStats,
) -> bool:
    """把一个 Release 完整写进库。

    顺序：release-group → album → album_artist → album_genre →
    release → track → track_artist → release_track。

    返回 True  = 写完了，调用方可以 commit。
    返回 False = 这个 release 没什么可写的（缺 release-group）。
                 调用方直接跳过：skip 计数已经在函数里加过，
                 而且一个字节都没写过，不需要 rollback。

    【本函数不 commit 也不 rollback】提交时机是调用方的策略
    （整艺人导入和按需入库都是「一个 release 一次 commit」，但那是调用方的决定）。
    出错直接往上抛，由调用方 rollback。
    """
    # ------------------------------------------------
    # Release 详情
    # ------------------------------------------------

    data = client.get_release(release_mbid)

    stats.api_request_count += 1

    # ------------------------------------------------
    # Release Group → Album
    # ------------------------------------------------

    release_group = data.get("release-group")

    if not release_group:
        print("  跳过：没有 Release Group")
        stats.skipped_release_count += 1
        return False

    album = adapter.album_to_musicmind(release_group)

    album_mbid = album["musicbrainz_id"]

    # Album 缓存
    album_id = ctx.album_ids.get(album_mbid)

    if album_id is None:

        album_id = ctx.album_repository.upsert(
            album,
            autocommit=False,
        )

        ctx.album_ids[album_mbid] = album_id

        stats.album_count += 1

    # ------------------------------------------------
    # Album Artist
    # ------------------------------------------------

    album_artists = adapter.album_artists_to_musicmind(release_group)

    for credit in album_artists:

        credit_mbid = credit["artist_musicbrainz_id"]

        credited_name = credit.get("credited_name")

        # 先从本次导入缓存找
        related_artist_id = ctx.artist_ids.get(credit_mbid)

        # 没有则创建 stub
        if related_artist_id is None:

            related_artist_id = ctx.artist_repository.ensure_stub(
                musicbrainz_id=credit_mbid,
                name=credited_name,
                autocommit=False,
            )

            ctx.artist_ids[credit_mbid] = related_artist_id

        pair = (album_id, related_artist_id)

        # 同一专辑的另一个 release 会算出同一对 id
        if pair in ctx.seen_album_artists:
            continue

        ctx.seen_album_artists.add(pair)

        ctx.album_artist_repository.upsert(
            album_id=album_id,
            artist_id=related_artist_id,
            credited_name=credited_name,
            join_phrase=credit.get("join_phrase"),
            autocommit=False,
        )

        stats.album_artist_count += 1

    # ------------------------------------------------
    # Album Genre
    # ------------------------------------------------

    genres = adapter.genres_to_musicmind(release_group)

    for genre in genres:

        genre_id = ctx.genre_repository.upsert(
            genre["name"],
            autocommit=False,
        )

        pair = (album_id, genre_id)

        # 同一专辑的另一个 release 会算出同一对 id
        if pair in ctx.seen_album_genres:
            continue

        ctx.seen_album_genres.add(pair)

        ctx.album_genre_repository.upsert(
            album_id=album_id,
            genre_id=genre_id,
            weight=genre["weight"],
            autocommit=False,
        )

        stats.album_genre_count += 1

    # ------------------------------------------------
    # Release
    # ------------------------------------------------

    release = adapter.release_to_musicmind(data)

    # MBID 换成本地 id
    release["album_id"] = ctx.album_ids[release.pop("album_musicbrainz_id")]

    release_id = ctx.release_repository.upsert(
        release,
        autocommit=False,
    )

    # ------------------------------------------------
    # Track
    # ------------------------------------------------

    for media in data.get("media", []):

        disc_number = media.get("position") or 1

        for track in media.get("tracks", []):

            recording = track.get("recording") or {}

            recording_mbid = recording.get("id")

            if not recording_mbid:
                continue

            # ----------------------------------------
            # Track
            # ----------------------------------------

            track_id = ctx.track_ids.get(recording_mbid)

            # 只在缓存未命中时 upsert
            # stats.track_count 统计的是「新增行数」
            if track_id is None:

                track_data = adapter.track_to_musicmind(track)

                track_id = ctx.track_repository.upsert(
                    track_data,
                    autocommit=False,
                )

                ctx.track_ids[recording_mbid] = track_id

                stats.track_count += 1

            # ----------------------------------------
            # Track Artist
            # ----------------------------------------

            track_artists = adapter.track_artists_to_musicmind(recording)

            for credit in track_artists:

                credit_mbid = credit["artist_musicbrainz_id"]

                credited_name = credit.get("credited_name")

                related_artist_id = ctx.artist_ids.get(credit_mbid)

                if related_artist_id is None:

                    related_artist_id = ctx.artist_repository.ensure_stub(
                        musicbrainz_id=credit_mbid,
                        name=credited_name,
                        autocommit=False,
                    )

                    ctx.artist_ids[credit_mbid] = related_artist_id

                pair = (track_id, related_artist_id)

                # 同一首歌出现在多张专辑里，会算出同一对 id
                if pair in ctx.seen_track_artists:
                    continue

                ctx.seen_track_artists.add(pair)

                ctx.track_artist_repository.upsert(
                    track_id=track_id,
                    artist_id=related_artist_id,
                    credited_name=credited_name,
                    join_phrase=credit.get("join_phrase"),
                    autocommit=False,
                )

                stats.track_artist_count += 1

            # ----------------------------------------
            # Release Track
            # ----------------------------------------

            ctx.release_track_repository.upsert(
                release_id=release_id,
                track_id=track_id,
                track_number=track.get("position"),
                disc_number=disc_number,
                autocommit=False,
            )

    return True
