"""点推荐卡片的播放按钮，验证真能出声（播放条出现）。"""
import sys, os
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
    pg.wait_for_selector(".rec-list.compact .play", timeout=30000)
    pg.click(".rec-list.compact .play")
    pg.wait_for_timeout(3500)
    err = pg.locator("text=试听暂时不可用").count()
    bar = pg.locator(".mini-player, .player-bar, [class*=mini]").count()
    btn = pg.locator(".rec-list.compact .play.on").count()
    print(f"错误提示={err} 播放条元素={bar} 按钮点亮={btn}")
    pg.screenshot(path="logs/shots/explore-playing.png")
    b.close()
