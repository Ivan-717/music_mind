"""按需入库（③）的端到端验证。

跑法（后端要已经在 8080 上跑着）：
    data-pipeline/.venv/Scripts/python.exe logs/test_ingestion.py
"""

import random
import string
import sys
import time

import pymysql
import requests

sys.path.insert(0, "data-pipeline")
from config.settings import MYSQL_CONFIG  # noqa: E402

BASE = "http://localhost:8080/api"
PASSWORD = "test12345678"
HOT_URL = "https://music.163.com/playlist?id=3778678"   # 网易云热歌榜

# 【筛选口径】不只是「MusicBrainz 上有这首歌」，还得「这首歌挂在某张 release 上」。
# 实测郑润泽《如果呢》《于是》：标题艺人精确命中，但 releases 为空（独立录音），
# 抓不了，会得到 NOT_FOUND——那是正确结果，但测不出「抓取成功」那条路径。
CANDIDATES = ["我不难过", "甲乙丙丁 (你我怎么两清)", "恋人", "两 难",
              "我怀念的", "出现又离开 (Live)", "开始懂了", "小半",
              "愿与愁", "刻在我心底的名字"]

PASSED = []
FAILED = []


def check(label, ok, extra=""):
    (PASSED if ok else FAILED).append(label)
    print(("  PASS " if ok else "  FAIL ") + label + (f"   {extra}" if extra else ""))


def db():
    return pymysql.connect(**{**MYSQL_CONFIG, "autocommit": True})


def register(username):
    r = requests.post(f"{BASE}/auth/register", json={
        "username": username, "password": PASSWORD,
        "nickname": username, "email": f"{username}@example.com"})
    assert r.status_code == 201, r.text


def login(username):
    r = requests.post(f"{BASE}/auth/login",
                      json={"username": username, "password": PASSWORD})
    r.raise_for_status()
    return {"Authorization": f"Bearer {r.json()['token']}"}


def import_hot(headers):
    r = requests.post(f"{BASE}/import/playlist",
                      json={"url": HOT_URL, "favorite": False}, headers=headers)
    r.raise_for_status()
    return r.json()


def tracks(headers, import_id, size=200):
    r = requests.get(f"{BASE}/import/playlists/{import_id}/tracks",
                     params={"page": 1, "size": size}, headers=headers)
    r.raise_for_status()
    return r.json()


def row_of(headers, import_id, title):
    for item in tracks(headers, import_id)["items"]:
        if item["title"] == title:
            return item
    return None


def status(headers):
    r = requests.get(f"{BASE}/ingestion/status", headers=headers)
    r.raise_for_status()
    return r.json()


