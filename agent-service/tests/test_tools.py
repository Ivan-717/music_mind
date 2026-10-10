"""单个工具的行为测试。

和 test_contracts.py 的分工：那边测「所有工具是不是都守规矩」，
这边测「某个工具的某个参数真的起作用了吗」。

全部离线：候选池用 monkeypatch 顶掉，不连数据库、不调 LLM。
"""

from __future__ import annotations

from musicmind_agent.evidence import EnrichedTrack, EvidenceSet
from musicmind_agent.tools import call
from musicmind_agent.tools.base import ToolContext


def track(track_id: int, **kw) -> EnrichedTrack:
    base = dict(
        track_id=track_id, track_name=f"歌{track_id}", duration_ms=240_000,
        artist_id=1000 + track_id, artist_name=f"艺人{track_id}", country_code="CN",
        album_id=2000 + track_id, album_name=f"专辑{track_id}",
        release_date="2016-06-01", primary_type="Album",
        album_genres=("mandopop",), artist_genres=(),
        arousal_measured=None, artist_verified=True,
    )
    base.update(kw)
    return EnrichedTrack(**base)


def _ctx(user_tracks) -> ToolContext:
    """最小上下文。connection=None 是安全的 —— 候选池已经被顶掉了。"""
    return ToolContext(
        connection=None,
        evidence=EvidenceSet(user_id=1, favorite_ids=[],
                             playlist_ids=[t.track_id for t in user_tracks]),
        tracks=list(user_tracks),
        mood_map={},
        library_genre_counts={},
    )


def _pool(monkeypatch, tracks) -> None:
    monkeypatch.setattr("musicmind_agent.tools.explore.load_all_enriched",
                        lambda _conn: list(tracks))


# ---------------------------------------------------------------
# search_tracks 的能量筛选
# ---------------------------------------------------------------

def test_search_tracks_energy_max_actually_filters(monkeypatch):
    """按「能量不高于 N」筛曲目必须真的能筛出来。

    【这个用例的由来】字段名曾经被写成 `arousal_measured_measured`
    （像是某次 arousal → arousal_measured 的批量改名执行了两遍）。
    它不报语法错，只在真的传了 energy 区间时抛 AttributeError，
    而 tools.base.call() 会把工具异常兜成「空结果 + warning」——
    于是表现是【永远搜不到】，不是报错。整个「推荐一点 emo 的歌」
    的路径是死的，而 87 个测试全绿：search_tracks 一个用例都没有。
    """
    quiet = track(101, arousal_measured=0.20)
    loud = track(102, arousal_measured=0.85)
    # 没实测的不能靠「看起来符合」入选 —— 给它一个会误导的值也没用，
    # 判据是「这行有没有实测」，不是「它看起来像多少」
    unmeasured = track(103, arousal_measured=None)
    _pool(monkeypatch, [quiet, loud, unmeasured])

    result = call("search_tracks", _ctx([track(1)]), {"arousal_max": 0.4, "limit": 10})

    # 「执行失败」是工具抛异常时 call() 兜出来的措辞 —— 它出现就说明
    # 工具根本没跑完，而返回值仍然长得像一个正常的空结果
    assert not any("执行失败" in w for w in result.warnings), result.warnings
    assert [r["track_id"] for r in result.rows] == [101]
    assert result.facts["search.matched"] == 1


def test_search_tracks_energy_min_filters_the_other_way(monkeypatch):
    _pool(monkeypatch, [track(101, arousal_measured=0.20),
                        track(102, arousal_measured=0.85)])

    result = call("search_tracks", _ctx([track(1)]), {"arousal_min": 0.6, "limit": 10})

    assert not any("执行失败" in w for w in result.warnings), result.warnings
    assert [r["track_id"] for r in result.rows] == [102]


def test_search_tracks_without_energy_keeps_unmeasured(monkeypatch):
    """不带能量条件时，没有实测特征的歌必须照样搜得到。

    库里 4617 首只有 400 多首有实测特征 —— 默认把它们排除掉
    等于把这个工具废掉。只有【显式】带了 energy 区间才筛实测。
    """
    _pool(monkeypatch, [track(103, arousal_measured=None)])

    result = call("search_tracks", _ctx([track(1)]), {"limit": 10})

    assert [r["track_id"] for r in result.rows] == [103]
    assert not result.warnings


