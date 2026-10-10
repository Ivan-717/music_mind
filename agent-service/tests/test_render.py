"""数字引用渲染的测试。

这组测的是「LLM 编不出数字」这个结构性保证 —— 它一旦破了，
报告里就会出现看起来很像真的、实际是编的数。
"""

from __future__ import annotations

import pytest

from musicmind_agent.render import (
    RenderError,
    find_bare_numbers,
    format_metric,
    render_text,
    verify_metrics,
)

FACTS = {
    "scope.tracks": 448,
    "genre.album.mandopop.share": 0.6835,
    "genre.album.mandopop.lift": 2.3,
    "coverage.genre_ratio": 0.8951,
}


def test_percent_suffix_renders_as_percentage():
    """0.6835 写成「68.3%」才读得通，写成「0.68」没人看得懂。"""
    assert format_metric("genre.album.mandopop.share", 0.6835) == "68.3%"
    assert format_metric("coverage.genre_ratio", 0.8951) == "89.5%"


def test_lift_renders_as_multiple():
    assert format_metric("genre.album.mandopop.lift", 2.3) == "2.3 倍"


def test_count_renders_plain():
    assert format_metric("scope.tracks", 448) == "448"


def test_render_substitutes_placeholders():
    text = "你有 {genre.album.mandopop.share} 的歌是 mandopop，共 {scope.tracks} 首"
    assert render_text(text, FACTS) == "你有 68.3% 的歌是 mandopop，共 448 首"


def test_placeholder_with_chinese_key_renders():
    """【回归】事实名里会带中文 —— artist_affinity 用艺人名生成 key。

    第一版的正则是 `[a-zA-Z0-9_.]+`，匹配不上 CJK，于是
    `{artist.薛之谦.share}` 原样留在报告里。**而且它不报错** ——
    正则匹配不上就跳过，报告里只是多了一对花括号。
    更糟的是我的验收脚本当时用了同一个错正则，两边都看不见这个 bug。
    """
    facts = {"artist.薛之谦.share": 0.2344}
    assert render_text("薛之谦占 {artist.薛之谦.share}", facts) == "薛之谦占 23.4%"


def test_unknown_placeholder_raises():
    """引用不存在的事实必须当场炸。

    渲染成空字符串会得到「你有  的歌是 mandopop」——看起来只是排版问题，
    实际是模型编了一个事实名，或者用了一个本轮没跑过的工具的输出。
    这两种都必须让上层知道。
    """
    with pytest.raises(RenderError, match="不存在的事实"):
        render_text("你有 {genre.album.nonexistent.share} 的歌", FACTS)


def test_non_strict_mode_keeps_placeholder():
    """验证器想要「收集所有问题再一起报」时用非严格模式。"""
    out = render_text("有 {missing.key} 个", FACTS, strict=False)
    assert "{missing.key}" in out


def test_find_bare_numbers_ignores_chinese_key_placeholders():
    """裸数字扫描也要认得出带中文的占位符，否则会把占位符里的键名当成内容。"""
    assert find_bare_numbers("薛之谦占 {artist.薛之谦.share}") == []


def test_find_bare_numbers_ignores_placeholders():
    """走占位符的数字不算裸数字 —— 它们本来就是安全的。"""
    text = "你有 {scope.tracks} 首歌，其中 448 首有流派"
    assert find_bare_numbers(text) == ["448"]


def test_find_bare_numbers_catches_forgotten_ones():
    text = "68.3% 是 mandopop，覆盖 89.5%"
    assert find_bare_numbers(text) == ["68.3%", "89.5%"]


def test_verify_metrics_accepts_matching_values():
    refs = [{"key": "scope.tracks", "expect": 448}]
    assert verify_metrics(refs, FACTS) == []


def test_verify_metrics_catches_misread_value():
    """比「编数字」更隐蔽的一种错：引用了真实存在的事实名，但读错了值。"""
    refs = [{"key": "genre.album.mandopop.share", "expect": 0.37}]
    violations = verify_metrics(refs, FACTS)
    assert len(violations) == 1
    assert "0.37" in violations[0] and "0.6835" in violations[0]


