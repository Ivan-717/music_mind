"""批量算曲目音频特征。把用户的歌从「只有标题和流派」变成「有实测的音乐能量」。

用法：
    python analyze_tracks.py                 # 处理所有还没算过的目标曲目
    python analyze_tracks.py --limit 20      # 先跑一小批看看
    python analyze_tracks.py --reanalyze     # 连算过的也重算（换算法后用）

【目标曲目怎么选】所有出现在某个用户歌单里、且已对齐（MATCHED）的不重复曲目，
外加所有被收藏过的曲目。这是「画像的输入」——推荐候选池不在这里，
它们暂时只有流派推断，没有实测特征（见方案里的诚实的缺口第 3 条）。

【限速】iTunes 约 20-25 请求/分。441 首大约 20 分钟。可断点续跑：
每首算完立刻提交，中断了重跑就接着来。
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

import requests  # noqa: E402

from musicmind_agent.audio import features as F  # noqa: E402
from musicmind_agent.audio.itunes import fetch_waveform, search_preview  # noqa: E402
from musicmind_agent.db import get_connection  # noqa: E402

# 拿不到试听的原因分两类：permanent=1 的续跑时跳过，=0 的下次还会重试
PERMANENT_REASONS = ("iTunes 上没有这首",)


@dataclass
class Stats:
    total: int = 0
    ok: int = 0
    verified: int = 0
    failed: int = 0
    skipped: int = 0
    start_time: float = field(default_factory=time.time)

    def elapsed(self) -> float:
        return time.time() - self.start_time

    def __str__(self) -> str:
        p = self.ok or 1
        return (
            "\n"
            "================ Analyze Summary ================\n"
            f"目标曲目  : {self.total}\n"
            f"成功      : {self.ok}\n"
            f"  其中艺人核对上的 : {self.verified} ({self.verified / p * 100:.0f}%)\n"
            f"失败      : {self.failed}\n"
            f"跳过(已算过): {self.skipped}\n"
            f"耗时      : {self.elapsed():.0f}s\n"
            "================================================="
        )


def load_aliases(connection) -> dict[int, tuple[str, ...]]:
    """艺人 id → 别名。iTunes 美国店存的是 "Jay Chou" 这种罗马字名，
    拿中文名去比永远对不上；有别名能把「艺人核对上」的比例拉起来。

    别名很少（全库 321 条），一次全读进内存。
    """
    aliases: dict[int, list[str]] = {}
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT artist_id, name FROM artist_alias
            WHERE name IS NOT NULL AND name <> ''
            """
        )
        for row in cursor.fetchall():
            aliases.setdefault(row["artist_id"], []).append(row["name"])
    return {k: tuple(v) for k, v in aliases.items()}


def load_targets(connection, limit: int | None, reanalyze: bool) -> list[dict]:
    """选出要分析的曲目。

    目标是「画像的输入」：出现在某个用户歌单里且已对齐的曲目，加上被收藏过的。
    推荐候选池不在这里 —— 它们暂时只有流派推断，没有实测特征。
    """
    already_done = "" if reanalyze else (
        "AND t.id NOT IN (SELECT track_id FROM track_audio_feature)"
    )

    # 【主艺人取 track_artist 里 id 最小的那条】
    # 一张表里一首歌可能有多个艺人（《珊瑚海》= 周杰倫 & 梁心頤），
    # 随便取一个会拿到合作者，搜索词就变成「珊瑚海 梁心頤」——搜不到。
    # track_artist 没有排序列，但入库时是按 MusicBrainz 的 credit 顺序插的，
    # 所以 id 最小的那条就是主艺人。
    sql = f"""
        SELECT t.id, t.name AS title, ar.name AS artist, ar.id AS artist_id
        FROM track t
        JOIN track_artist ta ON ta.id = (
                SELECT MIN(ta2.id) FROM track_artist ta2 WHERE ta2.track_id = t.id
             )
        JOIN artist ar ON ar.id = ta.artist_id
        WHERE t.id IN (
                SELECT matched_track_id FROM user_playlist_track
                WHERE match_status = 'MATCHED' AND matched_track_id IS NOT NULL
                  AND user_removed = 0
                UNION
                SELECT track_id FROM favorite_track
              )
          {already_done}
          AND t.id NOT IN (
                SELECT track_id FROM track_audio_analysis_fail WHERE permanent = 1
              )
        ORDER BY t.id
        {"LIMIT %s" if limit else ""}
    """

    with connection.cursor() as cursor:
        cursor.execute(sql, (limit,) if limit else ())
        return cursor.fetchall()


