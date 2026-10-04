"""证据集：一个用户的「音乐」到底是哪些曲目，以及它们的全部可查属性。

【为什么单独抽一层】所有工具都要这两样东西：
  1. 用户的曲目 id 集合（收藏 + 歌单已对齐，去重）
  2. 这些曲目连带上艺人 / 专辑 / 流派 / 年代 / 音频特征

把它抽出来有三个好处：
  · 覆盖率的分母只有一个来源 —— 每个工具各算各的，迟早对不上
  · 评估时要「藏歌」，只需在构造 EvidenceSet 时减掉，不用改任何工具
  · 推荐要「排除用户已知的」，也只需要这一个集合

【藏歌（hidden）为什么放在这一层】评估要把一部分歌从画像里藏起来，
看推荐能不能把它们找回来。如果藏歌只体现在某个工具里，另一个工具就会
泄露它 —— 而这种泄露不会报错，只会让评估数字虚高。放这里，藏一次，
所有工具天然看不到。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 判定「证据不足」的门槛。低于这个数，任何画像都是硬编出来的。
# 库里有 9 个用户只收藏了 1-2 首 —— 他们走的是 insufficient_data 分支，
# 那不是失败，是设计的一部分
MIN_TRACKS = 20
MIN_ARTISTS = 5


@dataclass
class EvidenceSet:
    """用户的曲目集合。生产环境里 hidden 恒为空。"""

    user_id: int
    favorite_ids: list[int] = field(default_factory=list)
    playlist_ids: list[int] = field(default_factory=list)
    hidden_ids: set[int] = field(default_factory=set)

    @property
    def all_ids(self) -> list[int]:
        """去重后的全部曲目。**这是所有覆盖率的分母。**"""
        seen = dict.fromkeys(self.favorite_ids + self.playlist_ids)
        return [tid for tid in seen if tid not in self.hidden_ids]

    def is_empty(self) -> bool:
        return not self.all_ids


@dataclass
class EnrichedTrack:
    """一首歌 + 它能查到的全部属性。工具们共用这一个结构。"""

    track_id: int
    track_name: str
    duration_ms: int | None

    artist_id: int | None
    artist_name: str | None
    country_code: str | None

    album_id: int | None
    album_name: str | None
    release_date: str | None
    primary_type: str | None

    album_genres: tuple[str, ...]
    artist_genres: tuple[str, ...]

    arousal_measured: float | None
    artist_verified: bool

    @property
    def year(self) -> int | None:
        if not self.release_date:
            return None
        head = str(self.release_date)[:4]
        return int(head) if head.isdigit() else None

    @property
    def genres(self) -> tuple[str, ...]:
        """专辑流派优先，没有就退到艺人流派。

        【为什么要有这个回退】实测：vdev 的歌经专辑能拿到流派的只有 139/438，
        经艺人有 384/438。专辑级标注在 MusicBrainz 上很稀疏（精选集、演唱会、
        原声带几乎都没有），艺人级好得多。所以默认走「任一个」的口径，
        但两个来源在 facts 里分开记，报告里能说清依据来自哪一层。
        """
        return self.album_genres or self.artist_genres

    @property
    def genre_source(self) -> str | None:
        if self.album_genres:
            return "album"
        if self.artist_genres:
            return "artist"
        return None


# 取「这首歌的代表专辑」——和项目里 ImportMapper 用的是同一条规则：
# 发行日期最早的，日期为空排最后，再按 id 定序。**必须确定性**，
# 否则同一首歌两次查询可能落到不同专辑上，数字对不上还查不出原因
_ALBUM_PICK = """
    LEFT JOIN release_track rt ON rt.id = (
        SELECT rt2.id
        FROM release_track rt2
        JOIN music_release mr2 ON mr2.id = rt2.release_id
        WHERE rt2.track_id = t.id
        ORDER BY mr2.release_date IS NULL, mr2.release_date, mr2.id
        LIMIT 1)
    LEFT JOIN music_release mr ON mr.id = rt.release_id
    LEFT JOIN album al ON al.id = mr.album_id
