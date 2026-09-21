from __future__ import annotations

import argparse
import time
import uuid
from dataclasses import dataclass, field

from config.settings import MUSICBRAINZ_CONFIG

from database.connection import get_connection
from musicbrainz import MusicBrainzClient
from musicbrainz.adapter import MusicBrainzDataAdapter
from musicbrainz.repository import (
    ArtistRepository,
    ArtistAliasRepository,
    AlbumRepository,
    AlbumArtistRepository,
    ReleaseRepository,
    TrackRepository,
    TrackArtistRepository,
    ReleaseTrackRepository,
)


# ============================================================
# ImportStats
# ============================================================

@dataclass
class ImportStats:

    artist_count: int = 0
    artist_alias_count: int = 0

    album_count: int = 0
    album_artist_count: int = 0

    track_count: int = 0
    track_artist_count: int = 0

    release_count: int = 0
    filtered_release_count: int = 0
    skipped_release_count: int = 0

    api_request_count: int = 0

    start_time: float = field(default_factory=time.time)

    def elapsed(self) -> float:
        return time.time() - self.start_time

    def __str__(self) -> str:
        return (
            "\n"
            "================ Import Summary ================\n"
            f"Artist             : {self.artist_count}\n"
            f"ArtistAlias        : {self.artist_alias_count}  (writes)\n"
            f"Album              : {self.album_count}  (unique)\n"
            f"AlbumArtist        : {self.album_artist_count}  (unique)\n"
            f"Track              : {self.track_count}  (unique)\n"
            f"TrackArtist        : {self.track_artist_count}  (unique)\n"
            f"Release processed   : {self.release_count}\n"
            f"Release filtered    : {self.filtered_release_count}\n"
            f"Release skipped     : {self.skipped_release_count}\n"
            f"API requests        : {self.api_request_count}\n"
            f"Elapsed             : {self.elapsed():.2f}s\n"
            "=================================================="
        )


# ============================================================
# UUID 判断
# ============================================================

def is_mbid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


# ============================================================
# Artist 解析
# ============================================================

def resolve_artist(
    client: MusicBrainzClient,
    name_or_mbid: str,
    stats: ImportStats,
) -> dict:

    if is_mbid(name_or_mbid):

        print(f"检测到 MBID：{name_or_mbid}")

        artist = client.get_artist(
            name_or_mbid,
            inc="aliases+genres",
        )

        stats.api_request_count += 1

        return artist

    print(f"搜索 Artist：{name_or_mbid}")

    result = client.search_artist(
        name_or_mbid,
        limit=3,
    )

    stats.api_request_count += 1

    artists = result.get("artists", [])

    if not artists:
        raise ValueError(
            f"没有找到 Artist：{name_or_mbid}"
        )

    artist = artists[0]

    print(
        f"搜索结果：{artist.get('name')} "
        f"({artist.get('id')})"
    )

    artist = client.get_artist(
        artist["id"],
        inc="aliases+genres",
    )

    stats.api_request_count += 1

    return artist


# ============================================================
# main import
# ============================================================