def test_verify_metrics_catches_unknown_key():
    violations = verify_metrics([{"key": "made.up.key", "expect": 1}], FACTS)
    assert len(violations) == 1
    assert "不存在" in violations[0]


def test_verify_metrics_key_without_expect_is_allowed():
    """只引用不声明值 = 让渲染层填，不算违规。"""
    assert verify_metrics([{"key": "scope.tracks"}], FACTS) == []


def test_brace_wrapped_number_is_stripped():
    """【回归】模型会把「写占位符」理解成「把数字包进花括号」。

    实测：追问时它写出 `占 {68.3%}` —— 数字是对的（渲染前引用的是正确的键），
    但显示出来带花括号，用户会以为页面坏了。
    """
    assert render_text("占 {68.3%}", FACTS) == "占 68.3%"
    assert render_text("共 {95} 首", FACTS) == "共 95 首"
    assert render_text("占 { 0.683 }", FACTS) == "占 0.683"


def test_brace_wrapped_number_fix_does_not_hide_fake_keys():
    """兜底不能掩盖真问题：编造的事实名里有点号和字母，不该被当成数字放过。"""
    out = render_text("占 {form.album.share}", FACTS, strict=False)
    assert "{form.album.share}" in out


# ---------------------------------------------------------------
# _render 的字段覆盖（渲染层的静默洞）
# ---------------------------------------------------------------

DRAFT_MIN = {
    "headline": {"title": "{scope.tracks}", "subtitle": "{scope.tracks}", "used_facts": []},
    "opening": "{scope.tracks}",
    "dimensions": [{
        "dimension": "genre", "summary": "{scope.tracks}", "confidence": "high",
        "claims": [{"text": "{scope.tracks}", "basis": "data"}],
    }],
    "recommendations": [{
        "candidate_index": 1, "name": "歌名", "reason": "{scope.tracks}",
        "relation_to_history": {"anchors": [], "note": "{scope.tracks}"}, "rank": 1,
    }],
    "limitations": ["{scope.tracks}"],
}


def test_render_covers_every_llm_text_field():
    """【回归】report.py 的 _render 必须覆盖 walk_texts 列出的每一个 LLM 文本字段。

    这类洞栽过两次：先 limitations、后 opening（v1.2 加字段时渲染没跟上，
    models.py 当时的注释写着「渲染/校验收口见 P5/P6」，然后就忘了 ——
    2026-10-10 开场白里一个占位符原样漏出来才暴露）。
    """
    from musicmind_agent.models import ReportDraft
    from musicmind_agent.prompts.report import _render
    from musicmind_agent.validate.checks import walk_texts

    rendered = _render(ReportDraft.model_validate(DRAFT_MIN), {"scope.tracks": 448})

    leftovers = [path for path, text in walk_texts(rendered) if "{" in text]
    assert not leftovers, f"这些字段没被渲染：{leftovers}"


def test_graph_render_covers_every_field_and_converts_traditional():
    """【回归】graph/nodes.py 的姊妹 _render 同样要覆盖全部字段 + 转简。

    两处 _render 是两份实现，坑的位置每次不同：opening 漏在 report.py 那份，
    转简漏在 nodes 这份（2026-10-10 实测：生产路径正文还带「周杰倫」）。
    渲染出口已统一到 render.render_display —— 这个测试钉住两边都得走它。
    """
    from musicmind_agent.graph.nodes import _render
    from musicmind_agent.validate.checks import walk_texts

    draft = {k: v for k, v in DRAFT_MIN.items()}
    # 标题里带一个「LLM 会从库里照抄的繁体名」——转简断言才有对象可测
    draft["headline"] = {"title": "常听周杰倫，占了 {artist.周杰倫.share}",
                         "subtitle": "{scope.tracks}", "used_facts": []}
    rendered = _render(draft, {"scope.tracks": 448, "artist.周杰倫.share": 0.12})

    leftovers = [path for path, text in walk_texts(rendered) if "{" in text]
    assert not leftovers, f"这些字段没被渲染：{leftovers}"
    # 转简也在生产路径的字段上生效
    assert "周杰倫" not in rendered["headline"]["title"]
    assert "周杰伦" in rendered["headline"]["title"]
