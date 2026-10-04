"""报告验证：五层确定性检查，零 LLM。

【为什么必须零 LLM】用 LLM 去验证 LLM，它的结论同样需要被验证 ——
防线退化成递归，而且你永远不知道哪一层的判断是可信的。
这里的每一条都是可以单测的纯逻辑。

【为什么是五层而不是一个大函数】每层的成本差一个数量级：
L1 只要一个正则，L5 要回查数据库。分层的意义是「便宜的足以定案时就不跑贵的」，
以及出错时能立刻说出是哪一类问题。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from musicmind_agent.tools import ToolContext

# 严重程度
#   error   报告不允许落库。Phase 4 会打回重写，重试失败则降级渲染
#   warning 记下来，但不阻断。通常是「可能有问题但无法机械判定」
ERROR = "error"
WARNING = "warning"


@dataclass
class Violation:
    layer: str        # structure / reference / literal / entity / evidence
    path: str         # 报告里的位置，如 dimensions[0].claims[1].text
    detail: str
    severity: str = ERROR


@dataclass
class ValidationResult:
    violations: list[Violation] = field(default_factory=list)
    checked: int = 0        # 检查了多少个断言（分母，让「0 违规」有意义）

    @property
    def errors(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == ERROR]

    @property
    def warnings(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == WARNING]

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        if self.ok and not self.warnings:
            return f"通过（检查了 {self.checked} 处）"
        parts = [f"检查 {self.checked} 处"]
        if self.errors:
            parts.append(f"违规 {len(self.errors)}")
        if self.warnings:
            parts.append(f"警告 {len(self.warnings)}")
        return "，".join(parts) + "\n" + "\n".join(
            f"  [{v.layer}] {v.path}: {v.detail}" for v in self.violations
        )


def validate(
    report: dict,
    ctx: ToolContext,
    candidate_ids: set[int] | None = None,
) -> ValidationResult:
    """跑全部五层。

    report        —— 渲染之后的报告 dict（数字已经替换成真值）
    ctx           —— 工具上下文：facts / 用户的曲目 / 连接
    candidate_ids —— 推荐候选的 id 池。传 None 就跳过「推荐是否来自候选池」这一项
    """
    from musicmind_agent.validate import checks

    result = ValidationResult()
    for layer_fn in (
        checks.check_structure,
        checks.check_references,
        checks.check_literals,
        checks.check_entities,
        checks.check_evidence,
    ):
        layer_fn(report, ctx, result, candidate_ids)
    return result


__all__ = ["Violation", "ValidationResult", "validate", "ERROR", "WARNING"]