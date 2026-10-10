"""M6 探索路径的界面验证（**不依赖 LLM**）。

跑法：python scripts/test_chat_path_ui.py（要后端 8080 + vite 5173）
做法：直接往 agent_conversation / agent_message 插一条带 path 的 assistant 消息，
打开 /explore 断言路径渲染出来。跑完把自己造的数据删掉。

【为什么要造数据】真跑一次「我想了解 Britpop」要 20-40 秒 + LLM 调用，
而且模型给不给 path 是随机的 —— 验收不能看运气（计划里的护栏 2）。
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import json
import random
import string

import pymysql
import requests
from playwright.sync_api import sync_playwright

sys.path.insert(0, "agent-service")
from musicmind_agent.db import get_connection  # noqa: E402

API, WEB = "http://localhost:8080/api", "http://localhost:5173"
P = "test12345678"

# 用固定测试号 jj_cdfjsz（有数据、密码已知）；没有就注册一个
username = "jj_cdfjsz"
r = requests.post(f"{API}/auth/login", json={"username": username, "password": P})
if not r.ok:
    username = "path_" + "".join(random.choices(string.ascii_lowercase, k=6))
    requests.post(f"{API}/auth/register", json={"username": username, "password": P,
                  "nickname": username, "email": username + "@example.com"}).raise_for_status()
    r = requests.post(f"{API}/auth/login", json={"username": username, "password": P})
token = r.json()["token"]

conn = get_connection()
try:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM app_user WHERE username=%s", (username,))
        uid = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO agent_conversation (user_id, title) VALUES (%s, %s)",
            (uid, "路径渲染测试（可删）"))
        conv_id = cur.lastrowid

        path_payload = {
            "answer": "Britpop 是九十年代英国的一股浪潮，从这几站走最清楚。",
            "recommendations": [],
            "fetch_proposals": [],
            "path": {
                "topic": "Britpop",
                "steps": [
                    {"order": 1, "name": "Oasis", "kind": "artist",
                     "release_mbid": None, "release_title": None, "release_artist": None,
                     "in_library": False, "why_here": "最直白的入口", "relation": None},
                    {"order": 2, "name": "Blur", "kind": "artist",
                     "release_mbid": "test-mbid-blur-0001",
                     "release_title": "The Great Escape", "release_artist": "Blur",
                     "in_library": False, "why_here": "对位面",
                     "relation": "和 Oasis 的英伦之战是理解这段的钥匙"},
                    {"order": 3, "name": "Pulp", "kind": "artist",
                     "release_mbid": None, "release_title": None, "release_artist": None,
                     "in_library": True, "why_here": "另一条更市井的线",
                     "relation": "比前两站更接近日常生活"},
                ],
            },
        }
        cur.execute(
            "INSERT INTO agent_message (conversation_id, role, content) VALUES (%s,'user',%s)",
            (conv_id, "我想了解 Britpop"))
        cur.execute(
            "INSERT INTO agent_message (conversation_id, role, content) VALUES (%s,'assistant',%s)",
            (conv_id, json.dumps(path_payload, ensure_ascii=False)))
    conn.commit()

    PASSED, FAILED = [], []
    def check(label, ok, extra=""):
        (PASSED if ok else FAILED).append(label)
        print(("  PASS " if ok else "  FAIL ") + label + (f"   {extra}" if extra else ""))

    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge", headless=True)
        pg = b.new_context(viewport={"width": 1400, "height": 1100}).new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)[:120]))
        pg.goto(f"{WEB}/login")
        pg.evaluate(f"localStorage.setItem('mm_token', {token!r})")
        pg.goto(f"{WEB}/explore")
        pg.wait_for_selector(".path-list li", timeout=25000)
        pg.wait_for_timeout(600)

        n = pg.locator(".path-list li").count()
        check("路径渲染出来且 ≥2 站", n >= 2, f"{n} 站")
        check("首站是 Oasis", pg.locator(".path-list .name").first.inner_text().strip() == "Oasis")
        check("关系行（连到上一站的那句话）在",
              "英伦之战" in pg.inner_text(".path-list"))
        check("已有的一站显示「已有」标签", pg.locator(".path-list .owned").count() >= 1)
        check("有 mbid 没的一站给「抓进库里」按钮", pg.locator(".path-list .grab").count() >= 1)
        pg.screenshot(path="logs/shots/explore-path.png")
        check("无 console/page 错误", not errors, "; ".join(errors)[:100])
        b.close()

    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
finally:
    # 清掉自己造的数据（消息先删，再删会话）
    with conn.cursor() as cur:
        cur.execute("DELETE FROM agent_message WHERE conversation_id=%s", (conv_id,))
        cur.execute("DELETE FROM agent_conversation WHERE id=%s", (conv_id,))
    conn.commit()
    conn.close()
    print("测试数据已清理")

sys.exit(1 if "FAILED" in globals() and FAILED else 0)
