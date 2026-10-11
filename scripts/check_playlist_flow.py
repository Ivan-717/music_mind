"""全流程验收：新建空歌单 → 推荐行「加入歌单」→ 歌单里能看到这首。"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import requests
from playwright.sync_api import sync_playwright

API, WEB = "http://localhost:8080/api", "http://localhost:5173"
token = requests.post(f"{API}/auth/login",
                      json={"username": "jj_cdfjsz", "password": "test12345678"}).json()["token"]
NAME = "验收测试歌单"

with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    pg = b.new_context(viewport={"width": 1180, "height": 900}).new_page()
    pg.goto(f"{WEB}/login")
    pg.evaluate(f"localStorage.setItem('mm_token', {token!r})")

    # 1. 新建空歌单
    pg.goto(f"{WEB}/my-playlist?source=created")
    pg.wait_for_selector(".playlist-tabs, .empty", timeout=20000)
    if pg.locator(".create-row").count():
        # 空态：直接输入
        pg.fill(".create-row input", NAME)
        pg.click(".create-row button")
    else:
        pg.click(".tab-add")
        pg.fill(".playlist-tabs input", NAME)
        pg.press(".playlist-tabs input", "Enter")
    pg.wait_for_selector(f"text=「{NAME}」", timeout=15000)
    print("PASS 1: 新建空歌单成功")

    # 2. 回对话页，把第一首推荐加入这张歌单
    pg.goto(f"{WEB}/explore")
    pg.wait_for_selector(".rec-list.compact .addpl", timeout=30000)
    pg.click(".rec-list.compact .addpl")
    pg.wait_for_selector(".addpl-panel button", timeout=8000)
    first = pg.locator(".rec-list.compact .name").first.inner_text()
    pg.click(f".addpl-panel button:has-text('{NAME}')")
    pg.wait_for_selector(".addpl-done", timeout=8000)
    print(f"PASS 2: 《{first}》加入「{NAME}」→ ✓ 已加入")

    # 3. 歌单里确实有这首
    pg.goto(f"{WEB}/my-playlist?source=created&playlist=" + requests.get(
        f"{API}/playlists", headers={"Authorization": f"Bearer {token}"}).json()
        .__getitem__(0)["id"].__str__())
    pg.wait_for_selector(".my-track-list li", timeout=15000)
    line = pg.locator(".my-track-list .name").first.inner_text()
    assert first in line, f"歌单第一首 {line} != 加入的 {first}"
    print(f"PASS 3: 歌单里第一首 = 《{line}》，与加入的一致")
    b.close()
