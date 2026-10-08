"""图结构与路由的测试。

【只测确定性部分】节点的 LLM 行为要花真钱、有随机性，
那是 evals/run_eval.py 的事，不放进单测 —— 混进来的后果是没人愿意跑测试。
"""

from __future__ import annotations

import json

import pytest

from musicmind_agent.graph import nodes
from musicmind_agent.graph.build import build_graph
from musicmind_agent.graph.state import MAX_BARREN_PROBES, MAX_PROBES, MAX_REPAIRS


def test_graph_compiles_without_checkpointer():
    assert build_graph(checkpoint=False) is not None


def test_all_nodes_registered():
    """节点名拼错不会在编译时报错，只会在运行时 KeyError。"""
    app = build_graph(checkpoint=False)
    expected = {"resolve_user", "plan", "run_core_tools", "probe", "compose",
                "validate", "repair", "fallback_render", "persist"}
    assert expected <= set(app.get_graph().nodes)


# ---------- 路由（纯函数，最好测的一层） ----------

def test_route_stops_when_model_says_done():
    """【这是修掉的那个真 bug】模型说 done 时，即使计划里还有没跑的探针也要停。

    之前节点的 early-return 也在判断去留，路由又在判次数 ——
    两处逻辑漂移的后果是：模型说「够了」，路由看到计划里还有 pending，
    又把它送回去，最多白烧 6 轮 LLM 调用。
    """
    state = {"model_done": True, "probe_count": 0, "probe_barren": 0,
             "plan": {"probes": ["artist_deep_dive", "collaboration_network"]}}
    assert nodes.route_after_probe(state) == "compose"


@pytest.mark.parametrize("barren,expected", [
    (0, "probe"), (MAX_BARREN_PROBES - 1, "probe"), (MAX_BARREN_PROBES, "compose"),
])
def test_route_stops_after_consecutive_barren_probes(barren, expected):
    """主出口看的是「连续几次没新增事实」，不是「跑了几次」。

    跑了但没新信息才是该停的信号 —— 一个探针在这个用户身上返回空，
    跑第二次还是空，第三次大概率还是空。
    """
    state = {"model_done": False, "probe_barren": barren,
             "probe_count": 1, "probe_tokens": 0}
    assert nodes.route_after_probe(state) == expected


@pytest.mark.parametrize("probe_count,expected", [
    (MAX_PROBES - 1, "probe"), (MAX_PROBES, "compose"),
])
def test_hard_cap_still_backstops(probe_count, expected):
    """硬上限不能去掉：模型交替产出「有收获 / 没收获」时，
    连续 barren 永远不会到 2，没有硬顶就会跑飞。"""
    state = {"model_done": False, "probe_barren": 0,
             "probe_count": probe_count, "probe_tokens": 0}
    assert nodes.route_after_probe(state) == expected


def test_token_budget_still_backstops():
    state = {"model_done": False, "probe_barren": 0,
             "probe_count": 1, "probe_tokens": 999999}
    assert nodes.route_after_probe(state) == "compose"


@pytest.mark.parametrize("repair_count,expected", [
    (0, "repair"), (MAX_REPAIRS - 1, "repair"), (MAX_REPAIRS, "fallback"),
])
def test_route_after_validate_gives_up_eventually(repair_count, expected):
    state = {"violations": [{"severity": "error", "path": "x", "detail": "y"}],
             "repair_count": repair_count}
    assert nodes.route_after_validate(state) == expected


def test_route_after_validate_passes_when_only_warnings():
    """警告不阻断落库 —— 否则每条「数字绑不上」都要白重写一轮。"""
    state = {"violations": [{"severity": "warning", "path": "x", "detail": "y"}],
             "repair_count": 0}
    assert nodes.route_after_validate(state) == "persist"


# ---------- 故障注入：降级路径真的能跑通 ----------