def import_artist(
    name_or_mbid: str,
    *,
    statuses: set[str] | None = {"Official"},
    primary_types: set[str] | None = {
        "Album",
        "EP",
        "Single",
    },
    page_size: int = 100,
    max_releases: int | None = None,
) -> ImportStats:

    stats = ImportStats()

    client = MusicBrainzClient(
        user_agent=MUSICBRAINZ_CONFIG["user_agent"]
    )

    adapter = MusicBrainzDataAdapter()

    connection = get_connection()

    # ========================================================
    # Repository
    # ========================================================

    artist_repository = ArtistRepository(connection)
    artist_alias_repository = ArtistAliasRepository(connection)

    album_repository = AlbumRepository(connection)
    album_artist_repository = AlbumArtistRepository(connection)

    track_repository = TrackRepository(connection)
    track_artist_repository = TrackArtistRepository(connection)

    release_repository = ReleaseRepository(connection)
    release_track_repository = ReleaseTrackRepository(connection)

    # ========================================================
    # 本次导入生命周期内的缓存
    # ========================================================

    artist_ids: dict[str, int] = {}
    album_ids: dict[str, int] = {}
    track_ids: dict[str, int] = {}

    # 关系表的唯一键是 (album_id, artist_id) / (track_id, artist_id)。
    # 一张专辑底下有多个 release，一首歌会出现在多张专辑里，
    # 同一对 id 会被反复算出来 —— 用 set 挡掉重复写入。
    # （不影响正确性，upsert 本来也幂等，纯粹是别白跑 SQL）
    seen_album_artists: set[tuple[int, int]] = set()
    seen_track_artists: set[tuple[int, int]] = set()

    # ========================================================
    # ① 解析 Artist
    # ========================================================

    print("=" * 60)
    print("① 解析 Artist")
    print("=" * 60)

    artist_data = resolve_artist(
        client,
        name_or_mbid,
        stats,
    )

    artist_mbid = artist_data["id"]

    # ========================================================
    # ② Artist 入库
    # ========================================================

    print()
    print("=" * 60)
    print("② 写入 Artist")
    print("=" * 60)

    artist = adapter.artist_to_musicmind(
        artist_data
    )

    artist_id = artist_repository.upsert(
        artist
    )

    artist_ids[artist["musicbrainz_id"]] = artist_id

    stats.artist_count += 1

    aliases = adapter.artist_aliases_to_musicmind(
        artist_data
    )

    for alias in aliases:

        artist_alias_repository.upsert(
            artist_id,
            alias,
            autocommit=False,
        )

        stats.artist_alias_count += 1

    # Artist 本体完成后立即提交
    connection.commit()

    print(
        f"Artist 已写入："
        f"{artist['name']} "
        f"(id={artist_id})"
    )

    # ========================================================
    # ③ Browse Releases
    # ========================================================

    print()
    print("=" * 60)
    print("③ Browse + 过滤 Artist Releases")
    print("=" * 60)

    offset = 0

    filtered_releases: list[dict] = []

    seen_release_mbids: set[str] = set()

    total_count = None

    while True:

        result = client.get_artist_releases(
            artist_mbid,
            limit=page_size,
            offset=offset,
        )

        stats.api_request_count += 1

        page_releases = result.get(
            "releases",
            []
        )

        total_count = result.get(
            "release-count",
            total_count,
        )

        print(
            f"Browse offset={offset} "
            f"本页={len(page_releases)} "
            f"总数={total_count} "
            f"已选={len(filtered_releases)}"
        )

        for release in page_releases:

            release_mbid = release.get("id")

            if not release_mbid:
                continue

            if release_mbid in seen_release_mbids:
                continue

            seen_release_mbids.add(
                release_mbid
            )

            # ------------------------------------------------
            # 边翻页边过滤
            # 每页自带 status / release-group，无需额外请求
            # ------------------------------------------------

            status = release.get("status")

            release_group = release.get(
                "release-group"
            ) or {}

            primary_type = release_group.get(
                "primary-type"
            )

            if (
                statuses is not None
                and status not in statuses
            ):
                stats.filtered_release_count += 1
                continue

            if (
                primary_types is not None
                and primary_type not in primary_types
            ):
                stats.filtered_release_count += 1
                continue

            filtered_releases.append(
                release
            )

            if (
                max_releases is not None
                and len(filtered_releases)
                >= max_releases
            ):
                break

        # 已经够数，不必再翻页
        # （超大艺人靠这个提前终止，否则要翻几十上百页）
        if (
            max_releases is not None
            and len(filtered_releases)
            >= max_releases
        ):

            print(
                f"已达 max_releases={max_releases}，"
                f"停止翻页"
            )
            break

        # 本页不足 page_size
        # 说明已经到最后一页
        if len(page_releases) < page_size:
            break

        offset += page_size

    print(
        f"浏览 {len(seen_release_mbids)} 个，"
        f"选出 {len(filtered_releases)} 个"
    )

    # ========================================================
    # ⑤ 逐 Release 获取详情
    # ========================================================

    for index, release in enumerate(
        filtered_releases,
        start=1,
    ):

        release_mbid = release["id"]

        print()
        print(
            f"[{index}/{len(filtered_releases)}] "
            f"处理 Release："
            f"{release.get('title')}"
        )

        try:

            # ------------------------------------------------
            # 获取 Release 详情
            # ------------------------------------------------

            data = client.get_release(
                release_mbid
            )

            stats.api_request_count += 1

            # ------------------------------------------------
            # Release Group → Album
            # ------------------------------------------------

            release_group = data.get(
                "release-group"
            )

            if not release_group:
                print(
                    "  跳过：没有 Release Group"
                )

                stats.skipped_release_count += 1
                continue

            album = adapter.album_to_musicmind(
                release_group
            )

            album_mbid = album[
                "musicbrainz_id"
            ]

            # Album 缓存
            album_id = album_ids.get(
                album_mbid
            )

            if album_id is None:

                album_id = album_repository.upsert(
                    album,
                    autocommit=False,
                )

                album_ids[
                    album_mbid
                ] = album_id

                stats.album_count += 1

            # ------------------------------------------------
            # Album Artist
            # ------------------------------------------------

            album_artists = (
                adapter.album_artists_to_musicmind(
                    release_group
                )
            )

            for credit in album_artists:

                credit_mbid = credit[
                    "artist_musicbrainz_id"
                ]

                credited_name = credit.get(
                    "credited_name"
                )

                # 先从本次导入缓存找
                related_artist_id = artist_ids.get(
                    credit_mbid
                )

                # 没有则创建 stub
                if related_artist_id is None:

                    related_artist_id = (
                        artist_repository.ensure_stub(
                            musicbrainz_id=credit_mbid,
                            name=credited_name,
                            autocommit=False,
                        )
                    )

                    artist_ids[
                        credit_mbid
                    ] = related_artist_id

                pair = (album_id, related_artist_id)

                # 同一专辑的另一个 release 会算出同一对 id
                if pair in seen_album_artists:
                    continue

                seen_album_artists.add(pair)

                album_artist_repository.upsert(
                    album_id=album_id,
                    artist_id=related_artist_id,
                    credited_name=credited_name,
                    join_phrase=credit.get(
                        "join_phrase"
                    ),
                    autocommit=False,
                )

                stats.album_artist_count += 1

            # ------------------------------------------------
            # Release
            # ------------------------------------------------

            release = adapter.release_to_musicmind(
                data
            )

            # MBID 换成本地 id
            release["album_id"] = album_ids[
                release.pop("album_musicbrainz_id")
            ]

            release_id = release_repository.upsert(
                release,
                autocommit=False,
            )

            # ------------------------------------------------
            # Track
            # ------------------------------------------------

            for media in data.get(
                "media",
                [],
            ):

                disc_number = (
                    media.get("position")
                    or 1
                )

                for track in media.get(
                    "tracks",
                    []
                ):

                    recording = track.get(
                        "recording"
                    ) or {}

                    recording_mbid = recording.get(
                        "id"
                    )

                    if not recording_mbid:
                        continue

                    # ----------------------------------------
                    # Track
                    # ----------------------------------------

                    track_id = track_ids.get(
                        recording_mbid
                    )

                    # 只在缓存未命中时 upsert
                    # stats.track_count 统计的是「新增行数」
                    if track_id is None:

                        track_data = (
                            adapter.track_to_musicmind(
                                track
                            )
                        )

                        track_id = (
                            track_repository.upsert(
                                track_data,
                                autocommit=False,
                            )
                        )

                        track_ids[
                            recording_mbid
                        ] = track_id

                        stats.track_count += 1

                    # ----------------------------------------
                    # Track Artist
                    # ----------------------------------------

                    track_artists = (
                        adapter.track_artists_to_musicmind(
                            recording
                        )
                    )

                    for credit in track_artists:

                        credit_mbid = credit[
                            "artist_musicbrainz_id"
                        ]

                        credited_name = credit.get(
                            "credited_name"
                        )

                        related_artist_id = (
                            artist_ids.get(
                                credit_mbid
                            )
                        )

                        if related_artist_id is None:

                            related_artist_id = (
                                artist_repository.ensure_stub(
                                    musicbrainz_id=credit_mbid,
                                    name=credited_name,
                                    autocommit=False,
                                )
                            )

                            artist_ids[
                                credit_mbid
                            ] = related_artist_id

                        pair = (track_id, related_artist_id)

                        # 同一首歌出现在多张专辑里，会算出同一对 id
                        if pair in seen_track_artists:
                            continue

                        seen_track_artists.add(pair)

                        track_artist_repository.upsert(
                            track_id=track_id,
                            artist_id=related_artist_id,
                            credited_name=credited_name,
                            join_phrase=credit.get(
                                "join_phrase"
                            ),
                            autocommit=False,
                        )

                        stats.track_artist_count += 1

                    # ----------------------------------------
                    # Release Track
                    # ----------------------------------------

                    release_track_repository.upsert(
                        release_id=release_id,
                        track_id=track_id,
                        track_number=track.get(
                            "position"
                        ),
                        disc_number=disc_number,
                        autocommit=False,
                    )

            # ------------------------------------------------
            # 一个 Release 完成
            # ------------------------------------------------

            connection.commit()

        except Exception as e:

            connection.rollback()

            stats.skipped_release_count += 1

            # 这个 print 自己也可能抛异常（输出重定向时
            # Windows 用 GBK 编码，编不出 ✓ / ✗），
            # 所以它必须在 except 里，不能让它误伤成功路径
            print(
                f"  ✗ Release 失败：{e}"
            )

            continue

        # 成功路径的打印放在 try 外面：
        # print 抛异常不应该被当成「写库失败」
        stats.release_count += 1

        print(
            f"  ✓ Release 完成"
        )

        # 每 50 个打印一次进度
        if index % 50 == 0:

            print(
                f"\n当前进度："
                f"{index}/{len(filtered_releases)}"
            )

    connection.close()

    return stats


