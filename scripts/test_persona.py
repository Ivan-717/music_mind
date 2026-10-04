"""Phase 6 端到端验证：生成报告 / 追问 / 历史读取 / 越权。

跑法（后端要在 8080 上）：
    data-pipeline/.venv/Scripts/python.exe logs/test_persona.py
"""
import random
import string
import sys
import time

import requests

API = "http://localhost:8080/api"
PASSWORD = "test12345678"
HOT_URL = "https://music.163.com/playlist?id=3778678"

PASSED, FAILED = [], []


def check(label, ok, extra=""):
    (PASSED if ok else FAILED).append(label)
    print(("  PASS " if ok else "  FAIL ") + label + (f"   {extra}" if extra else ""))


def setup_user(suffix):
    name = f"per_{suffix}"
    requests.post(f"{API}/auth/register", json={
        "username": name, "password": PASSWORD,
        "nickname": name, "email": f"{name}@example.com"}).raise_for_status()
    token = requests.post(f"{API}/auth/login",
                          json={"username": name, "password": PASSWORD}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def wait_run(h, run_id, limit=150):
    """轮询到结束。返回最后一次的响应体。"""
    deadline = time.time() + limit
    last = None
    while time.time() < deadline:
        last = requests.get(f"{API}/agent/runs/{run_id}", headers=h).json()
        if last.get("run", {}).get("status") in ("DONE", "FAILED"):
            return last
        time.sleep(3)
    return last


def main():
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    ha = setup_user(f"a{suffix}")
    hb = setup_user(f"b{suffix}")

    print("=== 准备：给 A 导入一个歌单（报告需要 ≥20 首曲目）===")
    r = requests.post(f"{API}/import/playlist",
                      json={"url": HOT_URL, "favorite": False}, headers=ha)
    check("导入歌单成功", r.status_code == 200, str(r.status_code))

    print("\n=== 1. 未登录 / 空数据 ===")
    r = requests.get(f"{API}/agent/status")
    check("未登录访问 → 401", r.status_code in (401, 403), str(r.status_code))

    r = requests.post(f"{API}/agent/report", headers=hb)
    check("B 没有曲目也能排队（守卫在 worker 里）", r.status_code == 202, str(r.status_code))
    b_run = r.json()["runId"]
    b_final = wait_run(hb, b_run, limit=90)
    check("B 的报告是 insufficient_data",
          b_final.get("report", {}).get("status") == "insufficient_data",
          str(b_final.get("report", {}).get("status")))
    check("B 的报告没有产出正文", not b_final.get("report") or b_final["report"].get("report_json") is None
          or b_final["report"].get("status") == "insufficient_data")

    print("\n=== 2. 生成报告 ===")
    started = time.time()
    r = requests.post(f"{API}/agent/report", headers=ha)
    check("POST /agent/report 返回 202", r.status_code == 202, str(r.status_code))
    body = r.json()
    check("返回 runId", isinstance(body.get("runId"), int), str(body))
    check("返回预估时长", body.get("estimateSeconds", 0) > 0, str(body.get("estimateSeconds")))

    run_id = body["runId"]
    final = wait_run(ha, run_id)
    elapsed = time.time() - started
    run = final.get("run", {})
    print(f"  耗时 {elapsed:.0f}s，状态 {run.get('status')}")
    check("报告生成成功（DONE）", run.get("status") == "DONE",
          run.get("errorMessage") or "")

    print("\n=== 3. 报告内容完整 ===")
    rep = final.get("report")
    check("run 响应里带了 report", rep is not None)
    if not rep:
        return
    import json
    payload = json.loads(rep["report_json"]) if isinstance(rep["report_json"], str) else rep["report_json"]
    check("有标题", bool(payload.get("headline", {}).get("title")),
          str(payload.get("headline", {}).get("title"))[:40])
    check("维度 ≥4", len(payload.get("dimensions") or []) >= 4,
          str(len(payload.get("dimensions") or [])))
    recs = payload.get("recommendations") or []
    check("推荐 ≥10 首", len(recs) >= 10, str(len(recs)))
    if recs:
        check("推荐带推荐理由", bool(recs[0].get("reason")), str(recs[0].get("reason"))[:50])
        check("推荐带『和你的关系』",
              bool((recs[0].get("relation_to_history") or {}).get("note")))
    check("有局限说明", len(payload.get("limitations") or []) >= 3)
    # 契约标记：Java 只搬运不解析，所以 report_json 必须是字符串
    check("report_json 是字符串（Java 未解析）", isinstance(rep["report_json"], str))

    print("\n=== 4. 刷新页面读回历史（新接口）===")
    report_id = rep["id"]
    r = requests.get(f"{API}/agent/reports/{report_id}", headers=ha)
    check("GET /agent/reports/{id} 返回 200", r.status_code == 200, str(r.status_code))
    if r.status_code == 200:
        detail = r.json()
        check("带正文", bool(detail.get("report", {}).get("report_json")))
        check("带追问历史（初始为空）", detail.get("messages") == [],
              str(len(detail.get("messages") or [])))

    print("\n=== 5. 追问 ===")
    r = requests.post(f"{API}/agent/ask",
                      json={"reportId": report_id, "question": "我最常听哪个流派？"},
                      headers=ha)
    check("POST /agent/ask 返回 202", r.status_code == 202, str(r.status_code))
    ask_run = r.json()["runId"]
    ask_final = wait_run(ha, ask_run, limit=150)
    check("追问完成（DONE）", ask_final.get("run", {}).get("status") == "DONE",
          ask_final.get("run", {}).get("errorMessage") or "")

    r = requests.get(f"{API}/agent/reports/{report_id}", headers=ha)
    msgs = r.json().get("messages") or []
    check("落到两条消息（问 + 答）", len(msgs) == 2, str(len(msgs)))
    if len(msgs) == 2:
        check("第一条是用户问的", msgs[0]["role"] == "user", msgs[0]["content"][:30])
        answer = msgs[1]["content"]
        check("第二条是回答且非空", msgs[1]["role"] == "assistant" and len(answer) > 10,
              answer[:60])
        # 【关键】回答里的数字要能对上报告 —— 这是「带证据回答」的意思
        check("回答里没有未渲染的占位符", "{" not in answer, answer[:60])

    print("\n=== 6. 越权 ===")
    r = requests.get(f"{API}/agent/reports/{report_id}", headers=hb)
    check("B 读 A 的报告 → 404", r.status_code == 404, str(r.status_code))
    r = requests.get(f"{API}/agent/runs/{run_id}", headers=hb)
    check("B 读 A 的运行 → 404", r.status_code == 404, str(r.status_code))
    r = requests.get(f"{API}/agent/reports/{report_id}")
    check("未登录读报告 → 401", r.status_code in (401, 403), str(r.status_code))

    print("\n=== 7. 报告列表 ===")
    r = requests.get(f"{API}/agent/reports", headers=ha)
    check("列表返回 200", r.status_code == 200, str(r.status_code))
    items = r.json()
    check("列表里有刚生成那份", any(x["id"] == report_id for x in items), str(len(items)))
    check("列表不含正文（几十 KB JSON 不能拉十份）",
          all("report_json" not in x for x in items))

    print("\n" + "=" * 60)
    print(f"通过 {len(PASSED)} / 失败 {len(FAILED)}")
    for name in FAILED:
        print(f"  FAILED: {name}")
    print("=" * 60)


if __name__ == "__main__":
    main()
