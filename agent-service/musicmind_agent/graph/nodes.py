"""八个节点。

【节点函数的签名是固定的】LangGraph 按 (state, config) 调用。
ctx 从 config 里取 —— 见 state.py 的说明，它不能进 state。
"""

from __future__ import annotations

import json
import time

from musicmind_agent.evidence import MIN_ARTISTS, MIN_TRACKS
from musicmind_agent.graph.state import (
    MAX_BARREN_PROBES,
    MAX_PROBES,
    MAX_REPAIRS,
    PROBE_TOKEN_BUDGET,
    AgentState,
    trace,
)
from musicmind_agent.llm import LLMClient
from musicmind_agent.models import ReportDraft
from musicmind_agent.prompts import compose as compose_prompt
from musicmind_agent.prompts import probe as probe_prompt
from musicmind_agent.render import render_text
from musicmind_agent.tools import call, catalog, core_tool_names
from musicmind_agent.tools.base import ToolContext
from musicmind_agent.validate import validate


def get_ctx(config) -> ToolContext:
    """从 config 里取上下文。**取不到就是配置错了，直接炸** ——
    不能返回 None 让下游去判空，那样错误会飘到很远的地方才现形。"""
    ctx = (config or {}).get("configurable", {}).get("ctx")
    if ctx is None:
        raise RuntimeError("config.configurable.ctx 缺失：调用方必须 build_context 后传进来")
    return ctx


def get_client(config) -> LLMClient:
    client = (config or {}).get("configurable", {}).get("client")
    if client is None:
        raise RuntimeError("config.configurable.client 缺失")
    return client


# ============================================================
# 1. resolve_user —— 确定性，数据不足守卫
# ============================================================

def resolve_user(state: AgentState, config) -> AgentState:
    started = time.monotonic()
    ctx = get_ctx(config)

    tracks = ctx.tracks
    artists = {t.artist_id for t in tracks if t.artist_id}
    insufficient = len(tracks) < MIN_TRACKS or len(artists) < MIN_ARTISTS

    started_entry = {"node": "resolve_user",
                     "ms": int((time.monotonic() - started) * 1000),
                     "note": f"{len(tracks)} 首 / {len(artists)} 位艺人"}

    return {
        "user_id": ctx.evidence.user_id,

        # 【这是一次运行的起点，必须把上一次的残留清干净】
        #
        # thread_id 是 `report-{user_id}` —— **同一个人第二次生成会落到同一个
        # checkpoint 上**，LangGraph 会把上一次的 state 合并进来。不清的话：
        #
        #   · tool_results 累积 —— 模型在 prompt 里看得见历史上所有探针的输出，
        #     而它们的 fact 不在本轮 ctx.facts 里。照着写就是渲染不出来的占位符
        #     （L1 会抓，但白跑一轮 repair）。**这是修轮次偏高的一个真实原因。**
        #   · trace 累积 —— 实测跑了 99 次之后，一份报告的 trace 有 834 步，
        #     checkpoint 库涨到 152MB
        #   · draft / rendered / violations 同理
        #
        # 第一次发现是因为 trace 里 `validate→repair→persist` 出现在
        # `resolve_user` **之前** —— 那个顺序在图上不可能出现
        "tool_results": {},
        "draft": {},
        "rendered": {},
        "violations": [],

        "plan": {},
        "probes": [],
        "probe_count": 0,
        "probe_tokens": 0,
        "probe_barren": 0,
        "model_done": False,
        "repair_count": 0,
        "degraded": False,
        "usage": {
            "insufficient": insufficient,
            "reason": (
                f"{len(tracks)} 首曲目 / {len(artists)} 位艺人"
                f"（门槛 {MIN_TRACKS} 首 / {MIN_ARTISTS} 位）"
            ) if insufficient else "",
        },
        # 【这里故意不用 trace() 那个 helper】它会把旧 trace 读出来接上去，
        # 而这一步要的是「从零开始记这一次」。之后每个节点再用 trace() 追加
        "trace": [started_entry],
    }


# ============================================================
# 2. plan —— LLM 勾选探针
# ============================================================

