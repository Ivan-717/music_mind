"""M4：把推荐存成歌单 —— 端到端验证。

跑法（后端 8080 要在跑）：
    data-pipeline/.venv/Scripts/python.exe scripts/test_playlist.py

真跑 1 次 LLM（问一句要推荐）。
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


def main():
    suffix = "".join(random.choices(string.ascii_lowercase, k=6))
    ha = register(f"pl_a_{suffix}")
    hb = register(f"pl_b_{suffix}")

    print("=== 0. 准备：导入一个歌单（对话要有数据）===")
    requests.post(f"{API}/import/playlist",
                  json={"url": HOT_URL, "favorite": False}, headers=ha).raise_for_status()

    print("\n=== 1. 让 Agent 给一批推荐（真跑一次 LLM）===")
    r = requests.post(f"{API}/agent/chat",
                      json={"message": "推荐几首安静的"}, headers=ha)
    check("受理", r.status_code == 202, str(r.status_code))
    run_id = r.json()["runId"]
    deadline = time.time() + 180
    final = {}
    while time.time() < deadline:
        final = requests.get(f"{API}/agent/runs/{run_id}", headers=ha).json()
        if final.get("run", {}).get("status") in ("DONE", "FAILED"):
            break
        time.sleep(3)
    check("回答完成", final.get("run", {}).get("status") == "DONE",
          final.get("run", {}).get("errorMessage") or "")

    msgs = final.get("messages") or []
    payload = json.loads(msgs[-1]["content"]) if msgs else {}
    recs = payload.get("recommendations") or []
    ids = [x["track_id"] for x in recs if x.get("track_id")]
    print(f"  推荐 {len(recs)} 条，track_id 有效 {len(ids)} 个")
    check("拿到了推荐", len(ids) > 0, str(len(ids)))
    if not ids:
        return

    print("\n=== 2. 存成歌单 ===")
    r = requests.post(f"{API}/playlists/from-tracks",
                      json={"name": "深夜写代码", "trackIds": ids}, headers=ha)
    check("POST /playlists/from-tracks 返回 201", r.status_code == 201, str(r.status_code))
    if r.status_code != 201:
        print("   ", r.text[:200])
        return
    body = r.json()
    print(f"  建了 {body['id']}《{body['name']}》灌了 {body['added']} 首，跳过 {body['skipped']}")
    pid = body["id"]
    check("全部灌进去了", body["added"] == len(ids), str(body))
    check("返回了歌单 id", isinstance(pid, int), str(body))

    print("\n=== 3. 歌单真的在（读的是现成那套接口）===")
    mine = requests.get(f"{API}/playlists", headers=ha).json()
    check("我的歌单里有它", any(x["id"] == pid for x in mine), str(len(mine)))
    tracks = requests.get(f"{API}/playlists/{pid}/tracks", headers=ha).json()
    check("曲目数对得上", len(tracks) == len(ids), f"{len(tracks)} vs {len(ids)}")
    check("曲目带歌名（不是裸 id）",
          bool(tracks) and bool(tracks[0].get("name")), str(tracks[0])[:80] if tracks else "")

    print("\n=== 4. 脏 id 跳过，不是整张失败 ===")
    r = requests.post(f"{API}/playlists/from-tracks",
                      json={"name": "带脏数据", "trackIds": ids[:1] + [99999999]}, headers=ha)
    check("还是 201", r.status_code == 201, str(r.status_code))
    if r.status_code == 201:
        check("存在的灌进去了", r.json()["added"] == 1, str(r.json()))
        check("不存在的计入 skipped", r.json()["skipped"] == 1, str(r.json()))

    print("\n=== 5. 参数校验 ===")
    r = requests.post(f"{API}/playlists/from-tracks",
                      json={"name": "", "trackIds": ids[:1]}, headers=ha)
    check("空名字 → 400", r.status_code == 400, str(r.status_code))
    r = requests.post(f"{API}/playlists/from-tracks",
                      json={"name": "太多", "trackIds": list(range(1, 200))}, headers=ha)
    check("超过 100 首 → 400", r.status_code == 400, str(r.status_code))
    r = requests.post(f"{API}/playlists/from-tracks",
                      json={"name": "没有歌", "trackIds": []}, headers=ha)
    check("空列表 → 400", r.status_code == 400, str(r.status_code))

    print("\n=== 6. 越权 ===")
    r = requests.get(f"{API}/playlists/{pid}/tracks", headers=hb)
    check("B 读 A 的歌单 → 404", r.status_code == 404, str(r.status_code))
    b_mine = requests.get(f"{API}/playlists", headers=hb).json()
    check("B 的列表里没有它", all(x["id"] != pid for x in b_mine))
    r = requests.post(f"{API}/playlists/from-tracks",
                      json={"name": "x", "trackIds": ids[:1]})
    check("未登录 → 401", r.status_code in (401, 403), str(r.status_code))

    print("\n" + "=" * 60)
    print(f"通过 {len(PASSED)} / 失败 {len(FAILED)}")
    for name in FAILED:
        print(f"  FAILED: {name}")
    print("=" * 60)


if __name__ == "__main__":
    main()
