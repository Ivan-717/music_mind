"""对话页推荐卡片（行内试听按钮）的验收截图。跑法：python scripts/shot_reco.py"""
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
    pg.goto(f"{WEB}/explore")
    pg.wait_for_selector(".ask-input", timeout=20000)
    pg.fill(".ask-input", "推荐几首安静的")
    pg.press(".ask-input", "Enter")
    # 等回答出现 + 推荐卡片带播放按钮（LLM 要跑 20-40 秒）
    pg.wait_for_selector(".rec-list.compact .play", timeout=120000)
    pg.wait_for_timeout(1200)
    pg.screenshot(path="logs/shots/explore-reco-play.png")
    b.close()
print("saved logs/shots/explore-reco-play.png")
