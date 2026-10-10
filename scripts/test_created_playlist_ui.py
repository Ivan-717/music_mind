"""自建歌单闭环的界面验证（**不依赖 LLM**）。

跑法：python scripts/test_created_playlist_ui.py（要后端 8080 + vite 5173）
覆盖：造歌单 → 「我建的」tab 能看见 → 改名 → 移除一首 → 深链直开 → 删除 → 清理。
同时回归「导入的」tab 原样工作。
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests
from playwright.sync_api import sync_playwright

API, WEB = "http://localhost:8080/api", "http://localhost:5173"
P = "test12345678"

token = requests.post(f"{API}/auth/login",
                      json={"username": "jj_cdfjsz", "password": P}).json()["token"]
H = {"Authorization": f"Bearer {token}"}

# 造数据：从专辑 10 的曲目里抽 6 首建两张歌单（不走 LLM，不走探索页）
tracks = requests.get(f"{API}/albums/10/tracks", headers=H, params={"releaseId": 7}).json()
ids = [t["trackId"] for t in tracks[:6]]
assert len(ids) >= 6, f"专辑曲目不够造数据：{len(ids)}"

created = []
for name in ("UI 测试歌单甲", "UI 测试歌单乙"):
    r = requests.post(f"{API}/playlists/from-tracks",
                      json={"name": name, "trackIds": ids[:3]}, headers=H)
    assert r.ok, r.text
    created.append(r.json()["id"])
print(f"造了两张歌单: {created}")

PASSED, FAILED = [], []


def check(label, ok, extra=""):
    (PASSED if ok else FAILED).append(label)
    print(("  PASS " if ok else "  FAIL ") + label + (f"   {extra}" if extra else ""))


try:
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        pg = b.new_context(viewport={"width": 1400, "height": 1100}).new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)[:120]))
        pg.on("dialog", lambda d: d.accept())          # confirm 一律确定
        pg.goto(f"{WEB}/login")
        pg.evaluate(f"localStorage.setItem('mm_token', {token!r})")

        # ---- 深链直达我建的（存歌单跳过来的那条路）----
        pg.goto(f"{WEB}/my-playlist?source=created&playlist={created[0]}")
        pg.wait_for_selector(".my-track-list li", timeout=25000)
        pg.wait_for_timeout(800)

        check("「我建的」tab 选中", "active" in (pg.locator(".status-tabs button").nth(1)
                                              .get_attribute("class") or ""))
        check("两张自建歌单的 pills 都在", pg.locator(".playlist-tabs .tab").count() == 2)
        check("深链选中的是甲",
              "UI 测试歌单甲" in pg.locator(".playlist-head .section-title").inner_text())
        check("曲目 3 首", pg.locator(".my-track-list li").count() == 3)
        check("行内有 ♡", pg.locator(".my-track-list .fav").count() == 3)
        check("有试听的给了 ▶（没试听给同宽空位）",
              pg.locator(".my-track-list .play").count() == 3)
        pg.screenshot(path="logs/shots/created-playlist.png")

        # ---- 改名 ----
        pg.click("text=改名")
        pg.fill(".rename-input", "UI 测试歌单甲·改")
        pg.keyboard.press("Enter")
        pg.wait_for_timeout(800)
        check("改名生效", "改" in pg.locator(".playlist-head .section-title").inner_text())

        # ---- 移除一首 ----
        pg.locator(".my-track-list .drop").first.click()
        pg.wait_for_timeout(800)
        check("移除一首后剩 2", pg.locator(".my-track-list li").count() == 2)

        # ---- 切到乙（【按 data-playlist-id 选】——按名字会被乱码/子串坑） ----
        pg.locator(f'.playlist-tabs .tab[data-playlist-id="{created[1]}"]').click()
        pg.wait_for_timeout(900)
        title_yi = pg.locator(".playlist-head .section-title").inner_text()
        check("切到乙", "乙" in title_yi, title_yi)

        # ---- 删除乙 ----
        pg.click("text=删除歌单")
        pg.wait_for_timeout(900)
        check("删除后只剩一张", pg.locator(".playlist-tabs .tab").count() == 1)
        created.remove(created[1])      # 乙已经删了，清理时不用再删

        # ---- 回归：导入的 tab ----
        # 注意：导入歌单的切换 pills 只在 >1 张时显示（v-if="playlists.length > 1"），
        # jj 只有 1 张 —— 所以断言「导入区的曲目内容渲染出来」，不是断言 pills
        pg.locator(".status-tabs button").first.click()
        pg.wait_for_timeout(1800)
        body = pg.inner_text("body")
        check("「导入的」tab 回归：导入歌单区渲染出来",
              ("已收录" in body) or ("未收录" in body) or pg.locator(".my-track-list li").count() >= 1,
              f"行数 {pg.locator('.my-track-list li').count()}")
        check("无 console/page 错误", not errors, "; ".join(errors)[:100])
        b.close()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
finally:
    for pid in created:                  # 清理（乙已删会 404，无妨）
        requests.delete(f"{API}/playlists/{pid}", headers=H)
    print("测试歌单已清理")

sys.exit(1 if FAILED else 0)
