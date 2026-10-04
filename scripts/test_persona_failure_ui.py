"""Phase 6 失败路径的界面验证。

跑法（后端 8080 + vite 5173 都要在跑）：
    python scripts/test_persona_failure_ui.py

【为什么单独一个脚本】test_persona_ui.py 走的是成功路径。
这个脚本用 Playwright 的路由拦截伪造后端响应，专测两条失败路径：

  A. 报告生成失败 → 用户必须看得见原因（Phase 6 验收标准第 6 条）
  B. 轮询连续失败 → 必须停下来并给出恢复入口，不能永久卡在「分析中…」

两条都不需要真的把后端弄挂 —— 要验的是【前端拿到失败响应之后的行为】，
在浏览器边界上伪造，测到的就是这个边界。
"""

import json
import random
import re
import string
import sys
import time

import requests
from playwright.sync_api import sync_playwright

# 【Windows 上必须显式 reconfigure】默认走 GBK，print 到控制台的中文全成乱码，
# 而这是个「看页面文字对不对」的测试 —— 输出乱码等于结果不可读
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

# 【为什么用正则不用 glob】两个坑：
#   1. axios 带查询串（?provider=deepseek），glob `**/api/agent/report` 匹配不上
#   2. `**/api/agent/report` 没有结尾锚，会把 /api/agent/reports 也吃掉
# 用正则把两个问题一起解决 —— 注意结尾的 $ 是必须的
RE_REPORT = re.compile(r"/api/agent/report(\?.*)?$")
RE_RUN = lambda run_id: re.compile(rf"/api/agent/runs/{run_id}(\?.*)?$")

API = "http://localhost:8080/api"
WEB = "http://localhost:5173"
PASSWORD = "test12345678"

FAIL_REASON = "LLMError: 两次都拿不到合法 JSON"

PASSED, FAILED = [], []


def check(label, ok, extra=""):
    (PASSED if ok else FAILED).append(label)
    print(("  PASS " if ok else "  FAIL ") + label + (f"   {extra}" if extra else ""))


def main():
    suffix = "".join(random.choices(string.ascii_lowercase, k=6))
    user = f"pfail_{suffix}"

    requests.post(f"{API}/auth/register", json={
        "username": user, "password": PASSWORD, "nickname": user,
        "email": f"{user}@example.com"}).raise_for_status()
    token = requests.post(f"{API}/auth/login",
                          json={"username": user, "password": PASSWORD}).json()["token"]

    console_errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.on("console", lambda m: console_errors.append(m.text)
                if m.type == "error" else None)
        page.on("pageerror", lambda e: console_errors.append(str(e)))

        page.goto(f"{WEB}/login")
        page.evaluate(f"localStorage.setItem('mm_token', {token!r})")

        # ============================================================
        # A. 报告生成失败 → 原因要看得见
        # ============================================================

        def report_ok(route, run_id):
            route.fulfill(status=202, content_type="application/json",
                          body=json.dumps({"runId": run_id, "estimateSeconds": 40}))

        def run_failed(route):
            route.fulfill(status=200, content_type="application/json", body=json.dumps({
                "run": {"id": 999001, "kind": "report", "status": "FAILED",
                        "errorMessage": FAIL_REASON, "question": None,
                        "reportId": None, "provider": "deepseek"},
                "report": None, "messages": [],
            }))

        print("=== A. 生成失败，原因要看得见 ===")
        page.route(RE_REPORT, lambda r: report_ok(r, 999001))
        page.route(RE_RUN(999001), run_failed)

        page.goto(f"{WEB}/persona")
        page.wait_for_selector(".persona-bar", timeout=15000)
        page.locator(".persona-bar button").click()
        page.wait_for_timeout(4000)

        text = page.inner_text("body")
        flat = " | ".join(text.split("\n"))[:150]

        check("失败原因显示出来了", FAIL_REASON in text, flat)
        # 原来 FAILED 和 degraded 共用一个条件，于是失败会说成「降级版本」
        check("没把它说成「降级版本」", "降级版本" not in text)
        # 原来是掉进空状态分支，用户以为是自己没点成功
        check("没显示「还没有报告」", "还没有报告" not in text)
        check("按钮恢复可点（能再试一次）",
              not page.locator(".persona-bar button").is_disabled())

        # ============================================================
        # B. 轮询连续失败 → 停下 + 恢复入口
        # ============================================================

        def run_broken(route):
            route.fulfill(status=500, content_type="application/json",
                          body='{"message":"boom"}')

        print("\n=== B. 轮询连续失败，要能恢复 ===")
        page.route(RE_REPORT, lambda r: report_ok(r, 999002))
        page.route(RE_RUN(999002), run_broken)

        page.locator(".persona-bar button").click()

        # 5 次失败 × 3 秒轮询 ≈ 12 秒，给到 45 秒余量
        stopped = False
        deadline = time.time() + 45
        while time.time() < deadline:
            if "失去联系" in page.inner_text("body"):
                stopped = True
                break
            page.wait_for_timeout(1000)

        check("连续失败后停下来了", stopped, flat)
        check("说明了是连接问题", stopped and "没连上" in page.inner_text("body"))
        reconnect = page.locator("button", has_text="重新连接")
        check("给了「重新连接」按钮", reconnect.count() == 1)

        # 点重连 → 面板要让位给进度条（状态真的重置了，不是只改了文案）
        if reconnect.count() == 1:
            reconnect.first.click()
            page.wait_for_timeout(500)
            check("点重连之后回到进度状态",
                  "失去联系" not in page.inner_text("body"))

        # 【反向断言】只有一次失败时【不能】停 —— 那正是这次要修的 bug
        def run_fail_once_then_ok(counter=[0]):
            def handler(route):
                counter[0] += 1
                if counter[0] == 1:
                    route.fulfill(status=500, content_type="application/json",
                                  body='{"message":"boom"}')
                else:
                    route.fulfill(status=200, content_type="application/json", body=json.dumps({
                        "run": {"id": 999003, "kind": "report", "status": "RUNNING",
                                "errorMessage": None, "question": None,
                                "reportId": None, "provider": "deepseek"},
                        "report": None, "messages": [],
                    }))
            return handler

        print("\n=== C. 只失败一次不能停（就是原来那个 bug）===")
        page.route(RE_REPORT, lambda r: report_ok(r, 999003))
        page.route(RE_RUN(999003), run_fail_once_then_ok())
        page.locator(".persona-bar button").click()
        page.wait_for_timeout(8000)          # 够跑 2-3 轮轮询

        body_c = page.inner_text("body")
        check("一次抖动之后还在轮询", "失去联系" not in body_c)
        check("进度面板还在", page.locator(".persona-progress").count() == 1)

        page.screenshot(path="logs/ui-persona-failure.png", full_page=False)
        browser.close()

    # 【要滤掉自己制造的 500】B 段故意让接口返 500，浏览器一定会把它记成
    # 控制台错误 —— 那是这个测试造出来的，不是页面的问题。
    # 不滤的话这条断言永远红，最后没人看它
    real_errors = [e for e in console_errors if "status of 500" not in e]
    check("浏览器控制台没有报错（滤掉自己注入的 500）", not real_errors,
          "; ".join(real_errors[:2]))

    print("\n" + "=" * 60)
    print(f"通过 {len(PASSED)} / 失败 {len(FAILED)}")
    for name in FAILED:
        print(f"  FAILED: {name}")
    print("=" * 60)


if __name__ == "__main__":
    main()
