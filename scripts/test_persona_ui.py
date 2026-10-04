"""Phase 6 的界面验证。跑法：python logs/test_persona_ui.py（要后端 8080 + vite 5173）"""
import random
import string
import time

import requests
from playwright.sync_api import sync_playwright

API, WEB, P = "http://localhost:8080/api", "http://localhost:5173", "test12345678"
HOT = "https://music.163.com/playlist?id=3778678"
PASSED, FAILED = [], []


def check(label, ok, extra=""):
    (PASSED if ok else FAILED).append(label)
    print(("  PASS " if ok else "  FAIL ") + label + (f"   {extra}" if extra else ""))


u = "pui_" + "".join(random.choices(string.ascii_lowercase, k=6))
requests.post(f"{API}/auth/register", json={"username": u, "password": P,
              "nickname": u, "email": u + "@example.com"}).raise_for_status()
token = requests.post(f"{API}/auth/login",
                      json={"username": u, "password": P}).json()["token"]
requests.post(f"{API}/import/playlist", json={"url": HOT, "favorite": False},
              headers={"Authorization": f"Bearer {token}"}).raise_for_status()

errors = []
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    pg = b.new_page(viewport={"width": 1400, "height": 1000})
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append(str(e)))

    pg.goto(f"{WEB}/login")
    pg.evaluate(f"localStorage.setItem('mm_token', {token!r})")
    pg.goto(f"{WEB}/persona")
    pg.wait_for_selector(".persona-bar", timeout=15000)

    check("页面打开、有生成按钮", pg.locator(".persona-bar button").count() == 1)
    check("没有报告时显示空状态", "还没有报告" in pg.inner_text("body"))

    pg.locator(".persona-bar button").click()
    pg.wait_for_timeout(2500)
    check("点完出现进度面板", pg.locator(".persona-progress").count() == 1)
    if pg.locator(".persona-progress").count():
        check("进度面板显示了已跑秒数", "正在分析" in pg.inner_text(".persona-progress"),
              pg.inner_text(".persona-progress").replace("\n", " ")[:60])

    # 等报告渲染出来（后端约 25-40 秒）
    ok = False
    deadline = time.time() + 150
    while time.time() < deadline:
        if pg.locator(".persona-dim").count() >= 3:
            ok = True
            break
        pg.wait_for_timeout(2000)

    check("报告渲染出来了", ok, f"维度块 {pg.locator('.persona-dim').count()} 个")
    check("推荐列表非空", pg.locator(".rec-list > li").count() >= 10,
          f"{pg.locator('.rec-list > li').count()} 条")
    check("每条推荐都有理由", pg.locator(".rec-list .reason").count() >= 10)

    text = pg.inner_text("body")
    check("页面上没有未渲染的占位符", "{" not in text and "}" not in text)

    check("有追问输入框", pg.locator(".ask-input").count() == 1)

    # 追问
    pg.fill(".ask-input", "我最常听哪个流派？")
    pg.locator(".ask-bar button").click()
    answered = False
    deadline = time.time() + 150
    while time.time() < deadline:
        if pg.locator(".msg-list li").count() >= 2:
            answered = True
            break
        pg.wait_for_timeout(2000)
    check("追问有回答", answered, f"消息 {pg.locator('.msg-list li').count()} 条")
    if answered:
        check("回答里没有未渲染的占位符", "{" not in pg.inner_text(".msg-list"))

    pg.screenshot(path="logs/ui-persona.png", full_page=False)
    b.close()

check("控制台没有报错", not errors, "; ".join(errors[:2]))
print("\n" + "=" * 60)
print(f"通过 {len(PASSED)} / 失败 {len(FAILED)}")
for x in FAILED:
    print("  FAILED:", x)
