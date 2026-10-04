"""「我的歌单」页轮询容错的界面验证。

跑法（后端 8080 + vite 5173 都要在跑）：
    python scripts/test_ingestion_poll_ui.py

和 test_persona_failure_ui.py 同一个套路：用 Playwright 的路由拦截伪造
/api/ingestion/status 的响应，专测轮询断线时的行为。

【要验的 bug】原来 refreshStatus 的 catch 里直接 stopPoll() ——
一次网络抖动就永久停表，而 ingestion 停在最后一次成功的值上，
hasActiveJob 恒真，那一行永远显示「抓取中」、♡ 和入库按钮永久禁用，
没有报错也没有恢复入口。
"""

import json
import random
import re
import string
import sys
import time

import requests
from playwright.sync_api import sync_playwright

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

API = "http://localhost:8080/api"
WEB = "http://localhost:5173"
PASSWORD = "test12345678"

# 队列里有活的状态。hasActiveJob 看的就是 currentJobId / queueCount
ACTIVE = {"paused": False, "queueCount": 3, "currentJobId": 77,
          "currentLabel": "正在抓：《测试曲目》", "activeTrackRowIds": [],
          "recentJobs": []}

RE_STATUS = re.compile(r"/api/ingestion/status(\?.*)?$")

PASSED, FAILED = [], []


def check(label, ok, extra=""):
    (PASSED if ok else FAILED).append(label)
    print(("  PASS " if ok else "  FAIL ") + label + (f"   {extra}" if extra else ""))


def fulfill(route, body, status=200):
    route.fulfill(status=status, content_type="application/json",
                  body=json.dumps(body, ensure_ascii=False))


def main():
    suffix = "".join(random.choices(string.ascii_lowercase, k=6))
    user = f"poll_{suffix}"
    requests.post(f"{API}/auth/register", json={
        "username": user, "password": PASSWORD, "nickname": user,
        "email": f"{user}@example.com"}).raise_for_status()
    token = requests.post(f"{API}/auth/login",
                          json={"username": user, "password": PASSWORD}).json()["token"]
    # 需要一张歌单，不然「我的歌单」页是空的
    requests.post(f"{API}/import/playlist",
                  json={"url": "https://music.163.com/playlist?id=3778678",
                        "favorite": False},
                  headers={"Authorization": f"Bearer {token}"}).raise_for_status()

    console_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.on("console", lambda m: console_errors.append(m.text)
                if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(str(e)))

        page.goto(f"{WEB}/login")
        page.evaluate(f"localStorage.setItem('mm_token', {token!r})")

        # ============================================================
        # A. 只失败一次 → 不能停表，后续状态要照常刷出来
        # ============================================================
        calls = {"n": 0}

        def flaky(route):
            calls["n"] += 1
            if calls["n"] == 1:
                fulfill(route, {"message": "boom"}, 500)
            else:
                fulfill(route, ACTIVE)

        print("=== A. 只失败一次不能停表（就是原来那个 bug）===")
        page.route(RE_STATUS, flaky)
        page.goto(f"{WEB}/my-playlist")
        page.wait_for_selector(".my-track-list li", timeout=25000)

        # 第一次 tick 就失败；要等下一轮（3 秒）才知道有没有续上
        shown = False
        deadline = time.time() + 20
        while time.time() < deadline:
            if "正在抓" in page.inner_text("body"):
                shown = True
                break
            page.wait_for_timeout(1000)

        check("一次失败之后轮询还在继续（拿到后续状态了）", shown,
              f"status 被请求了 {calls['n']} 次")
        check("没有误报「失去联系」", "失去联系" not in page.inner_text("body"))

        # ============================================================
        # B. 连续失败 → 停下、说清楚、给恢复入口
        # ============================================================
        print("\n=== B. 连续失败要能看见并能恢复 ===")
        page.route(RE_STATUS, lambda r: fulfill(r, {"message": "boom"}, 500))
        page.reload()
        page.wait_for_selector(".my-track-list li", timeout=25000)

        # 5 次 × 3 秒 ≈ 12 秒，给到 45 秒余量
        stopped = False
        deadline = time.time() + 45
        while time.time() < deadline:
            if "失去联系" in page.inner_text("body"):
                stopped = True
                break
            page.wait_for_timeout(1000)

        check("连续失败后停下来了", stopped)
        check("说明了是连接问题并交代抓取仍在跑",
              stopped and "后台照常跑" in page.inner_text("body"))
        reconnect = page.locator("button", has_text="重新连接")
        check("给了「重新连接」按钮", reconnect.count() == 1)

        # 点重连 → 换回正常响应 → 面板要让位给真实进度
        if reconnect.count() == 1:
            page.unroute(RE_STATUS)
            page.route(RE_STATUS, lambda r: fulfill(r, ACTIVE))
            reconnect.first.click()
            back = False
            deadline = time.time() + 20
            while time.time() < deadline:
                body = page.inner_text("body")
                if "正在抓" in body and "失去联系" not in body:
                    back = True
                    break
                page.wait_for_timeout(1000)
            check("点重连之后恢复成真实进度", back)

        page.screenshot(path="logs/ui-ingestion-poll.png", full_page=False)
        browser.close()

    real_errors = [e for e in console_errors if "status of 500" not in e]
    check("浏览器控制台没有报错（滤掉自己注入的 500）", not real_errors,
          "; ".join(real_errors[:2]))

    print("\n" + "=" * 60)
    print(f"通过 {len(PASSED)} / 失败 {len(FAILED)}")
    for name in FAILED:
        print(f"  FAILED: {name}")
    print("=" * 60)


if __name__ == "__main__":
    main()
