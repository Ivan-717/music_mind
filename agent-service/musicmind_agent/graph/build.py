"""图装配。

把「有哪些节点」和「怎么连」放在一个文件里 —— 分散在各处的 add_edge
会让人看不出整个流程，而流程正是这一步唯一要看懂的东西。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from musicmind_agent.graph import nodes
from musicmind_agent.graph.state import AgentState

CHECKPOINT_PATH = Path(__file__).resolve().parents[2] / ".data" / "checkpoints.db"


def build_graph(checkpoint: bool = True):
    graph = StateGraph(AgentState)

    graph.add_node("resolve_user", nodes.resolve_user)
    graph.add_node("plan", nodes.plan)
    graph.add_node("run_core_tools", nodes.run_core_tools)
    graph.add_node("probe", nodes.probe)
    graph.add_node("compose", nodes.compose)
    graph.add_node("validate", nodes.validate_node)
    graph.add_node("repair", nodes.repair)
    graph.add_node("fallback_render", nodes.fallback_render)
    graph.add_node("persist", nodes.persist)

    graph.add_edge(START, "resolve_user")
    # 数据不足直接终止 —— 硬编一个人格出来比不生成糟得多
    graph.add_conditional_edges(
        "resolve_user",
        lambda s: "end" if s["usage"].get("insufficient") else "plan",
        {"end": END, "plan": "plan"},
    )
    graph.add_edge("plan", "run_core_tools")
    graph.add_edge("run_core_tools", "probe")

    # probe 自环 + 出口
    graph.add_conditional_edges(
        "probe", nodes.route_after_probe,
        {"probe": "probe", "compose": "compose"},
    )

    graph.add_edge("compose", "validate")
    graph.add_conditional_edges(
        "validate", nodes.route_after_validate,
        {"repair": "repair", "fallback": "fallback_render", "persist": "persist"},
    )
    graph.add_edge("repair", "validate")          # ← 回边
    graph.add_edge("fallback_render", "persist")
    graph.add_edge("persist", END)

    if not checkpoint:
        return graph.compile()

    # SqliteSaver 不用 with（实测不支持），连接自己管
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(CHECKPOINT_PATH, check_same_thread=False)
    return graph.compile(checkpointer=SqliteSaver(connection))