def plan(state: AgentState, config) -> AgentState:
    started = time.monotonic()
    ctx, client = get_ctx(config), get_client(config)

    # 只给 Tier 1 的目录 —— 核心工具不在选项里，它们无条件跑
    messages = [
        {"role": "system", "content": probe_prompt.PLAN_SYSTEM},
        {"role": "user", "content": probe_prompt.PLAN_USER.format(
            overview=json.dumps(
                {k: v for k, v in sorted(ctx.facts.items()) if k.startswith(("coverage.", "scope."))},
                ensure_ascii=False, indent=1),
            catalog=json.dumps(catalog(tier=1), ensure_ascii=False, indent=1),
            max_probes=MAX_PROBES,
        )},
    ]
    raw, response = client.chat_json(messages)

    # 【不在白名单就丢弃，不报错不重试】跨模型稳的关键：
    # 两家模型都能稳定做「从给定列表里选」，但自由生成工具名则各有各的毛病。
    # 报告里出现一个没跑过的工具，比少跑一个探针糟得多
    allowed = {t["name"] for t in catalog(tier=1)}
    picked = [p for p in (raw.get("probes") or []) if p in allowed][:MAX_PROBES]

    return {
        "plan": {"probes": picked, "hypotheses": raw.get("hypotheses") or []},
        "usage": _add_usage(state, tokens_in=response.tokens_in, tokens_out=response.tokens_out),
        "trace": trace(state, "plan", ms=int((time.monotonic() - started) * 1000),
                       tokens_in=response.tokens_in, tokens_out=response.tokens_out,
                       note=f"选了 {picked}"),
    }


# ============================================================
# 3. run_core_tools —— 确定性
# ============================================================

def run_core_tools(state: AgentState, config) -> AgentState:
    started = time.monotonic()
    ctx = get_ctx(config)

    names = core_tool_names()
    results = {name: call(name, ctx) for name in names}
    # 存进 state 供 compose / repair 使用（见 state.py 的说明）
    merged = dict(state.get("tool_results") or {})
    merged.update({name: r.as_dict() for name, r in results.items()})

    return {
        "tool_results": merged,
        "trace": trace(state, "run_core_tools",
                       ms=int((time.monotonic() - started) * 1000),
                       note=f"{len(results)} 个核心工具，facts 仓 {len(ctx.facts)} 条"),
    }


# ============================================================
# 4. probe —— LLM 工具循环（自环）
# ============================================================

