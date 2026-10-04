# Phase 4 交接：LangGraph 工作流

**这一步是你写，我验收。** 目标：把 Phase 1/2/3 的三块（工具层、LLM 层、验证器）
编排成一个能跑、能重试、能看到过程的图。

```bash
.venv/Scripts/python.exe -m musicmind_agent.cli agent --user 34 --provider deepseek --out out/run-1
```

---

## 先说验证过的事（免得你按旧文档写）

我已经把 `langgraph 1.2.12` 装上并**逐条实测**了要用的 API。下面是实测结果，
不是文档摘抄 —— 这个库版本间漂移很大。

```python
# ✅ 导入路径
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

# ✅ 构造（不支持 with 语句，实测报 TypeError: does not support the context manager protocol）
conn = sqlite3.connect(path, check_same_thread=False)
saver = SqliteSaver(conn)
app = g.compile(checkpointer=saver)

# ✅ 调用与读状态
app.invoke(state, config={"configurable": {"thread_id": "t1"}})
app.get_state({"configurable": {"thread_id": "t1"}}).values

# ✅ 自环、条件边、回边都正常（实测跑通 probe 连转 3 次 + validate→repair→validate）
```

**两个决定设计的实测结论：**

**① 数据库连接不能进 state。** state 会被 checkpoint 序列化（msgpack），
pymysql 连接序列化不了。放进 `config["configurable"]` 可以 —— 实测确认
不可序列化对象能带进去、能被节点读到、且**不会进 checkpoint**。

**② `config` 在节点之间是只读的。** 实测：节点 a 里 `config['configurable']['ctx'] = x`，
节点 b 读到的是「看不见」。LangGraph 每个节点拿到的是 config 的副本。

→ 所以**不能**在第一个节点里懒建 ctx。必须由调用方建好、invoke 时传进去。

```python
# cli.py 里
ctx = build_context(connection, user_id)
app.invoke(state, config={"configurable": {"thread_id": ..., "ctx": ctx}})
```

---

## 图设计

```
[resolve_user]      确定性   数据不足守卫（<20 首 或 <5 艺人 → 直接终止）
      │
      │ insufficient ──→ END
      ↓
[plan]              LLM      从白名单里勾选探针 + 写下假设
      ↓
[run_core_tools]    确定性   Tier 0 六个全跑
      ↓
[probe] ──┐         LLM      工具循环，可自环
      ↑───┘                  上限 6 次 或 token 预算耗尽 → 出边
      ↓
[compose]           LLM      JSON mode 产出报告草稿
      ↓
[validate]          确定性   调 Phase 3 的验证器
      │
      ├─ 有违规 且 修复次数 <2 → [repair] → 回到 [validate]
      ├─ 有违规 且 已修 2 次   → [fallback_render] → END
      └─ 无违规               → [persist] → END
```

### 三条设计理由（这几条不写在代码里就容易被改坏）

**1. 核心工具不让 LLM 决定跑不跑。** Agent 决定的是「额外查什么」，
不是「查不查基础维度」。理由：两次运行必须可比，否则评估没有基座；
某个模型漏调一次情绪维度，报告会静悄悄缺一块而无人报警。

**2. probe 的自环必须有硬上限。** 既要次数上限（6 次），也要 token 预算。
只限次数的话，模型可以一轮塞十个工具调用；只限 token 的话，
可能出现「跑一次就花光」导致一次有效的补充查询都做不了。

**3. repair 要回灌验证器的**原文**。** 「引用了不存在的事实 `mood.x_median`」
比「校验失败 #3」有用一个数量级 —— Phase 3 的报错措辞就是按这个写的，
别在中间再加工成代码。

---

## 要建的文件（5 个）

```
agent-service/
  musicmind_agent/
    graph/
      __init__.py   ← 1. 导出 build_graph / run
      state.py      ← 2. AgentState + 常量
      nodes.py      ← 3. 八个节点的实现
      build.py      ← 4. 图装配
  musicmind_agent/cli.py  ← 5. 加 agent 子命令
  tests/test_graph.py     ← 6. 图结构 + 故障注入测试
```

---

## 1. `musicmind_agent/graph/state.py`

