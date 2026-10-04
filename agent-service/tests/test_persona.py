"""画像素材的测试。全部离线。

这一层的职责分界是它唯一的设计点：
    · 代码负责真实 —— 素材每条挂 fact key，依据行由代码渲染
    · LLM 负责好玩 —— 拿素材写意象

所以测试盯的就是「代码这一半有没有越界或不老实」。
"""

from __future__ import annotations

from musicmind_agent.persona import basis_line, traits_from_facts, render_traits


def full_facts(**over):
    facts = {
        "scope.tracks": 448, "scope.year_min": 2003, "scope.year_max": 2026,
        "mood.arousal_mean": 0.4265, "mood.measured_tracks": 418,
        "genre.album.mandopop.tracks": 402, "genre.album.mandopop.share": 0.9412,
        "genre.album.ballad.tracks": 35, "genre.album.ballad.share": 0.0819,
        "artist.薛之谦.tracks": 112, "artist.薛之谦.share": 0.25,
        "artist.top1_share": 0.25, "artist.top5_share": 0.52,
        "era.median_year": 2016,
        "diversity.genre_entropy": 0.61, "diversity.singleton_artist_share": 0.55,
    }
    facts.update(over)
    return facts


ROWS = {
    "genre_distribution": {"rows": [{"流派": "mandopop", "曲目数": 402},
                                    {"流派": "ballad", "曲目数": 35}]},
    "artist_affinity": {"rows": [{"艺人": "薛之谦", "曲目数": 112}]},
}


# ---------------------------------------------------------------
# 只挑不编
# ---------------------------------------------------------------

def test_missing_dimension_produces_no_trait():
    """没有的维度就不出素材，**不是给个默认值**。

    素材少几条，名字顶多朴素一点；编一条出去，整份报告的可信度就没了 ——
    而依据行是照着素材渲的，编的那条会显示成一个不存在的 key。
    """
    traits = traits_from_facts({"scope.tracks": 10})
    assert traits == []


def test_every_trait_key_exists_in_facts():
    facts = full_facts()
    for trait in traits_from_facts(facts, ROWS):
        assert trait.key in facts, f"{trait.key} 不在 facts 里 —— 依据行会渲染不出来"


def test_empty_facts_do_not_blow_up():
    assert traits_from_facts({}) == []
    assert basis_line([], {}) == ""
    assert "没有可用的素材" in render_traits([])


def test_traits_are_capped():
    assert len(traits_from_facts(full_facts(), ROWS, limit=2)) == 2


# ---------------------------------------------------------------
# 头部值的选取
# ---------------------------------------------------------------

def test_top_share_skips_top1_and_top5_aggregates():
    """`artist.top1_share` 名字像「某个叫 top1 的艺人」，而它的值往往最大 ——
    不排掉的话它一定被选中，然后名字会写成「top1 一个人占 25%」。
    """
    facts = full_facts(**{"artist.top1_share": 0.99})
    picked = [t.key for t in traits_from_facts(facts, ROWS)]
    assert "artist.薛之谦.share" in picked
    assert "artist.top1_share" not in picked


def test_uses_real_name_from_tool_rows():
    """fact key 是 _fact_key 洗过的，逆不回来 —— 真名得从工具 rows 里取。"""
    facts = full_facts(**{
        "genre.album.contemporary_r_b.tracks": 50,
        "genre.album.contemporary_r_b.share": 0.95,
    })
    rows = {"genre_distribution": {"rows": [{"流派": "contemporary R&B", "曲目数": 50}]}}
    reading = next(t.reading for t in traits_from_facts(facts, rows) if t.name == "头部流派")
    assert "contemporary R&B" in reading


def test_falls_back_to_key_name_without_rows():
    """拿不到 rows 时退回键名，是有损的（R&B 会变成 r b），但不能炸。"""
    facts = full_facts(**{
        "genre.album.contemporary_r_b.tracks": 50,
        "genre.album.contemporary_r_b.share": 0.95,
    })
    reading = next(t.reading for t in traits_from_facts(facts) if t.name == "头部流派")
    assert "contemporary r b" in reading


# ---------------------------------------------------------------
# 依据行
# ---------------------------------------------------------------

def test_basis_line_uses_the_shared_metric_renderer():
    """百分比渲染必须和报告正文同源（render.format_metric）。

    自己写一遍的话，同一个数字在标题下和正文里会长得不一样 ——
    而那种不一致没人会去比。
    """
    facts = full_facts()
    line = basis_line(traits_from_facts(facts, ROWS), facts)

    assert "头部流派 94.1%" in line      # share → 百分比
    assert "能量 0.43" in line           # 普通小数 → 两位
    assert "年代 2016" in line           # 整数原样
    assert "探索度 55.0%" in line        # 结尾是 _share 的也要走百分比


def test_basis_line_skips_keys_that_vanished():
    """素材是照着 facts 挑的，但渲染时 facts 可能已经不是那一份了
    （repair 一轮之后）。取不到就跳过，不能渲成 None。"""
    traits = traits_from_facts(full_facts(), ROWS)
    line = basis_line(traits, {"mood.arousal_mean": 0.4265})
    assert line == "能量 0.43"


def test_basis_line_is_deterministic():
    """同一份 facts 渲两次必须逐字一致 —— 报告里那行「依据」靠它。"""
    facts = full_facts()
    first = basis_line(traits_from_facts(facts, ROWS), facts)
    second = basis_line(traits_from_facts(facts, ROWS), facts)
    assert first == second


# ---------------------------------------------------------------
# 措辞的诚实性
# ---------------------------------------------------------------

def test_no_coverage_claim_without_the_count():
    """没有 mood.measured_tracks 时不能写「0 首是实测的」——
    那句话读起来像「一首实测都没有」，而真实情况是这条 fact 不在仓里。"""
    reading = next(t.reading for t in traits_from_facts({"mood.arousal_mean": 0.8})
                   if t.name == "能量")
    assert "0 首" not in reading
    assert "实测" not in reading


def test_coverage_claim_appears_when_the_count_is_there():
    reading = next(t.reading for t in traits_from_facts(full_facts(), ROWS)
                   if t.name == "能量")
    assert "418 首是 30 秒音频实测的" in reading


def test_arousal_band_is_anchored_not_invented():
    """档位词只在有客观参照时才给：arousal 是 normalize(x, low, high) 出来的，
    0.5 是**区间中点**，不是拍的阈值。"""
    def band(v):
        return next(t.reading for t in traits_from_facts({"mood.arousal_mean": v})
                    if t.name == "能量")

    assert "很静" in band(0.20)
    assert "偏静" in band(0.45)
    assert "偏热烈" in band(0.60)
    assert "很热烈" in band(0.90)
    assert "0.5 是区间中点" in band(0.60)