def test_fallback_render_drops_flagged_claims():
    """降级渲染要丢掉没通过验证的 claim，保留其余的。"""
    draft = {
        "headline": {"title": "t", "subtitle": "s"},
        "dimensions": [{
            "dimension": "genre", "summary": "x",
            "claims": [
                {"text": "好的", "metric_refs": [], "evidence_track_ids": [1], "basis": "data"},
                {"text": "坏的", "metric_refs": [], "evidence_track_ids": [], "basis": "data"},
            ],
        }],
        "recommendations": [{"track_id": 1, "reason": "r", "matched_dimensions": [],
                             "relation_to_history": {"anchors": [], "note": ""}, "rank": 1}],
        "limitations": ["原有的局限"],
    }
    class FakeCtx:
        # fallback_render 也要走 _render，所以得有 facts
        facts: dict = {}
    config = {"configurable": {"ctx": FakeCtx()}}
    out = nodes.fallback_render(
        {"draft": draft, "violations": [
            {"severity": "error", "path": "dimensions[0].claims[1]", "detail": "空口断言"}],
         "trace": []}, config)

    dims = out["rendered"]["dimensions"]
    assert len(dims[0]["claims"]) == 1
    assert dims[0]["claims"][0]["text"] == "好的"
    # 推荐项整块丢掉（含 LLM 写的解释）
    assert out["rendered"]["recommendations"] == []
    assert out["degraded"] is True
    assert any("降级" in x for x in out["rendered"]["limitations"])

# ---------- 两个真 bug 的回归 ----------
# 这两个都是「不抛异常、只是结果偏了」的那类，靠读代码看不出来。

def test_fallback_render_still_renders_placeholders(fake_ctx_double):
    """【回归】降级路径也必须走渲染。

    第一版从 draft 拼完降级报告就返回了，而 draft 里的数字还是 {fact.key} ——
    结果「降级后的报告」里有 47 处没替换的花括号。
    降级的意义是退回一个绝对正确的版本，结果退回去的更烂。
    """
    draft = {
        "headline": {"title": "t", "subtitle": ""},
        "dimensions": [{
            "dimension": "genre", "summary": "共 {scope.tracks} 首",
            "claims": [{"text": "有 {scope.tracks} 首",
                        "metric_refs": [], "evidence_track_ids": [1], "basis": "data"}],
        }],
        "recommendations": [],
        "limitations": ["覆盖 {coverage.genre_ratio}"],
    }
    out = nodes.fallback_render({"draft": draft, "violations": [], "trace": []},
                                {"configurable": {"ctx": fake_ctx_double}})

    rendered = out["rendered"]

    # 【只看文本字段】不能扫 json.dumps 的结果 —— JSON 自己的花括号会被当成占位符
    def texts(node):
        if isinstance(node, str):
            yield node
        elif isinstance(node, dict):
            for v in node.values():
                yield from texts(v)
        elif isinstance(node, list):
            for v in node:
                yield from texts(v)

    leftovers = [t for t in texts(rendered) if "{" in t or "}" in t]
    assert not leftovers, f"降级报告里还有没渲染的占位符：{leftovers}"
    assert "3" in rendered["dimensions"][0]["claims"][0]["text"]     # scope.tracks = 3
    assert "100.0%" in rendered["limitations"][0]                    # coverage.genre_ratio


def test_build_messages_includes_tool_results(fake_ctx_double):
    """【回归】compose 必须把工具产出传给模型。

    为了给 Phase 4 复用而抽 build_messages 时，我把 tool_results 做成了可选参数，
    图里就没传 —— 模型只看得见推荐候选那一列 track id，就把它们当成了用户的歌。
    实测：64 条违规里大半是「证据曲目 X 不是用户的歌」，推荐列表为空。

    核心工具的 evidence 是模型判断「哪些 id 能用」的**唯一**依据，
    缺了它必然出错，而且错得很有迷惑性（报告看起来结构完整）。
    """
    from musicmind_agent.prompts.report import build_messages

    class FakeResult:
        """假装一个 ToolResult 的 as_dict() 结果。"""
    tool_results = {"user_evidence_overview": {
        "tool": "user_evidence_overview", "args": {}, "facts": {"scope.tracks": 3},
        "rows": [], "coverage": {"considered": 3, "with_attribute": 3, "ratio": 1.0},
        "evidence": [{"track_id": 1, "name": "歌1", "artist": "艺人1", "why": "x"}],
        "warnings": [], "elapsed_ms": 1,
    }}

    content = build_messages(fake_ctx_double, None, tool_results)[1]["content"]
    assert "evidence" in content
    assert "用户自己听过的曲目" in content


