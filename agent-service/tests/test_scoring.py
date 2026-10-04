"""打分与音频特征的测试。全部离线、无随机性。"""

from __future__ import annotations

import pytest

from musicmind_agent.audio.features import fold_tempo, normalize
from musicmind_agent.evidence import EnrichedTrack
from musicmind_agent.reco.score import DEFAULT_WEIGHTS, build_profile, content_score


def track(track_id: int, **kw) -> EnrichedTrack:
    base = dict(
        track_id=track_id, track_name=f"t{track_id}", duration_ms=240_000,
        artist_id=1, artist_name="A", country_code=None,
        album_id=1, album_name="al", release_date="2010-01-01", primary_type="Album",
        album_genres=(), artist_genres=(), arousal_measured=None, artist_verified=True,
    )
    base.update(kw)
    return EnrichedTrack(**base)


# ---------------------------------------------------------------
# 音频
# ---------------------------------------------------------------

@pytest.mark.parametrize("raw,expected_range", [
    (184.6, (60, 160)),     # 实测：《演员》被 librosa 估成 184.6，明显是倍频错误
    (40.0, (60, 160)),
    (120.0, (60, 160)),
])
def test_fold_tempo_lands_in_range(raw, expected_range):
    folded = fold_tempo(raw)
    assert expected_range[0] <= folded < expected_range[1]


def test_fold_tempo_handles_garbage():
    assert fold_tempo(0) is None
    assert fold_tempo(-5) is None
    assert fold_tempo(float("nan")) is None


def test_normalize_clamps():
    assert normalize(50, 0, 100) == 0.5
    assert normalize(-10, 0, 100) == 0.0
    assert normalize(999, 0, 100) == 1.0
    assert normalize(5, 10, 10) == 0.5      # 退化区间不该炸


# ---------------------------------------------------------------
# 口味画像
# ---------------------------------------------------------------

def test_build_profile_counts_genres_and_artists():
    tracks = [
        track(1, album_genres=("mandopop",), artist_id=1),
        track(2, album_genres=("mandopop", "ballad"), artist_id=2),
        track(3, artist_genres=("hip hop",), artist_id=2),
    ]
    profile = build_profile(tracks)
    assert profile.known_tracks == {1, 2, 3}
    assert profile.known_artists == {1, 2}
    # 分母是【流派总数】不是曲目数 —— 一首歌有多个流派时两边都要计数。
    # 这里 mandopop×2 + ballad×1 + hip hop×1 = 4
    assert profile.genre_share["mandopop"] == pytest.approx(2 / 4)
    assert 2 in profile.top_artists


def test_profile_uses_artist_genre_as_fallback():
    """专辑级没有时退到艺人级 —— 库里 90% 的歌靠这条兜底。"""
    tracks = [track(1, album_genres=(), artist_genres=("mandopop",))]
    assert build_profile(tracks).genre_share.get("mandopop") == 1.0


# ---------------------------------------------------------------
# 内容打分
# ---------------------------------------------------------------

def test_score_is_deterministic():
    """评估要跑 5 折 × 6 个系统，任何随机性都会让对比失去意义。"""
    profile = build_profile([track(1, album_genres=("pop",))])
    candidate = track(99, album_genres=("pop",))
    assert content_score(candidate, profile) == content_score(candidate, profile)


def test_score_returns_components_not_just_total():
    """原则 4：推荐必须能说明「为什么」。解释的骨架就是这些分量 ——
    只返回一个总分，解释就只能靠 LLM 现编。"""
    profile = build_profile([track(1, album_genres=("pop",))])
    parts = content_score(track(99, album_genres=("pop",)), profile)
    assert "total" in parts
    for name in DEFAULT_WEIGHTS:
        assert name in parts, f"缺少分量 {name}"
    assert "novelty" in parts


def test_known_artist_scores_higher_than_unknown():
    profile = build_profile([track(1, artist_id=7, album_genres=("pop",))])
    known = content_score(track(99, artist_id=7, album_genres=("pop",)), profile)
    unknown = content_score(track(98, artist_id=8, album_genres=("pop",)), profile)
    assert known["artist"] > unknown["artist"]


def test_missing_genre_is_neutral_not_zero():
    """没有流派标注 ≠ 不像。

    库里三分之二的专辑没有流派，给 0 会让这些候选被系统性埋掉 ——
    而它们中间恰恰可能有用户会喜欢的歌。
    """
    profile = build_profile([track(1, album_genres=("pop",))])
    parts = content_score(track(99, album_genres=(), artist_genres=()), profile)
    assert parts["genre"] == 0.5


def test_inferred_mood_is_not_used_for_similarity():
    """**推断出来的能量不参与相似度。**

    流派推出来的能量粒度太粗（宽流派一律 0.5），拿它装作「能量相似」
    是在制造一个假的相似度。只有实测行（arousal 非空）才算。
    """
    profile = build_profile([track(1, arousal_measured=0.2)])
    no_measure = content_score(track(99, arousal_measured=None), profile)
    assert no_measure["mood"] == 0.5      # 中性，不是「相似」
