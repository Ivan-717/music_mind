"""工具契约的测试。

这一组测的不是「某个工具算得对不对」，而是「所有工具都守规矩」——
契约一旦破了，最直接的后果是报告里的数字无法被验证器核对，
而那种失败是静默的：报告看起来一切正常。

全部离线：不连数据库、不调 LLM。默认 pytest 必须秒级全绿。
"""

from __future__ import annotations

import pytest

from musicmind_agent.tools.base import (
    MAX_EVIDENCE_TOTAL,
    ToolContext,
    cap_evidence,
    cov,
)


# ---------------------------------------------------------------
# 覆盖率
# ---------------------------------------------------------------

def test_cov_computes_ratio():
    result = cov(considered=490, with_attribute=413)
    assert result["considered"] == 490
    assert result["with_attribute"] == 413
    assert result["ratio"] == pytest.approx(0.843, abs=1e-3)


def test_cov_with_zero_considered_does_not_divide_by_zero():
    """没有曲目时不能炸 —— 新用户走的就是这条路。"""
    result = cov(considered=0, with_attribute=0)
    assert result["ratio"] == 0.0


# ---------------------------------------------------------------
# facts 契约
# ---------------------------------------------------------------

def test_fact_key_must_be_dotted():
    """扁平的 dotted key 是验证器回查的索引，不是风格偏好。
    允许裸名字的话，两个域可能撞名而没人发现。"""
    ctx = ToolContext(connection=None, evidence=None, tracks=[])
    with pytest.raises(ValueError, match="dotted"):
        ctx.fact("tracks", 1)


def test_fact_key_conflict_is_loud():
    """同一个 key 被写成两个不同的值 = 报告引用到不确定的数字。
    宁可当场炸，也不要让报告里出现一个来源不明的数。"""
    ctx = ToolContext(connection=None, evidence=None, tracks=[])
    ctx.fact("genre.pop.share", 0.3)
    ctx.fact("genre.pop.share", 0.3)          # 同值重复写没事
    with pytest.raises(ValueError, match="冲突"):
        ctx.fact("genre.pop.share", 0.7)


# ---------------------------------------------------------------
# 证据预算
# ---------------------------------------------------------------

def test_evidence_is_capped():
    """证据是「能指回具体歌」，不是把歌单倒给 LLM。"""
    items = [{"track_id": i} for i in range(100)]
    assert len(cap_evidence(items)) == MAX_EVIDENCE_TOTAL


# ---------------------------------------------------------------
# 注册表：所有工具都必须守契约
# ---------------------------------------------------------------

def test_registry_is_populated():
    from musicmind_agent.tools import REGISTRY
    assert len(REGISTRY) >= 15


def test_every_tool_has_a_description():
    """没描述的工具有等于没有 —— LLM 从白名单里挑的时候看不到它。"""
    from musicmind_agent.tools import REGISTRY
    for name, tool in REGISTRY.items():
        assert tool.description.strip(), f"{name} 没有描述"
        assert tool.tier in (0, 1, 2), f"{name} 的 tier 不合法：{tool.tier}"


def test_core_tools_are_exactly_six():
    """核心工具的数量是个设计决定，不是巧合。

    它们每次报告都无条件跑，是「两次运行可比」的基础。
    增减这个集合等于改变报告的结构，应该是刻意的行为。
    """
    from musicmind_agent.tools import REGISTRY
    core = [n for n, t in REGISTRY.items() if t.tier == 0]
    assert len(core) == 6, f"核心工具应是 6 个，实际 {len(core)}：{core}"
    assert "mood_energy_profile" in core, "情绪/能量是核心维度，不能被降级成探针"


def test_tier1_catalog_excludes_core_tools():
    """给 LLM 看的目录里只能有探针。

    混进核心工具就等于把「查不查基础维度」交给模型决定 ——
    而某个模型漏调一次，报告会静悄悄缺一块，没有任何东西会报警。
    """
    from musicmind_agent.tools import catalog
    names = {entry["name"] for entry in catalog(tier=1)}
    assert "genre_distribution" not in names
    assert "mood_energy_profile" not in names
    assert "similar_tracks" in names
