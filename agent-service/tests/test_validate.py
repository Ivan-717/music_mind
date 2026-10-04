"""验证器的测试。用的全是 Phase 2 真实跑出来的失败样本。"""

from __future__ import annotations

import pytest

from musicmind_agent.validate import validate
from musicmind_agent.validate.normalize import (
    name_matches, numeric_forms, parse_cn_number,
)


# ---------- 归一化 ----------

@pytest.mark.parametrize("text,expected", [
    ("三", 3.0), ("十", 10.0), ("十二", 12.0), ("二十", 20.0),
    ("三成", 0.3), ("一半", 0.5), ("七成", 0.7),
])
def test_parse_cn_number(text, expected):
    assert parse_cn_number(text) == pytest.approx(expected)


def test_numeric_forms_covers_percent_and_decimal():
    """0.6835 在报告里可能写成 68.3%、68%、0.68 —— 都要能绑上。"""
    forms = numeric_forms(0.6835)
    assert "68.3%" in forms
    assert "0.68" in forms


def test_name_matches_across_scripts():
    """繁简。这个仓库已经栽过两次，别再栽第三次。"""
    assert name_matches("薛之谦", "薛之謙")
    assert name_matches("Jay Chou", "jay chou")


# ---------- L1 结构层：qwen 的真实失败样本 ----------

def test_fabricated_fact_key_is_caught(fake_ctx_double):
    """qwen 写了 mood.arousal_measured_median —— 这个键不存在。

    它把 arousal_measured_mean/min/max 和 arousal_median 两组名字拼在了一起。
    """
    report = {
        "headline": {"title": "t", "subtitle": ""},
        "dimensions": [{
            "dimension": "mood_energy",
            "summary": "",
            "claims": [{
                "text": f"中位数是 {{mood.arousal_measured_median}}",
                "metric_refs": [{"key": "mood.arousal_measured_median", "expect": None}],
                "evidence_track_ids": [],
                "basis": "data",
            }],
        }],
        "recommendations": [], "limitations": [],
    }
    result = validate(report, fake_ctx_double)
    assert not result.ok
    assert any(v.layer == "structure" and "arousal_measured_median" in v.detail
               for v in result.errors)


def test_claim_without_ref_or_evidence_is_warned(fake_ctx_double):
    """空口断言：既没引用事实也没证据。"""
    report = {
        "headline": {"title": "t", "subtitle": ""},
        "dimensions": [{
            "dimension": "genre", "summary": "",
            "claims": [{"text": "你很喜欢音乐", "metric_refs": [],
                        "evidence_track_ids": [], "basis": "data"}],
        }],
        "recommendations": [], "limitations": [],
    }
    result = validate(report, fake_ctx_double)
    assert any(v.layer == "structure" and v.severity == "warning" for v in result.warnings)


# ---------- L5 证据层：deepseek 第一版的真实失败样本 ----------

def test_evidence_from_candidate_pool_is_caught(fake_ctx_double):
    """第一版把推荐候选的 id 当成了用户的歌 —— 34 条证据全部越界。"""
    report = {
        "headline": {"title": "t", "subtitle": ""},
        "dimensions": [{
            "dimension": "genre", "summary": "",
            "claims": [{"text": "证据", "metric_refs": [],
                        "evidence_track_ids": [999999], "basis": "data"}],
        }],
        "recommendations": [], "limitations": [],
    }
    result = validate(report, fake_ctx_double, candidate_ids={999999})
    assert any(v.layer == "evidence" and "候选" in v.detail for v in result.errors)


# ---------- L4 实体层：两次误报的回归 ----------

def _report_with_text(text: str) -> dict:
    return {
        "headline": {"title": "t", "subtitle": ""},
        "dimensions": [{"dimension": "genre", "summary": "", "claims": [
            {"text": text, "metric_refs": [], "evidence_track_ids": [1]}]}],
        "recommendations": [], "limitations": [],
    }


def test_track_name_in_book_quotes_is_recognized(fake_ctx_double):
    """【回归】索引里必须包含歌名。

    第一版只收了艺人/专辑/流派，于是报告里「《十年》《浮夸》《稻香》」
    这些用户自己的歌全被判成「不在数据里」—— 一次性误报二十多条。
    带书名号的专名正是这一层主要要检查的对象。
    """
    result = validate(_report_with_text("你常听《歌1》"), fake_ctx_double)
    assert not [v for v in result.warnings if "歌1" in v.detail]


def test_partial_title_matches_full_title(fake_ctx_double):
    """【回归】变体集合必须【拍平】再比，否则子串匹配退化成集合成员判断。

    真实样本：候选歌名是「流行歌曲 (Popular Songs)」，报告写「《流行歌曲》」。
    写成 `[name_variants(n) for n in known]` 再 `for v in known_variants` 的话，
    v 是集合不是字符串，`q in v` 要求精确相等 —— 匹配不上，而且【不报错】，
    只是静默地多出一堆误报。

    这个坑在这个仓库里出现过三次（音频匹配、验证器、Java 侧各一次）。
    """
    # 「歌1」是 fake_ctx_double 里 track 1 的歌名，报告只写它的前缀
    result = validate(_report_with_text("推荐这首《歌》"), fake_ctx_double)
    # 「歌」是「歌1」的子串 —— 应该匹配上
    assert not [v for v in result.warnings if "《歌》" in v.detail]


def test_truly_unknown_name_still_warns(fake_ctx_double):
    """别把误报修过头 —— 真编的还是要报。"""
    result = validate(_report_with_text("你常听《这张专辑不存在》"), fake_ctx_double)
    assert any("这张专辑不存在" in v.detail for v in result.warnings)
