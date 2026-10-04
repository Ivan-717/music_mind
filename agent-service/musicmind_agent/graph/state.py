"""图的状态。

【什么放 state、什么放 config】
    state  会被 checkpoint 序列化 —— 只能放可序列化的东西（dict/list/str/int）
    config 不进 checkpoint —— 放连接、上下文这类运行期依赖

放错的后果：连接进 state 会在 checkpoint 时报序列化错误；
本该进 state 的东西放 config，则追问时读不回上一轮的信息。
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

# 【主出口：连续几次探针没往 facts 仓加新东西就停】
# 「跑了几次」不是好信号 —— 跑了但没新信息才是该停的信号。
# 阈值取 2：一次空手可能是这个探针刚好不适用，连着两次空手就说明
# 剩下的维度在这个用户身上确实没有数据。
MAX_BARREN_PROBES = 2

# 【兜底上限】防跑飞，不是日常出口。
# 必须有，因为模型交替产出「有收获 / 没收获」时，上面的规则永远不会触发。
# 8 是宽裕值 —— 正常一两轮就该被 model_done 或 barren 停掉，
# 真跑满 8 轮说明模型在空转，那是行为问题不是阈值问题
MAX_PROBES = 8

# 同理，token 硬顶也是兜底。**不做「每千 token 新增 fact 数」那种比值阈值**：
# 第一轮探针要带上全部核心工具的上下文（贵），后面几轮便宜 ——
# 同一个比值在前后两轮的含义完全不同，阈值定不准，而且它会和
# MAX_BARREN_PROBES 打架（两个都判「值不值」，判据还不一样）

# 修复次数上限。超了就降级渲染而不是继续重试 ——
# 两次都改不对，说明问题不在措辞而在模型这轮就是不行，再试只是烧钱
MAX_REPAIRS = 2

# probe 循环的 token 预算。和次数上限配合使用（见 nodes.py 的说明）
PROBE_TOKEN_BUDGET = 40000


class AgentState(TypedDict, total=False):
    """图中的数据。全部可序列化。"""

    user_id: int
    mode: Literal["report", "ask"]

    # 工具产出（ToolResult.as_dict() 的合并）。compose / repair 都要用它 ——
    # 尤其是里面的 evidence，那是模型判断「哪些 track_id 能用」的唯一依据。
    # 存 dict 不存 ToolResult：state 要过 checkpoint 序列化
    tool_results: dict[str, dict]

    # --- 计划与探针 ---
    plan: dict[str, Any]          # plan 节点输出：{probes: [...], hypotheses: [...]}
    probes: list[dict]            # 每次探针调用：{tool, args, ok, facts_digest}
    probe_count: int
    probe_tokens: int             # probe 阶段累计消耗
    probe_barren: int             # 连续几次探针没新增事实（主出口的判据）
    model_done: bool              # 模型说「够了」

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