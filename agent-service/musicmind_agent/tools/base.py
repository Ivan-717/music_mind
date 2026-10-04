"""工具契约。

所有工具返回同一个形状，规矩只有三条，但每条都有代价：

  1. **facts 用扁平的 dotted key，值必须是原始数值**
     {"genre.mandopop.share": 0.373}
     报告里的数字只能以 metric_ref 的形式引用这些 key，渲染时才替换成真值。
     这样「编造一个数字」在结构上就写不出来，而不是靠事后扫描去抓。

  2. **coverage 必填**
     84.3% 的覆盖率意味着每个百分比都要写明分母。没有 coverage 的百分比
     不允许出现在报告里 —— 否则「37% 是 mandopop」听起来很确定，
     实际上是在 413 首歌上算的，还有 77 首根本没流派。

  3. **evidence 有预算**
     每个分组最多 5 个 track_id，单次调用总量 ≤ 30。
     证据是「这个结论能指回哪几首具体的歌」，不是把歌单倒给 LLM。

工具层必须是 100% 确定性的：不调 LLM、不做模糊推断。
只要工具能返回 LLM 生成的东西，幻觉防治就全废了。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from musicmind_agent.evidence import EnrichedTrack, EvidenceSet

# 证据预算。写死在这里是为了让「工具返回了多少东西」是个常量，
# 而不是每个工具自己拿捏 —— 拿捏的结果一定是越给越多
MAX_EVIDENCE_PER_GROUP = 5
MAX_EVIDENCE_TOTAL = 30


@dataclass
class ToolResult:
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    facts: dict[str, float | int | str] = field(default_factory=dict)
    rows: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    elapsed_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "args": self.args,
            "facts": self.facts,
            "rows": self.rows,
            "evidence": self.evidence,
            "coverage": self.coverage,
            "warnings": self.warnings,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass
class ToolContext:
    """一次工具调用能拿到的东西。

    数据在 build_context 里一次取全，工具只做聚合 —— 这样就不会出现
    「同一个分母在五个工具里算法不一样」，也不会每个工具各查一遍库。
    """

    connection: Any
    evidence: EvidenceSet
    tracks: list[EnrichedTrack]
    # 流派 → {arousal, valence, confidence, weight}。weight 由置信度映射而来，
    # 用来压低宽流派（mandopop 这类）在推断里的发言权
    mood_map: dict[str, dict[str, Any]] = field(default_factory=dict)
    # 全库的流派分布，taste_diversity 算 KL 偏离要用
    library_genre_counts: dict[str, int] = field(default_factory=dict)
    facts: dict[str, float | int | str] = field(default_factory=dict)

    def fact(self, key: str, value: float | int | str) -> None:
        """登记一条事实。key 必须是 dotted 形式，且不能被重复写。

        重复写同一个 key 是 bug：要么两个工具的命名撞了，要么同一个工具
        在同一批数据上算出了两个值 —— 两种都会让报告引用到不确定的数字。
        """
        if "." not in key:
            raise ValueError(f"fact key 必须是 dotted 形式（domain.name.field）：{key}")
        if key in self.facts and self.facts[key] != value:
            raise ValueError(f"fact key 冲突：{key} = {self.facts[key]!r} / {value!r}")
        self.facts[key] = value

    def evidence_for(self, track: EnrichedTrack, why: str) -> dict[str, Any]:
        return {
            "track_id": track.track_id,
            "name": track.track_name,
            "artist": track.artist_name,
            "why": why,
        }


def cov(considered: int, with_attribute: int, note: str = "") -> dict[str, Any]:
    """覆盖率。每个工具都必须给。"""
    ratio = (with_attribute / considered) if considered else 0.0
    return {
        "considered": considered,
        "with_attribute": with_attribute,
        "ratio": round(ratio, 4),
        "note": note,
    }


def cap_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return items[:MAX_EVIDENCE_TOTAL]


@dataclass
class Tool:
    name: str
    tier: int                  # 0 核心（每次必跑）/ 1 探针（LLM 选）/ 2 支撑
    description: str
    params: dict[str, str]
    run: Callable[[ToolContext, dict[str, Any]], ToolResult]

    def catalog_entry(self) -> dict[str, Any]:
        """给 LLM 看的工具目录。**Tier 0 不给 LLM 选**（每次都无条件跑），
        所以目录里只列 Tier 1，避免把「选不选」这种不确定性引进来。"""
        return {"name": self.name, "description": self.description, "params": self.params}


REGISTRY: dict[str, Tool] = {}


def register(name: str, tier: int, description: str, params: dict[str, str] | None = None):
    def wrap(fn):
        REGISTRY[name] = Tool(
            name=name, tier=tier, description=description,
            params=params or {}, run=fn,
        )
        return fn
    return wrap


def call(name: str, ctx: ToolContext, args: dict[str, Any] | None = None) -> ToolResult:
    """执行一个工具。**工具抛异常不该终止整个流程** —— 记成一个空结果 +
    warning，让 Agent 知道这条路走不通，而不是整个报告崩掉。"""
    tool = REGISTRY.get(name)
    if tool is None:
        return ToolResult(tool=name, warnings=[f"没有这个工具：{name}"])

    started = time.monotonic()
    try:
        result = tool.run(ctx, args or {})
    except Exception as e:
        result = ToolResult(tool=name, args=args or {}, warnings=[f"执行失败：{type(e).__name__}: {e}"])

    result.tool = name
    result.args = args or {}
    result.elapsed_ms = int((time.monotonic() - started) * 1000)

    # 把工具产出的事实登记进全局仓。
    #
    # 【为什么放在 call() 里，而不是让每个工具自己调 ctx.fact()】
    # 靠自觉的事情一定会漏 —— 实测：6 个核心工具里只有 1 个登记了，
    # 结果是报告里 29 个占位符渲染不出来，整份报告的数字全是 {xxx} 原样。
    # 放在这里，所有工具（包括以后新加的）自动遵守，不需要谁记得。
    for key, value in result.facts.items():
        try:
            ctx.fact(key, value)
        except ValueError as e:
            # 两个工具用了同一个 key 但值不同 = 报告引用到不确定的数字。
            # 记成 warning 而不是抛异常：一个工具的命名冲突不该让整份报告失败，
            # 但必须留下痕迹让验证器能发现
            result.warnings.append(f"事实仓冲突：{e}")

    return result


def catalog(tier: int | None = None) -> list[dict[str, Any]]:
    return [
        t.catalog_entry()
        for t in REGISTRY.values()
        if tier is None or t.tier == tier
    ]


def core_tool_names() -> list[str]:
    return [t.name for t in REGISTRY.values() if t.tier == 0]
