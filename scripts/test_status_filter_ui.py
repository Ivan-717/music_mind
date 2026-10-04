"""已收录 / 未收录 筛选的界面验证。跑法：python logs/test_status_filter_ui.py"""
import random, string, time, requests
from playwright.sync_api import sync_playwright

API, WEB, P = "http://localhost:8080/api", "http://localhost:5173", "test12345678"
PASSED, FAILED = [], []

def check(label, ok, extra=""):
    (PASSED if ok else FAILED).append(label)
    print(("  PASS " if ok else "  FAIL ") + label + (f"   {extra}" if extra else ""))

u = "fltui_" + "".join(random.choices(string.ascii_lowercase, k=6))
requests.post(f"{API}/auth/register", json={"username": u, "password": P,
              "nickname": u, "email": u + "@example.com"}).raise_for_status()
token = requests.post(f"{API}/auth/login", json={"username": u, "password": P}).json()["token"]
h = {"Authorization": f"Bearer {token}"}
requests.post(f"{API}/import/playlist", json={"url": "https://music.163.com/playlist?id=3778678",
              "favorite": False}, headers=h).raise_for_status()

errors = []
with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    pg = b.new_page(viewport={"width": 1400, "height": 900})
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    pg.on("pageerror", lambda e: errors.append(str(e)))

    pg.goto(f"{WEB}/login")
    pg.evaluate(f"localStorage.setItem('mm_token', {token!r})")
    pg.goto(f"{WEB}/my-playlist")
    pg.wait_for_selector(".my-track-list li", timeout=20000)

    tabs = pg.locator(".status-tabs button")
    check("出现三个筛选标签", tabs.count() == 3, str(tabs.count()))
    labels = [tabs.nth(i).inner_text().split()[0] for i in range(3)]
    check("标签是 全部/已收录/未收录", labels == ["全部", "已收录", "未收录"], str(labels))
    counts = [tabs.nth(i).locator(".count").inner_text() for i in range(3)]
    check("三个数字都对得上", int(counts[0]) == int(counts[1]) + int(counts[2]),
          f"{counts}")

    def states():
        return pg.locator(".my-track-list .state").all_inner_texts()

    def click(i):
        tabs.nth(i).click()
        pg.wait_for_timeout(900)

    click(1)   # 已收录
    s = states()
    check("「已收录」下全是已收录", s and all(x == "已收录" for x in s), f"{len(s)} 行")
    note_before = [tabs.nth(i).locator(".count").inner_text() for i in range(3)]

    click(2)   # 未收录
    s = states()
    check("「未收录」下没有已收录的", s and "已收录" not in s, f"{len(s)} 行")
    note_after = [tabs.nth(i).locator(".count").inner_text() for i in range(3)]
    check("切换筛选后三个数字不变", note_before == note_after, f"{note_before} -> {note_after}")
    check("当前标签高亮", "active" in (tabs.nth(2).get_attribute("class") or ""))

    click(0)   # 全部
    check("「全部」下行数 ≥ 未收录的行数", len(states()) >= len(s),
          f"{len(states())} vs {len(s)}")

    pg.screenshot(path="logs/ui-status-filter.png", full_page=False)
    b.close()

check("控制台没有报错", not errors, "; ".join(errors[:3]))
print("\n" + "=" * 60)
print(f"通过 {len(PASSED)} / 失败 {len(FAILED)}")
for x in FAILED: print("  FAILED:", x)