```python
"""图的状态。

【什么放 state、什么放 config】
    state  会被 checkpoint 序列化 —— 只能放可序列化的东西（dict/list/str/int）
    config 不进 checkpoint —— 放连接、上下文这类运行期依赖

放错的后果：连接进 state 会在 checkpoint 时报序列化错误；
本该进 state 的东西放 config，则追问时读不回上一轮的信息。
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

# probe 自环的硬上限。上限本身是个设计决定：
# 太小（比如 2）则「覆盖率不足要换个维度补」做不完；
# 太大则模型会拿它当免费的探索额度，烧 token 却不出信息
MAX_PROBES = 6

# 修复次数上限。超了就降级渲染而不是继续重试 ——
# 两次都改不对，说明问题不在措辞而在模型这轮就是不行，再试只是烧钱
MAX_REPAIRS = 2

# probe 循环的 token 预算。和次数上限配合使用（见 nodes.py 的说明）
PROBE_TOKEN_BUDGET = 20000


class AgentState(TypedDict, total=False):
    """图中的数据。全部可序列化。"""

    user_id: int
    mode: Literal["report", "ask"]

    # --- 计划与探针 ---
    plan: dict[str, Any]          # plan 节点输出：{probes: [...], hypotheses: [...]}
    probes: list[dict]            # 每次探针调用：{tool, args, ok, facts_digest}
    probe_count: int
    probe_tokens: int             # probe 阶段累计消耗

    # --- 报告 ---
    draft: dict[str, Any]         # compose 的原始输出（未渲染）
    rendered: dict[str, Any]      # 渲染后（数字已替换）
    violations: list[dict]        # 验证器给的违规（**原文**，不要加工）
    repair_count: int
    degraded: bool                # 走没走降级渲染

    # --- 追踪 ---
    trace: list[dict]             # 每一步：{node, ms, tokens_in, tokens_out, note}
    usage: dict[str, Any]         # 汇总：tokens / llm_calls / 节点耗时


def trace(state: AgentState, node: str, **extra) -> list[dict]:
    """往 trace 里追加一步。节点统一用它，保证格式一致。"""
    return state.get("trace", []) + [{"node": node, **extra}]
```

---

## 2. `musicmind_agent/graph/nodes.py`

```python
"""八个节点。

【节点函数的签名是固定的】LangGraph 按 (state, config) 调用。
ctx 从 config 里取 —— 见 state.py 的说明，它不能进 state。
"""

from __future__ import annotations

import json
import time

from musicmind_agent.evidence import MIN_ARTISTS, MIN_TRACKS
from musicmind_agent.graph.state import (
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

    return {
        "user_id": ctx.evidence.user_id,
        "plan": {},
        "probes": [],
        "probe_count": 0,
        "probe_tokens": 0,
        "repair_count": 0,
        "degraded": False,
        "usage": {
            "insufficient": insufficient,
            "reason": (
                f"{len(tracks)} 首曲目 / {len(artists)} 位艺人"
                f"（门槛 {MIN_TRACKS} 首 / {MIN_ARTISTS} 位）"
            ) if insufficient else "",
        },
        "trace": trace(state, "resolve_user",
                       ms=int((time.monotonic() - started) * 1000),
                       note=f"{len(tracks)} 首 / {len(artists)} 位艺人"),
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

    return {
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
        return {
            "probe_count": state.get("probe_count", 0) + 1,
            "probe_tokens": state.get("probe_tokens", 0) + response.tokens_in,
            "usage": _add_usage(state, tokens_in=response.tokens_in, tokens_out=response.tokens_out),
            "trace": trace(state, "probe", ms=int((time.monotonic() - started) * 1000),
                           tokens_in=response.tokens_in, tokens_out=response.tokens_out,
                           note="模型认为够了"),
        }

    allowed = {t["name"] for t in catalog(tier=1)}
    ran: list[dict] = []
    for req in requests_[:3]:                      # 一轮最多跑 3 个，防止一口气烧光
        name = req.get("tool")
        if name not in allowed:
            # 编的工具名：记一条但不当错误 —— 它不影响报告的数字，只是少了一次探索
            ran.append({"tool": name, "ok": False, "error": "不在白名单里"})
            continue
        result = call(name, ctx, req.get("args") or {})
        ran.append({
            "tool": name,
            "args": req.get("args") or {},
            "ok": not result.warnings,
            # 只带 facts 的摘要进历史，不带 rows/evidence —— 那会把上下文撑爆
            "facts_digest": dict(list(result.facts.items())[:20]),
        })

    return {
        "probes": state.get("probes", []) + ran,
        "probe_count": state.get("probe_count", 0) + 1,
        "probe_tokens": state.get("probe_tokens", 0) + response.tokens_in,
        "usage": _add_usage(state, tokens_in=response.tokens_in, tokens_out=response.tokens_out),
        "trace": trace(state, "probe", ms=int((time.monotonic() - started) * 1000),
                       tokens_in=response.tokens_in, tokens_out=response.tokens_out,
                       note=f"跑了 {[r['tool'] for r in ran]}"),
    }


def route_after_probe(state: AgentState) -> str:
    """自环的出口。**两个上限都要有** ——
    只限次数的话，模型可以一轮塞十个调用；
    只限 token 的话，可能第一次就花光，一次补充查询都做不了。"""
    if state.get("probe_count", 0) >= MAX_PROBES:
        return "compose"
    if state.get("probe_tokens", 0) >= PROBE_TOKEN_BUDGET:
        return "compose"
    # 计划里指定的探针还没跑完，就再转一圈
    pending = [p for p in (state.get("plan", {}).get("probes") or [])
               if p not in {x["tool"] for x in state.get("probes", [])}]
    return "probe" if pending else "compose"


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
    candidates = call("similar_tracks", ctx, {"seed_track_ids": seeds, "limit": 30})

    messages = build_messages(ctx, candidates)
    raw, response = client.chat_json(messages)
    draft = ReportDraft.model_validate(raw).model_dump()

    return {
        "draft": draft,
        "rendered": _render(draft, ctx.facts),
        "usage": _add_usage(state, tokens_in=response.tokens_in, tokens_out=response.tokens_out),
        "trace": trace(state, "compose", ms=int((time.monotonic() - started) * 1000),
                       tokens_in=response.tokens_in, tokens_out=response.tokens_out),
    }


def _render(draft: dict, facts: dict) -> dict:
    """数字引用替换。**每个 LLM 写的字段都要过一遍** ——
    第一版漏了 limitations，那里面就带着花括号原样输出了。"""
    import copy

    data = copy.deepcopy(draft)
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
    data["limitations"] = [render_text(x, facts, strict=False) for x in data["limitations"]]
    return data


# ============================================================
# 6. validate —— 确定性，调 Phase 3
# ============================================================

def validate_node(state: AgentState, config) -> AgentState:
    started = time.monotonic()
    ctx = get_ctx(config)

    result = validate(state.get("rendered") or {}, ctx)

    return {
        "violations": [
            {"layer": v.layer, "path": v.path, "detail": v.detail, "severity": v.severity}
            for v in result.violations
        ],
        "trace": trace(state, "validate", ms=int((time.monotonic() - started) * 1000),
                       note=result.summary().splitlines()[0]),
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

    messages = build_messages(ctx, None) + [
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

    return {
        "draft": draft,
        "rendered": _render(draft, ctx.facts),
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
        kept_dims.append({**dim, "claims": claims})

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
        "rendered": degraded,
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
```

