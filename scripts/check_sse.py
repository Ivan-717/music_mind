"""SSE 进度旁路的端到端验收：真发一轮 chat，边跑边收 stage 事件。

前提：后端 + agent-service 已按 docs/sse-handoff.md 改完并重启。
跑法：python scripts/check_sse.py

会花一轮真实 LLM（约 20-40 秒），并给测试账号 jj_cdfjsz 的会话留一条消息。
判据三条：
  1. SSE 端点返回 200（不是 404 —— 404 = Java 层还没上）
  2. 至少收到 1 个 stage 事件，且**第一个事件在 15 秒内到达**（这才是「流」；
     全在最后一起到 = flush/管道某处被缓冲了）
  3. 轮询通道最终拿到 DONE —— 兜底路径不回归（数据正确性不依赖 SSE）
"""

from __future__ import annotations

import json
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests

API = "http://localhost:8080/api"
USER, PWD = "jj_cdfjsz", "test12345678"

token = requests.post(f"{API}/auth/login",
                      json={"username": USER, "password": PWD},
                      timeout=10).json()["token"]
H = {"Authorization": f"Bearer {token}"}

print("1) 排一轮对话…")
r = requests.post(f"{API}/agent/chat",
                  json={"message": "推荐几首安静的", "conversationId": None},
                  headers=H, timeout=10)
r.raise_for_status()
run_id = r.json()["runId"]
print(f"   runId = {run_id}")

events: list[tuple[float, str]] = []
sse_status: list[int] = []


def collect():
    t0 = time.monotonic()
    try:
        with requests.get(f"{API}/agent/runs/{run_id}/stream",
                          headers=H, stream=True, timeout=120) as resp:
            sse_status.append(resp.status_code)
            if resp.status_code != 200:
                return
            cur_event = None
            # 【别用 decode_unicode=True】SSE 响应头不带 charset 时，requests
            # 会默认按 latin-1 解 —— 中文全变乱码（数据没错，看着错）。自己解。
            for raw in resp.iter_lines():
                line = raw.decode("utf-8", errors="replace").strip() if raw else ""
                if line.startswith("event:"):
                    cur_event = line[6:].strip()
                elif line.startswith("data:") and cur_event == "stage":
                    try:
                        note = json.loads(line[5:].strip()).get("note", "")
                        events.append((time.monotonic() - t0, note))
                    except json.JSONDecodeError:
                        pass
                elif line == "":
                    cur_event = None
    except Exception as e:
        print(f"   SSE 读取异常：{type(e).__name__}: {e}")


th = threading.Thread(target=collect, daemon=True)
th.start()

print("2) 等 run 收尾（轮询兜底通道）…")
status = None
deadline = time.monotonic() + 120
while time.monotonic() < deadline:
    try:
        d = requests.get(f"{API}/agent/runs/{run_id}", headers=H, timeout=10).json()
        status = d.get("run", {}).get("status")
        if status in ("DONE", "FAILED"):
            break
    except Exception:
        pass
    time.sleep(3)
th.join(timeout=5)

print()
print(f"3) 结果：SSE status = {sse_status and sse_status[0]}, "
      f"stage 事件 {len(events)} 个，轮询终态 = {status}")
for t, note in events:
    print(f"   [{t:6.1f}s] {note}")

ok_status = sse_status == [200]
ok_events = len(events) >= 1
ok_early = ok_events and events[0][0] < 15
ok_poll = status == "DONE"

print()
print(("PASS" if ok_status else "FAIL") + " 1: SSE 端点 200"
      + ("" if ok_status else f"（实际 {sse_status or '连不上'} —— Java 层还没上？）"))
print(("PASS" if ok_events else "FAIL") + " 2a: 收到 stage 事件")
print(("PASS" if ok_early else "FAIL") + " 2b: 第一个事件 15 秒内到达（真流式）")
print(("PASS" if ok_poll else "FAIL") + " 3: 轮询兜底拿到 DONE")

sys.exit(0 if (ok_status and ok_events and ok_early and ok_poll) else 1)
