"""延迟测量：连跑 N 次，统计 p50 / p95。

【为什么要真跑】这个数字决定 Phase 6 走同步接口还是 202+轮询，
   而同步/异步决定了前端的整个交互形态。估是不行的。
"""
import json, statistics, sys, time
from musicmind_agent.db import get_connection
from musicmind_agent.graph import run_report

provider = sys.argv[1] if len(sys.argv) > 1 else "deepseek"
runs = int(sys.argv[2]) if len(sys.argv) > 2 else 10

times, rows = [], []
for i in range(runs):
    connection = get_connection()
    started = time.monotonic()
    try:
        final = run_report(connection, 34, provider, None)
    except Exception as e:
        print(f"  第 {i+1} 次失败：{type(e).__name__}: {e}")
        continue
    finally:
        connection.close()
    elapsed = time.monotonic() - started
    times.append(elapsed)
    usage = final.get("usage") or {}
    v = [x for x in final.get("violations", []) if x.get("severity") == "error"]
    rows.append({
        "秒": round(elapsed, 1),
        "探针轮": final.get("probe_count", 0),
        "修复轮": final.get("repair_count", 0),
        "降级": final.get("degraded", False),
        "残留违规": len(v),
        "tokens_out": usage.get("tokens_out", 0),
    })
    print(f"  第 {i+1} 次：{elapsed:.1f}s  探针 {rows[-1]['探针轮']} 轮  "
          f"修复 {rows[-1]['修复轮']} 轮  降级 {rows[-1]['降级']}  "
          f"out={rows[-1]['tokens_out']}")

if times:
    ordered = sorted(times)
    p50 = statistics.median(ordered)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    print()
    print(f"{provider} 跑 {len(times)} 次：")
    print(f"  p50 = {p50:.1f}s    p95 = {p95:.1f}s    min={min(times):.1f}s  max={max(times):.1f}s")
    print(f"  降级次数：{sum(1 for r in rows if r['降级'])}")
    json.dump(rows, open(f"out/latency-{provider}.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
