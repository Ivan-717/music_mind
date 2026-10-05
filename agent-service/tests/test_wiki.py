"""维基条目查找的测试。

【联网的两个用例单独标】它们是真去查维基，用来钉住两个实测失败过的名字；
其余全离线 —— 混在一起的话没人愿意跑测试。
"""

from __future__ import annotations

import pytest

from musicmind_agent.wiki import pick_best


def cand(title, pageid=1, size=1000):
    return {"title": title, "pageid": pageid, "size": size}


def test_exact_match_wins():
    """搜索自己把「无关的」排在前面时，档位要能把它压回去。

    实测：搜一个流派名，第一条可能是个音乐节。
    """
    best = pick_best("contemporary r&b", [
        cand("Contemporary R&B", 2),
        cand("节奏布鲁斯音乐节", 3),
    ])
    assert best["title"] == "Contemporary R&B"


def test_ignores_spaces_and_punctuation_case():
    """「contemporary r&b」和「Contemporary R&B」是同一个东西。"""
    assert pick_best("contemporary r&b", [cand("Contemporary R&B")]) is not None


def test_traditional_simplified_both_ways():
    best = pick_best("林俊杰", [cand("林俊傑")])
    assert best is not None, "繁简没归一的话这个歌手永远找不到"


def test_partial_name_still_matches():
    """查询词里带着前缀时也要能找到 —— 「G.E.M. 鄧紫棋」对「鄧紫棋」。

    这是实测失败过的那个：`titles=` 精确取查不到她，而她的页就在那儿。
    """
    assert pick_best("G.E.M. 鄧紫棋", [cand("鄧紫棋")]) is not None


def test_unrelated_results_are_rejected():
    """**宁可返回空，也不要一个不像的。** 返回错条目的代价是往向量库里
    灌一篇讲别的东西的文章，而检索时它会以很高的相似度被捞出来。"""
    assert pick_best("薛之谦", [cand("香港"), cand("1997年")]) is None


def test_empty_candidates():
    assert pick_best("薛之谦", []) is None


@pytest.mark.network
def test_follows_cross_script_redirect():
    """维基的重定向能吃掉跨文字的别名，而 search + 按名字筛会把它拒掉。

    米津玄師 在英文维基上叫「Kenshi Yonezu」—— 名字完全不像，
    但重定向是维基自己给的断言，比我们猜得准。而那个条目正是语料更厚的那个
    （实测中文 3862 字 vs 英文 14241 字）。
    """
    from musicmind_agent.wiki import find_pages
    pages = find_pages("米津玄師")
    langs = {p.lang for p in pages}
    assert langs == {"zh", "en"}, f"英文那条应该靠重定向拿到，实际只有 {langs}"
    assert len(next(p for p in pages if p.lang == "en").text) > 5000


@pytest.mark.network
@pytest.mark.parametrize("name", ["G.E.M. 鄧紫棋", "contemporary r&b", "林俊杰"])
def test_real_lookups(name):
    """真去查维基。钉住三个实测失败过的名字（前两个是名字匹配，
    第三个是繁简漏字）。跑法：pytest -m network"""
    from musicmind_agent.wiki import find_pages
    pages = find_pages(name)
    assert pages, f"{name} 一页都没找到"
    assert max(len(p.text) for p in pages) > 500