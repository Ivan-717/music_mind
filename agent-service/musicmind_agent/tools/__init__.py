"""工具注册表与上下文构造。

工具分三层，**层数不是分类学，是给「谁来决定调用」划边界**：

    Tier 0 核心（6 个）  每次报告无条件跑。证据的地基，不让 LLM 决定
    Tier 1 探针（7 个）  LLM 从白名单里挑，额度 6 次。这是 Agent 的自由度所在
    Tier 2 支撑（2 个）  图内部用，追问时 LLM 也可用

把 Tier 0 排除在 LLM 决策之外是有意的：核心维度固定，两次运行才可比，
评估才有基座。Agent 的自由度保留在「额外查什么」和叙事上。
"""

from __future__ import annotations

from typing import Any

from musicmind_agent.evidence import (
    SCOPE_ALL,
    EvidenceSet,
    load_enriched,
    resolve_all_known,
    resolve_user,
)
from musicmind_agent.tools.base import (  # noqa: F401
    REGISTRY,
    ToolContext,
    ToolResult,
    call,
    catalog,
    core_tool_names,
)

# 导入即注册。工具函数靠 @register 装饰器把自己挂进 REGISTRY
from musicmind_agent.tools import explore, library, profile  # noqa: F401,E402

CONFIDENCE_WEIGHT = {"high": 1.0, "medium": 0.6, "low": 0.2}


def load_mood_map(connection) -> dict[str, dict[str, Any]]:
    """流派 → 情绪。119 行，一次全读进内存。"""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT g.name, gm.arousal, gm.valence, gm.confidence, gm.note
            FROM genre_mood gm JOIN genre g ON g.id = gm.genre_id
            """
        )
        return {
            row["name"]: {
                "arousal": float(row["arousal"]),
                "valence": float(row["valence"]),
                "confidence": row["confidence"],
                "note": row["note"],
                "weight": CONFIDENCE_WEIGHT.get(row["confidence"], 0.2),
            }
            for row in cursor.fetchall()
        }


def load_library_genre_counts(connection) -> dict[str, int]:
    """全库流派分布（专辑级）。taste_diversity 用它算「用户偏离全库有多远」。"""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT g.name, COUNT(*) n
            FROM album_genre ag JOIN genre g ON g.id = ag.genre_id
            GROUP BY g.id
            """
        )
        return {row["name"]: row["n"] for row in cursor.fetchall()}


def build_context(
    connection,
    user_id: int,
    hidden_ids: set[int] | None = None,
    scope_kind: str = SCOPE_ALL,
    scope_ref: int | None = None,
) -> ToolContext:
    """把一个用户的数据取全。评估时传 hidden_ids 藏歌 ——
    藏一次，所有工具天然看不到，不用改任何工具。

    scope_kind / scope_ref 决定**画像**看哪一批曲目（见 evidence.resolve_user）。
    但 all_known_* 永远是整个曲库 —— 候选排除和探索判定不能跟着范围缩小，
    理由见 evidence.resolve_all_known。
    """
    evidence: EvidenceSet = resolve_user(connection, user_id, hidden_ids,
                                         scope_kind, scope_ref)
    known_ids, known_artists = resolve_all_known(connection, user_id, hidden_ids)
    return ToolContext(
        connection=connection,
        evidence=evidence,
        tracks=load_enriched(connection, evidence.all_ids),
        mood_map=load_mood_map(connection),
        library_genre_counts=load_library_genre_counts(connection),
        all_known_track_ids=known_ids,
        all_known_artist_ids=known_artists,
    )


__all__ = [
    "REGISTRY", "ToolContext", "ToolResult", "build_context",
    "call", "catalog", "core_tool_names",
]
