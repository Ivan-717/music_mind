"""LangGraph 工作流。"""

from __future__ import annotations

from musicmind_agent.graph.build import build_graph

__all__ = ["build_graph", "run_report"]


def run_report(connection, user_id: int, provider: str, out_dir: str | None = None,
               hidden_ids: set[int] | None = None,
               reco_count: int = 5) -> dict:
    """跑一次完整流程。CLI 和测试都走这个入口。

    【ctx 和 client 必须在这里建好、invoke 时传进去】
    实测：config 在节点之间是只读的（节点里改了，下一个节点看不见），
    所以不能在第一个节点里懒建。而 ctx 里有数据库连接，又不能进 state
    （checkpoint 要序列化）。两边一夹，唯一的位置就是 config。
    """
    from musicmind_agent.llm import LLMClient
    from musicmind_agent.tools import build_context

    # hidden_ids 是评估用的「藏歌」：把一部分歌从画像里摘掉，
    # 看推荐能不能把它们找回来。生产环境恒为 None。
    # 【藏歌仍然在候选池里】—— 它只是不进画像，不是从库里删掉。
    # 藏了又排除出候选，等于永远不可能命中，评估出来的 recall 恒为 0
    ctx = build_context(connection, user_id, hidden_ids)
    app = build_graph()
    client = LLMClient(provider=provider)

    final = app.invoke(
        {"user_id": user_id, "mode": "report"},
        config={"configurable": {
            "thread_id": f"report-{user_id}",
            "ctx": ctx,
            "client": client,
            "out_dir": out_dir,
            "reco_count": reco_count,
        }},
    )

    # 【事实仓和模型名要补进返回值】
    # 它们都不在图的状态里：facts 长在 ctx 上（ctx 不能进 state，有数据库连接），
    # provider/model 在 client 上（节点的 _add_usage 只累加了 token 数）。
    # 而下游都要用：落库要存 facts 快照（追问的上下文），
    # agent_report 要记是哪个模型生成的（换模型后能区分「质量变了」是谁的锅）
    final["facts"] = dict(ctx.facts)
    usage = final.setdefault("usage", {})
    usage.setdefault("provider", provider)
    usage.setdefault("model", client.config.get("model"))

    return final