"""指标。全部是纯函数 —— 好测、可复现。"""

from __future__ import annotations

import math
from collections import Counter


def recall_at_k(recommended: list[int], hidden: set[int], k: int) -> float:
    if not hidden:
        return 0.0
    return len(set(recommended[:k]) & hidden) / len(hidden)


def precision_at_k(recommended: list[int], hidden: set[int], k: int) -> float:
    top = recommended[:k]
    return len(set(top) & hidden) / len(top) if top else 0.0


def hit_rate_at_k(recommended: list[int], hidden: set[int], k: int) -> float:
    """至少命中一首的比例。recall 低但 hit_rate 高，说明「总能找到一点」。"""
    return 1.0 if set(recommended[:k]) & hidden else 0.0


def artist_recall(recommended_ids: list[int], hidden_ids: set[int],
                  artist_of: dict[int, int], k: int) -> float:
    """藏起来的【艺人】被找回的比例。

    【为什么它比曲目 recall 更接近「口味」】推荐一首同艺人的另一首歌，
    和推荐一首同流派不同艺人的歌，前者更容易命中曲目 recall，
    但后者才是「探索」。这个指标把两者分开。
    """
    hidden_artists = {artist_of.get(i) for i in hidden_ids} - {None}
    if not hidden_artists:
        return 0.0
    got = {artist_of.get(i) for i in recommended_ids[:k]} - {None}
    return len(got & hidden_artists) / len(hidden_artists)


def kl_divergence(p: Counter, q: Counter) -> float:
    """推荐集的流派分布 vs 用户真实分布。测「多样性有没有塌」。

    【为什么需要它】一个只推同一种流派的系统，recall 可能很高，
    但它没有在「推荐」，它只是在「复制你已有的」。KL 高说明偏离大。
    """
    p_total, q_total = sum(p.values()), sum(q.values())
    if not p_total or not q_total:
        return 0.0
    eps = 1e-9
    vocab = set(p) | set(q)
    return sum(
        (p.get(g, 0) / p_total + eps) * math.log(
            (p.get(g, 0) / p_total + eps) / (q.get(g, 0) / q_total + eps))
        for g in vocab
    )


def lift_over_random(recall: float, recall_random: float, ceiling: float) -> float:
    """相对随机的提升：0 = 和瞎猜一样，1 = 吃满上界。

    【为什么必须有它】random 推 k 首，光靠「藏歌占全库的比例」就能白拿命中 ——
    2026-10-08 实测 artist_cold k=50：random 3.3% > content 1.2%，
    绝对值在这个口径下已经没有分辨力了。上界已经被随机吃满时（denom <= 0）
    返回 0 —— 无从提升不是「无限好」。
    """
    denom = ceiling - recall_random
    if denom <= 0:
        return 0.0
    return (recall - recall_random) / denom


def novelty_at_k(recommended: list[int], known: set[int], k: int) -> float:
    """推的 k 首里「不在用户已知集合」的比例。

    【为什么和 recall 一起报】recall 高而 novelty 低 = 在复制用户已有的歌 ——
    旧口径 83% 那种数字就是泄露红利的形状。产品目标是推没听过的。
    注意 known 是【用户全部曲目】（含藏起来的那部分）——藏歌虽然不在画像里，
    但对用户来说仍然是「已经有的」。

    没传 k 截断的推荐（少于 k 条）时按实际条数算 —— 返回空集记 0。
    """
    top = recommended[:k]
    if not top:
        return 0.0
    return len([i for i in top if i not in known]) / len(top)