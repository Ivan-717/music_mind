"""分析范围：**「偏好从哪来」和「你已经有什么」是两件事**。

按一张歌单分析时，画像只来自那张歌单，但候选排除和探索判定必须看整个曲库。
两者混在一起的后果有两个，都不会报错，只是结果悄悄变得不对：

  · 候选池只排除那张歌单的歌 → 推荐你在别的歌单里已经有的歌
  · 探索配额把陈奕迅当陌生歌手 → 你在他那儿有 49 首，一半名额就废了

全部离线。真库上的 scope 过滤（SQL 那段）留给端到端验，这里测的是逻辑。
"""

from __future__ import annotations

from musicmind_agent.evidence import EnrichedTrack
from musicmind_agent.reco.recall import recommend
from musicmind_agent.reco.score import build_profile


def track(track_id: int, **kw) -> EnrichedTrack:
    base = dict(
        track_id=track_id, track_name=f"t{track_id}", duration_ms=240_000,
        artist_id=1000 + track_id, artist_name=f"A{track_id}", country_code=None,
        album_id=2000 + track_id, album_name=f"al{track_id}",
        release_date="2010-01-01", primary_type="Album",
        album_genres=("pop",), artist_genres=(),
        arousal_measured=None, artist_verified=True,
    )
    base.update(kw)
    return EnrichedTrack(**base)


# ---------------------------------------------------------------
# build_profile：不传 known_* 时行为必须和以前一模一样
# ---------------------------------------------------------------

def test_profile_defaults_to_scope_for_both():
    """全量分析和评估走的就是这条路 —— 默认值一旦变了，phase5 的评估数字就废了。"""
    tracks = [track(1, artist_id=7), track(2, artist_id=8)]
    p = build_profile(tracks)
    assert p.known_tracks == {1, 2}
    assert p.known_artists == {7, 8}


def test_profile_splits_taste_from_known():
    """偏好来自 scope，known_* 来自整体。"""
    scope = [track(1, artist_id=7, album_genres=("jay",))]
    p = build_profile(scope, known_artist_ids={7, 8}, known_track_ids={1, 2, 3})

    # 偏好只有 scope 那一首的影子
    assert set(p.genre_share) == {"jay"}
    assert p.top_artists == {7}
    # 「已经有」是整体的
    assert p.known_tracks == {1, 2, 3}
    assert p.known_artists == {7, 8}


# ---------------------------------------------------------------
# 候选池：排除整个曲库，不是排除 scope
# ---------------------------------------------------------------

def test_recall_excludes_whole_catalog_not_just_the_scope():
    """用户在别的歌单里已经有的歌，不能进候选池。"""
    from musicmind_agent.reco.recall import recall

    scope = [track(1, artist_id=7)]
    elsewhere = track(2, artist_id=9)        # 在别的歌单里，用户已经有
    fresh = track(99, artist_id=11)
    all_tracks = [track(1, artist_id=7), elsewhere, fresh]

    profile = build_profile(scope, known_artist_ids={7, 9}, known_track_ids={1, 2})
    merged = recall(scope, all_tracks, profile)

    assert 2 not in merged, "别的歌单里已有的歌不该进候选池"
    assert 99 in merged


# ---------------------------------------------------------------
# recommend：透传（这一环最容易漏，漏了是静默失效）
# ---------------------------------------------------------------

def test_recommend_passes_known_sets_to_build_profile(monkeypatch):
    import musicmind_agent.reco.recall as recall_mod

    captured = {}
    real = recall_mod.build_profile

    def spy(tracks, known_artist_ids=None, known_track_ids=None):
        captured["artists"] = known_artist_ids
        captured["tracks"] = known_track_ids
        return real(tracks, known_artist_ids, known_track_ids)

    monkeypatch.setattr(recall_mod, "build_profile", spy)

    recommend([track(1, artist_id=7)], [track(1, artist_id=7), track(99)],
              k=1, known_artist_ids={7, 8}, known_track_ids={1, 2})

    assert captured == {"artists": {7, 8}, "tracks": {1, 2}}


def test_explore_quota_splits_by_the_wide_known_set():
    """探索名额按「整个曲库的艺人」分，而不是按选中歌单的艺人分。

    这里 scope 只有周杰伦(7)，候选里 8 是「你在别的歌单里听过的」、
    9 是「完全没听过」。known_artists 传 {7, 8} 时，一半名额应该落到 9 身上。
    """
    scope = [track(1, artist_id=7)]
    pool = [track(100, artist_id=8), track(101, artist_id=8),
            track(200, artist_id=9), track(201, artist_id=9)]

    picked = recommend(scope, scope + pool, k=2, explore_quota=0.5,
                       known_artist_ids={7, 8}, known_track_ids={1})

    artists = {item.track.artist_id for item in picked}
    assert 9 in artists, f"陌生歌手那一半名额没留出来：{artists}"


def test_recommend_excludes_same_name_same_artist():
    """同曲不同版本也要排除（2026-10-07 实测被用户当场指出）。

    库里同一首歌有多条 MBID 条目（薛之谦《绅士》= 14265 / 14268）：
    known_track_ids 只排掉用户对齐上的那一条，另一条照样进候选 ——
    用户看到「我歌单里有这首」又被推一次。
    排除键是 (归一名, 归一主艺人)：**同名不同人不误伤** ——
    队长的《哪里都是你》不该挡掉周杰伦的同名歌。
    """
    from musicmind_agent.validate.normalize import name_key

    me = track(1, track_name="绅士", artist_name="薛之谦")
    other_copy = track(2, track_name="绅士", artist_name="薛之谦")   # 同曲的另一个条目
    name_twin = track(3, track_name="绅士", artist_name="别的人")    # 同名不同人
    fresh = track(4, track_name="全新的歌", artist_name="新的人")

    known_keys = {(name_key("绅士"), name_key("薛之谦"))}
    picked = recommend([me], [me, other_copy, name_twin, fresh], k=2,
                       explore_quota=0.0, known_track_ids={1},
                       known_name_keys=known_keys)
    ids = {item.track.track_id for item in picked}
    assert 2 not in ids, "同曲的另一个条目不该被推荐"
    assert 3 in ids, "同名不同人不该被误伤"
    assert 4 in ids

    # 繁简/空格归一后也算同一首：库里条目写繁体、歌单写简体同样要排掉
    tc = track(5, track_name="紳士", artist_name="薛之謙")
    picked2 = recommend([me], [me, tc, fresh], k=2, explore_quota=0.0,
                        known_track_ids={1}, known_name_keys=known_keys)
    assert 5 not in {i.track.track_id for i in picked2}, "繁简差异漏排了"

    # 括号附注也算同一首（实测：「守候」和库里的「守候 (2020重唱版)」）
    assert name_key("守候 (2020重唱版)") == name_key("守候")
    assert name_key("守候（2020重唱版）") == name_key("守候")