def test_search_tracks_warns_about_the_coverage_cost(monkeypatch):
    """带能量条件时要主动说出代价 —— 命中数偏少是覆盖率问题，
    不是「库里没有这样的歌」，模型得知道这个区别才写得出诚实的话。"""
    _pool(monkeypatch, [track(101, arousal_measured=0.20)])

    result = call("search_tracks", _ctx([track(1)]), {"arousal_max": 0.4})

    assert any("实测特征" in w for w in result.warnings), result.warnings


# ---------------------------------------------------------------
# artist_affinity 的未入库半边（层 2：Wikidata 缓存）
# ---------------------------------------------------------------

def test_artist_affinity_registered_tool_actually_runs():
    """【回归】走 REGISTRY 的 artist_affinity 必须是能跑的工具函数本身。

    实测事故：层 1 把 load_unmatched 插在 @register 和 artist_affinity 之间，
    装饰器贴到了 load_unmatched 上 —— 生产路径走 call() 调它，参数对不上
    （connection 收到 ToolContext）直接抛 AttributeError，被 call() 吞成
    warning，「头部艺人」和整段未入库素材静默消失。直调函数测不出来
    （那正是当时测试全绿的原因），只有走 call() 才复现。
    """
    result = call("artist_affinity", _ctx([track(1)]))

    assert not any("执行失败" in w for w in result.warnings), result.warnings
    assert "artist.distinct" in result.facts

def test_unmatched_genre_aggregates_by_tracks(tmp_path, monkeypatch):
    """未入库流派按**曲目加权**聚合，且覆盖率和聚合数一起出。

    按艺人数加权的话，25 首的头部艺人和 1 首的长尾同权 —— 画像要回答的
    是「这些歌里什么最多」，所以口径必须是曲目数。覆盖率（coverage）也
    必须如实带出：464 位里只有约 1/4 查得到条目，展示层靠它说「有据可查」。
    """
    import json

    from musicmind_agent.tools import profile

    wd = {
        "c-block": {"v": 2, "genres": ["嘻哈音樂"], "country": ["中华人民共和国"]},
        "马思唯": {"v": 2, "genres": ["嘻哈音樂"], "country": []},
        "无名氏": {"v": 2, "miss": True},
    }
    p = tmp_path / "wikidata_artists.json"
    p.write_text(json.dumps(wd, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(profile, "_WD_PATH", p)
    monkeypatch.setattr(profile, "_WD_CACHE", {"mtime": -1.0, "data": {}})
    monkeypatch.setattr(profile, "_unmatched_context", lambda ctx: [
        {"title": "a", "artists": "C-BLOCK", "release_year": 2020},
        {"title": "b", "artists": "C-BLOCK / 某人", "release_year": 2021},
        {"title": "c", "artists": "马思唯", "release_year": 2022},
        {"title": "d", "artists": "无名氏", "release_year": 2023},
    ])

    facts = profile.artist_affinity(_ctx([track(1)]), {}).facts

    assert facts["unmatched.tracks"] == 4
    assert facts["unmatched.genre.tracks"] == 3          # 3/4 首查得到流派
    assert facts["unmatched.genre.coverage"] == 0.75
    assert facts["unmatched.genre.嘻哈音樂.tracks"] == 3  # 2 + 1，按曲目加权
    assert facts["unmatched.genre.嘻哈音樂.share"] == 1.0
    assert facts["unmatched.country.中华人民共和国.tracks"] == 2


def test_unmatched_genre_absent_without_cache(tmp_path, monkeypatch):
    """没跑过抓取（缓存文件不存在）→ 一个 unmatched.genre.* 都不出。

    出默认值等于编数据；层 2 缺席时画像退回层 1 的口径，静默降级但不出假话。
    """
    from musicmind_agent.tools import profile

    monkeypatch.setattr(profile, "_WD_PATH", tmp_path / "nope.json")
    monkeypatch.setattr(profile, "_WD_CACHE", {"mtime": -1.0, "data": {}})
    monkeypatch.setattr(profile, "_unmatched_context", lambda ctx: [
        {"title": "a", "artists": "C-BLOCK", "release_year": 2020},
    ])

    facts = profile.artist_affinity(_ctx([track(1)]), {}).facts

    assert facts["unmatched.tracks"] == 1
    assert not any(k.startswith("unmatched.genre.") for k in facts)