def probe(state: AgentState, config) -> AgentState:
    """跑一批探针。

    **这个节点会自环**，由 route_after_probe 决定是再转一圈还是出边。
    每次进来只处理「模型这一轮想调的那几个」，不是一次跑完 ——
    这样模型能根据上一轮结果决定下一轮查什么。
    """
    started = time.monotonic()
    ctx, client = get_ctx(config), get_client(config)

    # 已跑过的探针结果要带上，否则模型会反复调同一个
    history = [
        {"tool": p["tool"], "args": p.get("args"), "facts": p.get("facts_digest")}
        for p in state.get("probes", [])
    ]

    messages = [
        {"role": "system", "content": probe_prompt.PROBE_SYSTEM},
        {"role": "user", "content": probe_prompt.PROBE_USER.format(
            overview=json.dumps(
                {k: v for k, v in sorted(ctx.facts.items())
                 if k.startswith(("coverage.", "scope.", "mood."))},
                ensure_ascii=False, indent=1),
            already=json.dumps(history, ensure_ascii=False, indent=1),
            catalog=json.dumps(catalog(tier=1), ensure_ascii=False, indent=1),
            remaining=MAX_PROBES - state.get("probe_count", 0),
        )},
    ]
    raw, response = client.chat_json(messages)

    requests_ = raw.get("calls") or []
    if raw.get("done") or not requests_:
        # 【模型说够了就记下来，不要在节点里直接决定去留】
        # 节点的职责是「记录发生了什么」，路由的职责是「据此决定去哪」。
        # 之前这两件事混在一起，导致计划里还有没跑的探针时，
        # 路由会无视模型的 done 继续转 —— 实测最多白烧 6 轮 LLM 调用。
        return {
            "model_done": True,
            "probe_count": state.get("probe_count", 0) + 1,
            "probe_tokens": state.get("probe_tokens", 0) + response.tokens_in,
            "usage": _add_usage(state, tokens_in=response.tokens_in, tokens_out=response.tokens_out),
            "trace": trace(state, "probe", ms=int((time.monotonic() - started) * 1000),
                           tokens_in=response.tokens_in, tokens_out=response.tokens_out,
                           note="模型认为够了"),
        }

    allowed = {t["name"] for t in catalog(tier=1)}
    ran: list[dict] = []
    probe_results: dict[str, dict] = {}            # 探针产出，合并进 tool_results
    facts_before = len(ctx.facts)                  # ← 用来算这一轮有没有收获

    for req in requests_[:3]:                      # 一轮最多跑 3 个，防止一口气烧光
        name = req.get("tool")
        if name not in allowed:
            # 编的工具名：记一条但不当错误 —— 它不影响报告的数字，只是少了一次探索
            ran.append({"tool": name, "ok": False, "error": "不在白名单里"})
            continue
        result = call(name, ctx, req.get("args") or {})
        probe_results[name] = result.as_dict()
        ran.append({
            "tool": name,
            "args": req.get("args") or {},
            "ok": not result.warnings,
            # 只带 facts 的摘要进历史，不带 rows/evidence —— 那会把上下文撑爆
            "facts_digest": dict(list(result.facts.items())[:20]),
        })

    # 【这一轮到底有没有收获】不是「跑了几次」，是「多了几条事实」。
    # 跑了很多次但 facts 仓没长，说明这些探针在这个用户身上是空转 ——
    # 那才是该停的信号，而「跑够 N 次」不是。
    call_added = len(ctx.facts) - facts_before
    barren = 0 if call_added > 0 else state.get("probe_barren", 0) + 1

    merged = dict(state.get("tool_results") or {})
    merged.update(probe_results)

    return {
        "tool_results": merged,
        "probes": state.get("probes", []) + ran,
        "probe_count": state.get("probe_count", 0) + 1,
        "probe_tokens": state.get("probe_tokens", 0) + response.tokens_in,
        "probe_barren": barren,
        "usage": _add_usage(state, tokens_in=response.tokens_in, tokens_out=response.tokens_out),
        "trace": trace(state, "probe", ms=int((time.monotonic() - started) * 1000),
                       tokens_in=response.tokens_in, tokens_out=response.tokens_out,
                       # 带上参数 —— 只记工具名的话，「artist_deep_dive 调了 3 次」
                       # 看不出是在查 3 个不同艺人（合理）还是重复调同一个（浪费）
                       note="跑了 " + ", ".join(
                           f"{r['tool']}({json.dumps(r.get('args') or {}, ensure_ascii=False)[:40]})"
                           for r in ran) + f"，新增 {call_added} 条事实"),
    }


def route_after_probe(state: AgentState) -> str:
    """自环的**唯一**出口。节点只负责记录状态，去留全在这里决定。

    【为什么收拢到一处】之前节点的 early-return 也在做「该不该停」的判断
    （模型返回 done 就直接返回），路由这边又在判次数 —— 两处逻辑漂移的后果
    是真实的：计划里还有没跑的探针时，路由会无视模型的 done 继续转。

    【出口的优先级，从主观到客观】

    1. **模型说够了** —— 唯一带判断力的出口。
       它看过全部上下文，比任何阈值更知道「再查有没有意义」。

    2. **连续空手而归** —— 主出口。
       「跑了几次」不是好信号，「跑完有没有新事实」才是。
       一个探针在这个用户身上返回空，跑第二次还是空，第三次大概率还是空。

    3. **硬上限兜底** —— 必须有，而且不是多余的：
       如果模型交替产出「有收获 / 没收获」，第 2 条永远不会触发。
       上限在这儿的作用是「防跑飞」，不是「日常出口」。
    """
    if state.get("model_done"):
        return "compose"

    if state.get("probe_barren", 0) >= MAX_BARREN_PROBES:
        return "compose"

    if state.get("probe_count", 0) >= MAX_PROBES:
        return "compose"
    if state.get("probe_tokens", 0) >= PROBE_TOKEN_BUDGET:
        return "compose"

    return "probe"


# ============================================================
# 5. compose —— LLM 产出草稿
# ============================================================

