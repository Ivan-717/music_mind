"""名称匹配的测试 —— 繁简、空格、同名异人。

【为什么这组测试必须存在】这个匹配层我第一次写的时候忘了套繁简，
后果是把《止戰之殤》《海阔天空》这类歌判成「iTunes 上没有这首」，
而 393 首里只有 177 首能核对上艺人（45%）。修完之后是 94%。

**而且这是同一个坑第二次绊我** —— 项目早就有「数据存原样、比对时扩繁简变体」
的政策（实体对齐、选 release 都套了），我在新写的匹配层漏了。
所以这些用例是回归测试，不是覆盖率装饰。
"""

from __future__ import annotations

from musicmind_agent.audio.itunes import contains_name, name_variants, normalize_name


def test_variants_cover_both_scripts():
    """一个中文名的变体集合里，简繁两种写法都要在。"""
    variants = name_variants("薛之谦")
    assert "薛之谦" in variants
    assert "薛之謙" in variants


def test_variants_of_traditional_input_too():
    """反向也要成立 —— 库里存的是繁体的艺人（周杰倫）同样要能匹配。"""
    variants = name_variants("周杰倫")
    assert "周杰倫" in variants
    assert "周杰伦" in variants


def test_contains_name_matches_across_scripts():
    """这就是那个 bug 的回归用例：库里的简体 vs iTunes 的繁体。"""
    assert contains_name("薛之謙", [name_variants("薛之谦")])
    assert contains_name("鳳毛麟角", [name_variants("凤毛麟角")])


def test_contains_name_rejects_different_artist():
    """同名异人必须拒绝 —— 这是艺人核对存在的意义。

    实测案例：薛之谦《肆無忌憚》在 iTunes 上只有陈凯彤的同名歌，
    如果不做艺人核对就会把陈凯彤那首算成薛之谦的音频特征。
    """
    assert not contains_name("陳凱彤", [name_variants("薛之谦")])


def test_contains_name_handles_suffix():
    """iTunes 常在标题后加后缀（「素顏 (with 何曼婷)」）。

    这里曾经写错过：用集合成员判断而不是子串匹配，
    `"素颜" in {"素顏", "素顏(with何曼婷)"}` 是 False，把正常的标题全滤掉了。
    """
    assert contains_name("素顏 (with 何曼婷)", [name_variants("素颜")])


def test_normalize_ignores_space_and_case():
    assert normalize_name("G.E.M. 鄧紫棋") == normalize_name("g.e.m.鄧紫棋")
    assert normalize_name(None) == ""


def test_multiple_needles_any_match():
    """别名列表里任意一个命中即可。"""
    needles = [name_variants("周杰倫"), name_variants("Jay Chou")]
    assert contains_name("Jay Chou", needles)
    assert contains_name("周杰倫", needles)
    assert not contains_name("陈奕迅", needles)
