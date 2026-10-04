"""Tier 2 支撑工具：全库口径 + 按 id 查详情。

不是给 LLM 做分析的，是给它「引用具体歌」和「说全库有多少」用的。
报告里写「在库里 4617 首里」这种话，数字必须来自这里。
"""

from __future__ import annotations

from musicmind_agent.evidence import load_enriched
from musicmind_agent.tools.base import ToolContext, ToolResult, cap_evidence, cov, register


@register(
    "library_stats", 2,
    "全库规模与流派分布。报告里说「全库有 N 首」时必须引用这里的数字",
)
def library_stats(ctx: ToolContext, args: dict) -> ToolResult:
    with ctx.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM track)  AS tracks,
              (SELECT COUNT(*) FROM artist) AS artists,
              (SELECT COUNT(*) FROM album)  AS albums,
              (SELECT COUNT(*) FROM track_audio_feature) AS analyzed
            """
        )
        row = cursor.fetchone()

    top_genres = sorted(ctx.library_genre_counts.items(), key=lambda x: -x[1])[:10]

    return ToolResult(
        tool="library_stats",
        facts={
            "library.tracks": row["tracks"],
            "library.artists": row["artists"],
            "library.albums": row["albums"],
            "library.audio_analyzed": row["analyzed"],
        },
        rows=[
            {"全库曲目": row["tracks"], "全库艺人": row["artists"],
             "全库专辑": row["albums"], "有音频特征": row["analyzed"]},
            *[{"全库流派 Top": f"{name} {count}"} for name, count in top_genres],
        ],
        coverage=cov(row["tracks"], row["analyzed"],
                     "全库口径。用户的画像只基于他自己的曲目，不受这里影响"),
    )


@register(
    "get_tracks", 2,
    "按 id 批量查曲目详情。写证据名字、追问时回查证据都用它",
    {"track_ids": "曲目 id 列表"},
)
def get_tracks(ctx: ToolContext, args: dict) -> ToolResult:
    ids = [int(i) for i in (args.get("track_ids") or [])][:30]
    if not ids:
        return ToolResult(tool="get_tracks", warnings=["没有给 track_ids"])

    tracks = load_enriched(ctx.connection, ids)

    return ToolResult(
        tool="get_tracks",
        facts={"tracks.requested": len(ids), "tracks.found": len(tracks)},
        rows=[
            {
                "track_id": t.track_id,
                "歌名": t.track_name,
                "艺人": t.artist_name,
                "专辑": t.album_name,
                "发行年": t.year,
                "流派": list(t.genres),
                "能量": t.arousal_measured,
            }
            for t in tracks
        ],
        evidence=cap_evidence([ctx.evidence_for(t, why="按 id 查得") for t in tracks]),
        coverage=cov(len(ids), len(tracks), "找不到的 id 可能是已被删除的曲目"),
    )