def compose(state: AgentState, config) -> AgentState:
    from musicmind_agent.prompts.report import format_context, build_messages

    started = time.monotonic()
    ctx, client = get_ctx(config), get_client(config)

    # 推荐候选：Phase 5 会换成正式的五路召回，这里先用 similar_tracks
    seeds = [t.track_id for t in sorted(
        ctx.tracks, key=lambda t: -(t.arousal_measured or 0))[:5]]
    # 候选数要跟着推荐条数放大 —— 只要 30 个候选却让模型挑 50 首，
    # 它只能重复或者编。评估里 k=50，所以这里也得给够
    reco_count = (config or {}).get("configurable", {}).get("reco_count", 5)
    candidates = call("similar_tracks", ctx,
                      {"seed_track_ids": seeds, "limit": max(30, reco_count * 3)})

    # 【必须传 tool_results】缺了它模型看不见核心工具的 evidence，
    # 就会拿推荐候选的 id 当证据 —— 实测 64 条违规里大半是这个
    messages = build_messages(ctx, candidates, state.get("tool_results"), reco_count)
    raw, response = client.chat_json(messages)
    draft = ReportDraft.model_validate(raw).model_dump()

    return {
        "draft": draft,
        "rendered": _render(draft, ctx.facts, candidates),
        "usage": _add_usage(state, tokens_in=response.tokens_in, tokens_out=response.tokens_out),
        "trace": trace(state, "compose", ms=int((time.monotonic() - started) * 1000),
                       tokens_in=response.tokens_in, tokens_out=response.tokens_out),
    }


def _map_candidates(data: dict, candidates: list[dict]) -> dict:
    """把模型给的候选序号映射回真实 track_id【并把名字带上】。

    **这是「模型空间」和「数据空间」的边界**：模型只看得见序号，
    落库的报告里必须是真实 id。两个线索都指不到的行直接丢掉，不要猜 ——
    猜错了推荐的就是另一首歌，而且没人会发现。

    【按名字反查优先，序号兜底】实测模型会系统性数错序号（报告 30：
    20 条里前 8 条的理由整体错开一行，它按 0-based 数了；同样 prompt 的
    报告 28 又全对）。所以推荐结构里让模型**同时原样抄歌名**：
    先按歌名在候选里找回真正那一行 —— 「抄一行里的歌名」比「数第几行」
    可靠得多（2026-10-07 修）。名字为空或匹配不上，才回到序号。
    两者都指不到 → 丢掉。
    名字归一用 name_variants（繁简/空格/大小写）——这个仓库比名字一律用它。

    【为什么要把名字也塞进报告】第一版只映射了 track_id，
    结果前端拿到一条只有 id 的推荐，页面上显示的是「#16033」——
    用户根本不知道推的是哪首歌，整个推荐列表就废了。
    序号对应的那一行本来就有歌名/艺人/专辑，顺手带上，前端不用再查一次。
    """
    from musicmind_agent.validate.normalize import name_variants

    # 歌名归一 → 行。同名多版本（live/录音室）撞名时取先出现的 ——
    # 总比错位好，而且这种撞名模型抄过来的名字本来也区分不了
    by_name: dict[str, dict] = {}
    for row in candidates:
        for variant in name_variants(str(row.get("歌名") or "")):
            by_name.setdefault(variant, row)

    kept = []
    for rec in data.get("recommendations") or []:
        row = None
        picked = str(rec.get("name") or "").strip()
        if picked:
            for variant in name_variants(picked):
                if variant in by_name:
                    row = by_name[variant]
                    break
        if row is None:
            idx = rec.get("candidate_index")
            if isinstance(idx, int) and 1 <= idx <= len(candidates):
                row = candidates[idx - 1]
        if row is None:
            continue
        kept.append({
            **rec,
            # 这行覆盖模型抄的名字 —— 落库的是候选表里的规范写法
            "track_id": row["track_id"],
            "name": row.get("歌名"),
            "artist_names": row.get("艺人"),
            "album_name": row.get("专辑"),
            "release_year": row.get("发行年"),
            # 给推荐列表的 ▶ 和播放条封面（M8 后加，来自 similar_tracks 的 rows）
            "has_preview": bool(row.get("hasPreview")),
            "album_id": row.get("albumId"),
            "rank": rec.get("rank") or len(kept) + 1,
        })
    return {**data, "recommendations": kept}


