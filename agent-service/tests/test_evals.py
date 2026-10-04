"""评估的离线部分。切分、天花板、指标、baseline —— 全是纯函数，秒级。"""

from __future__ import annotations

import pytest

from musicmind_agent.evals import metrics, splits


def test_random_folds_are_disjoint_and_cover_all():
    """5 折的藏歌必须互不重叠、合起来正好是全部 —— 否则某首歌被重复藏，
    或者从来没被藏过，两种都会让指标失真。"""
    class T:
        def __init__(self, i): self.track_id, self.artist_id = i, i // 3
    tracks = [T(i) for i in range(100)]
    folds = splits.random_item_folds(tracks, 5)
    union = set().union(*(f.hidden_ids for f in folds))
    assert len(union) == sum(len(f.hidden_ids) for f in folds)   # 不重叠
    assert union == {t.track_id for t in tracks}                 # 全覆盖


def test_artist_cold_hides_whole_artists():
    """按艺人藏：一个艺人要么全藏，要么全不藏。**半个艺人等于泄露**。"""
    class T:
        def __init__(self, i): self.track_id, self.artist_id = i, i // 3
    tracks = [T(i) for i in range(90)]
    folds = splits.artist_cold_folds(tracks, 5)
    by_artist = {}
    for t in tracks:
        by_artist.setdefault(t.artist_id, set()).add(t.track_id)
    for f in folds:
        for artist, ids in by_artist.items():
            assert ids <= f.hidden_ids or not (ids & f.hidden_ids)


def test_metric_perfect_and_zero():
    hidden = {1, 2, 3, 4}
    assert metrics.recall_at_k([1, 2, 3, 4], hidden, 20) == 1.0
    assert metrics.recall_at_k([9, 8, 7], hidden, 20) == 0.0
    assert metrics.recall_at_k([1, 2], hidden, 20) == 0.5


def test_recall_at_k_respects_k():
    """@20 只看前 20 个 —— 第 21 个命中不算。"""
    hidden = {99}
    assert metrics.recall_at_k([99] + list(range(100, 130)), hidden, 20) == 1.0
    assert metrics.recall_at_k(list(range(100, 120)) + [99], hidden, 20) == 0.0


def test_ceiling_is_a_diagnostic_not_a_guarantee():
    """天花板反映「库里有没有同类」。全部没有同类时应该是 0。"""
    class T:
        def __init__(self, i, artist, genres):
            self.track_id, self.artist_id, self.genres, self.album_id = i, artist, genres, i
    hidden_track = T(1, 100, ("说唱",))
    # 池子里只有另一个流派的歌，且艺人不同
    pool = [T(2, 200, ("古典",)), T(3, 201, ("古典",))]
    fold = splits.Fold(index=0, hidden_ids={1}, kind="artist_cold")
    ok, total = splits.ceiling(fold, [hidden_track] + pool, {"古典"}, {200, 201})
    assert (ok, total) == (0, 1)


def test_content_baseline_is_deterministic():
    """评估要跨系统对比，基线带随机性就没法比。"""
    from musicmind_agent.evals import baselines
    class T:
        def __init__(self, i): self.track_id, self.artist_id = i, i // 3
    assert baselines.random_pick([T(i) for i in range(50)], [T(0)], 5) == \
           baselines.random_pick([T(i) for i in range(50)], [T(0)], 5)

# ---------- 推荐的名额分配（评估给出的设计结论） ----------

def _mk(i, artist, genres=("mandopop",)):
    from musicmind_agent.evidence import EnrichedTrack
    return EnrichedTrack(
        track_id=i, track_name=f"歌{i}", duration_ms=240_000,
        artist_id=artist, artist_name=f"艺人{artist}", country_code="CN",
        album_id=i, album_name=f"专辑{i}", release_date="2016-01-01",
        primary_type="Album", album_genres=genres, artist_genres=(),
        arousal_measured=0.4, artist_verified=True,
    )


def test_recommend_reserves_slots_for_unfamiliar_artists():
    """【设计结论的回归】k 个位置里要留一部分给「没听过的歌手」。

    这是评估逼出来的：不留配额时，`artist` 分量把 top-k 全导向熟悉歌手，
    生人场景（整个歌手的歌都被藏掉）的「占上界」是 0.5% —— 和瞎猜一样。
    配额 0.5 之后是 4.5%，两个切分都打赢所有基线。

    不留配额的话这条会挂，那种回归是静默的：熟人场景分数照旧很好看。
    """
    from musicmind_agent.reco.recall import recommend

    user = [_mk(i, artist=1) for i in range(1, 11)]          # 用户只听过艺人 1
    pool = [_mk(i, artist=1) for i in range(11, 30)] + \
           [_mk(i, artist=a) for a in range(2, 8) for i in range(30 + a * 10, 38 + a * 10)]

    picked = recommend(user, user + pool, k=10, explore_quota=0.5)
    known = {t.artist_id for t in user}
    unfamiliar = [x for x in picked if x.track.artist_id not in known]
    assert len(unfamiliar) >= 4, f"陌生歌手只占了 {len(unfamiliar)}/10 个位置"


def test_recommend_quota_zero_falls_back_to_pure_relevance():
    """配额设 0 时应该完全按相关度排 —— 旋钮两边都要能拧到底。"""
    from musicmind_agent.reco.recall import recommend

    user = [_mk(i, artist=1) for i in range(1, 11)]
    pool = [_mk(i, artist=a) for a in range(2, 8) for i in range(30 + a * 10, 38 + a * 10)]
    picked = recommend(user, user + pool, k=5, explore_quota=0.0)
    assert len(picked) == 5
