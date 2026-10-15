"""MusicMind 的 MCP Server —— 把工具层暴露给 Claude Desktop 等 MCP 客户端。

跑法：python -m musicmind_agent.mcp_server --user 34

【为什么是单用户】ToolContext 的构造强制要 user_id（tools/__init__.py），
agent-service 的定位就是「一个人的电台」——MCP server 用 --user 固定身份，
不做多用户鉴权。

【stdout 是协议通道】mcp.run() 走 stdio transport —— stdout 上的每一个字节
都是 JSON-RPC 消息。这个文件里（以及它调用的任何代码路径里）任何 print()
都会破坏协议；调试日志只能走 stderr。
"""

from __future__ import annotations

import argparse
import sys

from mcp.server.mcpserver import MCPServer

# 【v2 的改名】2026-07 转正后 FastMCP → MCPServer（mcp>=2）。
# decorator（@mcp.tool()）和 run() 的用法没变；装到 1.x 的话这里换回
# `from mcp.server.fastmcp import FastMCP` 即可。
mcp = MCPServer("musicmind")

# main() 里赋值。单用户进程，模块级够用
_USER_ID = 0


def _render(result) -> str:
    """ToolResult → 给客户端模型读的 Markdown 文本。

    warnings 置顶（「Ollama 没开」这类状态要让人先看到，不能埋在最后）；
    facts 一行一条；rows 取前 10 行做表格（客户端的上下文也宝贵）。
    """
    parts: list[str] = []
    if result.warnings:
        parts.append("> ⚠ " + "；".join(result.warnings))
    if result.facts:
        parts.append("\n".join(f"- {k}: {v}" for k, v in result.facts.items()))
    if result.rows:
        # 【按行形状分组渲染多个表】工具的 rows 不保证同构 —— 实测
        # library_stats 先给「曲目统计」一行、再给「流派分布」一批，
        # 只按第一行的列头渲染的话，后面的行全是空表格行（| | | |）。
        groups: dict[tuple, list] = {}
        for r in result.rows:
            groups.setdefault(tuple(r.keys()), []).append(r)
        for shape, group_rows in groups.items():
            show = group_rows[:10]
            cols = list(shape)
            parts.append("| " + " | ".join(cols) + " |")
            parts.append("|" + "---|" * len(cols))
            for row in show:
                parts.append("| " + " | ".join(str(row.get(c, "")) for c in cols) + " |")
            if len(group_rows) > 10:
                parts.append(f"（这组共 {len(group_rows)} 行，显示前 10）")
    if not parts:
        parts.append("（没有结果）")
    return "\n\n".join(parts)


def _run(name: str, args: dict) -> str:
    """跑一个工具并渲染。**每次调用新建 ctx** —— call() 会把工具产出的 facts
    写进 ctx.facts（base.py 的 fact()），复用 ctx 会让两次调用互相撞 key。
    现有所有调用方（chat / graph）都是每次新建，照做。

    call() 自己永不抛（异常转 warnings），这里再兜一层连库失败 —— MCP
    工具的面貌必须是「返回一段能读的文本」，不是把异常摔给客户端。
    """
    from musicmind_agent.db import get_connection
    from musicmind_agent.tools import build_context, call

    try:
        connection = get_connection()
    except Exception as e:
        return f"工具执行失败：连不上数据库（{type(e).__name__}: {e}）"
    try:
        ctx = build_context(connection, _USER_ID)
        result = call(name, ctx, args)
        return _render(result)
    except Exception as e:
        return f"工具执行失败：{type(e).__name__}: {e}"
    finally:
        connection.close()


# ============================================================
# 暴露给 MCP 客户端的工具
# 函数签名 = 参数 schema（SDK 自动生成）；docstring = 工具描述。
# 参数与现有工具逐个对齐（python -m musicmind_agent.cli catalog 可核对）。
# ============================================================

@mcp.tool()
def search_knowledge(query: str, kind: str | None = None,
                     lang: str | None = None) -> str:
    """查音乐知识语料（维基条目）：流派是什么、艺人的背景、运动的来龙去脉。
    回答「为什么/是什么」类问题用它。kind 可选 artist / genre；lang 可选 zh / en。"""
    return _run("search_knowledge",
                {"query": query, "kind": kind, "lang": lang})


@mcp.tool()
def search_tracks(genre: str | None = None, year_from: int | None = None,
                  year_to: int | None = None, primary_type: str | None = None,
                  arousal_max: float | None = None,
                  arousal_min: float | None = None,
                  limit: int = 20) -> str:
    """在本地曲库里按条件搜歌。genre 是流派子串；arousal 是能量 0–1
    （越低越安静，**只对实测过的曲目有效**）；primary_type 如 Album / Single。
    默认排除用户已有的歌、每位艺人最多 2 首。"""
    return _run("search_tracks",
                {"genre": genre, "year_from": year_from, "year_to": year_to,
                 "primary_type": primary_type, "arousal_max": arousal_max,
                 "arousal_min": arousal_min, "limit": limit})


@mcp.tool()
def similar_tracks(seed_track_ids: list[int], limit: int = 10) -> str:
    """按内容相似度（流派/年代/艺人/能量的加权）找库里和种子曲目相似的歌。
    seed_track_ids 传用户喜欢的曲目 id 列表。"""
    return _run("similar_tracks",
                {"seed_track_ids": seed_track_ids, "limit": limit})


@mcp.tool()
def library_stats() -> str:
    """全库规模与流派分布总览。"""
    return _run("library_stats", {})


@mcp.tool()
def genre_distribution(top_n: int = 8) -> str:
    """用户的流派画像（专辑级 / 艺人级分开报）。"""
    return _run("genre_distribution", {"top_n": top_n})


@mcp.tool()
def mood_energy_profile() -> str:
    """用户的能量画像：实测能量均值/中位数、调性（大调占比）、效价（推断）。"""
    return _run("mood_energy_profile", {})


def main() -> int:
    global _USER_ID
    parser = argparse.ArgumentParser(description="MusicMind MCP Server")
    parser.add_argument("--user", type=int, required=True,
                        help="以哪个用户身份暴露工具（个人电台的单用户模式）")
    args = parser.parse_args()
    _USER_ID = args.user
    mcp.run()          # stdio transport —— stdout 是协议通道，日志走 stderr
    return 0


if __name__ == "__main__":
    sys.exit(main())