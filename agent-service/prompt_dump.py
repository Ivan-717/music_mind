"""同一次运行里：dump 发给模型的 prompt + 验证产出的报告。"""
import json
from musicmind_agent.llm import LLMClient
from musicmind_agent.db import get_connection
from musicmind_agent.evidence import resolve_user
from musicmind_agent.graph import run_report

original = LLMClient.chat_json
calls = []

def spy(self, messages):
    calls.append("\n".join(m["content"] for m in messages))
    return original(self, messages)

LLMClient.chat_json = spy

connection = get_connection()
user_ids = set(resolve_user(connection, 34).all_ids)
try:
    final = run_report(connection, 34, "deepseek", None)
finally:
    connection.close()

render = final.get("rendered") or {}
compose_prompt = calls[2] if len(calls) > 2 else ""

print("compose 的 prompt 里出现 16270 次数:", compose_prompt.count("16270"))
print()
print("报告里用到的证据 id（不是用户的会标 ✗）:")
bad = []
for d in render.get("dimensions", []):
    for c in d.get("claims", []):
        for t in c.get("evidence_track_ids", []):
            mark = "✓" if t in user_ids else "✗"
            if mark == "✗":
                bad.append(t)
print("  越界证据:", bad or "无")
print()
print("prompt 里出现的、像 track id 的数字（10000 以上的）:")
import re
big = sorted({int(x) for x in re.findall(r"\b(\d{5,6})\b", compose_prompt)})
print("  ", big[:15])
print()
print("越界的那些 id 在 prompt 里吗:", {b: compose_prompt.count(str(b)) for b in bad[:5]})
