"""推荐行表态（♡/加入歌单）+ 我的歌单新建入口 的验收截图。"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import requests
from playwright.sync_api import sync_playwright

API, WEB = "http://localhost:8080/api", "http://localhost:5173"
token = requests.post(f"{API}/auth/login",
                      json={"username": "jj_cdfjsz", "password": "test12345678"}).json()["token"]

os.makedirs("logs/shots", exist_ok=True)
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    pg = b.new_context(viewport={"width": 1180, "height": 900}).new_page()
    pg.goto(f"{WEB}/login")
    pg.evaluate(f"localStorage.setItem('mm_token', {token!r})")

    # 1. 对话页推荐行（有 ♡ 和「加入歌单」）
    pg.goto(f"{WEB}/explore")
    pg.wait_for_selector(".rec-list.compact .fav", timeout=30000)
    pg.wait_for_timeout(900)
    pg.screenshot(path="logs/shots/reco-actions.png")
    # 2. 点「加入歌单」→ 面板
    pg.click(".rec-list.compact .addpl")
    pg.wait_for_selector(".addpl-panel", timeout=8000)
    pg.wait_for_timeout(500)
    pg.screenshot(path="logs/shots/reco-addpl.png")
    print("面板内容:", pg.locator(".addpl-panel").inner_text()[:80].replace("\n", " / "))

    # 3. 我的歌单页
    pg.goto(f"{WEB}/my-playlist?source=created")
    pg.wait_for_selector(".playlist-tabs, .empty", timeout=20000)
    pg.wait_for_timeout(800)
    pg.screenshot(path="logs/shots/playlist-new.png")
    b.close()
print("saved 3 shots")
