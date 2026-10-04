"""音乐探索（对话）的端到端验证。

跑法（后端 8080 要在跑）：
    data-pipeline/.venv/Scripts/python.exe scripts/test_chat.py

真跑 1 次 LLM（一轮对话）。
"""

import json
import random
import string
import sys
import time

import requests

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

API = "http://localhost:8080/api"
PASSWORD = "test12345678"
HOT_URL = "https://music.163.com/playlist?id=3778678"

PASSED, FAILED = [], []


def check(label, ok, extra=""):
    (PASSED if ok else FAILED).append(label)
    print(("  PASS " if ok else "  FAIL ") + label + (f"   {extra}" if extra else ""))


def register(name):
    requests.post(f"{API}/auth/register", json={
        "username": name, "password": PASSWORD, "nickname": name,
        "email": f"{name}@example.com"}).raise_for_status()
    return {"Authorization": "Bearer " + requests.post(
        f"{API}/auth/login", json={"username": name, "password": PASSWORD}
    ).json()["token"]}


def wait_run(h, run_id, limit=180):
    deadline = time.time() + limit
    last = None
    while time.time() < deadline:
        last = requests.get(f"{API}/agent/runs/{run_id}", headers=h).json()
        if last.get("run", {}).get("status") in ("DONE", "FAILED"):
            return last
        time.sleep(3)
    return last


def main():
    suffix = "".join(random.choices(string.ascii_lowercase, k=6))
    ha = register(f"ch_a_{suffix}")
    hb = register(f"ch_b_{suffix}")

    print("=== 0. 准备：A 导入一个歌单（对话要有数据）===")
    requests.post(f"{API}/import/playlist",
                  json={"url": HOT_URL, "favorite": False}, headers=ha).raise_for_status()
    print("  导入完成")

    print("\n=== 1. 新开一个会话 ===")
    r = requests.post(f"{API}/agent/chat",
                      json={"message": "我听得最多的是什么流派？"}, headers=ha)
    check("POST /agent/chat 返回 202", r.status_code == 202, str(r.status_code))
    body = r.json()
    check("返回 runId", isinstance(body.get("runId"), int), str(body))
    conv = body.get("conversationId")
    check("返回 conversationId", isinstance(conv, int), str(body))
    if not conv:
        return
    run_id = body["runId"]

    print("\n=== 2. 越权 ===")
    r = requests.get(f"{API}/agent/conversations/{conv}", headers=hb)
    check("B 读 A 的会话 → 404", r.status_code == 404, str(r.status_code))
    r = requests.post(f"{API}/agent/chat",
                      json={"message": "hi", "conversationId": conv}, headers=hb)
    check("B 往 A 的会话里发消息 → 404", r.status_code == 404, str(r.status_code))
    r = requests.get(f"{API}/agent/conversations/{conv}")
    check("未登录读会话 → 401", r.status_code in (401, 403), str(r.status_code))

    print("\n=== 3. 等回答 ===")
    started = time.time()
    final = wait_run(ha, run_id)
    run = final.get("run", {})
    print(f"  耗时 {time.time()-started:.0f}s  状态 {run.get('status')}")
    check("回答完成（DONE）", run.get("status") == "DONE",
          run.get("errorMessage") or "")

    msgs = final.get("messages") or []
    check("落了 2 条消息（问 + 答）", len(msgs) == 2, str(len(msgs)))
    if len(msgs) != 2:
        return

    check("第一条是用户问的", msgs[0]["role"] == "user", msgs[0]["content"][:30])
    check("第二条是回答", msgs[1]["role"] == "assistant")

    payload = json.loads(msgs[1]["content"])
    answer = payload.get("answer") or ""
    print(f"  答：{answer[:120]}")
    check("回答非空", len(answer) > 10)
    check("回答里没有未渲染的占位符", "{" not in answer)
    check("回答里没有开发语境的词（M1/语料/评估）",
          not any(w in answer for w in ("M1", "M2", "语料", "prompt", "占位符")), answer[:60])

    print("\n=== 4. 刷新页面读回历史 ===")
    r = requests.get(f"{API}/agent/conversations/{conv}", headers=ha)
    check("GET /agent/conversations/{id} 返回 200", r.status_code == 200, str(r.status_code))
    if r.status_code == 200:
        d = r.json()
        check("带 conversation", bool(d.get("conversation")))
        check("带 2 条消息", len(d.get("messages") or []) == 2, str(len(d.get("messages") or [])))

    print("\n=== 5. 会话列表 ===")
    r = requests.get(f"{API}/agent/conversations", headers=ha)
    check("列表返回 200", r.status_code == 200, str(r.status_code))
    items = r.json()
    check("列表里有刚开那个", any(x["id"] == conv for x in items), str(len(items)))
    check("列表不含消息正文", all("content" not in x for x in items))
    check("标题取的是第一句", items[0].get("title", "").startswith("我听得最多"),
          str(items[0].get("title")))

    print("\n=== 6. 库里没有的要说不知道（再跑一次 LLM）===")
    r = requests.post(f"{API}/agent/chat",
                      json={"message": "推荐几首 Radiohead 的歌",
                            "conversationId": conv}, headers=ha)
    final2 = wait_run(ha, r.json()["runId"])
    msgs2 = final2.get("messages") or []
    last = json.loads(msgs2[-1]["content"]) if msgs2 else {}
    print(f"  答：{(last.get('answer') or '')[:140]}")
    check("推荐列表为空", not (last.get("recommendations") or []),
          str(len(last.get("recommendations") or [])))
    check("没有「据我所知」这类没有来源的话",
          "据我所知" not in (last.get("answer") or ""))

    print("\n" + "=" * 60)
    print(f"通过 {len(PASSED)} / 失败 {len(FAILED)}")
    for name in FAILED:
        print(f"  FAILED: {name}")
    print("=" * 60)


if __name__ == "__main__":
    main()