def test_run_core_tools_stores_results_in_state(fake_ctx_double):
    """工具产出要进 state，否则 compose / repair 拿不到（上一个 bug 的根因）。"""
    out = nodes.run_core_tools({}, {"configurable": {"ctx": fake_ctx_double}})
    assert out["tool_results"], "tool_results 没进 state"
    assert all(isinstance(v, dict) for v in out["tool_results"].values()), \
        "state 要过 checkpoint 序列化，只能存 dict 不能存 ToolResult"


def test_fallback_render_also_clears_bad_summaries(fake_ctx_double):
    """【回归】降级时，违规的维度 summary 也要清掉，不能只丢 claim。

    实测残留：「合唱网络只覆盖 {collab.tracks_with_multiple_artists} 首」——
    它引用的探针那一轮根本没跑，键不存在，渲染不出来。
    而它不在 claim 里，所以躲过了只盯 claim 的丢弃逻辑。
    """
    draft = {
        "headline": {"title": "t", "subtitle": ""},
        "dimensions": [
            {"dimension": "genre", "summary": "好的总结",
             "claims": [{"text": "x", "metric_refs": [], "evidence_track_ids": [1],
                         "basis": "data"}]},
            {"dimension": "collaboration", "summary": "覆盖 {collab.never_ran} 首",
             "claims": []},
        ],
        "recommendations": [], "limitations": [],
    }
    out = nodes.fallback_render(
        {"draft": draft,
         "violations": [{"severity": "error", "path": "dimensions[1].summary",
                         "detail": "引用了不存在的事实"}],
         "trace": []},
        {"configurable": {"ctx": fake_ctx_double}})

    dims = out["rendered"]["dimensions"]
    assert dims[0]["summary"] == "好的总结"          # 没违规的保持原样
    assert "{" not in dims[1]["summary"]            # 违规的被换掉
    assert "已丢弃" in dims[1]["summary"]


def test_map_candidates_drops_out_of_range_indices():
    """【防静默丢失】越界的候选序号要丢掉，不能猜。

    猜错了推荐的是另一首歌，而且没人会发现。
    但反过来说 —— 如果**全部**越界，推荐列表会变成空的，
    而那种失败看起来和「推荐得不准」一模一样（都是 0 命中）。
    """
    from musicmind_agent.graph.nodes import _map_candidates

    ids = [{"track_id": 100, "歌名": "甲", "艺人": "A"},
           {"track_id": 200, "歌名": "乙", "艺人": "B"},
           {"track_id": 300, "歌名": "丙", "艺人": "C"}]
    draft = {"recommendations": [
        {"candidate_index": 1, "reason": "a"},
        {"candidate_index": 3, "reason": "b"},
        {"candidate_index": 99, "reason": "越界"},      # 丢
        {"candidate_index": 0, "reason": "从 0 开始是错的"},  # 丢
        {"candidate_index": None, "reason": "没给"},     # 丢
    ]}
    out = _map_candidates(draft, ids)
    assert [r["track_id"] for r in out["recommendations"]] == [100, 300]
    # 【名字必须带上】只给 id 的话前端只能显示 #16033，用户不知道推的是哪首歌
    assert out["recommendations"][0]["name"] == "甲"
    assert out["recommendations"][0]["artist_names"] == "A"


def test_map_candidates_all_invalid_yields_empty():
    """全部越界时结果为空 —— 这条用来说明「0 命中」有两种可能：
    推荐得不准，或者一条都没映射上。评估里要能区分，见 run_eval 的返回条数列。"""
    from musicmind_agent.graph.nodes import _map_candidates
    draft = {"recommendations": [{"candidate_index": 999, "reason": "x"}]}
    assert _map_candidates(draft, [{"track_id": 1}, {"track_id": 2}])["recommendations"] == []


