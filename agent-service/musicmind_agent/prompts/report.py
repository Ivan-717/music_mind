"""组装一份报告：跑工具 → 喂给 LLM → 渲染 → 存下来。

Phase 2 只做「生成 + 渲染」，验证器是 Phase 3。
所以这个文件里【故意没有】校验逻辑 —— 先把链路跑通，再上一层层防线。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from musicmind_agent.llm import LLMClient, LLMResponse
from musicmind_agent.models import ReportDraft
from musicmind_agent.prompts.compose import PROMPT_VERSION, SYSTEM, USER_TEMPLATE
from musicmind_agent.render import render_text
from musicmind_agent.tools import build_context, call, catalog, core_tool_names


@dataclass
class GeneratedReport:
    draft: ReportDraft
    facts: dict
    rendered: dict          # 数字已经替换成真值的版本
    usage: dict


def _format_overview(ctx) -> str:
    """给 LLM 看的概览。只放事实，不放原始行 —— 它会淹没在数据里。"""
    lines = []
    for key, value in sorted(ctx.facts.items()):
        lines.append(f"- {key} = {value}")
    return "\n".join(lines)


def _format_tool_results(ctx, results) -> str:
    """results 是 {工具名: ToolResult 或它的 as_dict()}。

    【为什么要兼容 dict】图里把工具产出存进 state 才能跨节点复用，
    而 state 要过 checkpoint 序列化 —— ToolResult 是 dataclass，过不去。
    统一 as_dict() 之后两边都能用。
    """
    def field(result, key):
        return result.get(key) if isinstance(result, dict) else getattr(result, key)

    blocks = []
    for name, result in results.items():
        blocks.append(f"### {name}")
        blocks.append(f"facts: {json.dumps(field(result, 'facts'), ensure_ascii=False)}")
        rows = field(result, "rows")
        if rows:
            blocks.append(f"rows: {json.dumps(rows[:10], ensure_ascii=False)}")
        coverage = field(result, "coverage")
        if coverage:
            blocks.append(f"coverage: {json.dumps(coverage, ensure_ascii=False)}")
        # 【evidence 必须给 LLM 看】它列的是【用户自己的曲目】，是唯一可以
        # 拿来当证据的 id 池。不给的话模型只能从别处猜 id ——
        # 实测：第一版漏了这一块，模型把推荐候选的 id 当成用户的歌写进了证据和锚点，
        # 34 条证据、5 个锚点全部越界
        evidence = field(result, "evidence")
        if evidence:
            blocks.append("evidence（这些是【用户自己听过的曲目】，引用 id 只能从这里取）: "
                          + json.dumps(evidence, ensure_ascii=False))
        warnings = field(result, "warnings")
        if warnings:
            blocks.append(f"warnings: {warnings}")
        blocks.append("")
    return "\n".join(blocks)


def format_context(ctx, results) -> str:
    """把工具产出拼成给 LLM 看的那一大段。

    【为什么单独抽出来】compose 和 probe 两个节点都要给模型看上下文，
    但看的东西不一样（compose 要全部，probe 只要覆盖率和已有的探针结果）。
    抽出来才能复用同一套拼装规则，而不是各写一份、慢慢漂移。
    """
    return _format_tool_results(ctx, results)


def build_messages(ctx, candidates, tool_results=None, reco_count: int = 5) -> list[dict]:
    """compose / repair 共用的消息构造。

    candidates 传 None 表示「不重新给候选」—— repair 走的就是这条路：
    它只需要在原文基础上改，重新塞一遍候选反而会让它换一批推荐。

    tool_results **必须传**（图里从 state 取）。第一版把它做成可选，
    结果 compose 节点没传 —— 模型只看得见推荐候选那一列 track id，
    就把它们当成了用户的歌，64 条违规里大半是「证据曲目 X 不是用户的歌」。
    核心工具的 evidence 是模型判断「哪些 id 能用」的唯一依据，缺了它必错。
    """
    results = tool_results or {}

    # 【只告诉模型「能写哪些维度」，不告诉它「还有哪些工具没跑」】
    #
    # 两次实测，方向正好相反，很有信息量：
    #   · 给出 Tier 1 工具目录  → 3 次运行 119 条违规，全是编造事实名
    #     （写出 form.album.share —— album_form_distribution 没跑）
    #   · 改成列出「没跑过的探针名字」→ 3 次 311 条，更糟
    #     （写出 region.CN.share —— 名字见了就照着编）
    #
    # 结论：**只要提到没跑的工具，模型就会去编它们的键**，不管是给目录
    # 还是给名字。真正的根因不是信息不足 —— 概览里已经列了全部真实键，
    # 模型却还是给「region / collaboration / album_form」这些**没数据的维度**
    # 编内容。所以要限制的是**它能写哪些维度**，不是提示它缺什么。
    #
    # 前缀 → 维度名的映射来自 facts 的命名约定（见 tools/ 里各工具的 key）
    PREFIX_TO_DIMENSION = {
        "genre": "genre", "era": "era", "artist": "artist",
        "mood": "mood_energy", "diversity": "diversity",
        "form": "album_form", "collab": "collaboration",
        "region": "region", "duration": "duration",
    }
    present = {k.split(".")[0] for k in results and ctx.facts}
    available_dims = sorted({PREFIX_TO_DIMENSION[p] for p in present if p in PREFIX_TO_DIMENSION})
    unavailable = (
        "**本次只能写这些维度：** " + "、".join(available_dims) + "。\n"
        "其他维度（比如 region / collaboration / album_form）**这一轮没有数据**，"
        "不要为它们写任何内容 —— 写了也会因为引用不存在的事实被打回。"
    )

    blocks = _format_tool_results(ctx, results) if results else ""
    if candidates is not None:
        # 【不发 track_id】见 models.Recommendation 的说明。
        # prompt 里同时出现两列 track id（evidence 里用户听过的 + 候选里没听过的），
        # 模型会混 —— 实测每次跑都因此触发一轮 repair，约 10-13 秒。
        # 只发序号之后，候选的 id 根本不进 prompt，混都混不了。
        numbered = [
            {"candidate_index": i + 1,
             **{k: v for k, v in row.items() if k != "track_id"}}
            for i, row in enumerate(candidates.rows)
        ]
        blocks += (
            "\n### 推荐候选（【不是】用户的曲目，是准备推给他的新歌；"
            "只能出现在 recommendations 里，不能当证据。"
            "引用时写 candidate_index —— 这里没有 track_id）\n"
            + json.dumps(numbered, ensure_ascii=False)
        )

    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": USER_TEMPLATE.format(
            overview=_format_overview(ctx),
            tool_results=blocks or "（本轮没有额外的工具输出，用上面的概览）",
            unavailable=unavailable,
            reco_count=reco_count,
        )},
    ]


def build_report(connection, user_id: int, provider: str, client: LLMClient | None = None) -> GeneratedReport:
    ctx = build_context(connection, user_id)

    # Tier 0 全都跑。核心维度固定，不让 LLM 决定查不查
    results = {name: call(name, ctx) for name in core_tool_names()}

    client = client or LLMClient(provider=provider)

    # 推荐候选：先跑一次 similar_tracks 拿到候选列表给 LLM 挑
    # （Phase 5 会换成正式的五路召回，这里先用最简单的）
    seeds = [t.track_id for t in sorted(
        ctx.tracks, key=lambda t: -(t.arousal_measured or 0))[:5]]
    candidates = call("similar_tracks", ctx, {"seed_track_ids": seeds, "limit": 30})

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": USER_TEMPLATE.format(
            overview=_format_overview(ctx),
            tool_results=_format_tool_results(ctx, {n: r.as_dict() for n, r in results.items()})
                          # 这一段必须和用户的曲目划清界限。混在一起时模型
                          # 会把候选当用户的歌，拿它们的 id 去当证据和锚点
                          + "\n### 推荐候选（【不是】用户的曲目，是准备推给他的新歌；"
                            "只能出现在 recommendations 里，不能当证据）\n"
                          + json.dumps(candidates.rows, ensure_ascii=False),
            unavailable="",
            reco_count=5,
        )},
    ]

    raw, response = client.chat_json(messages)
    draft = ReportDraft.model_validate(raw)

    return GeneratedReport(
        draft=draft,
        facts=ctx.facts,
        rendered=_render(draft, ctx.facts),
        usage={
            "provider": response.provider,
            "model": response.model,
            "tokens_in": response.tokens_in,
            "tokens_out": response.tokens_out,
            "latency_ms": response.latency_ms,
            "prompt_version": PROMPT_VERSION,
        },
    )


def _render(draft: ReportDraft, facts: dict) -> dict:
    """把所有 {fact.key} 换成真值。strict=False —— Phase 2 先看有多少没替换上，
    Phase 3 的验证器会把它变成硬失败。"""
    data = draft.model_dump()
    data["headline"]["title"] = render_text(data["headline"]["title"], facts, strict=False)
    data["headline"]["subtitle"] = render_text(data["headline"]["subtitle"], facts, strict=False)
    for dim in data["dimensions"]:
        dim["summary"] = render_text(dim["summary"], facts, strict=False)
        for claim in dim["claims"]:
            claim["text"] = render_text(claim["text"], facts, strict=False)
    for rec in data["recommendations"]:
        rec["reason"] = render_text(rec["reason"], facts, strict=False)
        rec["relation_to_history"]["note"] = render_text(
            rec["relation_to_history"]["note"], facts, strict=False)
    # limitations 也要渲染 —— 第一版漏了，于是「专辑级只覆盖 {coverage.genre_via_album} 首」
    # 这种句子带着花括号原样输出。凡是 LLM 写的文本都要过一遍渲染，没有例外
    data["limitations"] = [
        render_text(item, facts, strict=False) for item in data["limitations"]
    ]
    return data