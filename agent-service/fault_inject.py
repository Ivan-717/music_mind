"""故障注入：验证 repair 和 fallback 两条路径真的能跑通。

一条从没被触发过的降级路径等于没有 —— 所以这里主动让它必然失败。
"""
import json, sys
import musicmind_agent.graph.nodes as nodes
import musicmind_agent.validate.checks as checks
from musicmind_agent.validate import ERROR, Violation
from musicmind_agent.db import get_connection
from musicmind_agent.graph import run_report

# 注入一条【永远修不掉】的违规 —— 不管模型怎么改，它都会再出现。
# 这样路由必然走满 repair 次数然后降级，两条路径一次测到
original = checks.check_structure
def broken(report, ctx, result, candidate_ids=None):
    original(report, ctx, result, candidate_ids)
    result.violations.append(Violation(
        layer="structure", path="injected", detail="故障注入：这条永远修不掉"))
checks.check_structure = broken

nodes.MAX_REPAIRS = 1          # 只修一次就放弃，省一轮 LLM

connection = get_connection()
try:
    final = run_report(connection, 34, "deepseek", "out/run-fault")
finally:
    connection.close()

print("降级：", final.get("degraded"))
print("修复轮次：", final.get("repair_count"))
print()
for step in final.get("trace", []):
    print(f"  {step['node']:16} {step.get('ms',0):>6}ms  {step.get('note','')}")

rendered = json.dumps(final.get("rendered") or {}, ensure_ascii=False)
print()
print("降级报告里还有花括号吗：", "{" in rendered)
