"""播放条封面的验收：**新会话**发消息（旧的推荐消息没有 album_id 字段）。"""
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
    pg.goto(f"{WEB}/explore")
    pg.wait_for_selector(".ask-input", timeout=20000)
    # 开新会话：确保页面上的推荐只有即将到来的这一批
    if pg.locator(".conv-select").count():
        pg.select_option(".conv-select", "")
        pg.wait_for_timeout(600)
    pg.fill(".ask-input", "再来几首安静的")
    pg.press(".ask-input", "Enter")
    pg.wait_for_selector(".rec-list.compact .play", timeout=120000)
    pg.click(".rec-list.compact .play")
    pg.wait_for_timeout(3200)
    ph = pg.locator(".mp-cover.placeholder").count()
    img = pg.locator("img.mp-cover, .mp-cover img").count()
    print(f"播放条：封面图={img} 占位符={ph}")
    pg.screenshot(path="logs/shots/player-cover.png")
    b.close()
