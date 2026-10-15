"""MCP Server 验收 smoke：用官方 SDK 的 client 连真 stdio，调真工具。

跑法：cd agent-service && .venv/Scripts/python.exe ../scripts/mcp_smoke.py
（或从仓库根：agent-service/.venv/Scripts/python.exe scripts/mcp_smoke.py）

【为什么不依赖任何桌面客户端】Inspector 适合有人看着图形界面点；
这个脚本管的是「每次改动后一条命令的回归」——不需要 Claude Desktop，
也不用手拼 JSON-RPC（那是十月初临时验证时的土办法）。

故障路径（手动）：停掉 Ollama 再跑一遍 —— search_knowledge 应返回
带说明的错误文本，脚本仍全绿（工具不崩 = 契约成立）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent          # 仓库根
AGENT_DIR = ROOT / "agent-service"
PYTHON = AGENT_DIR / ".venv" / "Scripts" / "python.exe"
USER = sys.argv[1] if len(sys.argv) > 1 else "34"

EXPECTED_TOOLS = {
    "search_knowledge", "search_tracks", "similar_tracks",
    "library_stats", "genre_distribution", "mood_energy_profile",
}

PASSED, FAILED = [], []


def check(label: str, ok: bool, extra: str = "") -> None:
    (PASSED if ok else FAILED).append(label)
    print(("  PASS " if ok else "  FAIL ") + label + (f"   {extra}" if extra else ""))


async def main() -> int:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    params = StdioServerParameters(
        command=str(PYTHON),
        args=["-m", "musicmind_agent.mcp_server", "--user", USER],
        cwd=str(AGENT_DIR),
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. 工具清单
            tools = await session.list_tools()
            names = {t.name for t in tools.tools}
            check(f"工具清单 = {len(EXPECTED_TOOLS)} 个且名字齐全",
                  names == EXPECTED_TOOLS, f"实际: {sorted(names)}")
            schemas_ok = all(
                t.input_schema and "properties" in t.input_schema for t in tools.tools)
            check("每个工具都有可用的 input_schema", schemas_ok)

            # 2. 四个真调用（断言结构与关键字样，不硬编码数字）
            r = await session.call_tool("library_stats", {})
            text = r.content[0].text
            check("library_stats 返回曲库规模", "library.tracks" in text,
                  text.splitlines()[0][:40] if text else "")

            r = await session.call_tool("genre_distribution", {"top_n": 3})
            text = r.content[0].text
            check("genre_distribution 返回流派画像",
                  "genre.album.mandopop.share" in text)

            r = await session.call_tool("search_tracks",
                                        {"arousal_max": 0.4, "limit": 3})
            text = r.content[0].text
            check("search_tracks 带能量档列 + 覆盖警告置顶",
                  "能量档" in text and text.lstrip().startswith("> ⚠"))

            r = await session.call_tool("search_knowledge", {"query": "Britpop"})
            text = r.content[0].text
            ok = bool(text.strip()) and "Traceback" not in text
            check("search_knowledge 有作答（Ollama 停掉时也应是说明文本）",
                  ok, text[:50].replace("\n", " "))

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
