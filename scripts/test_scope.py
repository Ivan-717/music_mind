"""分析范围（按歌单 / 按收藏 / 全部）的端到端验证。

跑法（后端要在 8080 上）：
    data-pipeline/.venv/Scripts/python.exe scripts/test_scope.py

【为什么会花 LLM 额度】范围错了是不会报错的 —— 只会生成一份「数字看着对、
其实是另一批歌」的报告。所以真正的验收必须真的生成一份，
再拿 data_scope 里的曲目数去对。
全程 2 次报告 + 1 次追问。
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
    r = requests.post(f"{API}/auth/register", json={
        "username": name, "password": PASSWORD, "nickname": name,
        "email": f"{name}@example.com"})
    assert r.status_code == 201, r.text
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


def data_scope(body):
    rep = body.get("report") or {}
    raw = rep.get("data_scope_json")
    return json.loads(raw) if isinstance(raw, str) else (raw or {})


def generate(h, **params):
    r = requests.post(f"{API}/agent/report", params=params, headers=h)
    if r.status_code != 202:
        return None, r
    return wait_run(h, r.json()["runId"]), None


def main():
    suffix = "".join(random.choices(string.ascii_lowercase, k=6))
    ha = register(f"sc_a_{suffix}")
    hb = register(f"sc_b_{suffix}")

    print("=== 0. 准备：A 导入一张歌单 ===")
    requests.post(f"{API}/import/playlist",
                  json={"url": HOT_URL, "favorite": False}, headers=ha).raise_for_status()
    imports = requests.get(f"{API}/import/playlists", headers=ha).json()
    imp = imports[0]
    import_id = imp["id"]
    print(f"  歌单 id={import_id} 《{imp['playlistName']}》"
          f" 导入 {imp['trackCount']} 首")

    print("\n=== 1. 列表带可分析曲目数 ===")
    check("返回里有 matchedCount", imp.get("matchedCount") is not None, str(imp.get("matchedCount")))
    check("matchedCount <= trackCount",
          (imp.get("matchedCount") or 0) <= imp["trackCount"],
          f"{imp.get('matchedCount')} / {imp['trackCount']}")
    check("matchedCount 就是已对齐数（不是导入数）",
          imp.get("matchedCount") != imp["trackCount"] or imp["trackCount"] == 0,
          f"{imp.get('matchedCount')} vs {imp['trackCount']}")

    print("\n=== 2. 越权：B 用 A 的歌单排报告 → 404 ===")
    r = requests.post(f"{API}/agent/report",
                      params={"scopeKind": "playlist", "scopeRef": import_id}, headers=hb)
    check("B 排 A 的歌单 → 404", r.status_code == 404, str(r.status_code))

    r = requests.post(f"{API}/agent/report",
                      params={"scopeKind": "playlist", "scopeRef": 999999}, headers=ha)
    check("不存在的歌单 → 404（和越权返回一样）", r.status_code == 404, str(r.status_code))

    r = requests.post(f"{API}/agent/report", params={"scopeKind": "playlist"}, headers=ha)
    check("playlist 但不给 scopeRef → 400", r.status_code == 400, str(r.status_code))

    print("\n=== 3. 按歌单生成报告（真跑一次 LLM）===")
    body, err = generate(ha, scopeKind="playlist", scopeRef=import_id)
    check("报告生成成功", err is None and body.get("run", {}).get("status") == "DONE",
          str(err and err.text[:80]) or str(body.get("run", {}).get("errorMessage")))
    if err is not None or body.get("run", {}).get("status") != "DONE":
        return

    rep = body["report"]
    scope = data_scope(body)
    print(f"  status={rep['status']} scope_label={rep.get('scope_label')} "
          f"画幅曲目={scope.get('scope.tracks')}")

    check("scope_label 是歌单名", rep.get("scope_label") == imp["playlistName"],
          str(rep.get("scope_label")))
    check("scope_kind 落库为 playlist", rep.get("scope_kind") == "playlist",
          str(rep.get("scope_kind")))
    check("画像曲目数 = 这张歌单的对齐数（不是全部曲库）",
          scope.get("scope.tracks") == imp.get("matchedCount"),
          f"报告说 {scope.get('scope.tracks')}，歌单说 {imp.get('matchedCount')}")

    report_id = rep["id"]

    print("\n=== 4. 追问也锚定同一个范围（再跑一次 LLM）===")
    r = requests.post(f"{API}/agent/ask",
                      json={"reportId": report_id, "question": "这份分析里一共用了多少首歌？"},
                      headers=ha)
    check("追问已受理", r.status_code == 202, str(r.status_code))
    body2 = wait_run(ha, r.json()["runId"])
    check("追问完成", body2.get("run", {}).get("status") == "DONE",
          str(body2.get("run", {}).get("errorMessage")))

    msgs = body2.get("messages") or []
    answer = msgs[-1]["content"] if msgs else ""
    print(f"  问：这份分析里一共用了多少首歌？")
    print(f"  答：{answer[:120]}")
    check("回答里没有未渲染的占位符", "{" not in answer)
    # 【这是这一步的关键】追问如果不带范围重建 context，它会答出「全部」的数
    check("追问用的是这个范围的数字（不是全部曲库的）",
          str(scope.get("scope.tracks")) in answer,
          f"报告范围是 {scope.get('scope.tracks')}，回答：{answer[:80]}")

    print("\n=== 5. 范围写进了 run 行（不是只靠参数传）===")
    runs = requests.get(f"{API}/agent/status", headers=ha).json()["recentRuns"]
    rep_run = next((x for x in runs if x.get("kind") == "report"), None)
    check("run 行带 scopeKind/scopeRef",
          rep_run and rep_run.get("scopeKind") == "playlist"
          and rep_run.get("scopeRef") == import_id,
          str(rep_run and {k: rep_run.get(k) for k in ("scopeKind", "scopeRef")}))

    print("\n" + "=" * 60)
    print(f"通过 {len(PASSED)} / 失败 {len(FAILED)}")
    for name in FAILED:
        print(f"  FAILED: {name}")
    print("=" * 60)


if __name__ == "__main__":
    main()