# ============================================================
# 批量导入
# ============================================================

def import_artists(
    names: list[str],
    **kwargs,
) -> dict[str, ImportStats]:
    """
    批量导入多个艺人。

    单个艺人失败不会中断整批——
    管道本身是幂等的，失败的艺人直接重跑即可。
    """

    results: dict[str, ImportStats] = {}
    failed: list[str] = []

    for index, name in enumerate(names, start=1):

        print()
        print("#" * 60)
        print(
            f"# [{index}/{len(names)}] {name}"
        )
        print("#" * 60)

        try:

            results[name] = import_artist(
                name,
                **kwargs,
            )

        except Exception as e:

            print(f"  ✗ 艺人导入失败：{e}")

            failed.append(name)

    print_batch_summary(results, failed)

    return results


def print_batch_summary(
    results: dict[str, ImportStats],
    failed: list[str],
) -> None:

    print()
    print("=" * 60)
    print("批量导入汇总")
    print("=" * 60)

    total_api = 0
    total_elapsed = 0.0

    for name, stats in results.items():

        total_api += stats.api_request_count
        total_elapsed += stats.elapsed()

        print(
            f"  ✓ {name:26.26} "
            f"album {stats.album_count:4}  "
            f"release {stats.release_count:4}  "
            f"track {stats.track_count:5}  "
            f"api {stats.api_request_count:4}"
        )

    for name in failed:
        print(f"  ✗ {name}")

    print("-" * 60)
    print(
        f"  成功 {len(results)} / 失败 {len(failed)}"
    )
    print(
        f"  总 API 请求 {total_api}，"
        f"累计耗时 {total_elapsed:.1f}s"
    )
    print("=" * 60)


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description="MusicMind MusicBrainz 数据导入"
    )

    parser.add_argument(
        "artists",
        nargs="+",
        help="一个或多个 Artist 名称 / MusicBrainz Artist MBID",
    )

    parser.add_argument(
        "--no-status-filter",
        action="store_true",
        help="不限制 Release status",
    )

    parser.add_argument(
        "--primary-types",
        nargs="+",
        default=[
            "Album",
            "EP",
            "Single",
        ],
        help="Release Group primary types",
    )

    parser.add_argument(
        "--max-releases",
        type=int,
        default=None,
        help="最多处理多少个 Release",
    )

    parser.add_argument(
        "--page-size",
        type=int,
        default=100,
        help="MusicBrainz browse page size",
    )

    args = parser.parse_args()

    statuses = None

    if not args.no_status_filter:
        statuses = {"Official"}

    common = dict(
        statuses=statuses,
        primary_types=set(args.primary_types),
        page_size=args.page_size,
        max_releases=args.max_releases,
    )

    # 单个艺人：打印详细统计
    if len(args.artists) == 1:

        print(
            import_artist(
                args.artists[0],
                **common,
            )
        )

    # 多个艺人：打印批量汇总
    else:

        import_artists(
            args.artists,
            **common,
        )


if __name__ == "__main__":
    main()