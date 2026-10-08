"""用户区分度：系统有没有在「认人」。

【为什么需要它】「能不能推回用户已有的歌」是个可疑的任务 —— 2026-10-08 实测：
库长大之后那个口径连 content 和 random 都分不开（见 docs/eval-results.md）。
但「给我推的东西应该更像我的、而不是另一个人的」是推荐器的第一性要求 ——
一测就死的信号。

做法（双向各测一次）：

    用 A 的曲库建画像 → 推 k 首 →
        对【A 的留出集】的 recall   vs   对【B 的留出集】的 recall
        Δ = 前者 − 后者，应当显著为正

两边都藏 20%（同折法、同折号）→ 基数口径可比。

【报告必须带两库重合率】两个账号若是同一个人（实测 vdev↔lizibin 重合 89%），
Δ 天然趋近 0 —— 那是「A/B 挑得不好」，不是系统不认人。
重合率超过 60% 时这一测的信号不可用，输出会自己标注。

跑法：
    .venv/Scripts/python.exe -m musicmind_agent.evals.discrimination --user-a 34 --user-b 132
"""

from __future__ import annotations

import argparse
import sys

# 【Windows 上必须自己转 UTF-8】控制台默认 GBK，print「✓」和中文直接抛
# UnicodeEncodeError（实测踩过好几次）。不指望调用方设环境变量
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from musicmind_agent.db import get_connection
from musicmind_agent.evidence import load_all_enriched
from musicmind_agent.evals import metrics, splits
from musicmind_agent.reco.recall import recommend
from musicmind_agent.tools import build_context

OVERLAP_WARN = 0.60      # 重合率超过它就明说「信号不可用」

# 【留出基数门槛】留出 12 首时，命中 0 和 1 的差别看起来是「Δ -0.4%」——
# 其实是**一首歌**的抽样噪声。基数不够就明说「不可判」，
# 不许把一个 0/12 vs 1/97 的噪声显示成「✗ 系统不认人」
MIN_HIDDEN = 30


def _run_direction(connection, all_tracks, target_id: int, other_id: int,
                   k: int, folds_n: int) -> list[tuple[float, float, int, int]]:
    """target 建画像推 k 首；返回每折的
    (对 target 留出的 recall, 对 other 留出的 recall, 两边留出基数)"""
    target = build_context(connection, target_id)
    other = build_context(connection, other_id)

    t_folds = splits.random_item_folds(target.tracks, folds_n)
    o_folds = splits.random_item_folds(other.tracks, folds_n)

    out = []
    for tf, of in zip(t_folds, o_folds):
        profile = [t for t in target.tracks if t.track_id not in tf.hidden_ids]
        ids = [it.track.track_id for it in recommend(profile, all_tracks, k)]
        # 两个用户的曲库有交集时：other 里没被藏的那部分已被 profile 排除
        # （不在候选池里），能命中的只有 other 的留出 —— 口径是干净的
        out.append((
            metrics.recall_at_k(ids, tf.hidden_ids, k),
            metrics.recall_at_k(ids, of.hidden_ids, k),
            len(tf.hidden_ids), len(of.hidden_ids),
        ))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="用户区分度测试")
    parser.add_argument("--user-a", type=int, default=34)
    parser.add_argument("--user-b", type=int, default=132)
    parser.add_argument("--k", type=int, default=20)
    parser.add_argument("--folds", type=int, default=5)
    args = parser.parse_args()

    connection = get_connection()
    try:
        all_tracks = load_all_enriched(connection)
        a = build_context(connection, args.user_a)
        b = build_context(connection, args.user_b)
        sa = {t.track_id for t in a.tracks}
        sb = {t.track_id for t in b.tracks}
        overlap = len(sa & sb) / len(sa | sb) if (sa | sb) else 0.0

        print(f"两库：A({args.user_a}) {len(sa)} 首 / B({args.user_b}) {len(sb)} 首 / "
              f"重合 {overlap * 100:.0f}%")
        if overlap > OVERLAP_WARN:
            print(f"  ⚠ 重合率 > {OVERLAP_WARN:.0%} —— 两个账号大概率是同一个人，"
                  f"这一测的信号不可用（换一对差异大的 A/B 再跑）")

        for label, (t_id, o_id) in {
            f"A→B ({args.user_a}→{args.user_b})": (args.user_a, args.user_b),
            f"B→A ({args.user_b}→{args.user_a})": (args.user_b, args.user_a),
        }.items():
            rows = _run_direction(connection, all_tracks, t_id, o_id, args.k, args.folds)
            selfs = [r for r, _, _, _ in rows]
            others = [o for _, o, _, _ in rows]
            min_hidden = min(min(ht, ho) for _, _, ht, ho in rows)
            delta = sum(selfs) / len(selfs) - sum(others) / len(others)

            if min_hidden < MIN_HIDDEN:
                print(f"{label}: 不可判 —— 留出基数太小（最小 {min_hidden} 首/折），"
                      f"Δ={delta:+.4f} 是抽样噪声，不是信号。换库大一些的用户对再跑")
                continue

            flag = "✓" if delta > 0 else "✗"
            print(f"{label}: 对自己留出 {sum(selfs)/len(selfs):.4f}  "
                  f"对他人的留出 {sum(others)/len(others):.4f}  "
                  f"Δ = {delta:+.4f}  {flag}"
                  + ("" if delta > 0 else "  ← 系统在推「像另一个人」的东西"))
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