"""

# 主艺人 = track_artist 里 id 最小的那条。没有排序列，但入库时是按
# MusicBrainz 的 credit 顺序插的（《珊瑚海》= 周杰倫 & 梁心頤，周杰倫在前）
_PRIMARY_ARTIST = """
    LEFT JOIN track_artist ta ON ta.id = (
        SELECT MIN(ta2.id) FROM track_artist ta2 WHERE ta2.track_id = t.id)
    LEFT JOIN artist ar ON ar.id = ta.artist_id
"""

_ENRICH_SQL = f"""
    SELECT t.id AS track_id, t.name AS track_name, t.duration_ms,
           ar.id AS artist_id, ar.name AS artist_name, ar.country_code,
           al.id AS album_id, al.name AS album_name,
           al.release_date, al.primary_type,
           (SELECT GROUP_CONCAT(g.name)
              FROM album_genre ag JOIN genre g ON g.id = ag.genre_id
             WHERE ag.album_id = al.id) AS album_genres,
           (SELECT GROUP_CONCAT(g.name)
              FROM artist_genre ag JOIN genre g ON g.id = ag.genre_id
             WHERE ag.artist_id = ar.id) AS artist_genres,
           af.arousal_measured, af.artist_verified
    FROM track t
    {_PRIMARY_ARTIST}
    {_ALBUM_PICK}
    LEFT JOIN track_audio_feature af ON af.track_id = t.id
    WHERE t.id IN ({{placeholders}})
"""


def resolve_user(connection, user_id: int, hidden_ids: set[int] | None = None) -> EvidenceSet:
    """把一个用户的收藏 + 歌单已对齐曲目读成 EvidenceSet。"""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT track_id FROM favorite_track WHERE user_id = %s", (user_id,)
        )
        favorites = [row["track_id"] for row in cursor.fetchall()]

        cursor.execute(
            """
            SELECT DISTINCT matched_track_id FROM user_playlist_track
            WHERE user_id = %s AND match_status = 'MATCHED'
              AND matched_track_id IS NOT NULL AND user_removed = 0
            """,
            (user_id,),
        )
        playlist = [row["matched_track_id"] for row in cursor.fetchall()]

    return EvidenceSet(
        user_id=user_id,
        favorite_ids=favorites,
        playlist_ids=playlist,
        hidden_ids=set(hidden_ids or ()),
    )


def _to_tracks(rows) -> list[EnrichedTrack]:
    def split(value) -> tuple[str, ...]:
        return tuple(g for g in (value or "").split(",") if g)

    return [
        EnrichedTrack(
            track_id=row["track_id"],
            track_name=row["track_name"],
            duration_ms=row["duration_ms"],
            artist_id=row["artist_id"],
            artist_name=row["artist_name"],
            country_code=row["country_code"],
            album_id=row["album_id"],
            album_name=row["album_name"],
            release_date=str(row["release_date"]) if row["release_date"] else None,
            primary_type=row["primary_type"],
            album_genres=split(row["album_genres"]),
            artist_genres=split(row["artist_genres"]),
            arousal_measured=(
                float(row["arousal_measured"]) if row["arousal_measured"] is not None else None
            ),
            artist_verified=bool(row["artist_verified"]),
        )
        for row in rows
    ]


def load_enriched(connection, track_ids: list[int]) -> list[EnrichedTrack]:
    """批量读指定曲目的全部属性。"""
    if not track_ids:
        return []

    sql = _ENRICH_SQL.format(placeholders=",".join(["%s"] * len(track_ids)))
    with connection.cursor() as cursor:
        cursor.execute(sql, track_ids)
        return _to_tracks(cursor.fetchall())


def load_all_enriched(connection) -> list[EnrichedTrack]:
    """全库曲目的全部属性。

    【为什么要全量】推荐和搜索的候选池是「全库减去用户已知」，也就是几千首。
    用 IN (...) 拼几千个占位符既慢又难看，而这些数据本来就要一次性载入内存。
    4617 行 × 十几个字段，几十 MB 的事。

    只在推荐/搜索路径用。画像路径永远走 load_enriched(user's ids) ——
    画像的分母必须只有用户自己的曲子，混进全库就全错了。
    """
    sql = _ENRICH_SQL.replace("WHERE t.id IN ({placeholders})", "")
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return _to_tracks(cursor.fetchall())
