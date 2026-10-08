"""型匹配的边界。**这个文件的每个用例都是构造的 facts**，不碰数据库不调网。"""

from musicmind_agent.persona_types import score_types, WILDCARD


def _facts(**kw):
    """最小可用的 facts 仓：只放用例关心的键"""
    return dict(kw)


def test_low_energy_narrow_first_is_nightwatch():
    out = score_types(_facts(**{"mood.arousal_mean": 0.30,
                                "diversity.genre_entropy": 0.40}))
    assert out[0]["name"] == "守夜人"


def test_high_energy_wide_first_is_dj():
    out = score_types(_facts(**{"mood.arousal_mean": 0.80,
                                "diversity.genre_entropy": 0.85}))
    assert out[0]["name"] == "隔壁的 DJ"


def test_old_median_year_archaeologist_in_top3():
    out = score_types(_facts(**{"mood.arousal_mean": 0.50,
                                "diversity.genre_entropy": 0.60,
                                "era.median_year": 1998}))
    assert "考古学家" in [x["name"] for x in out]


def test_missing_facts_do_not_crash_and_renormalize():
    # 只有能量、没有宽度：守夜人/高速公路 都该在候选里（宽度权重的缺失不该算它输）
    out = score_types(_facts(**{"mood.arousal_mean": 0.30}))
    assert len(out) == 3
    assert all(isinstance(x["score"], float) for x in out)


def test_nothing_matches_wildcard_first():
    # 所有目标区间都远离 —— 兜底型必须上第一位
    out = score_types(_facts(**{"mood.arousal_mean": 0.9999,
                                "diversity.genre_entropy": 0.9999}))
    assert out[0]["name"] == WILDCARD["name"] or out[0]["score"] >= 0.35


def test_deterministic():
    f = _facts(**{"mood.arousal_mean": 0.45, "diversity.genre_entropy": 0.64,
                  "era.median_year": 2015})
    assert score_types(f) == score_types(f)


def test_top_genre_share_derived_key():
    # genre.album.* 是动态键：派生上限应该被「一柜子同款」用起来
    out = score_types(_facts(**{"genre.album.mandopop.share": 0.95,
                                "mood.arousal_mean": 0.45,
                                "diversity.genre_entropy": 0.64}))
    assert "一柜子同款" in [x["name"] for x in out]


def test_all_types_reachable():
    """22 个型每个都要「够得着」—— 构造一个正中靶心的 facts，看它进不进 top1。"""
    cases = {
        "守夜人": {"mood.arousal_mean": 0.30, "diversity.genre_entropy": 0.40},
        "壁炉边的猫": {"mood.arousal_mean": 0.30, "diversity.genre_entropy": 0.60},
        "深夜漫游者": {"mood.arousal_mean": 0.30, "diversity.genre_entropy": 0.85},
        "老唱片店的常客": {"mood.arousal_mean": 0.48, "diversity.genre_entropy": 0.40},
        "温吞的听者": {"mood.arousal_mean": 0.48, "diversity.genre_entropy": 0.60},
        "杂货铺老板": {"mood.arousal_mean": 0.48, "diversity.genre_entropy": 0.85},
        "单曲循环怪": {"mood.arousal_mean": 0.70, "diversity.genre_entropy": 0.40},
        "高速公路": {"mood.arousal_mean": 0.70, "diversity.genre_entropy": 0.60},
        "隔壁的 DJ": {"mood.arousal_mean": 0.70, "diversity.genre_entropy": 0.85},
        "考古学家": {"era.median_year": 1998},
        "追新猎手": {"era.median_year": 2025},
        "时光旅行者": {"diversity.decades_covered": 6},
        "某人的头号歌迷": {"artist.top1_share": 0.30},
        "一柜子同款": {"genre.album.mandopop.share": 0.80},
        "华语钉子户": {"region.mandarin_share": 0.95},
        "跨洋听众": {"region.non_mandarin_share": 0.60},
        "黑胶收藏家": {"scope.tracks": 800, "coverage.genre_ratio": 0.80},
        "全自动点唱机": {"diversity.genre_entropy": 0.90,
                          "diversity.artists_per_100_tracks": 60},
        "雨天限定": {"mood.arousal_mean": 0.30, "mood.valence_inferred_mean": 0.30},
        "过山车乘客": {"mood.arousal_measured_max": 0.90,
                       "mood.arousal_measured_min": 0.20},
        "隐藏款听众": {"diversity.singleton_artist_share": 0.90},
    }
    for name, f in cases.items():
        out = score_types(_facts(**f))
        assert out[0]["name"] == name, f"{name} 没排到第一，实际第一是 {out[0]['name']}"