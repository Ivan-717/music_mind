"""对一份已生成的报告追问。

【为什么不复用 compose 那张图】那张图是「从零生成一份报告」的流程：
plan → probe → compose → validate → repair。追问只需要「带着上下文回答」，
重跑一遍是浪费（30 秒 + 一次完整 LLM 开销）。

【上下文从哪来】报告 JSON 的压缩版 + 报告生成时存下的 facts 快照。
**不是从 LangGraph 的 checkpoint 读** —— 那是库内部格式，换个版本就读不了。
追问的历史存在 agent_message 表里，那本来就是 UI 的数据源。
"""

from __future__ import annotations

import json

from musicmind_agent.evidence import SCOPE_ALL
from musicmind_agent.llm import LLMClient
from musicmind_agent.render import render_text
from musicmind_agent.tools import build_context, catalog
from musicmind_agent.tools.base import call as run_tool

ASK_SYSTEM = """你在回答用户对自己音乐人格报告的追问。

硬规则：

1. **只能用数据回答**。要提数字就写占位符 `{事实的key}`，渲染时替换成真值。
   自己编一个数字 = 回答作废。

   **占位符会连单位一起渲染出来**：`share`/`ratio` 渲染成 `68.3%`，
   `lift` 渲染成 `2.3 倍`。所以写「占 {key}」不要写成「占 {key} %」，
   写「是基准的 {key}」不要写成「是基准的 {key} 倍」——
   否则会渲染成「3.2 倍 倍」。这条在 compose 那边踩过一次，这里别再踩。

2. **只能引用「用户数据概览」里出现过的键，一个字母都不能改。**
   没有的键就是不存在，不要按命名规律拼。

3. 数据回答不了就直说「这套数据回答不了」。**不要用常识或者对歌手的印象凑答案** ——
   报告里的结论都有数据支撑，你的回答也要有。

4. 回答简短，2-4 句。用户是在看报告时顺手问一句，不是要一篇论文。

输出 JSON，两种形式之一：

要查东西（最多 3 个）：
{"calls": [{"tool": "工具名", "args": {{"参数": "值"}}}]}

直接回答：
{{"answer": "回答，数字写 {{fact.key}}", "used_tools": ["用过的工具名"]}}
"""

ASK_USER = """## 报告

{report}

## 用户数据概览（可以引用的事实）

{facts}

## 可用的工具（回答需要更多数据时用）

{catalog}

## 用户的追问

{question}
"""

# 一轮最多查几次。追问是「顺手问一句」，不是探索任务 ——
# 给太多轮会让一个简单问题等上半分钟
MAX_ASK_ROUNDS = 3


def ask(connection, user_id: int, report: dict, saved_facts: dict,
        question: str, provider: str,
        scope_kind: str = SCOPE_ALL, scope_ref: int | None = None) -> str:
    """回答一个问题，返回渲染后的回答文本。

    【ctx 必须按报告自己的范围重建】否则追问查出来的 facts 和报告里的数字
    对不上 —— 报告说「你有 432 首」，追问说「你有 490 首」，
    而那种错没有任何东西会报警。
    """
    ctx = build_context(connection, user_id, None, scope_kind, scope_ref)

    # 范围是按某张歌单、而那张歌单已经被删了。这时候硬答会比不答更糟 ——
    # 空集喂给模型，它会用常识凑一个答案出来
    if not ctx.tracks and scope_kind != SCOPE_ALL:
        return "这份报告的分析范围现在已经查不到曲目了（歌单可能已被删除），没法回答。"

    client = LLMClient(provider=provider)

    messages = [
        {"role": "system", "content": ASK_SYSTEM},
        {"role": "user", "content": ASK_USER.format(
            report=json.dumps(_slim(report), ensure_ascii=False),
            facts=json.dumps({k: v for k, v in sorted(saved_facts.items())},
                             ensure_ascii=False, default=str),
            catalog=json.dumps(catalog(), ensure_ascii=False, indent=1),
            question=question)},
    ]

    used: list[str] = []

    for _ in range(MAX_ASK_ROUNDS):
        raw, _resp = client.chat_json(messages)

        calls = raw.get("calls") or []
        if calls:
            blocks = []
            for req in calls[:3]:
                name = req.get("tool")
                if name not in {t["name"] for t in catalog()}:
                    continue
                result = run_tool(name, ctx, req.get("args") or {})
                used.append(name)
                blocks.append(
                    f"### {name}\n"
                    f"facts: {json.dumps(result.facts, ensure_ascii=False)}\n"
                    f"rows: {json.dumps(result.rows[:8], ensure_ascii=False)}")
            messages.append({"role": "assistant",
                             "content": json.dumps(raw, ensure_ascii=False)})
            messages.append({"role": "user", "content":
                             "## 工具结果\n" + "\n".join(blocks)
                             + "\n\n现在给出回答。"})
            continue

        text = raw.get("answer")
        if text:
            # 【渲染用合并后的事实仓】saved_facts 是报告生成时的快照
            # （build_context 里 facts 一开始是空的，要靠跑工具才填），
            # ctx.facts 是这次追问新查出来的。两边都要能用
            return render_text(text, {**saved_facts, **ctx.facts}, strict=False)

    return "这个问题我没能从数据里找到答案。"


