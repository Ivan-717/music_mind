"""390px 移动端的「不溢出、能读、能点」验证。

跑法：python scripts/test_mobile_390.py（要后端 8080 + vite 5173）
判定：每页 scrollWidth <= 391（容差 1px）+ 抽一行断言歌名区宽度 > 80
（防「溢出修好了但歌名被压成 0」——那不算修好）。
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests
from playwright.sync_api import sync_playwright

API, WEB = "http://localhost:8080/api", "http://localhost:5173"
P = "test12345678"

token = requests.post(f"{API}/auth/login",
                      json={"username": "jj_cdfjsz", "password": P}).json()["token"]

PAGES = [
    ("search", "/search?q=%E5%91%A8%E6%9D%B0%E4%BC%A6", ".track-list li"),
    ("my-playlist", "/my-playlist", ".my-track-list li"),
    ("album-detail", "/albums/10", ".track-list li"),
    ("favorites", "/favorites", "h2"),
    ("explore", "/explore", ".explore-bar"),
    ("persona", "/persona", ".persona-bar"),
]

PASSED, FAILED = [], []


def check(label, ok, extra=""):
    (PASSED if ok else FAILED).append(label)
    print(("  PASS " if ok else "  FAIL ") + label + (f"   {extra}" if extra else ""))


with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    pg = b.new_context(viewport={"width": 390, "height": 844}).new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)[:120]))
    pg.goto(f"{WEB}/login")
    pg.evaluate(f"localStorage.setItem('mm_token', {token!r})")

    for name, path, sel in PAGES:
        try:
            pg.goto(f"{WEB}{path}")
            pg.wait_for_selector(sel, timeout=20000)
            pg.wait_for_timeout(1600)
            w = pg.evaluate("document.documentElement.scrollWidth")
            check(f"{name}: 不横向溢出", w <= 391, f"scrollWidth={w}")
            # 抽一行歌名区宽度（有列表的页面才查）
            nm = pg.evaluate("""() => {
              const el = document.querySelector('.track-list .name, .my-track-list .name');
              return el ? Math.round(el.getBoundingClientRect().width) : null;
            }""")
            if nm is not None:
                check(f"{name}: 歌名区可读（>80px）", nm > 80, f"{nm}px")
            pg.screenshot(path=f"logs/shots/m10-mobile-{name}.png")
        except Exception as e:
            check(f"{name}: 打开失败", False, str(e)[:80])

    check("无 console/page 错误", not errors, "; ".join(errors)[:100])
    b.close()

print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
sys.exit(1 if FAILED else 0)
