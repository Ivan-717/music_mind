"""命令行入口。

Phase 1 只有 tools 一个子命令：把工具层单独跑出来看，不经过任何 LLM。
这一步的验收标准就是「工具输出的数字能和手头的事实逐一对上」——
LLM 还没进来，所以对不上就是工具的错。

    python -m musicmind_agent.cli tools --user 34
    python -m musicmind_agent.cli tools --user 34 --tool genre_distribution
    python -m musicmind_agent.cli catalog

后续会加 report / ask 子命令（Phase 2 起）。
"""

from __future__ import annotations

import argparse
import json
import sys

from musicmind_agent.prompts.report import build_report

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from musicmind_agent.db import get_connection  # noqa: E402
from musicmind_agent.tools import REGISTRY, build_context, call, catalog, core_tool_names  # noqa: E402


def cmd_catalog(args: argparse.Namespace) -> int:
    for tier, label in [(0, "核心（每次必跑，不经 LLM 决定）"),
                        (1, "探针（LLM 从白名单选）"),
                        (2, "支撑（图内部 / 追问用）")]:
        print(f"\n=== Tier {tier} {label} ===")
        for entry in catalog(tier):
            params = f"  参数: {entry['params']}" if entry["params"] else ""
            print(f"  {entry['name']}")
            print(f"      {entry['description']}{params}")
    return 0


def cmd_tools(args: argparse.Namespace) -> int:
    connection = get_connection()
    try:
        ctx = build_context(connection, args.user)
    except Exception as e:
        print(f"构造上下文失败：{e}", file=sys.stderr)
        return 1

    if not ctx.tracks:
        print(f"用户 {args.user} 没有任何曲目（收藏或歌单已对齐）")
        return 1

    names = [args.tool] if args.tool else core_tool_names()
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        print(f"没有这些工具：{unknown}", file=sys.stderr)
        return 1

    print(f"用户 {args.user}：{len(ctx.tracks)} 首曲目")
    print("=" * 70)

    results = {}
    for name in names:
        result = call(name, ctx)
        results[name] = result
        if args.json:
            continue

        print(f"\n### {name}  ({result.elapsed_ms}ms)")
        if result.warnings:
            for w in result.warnings:
                print(f"  ⚠ {w}")
        print("  facts:")
        for key, value in result.facts.items():
            print(f"    {key} = {value}")
        if result.rows:
            print("  rows:")
            for row in result.rows[:12]:
                print("    " + "  ".join(f"{k}={v}" for k, v in row.items()))
        if result.evidence:
            print(f"  evidence: {len(result.evidence)} 条，例如 "
                  + "; ".join(f"{e['name']}({e['why']})" for e in result.evidence[:3]))
        cov = result.coverage
        if cov:
            print(f"  coverage: {cov.get('with_attribute')}/{cov.get('considered')} "
                  f"= {cov.get('ratio')}")

    # ctx 里登记的事实是全局仓，报告的数字引用就靠它
    print("\n" + "=" * 70)
    print(f"facts 仓共 {len(ctx.facts)} 条")

    if args.json:
        print(json.dumps(
            {name: r.as_dict() for name, r in results.items()},
            ensure_ascii=False, indent=2))
    elif args.pretty:
        print(json.dumps(ctx.facts, ensure_ascii=False, indent=2))

    connection.close()
    return 0

def cmd_report(args: argparse.Namespace) -> int:

    connection = get_connection()
    try:
        report = build_report(connection, args.user, args.provider)
    except Exception as e:
        print(f"生成失败：{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        connection.close()

    payload = {"report": report.rendered, "usage": report.usage}

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"已写入 {args.out}")
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    print(f"\n{report.usage['provider']}/{report.usage['model']}  "
          f"in={report.usage['tokens_in']} out={report.usage['tokens_out']}  "
          f"{report.usage['latency_ms']}ms", file=sys.stderr)
    return 0

def cmd_validate(args: argparse.Namespace) -> int:
    from musicmind_agent.tools import build_context, call, core_tool_names
    from musicmind_agent.validate import validate

    report = json.load(open(args.report, encoding="utf-8"))["report"]

    connection = get_connection()
    try:
        ctx = build_context(connection, args.user)
        # facts 仓要靠跑工具填满 —— 报告里的键就来自这里
        for name in core_tool_names():
            call(name, ctx)
        result = validate(report, ctx)
    finally:
        connection.close()

    print(result.summary())
    return 0 if result.ok else 1

