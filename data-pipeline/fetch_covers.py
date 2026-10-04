from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

# 触发 load_dotenv()，把 .env 里的 HTTPS_PROXY 写进 os.environ。
# 必须在创建 requests.Session 之前 import。
from config.settings import MUSICBRAINZ_CONFIG

# 【目录和落盘都从 cover 包里拿】按需入库（ingest_release.py）也要写同一个目录，
# 各写一份的话迟早漂移 —— 而漂移的表现是「批处理抓的图在，按需抓的不见了」，
# 页面上分不出是谁写的
from cover import COVER_DIR, CoverArtClient, save_cover
from database.connection import get_connection


@dataclass
class CoverStats:
    album_total: int = 0
    downloaded: int = 0
    skipped_existing: int = 0
    no_cover: int = 0
    failed: int = 0
    release_attempts: int = 0
    start_time: float = field(default_factory=time.time)

    def elapsed(self) -> float:
        return time.time() - self.start_time

    def __str__(self) -> str:
        return (
            "\n"
            "================ Cover Summary ================\n"
            f"Album total        : {self.album_total}\n"
            f"Downloaded         : {self.downloaded}\n"
            f"Skipped (existing) : {self.skipped_existing}\n"
            f"No cover found     : {self.no_cover}\n"
            f"Failed             : {self.failed}\n"
            f"Release attempts   : {self.release_attempts}\n"
            f"Elapsed            : {self.elapsed():.1f}s\n"
            "==============================================="
        )


def describe_proxy() -> str:
    """
    报告当前生效的代理。密码用 *** 遮掉。
    """
    proxy = (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
    )

    if not proxy:
        return "未检测到代理（archive.org 大概率不可达）"

    # http://user:pass@host:port -> http://user:***@host:port
    if "@" in proxy:
        scheme, rest = proxy.split("://", 1)
        cred, host = rest.split("@", 1)
        user = cred.split(":")[0]
        return f"{scheme}://{user}:***@{host}"

    return proxy


def load_album_releases(connection) -> list[tuple[int, str, list[str]]]:
    """
    返回 [(album_id, album_name, [release_mbid, ...]), ...]

    release 按「最早发行在前」排序，和专辑详情页的默认版本规则一致。
    封面就按这个顺序试，取第一个有图的。
    """
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT a.id           AS album_id,
                   a.name         AS album_name,
                   mr.musicbrainz_id AS release_mbid,
                   mr.release_date,
                   mr.id          AS release_id
            FROM album a
            JOIN music_release mr ON mr.album_id = a.id
            ORDER BY a.id,
                     mr.release_date IS NULL,
                     mr.release_date,
                     mr.id
            """
        )
        rows = cursor.fetchall()

    albums: dict[int, tuple[str, list[str]]] = {}

    for row in rows:
        album_id = row["album_id"]
        if album_id not in albums:
            albums[album_id] = (row["album_name"], [])
        albums[album_id][1].append(row["release_mbid"])

    return [
        (album_id, name, mbids)
        for album_id, (name, mbids) in albums.items()
    ]


def fetch_all(
    *,
    size: int = 250,
    limit: int | None = None,
    force: bool = False,
    check_only: bool = False,
) -> CoverStats:

    stats = CoverStats()

    print("=" * 60)
    print("Cover Art Archive 抓取")
    print("=" * 60)
    print(f"代理      : {describe_proxy()}")
    print(f"输出目录  : {COVER_DIR}")
    print(f"图片尺寸  : front-{size}")

    client = CoverArtClient(
        user_agent=MUSICBRAINZ_CONFIG["user_agent"],
    )

    connection = get_connection()
    albums = load_album_releases(connection)
    connection.close()

    if limit is not None:
        albums = albums[:limit]

    stats.album_total = len(albums)
    print(f"待处理专辑: {len(albums)}")
    print("=" * 60)

    if check_only:
        # 拿第一张专辑的第一个 release 探一下路
        album_id, name, mbids = albums[0]
        print(f"\n连通性探测：album {album_id}《{name}》release {mbids[0]}")
        data = client.fetch_front(mbids[0], size=size)
        if data is None:
            print("  连上了，但这个 release 没有封面（404 也是有效响应）")
        else:
            print(f"  拿到 {len(data)} 字节")
        return stats

    manifest: dict[str, dict] = {}

    for index, (album_id, name, mbids) in enumerate(albums, start=1):
        target = COVER_DIR / f"{album_id}.jpg"

        if target.exists() and not force:
            stats.skipped_existing += 1
            manifest[str(album_id)] = {"release_mbid": None, "status": "existing"}
            continue

        print(f"[{index}/{len(albums)}] album {album_id}《{name}》 "
              f"({len(mbids)} 个 release)")

        saved_mbid = None

        for mbid in mbids:
            stats.release_attempts += 1
            try:
                data = client.fetch_front(mbid, size=size)
            except Exception as e:
                print(f"    ✗ {mbid} 失败：{e}")
                continue

            if data is None:
                continue

            save_cover(album_id, data)
            saved_mbid = mbid
            stats.downloaded += 1
            print(f"    ✓ {mbid} -> {len(data)} 字节")
            break

        if saved_mbid:
            manifest[str(album_id)] = {"release_mbid": saved_mbid, "status": "ok"}
        else:
            stats.no_cover += 1
            manifest[str(album_id)] = {"release_mbid": None, "status": "no_cover"}
            print("    - 所有 release 都没有封面")

    COVER_DIR.mkdir(parents=True, exist_ok=True)
    (COVER_DIR / "_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return stats


def main():
    parser = argparse.ArgumentParser(description="从 Cover Art Archive 抓取专辑封面")

    parser.add_argument("--size", type=int, default=250,
                        help="front-N 的 N（250/500/1200），默认 250")
    parser.add_argument("--limit", type=int, default=None,
                        help="只处理前 N 张专辑，用来先验证通路")
    parser.add_argument("--force", action="store_true",
                        help="已存在的文件也重下")
    parser.add_argument("--check", action="store_true",
                        help="只做连通性探测，不批量下载")

    args = parser.parse_args()

    stats = fetch_all(
        size=args.size,
        limit=args.limit,
        force=args.force,
        check_only=args.check,
    )

    print(stats)


if __name__ == "__main__":
    main()