def _render(draft: dict, facts: dict, candidates=None) -> dict:
    """数字引用替换。**每个 LLM 写的字段都要过一遍** ——
    第一版漏了 limitations，那里面就带着花括号原样输出了。"""
    import copy

    data = copy.deepcopy(draft)
    if candidates is not None:
        data = _map_candidates(data, candidates.rows)
    data["headline"]["title"] = render_text(data["headline"]["title"], facts, strict=False)
    data["headline"]["subtitle"] = render_text(data["headline"]["subtitle"], facts, strict=False)
    # 【新字段都要在这收口】漏一个就会出现「没替换的花括号」——
    # limitations 当年就是这么漏的
    data["opening"] = render_text(data.get("opening") or "", facts, strict=False)
    for dim in data["dimensions"]:
        dim["summary"] = render_text(dim["summary"], facts, strict=False)
        for claim in dim["claims"]:
            claim["text"] = render_text(claim["text"], facts, strict=False)
    for rec in data["recommendations"]:
        rec["reason"] = render_text(rec["reason"], facts, strict=False)
        rec["relation_to_history"]["note"] = render_text(
            rec["relation_to_history"]["note"], facts, strict=False)
    data["limitations"] = [render_text(x, facts, strict=False) for x in data["limitations"]]

    # 【依据行由代码渲染，不是 LLM 写的】名字是创作（模型负责），
    # 「这个名字打哪儿来」是事实（代码负责）。两个来源分开，
    # 模型就没法通过写一个好看的名字顺手把依据也编了。
    #
    # 这里只用 facts，不用 tool_results —— 依据行显示的是素材名（「头部流派」）
    # 加真值，不显示流派/艺人的名字，所以那层有损还原不影响到它
    from musicmind_agent.persona import basis_line, traits_from_facts
    data["persona_basis"] = basis_line(traits_from_facts(facts), facts)

    return data


# ============================================================
# 6. validate —— 确定性，调 Phase 3
# ============================================================

def validate_node(state: AgentState, config) -> AgentState:
    started = time.monotonic()
    ctx = get_ctx(config)

    result = validate(state.get("rendered") or {}, ctx)

    violations = [
        {"layer": v.layer, "path": v.path, "detail": v.detail, "severity": v.severity}
        for v in result.violations
    ]

    # trace 里带上具体违规，不只是条数 —— 调 repair 的时候
    # 「违规 5 → 违规 5」这种信息等于没说，要看得到内容才知道它为什么没改掉
    return {
        "violations": violations,
        "trace": trace(state, "validate", ms=int((time.monotonic() - started) * 1000),
                       note=result.summary().splitlines()[0],
                       violations=[f"[{v['layer']}] {v['path']}: {v['detail']}"
                                   for v in violations[:6]]),
    }


def route_after_validate(state: AgentState) -> str:
    errors = [v for v in state.get("violations", []) if v.get("severity") == "error"]
    if not errors:
        return "persist"
    if state.get("repair_count", 0) >= MAX_REPAIRS:
        return "fallback"
    return "repair"


# ============================================================
# 7. repair —— 把违规原文回灌给 LLM 重写
# ============================================================

def repair(state: AgentState, config) -> AgentState:
    from musicmind_agent.prompts.report import build_messages
    from musicmind_agent.prompts import repair as repair_prompt

    started = time.monotonic()
    ctx, client = get_ctx(config), get_client(config)

    errors = [v for v in state.get("violations", []) if v.get("severity") == "error"]

    messages = build_messages(ctx, None, state.get("tool_results")) + [
        {"role": "assistant", "content": json.dumps(state.get("draft"), ensure_ascii=False)},
        {"role": "user", "content": repair_prompt.REPAIR_USER.format(
            # 【原文回灌】不要在这里改写成代码/编号 ——
            # Phase 3 的报错措辞是按「给模型看」写的（含正确的键名提示），
            # 加工一遍就把最有用的信息丢了
            violations=json.dumps(errors, ensure_ascii=False, indent=1),
        )},
    ]
    raw, response = client.chat_json(messages)
    draft = ReportDraft.model_validate(raw).model_dump()

    # repair 也要带着候选去渲染 —— 模型重写时可能换推荐，
    # 序号不映射回去的话 rendered 里就没有 track_id 了
    seeds = [t.track_id for t in sorted(
        ctx.tracks, key=lambda t: -(t.arousal_measured or 0))[:5]]
    # 候选数要跟着推荐条数放大 —— 只要 30 个候选却让模型挑 50 首，
    # 它只能重复或者编。评估里 k=50，所以这里也得给够
    reco_count = (config or {}).get("configurable", {}).get("reco_count", 5)
    candidates = call("similar_tracks", ctx,
                      {"seed_track_ids": seeds, "limit": max(30, reco_count * 3)})

    return {
        "draft": draft,
        "rendered": _render(draft, ctx.facts, candidates),
        "repair_count": state.get("repair_count", 0) + 1,
        "usage": _add_usage(state, tokens_in=response.tokens_in, tokens_out=response.tokens_out),
        "trace": trace(state, "repair", ms=int((time.monotonic() - started) * 1000),
                       tokens_in=response.tokens_in, tokens_out=response.tokens_out,
                       note=f"修 {len(errors)} 条"),
    }