def record_failure(connection, track_id: int, reason: str) -> None:
    permanent = 1 if any(p in reason for p in PERMANENT_REASONS) else 0
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO track_audio_analysis_fail (track_id, reason, permanent, attempts)
            VALUES (%s, %s, %s, 1)
            ON DUPLICATE KEY UPDATE
                reason = VALUES(reason),
                permanent = VALUES(permanent),
                attempts = attempts + 1
            """,
            (track_id, reason[:255], permanent),
        )
    connection.commit()


def save_feature(connection, track_id: int, feature: F.AudioFeature,
                 preview_url: str, artist_verified: bool) -> None:
    row = feature.as_row()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO track_audio_feature
                (track_id, arousal_measured, tempo_bpm, rms, spectral_centroid, spectral_rolloff,
                 zero_crossing_rate, mode_major, mode_confidence, duration_s,
                 preview_url, artist_verified, analyzer_version)
            VALUES
                (%(track_id)s, %(arousal_measured)s, %(tempo_bpm)s, %(rms)s, %(spectral_centroid)s,
                 %(spectral_rolloff)s, %(zero_crossing_rate)s, %(mode_major)s,
                 %(mode_confidence)s, %(duration_s)s, %(preview_url)s,
                 %(artist_verified)s, %(analyzer_version)s)
            ON DUPLICATE KEY UPDATE
                arousal_measured = VALUES(arousal_measured), tempo_bpm = VALUES(tempo_bpm), rms = VALUES(rms),
                spectral_centroid = VALUES(spectral_centroid),
                spectral_rolloff = VALUES(spectral_rolloff),
                zero_crossing_rate = VALUES(zero_crossing_rate),
                mode_major = VALUES(mode_major), mode_confidence = VALUES(mode_confidence),
                duration_s = VALUES(duration_s), preview_url = VALUES(preview_url),
                artist_verified = VALUES(artist_verified),
                analyzer_version = VALUES(analyzer_version)
            """,
            {**row, "track_id": track_id, "preview_url": preview_url[:768],
             "artist_verified": 1 if artist_verified else 0},
        )
    connection.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="批量算曲目音频特征")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--reanalyze", action="store_true",
                        help="连算过的也重算（换算法版本后用）")
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": "MusicMind/0.1"})

    connection = get_connection()
    aliases = load_aliases(connection)
    targets = load_targets(connection, args.limit, args.reanalyze)

    stats = Stats()
    # 目标查询已经排除了算过的，这里的 skipped 只在 --reanalyze 时有意义
    stats.total = len(targets)

    print(f"目标 {stats.total} 首，iTunes 限速约 2.5 秒/次，预计 {stats.total * 3 / 60:.0f} 分钟…")

    for index, target in enumerate(targets, start=1):

        preview_url, verified = search_preview(
            target["title"], target["artist"], session,
            aliases=aliases.get(target["artist_id"], ()),
        )
        if not preview_url:
            stats.failed += 1
            record_failure(connection, target["id"], "iTunes 上没有这首")
            continue

        waveform, error = fetch_waveform(preview_url, session)
        if error:
            stats.failed += 1
            record_failure(connection, target["id"], error)
            continue

        feature = F.extract(waveform)
        save_feature(connection, target["id"], feature, preview_url, verified)

        stats.ok += 1
        stats.verified += verified

        if index % 25 == 0:
            print(
                f"  [{index}/{stats.total}] 成功 {stats.ok} "
                f"(艺人核对 {stats.verified}) 失败 {stats.failed} "
                f"耗时 {stats.elapsed():.0f}s"
            )

    connection.close()
    print(stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