def _slim(report: dict) -> dict:
    """报告压缩版。

    **别把整份塞进 prompt** —— 20 条推荐带理由就有几千 token，
    追问根本用不上（用户问的是「我最常听什么」这种），
    只会把事实仓和工具目录挤到窗口边缘。
    推荐只留前 5 条：用户追问时通常问的是「你推的这几首里第 2 首为什么」，
    留 5 条够用。
    """
    return {
        "headline": report.get("headline"),
        "dimensions": [
            {"dimension": d.get("dimension"), "summary": d.get("summary"),
             "claims": [c.get("text") for c in (d.get("claims") or [])]}
            for d in (report.get("dimensions") or [])
        ],
        "recommendations": [
            {"track_id": r.get("track_id"), "reason": r.get("reason")}
            for r in (report.get("recommendations") or [])[:5]
        ],
        "limitations": report.get("limitations"),
    }


def _load_json(value):
    return json.loads(value) if isinstance(value, str) else value


def answer_and_persist(connection, run_id: int) -> None:
    """从 agent_run 领一条 ask 任务，回答，写进 agent_message。"""
    from musicmind_agent.persist import load_run, mark_failed

    run = load_run(connection, run_id)
    if run is None:
        # 【抛，不能静默 return】静默返回的话 cli 照打 ASK_OK 退出码 0，
        # Java 认为成功、不做兜底，那条 run 永远停在 RUNNING。
        # 和 persist.run_and_persist 同一个坑
        raise RuntimeError(f"agent_run 里没有 id={run_id} 的行，什么都没跑")

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT report_json, facts_json, scope_kind, scope_ref "
            "FROM agent_report WHERE id=%s",
            (run["report_id"],))
        row = cursor.fetchone()

    if row is None:
        mark_failed(connection, run_id, "报告不存在")
        return

    text = ask(connection, run["user_id"],
               _load_json(row["report_json"]) or {},
               _load_json(row["facts_json"]) or {},
               run["question"], run["provider"],
               row["scope_kind"] or SCOPE_ALL, row["scope_ref"])

    with connection.cursor() as cursor:
        # 先记用户那句、再记回答 —— 顺序就是 UI 里的显示顺序
        cursor.execute(
            "INSERT INTO agent_message (report_id, run_id, role, content) "
            "VALUES (%s,%s,'user',%s)",
            (run["report_id"], run_id, run["question"]))
        cursor.execute(
            "INSERT INTO agent_message (report_id, run_id, role, content) "
            "VALUES (%s,%s,'assistant',%s)",
            (run["report_id"], run_id, text))
        cursor.execute(
            "UPDATE agent_run SET status='DONE', finished_at=NOW() WHERE id=%s",
            (run_id,))
    connection.commit()
