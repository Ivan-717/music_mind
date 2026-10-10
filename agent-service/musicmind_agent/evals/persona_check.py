"""画像评估驱动：对已落库的报告批量跑验证器 + 套路统计。

【为什么单独一个脚本】推荐有 run_eval（recall/lift/novelty），画像此前没有任何
例行评估 —— 2026-10-10 第一次系统评估是手工做的（逐份统计 41 份的标题），
这个脚本把那套手法固化：改 prompt / 改画像链路之后跑一次，看两个数：

    违规率  —— 验证器对每份报告跑全五层（需要重建该用户的 facts 仓）
    套路率  —— 标题命中「深夜/台灯/收音机」族的比例。**跨报告统计才有意义**：
               单看一份都贴切，横着看 21/41 全是同一族（prompt 1.4 加了
               禁用族 + 最近标题注入来治它，这个脚本就是它的回归检查）

跑法（不花钱，纯离线）：
    cd agent-service
    .venv/Scripts/python.exe -m musicmind_agent.evals.persona_check --limit 20
    .venv/Scripts/python.exe -m musicmind_agent.evals.persona_check --user 34
"""

from __future__ import annotations

import argparse
import json
import sys

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from musicmind_agent.db import get_connection  # noqa: E402
from musicmind_agent.tools import build_context, call, core_tool_names  # noqa: E402
from musicmind_agent.validate import validate  # noqa: E402

# 标题的「夜色电台」族 —— 2026-10-10 实测 41 份里「深夜」21 份、书桌/书房 17 份。
# 含变体（「灯光下」「夜幕」这种换汤不换药也要算进去）
CLICHE_WORDS = ("深夜", "夜色", "夜晚", "夜幕", "台灯", "灯光", "灯下",
                "收音机", "磁带", "书桌", "书房", "电台", "唱片机", "唱机")


def cliche_hits(title: str) -> list[str]:
    return [w for w in CLICHE_WORDS if w in (title or "")]


def main() -> int:
    parser = argparse.ArgumentParser(description="画像评估：验证器 + 套路统计")
    parser.add_argument("--limit", type=int, default=15, help="取最近 N 份（默认 15）")
    parser.add_argument("--user", type=int, default=None, help="只看某个用户")
    args = parser.parse_args()

    connection = get_connection()
    where = "WHERE user_id = %s" if args.user else ""
    params: tuple = (args.user,) if args.user else ()
    with connection.cursor() as cursor:
        cursor.execute(
            f"""SELECT id, user_id, headline, prompt_version, report_json
                FROM agent_report {where}
                ORDER BY id DESC LIMIT %s""",
            params + (args.limit,))
        rows = cursor.fetchall()

    ctx_cache: dict[int, object] = {}
    total_viol = total_checked = 0
    cliche_rows = repeated = 0
    seen_titles: dict[str, int] = {}

    print(f"{'id':>4} {'user':>5} {'版本':<12} {'违规':>4} {'套路':>4}  标题")
    for row in rows:
        report = row["report_json"]
        if isinstance(report, str):
            report = json.loads(report)

        # 同用户的 ctx 复用 —— 重建一次要跑一遍核心工具（无 LLM，但要查库）
        uid = row["user_id"]
        if uid not in ctx_cache:
            ctx = build_context(connection, uid)
            for name in core_tool_names():
                call(name, ctx)
            ctx_cache[uid] = ctx
        ctx = ctx_cache[uid]

        result = validate(report, ctx)
        n_viol = len(result.violations)
        total_viol += n_viol
        total_checked += result.checked

        hits = cliche_hits(row["headline"] or "")
        if hits:
            cliche_rows += 1
        title = row["headline"] or ""
        seen_titles[title] = seen_titles.get(title, 0) + 1
        if seen_titles[title] > 1:
            repeated += 1
        print(f"{row['id']:>4} {uid:>5} {row['prompt_version'] or '-':<12} "
              f"{n_viol:>4} {'★' if hits else '':>4}  {title}")

    n = len(rows)
    print()
    print(f"共 {n} 份：检查 {total_checked} 处，违规 {total_viol}"
          f"（{total_viol / max(total_checked, 1) * 100:.2f}%）")
    print(f"标题套路率 {cliche_rows}/{n}（{'/'.join(CLICHE_WORDS[:6])}… 族）；"
          f"完全重复 {repeated} 份")
    print("（历史的 prompt_version 多为 NULL —— 那是落库补丁之前的报告）")
    connection.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
