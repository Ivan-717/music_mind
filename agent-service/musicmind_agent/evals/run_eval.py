"""评估主驱动。

【为什么不放进 pytest】LLM 调用慢、花钱、有随机性。
混进单测的后果是没人愿意跑测试 —— 那是评估体系最常见的死法。
单测里只放切分、天花板、指标、baseline 这些纯函数的用例。
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from collections import Counter  # noqa: E402

from musicmind_agent.db import get_connection  # noqa: E402
from musicmind_agent.evidence import load_all_enriched  # noqa: E402
from musicmind_agent.tools import build_context  # noqa: E402
from musicmind_agent.evals import baselines, metrics, splits  # noqa: E402

RESULT_DIR = Path(__file__).resolve().parent / "results"


def run_deterministic(system: str, user_tracks, all_tracks, k: int) -> list[int]:
    fn = {
        "random": baselines.random_pick,
        "genre_prior": baselines.genre_prior,
        "artist_repeat": baselines.artist_repeat,
        "content": baselines.content,
    }[system]
    if system == "random":
        return fn(all_tracks, user_tracks, k)
    return fn(user_tracks, all_tracks, k)


def run_agent(connection, user_id: int, hidden_ids: set[int], provider: str, k: int):
    """跑完整图。返回推荐的 track_id 列表 + 运行统计。"""
    from musicmind_agent.graph import run_report

    final = run_report(connection, user_id, provider, None, hidden_ids, reco_count=k)
    rendered = final.get("rendered") or {}
    ids = [r.get("track_id") for r in rendered.get("recommendations", [])]
    return [i for i in ids if i][:k], final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", type=int, default=34)
    parser.add_argument("--systems", default="random,genre_prior,artist_repeat,content")
    parser.add_argument("--providers", default="deepseek")
    parser.add_argument("--folds", type=int, default=5)
    parser.add_argument("--k", type=int, default=20)
    parser.add_argument("--kind", default="artist_cold", choices=["artist_cold", "random_item"])
    args = parser.parse_args()

    systems = [s.strip() for s in args.systems.split(",") if s.strip()]
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]

    connection = get_connection()
    try:
        full = build_context(connection, args.user)
        all_tracks = load_all_enriched(connection)
        folds = (splits.artist_cold_folds if args.kind == "artist_cold"
                 else splits.random_item_folds)(full.tracks, args.folds)

        artist_of = {t.track_id: t.artist_id for t in all_tracks}
        rows = []

        for fold in folds:
            # 【画像用减掉藏歌之后的曲目；候选用全库】—— 这两个集合不一样，
            # 混用就是泄露。下面每个 baseline 都只拿 profile_tracks 建画像
            profile_tracks = [t for t in full.tracks if t.track_id not in fold.hidden_ids]

            ceil_ok, ceil_total = splits.ceiling(
                fold, all_tracks,
                {g for g, _ in Counter(
                    g for t in profile_tracks for g in t.genres).most_common(3)},
                {t.artist_id for t in profile_tracks if t.artist_id},
            )

            for system in systems:
                for provider in (providers if system == "agent_full" else ["-"]):
                    if system == "agent_full":
                        # 【单折失败不能拖垮整轮】LLM 偶发 JSON 解析失败是常态，
                        # 而一轮评估要跑几分钟、花真钱。失败就记一条失败，
                        # 继续跑下一折 —— 否则一次抖动就把前面的开销全废掉
                        try:
                            ids, final = run_agent(connection, args.user,
                                                   fold.hidden_ids, provider, args.k)
                        except Exception as e:
                            print(f"  {fold.name()[:24]:26} {system:14} {provider:9} "
                                  f"失败：{type(e).__name__}: {str(e)[:60]}")
                            rows.append({
                                "切分": fold.name(), "系统": system, "provider": provider,
                                "k": args.k, "失败": f"{type(e).__name__}",
                                f"recall@{args.k}": 0.0, "recall@5": 0.0, "recall@10": 0.0,
                                # 失败行也要有全部指标列 —— 汇总表按列名取，
                                # 少一个就 KeyError，在跑完几十分钟之后才炸
                                f"hit@{args.k}": 0.0, f"precision@{args.k}": 0.0,
                                f"artist_recall@{args.k}": 0.0,
                                "返回条数": 0, "recall上界": 0.0, "占上界比": 0.0,
                                "藏歌数": ceil_total, "可检索": ceil_ok,
                            })
                            continue
                        usage = final.get("usage") or {}
                        extra = {"降级": final.get("degraded"), "修复轮": final.get("repair_count"),
                                 "tokens_in": usage.get("tokens_in"), "tokens_out": usage.get("tokens_out")}
                    else:
                        ids = run_deterministic(system, profile_tracks, all_tracks, args.k)
                        extra = {}

                    k = args.k

                    # 【recall@k 的上界不是 1，是 min(可检索藏歌数, k) / 藏歌总数】
                    # 藏 138 首、只推 20 首时，recall@20 最高只能是 20/138 = 0.145，
                    # 哪怕系统完美无缺。拿 0.145 当分母报「recall 0.003」，
                    # 看起来像算法烂透了，其实分母用错了。
                    #
                    # 【为什么还要除以天花板】因为藏歌里可能有一部分在库里
                    # 根本没有同类，任何算法都拿不回来。两个上界取小的那个。
                    reachable = min(ceil_ok, k)
                    max_recall = reachable / ceil_total if ceil_total else 0

                    # 【「0 命中」和「什么都没返回」是两回事，不能都记 0】
                    # 实测撞到三种：降级会丢掉推荐整块（返回 0 条）、
                    # 模型没按指令给够条数（只给 5 条）、LLM 直接报错。
                    # 把它们和「认真推了但没推中」混成一个 0，
                    # 会得出「LLM 比基线差」这种**被工程问题污染的结论**——
                    # 实测 5 折里只有 1 折是真正可比的正面对决。
                    if not ids:
                        invalid = "降级丢光" if extra.get("降级") else "空结果"
                    elif len(ids) < k * 0.8:
                        invalid = f"只返回{len(ids)}条"
                    else:
                        invalid = ""

                    row = {
                        "切分": fold.name(), "系统": system,
                        "provider": provider, "k": k,
                        f"recall@{k}": round(metrics.recall_at_k(ids, fold.hidden_ids, k), 4),
                        # 【不同系统返回的条数可能不一样】agent_full 的 prompt 里
                        # 写死了「推荐 5 首」，而 content 返回 50 首 ——
                        # 拿 5 首去比 @50 是在比「谁返回得多」，不是比「谁推得准」。
                        # 加这两个小 k 的列，让两者在**都能满足的 k** 上可比
                        "recall@5": round(metrics.recall_at_k(ids, fold.hidden_ids, 5), 4),
                        "recall@10": round(metrics.recall_at_k(ids, fold.hidden_ids, 10), 4),
                        "返回条数": len(ids),
                        f"precision@{k}": round(metrics.precision_at_k(ids, fold.hidden_ids, k), 4),
                        f"hit@{k}": metrics.hit_rate_at_k(ids, fold.hidden_ids, k),
                        f"artist_recall@{k}": round(
                            metrics.artist_recall(ids, fold.hidden_ids, artist_of, k), 4),
                        "藏歌数": ceil_total,
                        "可检索": ceil_ok,
                        "recall上界": round(max_recall, 4),
                        "占上界比": round(
                            metrics.recall_at_k(ids, fold.hidden_ids, k) / max_recall, 4
                        ) if max_recall else 0,
                        "有效": "否" if invalid else "是",
                        "无效原因": invalid,
                        **extra,
                    }
                    rows.append(row)
                    print(f"  {row['切分'][:24]:26} {system:14} {provider:9} "
                          f"recall@{k}={row[f'recall@{k}']:.3f}  "
                          f"上界={max_recall:.3f}  占上界={row['占上界比']*100:5.1f}%  "
                          f"hit={row[f'hit@{k}']}")
    finally:
        connection.close()

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = RESULT_DIR / stamp
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "results.csv", "w", encoding="utf-8", newline="") as f:
        # 【fieldnames 要取所有行的并集】agent_full 的行多出「降级 / tokens」
        # 这几列，只按第一行取会 ValueError。这个错在评估跑完最后一步才炸，
        # 前面几分钟的 LLM 调用全白费
        fieldnames = list(dict.fromkeys(k for row in rows for k in row))
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n写进 {out/'results.csv'}")

    # 汇总：每个系统跨折的均值，并带上天花板
    k = args.k
    print(f"\n按系统汇总（跨折均值，k={k}）：")
    print(f"  {'系统':16}{'recall':>9}{'上界':>9}{'占上界':>9}{'hit':>7}")
    for system in systems:
        subset = [r for r in rows if r["系统"] == system]
        if not subset:
            continue
        # 【只统计有效的折】把「降级丢光了推荐」「只返回 5 条」「LLM 报错」
        # 和「认真推了没推中」混在一起平均，会得出被工程问题污染的结论
        valid = [r for r in subset if r.get("有效", "是") == "是"]
        skipped = len(subset) - len(valid)
        if not valid:
            print(f"  {system:16} 没有有效折（{skipped} 折无效）")
            continue
        n = len(valid)
        avg = sum(r[f"recall@{k}"] for r in valid) / n
        bound = sum(r["recall上界"] for r in valid) / n
        hit = sum(r[f"hit@{k}"] for r in valid) / n
        pct = f"{avg / bound * 100:.1f}%" if bound else "—"
        note = f"  （{skipped} 折无效，已排除）" if skipped else ""
        print(f"  {system:16}{avg:9.4f}{bound:9.4f}{pct:>9}{hit:7.2f}{note}")
    print()
    print("【怎么读】recall@k 的上界不是 1 —— 藏 N 首只推 k 首时上界是 min(可检索, k)/N。")
    print("          「占上界」才是能跨 k、跨切分比较的那个数。")
    return 0


if __name__ == "__main__":
    sys.exit(main())