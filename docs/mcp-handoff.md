# MCP Server 交接：把音乐库暴露给 MCP 客户端

**这一步是你的。** 目标：Claude Desktop（或任何 MCP 客户端）连上本机后，
可以直接问「我最常听什么」「推荐几首安静的」「Britpop 是什么」——
它调用你的工具，拿到真实数据再回答。

简历语境：2025-26 招聘最热的一个词，而你已经有的东西（17 个工具、
tool registry、警告不抛异常的契约）让接入度极高——**缺的只是一个协议层**。

---

## 起点：不需要任何新的数据能力

```
工具层        REGISTRY + call() + catalog()        ← 有了（tools/base.py）
上下文构造     build_context(connection, user_id)   ← 有了（tools/__init__.py）
```

**MCP Server 不调 LLM。** chat/ask 里模型调工具的那套（`catalog()` 给模型 →
模型返回工具调用），角色换成了 MCP 客户端的模型。你的 server 只负责把工具
按 MCP 协议暴露出去。

## 设计决策（完整代码里都有对应注释，这里是「为什么」）

1. **单用户模式** `--user 34`：`ToolContext` 构造强制 user_id，agent-service
   的定位就是「一个人的电台」；不做多用户鉴权。
2. **每次调用新建 ctx**：`call()` 把 facts 写进 ctx 仓（`base.py:176`），复用会
   撞 key（「事实仓冲突」warning）。现有调用方（chat/graph）都每次新建。
3. **暴露 6 个工具**：`search_knowledge`（最「MCP 味」，语料 RAG）、`search_tracks`、
   `similar_tracks`、`library_stats`、`genre_distribution`、`mood_energy_profile`。
   17 个全给会让客户端模型选择困难；`artist_deep_dive` 需要本地 artist id，
   对对话客户端不友好——首版不暴露。
4. **不手写 JSON Schema**：`@mcp.tool()` 会把**函数类型注解自动转成
   inputSchema**，docstring 当工具描述。所以每个工具是一个带类型注解的薄包装。
5. **技术选型（2026-10-14 实测更新）**：官方 `mcp` 包——**现在 `pip install mcp`
   装到的是 2.3.0（v2 已转正）**：FastMCP 改名 MCPServer，就是一处 import + 类名：

   ```python
   from mcp.server.mcpserver import MCPServer
   mcp = MCPServer("musicmind")
   ```

   decorator（`@mcp.tool()`）和 `run()` 用法不变。（v2 里协议类型字段是
   snake_case——`Tool.input_schema` 不再是 `inputSchema`——只有写底层测试代码
   时会碰到；装到 1.x 的话 import 换回 `mcp.server.fastmcp` 的 FastMCP。）
6. **warning 变错误文本，永不抛**：沿用 `call()` 的契约；「Ollama 没开」这类
   状态要出现在返回文本里，让客户端模型能如实转告，server 不许崩。
7. **stdout 是协议通道**：`mcp.run()` 走 stdio，stdout 上每个字节都是 JSON-RPC。
   服务器代码里**不许 print**，日志只能走 stderr。

---

## 改动清单

| 文件 | 动作 |
|---|---|
| `agent-service/musicmind_agent/mcp_server.py` | **新建**（完整代码在下） |
| `agent-service/requirements.txt` | 加一行 `mcp` |

## 完整代码：`agent-service/musicmind_agent/mcp_server.py`

```python
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
        rows = result.rows[:10]
        cols = list(rows[0].keys())
        parts.append("| " + " | ".join(cols) + " |")
        parts.append("|" + "---|" * len(cols))
        for row in rows:
            parts.append("| " + " | ".join(str(row.get(c, "")) for c in cols) + " |")
        if len(result.rows) > 10:
            parts.append(f"（共 {len(result.rows)} 行，显示前 10）")
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
```

`requirements.txt` 追加（放最后一行）：

```
mcp
```

---

## 验收（一条命令，不需要任何桌面客户端）

```bash
cd agent-service
.venv/Scripts/pip install mcp

# 主验收：官方 SDK client 连真 stdio 的 smoke（list + 4 个真调用）
agent-service/.venv/Scripts/python.exe ../scripts/mcp_smoke.py
#    预期：6 passed, 0 failed
#    （从仓库根跑：agent-service/.venv/Scripts/python.exe scripts/mcp_smoke.py）

# 故障路径已含在里面：Ollama 没开时 search_knowledge 应返回
# 「> ⚠ 连不上 Ollama」说明文本，脚本仍全绿
```

**可选**：想用图形界面点着看，用官方 Inspector（不需要 Claude Desktop）：

```bash
npx @modelcontextprotocol/inspector \
  agent-service/.venv/Scripts/python.exe -m musicmind_agent.mcp_server --user 34
```

**接线（任何 MCP 客户端都行，不绑定具体某一个）**：项目根的 `.mcp.json`
已经配好（Claude Code 的项目级配置）——`claude mcp list` 能看到它，
首次加载需要批准一次。之后在 Claude Code 里就能直接让它调你的工具
（「查一下我的流派分布」）。

其它宿主（Cursor、Inspector、【若你用】Claude Desktop……）同理：把这同一段
`command / args / env` 搬进各自的配置即可，**stdio 是标准协议，一份 server
处处可连**。换机器时记得改两个绝对路径（python 和 PYTHONPATH）。

---

## 之后（不在这一步）：简历话术

跑通后一起打磨措辞。方向：「基于自研 tool registry（17 个工具）暴露 MCP Server，
Claude Desktop 直连本地音乐库；工具调用全程走既有的数据契约与错误处理约定」。