def cmd_agent(args: argparse.Namespace) -> int:
    from musicmind_agent.graph import run_report

    connection = get_connection()
    try:
        final = run_report(connection, args.user, args.provider, args.out)
    except Exception as e:
        print(f"失败：{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        connection.close()

    usage = final.get("usage") or {}
    print(f"降级：{final.get('degraded', False)}   "
          f"修复轮次：{final.get('repair_count', 0)}   "
          f"探针：{final.get('probe_count', 0)}   "
          f"LLM 调用：{usage.get('llm_calls', 0)}")
    print(f"tokens in={usage.get('tokens_in', 0)} out={usage.get('tokens_out', 0)}")
    print()
    for step in final.get("trace", []):
        print(f"  {step['node']:16} {step.get('ms', 0):>6}ms  {step.get('note', '')}")

    if not final.get("rendered"):
        print("\n没有产出报告（数据不足或中途失败）")
        return 1
    return 0

def cmd_run(args: argparse.Namespace) -> int:
    """跑一次报告并落库。Java 子进程调的就是这个。

    【为什么要有它，而不是让 Java 直接调 `agent` 子命令】
    `agent` 把报告写文件、退出码表意，那是开发和调试用的。
    Java 需要的是「扔一个 run-id 进去，结果自己落库」——
    因为写库是 agent-service 的职责（见 schema-user.sql 的归属规则），
    Java 那边不该碰 agent_report。

    退出码：0 成功 / 1 失败。stdout 打 `RUN_OK <id>`，失败打 stderr。
    """
    from musicmind_agent.persist import mark_failed, run_and_persist

    connection = get_connection()
    try:
        report_id = run_and_persist(connection, args.run_id)
    except Exception as e:
        # 【失败也必须写回 run 行】否则队列里那条永远停在 RUNNING，
        # 前端一直转圈，唯一的恢复路径是重启 worker
        try:
            mark_failed(connection, args.run_id, f"{type(e).__name__}: {e}")
        except Exception:
            pass
        print(f"RUN_FAIL {args.run_id} {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        connection.close()

    print(f"RUN_OK {args.run_id} report={report_id}")
    return 0


def cmd_ask(args: argparse.Namespace) -> int:
    """对一份已生成的报告追问。同样的落库约定。"""
    from musicmind_agent.ask import answer_and_persist
    from musicmind_agent.persist import mark_failed

    connection = get_connection()
    try:
        answer_and_persist(connection, args.run_id)
    except Exception as e:
        try:
            mark_failed(connection, args.run_id, f"{type(e).__name__}: {e}")
        except Exception:
            pass
        print(f"ASK_FAIL {args.run_id} {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        connection.close()

    print(f"ASK_OK {args.run_id}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="musicmind", description="MusicMind Agent 服务")
    sub = parser.add_subparsers(dest="command", required=True)

    p_tools = sub.add_parser("tools", help="跑工具层（不经过 LLM）")
    p_tools.add_argument("--user", type=int, required=True)
    p_tools.add_argument("--tool", help="只跑这一个工具")
    p_tools.add_argument("--json", action="store_true", help="输出原始 JSON")
    p_tools.add_argument("--pretty", action="store_true", help="打印 facts 仓")
    p_tools.set_defaults(func=cmd_tools)

    p_cat = sub.add_parser("catalog", help="列出全部工具")
    p_cat.set_defaults(func=cmd_catalog)

    p_val = sub.add_parser("validate", help="验证一份已生成的报告")
    p_val.add_argument("--report", required=True, help="报告 JSON 的路径")
    p_val.add_argument("--user", type=int, required=True,
                       help="必须和生成报告时一致，否则 facts 仓对不上")
    p_val.set_defaults(func=cmd_validate)

    p_report = sub.add_parser("report", help="生成一份音乐人格报告")
    p_report.add_argument("--user", type=int, required=True)
    p_report.add_argument("--provider", default="deepseek", choices=["deepseek", "qwen"])
    p_report.add_argument("--out", help="把报告写到这个文件（默认打印到屏幕）")
    p_report.set_defaults(func=cmd_report)

    p_agent = sub.add_parser("agent", help="跑完整的 Agent 流程")
    p_agent.add_argument("--user", type=int, required=True)
    p_agent.add_argument("--provider", default="deepseek", choices=["deepseek", "qwen"])
    p_agent.add_argument("--out", help="产出目录（report.json + trace.jsonl）")
    p_agent.set_defaults(func=cmd_agent)
    p_run = sub.add_parser("run", help="跑一次报告并落库（Java 子进程调用）")
    p_run.add_argument("--run-id", type=int, required=True)
    p_run.set_defaults(func=cmd_run)

    p_ask = sub.add_parser("ask", help="对一份已生成的报告追问（Java 子进程调用）")
    p_ask.add_argument("--run-id", type=int, required=True)
    p_ask.set_defaults(func=cmd_ask)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":

    sys.exit(main())
