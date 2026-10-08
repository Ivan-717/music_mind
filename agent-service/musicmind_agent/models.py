"""报告的数据结构。

【数字只能以 metric_ref 的形式出现】LLM 不写数值、只写 `{fact.key}` 占位符，
渲染时替换。这样「编造一个数字」在结构上就写不出来。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MetricRef(BaseModel):
    """对一条事实的引用。expect 是 LLM 以为的值，验证器会拿它和实际值比。"""
    key: str
    expect: float | None = None


class Claim(BaseModel):
    text: str                                    # 叙事，数字写 {fact.key}
    metric_refs: list[MetricRef] = Field(default_factory=list)
    evidence_track_ids: list[int] = Field(default_factory=list)
    basis: Literal["data", "inference"] = "data"


class Dimension(BaseModel):
    dimension: Literal[
        "genre", "era", "artist", "mood_energy",
        "album_form", "duration", "diversity", "collaboration", "region",
    ]
    summary: str
    claims: list[Claim] = Field(default_factory=list)
    confidence: Literal["high", "medium", "low"] = "medium"


class RelationToHistory(BaseModel):
    """原则 4 的第三问：和用户过去喜欢的音乐有什么关系。"""
    anchors: list[int] = Field(default_factory=list)   # 必须是用户集里真实存在的 track_id
    note: str = ""


class Recommendation(BaseModel):
    """一条推荐。

    【模型给的是候选序号，不是 track_id】这一条是拿真实数据换来的：

    prompt 里本来会同时出现两列 track id —— 工具产出里的 `evidence`
    （用户听过的歌）和候选列表里的（没听过的）。模型分不清，
    实测反复把候选 id 当成用户的歌写进证据，**10 次跑里 10 次都因此触发了一轮 repair**
    （每轮约 10-13 秒 + tokens）。

    改成只给序号之后，候选的 track_id 根本不进 prompt，混都混不了。
    序号到 id 的映射在外面做（见 graph/nodes.py 的 _map_candidates）。

    最终落库的报告里仍然是 track_id —— 序号只是「模型和系统之间的接口」，不是数据。
    """

    candidate_index: int          # 1-based，对应 prompt 里候选列表的序号
    name: str = ""                # 候选行里的歌名，原样抄。
                                  # 【映射时按名字反查优先】实测模型会数错序号
                                  # （报告 30：20 条里前 8 条整体错开一行），
                                  # 但「抄歌名」这件事它可靠得多。见 nodes._map_candidates
    reason: str
    matched_dimensions: list[str] = Field(default_factory=list)   # 会被回查证实
    relation_to_history: RelationToHistory = Field(default_factory=RelationToHistory)
    rank: int = 0


class Headline(BaseModel):
    """报告的标题。**意象式命名**：不报数字，用一个画面写。

    例：title「夜行的猫」/ subtitle「耳机里循环着十年前的情歌，音量不大」。
    """

    title: str
    subtitle: str = ""

    # 【名字的依据】写这个意象时用了画像素材里的哪几条（填 fact key）。
    #
    # 它**不参与渲染** —— 报告里那行「依据」是代码从素材直接渲的，不走 LLM 的手。
    # 这个字段的作用是逼模型在动笔之前先想清楚「我这句话是打哪儿来的」，
    # 同时给验证器一个能查的抓手（L1 会核这些 key 是不是真在 facts 仓里）。
    used_facts: list[str] = Field(default_factory=list)


class ReportDraft(BaseModel):
    """LLM 直接产出的东西。渲染和验证在这之后做。"""
    headline: Headline
    opening: str = ""            # ← 新增：开场白（2-4 句），渲染/校验收口见 P5/P6
    dimensions: list[Dimension] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)