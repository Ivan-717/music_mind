"""验收：专辑名链接跳转 + 专辑/收藏页的「加入歌单」键。"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import requests
from playwright.sync_api import sync_playwright

API, WEB = "http://localhost:8080/api", "http://localhost:5173"
token = requests.post(f"{API}/auth/login",
                      json={"username": "jj_cdfjsz", "password": "test12345678"}).json()["token"]

with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    pg = b.new_context(viewport={"width": 1180, "height": 900}).new_page()
    pg.goto(f"{WEB}/login")
    pg.evaluate(f"localStorage.setItem('mm_token', {token!r})")

    # 1. 导入歌单：专辑名 → 点击 → 跳专辑详情页
    pg.goto(f"{WEB}/my-playlist")
    pg.wait_for_selector("a.album", timeout=20000)
    n = pg.locator("a.album").count()
    album_text = pg.locator("a.album").first.inner_text().strip()
    pg.click("a.album")
    pg.wait_for_url("**/albums/*", timeout=10000)
    print(f"PASS 1: 专辑链接 {n} 个，点「{album_text}」→ {pg.url.split('/')[-1] and pg.url}")
    pg.wait_for_timeout(1200)
    pg.screenshot(path="logs/shots/album-link-jump.png")

    # 2. 专辑详情页的「加入歌单」键
    pg.wait_for_selector(".track-list", timeout=15000)
    apl = pg.locator(".track-list .addpl").count()
    print(f"PASS 2: 专辑详情页「加入歌单」键 ×{apl}" if apl else "FAIL 2: 没有加入歌单键")
    pg.click(".track-list .addpl")
    pg.wait_for_selector(".addpl-panel", timeout=8000)
    print("PASS 2b: 面板可弹出")
    pg.screenshot(path="logs/shots/album-addpl.png")

    # 3. 收藏页
    pg.goto(f"{WEB}/favorites")
    pg.wait_for_selector(".fav-list", timeout=15000)
    fa = pg.locator(".fav-list .addpl").count()
    print(f"PASS 3: 收藏页「加入歌单」键 ×{fa}" if fa else "FAIL 3: 收藏页没有加入歌单键")
    pg.screenshot(path="logs/shots/fav-addpl.png")
    b.close()
