"""跑几次，把第一次 validate 的违规按「层 + 类别」统计。"""
import sys
from collections import Counter
from musicmind_agent.db import get_connection
from musicmind_agent import graph
from musicmind_agent.graph import nodes
from musicmind_agent.validate import validate as real_validate

buckets = Counter(); samples = {}
first_round = {"n": 0}

def spy(report, ctx, candidate_ids=None):
    result = real_validate(report, ctx, candidate_ids)
    if first_round["n"] < runs:
        first_round["n"] += 1
        for v in result.violations:
            if v.severity != "error":
                continue
            if "不存在的事实" in v.detail:      key = f"{v.layer} / 编造事实名"
            elif "不是用户的歌" in v.detail:    key = f"{v.layer} / 证据越界"
            elif "锚点" in v.detail:            key = f"{v.layer} / 锚点越界"
            elif "既没有引用事实" in v.detail:  key = f"{v.layer} / 空口断言"
            elif "绑不到" in v.detail:          key = f"{v.layer} / 裸数字绑不上"
            else:                              key = f"{v.layer} / 其他"
            buckets[key] += 1
            samples.setdefault(key, v.detail)
    return result

nodes.validate = spy
runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
for i in range(runs):
    connection = get_connection()
    try:
        graph.run_report(connection, 34, "deepseek", None)
    finally:
        connection.close()
    print(f"  跑完第 {i+1} 次")

print(f"\n{runs} 次运行的违规分布：")
for key, n in buckets.most_common():
    print(f"  {n:3}  {key}")
    print(f"       例：{samples[key][:110]}")
