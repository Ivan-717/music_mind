"""按需入库（③）的界面验证。

跑法（后端 8080 + vite 5173 都要在跑）：
    python logs/test_ingestion_ui.py

用系统 python（playwright 装在那儿），不是 data-pipeline 的 venv。
本机没装 chromium，用 channel="msedge" 借系统 Edge。
"""

import random
import string
import time

import requests
from playwright.sync_api import sync_playwright

API = "http://localhost:8080/api"
WEB = "http://localhost:5173"
PASSWORD = "test12345678"
HOT_URL = "https://music.163.com/playlist?id=3778678"

# 【筛选口径】不只是「MusicBrainz 上有这首歌」，还得「这首歌挂在某张 release 上」。
# 实测郑润泽《如果呢》《于是》：标题艺人精确命中，但 releases 为空（独立录音），
# 抓不了，会得到 NOT_FOUND——那是正确结果，但测不出「抓取成功」那条路径。
CANDIDATES = ["我不难过", "甲乙丙丁 (你我怎么两清)", "恋人", "两 难",
              "我怀念的", "出现又离开 (Live)", "开始懂了", "小半",
              "愿与愁", "刻在我心底的名字"]

PASSED, FAILED = [], []


def check(label, ok, extra=""):
    (PASSED if ok else FAILED).append(label)
    print(("  PASS " if ok else "  FAIL ") + label + (f"   {extra}" if extra else ""))


def main():
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    user = f"ui_{suffix}"

    # ---------- 准备数据（走接口，不手动造） ----------
    requests.post(f"{API}/auth/register", json={
        "username": user, "password": PASSWORD, "nickname": user,
        "email": f"{user}@example.com"}).raise_for_status()
    token = requests.post(f"{API}/auth/login",
                          json={"username": user, "password": PASSWORD}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    requests.post(f"{API}/import/playlist",
                  json={"url": HOT_URL, "favorite": False}, headers=headers).raise_for_status()
    import_id = requests.get(f"{API}/import/playlists", headers=headers).json()[0]["id"]

    rows = requests.get(f"{API}/import/playlists/{import_id}/tracks",
                        params={"page": 1, "size": 200}, headers=headers).json()["items"]
    unresolved = {r["title"]: r for r in rows if r["matchedTrackId"] is None}

    TARGET = next((t for t in CANDIDATES if t in unresolved), None)
    if TARGET is None:
        print("候选曲目都已入库，跳过本测试（换一首候选再跑，见脚本顶部的 CANDIDATES）")
        return

    print(f"准备完成：用户 {user}，歌单 {import_id}，目标《{TARGET}》"
          f"（本地库里还没有，会真的走一遍抓取）")

    console_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.on("console", lambda m: console_errors.append(m.text)
                if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(str(e)))

        # 登录态走 localStorage，省掉一次界面登录
        page.goto(f"{WEB}/login")
        page.evaluate(f"localStorage.setItem('mm_token', {token!r})")
        page.goto(f"{WEB}/my-playlist")
        page.wait_for_selector(".my-track-list li", timeout=20000)

        row = page.locator(".my-track-list li").filter(has_text=TARGET).first
        check("找到目标行", row.count() > 0)
        check("这一行显示「未收录」", "未收录" in row.locator(".state").inner_text(),
              row.locator(".state").inner_text())
        check("♡ 是禁用的", row.locator(".fav").is_disabled())
        check("有「入库」按钮", row.locator(".ingest").count() == 1)

        # ---------- 点入库 ----------
        row.locator(".ingest").click()
        page.wait_for_timeout(600)

        check("按钮变成「抓取中」", "抓取中" in row.locator(".ingest").inner_text(),
              row.locator(".ingest").inner_text())
        check("按钮被禁用", row.locator(".ingest").is_disabled())

        panel = page.locator(".ingest-panel")
        check("出现进度面板", panel.count() == 1)

        # 任务刚排上时还是 QUEUED，面板显示「准备中…」——worker 要等下一轮轮询
        # （1.5 秒）才领取。所以这里要等，不是马上断言
        panel_shows_target = False
        deadline = time.time() + 10
        while time.time() < deadline:
            if TARGET in panel.inner_text():
                panel_shows_target = True
                break
            page.wait_for_timeout(500)
        check("面板显示了正在抓的那首", panel_shows_target,
              panel.inner_text().replace("\n", " | ")[:120])

        # ---------- 等轮询把状态刷回来 ----------
        deadline = time.time() + 60
        flipped = False
        while time.time() < deadline:
            if "已收录" in row.locator(".state").inner_text():
                flipped = True
                break
            page.wait_for_timeout(900)

        check("行状态自动翻成「已收录」", flipped, row.locator(".state").inner_text())
        check("♡ 解禁了", not row.locator(".fav").is_disabled())
        check("「入库」按钮消失", row.locator(".ingest").count() == 0)

        # 抓取完成后 ♡ 真的要能用
        if not row.locator(".fav").is_disabled():
            row.locator(".fav").click()
            page.wait_for_timeout(800)
            check("♡ 点得动（变成已收藏）", row.locator(".fav").inner_text().strip() == "♥",
                  row.locator(".fav").inner_text())

        check("整单按钮出现（还有未收录的歌）",
              page.locator(".playlist-actions button", has_text="批量入库").count() == 1)

        page.screenshot(path="logs/ui-ingestion.png", full_page=False)
        browser.close()

    check("浏览器控制台没有报错", not console_errors,
          "; ".join(console_errors[:3]))

    print("\n" + "=" * 60)
    print(f"通过 {len(PASSED)} / 失败 {len(FAILED)}")
    for name in FAILED:
        print(f"  FAILED: {name}")
    print("=" * 60)


if __name__ == "__main__":
    main()
