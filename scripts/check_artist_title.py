"""验证：截断的歌手名 hover 挂全名 title；不截断时不留 title。

机制在 App.vue 的全局委托（mouseover → .artist 截断判断）。
这个脚本在专辑详情页的 150px 歌手列上构造超长名来触发。
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import requests
from playwright.sync_api import sync_playwright

API, WEB = "http://localhost:8080/api", "http://localhost:5173"
SEL = ".track-list .artist"
token = requests.post(f"{API}/auth/login",
                      json={"username": "jj_cdfjsz", "password": "test12345678"},
                      timeout=10).json()["token"]

with sync_playwright() as p:
    b = p.chromium.launch(channel="msedge", headless=True)
    pg = b.new_context(viewport={"width": 1180, "height": 900}).new_page()
    pg.goto(f"{WEB}/login", timeout=30000)
    pg.evaluate(f"localStorage.setItem('mm_token', {token!r})")
    pg.goto(f"{WEB}/albums/857", timeout=30000)
    pg.wait_for_selector(SEL, timeout=25000)

    # 1) 构造超长名（必然截断），真实 hover → title 应为全名
    pg.evaluate(f"""() => {{
      const el = document.querySelector('{SEL}');
      el.dataset.orig = el.textContent;
      el.textContent = '超长测试歌手名甲乙丙丁戊己庚辛壬癸子丑寅卯辰巳午未申酉戌亥';
    }}""")
    pg.hover(SEL)
    pg.wait_for_timeout(400)
    t1 = pg.evaluate(f"document.querySelector('{SEL}').title")
    print(("PASS 1" if "超长测试歌手" in t1 else "FAIL 1")
          + f": 截断时 hover → title=「{t1[:22]}…」", flush=True)

    # 2) 换回短名 + 派发 mouseover（等价于鼠标移回）→ title 应被清掉
    t2 = pg.evaluate(f"""() => {{
      const el = document.querySelector('{SEL}');
      el.textContent = '短名字';
      el.dispatchEvent(new MouseEvent('mouseover', {{bubbles: true}}));
      return el.title;
    }}""")
    print(("PASS 2" if not t2 else "FAIL 2")
          + f": 不截断时 → title=「{t2}」", flush=True)
    pg.evaluate(f"() => {{ const el = document.querySelector('{SEL}'); el.textContent = el.dataset.orig; }}")
    b.close()