def wait_for_idle(headers, timeout=180):
    """等到队列空且没有正在跑的任务"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        s = status(headers)
        last = s
        if s["queueCount"] == 0 and s["currentJobId"] is None:
            return s
        time.sleep(2)
    return last


def main():
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    user_a, user_b = f"ing_a_{suffix}", f"ing_b_{suffix}"
    register(user_a)
    register(user_b)
    ha, hb = login(user_a), login(user_b)

    print("\n=== 1. 准备：A 导入热歌榜 ===")
    result = import_hot(ha)
    import_id = result["importId"] if "importId" in result else None
    if import_id is None:
        # 导入接口不返回 importId，从列表拿
        import_id = requests.get(f"{BASE}/import/playlists", headers=ha).json()[0]["id"]
    print(f"  歌单 id={import_id} 解析 {result['parsed']} 首，已对上 {result['matched']} 首")

    target, title = None, None
    for name in CANDIDATES:
        row = row_of(ha, import_id, name)
        if row is not None and row["matchedTrackId"] is None:
            target, title = row, name
            break
    check("热歌榜里有还没入库的候选曲目", target is not None,
          f"可用候选={CANDIDATES}")
    if target is None:
        return
    row_id = target["id"]
    print(f"  目标：《{title}》 行 id={row_id}")
    check("这一行当前是未对齐", target["matchedTrackId"] is None,
          f"status={target['matchStatus']}")

    print("\n=== 2. 逐首入库 ===")
    r = requests.post(f"{BASE}/ingestion/tracks",
                      json={"trackRowIds": [row_id]}, headers=ha)
    check("POST /ingestion/tracks 返回 202", r.status_code == 202, str(r.status_code))
    body = r.json()
    check("排进队列 1 首", body["queued"] == 1, str(body))
    check("返回预估耗时", body["estimateSeconds"] > 0, str(body["estimateSeconds"]))

    print("\n=== 3. 重复排队被去重 ===")
    r = requests.post(f"{BASE}/ingestion/tracks",
                      json={"trackRowIds": [row_id]}, headers=ha)
    body = r.json()
    check("第二次排队 queued=0", body["queued"] == 0, str(body))
    check("计入 skippedQueued", body["skippedQueued"] == 1, str(body))

    print("\n=== 4. 越权：B 排 A 的行 ===")
    r = requests.post(f"{BASE}/ingestion/tracks",
                      json={"trackRowIds": [row_id]}, headers=hb)
    check("B 排 A 的曲目行 → 404", r.status_code == 404, str(r.status_code))
    r = requests.post(f"{BASE}/ingestion/playlists/{import_id}", headers=hb)
    check("B 排 A 的整单 → 404", r.status_code == 404, str(r.status_code))
    r = requests.get(f"{BASE}/ingestion/status")
    check("未登录访问 status → 401/403", r.status_code in (401, 403), str(r.status_code))

    print("\n=== 5. 等 worker 跑完 ===")
    started = time.time()
    s = wait_for_idle(ha)
    job = next((j for j in s["recentJobs"] if j["trackRowId"] == row_id), None)
    check("任务有记录", job is not None)
    if job:
        print(f"  状态={job['status']} release={job['releaseMbid']} "
              f"重对齐={job['rematchedCount']} 耗时={time.time()-started:.1f}s")
        check("任务成功（DONE）", job["status"] == "DONE",
              job.get("errorMessage") or "")
        check("解析出了 release MBID", bool(job["releaseMbid"]))

    print("\n=== 6. 入库后那一行变成可收藏 ===")
    after = row_of(ha, import_id, title)
    check("match_status 变成 MATCHED", after["matchStatus"] == "MATCHED",
          f"status={after['matchStatus']}")
    check("matcherTrackId 有值", after["matchedTrackId"] is not None)

    if after["matchedTrackId"]:
        r = requests.post(f"{BASE}/favorites/batch",
                          json={"trackIds": [after["matchedTrackId"]]}, headers=ha)
        check("入库后的歌能收藏", r.status_code == 200 and r.json()["changed"] == 1,
              r.text[:120])

    print("\n=== 7. NOT_FOUND 路径 ===")
    with db() as conn, conn.cursor() as cur:
        cur.execute("""
            INSERT INTO user_playlist_track
                (import_id, user_id, provider, external_id, position, title, artists,
                 album_name, duration_ms, match_status)
            SELECT %s, user_id, provider, %s, 9999, %s, %s, NULL, NULL, 'UNRESOLVED'
            FROM user_playlist_import WHERE id = %s
            """, (import_id, f"bogus{suffix}", "zzzzzz不存在xyz", "zzzzzz不存在xyz", import_id))
        cur.execute("SELECT id FROM user_playlist_track WHERE external_id = %s",
                    (f"bogus{suffix}",))
        bogus_row = cur.fetchone()["id"]

    r = requests.post(f"{BASE}/ingestion/tracks",
                      json={"trackRowIds": [bogus_row]}, headers=ha)
    check("脏数据行也能排队", r.json()["queued"] == 1, str(r.json()))
    s = wait_for_idle(ha)
    bogus_job = next((j for j in s["recentJobs"] if j["trackRowId"] == bogus_row), None)
    check("列为 NOT_FOUND", bogus_job and bogus_job["status"] == "NOT_FOUND",
          str(bogus_job and bogus_job["status"]))
    check("带了原因说明", bool(bogus_job and bogus_job["errorMessage"]),
          str(bogus_job and bogus_job["errorMessage"]))

    print("\n=== 8. 停止 / 恢复 ===")
    r = requests.post(f"{BASE}/ingestion/stop", headers=ha)
    check("stop 之后 paused=true", r.json()["paused"] is True, str(r.json())[:80])
    r = requests.post(f"{BASE}/ingestion/resume", headers=ha)
    check("resume 之后 paused=false", r.json()["paused"] is False, str(r.json())[:80])

    print("\n=== 9. 防降级：重新导入同一歌单，已对上的一行不能掉回未对齐 ===")
    before = row_of(ha, import_id, title)["matchStatus"]
    import_hot(ha)
    after = row_of(ha, import_id, title)["matchStatus"]
    check("重导入后仍是 MATCHED", before == "MATCHED" and after == "MATCHED",
          f"{before} → {after}")

    print("\n=== 10. 整单排队 ===")
    r = requests.post(f"{BASE}/ingestion/playlists/{import_id}", headers=ha)
    check("整单排队返回 202", r.status_code == 202, str(r.status_code))
    body = r.json()
    print(f"  提交={body['total']} 排队={body['queued']} "
          f"已对上跳过={body['skippedAlreadyMatched']} 重复跳过={body['skippedQueued']} "
          f"脏数据={body['skippedInvalid']} 队列长={body['queueCount']} "
          f"预估={body['estimateSeconds']}s")
    check("整单把未对齐的都排进去了", body["queued"] > 100, str(body["queued"]))
    # queueCount 只数 QUEUED。单 worker 会立刻领走一条变成 RUNNING（不算在内），
    # 所以差 1 是正常的，不是漏排
    check("队列长度对得上", body["queueCount"] >= body["queued"] - 1,
          f"queued={body['queued']} queueCount={body['queueCount']}")

    # 别让两百首真跑完——停掉并清队列
    requests.post(f"{BASE}/ingestion/stop", headers=ha)
    with db() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM ingestion_job WHERE status = 'QUEUED'")
        print(f"  清理了 {cur.rowcount} 条排队中的任务")
    requests.post(f"{BASE}/ingestion/resume", headers=ha)

    print("\n" + "=" * 60)
    print(f"通过 {len(PASSED)} / 失败 {len(FAILED)}")
    for name in FAILED:
        print(f"  FAILED: {name}")
    print("=" * 60)


if __name__ == "__main__":
    main()
