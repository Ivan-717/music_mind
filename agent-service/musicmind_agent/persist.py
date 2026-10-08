"""把报告写进 agent_report，并更新 agent_run 的状态。

【这个文件存在的唯一理由】agent-service 是 agent 侧表的唯一写者。
Java 只建 run 行、只读报告 —— 它既不解析也不写 report_json。
一旦 Java 开始写，报告 schema 一改就要两边同时改，而那种 bug
在生产上才现形。

【为什么 run 和 report 分开两张表】run 是「有人点了按钮」，
report 是「产出了一份东西」。追问也产生 run（kind='ask'），但不产生 report。
"""

from __future__ import annotations

import json
import time

from musicmind_agent.evidence import SCOPE_ALL, scope_label
from musicmind_agent.graph import run_report

# 【推荐条数别超过 20】
# 产品上没人读 50 条；技术上 50 条的输出会把 max_tokens 撑爆 ——
# 实测 8192 都在边界上，一半的折 JSON 被从中间截断，
# 报出来的错是「Unterminated string」，看起来像模型不会写 JSON。
RECO_COUNT = 20


def load_run(connection, run_id: int) -> dict | None:
    """按 id 读一条 run。

    【这里【不】claim】队列的串行化由 Java 的 AgentWorker 负责 ——
    它已经把行从 QUEUED 改成 RUNNING 才起的这个子进程。
    子进程再 claim 一次的话，条件「status='QUEUED'」永远不成立，
    结果是「子进程退出码 0、但什么都没产出」——
    实测就是这么挂的：RUN_OK 5 report=0，前端一直转圈。

    这也是为什么 ingest_release.py 那边可以 claim（那个队列全在 Java 侧，
    子进程只负责抓取），而这里不行（两边都想管同一条状态）。
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT * FROM agent_run WHERE id=%s", (run_id,))
        return cursor.fetchone()


def mark_failed(connection, run_id: int, message: str) -> None:
    """失败也要写回 run 行 —— 否则队列里那条永远停在 RUNNING，
    前端一直转圈，而唯一的恢复路径是重启 worker。"""
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE agent_run SET status='FAILED', error_message=%s, finished_at=NOW() "
            "WHERE id=%s", ((message or "")[:1000], run_id))
    connection.commit()


def run_and_persist(connection, run_id: int) -> int:
    """跑一次报告 → 落库 → 回填 run 行。返回 report_id。

    【run 行不存在要抛，不能返回 0】原来返回 0，而 cli 那边照打
    `RUN_OK <id> report=0` 退出码 0 —— Java 认为跑成了，不做兜底
    （finishFailed 只在子进程没跑成时调），那条 run 就停在 RUNNING，
    等 600 秒后被 requeueStale 打回队列，然后原样再挂一次，无限循环。

    「返回 0 让 caller 当失败处理」这句话原来的 docstring 里就写着，
    但没有任何 caller 这么做 —— 注释描述的是意图，不是实现
    """
    run = load_run(connection, run_id)
    if run is None:
        raise RuntimeError(f"agent_run 里没有 id={run_id} 的行，什么都没跑")

    # 【范围从 run 行读，不从调用方传】Java 建行时就写好了，子进程只认这一份。
    # 传参的话「Java 写的」和「Python 用的」会有两个来源，迟早对不上
    scope_kind = run.get("scope_kind") or SCOPE_ALL
    scope_ref = run.get("scope_ref")

    started = time.monotonic()
    final = run_report(connection, run["user_id"], run["provider"],
                       out_dir=None, reco_count=RECO_COUNT,
                       scope_kind=scope_kind, scope_ref=scope_ref)

    rendered = final.get("rendered") or {}
    facts = final.get("facts") or {}
    usage = final.get("usage") or {}

    # 【数据不足要走专门的状态】库里有两个用户只收藏了 1-2 首，
    # 硬编一份人格出来比不生成糟得多。前端看到这个状态要说清原因
    if usage.get("insufficient"):
        status = "insufficient_data"
    elif final.get("degraded"):
        status = "degraded"
    else:
        status = "ok"

    # 只留前端要显示的那部分覆盖率。整个 facts 仓有 100 多条，
    # 全塞进 data_scope 是噪声
    data_scope = {k: v for k, v in facts.items()
                  if k.startswith(("scope.", "coverage."))}

    # 「型」是代码算的，和 facts 一样是数据 —— 不经过 LLM、不进验证链。
    # 放在 persist 里而不是 graph 节点里：正常/降级两条路径都会经过这里，
    # 一处就全覆盖了
    from musicmind_agent.persona_types import score_types
    rendered["persona_type_candidates"] = score_types(facts)

    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO agent_report
                (user_id, status, scope_kind, scope_ref, scope_label,
                 report_json, facts_json, data_scope_json, headline,
                 llm_provider, llm_model, tokens_in, tokens_out, latency_ms)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (run["user_id"], status, scope_kind, scope_ref,
             # 【label 在这里定，不是入队时定】入队到出报告之间歌单可能已被改名。
             # 报告要的是「生成这一刻它叫什么」
             scope_label(connection, run["user_id"], scope_kind, scope_ref),
             json.dumps(rendered, ensure_ascii=False),
             json.dumps(facts, ensure_ascii=False, default=str),
             json.dumps(data_scope, ensure_ascii=False, default=str),
             (rendered.get("headline") or {}).get("title"),
             usage.get("provider"), usage.get("model"),
             usage.get("tokens_in"), usage.get("tokens_out"),
             int((time.monotonic() - started) * 1000)))
        report_id = cursor.lastrowid

        cursor.execute(
            "UPDATE agent_run SET status='DONE', report_id=%s, finished_at=NOW() WHERE id=%s",
            (report_id, run_id))
    connection.commit()
    return report_id
