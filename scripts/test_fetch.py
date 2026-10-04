"""M3：Agent 主动触发的按需入库 —— 端到端验证。

跑法（后端 8080 要在跑）：
    data-pipeline/.venv/Scripts/python.exe scripts/test_fetch.py

真跑 1 次 LLM（问一句库里没有的）。
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


def wait_run(h, run_id, limit=200):
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
    user = f"fe_{suffix}"
    ha = register(user)
    hb = register(f"fe_b_{suffix}")

    print("=== 0. 准备：导入一个歌单（对话要有数据）===")
    requests.post(f"{API}/import/playlist",
                  json={"url": HOT_URL, "favorite": False}, headers=ha).raise_for_status()

    print("\n=== 1. 问一个库里没有的（真跑一次 LLM）===")
    r = requests.post(f"{API}/agent/chat",
                      json={"message": "我想了解 Britpop，有什么推荐的吗"}, headers=ha)
    check("受理", r.status_code == 202, str(r.status_code))
    conv, run_id = r.json()["conversationId"], r.json()["runId"]
    final = wait_run(ha, run_id)
    check("回答完成", final.get("run", {}).get("status") == "DONE",
          final.get("run", {}).get("errorMessage") or "")

    msgs = final.get("messages") or []
    payload = json.loads(msgs[-1]["content"]) if msgs else {}
    props = payload.get("fetch_proposals") or []
    print(f"  答：{(payload.get('answer') or '')[:130]}")
    print(f"  提议 {len(props)} 张：")
    for p in props:
        print(f"    · {p.get('title')} / {p.get('artist')} ({p.get('year')})  {p['release_mbid'][:8]}")
    check("给出了抓取提议", len(props) > 0, str(len(props)))
    if not props:
        return
    check("提议不超过 5 张", len(props) <= 5, str(len(props)))
    check("每条都有 release_mbid", all(p.get("release_mbid") for p in props))
    check("回答里没有未渲染的占位符", "{" not in (payload.get("answer") or ""))
    # 【别只查 answer】第一版就漏了这里：why 里的 {era.2005.share} 原样输出了，
    # 而断言只看 answer，一路绿着过去
    check("每条提议的 why 也没有未渲染的占位符",
          all("{" not in (p.get("why") or "") for p in props),
          next((p.get("why") for p in props if "{" in (p.get("why") or "")), ""))

    print("\n=== 2. 越权 / 参数 ===")
    r = requests.post(f"{API}/agent/fetch",
                      json={"proposals": [{"releaseMbid": props[0]["release_mbid"]}]})
    check("未登录 → 401", r.status_code in (401, 403), str(r.status_code))
    r = requests.post(f"{API}/agent/fetch", json={"proposals": []}, headers=ha)
    check("空列表 → 400", r.status_code == 400, str(r.status_code))
    r = requests.post(f"{API}/agent/fetch", json={"proposals": [
        {"releaseMbid": f"00000000-0000-0000-0000-{i:012d}"} for i in range(6)
    ]}, headers=ha)
    check("超过 5 张 → 400", r.status_code == 400, str(r.status_code))

    print("\n=== 3. 抓进库里 ===")
    r = requests.post(f"{API}/agent/fetch",
                      json={"proposals": [{"releaseMbid": p["release_mbid"],
                                           "title": p["title"], "artist": p["artist"]}
                                          for p in props]}, headers=ha)
    check("POST /agent/fetch 返回 202", r.status_code == 202, str(r.status_code))
    if r.status_code != 202:
        print("   ", r.text[:200])
        return
    body = r.json()
    print(f"  排队 {body['queued']} 张，跳过 {body['skippedQueued']}，队列长 {body['queueCount']}")
    check("排进了队列", body["queued"] > 0, str(body))
    check("返回了 importId", isinstance(body.get("importId"), int), str(body))
    check("没有重复排", body["queued"] + body["skippedQueued"] == len(props), str(body))

    print("\n=== 4. 落点是一张「AI 帮你找的」歌单 ===")
    imports = requests.get(f"{API}/import/playlists", headers=ha).json()
    ai = next((x for x in imports if x.get("provider") == "agent"), None)
    check("出现了 provider=agent 的歌单", ai is not None,
          str([(x.get("provider"), x.get("playlistName")) for x in imports]))
    if ai:
        check("名字是「AI 帮你找的」", ai["playlistName"] == "AI 帮你找的", ai["playlistName"])
        rows = requests.get(f"{API}/import/playlists/{ai['id']}/tracks",
                            params={"page": 1, "size": 50}, headers=ha).json()
        check("里面就是刚提议的那几张",
              rows["total"] == len(props), f"{rows['total']} vs {len(props)}")

    print("\n=== 5. 越权：B 看不到 A 的这张歌单 ===")
    if ai:
        r = requests.get(f"{API}/import/playlists/{ai['id']}/tracks", headers=hb)
        check("B 读 A 的 AI 歌单 → 404", r.status_code == 404, str(r.status_code))
        b_imports = requests.get(f"{API}/import/playlists", headers=hb).json()
        check("B 的列表里没有它", all(x["id"] != ai["id"] for x in b_imports))

    print("\n=== 6. 同一张别重复排 ===")
    r = requests.post(f"{API}/agent/fetch",
                      json={"proposals": [{"releaseMbid": props[0]["release_mbid"],
                                           "title": props[0]["title"],
                                           "artist": props[0]["artist"]}]}, headers=ha)
    check("第二次排 queued=0", r.json()["queued"] == 0, str(r.json()))
    check("计入 skippedQueued", r.json()["skippedQueued"] == 1, str(r.json()))

    print("\n" + "=" * 60)
    print(f"通过 {len(PASSED)} / 失败 {len(FAILED)}")
    for name in FAILED:
        print(f"  FAILED: {name}")
    print("=" * 60)


if __name__ == "__main__":
    main()