---

## 3. `musicmind_agent/graph/build.py`

```python
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
```

---

## 4. `musicmind_agent/graph/__init__.py`

```python
"""LangGraph 工作流。"""

from __future__ import annotations

from musicmind_agent.graph.build import build_graph

__all__ = ["build_graph", "run_report"]


def run_report(connection, user_id: int, provider: str, out_dir: str | None = None) -> dict:
    """跑一次完整流程。CLI 和测试都走这个入口。

    【ctx 和 client 必须在这里建好、invoke 时传进去】
    实测：config 在节点之间是只读的（节点里改了，下一个节点看不见），
    所以不能在第一个节点里懒建。而 ctx 里有数据库连接，又不能进 state
    （checkpoint 要序列化）。两边一夹，唯一的位置就是 config。
    """
    from musicmind_agent.llm import LLMClient
    from musicmind_agent.tools import build_context

    ctx = build_context(connection, user_id)
    app = build_graph()

    return app.invoke(
        {"user_id": user_id, "mode": "report"},
        config={"configurable": {
            "thread_id": f"report-{user_id}",
            "ctx": ctx,
            "client": LLMClient(provider=provider),
            "out_dir": out_dir,
        }},
    )
```

---

## 5. `cli.py` 加 `agent` 子命令

```python
def cmd_agent(args: argparse.Namespace) -> int:
    from musicmind_agent.graph import run_report

    connection = get_connection()
    try:
        final = run_report(connection, args.user, args.provider, args.out)
    except Exception as e:
        print(f"失败：{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        connection.close()

    usage = final.get("usage") or {}
    print(f"降级：{final.get('degraded', False)}   "
          f"修复轮次：{final.get('repair_count', 0)}   "
          f"探针：{final.get('probe_count', 0)}   "
          f"LLM 调用：{usage.get('llm_calls', 0)}")
    print(f"tokens in={usage.get('tokens_in', 0)} out={usage.get('tokens_out', 0)}")
    print()
    for step in final.get("trace", []):
        print(f"  {step['node']:16} {step.get('ms', 0):>6}ms  {step.get('note', '')}")

    if not final.get("rendered"):
        print("\n没有产出报告（数据不足或中途失败）")
        return 1
    return 0
```

加进 `main()`：

```python
    p_agent = sub.add_parser("agent", help="跑完整的 Agent 流程")
    p_agent.add_argument("--user", type=int, required=True)
    p_agent.add_argument("--provider", default="deepseek", choices=["deepseek", "qwen"])
    p_agent.add_argument("--out", help="产出目录（report.json + trace.jsonl）")
    p_agent.set_defaults(func=cmd_agent)
```

---

