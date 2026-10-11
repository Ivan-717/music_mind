"""对话页（深夜电台）改版后的截图快照。跑法：python scripts/shot_explore.py"""
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
    pg = b.new_context(viewport={"width": 1180, "height": 860}).new_page()
    pg.goto(f"{WEB}/login")
    pg.evaluate(f"localStorage.setItem('mm_token', {token!r})")
    pg.goto(f"{WEB}/explore")
    pg.wait_for_selector(".explore-head", timeout=20000)
    pg.wait_for_timeout(1800)
    pg.screenshot(path="logs/shots/explore-radio.png")
    b.close()
print("saved logs/shots/explore-radio.png")
