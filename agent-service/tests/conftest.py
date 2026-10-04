"""测试用的假上下文。

【为什么不连真数据库】验证器的测试测的是**逻辑**，不是数据。
连上库之后，测试的结果会随着库里内容变化 —— 那种测试今天绿明天红，
最后没人愿意跑。真数据留给端到端那一组（跑 out/ 里的真实报告）。
"""

from __future__ import annotations

import pytest

from musicmind_agent.evidence import EnrichedTrack, EvidenceSet
from musicmind_agent.tools.base import ToolContext


def make_track(track_id: int, **kw) -> EnrichedTrack:
    base = dict(
        track_id=track_id,
        track_name=f"歌{track_id}",
        duration_ms=240_000,
        artist_id=100 + track_id,
        artist_name=f"艺人{track_id}",
        country_code="CN",
        album_id=200 + track_id,
        album_name=f"专辑{track_id}",
        release_date="2016-06-01",
        primary_type="Album",
        album_genres=("mandopop",),
        artist_genres=(),
        arousal_measured=0.42,
        artist_verified=True,
    )
    base.update(kw)
    return EnrichedTrack(**base)


@pytest.fixture
def fake_ctx_double() -> ToolContext:
    """最小可用的 ToolContext。

    facts 里的键是照着真实 facts 仓的形状挑的 —— 尤其是
    `mood.arousal_measured_mean` / `mood.arousal_median` 这一对：
    qwen 那次失败正是把这两个名字拼成了 `mood.arousal_measured_median`，
    所以测试数据必须让这个「拼出来的键」看起来很近，否则测不到东西。

    connection=None 是有意的：验证器的 L5 只在有推荐项时才会查库，
    这一组测试的推荐列表是空的，走不到那里。
    """
    tracks = [
        make_track(1, album_genres=("mandopop",), arousal_measured=0.30),
        make_track(2, album_genres=("mandopop", "ballad"), arousal_measured=0.80),
        make_track(3, album_genres=(), artist_genres=("hip hop",), arousal_measured=None),
    ]

    facts = {
        # 真实 facts 仓里存在的一组键
        "scope.tracks": 3,
        "scope.artists": 3,
        "coverage.genre": 3,
        "coverage.genre_ratio": 1.0,
        "coverage.genre_via_album": 2,
        "coverage.genre_via_album_ratio": 0.6667,
        "genre.album.mandopop.share": 0.6667,
        "genre.album.mandopop.tracks": 2,
        "genre.album.mandopop.lift": 2.3,
        # 这一对是 qwen 拼接的来源 —— 注意【没有】mood.arousal_measured_median
        "mood.arousal_measured_mean": 0.55,
        "mood.arousal_median": 0.55,
        "mood.measured_tracks": 2,
        "era.2015.share": 1.0,
        "artist.top5_share": 1.0,
        "artist.艺人1.share": 0.3333,
    }

    return ToolContext(
        connection=None,
        evidence=EvidenceSet(user_id=1, favorite_ids=[], playlist_ids=[1, 2, 3]),
        tracks=tracks,
        mood_map={},
        library_genre_counts={"mandopop": 10},
        facts=facts,
    )