## 6. `tests/test_graph.py`

```python
"""图结构与路由的测试。

【只测确定性部分】节点的 LLM 行为要花真钱、有随机性，
那是 evals/run_eval.py 的事，不放进单测 —— 混进来的后果是没人愿意跑测试。
"""

from __future__ import annotations

import pytest

from musicmind_agent.graph import nodes
from musicmind_agent.graph.build import build_graph
from musicmind_agent.graph.state import MAX_PROBES, MAX_REPAIRS


def test_graph_compiles_without_checkpointer():
    assert build_graph(checkpoint=False) is not None


def test_all_nodes_registered():
    """节点名拼错不会在编译时报错，只会在运行时 KeyError。"""
    app = build_graph(checkpoint=False)
    expected = {"resolve_user", "plan", "run_core_tools", "probe", "compose",
                "validate", "repair", "fallback_render", "persist"}
    assert expected <= set(app.get_graph().nodes)


# ---------- 路由（纯函数，最好测的一层） ----------

@pytest.mark.parametrize("probe_count,expected", [
    (0, "probe"), (MAX_PROBES - 1, "probe"), (MAX_PROBES, "compose"),
])
def test_route_after_probe_stops_at_limit(probe_count, expected):
    state = {"probe_count": probe_count, "probe_tokens": 0,
             "probes": [], "plan": {"probes": ["search_tracks"]}}
    assert nodes.route_after_probe(state) == expected


def test_route_after_probe_stops_on_token_budget():
    """只限次数不够 —— 模型可以一轮塞十个调用烧光预算。"""
    state = {"probe_count": 1, "probe_tokens": 999999,
             "probes": [], "plan": {"probes": ["search_tracks"]}}
    assert nodes.route_after_probe(state) == "compose"


def test_route_after_probe_runs_planned_probes():
    """计划里指定了但还没跑的探针，要再转一圈。"""
    state = {"probe_count": 1, "probe_tokens": 0,
             "probes": [{"tool": "search_tracks"}],
             "plan": {"probes": ["search_tracks", "artist_deep_dive"]}}
    assert nodes.route_after_probe(state) == "probe"


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
    class FakeCtx: pass
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
```

---

## 怎么跑

```bash
cd agent-service

# 单测
.venv/Scripts/python.exe -m pytest -q

# 跑一次完整流程
.venv/Scripts/python.exe -m musicmind_agent.cli agent --user 34 --provider deepseek --out out/run-1
.venv/Scripts/python.exe -m musicmind_agent.cli agent --user 34 --provider qwen --out out/run-2

# 看 trace（每一步的耗时和 note）
cat out/run-1/trace.jsonl
```

---

## 验收标准

1. **单测全绿，且仍在 1 秒内**（LLM 调用不能进单测）
2. **两家各跑 3 次**，产出的 `trace.jsonl` 里能看到：`run_core_tools` → 若干 `probe` → `compose` → `validate`，每步有耗时
3. **repair 被真实触发至少一次**。做法：把 `MAX_REPAIRS` 临时改成 0，
   跑一次 qwen —— 它现在必然产出 `mood.arousal_measured_median` 那个违规，
   会直接走 fallback。确认 `degraded=true` 且 report.json 里没有花括号残留
4. **fallback 被真实触发至少一次**（同上，就是那条路径）
5. **数据不足守卫**：找一个个位数收藏的用户跑一次，
   应该直接结束、不产出报告、`usage.insufficient=true`
6. **10 次 p50/p95 延迟**（同一 provider 连跑 10 次，从 trace 里统计总耗时）。
   **这个数字决定 Phase 6 走同步接口还是 202+轮询** —— 所以必须真跑，不能估

---

## 五个坑

1. **`config` 在节点之间只读**（实测）。ctx 必须由调用方建好传进去。
2. **`SqliteSaver` 不支持 `with`**（实测）。连接自己管，别写出 `with SqliteSaver(...)`。
3. **连接不能进 state**。checkpoint 会 msgpack 序列化，连接序列化不了。
4. **probe 的历史里只带 facts 摘要**，不要带 rows/evidence —— 那个会撑爆上下文，
   而且和「证据 id 只能来自用户曲目」的约束打架。
5. **Windows 编码**：`trace.jsonl` 和 `report.json` 都显式 `encoding="utf-8"` +
   `ensure_ascii=False`。这个仓库已经踩过。

---

## 写完发我什么

1. `pytest -q` 输出
2. 两家的 `trace.jsonl`（我要看工具序列、耗时、tokens）
3. 故障注入那两次的结果（degraded=true 的 report.json）
4. **10 次延迟的 p50/p95**
5. 你在写的时候觉得哪条设计别扭 —— 尤其是 `route_after_probe` 那两个上限，
   它们是我拍的，你跑完真实数据可能觉得该调