def test_map_candidates_name_wins_over_wrong_index():
    """实测的错位（报告 30）：序号数错一行、名字抄对了 —— 必须按名字找回来。

    模型「数第几行」不可靠（0-based、错一行都发生过），
    但「抄一行里的歌名」可靠得多。名字优先、序号兜底：都指不到才丢。
    """
    from musicmind_agent.graph.nodes import _map_candidates

    rows = [{"track_id": 100, "歌名": "甲", "艺人": "A"},
            {"track_id": 200, "歌名": "乙", "艺人": "B"},
            {"track_id": 300, "歌名": "丙", "艺人": "C"}]

    # 想推「丙」（第 3 行），但序号按 0-based 写成 2 —— 名字抄对了
    out = _map_candidates(
        {"recommendations": [{"candidate_index": 2, "name": "丙", "reason": "x"}]}, rows)
    assert out["recommendations"][0]["track_id"] == 300      # 信名字，不信序号
    assert out["recommendations"][0]["name"] == "丙"          # 落库的是规范写法

    # 简繁/空格归一：抄成「 丙 」也认
    out = _map_candidates(
        {"recommendations": [{"candidate_index": 1, "name": " 丙 ", "reason": "x"}]}, rows)
    assert out["recommendations"][0]["track_id"] == 300

    # 名字匹配不上、序号有效 → 回到序号（名字可能只是抄错了，序号还算数）
    out = _map_candidates(
        {"recommendations": [{"candidate_index": 2, "name": "查无此歌", "reason": "x"}]}, rows)
    assert out["recommendations"][0]["track_id"] == 200

    # 名字乱写 + 序号越界 → 丢，不猜
    out = _map_candidates(
        {"recommendations": [{"candidate_index": 99, "name": "查无此歌", "reason": "x"}]}, rows)
    assert out["recommendations"] == []


# ---------- 起点必须清干净上一次的残留 ----------

def _ctx_with(n_tracks: int):
    from musicmind_agent.evidence import EnrichedTrack, EvidenceSet
    from musicmind_agent.tools.base import ToolContext

    def track(i):
        return EnrichedTrack(
            track_id=i, track_name=f"t{i}", duration_ms=240_000,
            artist_id=100 + i, artist_name=f"a{i}", country_code="CN",
            album_id=200 + i, album_name=f"al{i}", release_date="2016-01-01",
            primary_type="Album", album_genres=("pop",), artist_genres=(),
            arousal_measured=None, artist_verified=True,
        )

    tracks = [track(i) for i in range(1, n_tracks + 1)]
    return ToolContext(
        connection=None,
        evidence=EvidenceSet(user_id=34, favorite_ids=[],
                             playlist_ids=[t.track_id for t in tracks]),
        tracks=tracks, mood_map={}, library_genre_counts={},
    )


def test_resolve_user_wipes_the_previous_run():
    """**同一个人第二次生成会落在同一个 checkpoint 上。**

    thread_id 是 `report-{user_id}`，LangGraph 会把上一次的 state 合并进来。
    resolve_user 是一次运行的起点，不清的话：

      · tool_results 累积 —— 模型在 prompt 里看得见历史上所有探针的输出，
        而它们的 fact 不在本轮 ctx.facts 里，照着写就是渲染不出来的占位符
        （L1 会抓，但白跑一轮 repair）。**这是修轮次偏高的一个真实原因**
      · trace 累积 —— 实测跑 99 次之后，一份报告的 trace 有 834 步，
        checkpoint 库涨到 152MB

    第一次发现是因为 trace 里 `validate→repair→persist` 出现在了
    `resolve_user` **之前** —— 那个顺序在图上不可能出现。
    """
    stale = {
        "user_id": 34,
        "tool_results": {"旧的探针": {"facts": {"old.key": 1}}},
        "draft": {"headline": {"title": "上一份报告"}},
        "rendered": {"headline": {"title": "上一份报告"}},
        "violations": [{"layer": "structure", "path": "x", "detail": "y"}],
        "plan": {"probes": ["tracks"]},
        "probes": [{"tool": "tracks"}],
        "probe_count": 3, "probe_tokens": 9999, "probe_barren": 2,
        "model_done": True, "repair_count": 2, "degraded": True,
        "usage": {"tokens_in": 99999},
        "trace": [{"node": "validate"}, {"node": "repair"}, {"node": "persist"}],
    }

    out = nodes.resolve_user(stale, {"configurable": {"ctx": _ctx_with(25)}})

    assert out["tool_results"] == {}, "上一轮的探针结果会污染 prompt"
    assert out["draft"] == {}
    assert out["rendered"] == {}
    assert out["violations"] == []
    assert out["plan"] == {} and out["probes"] == []
    assert out["probe_count"] == 0 and out["model_done"] is False
    assert out["repair_count"] == 0 and out["degraded"] is False

    # trace 从这一次的第一条重新开始，不是接在旧的后面
    assert len(out["trace"]) == 1
    assert out["trace"][0]["node"] == "resolve_user"