# ============================================================
# 8. fallback_render —— 确定性降级
# ============================================================

def fallback_render(state: AgentState, config) -> AgentState:
    """代码直接渲染数据部分，叙事里没过验证的整段丢掉。

    【为什么要有这一条】它是「报告里不会出现没根据的数字」的
    **结构性保证**，不是概率性保证 —— 重试两次都改不对时，
    仍然有一份数据部分绝对正确的报告可以落库，而不是带着违规数据出去。

    代价是报告变「干」：只剩维度的 summary 和纯数据行，没有叙事。
    这是有意的取舍。
    """
    ctx = get_ctx(config)
    draft = state.get("draft") or {}
    violations = state.get("violations", [])
    bad_paths = {v["path"] for v in violations if v.get("severity") == "error"}

    kept_dims = []
    for i, dim in enumerate(draft.get("dimensions") or []):
        claims = [
            c for j, c in enumerate(dim.get("claims") or [])
            if f"dimensions[{i}].claims[{j}]" not in bad_paths
        ]
        # 【summary 也要管】第一版只丢违规的 claim，summary 原样留着 ——
        # 实测降级报告里还残留「合唱网络只覆盖 {collab.xxx} 首」这种句子。
        # 它引用的探针这一轮根本没跑，键不存在，渲染不出来，而它又不在
        # claim 里，所以躲过了丢弃逻辑。降级的意义是「退到绝对正确的版本」，
        # 留一句带花括号的总结等于没退
        summary = dim.get("summary") or ""
        if f"dimensions[{i}].summary" in bad_paths:
            summary = "（这一维度的结语未通过校验，已丢弃）"
        kept_dims.append({**dim, "summary": summary, "claims": claims})

    degraded = {
        "headline": {
            "title": "音乐画像（数据部分）",
            "subtitle": f"叙事部分未通过校验，已降级。原始违规 {len(violations)} 条",
        },
        "dimensions": kept_dims,
        "recommendations": [],          # 推荐项含 LLM 写的解释，整块丢掉
        "limitations": (draft.get("limitations") or []) + [
            "本次报告走了降级渲染：模型两次重写后仍有无法核实的内容，"
            "叙事部分被丢弃，只保留能机械核对的数据。",
        ],
    }

    return {
        # 【降级路径也必须渲染】第一版漏了这一步：degraded 是从 draft 拼的，
        # 而 draft 里的数字还是 {fact.key} 占位符 —— 于是「降级后的报告」
        # 里全是没替换的花括号，47 处。降级的意义是「退回绝对正确的版本」，
        # 结果退回去的是一份更烂的。
        "rendered": _render(degraded, ctx.facts),
        "degraded": True,
        "trace": trace(state, "fallback_render",
                       note=f"丢弃 {len(bad_paths)} 处违规内容"),
    }


# ============================================================
# 9. persist
# ============================================================

def persist(state: AgentState, config) -> AgentState:
    """落盘。Phase 6 会换成写 agent_report 表，这里先写文件。"""
    out_dir = (config or {}).get("configurable", {}).get("out_dir")
    if not out_dir:
        return {"trace": trace(state, "persist", note="没指定 out_dir，跳过")}

    import os

    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(state.get("rendered"), f, ensure_ascii=False, indent=2)
    with open(os.path.join(out_dir, "trace.jsonl"), "w", encoding="utf-8") as f:
        for step in state.get("trace", []):
            f.write(json.dumps(step, ensure_ascii=False) + "\n")

    return {"trace": trace(state, "persist", note=out_dir)}


# ============================================================
# 辅助
# ============================================================

def _add_usage(state: AgentState, **delta) -> dict:
    usage = dict(state.get("usage") or {})
    for key, value in delta.items():
        usage[key] = usage.get(key, 0) + value
    usage["llm_calls"] = usage.get("llm_calls", 0) + 1
    return usage